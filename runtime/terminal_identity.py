"""Generic explicit iTerm terminal addresses; no agent events or active-tab fallback."""
import re


def terminal_id(value):
    """Accept only an explicit bare UUID or iTerm's local panel address."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r'(?:w[0-9]+t[0-9]+p[0-9]+:)?'
        r'([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})', value)
    return match[1].upper() if match else None


def terminal_from_environment(environment: dict[str, str]) -> str | None:
    """Reject invalid or disagreeing sources, including present empty values."""
    terminals = [terminal_id(environment[key])
                 for key in ('ITERM_SESSION_ID', 'TERM_SESSION_ID') if key in environment]
    if not terminals or any(value is None for value in terminals):
        return None
    return terminals[0] if len(set(terminals)) == 1 else None


def process_start(pid: int) -> str | None:
    """Kernel-observed birth identity, not kill(pid, 0) liveness."""
    import subprocess
    try:
        result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='],
                                capture_output=True, text=True, timeout=2)
        return result.stdout.strip() or None if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def tty_device(path):
    import os
    import stat
    try:
        info = os.stat(path)
        return info.st_rdev if stat.S_ISCHR(info.st_mode) else None
    except (OSError, TypeError, ValueError):
        return None


async def observe_own_terminal(pid: int, tty: str, environment: dict[str, str], sdk):
    """Match process controlling tty AND explicit SDK session tty before OSC writes."""
    import subprocess
    terminal = terminal_from_environment(environment)
    device = tty_device(tty)
    if terminal is None or device is None:
        return None
    result = subprocess.run(['/bin/ps','-p',str(pid),'-o','tty='],
                            capture_output=True,text=True,timeout=2)
    process_tty = result.stdout.strip()
    if result.returncode or not process_tty or process_tty == '??' or tty_device('/dev/'+process_tty) != device:
        return None
    connection = await sdk.Connection.async_create()
    try:
        app = await sdk.async_get_app(connection)
        matches = []
        for window in app.terminal_windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    if session.session_id.upper() != terminal:
                        continue
                    if tty_device(await session.async_get_variable('tty')) == device:
                        matches.append({'terminal_id':terminal, 'tab_id':tab.tab_id,
                                        'window_id':window.window_id, 'tty':tty,
                                        'identity':await session.async_get_variable('user.iterm2_utils_omp')})
        return matches[0] if len(matches) == 1 else None
    finally:
        await connection.websocket.close()


def _main():
    import asyncio
    import json
    import os
    import sys
    import iterm2
    # Invoked only by an installed extension, never during discovery/bootstrap.
    try:
        result = asyncio.run(asyncio.wait_for(
            observe_own_terminal(int(sys.argv[1]), sys.argv[2], dict(os.environ), iterm2), 4))
        print(json.dumps(result))
    except Exception:
        print('null')


if __name__ == '__main__':
    _main()
