"""Optional omp stdio MCP server; one owned JSON pointer, never agent CLI calls."""
import os
import stat
from pathlib import Path

from . import jsonfile
from .omp import _bytes, same
from ..models import FileEdit, Finding, OmpProfile

NAME = 'iterm2-observe'
TOOLS = frozenset({'list_sessions', 'get_session_info', 'get_screen_contents', 'get_selection',
    'get_scrollback', 'get_recent_output', 'get_variable', 'list_profiles', 'set_badge',
    'set_title', 'set_tab_color', 'set_user_variable', 'post_notification'})
PUBLIC_TOOLS = TOOLS | {'list_projects', 'open_shell', 'launch_omp_task'}


def definition(binding):
    """Only an explicit installed binding can describe a new runtime."""
    if binding is None:
        raise ValueError('Explicit installation binding required')
    return {'command': str(binding.python), 'args': ['-I',
        str(binding.install_root/'runtime/iterm2_mcp_entry.py'),
        '--omp-profile', str(binding.profile.agent_dir), '--receipt', str(binding.receipt_path)],
        'env': {}, 'timeout': 300000, 'enabled': True}


def _storage(profile):
    if not isinstance(profile, OmpProfile) or not profile.agent_dir.is_absolute():
        raise ValueError('Invalid omp MCP profile')
    return profile.agent_dir/'mcp.json'


def _read(profile):
    path = _storage(profile)
    raw = _bytes(path)
    root = jsonfile.parse(raw) if raw is not None else {}
    if not isinstance(root, dict) or 'mcpServers' in root and not isinstance(root['mcpServers'], dict):
        raise ValueError('Invalid MCP configuration')
    for key in ('disabledServers', 'enabledServers'):
        if key in root and (not isinstance(root[key], list) or any(not isinstance(name, str) for name in root[key])):
            raise ValueError('Invalid MCP server policy')
    if NAME in root.get('disabledServers', []) or 'enabledServers' in root and NAME not in root['enabledServers']:
        raise ValueError('Selected MCP server is explicitly disabled')
    return path, raw, root


def read_server(profile: OmpProfile, runner=None) -> dict:
    """Return local server presence without executing any process."""
    _, _, root = _read(profile)
    servers = root.get('mcpServers', {})
    return {'exists': NAME in servers, 'value': servers.get(NAME)}


def server_edit(profile: OmpProfile, runner=None, *, owner: str = 'mcp', binding=None) -> FileEdit:
    """Pure ChangeSet edit; engine compiles the entire selected server atomically."""
    path, raw, root = _read(profile)
    servers = root.get('mcpServers', {})
    expected = definition(binding)
    if NAME in servers and not same(servers[NAME], expected):
        raise ValueError('Foreign MCP server name collision; explicitly remove owned legacy MCP first')
    content = raw if NAME in servers else jsonfile.patch(raw or b'{}', ('mcpServers', NAME), expected)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    return FileEdit(path, raw, content, mode, owner)


def probe(context, runner):
    """Explicit live MCP handshake; not part of read/plan/storage mutation."""
    ready = False
    try:
        binding = installed_binding(context)
        authorize_binding(binding)
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL') if key in os.environ}
        env['HOME'] = str(context.paths.home)
        value = definition(binding)
        result = runner.mcp_probe([value['command'], *value['args']], timeout=5, env=env)
        tools = result.get('tools')
        ready = (result.get('sessions') is True and isinstance(tools,list) and
                 len(tools) == len(PUBLIC_TOOLS) and all(isinstance(tool,str) for tool in tools) and set(tools) == PUBLIC_TOOLS)
    except Exception:
        pass
    return Finding('mcp', None, 'mcp_connection', 'ready' if ready else 'unavailable',
        'Owned catalogue and read-only observe readiness verified; native UI/editor acceptance remains unverified.' if ready else
        'Owned MCP readiness unavailable; check optional dependencies, ownership and Python API authorization.')


def installed_binding(context):
    from ..mcp.binding import McpBinding
    value = read_server(context.omp_profile)['value']
    if not isinstance(value, dict) or not isinstance(value.get('args'), list):
        raise ValueError('Owned registration unavailable')
    args = value['args']
    if len(args) != 6 or args[0] != '-I' or args[2] != '--omp-profile' or args[4] != '--receipt':
        raise ValueError('Explicit legacy replacement required')
    return McpBinding(context.omp_profile, Path(args[1]).parent.parent,
                      context.paths.data/'receipt.json', Path(value['command']))


def authorize_binding(binding):
    """Re-read registration, receipt, payload and stamped adapter on every call."""
    from .. import engine
    from ..features.mcp import verify_release, extension_content
    if not all(p.is_absolute() for p in (binding.python, binding.install_root,
                                        binding.receipt_path, binding.profile.agent_dir)):
        raise ValueError('Invalid installation binding')
    if binding.receipt_path.name != 'receipt.json':
        raise ValueError('Invalid receipt')
    from ..project_edits import read_receipt
    _, receipt = read_receipt(binding.receipt_path)
    if (receipt is None or 'mcp' not in receipt.selection.features or
            receipt.selection.omp_profile != binding.profile):
        raise ValueError('Installation revoked')
    expected = definition(binding)
    if not same(read_server(binding.profile), {'exists':True, 'value':expected}):
        raise ValueError('Registration revoked')
    target = _storage(binding.profile)
    extension = binding.profile.agent_dir/'extensions/iterm2-utils-projects.ts'
    for path, kind in ((target, 'json'), (extension, 'file')):
        owned = [r for r in receipt.resources if r['kind'] == kind and
                 r['target'] == str(path.resolve()) and r['owners'] == ['mcp'] and
                 (kind != 'json' or r['locator']['pointer'] == ['mcpServers', NAME])]
        if len(owned) != 1 or not engine._same(engine._read(owned[0], None, None), owned[0]['installed']):
            raise ValueError('Installation ownership unavailable')
    verify_release(binding.install_root, binding.receipt_path.parent)
    if _bytes(extension) != extension_content(binding):
        raise ValueError('Adapter provenance changed')
