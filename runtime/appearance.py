"""Repository appearance rules, usable without the optional iTerm2 API."""

import argparse
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import threading
import time

try:
    from .terminal_identity import terminal_from_environment, terminal_id, tty_device as _tty_device, verified_identity, foreground_process, foreground_state, process_start, process_image
except ImportError:
    from terminal_identity import terminal_from_environment, terminal_id, tty_device as _tty_device, verified_identity, foreground_process, foreground_state, process_start, process_image


BUILTIN_ICONS = frozenset({
    'ios', 'android', 'kotlett', 'ios-mail', 'ios-cloud',
    'android-mail', 'android-cloud', 'chrome-mail', 'chrome-cloud',
})


def load_rules(path: Path) -> list[dict[str, str]]:
    """Validate rules and normalize physical roots without requiring mounted disks."""
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict) or set(document) != {'projects'}:
        raise ValueError('Appearance configuration must contain only projects')
    if not isinstance(document['projects'], list) or not document['projects']:
        raise ValueError('Appearance projects must be a nonempty list')
    rules = []
    roots = set()
    identities = set()
    for project in document['projects']:
        if not isinstance(project, dict) or set(project) != {'root', 'color', 'icon'}:
            raise ValueError('Appearance project must contain root, color and icon')
        if any(not isinstance(value, str) or '\x00' in value for value in project.values()):
            raise ValueError('Appearance project values must be strings without NUL')
        root = Path(project['root'])
        if not root.is_absolute():
            raise ValueError('Appearance root must be an absolute path')
        if re.fullmatch(r'#[0-9a-fA-F]{6}', project['color']) is None:
            raise ValueError('Appearance color must be #RRGGBB')
        icon = project['icon']
        if icon not in BUILTIN_ICONS and not (Path(icon).is_absolute() and Path(icon).suffix.lower() == '.png'):
            raise ValueError('Appearance icon must be a builtin name or absolute PNG path')
        try:
            root = root.resolve()
        except (OSError, RuntimeError):
            # Preserve unavailable rules; selection retries when the disk is available.
            pass
        identity = _directory_identity(root)
        if root in roots or identity is not None and identity in identities:
            raise ValueError('Appearance roots must be physically unique')
        roots.add(root)
        if identity is not None:
            identities.add(identity)
        rules.append({'root': str(root), 'color': project['color'].upper(), 'icon': icon})
    return rules


def _directory_identity(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
        return (info.st_dev, info.st_ino) if stat.S_ISDIR(info.st_mode) else None
    except (OSError, RuntimeError):
        return None


def select_rule(rules: list[dict[str, str]], cwd: Path) -> dict[str, str] | None:
    """Select the most specific available physical root containing cwd."""
    try:
        physical_cwd = cwd.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if _directory_identity(physical_cwd) is None:
        return None
    ancestors = {_directory_identity(path): index
                 for index, path in enumerate((physical_cwd, *physical_cwd.parents))}
    selected, distance = None, len(physical_cwd.parts)
    for rule in rules:
        identity = _directory_identity(Path(rule['root']))
        if identity is not None and ancestors.get(identity, distance) < distance:
            selected = rule
            distance = ancestors[identity]
    return selected


_HARD_SECONDS = 2.8
_API_TIMEOUT = 2.2
_WATCH_SECONDS = 1.5
_SNAPSHOT_VARIABLE = 'user.iterm2_utils_appearance_snapshot'
_APPEARANCE_KEYS = frozenset({
    'Tab Color', 'Tab Color (Light)', 'Tab Color (Dark)', 'Use Tab Color',
    'Use Tab Color (Light)', 'Use Tab Color (Dark)', 'Icon', 'Custom Icon Path',
})


def _valid_properties(value):
    return isinstance(value, dict) and set(value) == _APPEARANCE_KEYS


def _baseline(record):
    value = None if record is None else record.get('shell_baseline')
    if (not isinstance(value, dict) or set(value) != {'owner', 'properties', 'image', 'cwd'}
            or not _valid_properties(value['properties']) or type(value['image']) is not str
            or not value['image'].startswith('/') or type(value['cwd']) is not str
            or not value['cwd'].startswith('/')):
        return None
    owner = value['owner']
    if (type(owner) is not list or len(owner) != 4
            or any(type(item) is not kind for item, kind in zip(owner, (str, int, str, int)))):
        return None
    return value


def _baseline_refresh_allowed(record, launch_id, owner):
    return (record is None or 'main_owner' not in record
            or owner is not None and record['launch_id'] == launch_id
            and record['main_owner'] == list(owner))




class _TerminalMismatch(Exception):
    pass


class _API:
    """Optional official SDK; importing the rules module never imports it."""

    def __init__(self):
        import iterm2
        self.sdk = iterm2
        self.connection = None

    async def connect(self):
        self.connection = await self.sdk.Connection.async_create()

    async def find(self, terminal):
        app = await self.sdk.async_get_app(self.connection)
        return app.get_session_by_id(terminal)

    async def owns_terminal(self, session, device: int) -> bool:
        return session is not None and device is not None and _tty_device(
            await session.async_get_variable('tty')) == device

    async def main_identity(self, session, registry):
        if registry is None:
            return None
        app = await self.sdk.async_get_app(self.connection)
        matches = [(window, tab, candidate) for window in app.terminal_windows
                   for tab in window.tabs for candidate in tab.all_sessions
                   if candidate.session_id == session.session_id]
        if len(matches) != 1:
            return None
        window, tab, actual = matches[0]
        try:
            observed = json.loads(await actual.async_get_variable('user.iterm2_utils_omp'))
        except (ValueError, TypeError):
            return None
        if type(observed) is not dict:
            return None
        # Scope comes from the actual SDK tree, not stale embedded addresses.
        observed.update(terminal_id=terminal_id(actual.session_id),
                        tab_id=tab.tab_id, window_id=window.window_id)
        identity = verified_identity(registry, observed)
        return identity if identity is not None and foreground_process(
            identity['pid'], identity['process_start'], await actual.async_get_variable('tty')) else None

    async def write(self, session, color, icon):
        profile = self.sdk.LocalWriteOnlyProfile()
        rgb = self.sdk.Color(*(int(color[index:index + 2], 16) for index in (1, 3, 5)))
        # These variants preserve the profile's separate light/dark preference.
        profile.set_tab_color(rgb)
        profile.set_tab_color_light(rgb)
        profile.set_tab_color_dark(rgb)
        profile.set_use_tab_color(True)
        profile.set_use_tab_color_light(True)
        profile.set_use_tab_color_dark(True)
        profile.set_icon_mode(self.sdk.IconMode.CUSTOM)
        profile.set_custom_icon_path(icon)
        await session.async_set_profile_properties(profile)

    async def reset(self, session):
        profile = self.sdk.LocalWriteOnlyProfile()
        profile.set_use_tab_color(False)
        profile.set_use_tab_color_light(False)
        profile.set_use_tab_color_dark(False)
        profile.set_icon_mode(self.sdk.IconMode.NONE)
        profile.set_custom_icon_path('')
        await session.async_set_profile_properties(profile)

    async def snapshot(self, session):
        profile = await session.async_get_profile()
        values = profile.local_write_only_copy.values
        return {key: json.loads(values.get(key, 'null')) for key in _APPEARANCE_KEYS}

    async def _read_record(self, session):
        try:
            record = json.loads(await session.async_get_variable(_SNAPSHOT_VARIABLE))
            if (not isinstance(record, dict) or not {'launch_id', 'properties'} <= set(record)
                    or not set(record) <= {'launch_id', 'properties', 'shell_baseline', 'main_owner'}):
                return None
            return record
        except (ValueError, TypeError):
            return None

    async def save_snapshot(self, session, properties, launch_id, owner=None):
        async with self.sdk.Transaction(self.connection):
            baseline = _baseline(await self._read_record(session))
            record = {'launch_id': launch_id, 'properties': properties}
            if owner is not None:
                record['main_owner'] = list(owner)
            if baseline is not None:
                record['shell_baseline'] = baseline
            await session.async_set_variable(_SNAPSHOT_VARIABLE, json.dumps(record))

    async def save_baseline(self, session, properties, owner, image, cwd, *, launch_id=None, restored_owner=None):
        async with self.sdk.Transaction(self.connection):
            record = await self._read_record(session) or {'launch_id': None, 'properties': None}
            if not _baseline_refresh_allowed(record, launch_id, restored_owner):
                return False
            await session.async_set_variable(_SNAPSHOT_VARIABLE, json.dumps({
                **record, 'shell_baseline': {
                    'owner': owner, 'properties': properties, 'image': image, 'cwd': cwd}}))
            return True

    async def take_baseline(self, session, owner, cwd):
        baseline = _baseline(await self._read_record(session))
        return (baseline['properties'] if baseline is not None
                and baseline['owner'] == owner and baseline['cwd'] == cwd else None)

    async def baseline_image(self, session, owner):
        baseline = _baseline(await self._read_record(session))
        return baseline['image'] if baseline is not None and baseline['owner'] == owner else None

    async def can_refresh_baseline(self, session, launch_id, owner):
        return _baseline_refresh_allowed(await self._read_record(session), launch_id, owner)

    async def take_owner(self, session, launch_id):
        record = await self._read_snapshot_record(session, launch_id)
        owner = None if record is None else record.get('main_owner')
        if (type(owner) is list and len(owner) == 3
                and all(type(item) is kind for item, kind in zip(owner, (str, int, str)))):
            return tuple(owner)
        return None

    async def departed(self, owner, tty):
        return foreground_state(owner[1], owner[2], tty) == 'departed'

    async def invalidate_snapshot(self, session, *, keep_baseline=True):
        async with self.sdk.Transaction(self.connection):
            baseline = _baseline(await self._read_record(session)) if keep_baseline else None
            value = None if baseline is None else json.dumps({
                'launch_id': None, 'properties': None, 'shell_baseline': baseline})
            await session.async_set_variable(_SNAPSHOT_VARIABLE, value)

    async def _read_snapshot_record(self, session, launch_id):
        record = await self._read_record(session)
        return record if record is not None and record['launch_id'] == launch_id else None

    async def take_snapshot(self, session, launch_id):
        # Keep ownership until the return observer has finished using its snapshot.
        record = await self._read_snapshot_record(session, launch_id)
        properties = None if record is None else record['properties']
        if not _valid_properties(properties):
            return None
        return properties

    async def clear_snapshot(self, session, launch_id):
        async with self.sdk.Transaction(self.connection):
            record = await self._read_snapshot_record(session, launch_id)
            if record is not None:
                baseline = _baseline(record)
                value = None if baseline is None else json.dumps({
                    'launch_id': None, 'properties': None, 'shell_baseline': baseline})
                await session.async_set_variable(_SNAPSHOT_VARIABLE, value)

    async def restore(self, session, properties, launch_id):
        async with self.sdk.Transaction(self.connection):
            if await self.take_snapshot(session, launch_id) is None:
                return False
            await session.async_set_profile_properties(self.sdk.LocalWriteOnlyProfile(properties))
            return True

    async def write_if_current(self, session, color, icon, launch_id):
        async with self.sdk.Transaction(self.connection):
            if await self._read_snapshot_record(session, launch_id) is None:
                return False
            await self.write(session, color, icon)
            return True

    @asynccontextmanager
    async def watch(self, terminal):
        events = asyncio.Queue()
        tasks = []

        async def forward(monitor):
            while True:
                await monitor.async_get()
                events.put_nowait(None)

        async with AsyncExitStack() as stack:
            try:
                # jobName only wakes foreground revalidation (e.g. fg), never authorizes it.
                for name in ('user.iterm2_utils_omp', 'profileName', 'jobName'):
                    async with asyncio.timeout(_API_TIMEOUT):
                        monitor = await stack.enter_async_context(self.sdk.VariableMonitor(
                            self.connection, self.sdk.VariableScopes.SESSION, name, terminal))
                    tasks.append(asyncio.create_task(forward(monitor)))
                yield events
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self):
        if self.connection is not None:
            await self.connection.websocket.close()


def _launch_owner(identity):
    return None if identity is None else tuple(identity[key] for key in ('terminal_id', 'pid', 'process_start'))


async def _operate(request):
    api = None
    try:
        terminal, phase = request['terminal'], request['phase']
        command_scope = request.get('command_scope') is True
        if terminal_id(terminal) != terminal or phase not in {'shell', 'launch', 'return', 'probe'}:
            return 'unavailable'
        # Command lifetime is owned by the shell's cancel/reap fence, not an idle timer.
        async with asyncio.timeout(None if command_scope else _API_TIMEOUT):
            api = _API()
            async with asyncio.timeout(_API_TIMEOUT):
                await api.connect()
                session = await api.find(terminal)
            if session is None:
                return 'unavailable'
            if phase == 'probe':
                return 'ready'
            device, owned = request.get('device'), False

            async def require_ownership():
                nonlocal owned
                owned = False
                async with asyncio.timeout(_API_TIMEOUT):
                    if device is None or not await api.owns_terminal(session, device):
                        raise _TerminalMismatch()
                owned = True

            await require_ownership()
            registry = Path(request['registry']) if request.get('registry') else None
            shell_pid = request.get('shell_pid')
            shell_birth = process_start(shell_pid) if type(shell_pid) is int else None
            shell_owner = [terminal, shell_pid, shell_birth, device] if shell_birth is not None else None
            shell_image = None
            if shell_owner is not None:
                async with asyncio.timeout(_API_TIMEOUT):
                    shell_image = (process_image(shell_pid) if phase == 'shell' or request.get('armed')
                                   else await api.baseline_image(session, shell_owner))

            def shell_foreground():
                return (shell_owner is not None and shell_image is not None
                        and process_image(shell_pid) == shell_image
                        and foreground_process(shell_pid, shell_birth, request.get('tty')))

            async def refresh_baseline(restored_owner=None):
                if shell_owner is None:
                    return
                async with asyncio.timeout(_API_TIMEOUT):
                    await require_ownership()
                    if not await api.can_refresh_baseline(session, request.get('launch_id'), restored_owner):
                        return
                    if not shell_foreground() or await api.main_identity(session, registry) is not None:
                        return
                    properties = await api.snapshot(session)
                    await require_ownership()
                    if shell_foreground() and await api.main_identity(session, registry) is None:
                        await api.save_baseline(session, properties, shell_owner, shell_image, request.get('cwd'),
                                                launch_id=request.get('launch_id'), restored_owner=restored_owner)

            identity, preserved = None, None

            async def departed():
                return (identity is not None and identity[0] == terminal
                        and (shell_pid is None or shell_foreground())
                        and await api.departed(identity, request.get('tty'))
                        and await api.main_identity(session, registry) is None)

            async def write():
                await require_ownership()
                if phase == 'launch' and _launch_owner(await api.main_identity(session, registry)) != identity:
                    return False
                if phase == 'return' and not await departed():
                    return False
                if request.get('preserve'):
                    return await api.restore(session, preserved, request.get('launch_id'))
                if phase != 'shell':
                    return await api.write_if_current(session, request['color'], request['icon'], request.get('launch_id'))
                if request.get('reset'):
                    await api.reset(session)
                else:
                    await api.write(session, request['color'], request['icon'])
                return True

            if phase == 'shell':
                await api.invalidate_snapshot(session, keep_baseline=False)
                await write()
                await refresh_baseline()
                return 'applied'
            async with api.watch(terminal) as events:
                applied = False
                try:
                    async with asyncio.timeout(_API_TIMEOUT):
                        if phase == 'launch':
                            if command_scope and not request.get('armed'):
                                if shell_owner is None:
                                    return 'ignored'
                                baseline = await api.take_baseline(session, shell_owner, request.get('cwd'))
                                if baseline is None:
                                    return 'ignored'
                                if request.get('preserve'):
                                    preserved = baseline
                            else:
                                # Only the explicitly armed path waits before the agent starts.
                                if shell_pid is not None:
                                    if not shell_foreground():
                                        return 'ignored'
                                    await refresh_baseline()
                                    baseline = await api.take_baseline(session, shell_owner, request.get('cwd'))
                                    if baseline is None:
                                        return 'ignored'
                                    if request.get('preserve'):
                                        preserved = baseline
                                elif request.get('preserve'):
                                    preserved = await api.snapshot(session)
                                await require_ownership()
                                await api.invalidate_snapshot(session)
                        else:
                            identity = await api.take_owner(session, request.get('launch_id'))
                            if request.get('preserve'):
                                preserved = await api.take_snapshot(session, request.get('launch_id'))
                            if identity is None or request.get('preserve') and preserved is None:
                                await refresh_baseline()
                                return 'ignored'

                    async def reconcile():
                        nonlocal identity
                        async with asyncio.timeout(_API_TIMEOUT):
                            await require_ownership()
                            if phase == 'launch':
                                current = await api.main_identity(session, registry)
                                if current is None:
                                    return False
                                if identity is None:
                                    identity = _launch_owner(current)
                                    await require_ownership()
                                    await api.save_snapshot(session, preserved, request.get('launch_id'), identity)
                                if _launch_owner(current) != identity:
                                    return False
                            elif not await departed():
                                return False
                            changed = await write()
                            if phase == 'return' and changed:
                                await refresh_baseline(identity)
                            return changed

                    applied = await reconcile()
                    if 'ready_fd' in request:
                        ready_fd = request.pop('ready_fd')
                        try:
                            os.write(ready_fd, b'ready\n')
                        finally:
                            os.close(ready_fd)
                    loop = asyncio.get_running_loop()
                    stop = None if command_scope and identity is None else loop.time() + _WATCH_SECONDS
                    while True:
                        if stop is None:
                            await events.get()
                        else:
                            remaining = stop - loop.time()
                            if remaining <= 0:
                                break
                            try:
                                async with asyncio.timeout(remaining):
                                    await events.get()
                            except TimeoutError:
                                break
                        applied = await reconcile() or applied
                        if stop is None and identity is not None:
                            # The APS window starts at verified publication, never preexec.
                            stop = loop.time() + _WATCH_SECONDS
                    return 'applied' if applied else 'ignored' if request.get('preserve') else 'timeout'
                finally:
                    if phase == 'return' and owned and applied:
                        async with asyncio.timeout(_API_TIMEOUT):
                            if await departed():
                                await require_ownership()
                                await api.clear_snapshot(session, request.get('launch_id'))
    except _TerminalMismatch:
        return 'ignored'
    except TimeoutError:
        return 'timeout'
    except Exception:
        return 'unavailable'
    finally:
        if api is not None:
            try:
                async with asyncio.timeout(0.15):
                    await api.close()
            except Exception:
                pass


class _Cancelled(BaseException):
    pass


def _supervise(request, environment):
    """Bound SDK import/auth too; SIGTERM + wait is the launcher's cancel fence."""
    if threading.current_thread() is not threading.main_thread():
        return 'unavailable'
    started = time.monotonic()
    child = None
    ready_fd = None
    startup_read = None
    external_ready = None
    cancelled = False
    interrupted = False
    handlers = {}

    def cancel(_signum, _frame):
        nonlocal cancelled
        cancelled = True
        if child is not None:
            raise _Cancelled()

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            handlers[signum] = signal.signal(signum, cancel)
        if request.get('command_scope'):
            if 'ready_fd' in request:
                external_ready = os.dup(request['ready_fd'])
                request = {**request, 'armed': True}
            startup_read, ready_fd = os.pipe()
            request = {**request, 'ready_fd': ready_fd}
        elif 'ready_fd' in request:
            # Only a readiness duplicate reaches the worker; supervisor owns lifetime.
            ready_fd = os.dup(request['ready_fd'])
            request = {**request, 'ready_fd': ready_fd}
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).absolute()), '--worker'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment, start_new_session=True, text=True,
            pass_fds=() if ready_fd is None else (ready_fd,))
        if ready_fd is not None:
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGTERM, signal.SIGINT))
            try:
                os.close(ready_fd)
                ready_fd = None
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        if cancelled:
            raise _Cancelled()
        if startup_read is not None:
            child.stdin.write(json.dumps(request))
            child.stdin.close()
            child.stdin = None
            remaining = max(0, _HARD_SECONDS - (time.monotonic() - started))
            if not select.select([startup_read], [], [], remaining)[0]:
                raise subprocess.TimeoutExpired('appearance startup', _HARD_SECONDS)
            ready = os.read(startup_read, 6) == b'ready\n'
            if ready and external_ready is not None:
                os.write(external_ready, b'ready\n')
            # Watch the actual shell process and worker pipe, without idle polling.
            if ready:
                with select.kqueue() as lifetime:
                    lifetime.control([
                        select.kevent(request['shell_pid'], filter=select.KQ_FILTER_PROC,
                                      flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT),
                        select.kevent(child.stdout.fileno(), filter=select.KQ_FILTER_READ,
                                      flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT)], 0, 0)
                    event = lifetime.control(None, 1, None)[0]
                    if event.filter == select.KQ_FILTER_PROC:
                        interrupted = True
                        return 'ignored'
            output, _ = child.communicate(timeout=_HARD_SECONDS)
        else:
            output, _ = child.communicate(
                input=json.dumps(request), timeout=max(0, _HARD_SECONDS - (time.monotonic() - started)))
        allowed = {'ready', 'unavailable', 'timeout'} if request['phase'] == 'probe' else {'applied', 'ignored', 'unavailable', 'timeout'}
        result = output.strip()
        return result if child.returncode == 0 and result in allowed else 'unavailable'
    except subprocess.TimeoutExpired:
        interrupted = True
        return 'timeout'
    except (_Cancelled, OSError):
        interrupted = True
        return 'unavailable'
    finally:
        for signum in handlers:
            signal.signal(signum, signal.SIG_IGN)
        if ready_fd is not None:
            os.close(ready_fd)
        if startup_read is not None:
            os.close(startup_read)
        if external_ready is not None:
            os.close(external_ready)
        if child is not None:
            if interrupted or child.returncode is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            for stream in (child.stdin, child.stdout):
                if stream is not None:
                    stream.close()
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def apply(config: Path, cwd: Path, phase: str, *, environment: dict[str, str],
          ready_fd: int | None = None, launch_id: str | None = None,
          tty: str | None = None, registry: Path | None = None,
          shell_pid: int | None = None, command_scope: bool = False) -> str:
    """Apply this physical directory's rule to its explicit iTerm2 session."""
    terminal = terminal_from_environment(environment)
    if terminal is None or environment.get('TMUX'):
        return 'ignored'
    if phase not in {'shell', 'launch', 'return'}:
        return 'unavailable'
    request = {'terminal': terminal, 'phase': phase, 'config': str(config), 'cwd': str(cwd), 'tty': tty}
    if shell_pid is not None:
        if type(shell_pid) is not int or not 0 < shell_pid <= 0x7fffffff:
            return 'unavailable'
        request['shell_pid'] = shell_pid
    if command_scope:
        if phase != 'launch' or shell_pid is None:
            return 'unavailable'
        request['command_scope'] = True
    if registry is not None or environment.get('ITERM2_UTILS_IDENTITY_REGISTRY'):
        request['registry'] = str(registry or environment['ITERM2_UTILS_IDENTITY_REGISTRY'])
    if launch_id is not None:
        if not isinstance(launch_id, str) or re.fullmatch(r'[0-9]{1,20}-[0-9]{1,20}', launch_id) is None:
            return 'unavailable'
        request['launch_id'] = launch_id
    if ready_fd is not None:
        if phase != 'launch' or type(ready_fd) is not int or ready_fd < 3:
            return 'unavailable'
        request['ready_fd'] = ready_fd
    return _supervise(request, environment)


def _run_request(request):
    """Filesystem checks also run within the supervisor's hard deadline."""
    try:
        if request['phase'] != 'probe':
            device = _tty_device(request.get('tty'))
            if device is None:
                return 'ignored'
            request = {**request, 'device': device}
            rule = select_rule(load_rules(Path(request['config'])), Path(request['cwd']))
            if rule is None:
                if request['phase'] == 'shell':
                    request = {**request, 'reset': True}
                else:
                    request = {**request, 'preserve': True}
            else:
                icon = (Path(__file__).parent / 'assets' / 'appearance' / (rule['icon'] + '.png')
                        if rule['icon'] in BUILTIN_ICONS else Path(rule['icon']))
                if not icon.is_file():
                    return 'unavailable'
                request = {**request, 'color': rule['color'], 'icon': str(icon)}
        return asyncio.run(_operate(request))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        return 'unavailable'


def probe(*, environment: dict[str, str]) -> str:
    """Read-only connectivity check of the explicitly identified session."""
    terminal = terminal_from_environment(environment)
    if terminal is None or environment.get('TMUX'):
        return 'unavailable'
    return _supervise({'terminal': terminal, 'phase': 'probe'}, environment)


def _main():
    result = 'unavailable'
    try:
        if sys.argv[1:] == ['--worker']:
            request = json.loads(sys.stdin.read())
            # SDK diagnostics may include private details; emit only our status.
            with open(os.devnull, 'w') as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
                result = _run_request(request)
        else:
            parser = argparse.ArgumentParser(exit_on_error=False, add_help=False)
            parser.add_argument('--probe', action='store_true')
            parser.add_argument('--config', type=Path)
            parser.add_argument('--cwd', type=Path)
            parser.add_argument('--phase', choices=('shell', 'launch', 'return'))
            parser.add_argument('--ready-fd', type=int)
            parser.add_argument('--launch-id')
            parser.add_argument('--tty')
            parser.add_argument('--registry', type=Path)
            parser.add_argument('--shell-pid', type=int)
            parser.add_argument('--command-scope', action='store_true')
            with open(os.devnull, 'w') as quiet, redirect_stderr(quiet):
                args = parser.parse_args()
            if args.probe:
                result = probe(environment=dict(os.environ))
            elif args.config is not None and args.cwd is not None and args.phase:
                result = apply(args.config, args.cwd, args.phase, environment=dict(os.environ),
                               ready_fd=args.ready_fd, launch_id=args.launch_id, tty=args.tty,
                               registry=args.registry, shell_pid=args.shell_pid,
                               command_scope=args.command_scope)
    except (Exception, SystemExit):
        pass
    print(result)


if __name__ == '__main__':
    _main()
