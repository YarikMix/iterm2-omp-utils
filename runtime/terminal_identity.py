"""Generic explicit iTerm terminal addresses; no agent events or active-tab fallback."""
import re
import ctypes
import sys


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


class _ProcBSDInfo(ctypes.Structure):
    """Public Darwin sys/proc_info.h proc_bsdinfo (LP64, MAXCOMLEN=16)."""
    _fields_ = [
        ('pbi_flags', ctypes.c_uint32), ('pbi_status', ctypes.c_uint32),
        ('pbi_xstatus', ctypes.c_uint32), ('pbi_pid', ctypes.c_uint32),
        ('pbi_ppid', ctypes.c_uint32), ('pbi_uid', ctypes.c_uint32),
        ('pbi_gid', ctypes.c_uint32), ('pbi_ruid', ctypes.c_uint32),
        ('pbi_rgid', ctypes.c_uint32), ('pbi_svuid', ctypes.c_uint32),
        ('pbi_svgid', ctypes.c_uint32), ('rfu_1', ctypes.c_uint32),
        ('pbi_comm', ctypes.c_char * 16), ('pbi_name', ctypes.c_char * 32),
        ('pbi_nfiles', ctypes.c_uint32), ('pbi_pgid', ctypes.c_uint32),
        ('pbi_pjobc', ctypes.c_uint32), ('e_tdev', ctypes.c_uint32),
        ('e_tpgid', ctypes.c_uint32), ('pbi_nice', ctypes.c_int32),
        ('pbi_start_tvsec', ctypes.c_uint64), ('pbi_start_tvusec', ctypes.c_uint64),
    ]


def _read_bsdinfo(pid: int) -> _ProcBSDInfo | None:
    """Only public libproc PROC_PIDTBSDINFO; unavailable ABI is not evidence."""
    if sys.platform != 'darwin' or ctypes.sizeof(_ProcBSDInfo) != 136:
        return None
    try:
        libproc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        probe = libproc.proc_pidinfo
        probe.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                         ctypes.c_void_p, ctypes.c_int]
        probe.restype = ctypes.c_int
        info = _ProcBSDInfo()
        size = ctypes.sizeof(info)
        if probe(pid, 3, 0, ctypes.byref(info), size) != size:
            return None
        return info
    except (OSError, AttributeError, ctypes.ArgumentError):
        return None


def process_start(pid: int) -> str | None:
    """Live Darwin kernel birth at microsecond precision, or no authority.

    sys/proc.h: only SRUN=2, SSLEEP=3 and SSTOP=4 are live; SIDL and
    SZOMB (including an unreaped exited process) cannot establish identity.
    """
    if type(pid) is not int or not 0 < pid <= 0x7fffffff:
        return None
    info = _read_bsdinfo(pid)
    if (info is None or info.pbi_pid != pid or info.pbi_status not in {2, 3, 4}
            or info.pbi_start_tvsec <= 0 or not 0 <= info.pbi_start_tvusec < 1000000):
        return None
    return f'darwin-bsd:{info.pbi_start_tvsec}:{info.pbi_start_tvusec:06d}'


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
    if len(sys.argv) == 3 and sys.argv[1] == '--process-start':
        try:
            value = process_start(int(sys.argv[2]))
        except ValueError:
            value = None
        print(json.dumps(value))
        return
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
