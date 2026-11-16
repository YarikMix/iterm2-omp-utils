"""Private, versioned receipts. Invalid state never grants ownership."""
import base64
import binascii
import json
import os
import shlex
import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .legacy_state import LegacyReceipt
from .models import OmpProfile, Receipt, Selection, UiStep

VERSION = '2'
RESOURCE_VERSION = '1'
FIELDS = {'kind','target','locator','before','installed','owners','version'}
KINDS = {'file','json','toml','zsh','preference','registration','symlink','hook','profile_bar','status_bar_position','omp_setting','omp_binding'}
CURRENT_FEATURES = frozenset({'clipboard', 'status', 'notifications', 'mcp', 'shell', 'shortcuts',
                              'appearance', 'project-launcher', 'bootstrap-skill'})
CURRENT_SHORTCUTS = frozenset({'ctrl-v-ru', 'alt-enter', 'ctrl-q', 'resume'})
SHARED_OWNERS = frozenset({'shared:runtime', 'shared:shell', 'shared:hooks', 'shared:agent-profiles',
                           'shared:project-launcher'})


def private_dir(path):
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.chmod(0o700)


def durable_write(path, content, mode=0o600, *, before_replace=None):
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if before_replace is not None:
            before_replace()
        os.replace(temporary,path)
        directory = os.open(path.parent,os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_ui(steps):
    if not isinstance(steps, list):
        raise ValueError('Invalid pending UI')
    for step in steps:
        if (not isinstance(step, UiStep) or not all(isinstance(v, str) for v in
                (step.code, step.feature, step.instruction)) or
                (step.agent is not None and not isinstance(step.agent, str))):
            raise ValueError('Invalid pending UI')


def validate_resources(resources):
    if not isinstance(resources, list):
        raise ValueError('Invalid resources')
    for r in resources:
        if (not isinstance(r,dict) or set(r) != FIELDS or r['version'] != RESOURCE_VERSION or
            r['kind'] not in KINDS or not isinstance(r['target'],str) or
            not isinstance(r['locator'],dict) or not isinstance(r['owners'],list) or
            not r['owners'] or any(not isinstance(o,str) or not o for o in r['owners'])):
            raise ValueError('Invalid receipt resource')
        for field in ('before','installed'):
            if (not isinstance(r[field],dict) or set(r[field]) != {'exists','value'} or
                type(r[field]['exists']) is not bool):
                raise ValueError('Invalid receipt value')
        for field in ('before','installed'):
            value = r[field]
            if not value['exists'] and value['value'] is not None:
                raise ValueError('Invalid absent receipt value')
            if value['exists'] and r['kind'] in {'file','zsh','symlink'}:
                if not isinstance(value['value'],str):
                    raise ValueError('Invalid receipt payload')
                if r['kind'] == 'file':
                    try:
                        base64.b64decode(value['value'],validate=True)
                    except (ValueError,binascii.Error):
                        raise ValueError('Invalid receipt payload') from None
        if r['kind'] in {'omp_setting','omp_binding'}:
            from .config import omp
            omp.validate_resource(r)
        if r['kind'] in {'profile_bar','status_bar_position'}:
            from .config import iterm
            if r['locator'] != {}:
                raise ValueError('Invalid native resource address')
            if r['kind'] == 'profile_bar':
                iterm.identifier(r['target'])
                validator = iterm.validate_bar
            else:
                if r['target'] != iterm.DOMAIN:
                    raise ValueError('Invalid native position address')
                validator = iterm.validate_position
            for field in ('before','installed'):
                iterm.existing(r[field], validator)
        if r['kind'] in {'file','json','toml','zsh','hook'}:
            mode = r['locator'].get('mode')
            if type(mode) is not int or not 0 <= mode <= 0o7777:
                raise ValueError('Invalid receipt mode')
        if r['kind'] in {'zsh','registration','preference'}:
            key = 'key' if r['kind']=='preference' else 'name'
            if not isinstance(r['locator'].get(key),str) or not r['locator'][key]:
                raise ValueError('Invalid receipt address')
        if r['kind'] in {'file','json','toml','zsh','symlink','hook'} and not Path(r['target']).is_absolute():
            raise ValueError('Invalid receipt target')
        if r['kind'] in {'json','toml'} and (not isinstance(r['locator'].get('pointer'),list) or
                any(type(p) not in (str,int) for p in r['locator']['pointer'])):
            raise ValueError('Invalid receipt address')
        if r['kind'] == 'zsh' and 'placement' in r['locator']:
            loc = r['locator']
            value = loc['placement']
            if (set(loc) != {'name','mode','placement'} or loc['name'] not in {'legacy-status','legacy-restore'} or
                    not isinstance(value,dict) or set(value) != {'before','after','order'} or
                    any(value[key] is not None and (not isinstance(value[key],str) or not re.fullmatch('[0-9a-f]{64}',value[key])) for key in ('before','after')) or
                    not isinstance(value['order'],list) or any(name not in {'legacy-status','legacy-restore'} for name in value['order']) or
                    len(set(value['order'])) != len(value['order']) or loc['name'] not in value['order']):
                raise ValueError('Invalid legacy placement')
        if r['kind'] == 'hook':
            loc = r['locator']
            if set(loc) != {'pointer','entry','mode'} or not isinstance(loc['pointer'],list) or len(loc['pointer']) != 2 or loc['pointer'][0] != 'hooks' or not isinstance(loc['pointer'][1],str):
                raise ValueError('Invalid hook address')
            validate_hook(loc['entry'])
            for key in ('before','installed'):
                if r[key]['exists'] and r[key]['value'] != loc['entry']:
                    raise ValueError('Invalid hook value')


def validate_selection(choice):
    from .omp_profile import profile_name
    if not isinstance(choice, Selection):
        raise ValueError('Current selection required')
    for values in (choice.features, choice.shortcuts):
        if not isinstance(values, frozenset) or any(not isinstance(v, str) or not v for v in values):
            raise ValueError('Invalid selection')
    if (not isinstance(choice.parent_profile, str) or not choice.parent_profile.strip() or
            type(choice.notify_errors) is not bool or
            (choice.resume_key is not None and (not isinstance(choice.resume_key, str) or not choice.resume_key))):
        raise ValueError('Invalid selection')
    profile = choice.omp_profile
    if (not isinstance(profile, OmpProfile) or not isinstance(profile.agent_dir, Path) or
            not profile.agent_dir.is_absolute() or
            (profile.name is not None and (not isinstance(profile.name, str) or profile_name(profile.name) != profile.name))):
        raise ValueError('Invalid omp profile')
    if not choice.features <= CURRENT_FEATURES or not choice.shortcuts <= CURRENT_SHORTCUTS:
        raise ValueError('Unknown current selection')
    if choice.shortcuts and 'shortcuts' not in choice.features:
        raise ValueError('Shortcut choices require their feature')
    return choice


def validate(receipt):
    if not isinstance(receipt, Receipt) or receipt.version != VERSION:
        raise ValueError('Unsupported receipt')
    validate_selection(receipt.selection)
    validate_resources(receipt.resources)
    validate_ui(receipt.pending_ui)
    if any(step.agent not in {None, 'omp'} for step in receipt.pending_ui):
        raise ValueError('Historical UI requires historical state')
    for resource in receipt.resources:
        for owner in resource['owners']:
            if owner not in SHARED_OWNERS and owner.removeprefix('omp:') not in CURRENT_FEATURES:
                raise ValueError('Unknown or historical owner requires historical state')
        if resource['kind'] == 'registration' and resource['target'] != 'omp':
            raise ValueError('Historical registration requires historical state')
    if not isinstance(receipt.legacy_cleanup, list):
        raise ValueError('Invalid historical cleanup')
    from .legacy_state import decode
    for raw in receipt.legacy_cleanup:
        decode(raw)
    return receipt


def decode(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid receipt')
    if data.get('version') == '1':
        from .legacy_state import decode as decode_legacy
        return decode_legacy(data)
    if set(data) != {'version', 'selection', 'resources', 'pending_ui', 'legacy_cleanup'} or data['version'] != VERSION:
        raise ValueError('Unsupported receipt')
    if not isinstance(data['selection'], dict) or not isinstance(data['pending_ui'], list):
        raise ValueError('Invalid selection')
    selection = dict(data['selection'])
    if set(selection) != {'features', 'shortcuts', 'parent_profile', 'omp_profile', 'resume_key', 'notify_errors'}:
        raise ValueError('Invalid selection')
    for key in ('features', 'shortcuts'):
        values = selection[key]
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
            raise ValueError('Invalid selection')
        selection[key] = frozenset(values)
    profile = selection['omp_profile']
    if not isinstance(profile, dict) or set(profile) != {'name', 'agent_dir'} or not isinstance(profile['agent_dir'], str):
        raise ValueError('Invalid omp profile')
    selection['omp_profile'] = OmpProfile(profile['name'], Path(profile['agent_dir']))
    return validate(Receipt(data['version'], Selection(**selection), data['resources'],
                            [UiStep(**s) for s in data['pending_ui']], data['legacy_cleanup']))


def load(path: Path) -> 'Receipt | LegacyReceipt | None':
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        from .config.jsonfile import parse
        return decode(parse(raw))
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        raise ValueError('Invalid or unsupported receipt; ownership unavailable') from None


def save(path: Path, receipt: Receipt) -> None:
    data = asdict(validate(receipt))
    for key in ('features', 'shortcuts'):
        data['selection'][key] = sorted(data['selection'][key])
    data['selection']['omp_profile']['agent_dir'] = str(receipt.selection.omp_profile.agent_dir)
    private_dir(path.parent)
    durable_write(path, (json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False)+'\n').encode())


def save_recovery(path: Path, receipt) -> None:
    """Preserve journal identity, including v1 migration intent with a v2 result."""
    from .legacy_state import LegacyReceipt, encode
    if isinstance(receipt, LegacyReceipt):
        data = encode(receipt)
        private_dir(path.parent)
        durable_write(path, (json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False)+'\n').encode())
    else:
        save(path, receipt)


def validate_hook(entry):
    if not isinstance(entry,dict) or set(entry) - {'hooks','matcher'} or 'hooks' not in entry:
        raise ValueError('Invalid hook entry')
    if 'matcher' in entry and (not isinstance(entry['matcher'],str) or len(entry['matcher']) > 512):
        raise ValueError('Invalid hook matcher')
    if not isinstance(entry['hooks'],list) or len(entry['hooks']) != 1:
        raise ValueError('Invalid hook commands')
    hook = entry['hooks'][0]
    if (not isinstance(hook,dict) or set(hook) - {'type','command','timeout','async'} or
            hook.get('type') != 'command' or not isinstance(hook.get('command'),str) or
            len(hook['command']) > 8192 or ('timeout' in hook and type(hook['timeout']) not in (int,float)) or
            ('async' in hook and type(hook['async']) is not bool)):
        raise ValueError('Invalid hook command')


NATIVE_EVENTS = frozenset({'SessionStart','SessionEnd','UserPromptSubmit','PreToolUse','PostToolUse',
    'PostToolUseFailure','PermissionRequest','Notification','Stop','StopFailure','SubagentStart',
    'SubagentStop','PreCompact','PostCompact'})
NATIVE_ARGUMENTS = frozenset({'start','stop','working','waiting','idle','session-start','session-end',
    'user-prompt-submit','pre-tool-use','post-tool-use','notification','permission-request'})


def validate_native_entry(item):
    if item['event'] not in NATIVE_EVENTS:
        raise ValueError('Unknown native hook event')
    entry = item['entry']
    validate_hook(entry)
    if entry.get('matcher','') not in {'','*'}:
        raise ValueError('Unknown native matcher')
    words = shlex.split(entry['hooks'][0]['command'])
    if (not words or not Path(words[0]).is_absolute() or
            not (words[0].endswith('/.config/iterm2/cc-status') or
                 words[0].endswith('/Contents/Resources/utilities/cc-status')) or
            len(words) > 2 or (len(words)==2 and words[1] not in NATIVE_ARGUMENTS)):
        raise ValueError('Unknown native command')
