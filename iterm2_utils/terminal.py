"""Bounded read-only terminal inventory and independent SDK identity observation."""
import asyncio
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from runtime.terminal_identity import process_start
from .omp_sessions import read_bindings


class Terminal:
    def __init__(self, executable: Path, runner, registry: Path | None = None):
        self.executable = str(executable)
        self.runner = runner
        self.registry = registry
        self.deadline = None

    def _run(self, argv):
        budget = min(10, self.deadline-time.monotonic()) if self.deadline is not None else 10
        if budget <= 0:
            raise TimeoutError('Terminal observation deadline')
        result = self.runner.run(argv, timeout=budget)
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

    def sdk_observe(self, terminal):
        return self._run([sys.executable,'-m','iterm2_utils.terminal',terminal])

    def observe(self, terminal):
        value = self.sdk_observe(terminal)
        if not isinstance(value,dict) or value.get('terminal_id') != terminal:
            return None
        raw = json.loads(value['identity'])
        if not isinstance(raw,dict):
            return None
        return {**raw, **{key:value[key] for key in ('terminal_id','tab_id','window_id')}}


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
        return dict(terminal_id=session.session_id, tab_id=tab.tab_id, window_id=window.window_id, identity=identity)
    finally:
        await connection.websocket.close()


if __name__ == '__main__':
    protocol = sys.stdout
    with open(os.devnull,'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
        try:
            async def bounded():
                async with asyncio.timeout(10):
                    return await _observe(sys.argv[1])
            value = asyncio.run(bounded())
        except (Exception,SystemExit):
            value = None
    protocol.write(json.dumps(value)+'\n')
