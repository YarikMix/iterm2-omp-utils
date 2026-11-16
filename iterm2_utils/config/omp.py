"""Profile-scoped native YAML addresses; Python owns filesystem CAS and journaling.

The bundled Bun helper is a pure transform, not `omp config`: native config
initialization can migrate/write storage. No settings or values enter argv/errors.
"""
import json
import os
from pathlib import Path
import re
import stat

from .. import state
from ..commands import Runner
from ..models import OmpProfile, OmpEdit

LIMIT = 1024 * 1024
HELPER = Path(__file__).resolve().parents[2]/'runtime/omp_config.ts'
SETTINGS = frozenset({'terminal.programStatus', 'completion.notify', 'error.notify'})


def same(left, right):
    """JSON equality must not conflate false/0 or true/1."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return left == right


def value_snapshot(value):
    if (not isinstance(value, dict) or set(value) != {'exists', 'value'} or
            type(value['exists']) is not bool or not value['exists'] and value['value'] is not None):
        raise ValueError('Invalid native address value')
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise ValueError('Invalid native address value') from None
    return value


def validate_resource(resource):
    """Validate persisted addresses without executing a parser or touching files."""
    from ..omp_profile import profile_name
    loc = resource['locator']
    if (set(loc) != {'key','profile','agent_dir','mode'} or
            not isinstance(loc['agent_dir'], str) or not Path(loc['agent_dir']).is_absolute() or
            not Path(resource['target']).is_absolute() or
            type(loc['mode']) is not int or not 0 <= loc['mode'] <= 0o7777 or
            not isinstance(loc['key'], str) or
            loc['profile'] is not None and (not isinstance(loc['profile'], str) or profile_name(loc['profile']) != loc['profile'])):
        raise ValueError('Invalid native omp receipt address')
    if resource['kind'] == 'omp_setting':
        if loc['key'] not in SETTINGS:
            raise ValueError('Unsupported native omp setting')
    elif not re.fullmatch(r'(?:app|tui)\.[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*', loc['key']):
        raise ValueError('Invalid native omp action')
    for field in ('before','installed'):
        snapshot = value_snapshot(resource[field])
        if not snapshot['exists'] or snapshot['value'] is None:
            continue
        value = snapshot['value']
        if resource['kind'] == 'omp_setting':
            valid = type(value) is bool if loc['key'] == 'terminal.programStatus' else value in ('on','off')
        else:
            chords = value if isinstance(value,list) else [value]
            valid = len(chords) <= 64 and all(isinstance(chord,str) and chord.strip() and len(chord) <= 100 and not re.search(r'[\x00-\x1f]',chord) for chord in chords)
        if not valid:
            raise ValueError('Invalid native omp receipt value')


def storage(profile: OmpProfile, kind: str) -> Path:
    if not isinstance(profile, OmpProfile) or not profile.agent_dir.is_absolute() or kind not in {'setting', 'binding'}:
        raise ValueError('Invalid native omp address')
    stem = 'config' if kind == 'setting' else 'keybindings'
    for suffix in ('.yml', '.yaml'):
        path = profile.agent_dir/(stem + suffix)
        if path.exists() or path.is_symlink():
            return path
    # Creating an empty YAML file would mask native migrations of existing JSON
    # configuration. Do not perform those migrations or silently change scope.
    legacy = ('settings.json', 'settings.jsonc') if kind == 'setting' else ('keybindings.json',)
    if any((profile.agent_dir/name).exists() for name in legacy):
        raise ValueError('Native configuration migration required before editing')
    return profile.agent_dir/(stem + '.yml')


def _bytes(path: Path) -> bytes | None:
    try:
        with path.open('rb') as source:
            raw = source.read(LIMIT + 1)
    except FileNotFoundError:
        return None
    except OSError:
        raise ValueError('Native omp configuration is unreadable') from None
    if len(raw) > LIMIT:
        raise ValueError('Native omp configuration exceeds size limit')
    return raw


def transform(raw: bytes | None, kind: str, key: str, runner: Runner, *, value=None, expected=None, operation='read') -> dict:
    try:
        source = (raw or b'').decode('utf-8', errors='strict')
        request = {'source': source, 'kind': kind, 'key': key, 'operation': operation}
        if operation == 'patch':
            request.update(value=value_snapshot(value), expected=value_snapshot(expected))
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False)
        if len(payload.encode()) > 2 * LIMIT:
            raise ValueError()
        env = {'PATH': os.environ.get('PATH', os.defpath), 'HOME': str(HELPER.parent),
               'BUN_RUNTIME_TRANSPILER_CACHE_PATH': '0', 'DO_NOT_TRACK': '1'}
        response = runner.run(['bun', '--no-install', '--no-env-file', '--config=/dev/null', str(HELPER)],
                              timeout=5, stdin=payload, env=env)
        if response.returncode or len(response.stdout.encode()) > 2 * LIMIT:
            raise ValueError()
        result = json.loads(response.stdout)
        if not isinstance(result, dict) or 'error' in result:
            raise ValueError()
        if operation == 'bindings':
            if set(result) != {'bindings'} or not isinstance(result['bindings'], dict):
                raise ValueError()
        elif operation == 'read':
            if set(result) != {'value'}:
                raise ValueError()
            value_snapshot(result['value'])
        elif set(result) != {'source', 'value'} or not isinstance(result['source'], str) or len(result['source'].encode()) > LIMIT or not same(result['value'], value):
            raise ValueError()
        return result
    except Exception:
        raise ValueError('Native omp configuration helper failed') from None


def read_address(profile, kind, key, runner, *, path=None):
    selected = storage(profile, kind).resolve()
    if path is not None and selected != Path(path):
        raise ValueError('Native omp configuration location changed')
    return transform(_bytes(selected), kind, key, runner)['value']


def read_setting(profile: OmpProfile, key: str, runner: Runner) -> dict:
    return read_address(profile, 'setting', key, runner)


def read_binding(profile: OmpProfile, action: str, runner: Runner) -> dict:
    """Local presence, never a fabricated inherited value in a receipt inverse."""
    return read_address(profile, 'binding', action, runner)


def _inherited_profile(profile):
    if profile.name is None:
        return None
    directory = profile.agent_dir
    if directory.name != 'agent' or directory.parent.name != profile.name or directory.parent.parent.name != 'profiles':
        raise ValueError('Named omp profile location cannot establish inheritance')
    return OmpProfile(None, directory.parent.parent.parent/'agent')


def effective_binding(profile: OmpProfile, action: str, runner: Runner) -> dict:
    local = read_binding(profile, action, runner)
    inherited = _inherited_profile(profile)
    return read_binding(inherited, action, runner) if not local['exists'] and inherited is not None else local


def _binding_guards(profile, action, value, runner):
    """Read inherited remaps without migration; reject cross-action collisions.

    Guards are checked again during staging, including byte generations, so a
    default-profile writer cannot silently invalidate the selected remap.
    """
    sources, merged = [], {}
    inherited = _inherited_profile(profile)
    for scope in ([inherited] if inherited else []) + [profile]:
        path = storage(scope, 'binding').resolve()
        raw = _bytes(path)
        merged.update(transform(raw, 'binding', action, runner, operation='bindings')['bindings'])
        sources.append((scope, path, raw))
    if value['exists']:
        wanted = value['value']
        chords = wanted if isinstance(wanted, list) else [] if wanted is None else [wanted]
        normalized = {chord.strip().lower() for chord in chords if isinstance(chord, str)}
        for other, keys in merged.items():
            alternatives = keys if isinstance(keys, list) else [] if keys is None else [keys]
            if other != action and normalized.intersection(key.strip().lower() for key in alternatives):
                raise ValueError('Selected binding conflicts with another native action')
    return sources


def set_address(profile, kind, key, value, runner, *, expected, path=None):
    value_snapshot(value); value_snapshot(expected)
    selected = storage(profile, kind).resolve()
    if path is not None and selected != Path(path):
        raise ValueError('Native omp configuration location changed')
    raw = _bytes(selected)
    guards = _binding_guards(profile, key, value, runner) if kind == 'binding' else []
    result = transform(raw, kind, key, runner, value=value, expected=expected, operation='patch')['source'].encode()
    if result == raw:
        return
    mode = stat.S_IMODE(selected.stat().st_mode) if selected.exists() else 0o600
    def check():
        if storage(profile, kind).resolve() != selected or _bytes(selected) != raw:
            raise ValueError('Concurrent native configuration edit')
        for scope, original_path, original in guards:
            if storage(scope, 'binding').resolve() != original_path or _bytes(original_path) != original:
                raise ValueError('Concurrent inherited binding edit')
    selected.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.durable_write(selected, result, mode, before_replace=check)


def set_setting(profile: OmpProfile, key: str, value: dict, runner: Runner, *, expected: dict) -> None:
    set_address(profile, 'setting', key, value, runner, expected=expected)


def set_binding(profile: OmpProfile, action: str, value: dict, runner: Runner, *, expected: dict) -> None:
    set_address(profile, 'binding', action, value, runner, expected=expected)


def _edit(profile, kind, key, value, runner, owner):
    value_snapshot(value)
    path = storage(profile, kind).resolve()
    raw = _bytes(path)
    before = transform(raw, kind, key, runner)['value']
    transform(raw, kind, key, runner, value=value, expected=before, operation='patch')
    if kind == 'binding':
        _binding_guards(profile, key, value, runner)
    return OmpEdit(profile, kind, key, before, value, owner, path)


def setting_edit(profile: OmpProfile, key: str, value: dict, runner: Runner, *, owner: str) -> OmpEdit:
    """Pure builder: capture just one nested native setting, no writes."""
    return _edit(profile, 'setting', key, value, runner, owner)


def binding_edit(profile: OmpProfile, action: str, value: dict, runner: Runner, *, owner: str = 'shortcuts') -> OmpEdit:
    """Pure builder: action IDs are literal YAML keys, never dotted paths."""
    return _edit(profile, 'binding', action, value, runner, owner)
