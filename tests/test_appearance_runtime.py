import asyncio
import fcntl
from contextlib import asynccontextmanager
import json
import os
import pty
from pathlib import Path
import signal
import select
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from runtime import appearance


UUID = '12345678-1234-1234-1234-123456789ABC'
ENV = {'ITERM_SESSION_ID': 'w0t1p0:' + UUID}
DEVICE = os.stat('/dev/null').st_rdev


class AppearanceEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.config = self.repo / 'appearance.json'
        self.config.write_text(json.dumps({'projects': [
            {'root': str(self.repo), 'color': '#65A85A', 'icon': 'android-mail'}]}))

    def test_old_caller_without_tty_is_ignored_before_api_or_rules(self):
        with patch.object(appearance, '_supervise', side_effect=lambda request, env: appearance._run_request(request)), \
             patch.object(appearance, '_API') as api, patch.object(appearance, 'load_rules') as rules:
            for phase in ('shell', 'launch', 'return'):
                self.assertEqual(appearance.apply(self.config, self.repo, phase, environment=ENV), 'ignored')
            api.assert_not_called()
            rules.assert_not_called()

    def test_public_entrypoints_exist(self):
        self.assertTrue(callable(getattr(appearance, 'apply', None)))
        self.assertTrue(callable(getattr(appearance, 'probe', None)))

    def test_bad_or_conflicting_ids_do_not_start_worker(self):
        with patch.object(appearance, '_supervise') as worker:
            for env in ({}, {'ITERM_SESSION_ID': 'active'},
                        {**ENV, 'TERM_SESSION_ID': '00000000-0000-0000-0000-000000000000'}):
                self.assertEqual(appearance.apply(self.config, self.repo, 'shell', environment=env, tty='/dev/null'), 'ignored')
            worker.assert_not_called()

    def test_tmux_rejects_inherited_session_before_apply_or_probe(self):
        env = {**ENV, 'TERM_SESSION_ID': UUID, 'TMUX': '/fixture/tmux,42,0'}
        for call, expected in ((lambda: appearance.apply(self.config, self.repo, 'launch', environment=env, tty='/dev/null'), 'ignored'),
                               (lambda: appearance.probe(environment=env), 'unavailable')):
            with self.subTest(expected=expected), patch.object(appearance, '_supervise', return_value='wrong-session-worker') as worker:
                self.assertEqual(call(), expected)
                worker.assert_not_called()

    def test_absent_or_empty_tmux_keeps_explicit_session_available(self):
        for env in (ENV, {**ENV, 'TMUX': ''}):
            with self.subTest(env=env), patch.object(appearance, '_supervise', return_value='applied'):
                self.assertEqual(appearance.apply(self.config, self.repo, 'shell', environment=env, tty='/dev/null'), 'applied')
            with patch.object(appearance, '_supervise', return_value='ready'):
                self.assertEqual(appearance.probe(environment=env), 'ready')

    def test_invalid_readiness_and_launch_identity_do_not_start_worker(self):
        for arguments in ({'ready_fd': 0}, {'ready_fd': '3'}, {'launch_id': '../foreign'},
                          {'launch_id': '42-1\nprivate'}, {'launch_id': 1}):
            with self.subTest(arguments=arguments), patch.object(appearance, '_supervise') as worker:
                self.assertEqual(appearance.apply(self.config, self.repo, 'launch', environment=ENV, tty='/dev/null', **arguments), 'unavailable')
                worker.assert_not_called()

    def test_no_match_shell_requests_default_reset(self):
        with patch.object(appearance, '_supervise', side_effect=lambda request, env: appearance._run_request(request)), \
             patch.object(appearance, '_operate', new=AsyncMock(return_value='applied')) as operation:
            self.assertEqual(appearance.apply(self.config, Path('/'), 'shell', environment=ENV, tty='/dev/null'), 'applied')
        self.assertEqual(operation.call_args.args[0], {
            'terminal': UUID, 'phase': 'shell', 'config': str(self.config), 'cwd': '/', 'tty': '/dev/null', 'device': DEVICE, 'reset': True})

    def test_no_match_reset_still_requires_session_and_valid_config(self):
        with patch.object(appearance, '_supervise', side_effect=lambda request, env: appearance._run_request(request)), \
             patch.object(appearance, '_API') as api:
            for env in ({}, {**ENV, 'TMUX': '/fixture/tmux,42,0'}):
                with self.subTest(env=env):
                    self.assertEqual(appearance.apply(self.config, Path('/'), 'shell', environment=env, tty='/dev/null'), 'ignored')
            for contents in ('invalid JSON', '{"projects":[]}'):
                with self.subTest(contents=contents):
                    self.config.write_text(contents)
                    self.assertEqual(appearance.apply(self.config, Path('/'), 'shell', environment=ENV, tty='/dev/null'), 'unavailable')
            api.assert_not_called()

    def test_no_match_launch_and_return_reach_preservation_observer(self):
        with patch.object(appearance, '_supervise', side_effect=lambda request, env: appearance._run_request(request)), \
             patch.object(appearance, '_operate', new=AsyncMock(return_value='applied')) as operation:
            for phase in ('launch', 'return'):
                self.assertEqual(appearance.apply(self.config, Path('/'), phase, environment=ENV, tty='/dev/null'), 'applied')
                self.assertTrue(operation.call_args.args[0]['preserve'])

    def test_valid_rule_passes_explicit_uuid_and_builtin_path(self):
        with patch.object(appearance, '_supervise', side_effect=lambda request, env: appearance._run_request(request)), \
             patch.object(appearance, '_operate', new=AsyncMock(return_value='applied')) as operation:
            self.assertEqual(appearance.apply(self.config, self.repo, 'shell', environment=ENV, tty='/dev/null'), 'applied')
        request = operation.call_args.args[0]
        self.assertEqual(request['terminal'], UUID)
        self.assertEqual(request['icon'], str(Path(appearance.__file__).parent / 'assets/appearance/android-mail.png'))

    def test_filesystem_work_is_inside_supervised_worker(self):
        with patch.object(appearance, '_supervise', return_value='timeout') as worker, \
             patch.object(appearance, 'load_rules') as load, patch.object(appearance, '_tty_device') as tty:
            self.assertEqual(appearance.apply(self.config, self.repo, 'shell', environment=ENV, tty='/dev/null'), 'timeout')
        load.assert_not_called()
        tty.assert_not_called()
        self.assertEqual(worker.call_args.args, ({'terminal': UUID, 'phase': 'shell',
                         'config': str(self.config), 'cwd': str(self.repo), 'tty': '/dev/null'}, ENV))

    def test_missing_custom_icon_is_unavailable_without_connecting(self):
        self.config.write_text(json.dumps({'projects': [
            {'root': str(self.repo), 'color': '#65A85A', 'icon': str(self.repo / 'lost.png')}]}))
        with patch.object(appearance, '_supervise', side_effect=lambda request, env: appearance._run_request(request)), \
             patch.object(appearance, '_API') as api:
            self.assertEqual(appearance.apply(self.config, self.repo, 'shell', environment=ENV, tty='/dev/null'), 'unavailable')
            api.assert_not_called()

    def test_custom_icon_and_probe(self):
        icon = self.repo / 'custom.png'
        icon.write_bytes(b'png')
        self.config.write_text(json.dumps({'projects': [
            {'root': str(self.repo), 'color': '#65A85A', 'icon': str(icon)}]}))
        with patch.object(appearance, '_supervise', side_effect=lambda request, env: appearance._run_request(request)), \
             patch.object(appearance, '_operate', new=AsyncMock(return_value='applied')) as operation:
            appearance.apply(self.config, self.repo, 'return', environment=ENV, tty='/dev/null')
            self.assertEqual(operation.call_args.args[0]['icon'], str(icon))
        with patch.object(appearance, '_supervise', return_value='ready') as worker:
            self.assertEqual(appearance.probe(environment=ENV), 'ready')
            self.assertEqual(worker.call_args.args[0], {'terminal': UUID, 'phase': 'probe'})

    def test_invalid_config_and_phase_are_quiet_unavailable(self):
        self.config.write_text('private invalid contents')
        self.assertEqual(appearance.apply(self.config, self.repo, 'shell', environment=ENV, tty='/dev/null'), 'unavailable')
        self.assertEqual(appearance.apply(self.config, self.repo, 'other', environment=ENV, tty='/dev/null'), 'unavailable')

    def test_cli_invalid_input_has_only_status(self):
        result = subprocess.run([sys.executable, appearance.__file__, '--config', str(self.config),
                                 '--cwd', str(self.repo), '--phase', 'shell'],
                                env={}, capture_output=True, text=True, check=False)
        self.assertEqual(result.stdout, 'ignored\n')
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.returncode, 0)

    def test_cli_rejects_arguments_without_leaking_them(self):
        result = subprocess.run([sys.executable, appearance.__file__, '--secret-fixture=/private/path'],
                                env={}, capture_output=True, text=True, check=False)
        self.assertEqual((result.stdout, result.stderr, result.returncode), ('unavailable\n', '', 0))


class FakeAPI:
    def __init__(self):
        self.session = object()
        self.owns_terminal = AsyncMock(return_value=True)
        self.connect = AsyncMock()
        self.find = AsyncMock(return_value=self.session)
        self.write = AsyncMock()
        self.reset = AsyncMock(side_effect=self._reset)
        self.close = AsyncMock()
        self.main = 'zsh'
        self.generation = 'first'
        self.process_pid = 42
        self.events = asyncio.Queue()
        self.watching = False
        self.current = {'Tab Color': {'Red Component': .4}, 'Use Tab Color': True,
                        'Custom Icon Path': '/fixture/manual.png', 'Icon': 2}
        self.saved = None
        self.snapshot = AsyncMock(side_effect=lambda session: dict(self.current))
        self.baseline = None
        self.save_snapshot = AsyncMock(side_effect=self._save_snapshot)
        self.invalidate_snapshot = AsyncMock(side_effect=self._invalidate_snapshot)
        self.take_snapshot = AsyncMock(side_effect=self._take_snapshot)
        self.clear_snapshot = AsyncMock(side_effect=self._clear_snapshot)
        self.restore = AsyncMock(side_effect=self._restore)
        self.write_if_current = AsyncMock(side_effect=self._write_if_current)

    async def _reset(self, session):
        self.current.update({'Use Tab Color': False, 'Use Tab Color (Light)': False,
                             'Use Tab Color (Dark)': False, 'Icon': 0, 'Custom Icon Path': ''})

    async def _save_snapshot(self, session, properties, launch_id=None, owner=None):
        self.saved = (launch_id, None if properties is None else dict(properties))
        self.main_owner = owner

    async def _invalidate_snapshot(self, session, *, keep_baseline=True):
        self.saved = None
        if not keep_baseline:
            self.baseline = None

    async def _write_if_current(self, session, color, icon, launch_id=None):
        if self.saved is None or self.saved[0] != launch_id:
            return False
        await self.write(session, color, icon)
        return True

    async def _take_snapshot(self, session, launch_id=None):
        if self.saved is None or self.saved[0] != launch_id:
            return None
        return self.saved[1]

    async def _clear_snapshot(self, session, launch_id=None):
        if self.saved is not None and self.saved[0] == launch_id:
            self.saved = None

    async def _restore(self, session, properties, launch_id=None):
        if self.saved is None or self.saved[0] != launch_id:
            return False
        self.current = dict(properties)
        return True

    async def main_identity(self, session, registry):
        return {'terminal_id': UUID, 'pid': self.process_pid, 'process_start': 'birth',
                'generation': self.generation} if self.main == 'omp' else None

    async def save_baseline(self, session, properties, owner, image, cwd, **claim):
        self.baseline = (owner, dict(properties), image, cwd)

    async def take_baseline(self, session, owner, cwd):
        return dict(self.baseline[1]) if self.baseline and self.baseline[0] == owner and self.baseline[3] == cwd else None

    async def baseline_image(self, session, owner):
        return self.baseline[2] if self.baseline and self.baseline[0] == owner else None

    async def can_refresh_baseline(self, session, launch_id, owner):
        return self.saved is None or (owner is not None and self.saved[0] == launch_id
                                     and owner == self.main_owner)

    async def take_owner(self, session, launch_id):
        if self.saved is None or self.saved[0] != launch_id:
            return None
        return getattr(self, 'main_owner', None) or (UUID, 42, 'birth')

    async def departed(self, owner, tty):
        return self.main != 'omp'

    @asynccontextmanager
    async def watch(self, terminal):
        self.watching = True
        try:
            yield self.events
        finally:
            self.watching = False


class AppearanceOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.request = {'terminal': UUID, 'device': DEVICE, 'phase': 'shell', 'color': '#65A85A', 'icon': '/fixture/a.png'}
        self.factory = patch.object(appearance, '_API', return_value=self.api)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    async def test_foreign_or_missing_tty_never_mutates_session(self):
        for phase in ('shell', 'launch', 'return'):
            for matched in (False, True):
                for device in (None, 17):
                    with self.subTest(phase=phase, matched=matched, device=device):
                        api = FakeAPI()
                        api.owns_terminal.return_value = False
                        api.saved = ('42-1', dict(api.current))
                        original = api.saved
                        request = {**self.request, 'phase': phase, 'device': device,
                                   'launch_id': '42-1'}
                        if not matched:
                            request = {'terminal': UUID, 'phase': phase, 'device': device,
                                       'launch_id': '42-1',
                                       'reset' if phase == 'shell' else 'preserve': True}
                        with patch.object(appearance, '_API', return_value=api), \
                             patch.object(appearance, '_WATCH_SECONDS', .001):
                            self.assertEqual(await appearance._operate(request), 'ignored')
                        for name in ('write', 'reset', 'save_snapshot', 'invalidate_snapshot',
                                     'restore', 'clear_snapshot', 'write_if_current', 'snapshot', 'take_snapshot'):
                            getattr(api, name).assert_not_called()
                        self.assertEqual(api.saved, original)

    async def test_closed_session_cannot_mutate_or_clear_snapshot(self):
        self.api.saved = ('42-1', dict(self.api.current))
        original = self.api.saved
        self.api.find.return_value = None
        for phase in ('shell', 'launch', 'return'):
            with self.subTest(phase=phase):
                self.assertEqual(await appearance._operate({**self.request, 'phase': phase,
                                 'launch_id': '42-1', 'preserve': phase != 'shell'}), 'unavailable')
        for name in ('write', 'reset', 'save_snapshot', 'invalidate_snapshot',
                     'restore', 'clear_snapshot', 'write_if_current', 'snapshot', 'take_snapshot'):
            getattr(self.api, name).assert_not_called()
        self.assertEqual(self.api.saved, original)

    async def test_tty_read_error_or_timeout_cannot_mutate(self):
        for error, expected in ((RuntimeError('private tty error'), 'unavailable'),
                                (TimeoutError(), 'timeout')):
            with self.subTest(expected=expected):
                self.api.owns_terminal.side_effect = error
                self.assertEqual(await appearance._operate({**self.request, 'device': 17}), expected)
                self.api.invalidate_snapshot.assert_not_called()
                self.api.write.assert_not_called()

    async def test_lost_ownership_never_cleans_snapshot_even_if_later_read_would_match(self):
        self.api.saved = ('42-1', dict(self.api.current))
        original = self.api.saved
        self.api.owns_terminal.side_effect = [True, False, True]
        request = {**self.request, 'phase': 'return', 'launch_id': '42-1', 'preserve': True}
        self.assertEqual(await appearance._operate(request), 'ignored')
        self.api.restore.assert_not_called()
        self.api.clear_snapshot.assert_not_called()
        self.assertEqual(self.api.saved, original)
        self.assertEqual(self.api.owns_terminal.await_count, 2)

    async def test_ownership_read_error_before_write_also_skips_cleanup(self):
        self.api.saved = ('42-1', dict(self.api.current))
        original = self.api.saved
        self.api.owns_terminal.side_effect = [True, RuntimeError('closed session'), True]
        request = {**self.request, 'phase': 'return', 'launch_id': '42-1', 'preserve': True}
        self.assertEqual(await appearance._operate(request), 'unavailable')
        self.api.restore.assert_not_called()
        self.api.clear_snapshot.assert_not_called()
        self.assertEqual(self.api.saved, original)

    async def test_ownership_loss_before_snapshot_save_keeps_existing_snapshot(self):
        self.api.saved = ('old', dict(self.api.current))
        original = self.api.saved
        self.api.owns_terminal.side_effect = [True, False]
        request = {**self.request, 'phase': 'launch', 'preserve': True, 'launch_id': '42-1'}
        self.assertEqual(await appearance._operate(request), 'ignored')
        self.api.snapshot.assert_awaited_once()
        self.api.save_snapshot.assert_not_called()
        self.assertEqual(self.api.saved, original)

    async def test_observer_ownership_loss_blocks_deferred_write_and_cleanup(self):
        for phase in ('launch', 'return'):
            for preserve in (False, True):
                with self.subTest(phase=phase, preserve=preserve):
                    api = FakeAPI()
                    api.main = 'zsh' if phase == 'launch' else 'omp'
                    api.saved = ('42-1', dict(api.current) if preserve else None)
                    owned = True
                    api.owns_terminal.side_effect = lambda *args: owned
                    request = {**self.request, 'phase': phase, 'launch_id': '42-1', 'preserve': preserve}
                    async def drive():
                        nonlocal owned
                        while not api.watching:
                            await asyncio.sleep(0)
                        # Initial snapshot/write have finished before this event.
                        counts = [getattr(api, name).await_count for name in
                                  ('write', 'restore', 'write_if_current', 'clear_snapshot')]
                        saved = api.saved
                        owned = False
                        api.main = 'omp' if phase == 'launch' else 'zsh'
                        await api.events.put(None)
                        return counts, saved
                    driver = asyncio.create_task(drive())
                    try:
                        with patch.object(appearance, '_API', return_value=api), \
                             patch.object(appearance, '_WATCH_SECONDS', .02):
                            self.assertEqual(await appearance._operate(request), 'ignored')
                        counts, saved = await driver
                        self.assertEqual([getattr(api, name).await_count for name in
                                          ('write', 'restore', 'write_if_current', 'clear_snapshot')], counts)
                        self.assertEqual(api.saved, saved)
                    finally:
                        driver.cancel()
                        await asyncio.gather(driver, return_exceptions=True)

    async def test_ownership_loss_only_at_final_cleanup_preserves_snapshot(self):
        self.api.saved = ('42-1', dict(self.api.current))
        original = self.api.saved
        self.api.main = 'zsh'
        self.api.owns_terminal.side_effect = [True, True, True, False]
        with patch.object(appearance, '_WATCH_SECONDS', .001):
            self.assertEqual(await appearance._operate({**self.request, 'phase': 'return',
                             'preserve': True, 'launch_id': '42-1'}), 'ignored')
        self.api.clear_snapshot.assert_not_called()
        self.api.restore.assert_awaited_once()
        self.assertEqual(self.api.saved, original)

    async def test_tty_read_deadline_is_quiet_and_never_mutates(self):
        async def blocked(*args):
            await asyncio.Future()
        self.api.owns_terminal.side_effect = blocked
        with patch.object(appearance, '_API_TIMEOUT', .01):
            self.assertEqual(await appearance._operate(self.request), 'timeout')
        self.api.invalidate_snapshot.assert_not_called()
        self.api.write.assert_not_called()

    async def test_explicit_session_only_and_cleanup(self):
        self.assertEqual(await appearance._operate(self.request), 'applied')
        self.api.find.assert_awaited_once_with(UUID)
        self.api.write.assert_awaited_once_with(self.api.session, '#65A85A', '/fixture/a.png')
        self.api.close.assert_awaited_once()

    async def test_default_reset_uses_only_explicit_session(self):
        request = {'terminal': UUID, 'device': DEVICE, 'phase': 'shell', 'reset': True}
        with patch.object(self.api, 'watch') as watch:
            self.assertEqual(await appearance._operate(request), 'applied')
        watch.assert_not_called()
        self.api.find.assert_awaited_once_with(UUID)
        self.api.reset.assert_awaited_once_with(self.api.session)
        self.api.write.assert_not_called()
        self.assertFalse(self.api.watching)
        self.api.close.assert_awaited_once()

    async def test_default_reset_missing_session_or_invalid_uuid_cannot_write(self):
        request = {'terminal': UUID, 'device': DEVICE, 'phase': 'shell', 'reset': True}
        self.api.find.return_value = None
        self.assertEqual(await appearance._operate(request), 'unavailable')
        self.assertEqual(await appearance._operate({**request, 'terminal': 'active'}), 'unavailable')
        self.api.reset.assert_not_called()
        self.api.write.assert_not_called()

    async def test_default_reset_waits_for_native_write_and_reports_errors(self):
        request = {'terminal': UUID, 'device': DEVICE, 'phase': 'shell', 'reset': True}
        started, released = asyncio.Event(), asyncio.Event()
        async def delayed(session):
            started.set()
            await released.wait()
        self.api.reset.side_effect = delayed
        operation = asyncio.create_task(appearance._operate(request))
        try:
            await asyncio.sleep(0)
            self.assertTrue(started.is_set(), 'native reset was not awaited')
            self.assertFalse(operation.done())
            released.set()
            self.assertEqual(await operation, 'applied')
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        self.api.reset.side_effect = RuntimeError('private API details')
        self.assertEqual(await appearance._operate(request), 'unavailable')

    async def test_probe_never_writes(self):
        self.request = {'terminal': UUID, 'phase': 'probe'}
        self.assertEqual(await appearance._operate(self.request), 'ready')
        self.api.write.assert_not_called()
        self.api.owns_terminal.assert_not_called()

    async def test_missing_session_and_denial(self):
        self.api.find.return_value = None
        self.assertEqual(await appearance._operate(self.request), 'unavailable')
        self.api.write.assert_not_called()
        self.api.find.return_value = self.api.session
        self.api.write.side_effect = RuntimeError('private details')
        self.assertEqual(await appearance._operate(self.request), 'unavailable')
        self.assertEqual(self.api.close.await_count, 2)

    async def test_absent_sdk_is_unavailable(self):
        with patch.object(appearance, '_API', side_effect=ImportError):
            self.assertEqual(await appearance._operate(self.request), 'unavailable')

    async def test_connect_deadline_and_cleanup(self):
        async def blocked():
            await asyncio.Future()
        self.api.connect.side_effect = blocked
        with patch.object(appearance, '_API_TIMEOUT', 0.01):
            self.assertEqual(await appearance._operate(self.request), 'timeout')
        self.api.close.assert_awaited_once()

    async def run_event_case(self, phase, initial_job, events):
        self.request['phase'] = phase
        self.api.main = initial_job
        if phase == 'return':
            self.api.saved = (self.request.get('launch_id'), None)
        async def drive():
            while not self.api.watching:
                await asyncio.sleep(0)
            for job in events:
                self.api.main = job
                await self.api.events.put(None)
                # Wait for the event handler to observe the current job.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
        driver = asyncio.create_task(drive())
        with patch.object(appearance, '_WATCH_SECONDS', 0.02):
            result = await appearance._operate(self.request)
        await driver
        self.assertFalse(self.api.watching)
        self.api.close.assert_awaited_once()
        return result

    async def test_bun_shell_names_and_stale_identity_never_authorize_launch_writes(self):
        for unverified in ('bun', 'omp-name-only', 'stale-generation', 'zsh'):
            self.api.main = unverified
            with patch.object(appearance, '_WATCH_SECONDS', .001):
                self.assertEqual(await appearance._operate({**self.request, 'phase': 'launch'}), 'timeout')
            self.api.write.assert_not_called()
            self.api.save_snapshot.assert_not_called()

    async def test_launch_reapplies_after_aps_profile_change(self):
        self.assertEqual(await self.run_event_case('launch', 'zsh', ['omp', 'omp']), 'applied')
        self.assertEqual(self.api.write.await_count, 2)

    async def test_same_process_switch_generation_reapplies_after_profile_reset(self):
        self.api.main = 'omp'
        reset = asyncio.Event()
        async def write(session, color, icon):
            self.api.current = {'color': color, 'icon': icon}
            reset.set()
        self.api.write.side_effect = write
        request = {**self.request, 'phase': 'launch', 'launch_id': '42-1'}
        async def switch():
            await reset.wait()
            reset.clear()
            self.api.generation = 'second-dialog-generation'
            self.api.current = {'profile-reset': True}
            await self.api.events.put(None)
            await reset.wait()
        driver = asyncio.create_task(switch())
        try:
            with patch.object(appearance, '_WATCH_SECONDS', .05):
                self.assertEqual(await appearance._operate(request), 'applied')
            await asyncio.wait_for(driver, 1)
            self.assertEqual(self.api.current, {'color': '#65A85A', 'icon': '/fixture/a.png'})
            self.assertEqual(self.api.write.await_count, 2)
            self.assertEqual(self.api.save_snapshot.await_count, 1)
        finally:
            driver.cancel()
            await asyncio.gather(driver, return_exceptions=True)

    async def test_replacement_process_cannot_inherit_the_original_launch_claim(self):
        self.api.main = 'omp'
        first = asyncio.Event()
        self.api.write.side_effect = lambda *args: first.set()
        async def replace():
            await first.wait()
            self.api.process_pid = 43
            self.api.generation = 'replacement'
            self.api.current = {'replacement-aps': True}
            await self.api.events.put(None)
        driver = asyncio.create_task(replace())
        with patch.object(appearance, '_WATCH_SECONDS', .02):
            self.assertEqual(await appearance._operate({**self.request, 'phase': 'launch'}), 'applied')
        await driver
        self.assertEqual(self.api.write.await_count, 1)
        self.assertEqual(self.api.current, {'replacement-aps': True})
        self.assertEqual(self.api.main_owner, (UUID, 42, 'birth'))

    async def test_publication_gap_is_not_positive_foreground_departure(self):
        original = dict(self.api.current)
        self.api.saved = ('42-1', original)
        self.api.main = 'omp'
        self.api.current = {'during-switch': True}
        with patch.object(self.api, 'main_identity', new=AsyncMock(return_value=None)), \
             patch.object(appearance, '_WATCH_SECONDS', .001):
            result = await appearance._operate(dict(terminal=UUID, device=DEVICE, phase='return',
                                                    preserve=True, launch_id='42-1'))
        self.assertEqual(result, 'ignored')
        self.assertEqual(self.api.current, {'during-switch': True})
        self.api.restore.assert_not_awaited()
        self.api.clear_snapshot.assert_not_awaited()
        self.assertEqual(self.api.saved, ('42-1', original))

    async def test_immediate_main_uses_only_a_proven_matching_shell_baseline(self):
        original = dict(self.api.current)
        for birth, expected in (('shell-birth', 'applied'), ('foreign-birth', 'ignored')):
            self.api.main = 'omp'
            self.api.current = {'agent-aps': True}
            self.api.baseline = ([UUID, 42, birth, DEVICE], original, '/fixture/zsh', '/fixture/cwd')
            with patch.object(appearance, 'process_start', return_value='shell-birth'), \
                 patch.object(appearance, 'process_image', return_value='/fixture/zsh'), \
                 patch.object(appearance, 'foreground_process', return_value=False), \
                 patch.object(appearance, '_WATCH_SECONDS', .001):
                result = await appearance._operate(dict(terminal=UUID, device=DEVICE, tty='/dev/null',
                    phase='launch', command_scope=True, cwd='/fixture/cwd', shell_pid=42, preserve=True, launch_id='42-1'))
            self.assertEqual(result, expected)
            self.assertEqual(self.api.current, original if expected == 'applied' else {'agent-aps': True})
        self.api.snapshot.assert_not_awaited()

    async def test_exec_replacement_does_not_refresh_a_shell_baseline_in_publication_gap(self):
        original = dict(self.api.current)
        self.api.baseline = ([UUID, 42, 'shell-birth', DEVICE], original, '/fixture/zsh', '/fixture/cwd')
        self.api.current = {'agent-aps': True}
        with patch.object(appearance, 'process_start', return_value='shell-birth'), \
             patch.object(appearance, 'process_image', return_value='/fixture/other-executable'), \
             patch.object(appearance, 'foreground_process', return_value=True):
            self.assertEqual(await appearance._operate(dict(terminal=UUID, device=DEVICE, tty='/dev/null',
                             phase='return', shell_pid=42, preserve=True, launch_id='42-1')), 'ignored')
        self.api.snapshot.assert_not_awaited()
        self.assertEqual(self.api.baseline[1], original)

    async def test_pending_previous_return_cannot_become_a_new_shell_original(self):
        original = dict(self.api.current)
        self.api.baseline = ([UUID, 42, 'shell-birth', DEVICE], original, '/fixture/zsh', '/fixture/cwd')
        self.api.saved = ('old-command', original)
        self.api.main_owner = (UUID, 91, 'birth')
        self.api.current = {'previous-agent-aps': True}
        with patch.object(appearance, 'process_start', return_value='shell-birth'), \
             patch.object(appearance, 'process_image', return_value='/fixture/zsh'), \
             patch.object(appearance, 'foreground_process', return_value=True):
            self.assertEqual(await appearance._operate(dict(terminal=UUID, device=DEVICE, tty='/dev/null',
                cwd='/fixture/cwd', phase='return', shell_pid=42, preserve=True, launch_id='new-command')), 'ignored')
        self.api.snapshot.assert_not_awaited()
        self.assertEqual(self.api.baseline[1], original)
        self.assertEqual(self.api.saved, ('old-command', original))

    async def delayed_publication_case(self, delay, armed=False):
        original = dict(self.api.current)
        self.api.process_pid = 91
        if not armed:
            self.api.baseline = ([UUID, 42, 'shell-birth', DEVICE], original, '/fixture/zsh', '/fixture/cwd')
        read_fd, write_fd = os.pipe()
        request = dict(terminal=UUID, device=DEVICE, tty='/dev/null', phase='launch',
                       command_scope=True, cwd='/fixture/cwd', shell_pid=42, preserve=True, launch_id='42-1',
                       ready_fd=write_fd)
        if armed:
            request['armed'] = True
        with patch.object(appearance, 'process_start', return_value='shell-birth'), \
             patch.object(appearance, 'process_image', return_value='/fixture/zsh'), \
             patch.object(appearance, 'foreground_process', side_effect=lambda *a: self.api.main != 'omp'), \
             patch.object(appearance, '_WATCH_SECONDS', .001):
            task = asyncio.create_task(appearance._operate(request))
            try:
                self.assertEqual(await asyncio.to_thread(os.read, read_fd, 6), b'ready\n')
                # Actual publication is deliberately later than the old pre-command window.
                await asyncio.sleep(delay)
                self.assertFalse(task.done())
                self.api.current = {'agent-aps': True}
                self.api.main = 'omp'
                await self.api.events.put(None)
                self.assertEqual(await asyncio.wait_for(task, 2), 'applied')
                self.assertEqual(self.api.current, original)
                self.api.main = 'zsh'
                self.api.current = {'return-aps': True}
                returned = {key: value for key, value in request.items()
                            if key not in {'command_scope', 'ready_fd', 'armed'}}
                self.assertEqual(await appearance._operate({**returned, 'phase': 'return'}), 'applied')
                self.assertEqual(self.api.current, original)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                os.close(read_fd)

    async def test_delayed_command_start_preserves_styling_and_outside_originals(self):
        await self.delayed_publication_case(2)

    async def test_delayed_identity_publication_preserves_styling_and_outside_originals(self):
        await self.delayed_publication_case(3, armed=True)

    async def test_return_observes_shell_aps_reversal(self):
        self.assertEqual(await self.run_event_case('return', 'omp', ['zsh', 'zsh']), 'applied')
        self.assertEqual(self.api.write.await_count, 2)

    async def test_early_exit_stale_event_does_not_write(self):
        self.assertEqual(await self.run_event_case('launch', 'zsh', ['zsh']), 'timeout')
        self.api.write.assert_not_called()

    async def test_no_match_preserves_manual_snapshot_across_launch_and_return(self):
        expected = dict(self.api.current)
        self.request = {'terminal': UUID, 'device': DEVICE, 'phase': 'launch', 'preserve': True}
        async def launch():
            while not self.api.watching:
                await asyncio.sleep(0)
            self.api.current = {'Use Tab Color': False, 'Custom Icon Path': ''}
            self.api.main = 'omp'
            await self.api.events.put(None)
        driver = asyncio.create_task(launch())
        try:
            with patch.object(appearance, '_WATCH_SECONDS', .02):
                self.assertEqual(await appearance._operate(self.request), 'applied')
            await driver
            self.assertEqual(self.api.current, expected)
            self.api.current = {'Use Tab Color': False, 'Custom Icon Path': ''}
            self.api.main = 'zsh'
            with patch.object(appearance, '_WATCH_SECONDS', .02):
                self.assertEqual(await appearance._operate({**self.request, 'phase': 'return'}), 'applied')
            self.assertEqual(self.api.current, expected)
            self.assertIsNone(self.api.saved)
            self.api.write.assert_not_called()
        finally:
            driver.cancel()
            await asyncio.gather(driver, return_exceptions=True)

    async def test_default_survives_no_match_omp_aps_and_return(self):
        self.assertEqual(await appearance._operate({'terminal': UUID, 'device': DEVICE, 'phase': 'shell', 'reset': True}), 'applied')
        expected = {'Tab Color': {'Red Component': .4}, 'Use Tab Color': False,
                    'Use Tab Color (Light)': False, 'Use Tab Color (Dark)': False,
                    'Custom Icon Path': '', 'Icon': 0}
        self.assertEqual(self.api.current, expected)
        request = {'terminal': UUID, 'device': DEVICE, 'phase': 'launch', 'preserve': True, 'launch_id': '42-1'}
        async def launch():
            while not self.api.watching:
                await asyncio.sleep(0)
            self.api.current = {'Use Tab Color': True, 'Use Tab Color (Light)': True,
                                'Use Tab Color (Dark)': True, 'Icon': 2, 'Custom Icon Path': '/fixture/omp.png'}
            self.api.main = 'omp'
            await self.api.events.put(None)
        driver = asyncio.create_task(launch())
        try:
            with patch.object(appearance, '_WATCH_SECONDS', .02):
                self.assertEqual(await appearance._operate(request), 'applied')
            await driver
            self.assertEqual(self.api.current, expected)
            self.api.current = {'Use Tab Color': True, 'Icon': 2, 'Custom Icon Path': '/fixture/shell.png'}
            self.api.main = 'zsh'
            with patch.object(appearance, '_WATCH_SECONDS', .02):
                self.assertEqual(await appearance._operate({**request, 'phase': 'return'}), 'applied')
            self.assertEqual(self.api.current, expected)
            self.assertIsNone(self.api.saved)
            self.api.reset.assert_awaited_once_with(self.api.session)
            self.api.write.assert_not_called()
        finally:
            driver.cancel()
            await asyncio.gather(driver, return_exceptions=True)

    async def test_new_shell_target_invalidates_an_old_preserved_return(self):
        old_properties = dict(self.api.current)
        for reset in (False, True):
            with self.subTest(reset=reset):
                self.api.saved = ('42-1', old_properties)
                self.api.current = dict(old_properties)
                expected = {'Use Tab Color': True, 'Custom Icon Path': '/fixture/new-project.png'}
                shell_request = {**self.request, 'icon': expected['Custom Icon Path']}
                if reset:
                    shell_request = {'terminal': UUID, 'device': DEVICE, 'phase': 'shell', 'reset': True}
                    expected = {**old_properties, 'Use Tab Color': False, 'Use Tab Color (Light)': False,
                                'Use Tab Color (Dark)': False, 'Icon': 0, 'Custom Icon Path': ''}
                async def assign(session, color, icon):
                    self.api.current = {'Use Tab Color': True, 'Custom Icon Path': icon}
                self.api.write.side_effect = assign
                async def take_then_shell(session, launch_id):
                    properties = await self.api._take_snapshot(session, launch_id)
                    self.assertEqual(await appearance._operate(shell_request), 'applied')
                    return properties
                self.api.take_snapshot.side_effect = take_then_shell
                request = {'terminal': UUID, 'device': DEVICE, 'phase': 'return', 'preserve': True, 'launch_id': '42-1'}
                with patch.object(appearance, '_WATCH_SECONDS', .001):
                    self.assertEqual(await appearance._operate(request), 'ignored')
                self.assertEqual(self.api.current, expected)

    async def test_new_shell_target_blocks_late_matched_return_assignment(self):
        for launch_id in ('42-1', None):
            for reset in (False, True):
                with self.subTest(launch_id=launch_id, reset=reset):
                    self.api.saved = (launch_id, None)
                    old_writes = []
                    async def assign(session, color, icon):
                        self.api.current = {'Use Tab Color': True, 'Custom Icon Path': icon}
                        if icon == '/fixture/old-project.png':
                            old_writes.append(icon)
                    self.api.write.side_effect = assign
                    old_request = {**self.request, 'phase': 'return', 'launch_id': launch_id,
                                   'icon': '/fixture/old-project.png'}
                    with patch.object(appearance, '_WATCH_SECONDS', .02):
                        observer = asyncio.create_task(appearance._operate(old_request))
                        try:
                            await asyncio.sleep(0)
                            self.assertEqual(old_writes, ['/fixture/old-project.png'])
                            shell = ({'terminal': UUID, 'device': DEVICE, 'phase': 'shell', 'reset': True} if reset
                                     else {**self.request, 'icon': '/fixture/new-project.png'})
                            self.assertEqual(await appearance._operate(shell), 'applied')
                            expected = dict(self.api.current)
                            await self.api.events.put(None)
                            self.assertEqual(await observer, 'applied')
                            self.assertEqual(self.api.current, expected)
                            self.assertEqual(old_writes, ['/fixture/old-project.png'])
                        finally:
                            observer.cancel()
                            await asyncio.gather(observer, return_exceptions=True)

    async def test_no_match_without_transition_does_not_reassign_manual_style(self):
        expected = dict(self.api.current)
        self.request = {'terminal': UUID, 'device': DEVICE, 'phase': 'launch', 'preserve': True}
        with patch.object(appearance, '_WATCH_SECONDS', .01):
            self.assertEqual(await appearance._operate(self.request), 'ignored')
        self.assertEqual(self.api.current, expected)
        self.api.restore.assert_not_called()

    async def test_no_match_return_without_snapshot_leaves_session_untouched(self):
        self.request = {'terminal': UUID, 'device': DEVICE, 'phase': 'return', 'preserve': True}
        self.assertEqual(await appearance._operate(self.request), 'ignored')
        self.api.restore.assert_not_called()

    async def test_failed_new_launch_cannot_restore_an_older_snapshot(self):
        request = {'terminal': UUID, 'device': DEVICE, 'phase': 'launch', 'preserve': True, 'launch_id': '42-1'}
        with patch.object(appearance, '_WATCH_SECONDS', .001):
            await appearance._operate(request)
            self.api.current = {'Use Tab Color': False, 'Custom Icon Path': '/fixture/new-manual.png'}
            self.assertEqual(await appearance._operate({**request, 'phase': 'return', 'launch_id': '42-2'}), 'ignored')
        self.assertEqual(self.api.current, {'Use Tab Color': False, 'Custom Icon Path': '/fixture/new-manual.png'})

    async def test_newer_snapshot_or_matched_claim_after_read_blocks_old_return(self):
        old_properties = dict(self.api.current)
        newer_properties = {'Use Tab Color': False, 'Custom Icon Path': '/fixture/newer.png'}
        for snapshot in (newer_properties, None):
            with self.subTest(snapshot=snapshot):
                self.api.saved = ('42-1', old_properties)
                async def take_then_replace(session, launch_id):
                    properties = await self.api._take_snapshot(session, launch_id)
                    self.api.saved = ('43-1', snapshot)
                    self.api.current = dict(newer_properties)
                    return properties
                self.api.take_snapshot.side_effect = take_then_replace
                request = {'terminal': UUID, 'device': DEVICE, 'phase': 'return', 'preserve': True, 'launch_id': '42-1'}
                with patch.object(appearance, '_WATCH_SECONDS', .001):
                    self.assertEqual(await appearance._operate(request), 'ignored')
                self.assertEqual(self.api.current, newer_properties)
                self.assertEqual(self.api.saved, ('43-1', snapshot))

    async def test_matched_launch_claims_before_write_and_return_clears_its_claim(self):
        self.api.saved = ('42-1', dict(self.api.current))
        ownership_at_write = []
        self.api.write.side_effect = lambda *args: ownership_at_write.append(self.api.saved)
        self.api.main = 'omp'
        request = {**self.request, 'phase': 'launch', 'launch_id': '43-1'}
        with patch.object(appearance, '_WATCH_SECONDS', .001):
            self.assertEqual(await appearance._operate(request), 'applied')
            self.assertEqual(ownership_at_write, [('43-1', None)])
            self.api.main = 'zsh'
            self.assertEqual(await appearance._operate({**request, 'phase': 'return'}), 'applied')
        self.api.save_snapshot.assert_awaited_once_with(self.api.session, None, '43-1', (UUID, 42, 'birth'))
        self.assertIsNone(self.api.saved)

    async def test_cancelled_return_preserves_still_foreground_main_claim(self):
        self.api.saved = ('42-1', dict(self.api.current))
        self.api.main = 'omp'
        request = {'terminal': UUID, 'device': DEVICE, 'phase': 'return', 'preserve': True, 'launch_id': '42-1'}
        observer = asyncio.create_task(appearance._operate(request))
        try:
            while not self.api.take_snapshot.await_count:
                await asyncio.sleep(0)
            self.assertIsNotNone(self.api.saved)
        finally:
            observer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await observer
        self.api.clear_snapshot.assert_not_awaited()
        self.assertIsNotNone(self.api.saved)
        self.assertFalse(self.api.watching)
        self.api.close.assert_awaited_once()

    async def test_relaunch_cancels_old_observer_before_new_write(self):
        self.request['phase'] = 'launch'
        old = asyncio.create_task(appearance._operate(self.request))
        while not self.api.watching:
            await asyncio.sleep(0)
        old.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await old
        self.assertFalse(self.api.watching)
        writes = self.api.write.await_count
        self.api.main = 'omp'
        await self.api.events.put(None)
        await asyncio.sleep(0)
        self.assertEqual(self.api.write.await_count, writes)
        self.api.close.assert_awaited_once()
        newer = FakeAPI()
        with patch.object(appearance, '_API', return_value=newer):
            self.assertEqual(await appearance._operate({**self.request, 'phase': 'shell', 'color': '#112233'}), 'applied')
        newer.write.assert_awaited_once_with(newer.session, '#112233', '/fixture/a.png')
        self.assertEqual(self.api.write.await_count, writes)


class SnapshotSession:
    """Model another connection replacing state before a read reply arrives."""

    def __init__(self, record):
        self.record = record
        self.current = record['properties']
        self.replacement_after_read = None
        self.deferred_replacement = None
        self.in_transaction = False
        self.writes = []

    def replace(self, record):
        if self.in_transaction:
            self.deferred_replacement = record
        else:
            self.record = record
            if record['properties'] is not None:
                self.current = record['properties']

    @asynccontextmanager
    async def transaction(self, connection):
        self.in_transaction = True
        try:
            yield
        finally:
            self.in_transaction = False
            if self.deferred_replacement is not None:
                self.replace(self.deferred_replacement)
                self.deferred_replacement = None

    async def async_get_variable(self, name):
        value = json.dumps(self.record)
        if self.replacement_after_read is not None:
            self.replace(self.replacement_after_read)
            self.replacement_after_read = None
        return value

    async def async_set_variable(self, name, value):
        self.record = None if value is None else json.loads(value)

    async def async_set_profile_properties(self, profile):
        self.writes.append((self.in_transaction, profile))
        self.current = profile


class InstalledAppearanceTests(unittest.TestCase):
    def test_standalone_release_imports_only_its_adjacent_identity_helper(self):
        import shutil
        with tempfile.TemporaryDirectory() as root:
            release = Path(root) / 'release'
            release.mkdir()
            for name in ('appearance.py', 'terminal_identity.py'):
                shutil.copy(Path(appearance.__file__).parent / name, release / name)
            code = """import runpy,sys,pathlib
root=pathlib.Path(sys.argv[1])
sys.path.insert(0,str(root))
module=runpy.run_path(str(root/'appearance.py'))
import terminal_identity
assert pathlib.Path(terminal_identity.__file__).parent == root
assert module['verified_identity'] is terminal_identity.verified_identity
assert 'iterm2_utils' not in sys.modules
print('standalone')
"""
            result = subprocess.run([sys.executable, '-I', '-c', code, str(release)],
                                    cwd=root, env={'HOME': root}, capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'standalone\n', ''))


class OmpIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_operation_writes_only_after_actual_private_live_identity(self):
        from runtime import terminal_identity
        with tempfile.TemporaryDirectory() as root:
            registry = Path(root) / 'identity'
            registry.mkdir(mode=0o700)
            record = dict(schema=1, terminal_id=UUID, tab_id='tab', window_id='window',
                          session_file=None, session_id='actual-main', cwd=root,
                          profile={'name': None, 'agent_dir': root}, pid=42,
                          process_start='darwin-bsd:123:000456', generation='generation')
            path = registry / 'instance-generation.json'
            path.write_text(json.dumps(record)); path.chmod(0o600)
            variables = {'tty': '/dev/null', 'user.iterm2_utils_omp': json.dumps(record)}
            session = Mock(session_id=UUID,
                           async_get_variable=AsyncMock(side_effect=lambda name: variables.get(name)),
                           async_set_variable=AsyncMock(side_effect=lambda name, value: variables.update({name: value})),
                           async_set_profile_properties=AsyncMock())
            tab = Mock(tab_id='tab', all_sessions=[session])
            window = Mock(window_id='window', tabs=[tab])
            app = Mock(terminal_windows=[window], get_session_by_id=Mock(return_value=session))
            connection = Mock(websocket=Mock(close=AsyncMock()))
            sdk = Mock(async_get_app=AsyncMock(return_value=app))
            sdk.Connection.async_create = AsyncMock(return_value=connection)
            sdk.Transaction.return_value = AsyncMock()
            class Monitor:
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
                async def async_get(self): await asyncio.Future()
            sdk.VariableMonitor.side_effect = lambda *args: Monitor()
            request = dict(terminal=UUID, device=DEVICE, phase='launch', registry=str(registry),
                           launch_id='42-1', color='#65A85A', icon='/fixture/a.png')
            for birth, expected in ((record['process_start'], 'applied'),
                                    ('darwin-bsd:123:000457', 'timeout'), (None, 'timeout')):
                session.async_set_profile_properties.reset_mock()
                with patch.dict(sys.modules, {'iterm2': sdk}), \
                     patch.object(terminal_identity, 'process_start', return_value=birth), \
                     patch.object(appearance, 'foreground_process', return_value=True), \
                     patch.object(appearance, '_WATCH_SECONDS', .001):
                    self.assertEqual(await appearance._operate(request), expected)
                self.assertEqual(session.async_set_profile_properties.await_count,
                                 1 if expected == 'applied' else 0)

    async def test_appearance_foreground_check_is_separate_from_live_birth(self):
        from runtime import terminal_identity
        for state, group, foreground, expected in ((3, 42, 42, True),
                                                   (4, 42, 42, False),
                                                   (3, 42, 17, False)):
            info = terminal_identity._ProcBSDInfo(pbi_pid=42, pbi_status=state,
                pbi_start_tvsec=123, pbi_start_tvusec=456, pbi_pgid=group,
                e_tpgid=foreground, e_tdev=DEVICE & 0xffffffff)
            with patch.object(terminal_identity, '_read_bsdinfo', return_value=info):
                self.assertEqual(terminal_identity.foreground_process(42, 'darwin-bsd:123:000456', '/dev/null'), expected)
                self.assertEqual(terminal_identity.process_start(42), 'darwin-bsd:123:000456')
        with patch.object(terminal_identity, '_read_bsdinfo', return_value=None), \
             patch.object(os, 'getpgid', return_value=42):
            self.assertEqual(terminal_identity.foreground_state(42, 'birth', '/dev/null'), 'unknown')

    async def test_suspend_to_shell_restores_original_without_removing_live_dialog(self):
        script = r"""import asyncio,fcntl,json,os,pathlib,signal,subprocess,sys,termios
from unittest.mock import patch
from runtime import appearance,terminal_identity
from iterm2_utils.omp_sessions import read_bindings
from tests.test_appearance_runtime import FakeAPI,UUID
root=pathlib.Path(sys.argv[1]); tty=os.ttyname(0)
registry=root/'identity'; registry.mkdir(mode=0o700)
ready_read,ready_write=os.pipe()
child=os.fork()
if child==0:
    os.close(ready_read); os.setpgid(0,0); os.write(ready_write,b'ready'); os.close(ready_write)
    signal.pause(); os._exit(0)
os.close(ready_write); os.read(ready_read,5); os.close(ready_read)
signal.signal(signal.SIGTTOU,signal.SIG_IGN)
try:
    os.tcsetpgrp(0,child)
    birth=terminal_identity.process_start(child)
    assert birth is not None
    image=terminal_identity.process_image(os.getpid())
    assert image is not None and pathlib.Path(image).samefile(sys.executable)
    def detached_state():
        code='import sys; from runtime.terminal_identity import foreground_state; print(foreground_state(int(sys.argv[1]),sys.argv[2],sys.argv[3]))'
        result=subprocess.run([sys.executable,'-c',code,str(child),birth,tty],stdin=subprocess.DEVNULL,
                              start_new_session=True,capture_output=True,text=True,timeout=3)
        assert result.returncode==0,result.stderr
        return result.stdout.strip()
    assert detached_state()=='foreground'
    record=dict(schema=1,terminal_id=UUID,tab_id='tab',window_id='window',session_file=None,
                session_id='suspended-dialog',cwd=str(root),profile=dict(name=None,agent_dir=str(root)),
                pid=child,process_start=birth,generation='generation')
    path=registry/'instance-generation.json'; path.write_text(json.dumps(record)); path.chmod(0o600)
    api=FakeAPI()
    async def main_identity(*args):
        live=terminal_identity.verified_identity(registry,record)
        return live if live and terminal_identity.foreground_process(child,birth,tty) else None
    api.main_identity=main_identity
    async def departed(owner,actual_tty):
        return terminal_identity.foreground_state(owner[1],owner[2],actual_tty)=='departed'
    api.departed=departed
    original=dict(api.current)
    request=dict(terminal=UUID,device=os.fstat(0).st_rdev,tty=tty,phase='launch',preserve=True,launch_id='42-1')
    with patch.object(appearance,'_API',return_value=api),patch.object(appearance,'_WATCH_SECONDS',.001):
        assert asyncio.run(appearance._operate(request))=='applied'
        os.kill(child,signal.SIGSTOP); os.waitpid(child,os.WUNTRACED)
        os.tcsetpgrp(0,os.getpgrp())
        assert detached_state()=='departed'
        api.current={'profile-reset':True}
        api.events=asyncio.Queue()  # Each actual invocation owns a fresh SDK/event loop.
        assert asyncio.run(appearance._operate({**request,'phase':'return'}))=='applied'
    print(json.dumps(dict(restored=api.current==original,live=terminal_identity.process_start(child)==birth,
                          binding=read_bindings(registry)[0].session_id,record=path.exists(),
                          foreground=terminal_identity.foreground_process(child,birth,tty))))
finally:
    os.tcsetpgrp(0,os.getpgrp()); os.kill(child,signal.SIGKILL); os.waitpid(child,0)
"""
        with tempfile.TemporaryDirectory() as root:
            master, slave = pty.openpty()
            try:
                def own_terminal():
                    os.setsid()
                    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
                result = subprocess.run([sys.executable, '-c', script, root],
                                        cwd=Path(appearance.__file__).resolve().parents[1],
                                        env={**os.environ, 'HOME': root}, stdin=slave,
                                        preexec_fn=own_terminal, capture_output=True, text=True, timeout=10)
            finally:
                os.close(master); os.close(slave)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(restored=True, live=True,
                             binding='suspended-dialog', record=True, foreground=False))

    async def test_actual_identity_requires_registry_birth_and_independent_addresses(self):
        from runtime import terminal_identity
        with tempfile.TemporaryDirectory() as root:
            registry = Path(root) / 'identity'
            registry.mkdir(mode=0o700)
            record = dict(schema=1, terminal_id=UUID, tab_id='tab', window_id='window',
                          session_file=None, session_id='actual-main', cwd=root,
                          profile={'name': None, 'agent_dir': root}, pid=42,
                          process_start='darwin-bsd:123:000456', generation='generation')
            path = registry / 'instance-generation.json'
            path.write_text(json.dumps(record)); path.chmod(0o600)
            with patch.object(terminal_identity, 'process_start', return_value=record['process_start']):
                self.assertEqual(terminal_identity.verified_identity(registry, record), record)
                for key in ('terminal_id', 'tab_id', 'window_id', 'generation', 'session_id'):
                    self.assertIsNone(terminal_identity.verified_identity(registry, {**record, key: 'foreign'}))
            for birth in (None, 'darwin-bsd:123:000457'):
                with patch.object(terminal_identity, 'process_start', return_value=birth):
                    self.assertIsNone(terminal_identity.verified_identity(registry, record))
            path.chmod(0o644)
            with patch.object(terminal_identity, 'process_start', return_value=record['process_start']):
                self.assertIsNone(terminal_identity.verified_identity(registry, record))

    async def test_sdk_identity_uses_observed_addresses_not_embedded_registry_echo(self):
        sdk = Mock()
        session = Mock(session_id=UUID, async_get_variable=AsyncMock(return_value=json.dumps({
            'terminal_id': UUID, 'tab_id': 'stale', 'window_id': 'stale'})))
        tab = Mock(tab_id='actual-tab', all_sessions=[session])
        window = Mock(window_id='actual-window', tabs=[tab])
        sdk.async_get_app = AsyncMock(return_value=Mock(terminal_windows=[window]))
        with patch.dict(sys.modules, {'iterm2': sdk}):
            api = appearance._API()
        with patch.object(appearance, 'verified_identity', return_value=None) as verify:
            self.assertIsNone(await api.main_identity(session, Path('/fixture/identity')))
        observed = verify.call_args.args[1]
        self.assertEqual((observed['terminal_id'], observed['tab_id'], observed['window_id']),
                         (UUID, 'actual-tab', 'actual-window'))

class NativeAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_device_alias_and_foreign_pty(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(sys.modules, {'iterm2': Mock()}):
            api = appearance._API()
            master, slave = pty.openpty()
            foreign_master, foreign_slave = pty.openpty()
            try:
                tty = os.ttyname(slave)
                alias = Path(root) / 'tty-alias'
                alias.symlink_to(tty)
                device = os.fstat(slave).st_rdev
                session = Mock(async_get_variable=AsyncMock(return_value=str(alias)))
                self.assertEqual(appearance._tty_device(tty), device)
                self.assertEqual(appearance._tty_device(str(alias)), device)
                self.assertTrue(await api.owns_terminal(session, device))
                session.async_get_variable.assert_awaited_once_with('tty')
                session.async_get_variable.return_value = os.ttyname(foreign_slave)
                self.assertFalse(await api.owns_terminal(session, device))
                for path in (None, '', 'relative', '/missing-fixture', str(Path(root)),
                             str(Path(root) / 'file'), '/dev/null\x00private'):
                    with self.subTest(path=path):
                        (Path(root) / 'file').touch()
                        self.assertIsNone(appearance._tty_device(path))
                        session.async_get_variable.return_value = path
                        self.assertFalse(await api.owns_terminal(session, device))
                self.assertFalse(await api.owns_terminal(None, device))
                self.assertFalse(await api.owns_terminal(session, None))
            finally:
                for fd in (master, slave, foreign_master, foreign_slave):
                    os.close(fd)

    async def test_reset_disables_all_color_variants_and_custom_icon(self):
        sdk = Mock()
        sdk.IconMode.NONE = 0
        sdk.LocalWriteOnlyProfile.return_value = profile = Mock()
        with patch.dict(sys.modules, {'iterm2': sdk}):
            api = appearance._API()
        session = Mock(async_set_profile_properties=AsyncMock())
        await api.reset(session)
        native_keys = {'set_use_tab_color': 'Use Tab Color',
                       'set_use_tab_color_light': 'Use Tab Color (Light)',
                       'set_use_tab_color_dark': 'Use Tab Color (Dark)',
                       'set_icon_mode': 'Icon', 'set_custom_icon_path': 'Custom Icon Path'}
        self.assertEqual({native_keys[call[0]]: call.args[0] for call in profile.mock_calls}, {
            'Use Tab Color': False, 'Use Tab Color (Light)': False, 'Use Tab Color (Dark)': False,
            'Icon': 0, 'Custom Icon Path': ''})
        self.assertEqual(len(profile.mock_calls), 5)
        sdk.Color.assert_not_called()
        sdk.LocalWriteOnlyProfile.assert_called_once_with()
        session.async_set_profile_properties.assert_awaited_once_with(profile)

    def snapshot_fixture(self):
        properties = {key: None for key in appearance._APPEARANCE_KEYS}
        record = {'launch_id': '42-1', 'properties': properties}
        newer = {'launch_id': '43-1', 'properties': {**properties, 'Custom Icon Path': '/fixture/newer.png'}}
        session = SnapshotSession(record)
        sdk = Mock(Transaction=session.transaction, LocalWriteOnlyProfile=lambda value: dict(value))
        with patch.dict(sys.modules, {'iterm2': sdk}):
            api = appearance._API()
        return api, session, record, newer

    async def test_read_reply_cannot_clear_a_newer_snapshot(self):
        api, session, record, newer = self.snapshot_fixture()
        session.replacement_after_read = newer
        self.assertEqual(await api.take_snapshot(session, '42-1'), record['properties'])
        self.assertEqual(session.record, newer)

    async def test_cached_restore_rejects_newer_snapshot_and_matched_claim(self):
        for marker in (False, True):
            with self.subTest(marker=marker):
                api, session, record, newer = self.snapshot_fixture()
                properties = await api.take_snapshot(session, '42-1')
                session.replace(newer)
                if marker:
                    session.record = {**newer, 'properties': None}
                self.assertFalse(await api.restore(session, properties, '42-1'))
                self.assertEqual(session.current, newer['properties'])
                self.assertEqual(session.record['launch_id'], '43-1')

    async def test_restore_check_and_write_cannot_overwrite_a_queued_new_launch(self):
        api, session, record, newer = self.snapshot_fixture()
        session.replacement_after_read = newer
        self.assertTrue(await api.restore(session, record['properties'], '42-1'))
        self.assertEqual(session.record, newer)
        self.assertEqual(session.current, newer['properties'])
        self.assertFalse(session.in_transaction)

    async def test_matched_write_rejects_a_newer_claim(self):
        api, session, record, newer = self.snapshot_fixture()
        session.replace({**newer, 'properties': None})
        self.assertFalse(await api.write_if_current(session, '#65A85A', '/fixture/old-project.png', '42-1'))
        self.assertEqual(session.current, record['properties'])
        self.assertEqual(session.writes, [])
        self.assertEqual(session.record['launch_id'], '43-1')

    async def test_matched_check_and_assignment_are_atomic_against_a_queued_new_claim(self):
        api, session, record, newer = self.snapshot_fixture()
        session.record = {**record, 'properties': None}
        api.sdk.LocalWriteOnlyProfile = Mock()
        profile = api.sdk.LocalWriteOnlyProfile.return_value
        session.replacement_after_read = newer
        self.assertTrue(await api.write_if_current(session, '#65A85A', '/fixture/old-project.png', '42-1'))
        self.assertEqual(session.writes, [(True, profile)])
        self.assertEqual(session.record, newer)
        self.assertEqual(session.current, newer['properties'])
        self.assertFalse(session.in_transaction)

    async def test_shell_invalidation_removes_explicit_and_legacy_launch_claims(self):
        for launch_id in ('42-1', None):
            with self.subTest(launch_id=launch_id):
                api, session, record, newer = self.snapshot_fixture()
                session.record = {'launch_id': launch_id, 'properties': None}
                await api.invalidate_snapshot(session)
                self.assertIsNone(session.record)
                self.assertFalse(await api.write_if_current(session, '#65A85A', '/fixture/old-project.png', launch_id))
                self.assertEqual(session.writes, [])
                self.assertEqual(session.current, record['properties'])

    async def test_clear_check_and_write_cannot_erase_a_queued_new_launch(self):
        api, session, record, newer = self.snapshot_fixture()
        session.replacement_after_read = newer
        await api.clear_snapshot(session, '42-1')
        self.assertEqual(session.record, newer)
        self.assertFalse(session.in_transaction)

    async def test_clear_preserves_newer_record_and_removes_own_matched_claim(self):
        api, session, record, newer = self.snapshot_fixture()
        session.replace(newer)
        await api.clear_snapshot(session, '42-1')
        self.assertEqual(session.record, newer)
        session.record = {**record, 'properties': None}
        await api.clear_snapshot(session, '42-1')
        self.assertIsNone(session.record)

    async def test_snapshot_roundtrip_is_session_local_and_allowlisted(self):
        keys = ('Tab Color', 'Tab Color (Light)', 'Tab Color (Dark)', 'Use Tab Color',
                'Use Tab Color (Light)', 'Use Tab Color (Dark)', 'Icon', 'Custom Icon Path')
        expected = dict(zip(keys, ({'Red Component': .4}, None, {'Red Component': .9},
                                  True, None, False, 2, '/fixture/manual.png')))
        values = {key: json.dumps(value) for key, value in {**expected, 'Name': 'do not restore'}.items()}
        sdk = Mock()
        sdk.Transaction.return_value = AsyncMock()
        record = {'launch_id': '42-1', 'properties': expected}
        session = Mock(async_get_profile=AsyncMock(return_value=Mock(local_write_only_copy=Mock(values=values))),
                       async_get_variable=AsyncMock(return_value=json.dumps(record)),
                       async_set_variable=AsyncMock(), async_set_profile_properties=AsyncMock())
        with patch.dict(sys.modules, {'iterm2': sdk}):
            api = appearance._API()
        snapshot = await api.snapshot(session)
        self.assertEqual(snapshot, expected)
        await api.save_snapshot(session, snapshot, '42-1')
        saved = session.async_set_variable.call_args
        self.assertTrue(saved.args[0].startswith('user.'))
        self.assertEqual(json.loads(saved.args[1]), record)
        self.assertEqual(await api.take_snapshot(session, '42-1'), expected)
        self.assertEqual(session.async_set_variable.await_count, 1)
        self.assertTrue(await api.restore(session, snapshot, '42-1'))
        sdk.LocalWriteOnlyProfile.assert_called_once_with(expected)
        session.async_set_profile_properties.assert_awaited_once_with(sdk.LocalWriteOnlyProfile.return_value)
        await api.clear_snapshot(session, '42-1')
        session.async_set_variable.assert_awaited_with(saved.args[0], None)

    async def test_shell_baseline_survives_launch_claim_and_return_cleanup(self):
        api, session, record, newer = self.snapshot_fixture()
        owner = [UUID, 42, 'shell-birth', DEVICE]
        await api.save_baseline(session, record['properties'], owner, '/fixture/zsh', '/fixture/cwd')
        await api.save_snapshot(session, record['properties'], '42-1', (UUID, 91, 'main-birth'))
        self.assertEqual(await api.take_owner(session, '42-1'), (UUID, 91, 'main-birth'))
        self.assertEqual(await api.take_baseline(session, owner, '/fixture/cwd'), record['properties'])
        self.assertIsNone(await api.take_baseline(session, owner, '/fixture/another-root'))
        for index, value in enumerate(('foreign-terminal', 43, 'foreign-birth', DEVICE + 1)):
            foreign = list(owner)
            foreign[index] = value
            self.assertIsNone(await api.take_baseline(session, foreign, '/fixture/cwd'))
        manual = {**record['properties'], 'Custom Icon Path': '/fixture/new-manual.png'}
        await api.save_baseline(session, manual, owner, '/fixture/zsh', '/fixture/cwd',
                                launch_id='42-1', restored_owner=(UUID, 91, 'main-birth'))
        self.assertEqual(await api.take_snapshot(session, '42-1'), record['properties'])
        await api.clear_snapshot(session, '42-1')
        self.assertIsNone(await api.take_owner(session, '42-1'))
        self.assertEqual(await api.take_baseline(session, owner, '/fixture/cwd'), manual)
        await api.save_snapshot(session, newer['properties'], '43-1', (UUID, 92, 'new-main'))
        self.assertFalse(await api.save_baseline(session, record['properties'], owner, '/fixture/zsh', '/fixture/cwd',
                                                launch_id='42-1', restored_owner=(UUID, 91, 'main-birth')))
        self.assertEqual(await api.take_baseline(session, owner, '/fixture/cwd'), manual)
        self.assertEqual(await api.take_owner(session, '43-1'), (UUID, 92, 'new-main'))
        await api.invalidate_snapshot(session, keep_baseline=False)
        self.assertIsNone(await api.take_baseline(session, owner, '/fixture/cwd'))

    async def test_corrupt_or_foreign_snapshot_cannot_restore_other_properties(self):
        with patch.dict(sys.modules, {'iterm2': Mock()}):
            api = appearance._API()
        for value in (None, 'invalid', '[]', '{"Name":"foreign"}', '{}'):
            session = Mock(async_get_variable=AsyncMock(return_value=value), async_set_variable=AsyncMock())
            with self.subTest(value=value):
                self.assertIsNone(await api.take_snapshot(session, '42-1'))

    async def test_snapshot_from_a_different_launch_cannot_overwrite_or_clear_current_state(self):
        with patch.dict(sys.modules, {'iterm2': Mock()}):
            api = appearance._API()
        record = {'launch_id': '42-1', 'properties': {key: None for key in
                  ('Tab Color', 'Tab Color (Light)', 'Tab Color (Dark)', 'Use Tab Color',
                   'Use Tab Color (Light)', 'Use Tab Color (Dark)', 'Icon', 'Custom Icon Path')}}
        session = Mock(async_get_variable=AsyncMock(return_value=json.dumps(record)), async_set_variable=AsyncMock())
        self.assertIsNone(await api.take_snapshot(session, '42-2'))
        session.async_set_variable.assert_not_called()

    async def test_subscription_uses_identity_profile_and_foreground_wakeups_with_explicit_id(self):
        sdk = Mock()
        monitors = []

        class Monitor:
            def __init__(self, connection, scope, name, terminal):
                self.args = (connection, scope, name, terminal)
                self.queue = asyncio.Queue()
                self.closed = False
                monitors.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                self.closed = True

            async def async_get(self):
                return await self.queue.get()

        sdk.VariableMonitor = Monitor
        with patch.dict(sys.modules, {'iterm2': sdk}):
            api = appearance._API()
        api.connection = object()
        async with api.watch(UUID) as events:
            await monitors[1].queue.put('omp')
            await asyncio.wait_for(events.get(), .1)
        self.assertEqual([monitor.args for monitor in monitors], [
            (api.connection, sdk.VariableScopes.SESSION, 'user.iterm2_utils_omp', UUID),
            (api.connection, sdk.VariableScopes.SESSION, 'profileName', UUID),
            (api.connection, sdk.VariableScopes.SESSION, 'jobName', UUID)])
        self.assertTrue(all(monitor.closed for monitor in monitors))

    async def test_only_color_and_icon_properties_including_light_dark(self):
        sdk = Mock()
        sdk.LocalWriteOnlyProfile.return_value = profile = Mock()
        sdk.Color.return_value = color = object()
        with patch.dict(sys.modules, {'iterm2': sdk}):
            api = appearance._API()
        session = Mock(async_set_profile_properties=AsyncMock())
        await api.write(session, '#65A85A', '/fixture/icon.png')
        sdk.Color.assert_called_once_with(101, 168, 90)
        expected = {'set_tab_color': color, 'set_tab_color_light': color, 'set_tab_color_dark': color,
                    'set_use_tab_color': True, 'set_use_tab_color_light': True, 'set_use_tab_color_dark': True,
                    'set_icon_mode': sdk.IconMode.CUSTOM, 'set_custom_icon_path': '/fixture/icon.png'}
        self.assertEqual({call[0]: call.args[0] for call in profile.mock_calls}, expected)
        self.assertEqual(len(profile.mock_calls), 8)
        session.async_set_profile_properties.assert_awaited_once_with(profile)


class SupervisorTests(unittest.TestCase):
    def test_command_observer_outlives_cold_deadline_and_is_reaped_on_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root/'command-worker.py'
            helper.write_text("""import json,os,pathlib,signal,sys
root=pathlib.Path(__file__).parent
if sys.argv[1:]==['--worker']:
    request=json.load(sys.stdin)
    os.write(request['ready_fd'],b'ready\\n'); os.close(request['ready_fd'])
    (root/'worker.pid').write_text(str(os.getpid()))
    signal.pause()
else:
    sys.path.insert(0,sys.argv[1])
    from runtime import appearance
    appearance.__file__=__file__
    print(appearance._supervise(dict(phase='launch',command_scope=True,shell_pid=os.getppid()),dict(os.environ)))
""")
            with subprocess.Popen([sys.executable, str(helper), str(Path(appearance.__file__).resolve().parents[1])],
                                  env={**os.environ, 'HOME': directory},
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as supervisor:
                try:
                    marker = root/'worker.pid'
                    deadline = time.monotonic()+4
                    while not marker.exists() and supervisor.poll() is None and time.monotonic()<deadline:
                        time.sleep(.01)
                    self.assertTrue(marker.exists(), 'worker never acknowledged startup')
                    time.sleep(appearance._HARD_SECONDS+.3)
                    self.assertIsNone(supervisor.poll(), 'command lifetime was incorrectly an idle deadline')
                    supervisor.terminate()
                    self.assertEqual(supervisor.communicate(timeout=3), ('unavailable\n', ''))
                    self.assert_process_gone(int(marker.read_text()))
                finally:
                    if supervisor.poll() is None:
                        supervisor.terminate()
                        supervisor.wait(timeout=3)

    def test_signal_around_ready_duplicate_close_still_reaps_and_restores_handlers(self):
        for signum, timing in ((sig, when) for sig in (signal.SIGTERM, signal.SIGINT)
                               for when in ('before', 'after')):
            with self.subTest(signum=signum, timing=timing):
                child = Mock(pid=12345, returncode=None)
                handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
                mask = signal.pthread_sigmask(signal.SIG_BLOCK, ())
                closed = []
                def close(fd):
                    if timing == 'before':
                        signal.raise_signal(signum)
                    if fd in closed:
                        raise OSError(9, 'duplicate already closed')
                    closed.append(fd)
                    if timing == 'after':
                        signal.raise_signal(signum)
                try:
                    with patch.object(appearance.os, 'dup', return_value=42), \
                         patch.object(appearance.os, 'close', side_effect=close), \
                         patch.object(appearance.subprocess, 'Popen', return_value=child), \
                         patch.object(appearance.os, 'killpg') as kill:
                        self.assertEqual(appearance._supervise(
                            {'terminal': UUID, 'phase': 'launch', 'ready_fd': 3}, ENV), 'unavailable')
                    self.assertEqual(closed, [42])
                    kill.assert_called_once_with(12345, signal.SIGKILL)
                    child.wait.assert_called_once()
                    child.stdin.close.assert_called_once()
                    child.stdout.close.assert_called_once()
                    for sig, handler in handlers.items():
                        self.assertEqual(signal.getsignal(sig), handler)
                    self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, ()), mask)
                finally:
                    for sig, handler in handlers.items():
                        signal.signal(sig, handler)
                    signal.pthread_sigmask(signal.SIG_SETMASK, mask)

    def test_real_worker_readiness_without_identity_never_authorizes_write_and_keeps_cancel_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'iterm2.py').write_text('''
import asyncio, os, pathlib
class Profile:
    def __getattr__(self, name): return lambda *args: None
LocalWriteOnlyProfile = Profile
Color = lambda *args: None
class IconMode: CUSTOM = 2
class Transaction:
    def __init__(self, *args): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
class VariableScopes: SESSION = 1
class VariableMonitor:
    def __init__(self, *args): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def async_get(self): await asyncio.Future()
class Session:
    snapshot = None
    async def async_get_variable(self, name):
        if name == 'tty': return os.environ['APPEARANCE_TEST_TTY']
        return self.snapshot
    async def async_set_variable(self, name, value): self.snapshot = value
    async def async_set_profile_properties(self, profile):
        await asyncio.sleep(.05)
        pathlib.Path(os.environ['APPEARANCE_TEST_WRITE']).touch()
class App:
    def get_session_by_id(self, terminal): return Session()
async def async_get_app(connection): return App()
class Connection:
    @staticmethod
    async def async_create(): return Connection()
    @property
    def websocket(self): return self
    async def close(self): pass
''')
            config = root / 'rules.json'
            config.write_text(json.dumps({'projects': [{'root': str(root), 'color': '#65A85A', 'icon': 'android-mail'}]}))
            marker = root / 'written'
            master, slave = pty.openpty()
            self.addCleanup(os.close, master)
            self.addCleanup(os.close, slave)
            tty = os.ttyname(slave)
            def own_terminal():
                os.setsid()
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            read_fd, write_fd = os.pipe()
            try:
                with subprocess.Popen([sys.executable, appearance.__file__, '--config', str(config),
                        '--cwd', str(root), '--phase', 'launch', '--ready-fd', str(write_fd), '--tty', tty],
                        env={**ENV, 'PYTHONPATH': str(root), 'APPEARANCE_TEST_WRITE': str(marker),
                             'APPEARANCE_TEST_TTY': tty},
                        preexec_fn=own_terminal, stdin=slave, pass_fds=(write_fd,),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
                    os.close(write_fd)
                    write_fd = None
                    try:
                        self.assertTrue(select.select([read_fd], [], [], 2)[0], 'no readiness or EOF')
                        self.assertEqual(os.read(read_fd, 64), b'ready\n')
                        self.assertFalse(marker.exists(), 'read-only API success is not main identity')
                        self.assertIsNone(child.poll(), 'observer must remain alive after readiness')
                        child.terminate()
                        self.assertEqual(child.communicate(timeout=1), ('unavailable\n', ''))
                        self.assertEqual(os.read(read_fd, 64), b'')
                    finally:
                        if child.poll() is None:
                            child.terminate()
                            child.communicate(timeout=3)
            finally:
                os.close(read_fd)
                if write_fd is not None:
                    os.close(write_fd)

    def test_worker_missing_sdk_and_sdk_diagnostics_stay_private(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'iterm2.py').write_text("print('private SDK detail'); raise ImportError('private path')")
            self.assertEqual(appearance.probe(environment={**ENV, 'PYTHONPATH': str(root)}), 'unavailable')

    def test_real_supervisor_sigterm_reaps_auth_descendant(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'iterm2.py').write_text('''
import os, pathlib, subprocess, sys
class Connection:
    @staticmethod
    async def async_create():
        child = subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()'])
        pathlib.Path(os.environ['APPEARANCE_TEST_PID']).write_text(str(child.pid))
        child.wait()
''')
            marker = root / 'child.pid'
            with subprocess.Popen([sys.executable, appearance.__file__, '--probe'],
                    env={**ENV, 'PYTHONPATH': str(root), 'APPEARANCE_TEST_PID': str(marker)},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as supervisor:
                try:
                    deadline = time.monotonic() + 1.5
                    while not marker.exists() and supervisor.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(marker.exists(), 'fake auth never started')
                    supervisor.terminate()
                    output, error = supervisor.communicate(timeout=1)
                    self.assertEqual((output, error, supervisor.returncode), ('unavailable\n', '', 0))
                    self.assert_process_gone(int(marker.read_text()))
                finally:
                    if supervisor.poll() is None:
                        supervisor.terminate()
                        supervisor.wait(timeout=3)

    def test_cancel_during_spawn_is_not_lost(self):
        child = Mock(pid=12345, returncode=None)
        def spawning(*args, **kwargs):
            signal.raise_signal(signal.SIGTERM)
            return child
        with patch.object(appearance.subprocess, 'Popen', side_effect=spawning), \
             patch.object(appearance.os, 'killpg') as kill:
            self.assertEqual(appearance._supervise({'terminal': UUID, 'phase': 'probe'}, ENV), 'unavailable')
        child.communicate.assert_not_called()
        kill.assert_called_once_with(12345, signal.SIGKILL)
        child.wait.assert_called_once()

    def test_timeout_kills_descendants_even_when_worker_already_exited(self):
        child = Mock(pid=12345, returncode=1)
        child.communicate.side_effect = subprocess.TimeoutExpired('worker', 1)
        with patch.object(appearance.subprocess, 'Popen', return_value=child), \
             patch.object(appearance.os, 'killpg') as kill:
            self.assertEqual(appearance._supervise({'terminal': UUID, 'phase': 'probe'}, ENV), 'timeout')
        kill.assert_called_once_with(12345, signal.SIGKILL)

    def test_real_sync_auth_timeout_kills_descendant(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'iterm2.py').write_text('''
import os, pathlib, subprocess, sys
class Connection:
    @staticmethod
    async def async_create():
        child = subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()'])
        pathlib.Path(os.environ['APPEARANCE_TEST_PID']).write_text(str(child.pid))
        child.wait()
''')
            marker = root / 'child.pid'
            started = time.monotonic()
            result = appearance._supervise({'terminal': UUID, 'phase': 'probe'},
                {**ENV, 'PYTHONPATH': str(root), 'APPEARANCE_TEST_PID': str(marker)})
            self.assertEqual(result, 'timeout')
            self.assertLess(time.monotonic() - started, 3.1)
            pid = int(marker.read_text())
            self.assert_process_gone(pid)

    def assert_process_gone(self, pid):
        # Allow the OS to reap this test's killed orphan without inspecting others.
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(.01)
        self.fail('fake auth descendant survived cancellation')

    def test_fake_clock_deadline_includes_process_start_and_kills_group(self):
        child = Mock(pid=12345, returncode=None)
        child.communicate.side_effect = subprocess.TimeoutExpired('worker', 1)
        with patch.object(appearance.time, 'monotonic', side_effect=[10, 11]), \
             patch.object(appearance.subprocess, 'Popen', return_value=child), \
             patch.object(appearance.os, 'killpg') as kill:
            self.assertEqual(appearance._supervise({'terminal': UUID, 'phase': 'probe'}, ENV), 'timeout')
        self.assertAlmostEqual(child.communicate.call_args.kwargs['timeout'], appearance._HARD_SECONDS - 1)
        kill.assert_called_once_with(12345, signal.SIGKILL)
        child.wait.assert_called_once()

    def test_signal_cancellation_kills_and_reaps_group(self):
        child = Mock(pid=12345, returncode=None)
        def interrupted(**kwargs):
            signal.raise_signal(signal.SIGTERM)
        child.communicate.side_effect = interrupted
        original = signal.getsignal(signal.SIGTERM)
        with patch.object(appearance.subprocess, 'Popen', return_value=child), \
             patch.object(appearance.os, 'killpg') as kill:
            self.assertEqual(appearance._supervise({'terminal': UUID, 'phase': 'probe'}, ENV), 'unavailable')
        kill.assert_called_once_with(12345, signal.SIGKILL)
        child.wait.assert_called_once()
        self.assertEqual(signal.getsignal(signal.SIGTERM), original)
