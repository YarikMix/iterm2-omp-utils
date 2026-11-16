"""Optional omp stdio MCP server; one owned JSON pointer, never agent CLI calls."""
import os
import stat

from . import jsonfile
from .omp import LIMIT, same
from ..models import FileEdit, Finding, OmpProfile

NAME = 'iterm2-observe'
ARGS = ['--with', 'mcp<2', 'mcp-server-iterm2==0.1.1']
TOOLS = frozenset({'list_sessions', 'get_session_info', 'get_screen_contents', 'get_selection',
    'get_scrollback', 'get_recent_output', 'get_variable', 'list_profiles', 'set_badge',
    'set_title', 'set_tab_color', 'set_user_variable', 'post_notification'})


def definition():
    return {'command': 'uvx', 'args': list(ARGS), 'env': {}, 'enabled': True}


def _storage(profile):
    if not isinstance(profile, OmpProfile) or not profile.agent_dir.is_absolute():
        raise ValueError('Invalid omp MCP profile')
    return profile.agent_dir/'mcp.json'


def _read(profile):
    path = _storage(profile)
    try:
        with path.open('rb') as source:
            raw = source.read(LIMIT + 1)
    except FileNotFoundError:
        raw = None
    except OSError:
        raise ValueError('MCP configuration is unreadable') from None
    if raw is not None and len(raw) > LIMIT:
        raise ValueError('MCP configuration exceeds size limit')
    root = jsonfile.parse(raw) if raw is not None else {}
    if not isinstance(root, dict) or 'mcpServers' in root and not isinstance(root['mcpServers'], dict):
        raise ValueError('Invalid MCP configuration')
    for key in ('disabledServers', 'enabledServers'):
        if key in root and (not isinstance(root[key], list) or any(not isinstance(name, str) for name in root[key])):
            raise ValueError('Invalid MCP server policy')
    if NAME in root.get('disabledServers', []):
        raise ValueError('Selected MCP server is explicitly disabled')
    return path, raw, root


def read_server(profile: OmpProfile, runner=None) -> dict:
    """Return local server presence without executing any process."""
    _, _, root = _read(profile)
    servers = root.get('mcpServers', {})
    return {'exists': NAME in servers, 'value': servers.get(NAME)}


def server_edit(profile: OmpProfile, runner=None, *, owner: str = 'mcp') -> FileEdit:
    """Pure ChangeSet edit; engine compiles the entire selected server atomically."""
    path, raw, root = _read(profile)
    servers = root.get('mcpServers', {})
    if NAME in servers and not same(servers[NAME], definition()):
        raise ValueError('Foreign MCP server name collision')
    content = raw if NAME in servers else jsonfile.patch(raw or b'{}', ('mcpServers', NAME), definition())
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    return FileEdit(path, raw, content, mode, owner)


def probe(context, runner):
    """Explicit live MCP handshake; not part of read/plan/storage mutation."""
    ready = False
    try:
        if context.omp_profile is None or not same(read_server(context.omp_profile), {'exists': True, 'value': definition()}):
            raise ValueError('Pinned MCP definition unavailable')
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL') if key in os.environ}
        env['HOME'] = str(context.paths.home)
        executable = str(context.executables.get('uvx', 'uvx'))
        result = runner.mcp_probe([executable, *ARGS], timeout=5, env=env)
        tools = result.get('tools')
        ready = (result.get('sessions') is True and isinstance(tools,list) and
                 len(tools) == len(TOOLS) and all(isinstance(tool,str) for tool in tools) and set(tools) == TOOLS)
    except Exception:
        pass
    return Finding('mcp', None, 'mcp_connection', 'ready' if ready else 'unavailable',
        'Pinned MCP connection and observe tool policy verified.' if ready else
        'Pinned MCP connection or tool policy could not be verified; authorize the iTerm2 Python API and retry.')
