"""Pure, explicitly allowlisted MCP releases and profile-scoped adapter."""
import hashlib
import json
from pathlib import Path
import re

from ..config.mcp import definition, server_edit
from ..mcp.binding import McpBinding
from ..models import ChangeSet, Context, FileEdit, Selection, UiStep
from .shell import _source

# Package sources are explicit; no recursive checkout copy or shell-feature dependency.
PACKAGE_FILES = (
    '__init__.py', '__main__.py', 'cli.py', 'commands.py', 'discovery.py', 'engine.py',
    'lifecycle.py', 'launch.py', 'launch_api.py', 'launch_checks.py', 'legacy_state.py',
    'migration.py', 'models.py', 'omp_profile.py', 'omp_sessions.py', 'planner.py',
    'profile_api.py', 'project_edits.py', 'skill_install.py', 'state.py', 'terminal.py',
    'config/__init__.py', 'config/iterm.py', 'config/jsonfile.py', 'config/legacy_mcp.py',
    'config/mcp.py', 'config/omp.py', 'config/preferences.py', 'config/tomlfile.py', 'config/zshrc.py',
    'features/__init__.py', 'features/appearance.py', 'features/mcp.py', 'features/notifications.py',
    'features/profiles.py', 'features/project_launcher.py', 'features/restore.py', 'features/shell.py',
    'features/status.py', 'mcp/__init__.py', 'mcp/__main__.py', 'mcp/binding.py', 'mcp/connection.py',
    'mcp/cookie.py', 'mcp/errors.py', 'mcp/launch_tools.py', 'mcp/launch_worker.py', 'mcp/observe.py',
    'mcp/output_cursor.py', 'mcp/project_worker.py', 'mcp/server.py', 'mcp/session.py',
    'mcp/tools/__init__.py', 'mcp/tools/read.py', 'mcp/tools/write.py',
)
BASE_FILES = tuple('iterm2_utils/'+name for name in PACKAGE_FILES) + (
    'runtime/iterm2_mcp_entry.py', 'runtime/terminal_identity.py', 'runtime/omp_config.ts',
    'runtime/omp_identity.ts', 'runtime/omp_iterm2_projects.ts', 'runtime/appearance.py',
    'runtime/appearance.zsh', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'sources.lock.json',
    'vendor/mcp_server_iterm2/LICENSE', 'vendor/shell_integration/LICENSE',
    'vendor/shell_integration/iterm2_shell_integration.zsh',
)


def payload_names(repo):
    manifest = json.loads(_source(repo, Path('sources.lock.json')))
    extra = []
    for item in manifest['sources']:
        name = item['path']
        if name.startswith(('vendor/yaml/', 'runtime/assets/appearance/')):
            if hashlib.sha256(_source(repo, Path(name))).hexdigest() != item['sha256']:
                raise ValueError('Payload provenance changed')
            extra.append(name)
    return tuple(sorted((*BASE_FILES, *extra)))


def _digest(files):
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode()+b'\0'+content+b'\0')
    return digest.hexdigest()


def verify_release(root, data):
    if (root.parent.resolve() != (data/'mcp/releases').resolve() or
            not re.fullmatch('[0-9a-f]{64}', root.name) or root.is_symlink()):
        raise ValueError('Invalid release namespace')
    files = {name:_source(root, Path(name)) for name in payload_names(root)}
    if _digest(files) != root.name:
        raise ValueError('Immutable payload changed')


def retain_release_resource(resource, context):
    """Only proved owned, unchanged content-addressed payload bytes survive opt-out."""
    if resource['kind'] != 'file' or resource['owners'] != ['mcp']:
        return False
    path = Path(resource['target'])
    base = (context.paths.data/'mcp/releases').resolve()
    if not path.is_relative_to(base):
        return False
    relative = path.relative_to(base)
    if len(relative.parts) < 2:
        return False
    root = base/relative.parts[0]
    try:
        verify_release(root, context.paths.data)
        return str(path.relative_to(root)) in payload_names(root)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Damaged payloads lose retention, not the ability to revoke their entry.
        return False

def superseded_payload_resources(receipt, compiled, context):
    """Retire only the prior authorized payload, in its replacement checkpoint."""
    from .. import engine
    from ..config import mcp
    target = str((receipt.selection.omp_profile.agent_dir/'mcp.json').resolve())
    replacement = next((r for r in compiled if r['kind'] == 'json' and
        r['target'] == target and r['owners'] == ['mcp'] and
        r['locator']['pointer'] == ['mcpServers', mcp.NAME] and
        r['before']['exists'] and r['installed']['exists'] and
        not engine._same(r['before'], r['installed'])), None)
    if replacement is None:
        return set()
    old = mcp.installed_binding(context)
    value = replacement['installed']['value']
    args = value.get('args', [])
    if len(args) != 6:
        return set()
    new = McpBinding(old.profile, Path(args[1]).parent.parent, old.receipt_path, Path(value['command']))
    if (new.install_root == old.install_root or
            new.install_root.parent.resolve() != (context.paths.data/'mcp/releases').resolve() or
            not re.fullmatch('[0-9a-f]{64}', new.install_root.name) or
            value != definition(new) or replacement['before']['value'] != definition(old)):
        return set()
    mcp.authorize_binding(old)
    targets = {str((old.install_root/name).resolve()) for name in payload_names(old.install_root)}
    retired = set()
    for resource in receipt.resources:
        if resource['kind'] == 'file' and resource['owners'] == ['mcp'] and resource['target'] in targets:
            if not engine._same(engine._read(resource, None, context), resource['installed']):
                raise ValueError('Prior owned payload changed')
            retired.add(engine._identity(resource))
    return retired



def extension_content(binding):
    install = {'python':str(binding.python), 'entry':str(binding.install_root/'runtime/iterm2_mcp_entry.py'),
               'profile':{'name':binding.profile.name,'agent_dir':str(binding.profile.agent_dir)},
               'receipt':str(binding.receipt_path)}
    source = _source(binding.install_root, Path('runtime/omp_iterm2_projects.ts'))
    marker = b"function installation(): Installation { throw new Error('Install the profile-scoped projects extension first'); }"
    if source.count(marker) != 1:
        raise ValueError('Adapter installation contract changed')
    return source.replace(marker, b'function installation(): Installation { return '+json.dumps(install).encode()+b'; }')


def build(context: Context, selection: Selection) -> ChangeSet:
    from .. import engine, state
    changes = ChangeSet([], [], [])
    if 'mcp' not in selection.features:
        return changes
    files = {name:_source(context.paths.repo, Path(name)) for name in payload_names(context.paths.repo)}
    release = context.paths.data/'mcp/releases'/_digest(files)
    if release.exists():
        verify_release(release, context.paths.data)
    binding = McpBinding(selection.omp_profile, release, context.paths.data/'receipt.json', context.executables['python3'])
    # Stamp from checked source bytes before a pure plan has written the release.
    source = files['runtime/omp_iterm2_projects.ts']
    install = {'python':str(binding.python), 'entry':str(release/'runtime/iterm2_mcp_entry.py'),
               'profile':{'name':binding.profile.name,'agent_dir':str(binding.profile.agent_dir)},
               'receipt':str(binding.receipt_path)}
    marker = b"function installation(): Installation { throw new Error('Install the profile-scoped projects extension first'); }"
    if source.count(marker) != 1:
        raise ValueError('Adapter installation contract changed')
    content = source.replace(marker,b'function installation(): Installation { return '+json.dumps(install).encode()+b'; }')
    target = selection.omp_profile.agent_dir/'extensions/iterm2-utils-projects.ts'
    before = _source(target.parent, Path(target.name)) if target.exists() else None
    receipt = state.load(binding.receipt_path)
    if before is not None:
        owned = [r for r in receipt.resources if r['target'] == str(target.resolve()) and r['owners'] == ['mcp']] if receipt else []
        if not owned or any(not engine._same(engine._read(r,None,context),r['installed']) for r in owned):
            raise ValueError('Adapter owned by another writer')
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError('Unsafe adapter path')
    from ..config import mcp, jsonfile
    current = mcp.read_server(selection.omp_profile)
    expected = definition(binding)
    if current['exists'] and current['value'] != expected:
        # Only an already authorized owned replacement can upgrade in place.
        mcp.authorize_binding(mcp.installed_binding(context))
        path, raw, _ = mcp._read(selection.omp_profile)
        registration = FileEdit(path, raw, jsonfile.patch(raw, ('mcpServers',mcp.NAME), expected), 0o600, 'mcp')
    else:
        registration = server_edit(selection.omp_profile, binding=binding)
    # Identical foreign registration is not installation authority.
    if registration.before == registration.after:
        owned = [r for r in receipt.resources if r['target'] == str(registration.path.resolve()) and
                 r['kind'] == 'json' and r['locator']['pointer'] == ['mcpServers','iterm2-observe'] and
                 r['owners'] == ['mcp']] if receipt else []
        if not owned:
            raise ValueError('Registration is not owned')
    for name, content_bytes in files.items():
        path = release/name
        changes.edits.append(FileEdit(path, path.read_bytes() if path.exists() else None, content_bytes, 0o600, 'mcp'))
    changes.edits.extend([registration, FileEdit(target,before,content,0o600,'mcp')])
    changes.ui.append(UiStep('mcp_authorize','mcp','omp',
        'Authorize the iTerm2 Python API; start a fresh selected-profile omp session. '
        'Run doctor --live for read-only catalogue/observe readiness; UI/editor acceptance is separate.'))
    return changes
