"""Bounded read-only terminal inventory and independent SDK identity observation."""
import asyncio
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from runtime.terminal_identity import process_start, foreground_process, process_image, process_executable_path
from .omp_sessions import read_bindings


class Terminal:
    def __init__(self, executable: Path, runner, registry: Path | None = None):
        self.executable = str(executable)
        self.runner = runner
        self.registry = registry
        self.deadline = None

    def _execute(self, argv):
        budget = min(10, self.deadline-time.monotonic()) if self.deadline is not None else 10
        if budget <= 0:
            raise TimeoutError('Terminal observation deadline')
        return self.runner.run(argv, timeout=budget)

    def _run(self, argv):
        result = self._execute(argv)
        if result.returncode:
            raise ValueError('Terminal observation unavailable')
        return json.loads(result.stdout)

    def _list(self, kind):
        value = self._run([self.executable, kind, 'list', '--json'])
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError('Incomplete inventory')
        return value

    def profiles(self):
        return self._list('profile')

    def profile(self, name):
        value = self._run([self.executable, 'profile', 'show', name, '--json'])
        if not isinstance(value, dict):
            raise ValueError('Invalid profile')
        return value

    def variable(self, terminal, name):
        value = self._run([self.executable, 'session', 'get-var', name, '--session', terminal])
        if not isinstance(value, str):
            raise ValueError('Invalid variable')
        return value

    def job_pid(self, terminal):
        value = self._run([self.executable, 'session', 'get-var', 'session.jobPid', '--session', terminal])
        if type(value) is not int or value <= 0:
            raise ValueError('Invalid job PID')
        return value

    def panes(self):
        windows, tabs, sessions = (self._list(kind) for kind in ('window','tab','session'))
        def ids(items):
            values = [item.get('id') for item in items]
            if any(not isinstance(v,str) or not v for v in values) or len(values) != len(set(values)):
                raise ValueError('Invalid inventory identities')
            return set(values)
        wids, tids = ids(windows), ids(tabs)
        ids(sessions)
        positions = {}
        for tab in tabs:
            wid, index = tab.get('window_id'), tab.get('index')
            if wid not in wids or type(index) is not int or index < 0 or (wid,index) in positions.values():
                raise ValueError('Incomplete tab inventory')
            positions[tab['id']] = (wid,index)
        for wid in wids:
            indexes = sorted(index for window,index in positions.values() if window == wid)
            if not indexes or indexes != list(range(len(indexes))):
                raise ValueError('Incomplete window inventory')
        result = []
        for session in sessions:
            tid,wid = session.get('tab_id'),session.get('window_id')
            if tid not in tids or positions[tid][0] != wid:
                raise ValueError('Incomplete session inventory')
            result.append(dict(terminal_id=session['id'],tab_id=tid,window_id=wid))
        if {item['tab_id'] for item in result} != tids:
            raise ValueError('Missing sessions')
        return result

    def select_window(self, explicit, env):
        panes = self.panes()
        windows = {p['window_id'] for p in panes}
        if explicit:
            if explicit not in windows:
                raise ValueError('Target window unavailable')
            return explicit
        parents = [value.rsplit(':',1)[-1] for key in ('ITERM_SESSION_ID','TERM_SESSION_ID') if (value := env.get(key))]
        if parents:
            if len(set(parents)) != 1:
                raise ValueError('Conflicting parent addresses')
            matches = [p for p in panes if p['terminal_id'].lower() == parents[0].lower()]
            if len(matches) != 1:
                raise ValueError('Parent unavailable')
            return matches[0]['window_id']
        if len(windows) != 1:
            raise ValueError('Explicit window required')
        return next(iter(windows))

    def bindings(self):
        return read_bindings(self.registry) if self.registry else []

    process_start = staticmethod(process_start)
    foreground_process = staticmethod(foreground_process)
    process_image = staticmethod(process_image)
    process_executable_path = staticmethod(process_executable_path)

    def sdk_observe(self, terminal):
        return self._run([sys.executable,'-m','iterm2_utils.terminal',terminal])

    def observe(self, terminal):
        value = self.sdk_observe(terminal)
        if (not isinstance(value,dict) or value.get('terminal_id') != terminal or
                any(not isinstance(value.get(key),str) or not value[key] for key in ('tab_id','window_id'))):
            return None
        if not isinstance(value.get('identity'),str):
            return None
        try:
            raw = json.loads(value['identity'])
        except ValueError:
            return None
        if not isinstance(raw,dict):
            return None
        return {**raw, **{key:value[key] for key in ('terminal_id','tab_id','window_id')}}

    def complete_panes(self):
        before = self.panes()
        raw = self._run([sys.executable,'-m','iterm2_utils.terminal','--inventory'])
        after = self.panes()
        def addresses(rows):
            if not isinstance(rows,list):
                raise ValueError('Incomplete SDK inventory')
            values = [tuple(row[key] for key in ('terminal_id','tab_id','window_id')) for row in rows]
            if len(values) != len(set(values)):
                raise ValueError('Duplicate SDK inventory')
            return set(values)
        if addresses(before) != addresses(raw) or addresses(before) != addresses(after):
            raise ValueError('Changed or incomplete SDK inventory')
        return before

    def ordinary_shell(self, pane, zsh):
        """Exclude only a proven foreground zsh and its optional native login supervisor."""
        try:
            sample = self.sdk_observe(pane['terminal_id'])
            if (not isinstance(sample,dict) or any(sample.get(k) != v for k,v in pane.items())
                    or 'identity' not in sample or sample['identity'] is not None):
                return False
            root,pid,tty = sample.get('pid'),sample.get('job_pid'),sample.get('tty')
            if (type(root) is not int or not 0 < root <= 0x7fffffff or
                    type(pid) is not int or not 0 < pid <= 0x7fffffff or
                    not isinstance(tty,str) or not re.fullmatch(r'/dev/ttys[0-9]+',tty)):
                return False
            birth = self.process_start(pid)
            if not birth or Path(zsh).resolve() != Path('/bin/zsh').resolve():
                return False
            def text(argv, no_match=False):
                result = self._execute(argv)
                if result.stderr or (result.returncode and not (
                        no_match and result.returncode == 1 and not result.stdout)):
                    raise ValueError('TTY observation unavailable')
                if no_match and result.returncode == 0 and not result.stdout:
                    raise ValueError('Empty successful TTY observation')
                return result.stdout
            previous_rows = None
            births = {}
            for _ in range(2):
                if (self.process_start(pid) != birth or not self.foreground_process(pid,birth,tty)
                        or self.process_image(pid) != str(Path(zsh).resolve())):
                    return False
                if root != pid and self.process_executable_path(root) != '/usr/bin/login':
                    return False
                rows = {}
                for line in text(['/bin/ps','-t',tty,'-o','pid=,ppid=,uid=,state=']).splitlines():
                    fields = line.split()
                    if (len(fields) != 4 or any(not field.isdigit() for field in fields[:3])
                            or not re.fullmatch(r'[RSI][+N<>sLEW]*',fields[3])):
                        return False
                    process,parent,uid = map(int,fields[:3])
                    if (not 0 < process <= 0x7fffffff or not 0 <= parent <= 0x7fffffff or
                            process in rows or uid != (0 if process == root and root != pid else os.getuid())):
                        return False
                    rows[process] = (parent,uid,fields[3])
                if previous_rows is not None and rows != previous_rows:
                    return False
                previous_rows = rows
                if pid not in rows or root not in rows or root != pid and rows[pid][0] != root:
                    return False
                holders = text(['/usr/sbin/lsof','-nP','-t','+w','--',tty]).splitlines()
                if holders != [str(pid)]:
                    return False
                others = sorted(set(rows)-{pid,root})
                if others:
                    selected = ','.join(map(str,others))
                    canonical = text(['/bin/ps','-p',selected,'-o','pid=,tty=']).splitlines()
                    if sorted(line.split() for line in canonical) != sorted(
                            [[str(other),tty.removeprefix('/dev/')] for other in others]):
                        return False
                    for other in others:
                        observed_birth = self.process_start(other)
                        if not observed_birth or other in births and births[other] != observed_birth:
                            return False
                        births[other] = observed_birth
                    aliases = text(['/usr/sbin/lsof','-nP','-t','+w','-a','-p',selected,'--','/dev/tty'],True).splitlines()
                    if len(aliases) != len(set(aliases)):
                        return False
                    for alias in aliases:
                        if (not alias.isdigit() or int(alias) not in others or
                                self.process_image(int(alias)) != str(Path(zsh).resolve()) or
                                self.process_start(int(alias)) != births[int(alias)]):
                            return False
                if (self.sdk_observe(pane['terminal_id']) != sample or
                        self.job_pid(pane['terminal_id']) != pid or
                        self.variable(pane['terminal_id'],'tty') != tty or
                        self.process_start(pid) != birth or not self.foreground_process(pid,birth,tty)):
                    return False
                if root != pid and self.process_executable_path(root) != '/usr/bin/login':
                    return False
            return self.deadline is None or time.monotonic() < self.deadline
        except (OSError,ValueError,KeyError,TypeError,AttributeError,TimeoutError,subprocess.SubprocessError):
            return False


async def _observe(terminal):
    import iterm2
    connection = await iterm2.Connection.async_create()
    try:
        app = await iterm2.async_get_app(connection)
        matches = [(window,tab,session) for window in app.terminal_windows for tab in window.tabs
                   for session in tab.sessions if session.session_id == terminal]
        if len(matches) != 1:
            return None
        window,tab,session = matches[0]
        identity = await session.async_get_variable('user.iterm2_utils_omp')
        pid = await session.async_get_variable('session.pid') if identity is None else None
        job_pid = await session.async_get_variable('session.jobPid') if identity is None else None
        tty = await session.async_get_variable('tty') if identity is None else None
        return dict(terminal_id=session.session_id, tab_id=tab.tab_id, window_id=window.window_id,
                    identity=identity, pid=pid, job_pid=job_pid, tty=tty)
    finally:
        await connection.websocket.close()


def _visible_inventory(response):
    """Read the raw RPC tree; high-level visible sessions alone omit hidden panes."""
    if not response.HasField('list_sessions_response'):
        raise ValueError('Missing SDK envelope')
    snapshot = response.list_sessions_response
    if snapshot.buried_sessions:
        raise ValueError('Hidden sessions')
    result,windows,tabs,sessions,nodes = [],set(),set(),set(),{}
    def unique(value, seen):
        if not isinstance(value,str) or not value or value in seen:
            raise ValueError('Malformed SDK identities')
        seen.add(value)
        return value
    def visit(node, wid, tid, depth=0):
        if depth > 64 or id(node) in nodes or not node.links:
            raise ValueError('Malformed SDK tree')
        nodes[id(node)] = node
        for link in node.links:
            kind = link.WhichOneof('child')
            if kind == 'session':
                sid = unique(link.session.unique_identifier,sessions)
                result.append(dict(terminal_id=sid,tab_id=tid,window_id=wid))
            elif kind == 'node':
                visit(link.node,wid,tid,depth+1)
            else:
                raise ValueError('Missing SDK tree link')
    for window in snapshot.windows:
        wid = unique(window.window_id,windows)
        if not window.tabs:
            raise ValueError('Unsupported window')
        for tab in window.tabs:
            tid = unique(tab.tab_id,tabs)
            if (not tab.HasField('root') or tab.minimized_sessions or
                    tab.HasField('tmux_connection_id') or
                    tab.HasField('tmux_window_id') and tab.tmux_window_id != '-1'):
                raise ValueError('Incomplete visible tab')
            visit(tab.root,wid,tid)
            if not tab.active_session_id or not any(
                    p['terminal_id'] == tab.active_session_id and p['tab_id'] == tid for p in result):
                raise ValueError('Incomplete active session')
    return result


async def _inventory():
    import iterm2
    connection = await iterm2.Connection.async_create()
    try:
        return _visible_inventory(await iterm2.rpc.async_list_sessions(connection))
    finally:
        await connection.websocket.close()


if __name__ == '__main__':
    protocol = sys.stdout
    with open(os.devnull,'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
        try:
            async def bounded():
                async with asyncio.timeout(10):
                    return await (_inventory() if sys.argv[1] == '--inventory' else _observe(sys.argv[1]))
            value = asyncio.run(bounded())
        except (Exception,SystemExit):
            value = None
    protocol.write(json.dumps(value)+'\n')
