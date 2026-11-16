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


def _birth(pid, info):
    if (info is None or info.pbi_pid != pid or info.pbi_start_tvsec <= 0
            or not 0 <= info.pbi_start_tvusec < 1000000):
        return None
    return f'darwin-bsd:{info.pbi_start_tvsec}:{info.pbi_start_tvusec:06d}'


def process_start(pid: int) -> str | None:
    """Live Darwin kernel birth at microsecond precision, or no authority.

    sys/proc.h: only SRUN=2, SSLEEP=3 and SSTOP=4 are live; SIDL and
    SZOMB (including an unreaped exited process) cannot establish identity.
    """
    if type(pid) is not int or not 0 < pid <= 0x7fffffff:
        return None
    info = _read_bsdinfo(pid)
    return _birth(pid, info) if info is not None and info.pbi_status in {2, 3, 4} else None


def tty_device(path):
    import os
    import stat
    if not isinstance(path, str) or not path.startswith('/') or '\x00' in path:
        return None
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


def read_identity_records(registry):
    """Shared private schema reader, usable from an installed standalone runtime."""
    import json
    import os
    from pathlib import Path
    import stat
    fields = {'schema', 'terminal_id', 'tab_id', 'window_id', 'session_file',
              'session_id', 'cwd', 'profile', 'pid', 'process_start', 'generation'}
    result = []
    try:
        info = registry.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o777 != 0o700 or info.st_uid != os.getuid():
            return []
        for path in registry.glob('*.json'):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as source:
                    info = os.fstat(source.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o777 != 0o600
                            or info.st_size > 65536 or info.st_uid != os.getuid()):
                        continue
                    raw = json.loads(source.read(65537))
                if type(raw) is not dict or set(raw) != fields or type(raw['schema']) is not int or raw['schema'] != 1:
                    continue
                profile = raw['profile']
                if (type(profile) is not dict or set(profile) != {'name', 'agent_dir'}
                        or not Path(profile['agent_dir']).is_absolute()
                        or profile['name'] is not None and not isinstance(profile['name'], str)):
                    continue
                if terminal_id(raw['terminal_id']) != raw['terminal_id'] or type(raw['pid']) is not int or raw['pid'] <= 0:
                    continue
                if any(not isinstance(raw[key], str) or not raw[key] for key in ('session_id', 'process_start', 'generation', 'cwd')):
                    continue
                if any(raw[key] is not None and not isinstance(raw[key], str) for key in ('tab_id', 'window_id', 'session_file')):
                    continue
                if not Path(raw['cwd']).is_absolute() or raw['session_file'] is not None and not Path(raw['session_file']).is_absolute():
                    continue
                result.append(raw)
            except (ValueError, OSError, KeyError, TypeError):
                continue
    except OSError:
        pass
    return result


def verified_identity(registry, observed):
    """Require independent SDK addresses/variable plus a private live birth match."""
    if type(observed) is not dict:
        return None
    matches = [record for record in read_identity_records(registry)
               if record == observed and process_start(record['pid']) == record['process_start']]
    return matches[0] if len(matches) == 1 else None


def process_image(pid):
    """Kernel executable identity for a previously observed shell, never name trust."""
    if sys.platform != 'darwin' or type(pid) is not int or not 0 < pid <= 0x7fffffff:
        return None
    try:
        probe = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True).proc_pidpath
        probe.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        probe.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(4096)
        if probe(pid, buffer, len(buffer)) <= 0:
            return None
        path = buffer.value.decode('utf-8')
        return path if path.startswith('/') and process_start(pid) is not None else None
    except (OSError, AttributeError, UnicodeError, ctypes.ArgumentError):
        return None


def foreground_state(pid, birth, tty):
    """One kernel BSD snapshot works even in the detached appearance worker."""
    import os
    device = tty_device(tty)
    if device is None or type(pid) is not int or not 0 < pid <= 0x7fffffff:
        return 'unknown'
    info = _read_bsdinfo(pid)
    if info is None:
        try:
            os.getpgid(pid)
        except ProcessLookupError:
            return 'departed'
        except OSError:
            pass
        return 'unknown'
    if _birth(pid, info) != birth:
        return 'unknown'
    if info.pbi_status in {4, 5} or info.e_tdev != (device & 0xffffffff):
        return 'departed'
    if (info.pbi_status not in {2, 3} or not 0 < info.pbi_pgid <= 0x7fffffff
            or not 0 < info.e_tpgid <= 0x7fffffff):
        return 'unknown'
    return 'foreground' if info.pbi_pgid == info.e_tpgid else 'departed'


def foreground_process(pid, birth, tty):
    """Stopped dialogs stay live, but cannot authorize appearance writes."""
    return foreground_state(pid, birth, tty) == 'foreground'


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
