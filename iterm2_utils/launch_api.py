"""One SDK create, supervised across synchronous SDK import and authorization."""
import asyncio
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import json
import math
import os
import sys
import time

from .models import Finding


_PREFLIGHT_SECONDS = 10
_CREATE_SECONDS = 30
_CLOSE_WORKER_SECONDS = 60


@dataclass(frozen=True)
class LaunchCreation:
    status: str
    window_id: str | None
    tab_id: str | None
    session_id: str | None
    deadline: float | None
    findings: tuple[Finding, ...]


def _identifier(value):
    if not isinstance(value, str) or not value or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid SDK identifier')
    return value


async def _operate(request, emit):
    connection = None
    sent = False
    try:
        emit({'phase': 'connect'})
        import iterm2
        async with asyncio.timeout(_PREFLIGHT_SECONDS):
            connection = await iterm2.Connection.async_create()
        emit({'phase': 'app'})
        async with asyncio.timeout(_PREFLIGHT_SECONDS):
            app = await iterm2.async_get_app(connection)
        emit({'phase': 'profiles'})
        async with asyncio.timeout(_PREFLIGHT_SECONDS):
            profiles = await iterm2.Profile.async_get(connection)
        matches = [p for p in profiles if p.name == request['profile']]
        if len(matches) != 1 or matches[0].guid != request['profile_guid']:
            return 'blocked'
        basis,parent=request.get('window_basis',('explicit',''))
        new_window=basis=='new'
        if new_window:
            if parent or request['window_id']!='':
                return 'blocked'
        else:
            window = app.get_window_by_id(request['window_id'])
            if window is None or window.window_id != request['window_id']:
                return 'blocked'
            if basis=='parent':
                matches=[w.window_id for w in app.terminal_windows for t in w.tabs for s in t.sessions
                         if s.session_id.lower()==parent.lower()]
                if matches != [request['window_id']]:return 'blocked'
            elif basis=='sole':
                if [w.window_id for w in app.terminal_windows] != [request['window_id']]:return 'blocked'
            elif basis!='explicit':
                return 'blocked'
        deadline = time.monotonic() + _CREATE_SECONDS
        # Publish uncertainty before the one possible mutation; cancellation is no rollback.
        emit({'phase': 'create', 'window_id': None if new_window else _identifier(window.window_id), 'deadline': deadline})
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            return 'blocked'
        sent = True
        async with asyncio.timeout(remaining):
            if new_window:
                window = await iterm2.Window.async_create(connection, profile=request['profile'], command=request['command'])
                if window is None:
                    return 'unknown'
                emit({'window_id': _identifier(window.window_id)})
                if len(window.tabs) != 1:
                    return 'unknown'
                tab = window.tabs[0]
            else:
                tab = await window.async_create_tab(profile=request['profile'], command=request['command'], select=True)
            emit({'tab_id': _identifier(tab.tab_id)})
            sessions = tab.all_sessions
            if len(sessions) != 1:
                return 'unknown'
            emit({'session_id': _identifier(sessions[0].session_id)})
        return 'created_unverified'
    except (Exception, SystemExit, asyncio.CancelledError):
        return 'unknown' if sent else 'blocked'
    finally:
        if connection is not None:
            try:
                async with asyncio.timeout(.2):
                    await connection.websocket.close()
            except (Exception, SystemExit, asyncio.CancelledError):
                pass


def _result(status, window_id=None, tab_id=None, session_id=None, deadline=None):
    message = ('The iTerm2 SDK or selected launch target is unavailable.' if status == 'blocked' else
               'Launch observations are incomplete. Inspect the known tab before taking further action.')
    findings = () if status == 'created_unverified' else (
        Finding('launch', 'omp', 'launch_'+status, 'unavailable', message),)
    return LaunchCreation(status, window_id, tab_id, session_id, deadline, findings)


async def create_tab(window_id: str, profile: str, profile_guid: str, command: str, *,
                     window_basis=('explicit',''),
                     on_window_progress: Callable[[dict[str, str]], None] | None = None) -> LaunchCreation:
    """Bound SDK auth in a same-Python helper; no retries or terminal cleanup."""
    child = None
    status = 'blocked'
    completed = False
    known_window = tab_id = session_id = deadline = None
    new_window = window_basis == ('new','')
    try:
        async with asyncio.timeout(_PREFLIGHT_SECONDS):
            child = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'iterm2_utils.launch_api',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=4096)
            child.stdin.write(json.dumps(dict(window_id=window_id, profile=profile,window_basis=window_basis,
                                             profile_guid=profile_guid, command=command)).encode()+b'\n')
            await child.stdin.drain()

        async def read(seconds):
            async with asyncio.timeout(max(0, seconds)):
                line = await child.stdout.readline()
            if len(line) > 4096 or not line.endswith(b'\n'):
                raise ValueError('Invalid helper frame')
            frame = json.loads(line)
            if not isinstance(frame, dict):
                raise ValueError('Invalid helper frame')
            return frame

        for phase in ('connect', 'app', 'profiles', 'create'):
            frame = await read(_PREFLIGHT_SECONDS)
            if frame == {'result': 'blocked'}:
                completed = True
                return _result('blocked')
            if phase != 'create':
                if frame != {'phase': phase}:
                    raise ValueError('Invalid helper phase')
                continue
            if frame.get('phase') != 'create':
                raise ValueError('Invalid helper phase')
            creation_deadline = frame.get('deadline')
            if (set(frame) != {'phase', 'window_id', 'deadline'} or frame['window_id'] != (None if new_window else window_id) or
                    isinstance(creation_deadline, bool) or not isinstance(creation_deadline, (float, int)) or
                    not math.isfinite(creation_deadline) or
                    not time.monotonic() < creation_deadline <= time.monotonic()+_CREATE_SECONDS):
                raise ValueError('Invalid creation frame')
            known_window = None if new_window else window_id
            deadline = creation_deadline
            status = 'unknown'
            child.stdin.write(b'create\n')
            await child.stdin.drain()
            child.stdin.close()

        for field in (('window_id', 'tab_id', 'session_id', 'result') if new_window else ('tab_id', 'session_id', 'result')):
            frame = await read(deadline-time.monotonic())
            if frame == {'result': 'unknown'}:
                completed = True
                break
            if field == 'result':
                if frame != {'result': 'created_unverified'}:
                    raise ValueError('Invalid helper result')
                status = 'created_unverified'
                completed = True
            elif set(frame) != {field}:
                raise ValueError('Invalid helper identifier')
            else:
                value = _identifier(frame[field])
                if field == 'window_id':
                    known_window = value
                    status = 'created_unverified'
                elif field == 'tab_id':
                    tab_id = value
                else:
                    session_id = value
                if new_window and on_window_progress is not None:
                    on_window_progress({field: value})
    except (Exception, asyncio.CancelledError):
        # Exceptions may contain SDK settings or command text; expose fixed findings only.
        pass
    finally:
        if child is not None:
            if not child.stdin.is_closing():
                child.stdin.close()
            if child.returncode is None:
                try:
                    if not completed:
                        try:
                            child.kill()
                        except ProcessLookupError:
                            pass
                    async with asyncio.timeout(.3):
                        await child.wait()
                except TimeoutError:
                    try:
                        child.kill()  # Only this SDK helper, never the created terminal/process.
                    except ProcessLookupError:
                        pass
                    await child.wait()
    return _result(status, known_window, tab_id, session_id, deadline)


@dataclass(frozen=True)
class TabClosure:
    status: str
    window_id: str
    tab_id: str
    session_id: str
    findings: tuple[Finding, ...]


def _close_inventory(response):
    """Account for every visible, minimized and buried native session identity."""
    if not response.HasField('list_sessions_response'):
        raise ValueError('Missing SDK envelope')
    snapshot = response.list_sessions_response
    windows, tabs, sessions, nodes = set(), {}, set(), {}

    def unique(value, seen):
        value = _identifier(value)
        if value in seen:
            raise ValueError('Duplicate SDK identity')
        return value

    def session(summary):
        sid = unique(summary.unique_identifier, sessions)
        sessions.add(sid)
        return sid

    def visit(node, visible, depth=0):
        if depth > 64 or id(node) in nodes or not node.links:
            raise ValueError('Malformed SDK tree')
        nodes[id(node)] = node
        for link in node.links:
            kind = link.WhichOneof('child')
            if kind == 'session':
                visible.append(session(link.session))
            elif kind == 'node':
                visit(link.node, visible, depth+1)
            else:
                raise ValueError('Missing SDK tree link')

    for window in snapshot.windows:
        wid = unique(window.window_id, windows)
        windows.add(wid)
        if not window.tabs:
            raise ValueError('Incomplete SDK window')
        for tab in window.tabs:
            tid = unique(tab.tab_id, tabs)
            if not tab.HasField('root'):
                raise ValueError('Incomplete SDK tab')
            visible = []
            visit(tab.root, visible)
            minimized = [session(summary) for summary in tab.minimized_sessions]
            if tab.active_session_id not in visible:
                raise ValueError('Incomplete active session')
            mux = (tab.HasField('tmux_connection_id') or
                   tab.HasField('tmux_window_id') and tab.tmux_window_id != '-1')
            tabs[tid] = (wid, visible, minimized, mux)
    for summary in snapshot.buried_sessions:
        session(summary)
    return tabs, sessions


async def _close_operate(request, emit):
    connection = None
    sent = False
    status = 'blocked'
    try:
        if set(request) != {'window_id', 'tab_id', 'session_id'}:
            raise ValueError('Invalid close request')
        wid, tid, sid = (_identifier(request[key]) for key in ('window_id','tab_id','session_id'))
        emit({'phase': 'connect'})
        import iterm2
        # Check the native operation before any mutation; no high-level close fallback.
        if not callable(iterm2.rpc.async_close):
            raise ValueError('Missing SDK close')
        async with asyncio.timeout(_PREFLIGHT_SECONDS):
            connection = await iterm2.Connection.async_create()
        emit({'phase': 'inventory'})
        async with asyncio.timeout(_PREFLIGHT_SECONDS):
            tabs, _ = _close_inventory(await iterm2.rpc.async_list_sessions(connection))
        if tabs.get(tid) != (wid, [sid], [], False):
            return 'blocked'
        emit({'phase': 'close'})
        async with asyncio.timeout(_CREATE_SECONDS):
            sent = True
            async with asyncio.timeout(_PREFLIGHT_SECONDS):
                response = await iterm2.rpc.async_close(connection, tabs=[tid], force=False)
            if not response.HasField('close_response'):
                raise ValueError('Missing SDK close response')
            statuses = list(response.close_response.statuses)
            if any(type(code) is not int for code in statuses):
                status = 'unknown'
            elif statuses in ([1], [2]):  # Native NOT_FOUND / USER_DECLINED are explicit refusals.
                status = 'blocked'
            elif statuses == [0]:
                async with asyncio.timeout(_PREFLIGHT_SECONDS):
                    tabs, sessions = _close_inventory(await iterm2.rpc.async_list_sessions(connection))
                status = 'closed' if tid not in tabs and sid not in sessions else 'unknown'
            else:
                status = 'unknown'
    except (Exception, SystemExit, asyncio.CancelledError):
        status = 'unknown' if sent else 'blocked'
    finally:
        if connection is not None:
            try:
                async with asyncio.timeout(.2):
                    await connection.websocket.close()
            except (Exception, SystemExit, asyncio.CancelledError):
                status = 'unknown'
    return status


def _closure(status, window_id, tab_id, session_id):
    message = ('The exact tab target or SDK is unavailable, or iTerm2 refused the close.' if status == 'blocked' else
               'Close outcome is uncertain. Inspect the exact IDs; do not retry automatically.')
    findings = () if status == 'closed' else (
        Finding('close', None, 'close_'+status,
                'unavailable' if status == 'blocked' else 'pending_ui', message),)
    return TabClosure(status, window_id, tab_id, session_id, findings)


async def close_tab(window_id: str, tab_id: str, session_id: str) -> TabClosure:
    """One exact native tab close in a bounded same-Python worker, never retried."""
    child = None
    status = 'blocked'
    try:
        request = dict(window_id=window_id, tab_id=tab_id, session_id=session_id)
        for value in request.values():
            _identifier(value)
        async with asyncio.timeout(_CLOSE_WORKER_SECONDS):
            child = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'iterm2_utils.launch_api', '--close',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=4096)
            status = 'unknown'
            child.stdin.write(json.dumps(request).encode()+b'\n')
            await child.stdin.drain()
            child.stdin.close()
            for phase in ('connect', 'inventory', 'close', 'result'):
                async with asyncio.timeout(_CREATE_SECONDS if phase == 'result' else _PREFLIGHT_SECONDS):
                    line = await child.stdout.readline()
                if len(line) > 4096 or not line.endswith(b'\n'):
                    raise ValueError('Invalid close worker frame')
                frame = json.loads(line)
                if frame in ({'result': 'blocked'}, {'result': 'unknown'}):
                    final = frame['result']
                    break
                if phase == 'result':
                    if frame != {'result': 'closed'}:
                        raise ValueError('Invalid close worker result')
                    final = 'closed'
                elif frame != {'phase': phase}:
                    raise ValueError('Invalid close worker phase')
            async with asyncio.timeout(_PREFLIGHT_SECONDS):
                if await child.stdout.read(1) or await child.wait() != 0:
                    raise ValueError('Failed close worker protocol')
            status = final
    except (Exception, asyncio.CancelledError):
        # Once spawned, timeout/protocol failure cannot establish that no RPC was sent.
        if child is not None:
            status = 'unknown'
    finally:
        if child is not None:
            if not child.stdin.is_closing():
                child.stdin.close()
            if child.returncode is None:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
            try:
                async with asyncio.timeout(.3):
                    await child.communicate()
            except (Exception, asyncio.CancelledError):
                status = 'unknown'
    return _closure(status, window_id, tab_id, session_id)


def _worker():
    protocol = sys.stdout
    with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
        def emit(frame):
            protocol.write(json.dumps(frame)+'\n')
            protocol.flush()
            if frame.get('phase') == 'create' and sys.stdin.readline() != 'create\n':
                raise ValueError('Creation was not acknowledged')
        try:
            request = json.loads(sys.stdin.readline())
            status = asyncio.run(_close_operate(request, emit) if sys.argv[1:] == ['--close']
                                 else _operate(request, emit))
        except (Exception, SystemExit):
            status = 'unknown' if sys.argv[1:] == ['--close'] else 'blocked'
        emit({'result': status})


if __name__ == '__main__':
    _worker()
