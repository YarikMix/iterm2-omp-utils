"""The existing 13 observe/annotation tools, with authorization per call.

Adapted from mcp-server-iterm2 v0.1.1, Copyright (c) 2026 Rob Trame (MIT).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .connection import ObserveConnection
from .errors import MCPIterm2Error, to_error_text
from .session import normalize_iterm_session_id
from .tools import read, write

OBSERVE_TOOLS = frozenset({'list_sessions', 'get_session_info', 'get_screen_contents',
    'get_selection', 'get_scrollback', 'get_recent_output', 'get_variable',
    'list_profiles', 'set_badge', 'set_title', 'set_tab_color', 'set_user_variable',
    'post_notification'})


def register_observe(server, observe: ObserveConnection,
                     authorize: Callable[[], Awaitable[None]], terminal_id: str | None) -> None:
    env_id = normalize_iterm_session_id(terminal_id)

    async def call(impl, *, target=False, session_id=None, notification=False, **kwargs):
        try:
            try:
                await authorize()
            except Exception:
                await observe.aclose()
                raise
            if notification:
                return await impl(**kwargs)
            if target:
                kwargs.update(session_id_arg=session_id, env_session_id=env_id)
            async with observe.lease() as client:
                result = impl(client, **kwargs)
                if isinstance(result, dict):
                    return result
                return await result
        except Exception as exc:
            # No traceback/logging or raw SDK/osascript payloads at this boundary.
            message = to_error_text(exc) if isinstance(exc, MCPIterm2Error) else 'Internal error.'
            raise RuntimeError(message) from None

    @server.tool()
    async def list_sessions() -> dict[str, Any]:
        """List all windows, tabs, and sessions iTerm2 currently has open."""
        return await call(read.list_sessions_impl)

    @server.tool()
    async def get_session_info(session_id: str | None = None) -> dict[str, Any]:
        """Return title, working dir, profile, badge, dimensions, TTY for a session."""
        return await call(read.get_session_info_impl, target=True, session_id=session_id)

    @server.tool()
    async def get_screen_contents(session_id: str | None = None) -> dict[str, Any]:
        """Return the visible buffer text and cursor position for a session."""
        return await call(read.get_screen_contents_impl, target=True, session_id=session_id)

    @server.tool()
    async def get_selection(session_id: str | None = None) -> dict[str, Any]:
        """Return currently-selected text in the session, or empty string."""
        return await call(read.get_selection_impl, target=True, session_id=session_id)

    @server.tool()
    async def get_scrollback(session_id: str | None = None, n_lines: int = 200) -> dict[str, Any]:
        """Return the last N lines of scrollback (default 200, max 5000)."""
        return await call(read.get_scrollback_impl, target=True, session_id=session_id, n_lines=n_lines)

    @server.tool()
    async def get_recent_output(session_id: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Return output since the cursor, or the visible screen on the first call."""
        return await call(read.get_recent_output_impl, target=True, session_id=session_id, cursor=cursor)

    @server.tool()
    async def get_variable(name: str, session_id: str | None = None) -> dict[str, Any]:
        """Read an iTerm2 variable by fully-qualified name."""
        return await call(read.get_variable_impl, target=True, session_id=session_id, name=name)

    @server.tool()
    async def list_profiles() -> dict[str, Any]:
        """List available iTerm2 profiles by name and GUID."""
        return await call(read.list_profiles_impl)

    @server.tool()
    async def set_badge(text: str, session_id: str | None = None) -> dict[str, Any]:
        """Set session badge text; requires \\(user.badge) in the badge format."""
        return await call(write.set_badge_impl, target=True, session_id=session_id, text=text)

    @server.tool()
    async def set_title(title: str, session_id: str | None = None) -> dict[str, Any]:
        """Override the session title. Rendering depends on profile title settings."""
        return await call(write.set_title_impl, target=True, session_id=session_id, title=title)

    @server.tool()
    async def set_tab_color(r: int, g: int, b: int, session_id: str | None = None) -> dict[str, Any]:
        """Set the tab tint as RGB (each component 0-255)."""
        return await call(write.set_tab_color_impl, target=True, session_id=session_id, r=r, g=g, b=b)

    @server.tool()
    async def set_user_variable(name: str, value: str, session_id: str | None = None) -> dict[str, Any]:
        """Set a user-scoped session variable. Name must start with 'user.'."""
        return await call(write.set_user_variable_impl, target=True, session_id=session_id, name=name, value=value)

    @server.tool()
    async def post_notification(title: str, body: str) -> dict[str, Any]:
        """Post a macOS notification (banner) with the given title and body."""
        return await call(write.post_notification_impl, notification=True, title=title, body=body)
