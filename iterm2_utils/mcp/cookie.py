# Adapted from mcp-server-iterm2 v0.1.1; Copyright (c) 2026 Rob Trame (MIT).
"""Request an iTerm2 API cookie via AppleScript."""

import os
import asyncio

from iterm2_utils.mcp.errors import APINotEnabled, AuthDenied, ITermNotRunning, SubprocessTimeout

_OSASCRIPT_COMMAND = [
    "/usr/bin/osascript",
    "-e",
    'tell application "iTerm2" to request cookie',
]
_COOKIE_TIMEOUT_S = 30.0


def _osascript_env() -> dict[str, str]:
    """Minimal environment for osascript children — explicitly excludes ITERM2_COOKIE.

    osascript needs PATH (for tools it shells out to) and HOME (for bundle
    lookups). It does NOT need our cookie or other state, so we don't leak them
    to a child process that has no business reading them.
    """
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/"),
    }


async def request_cookie_async() -> str:
    """Request one cookie, killing and reaping the child on cancel/timeout."""
    process = await asyncio.create_subprocess_exec(
        *_OSASCRIPT_COMMAND, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=_osascript_env())
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), _COOKIE_TIMEOUT_S)
    except BaseException as exc:
        if process.returncode is None:
            process.kill()
        await process.wait()
        if isinstance(exc, TimeoutError):
            raise SubprocessTimeout("requesting iTerm2 cookie", _COOKIE_TIMEOUT_S) from None
        raise
    if process.returncode == 0 and stdout.strip():
        return stdout.decode("utf-8").strip()
    stderr_lower = stderr.decode("utf-8", errors="replace").lower()
    if "isn’t running" in stderr_lower or "application isn't running" in stderr_lower:
        raise ITermNotRunning()
    if "python api is not enabled" in stderr_lower:
        raise APINotEnabled()
    raise AuthDenied()
