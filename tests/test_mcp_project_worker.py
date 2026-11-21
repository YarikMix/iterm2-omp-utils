"""Private edit protocol against isolated engine/native fixtures only."""
import importlib
import io
import json
from unittest.mock import patch

from iterm2_utils import engine
from iterm2_utils.mcp.binding import McpBinding
from tests.test_project_edits import ProjectEditTests


class ProjectWorkerTests(ProjectEditTests):
    def worker(self, frames, authorize=lambda: None, at_preview=None):
        self.assertIsNotNone(importlib.util.find_spec('iterm2_utils.mcp.project_worker'), 'Private gated edit worker is not implemented')
        worker = importlib.import_module('iterm2_utils.mcp.project_worker')
        binding = McpBinding(self.profile, self.context.paths.repo,
                             self.context.paths.data/'receipt.json', self.context.executables['python3'])
        output = io.StringIO()
        class Output:
            def write(inner, value):
                output.write(value)
                if at_preview and '"preview"' in value:
                    at_preview()
            def flush(inner): pass
        source = io.TextIOWrapper(io.BytesIO(frames))
        with patch.object(worker, 'bound_paths', return_value=self.context.paths), \
             patch.object(worker, 'discover', return_value=self.context), \
             patch.object(worker, 'Runner', return_value=self.runner), \
             patch('sys.stdin', source), patch('sys.stdout', Output()):
            code = worker.main(binding, authorize=authorize)
        return code, [json.loads(line) for line in output.getvalue().splitlines()]

    def prepare_frame(self, **change):
        return (json.dumps(dict(type='prepare', change=dict(operation='rename', project='project-a', name='Changed', **change)))+'\n').encode()

    def test_worker_rejects_commit_before_preview_and_multiple_commit(self):
        self.installed()
        before = self.snapshot()
        oversized = self.prepare_frame().rstrip(b'\n') + b' '*65536 + b'\n' + b'{"type":"commit"}\n'
        for raw in (b'{"type":"commit"}\n', b'bad\n', oversized,
                    self.prepare_frame()+b'{"type":"commit"}\n{"type":"commit"}\n',
                    self.prepare_frame()+b'{"type":"commit","confirm":true}\n',
                    self.prepare_frame()+b'{"type":"commit"}\njunk',
                    b'{"type":"prepare","change":{"operation":"remove","project":"project-a","confirm":true}}\n'):
            with self.subTest(raw=raw[:80]):
                self.worker(raw)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(any(c['operation'].startswith('write_') for c in self.calls))
        calls = []
        def authorized():
            calls.append(True)
            if len(calls) == 2:
                with self.assertRaises(BlockingIOError):
                    with engine._lock(self.context): pass
        _, frames = self.worker(self.prepare_frame()+b'{"type":"commit"}\n', authorized)
        self.assertEqual(frames[-1], {'result': {'status': 'applied'}})
        self.assertEqual(calls, [True, True])
        self.assertEqual(json.loads(self.dynamic.read_bytes())['Profiles'][0]['Name'], 'Changed')

    def test_confirmation_binds_original_pending_preview(self):
        self.installed()
        for target in ('config', 'ownership', 'journal'):
            with self.subTest(target=target):
                config = self.context.paths.config/'iterm2-utils-project-launcher.json'
                original = config.read_bytes()
                revoked = []
                def authorize():
                    if revoked: raise ValueError('private detail must not escape')
                def change():
                    if target == 'config': config.write_bytes(original+b' ')
                    elif target == 'journal': (self.context.paths.data/'journal').mkdir()
                    else: revoked.append(True)
                with patch.object(engine, '_set', wraps=engine._set) as mutate, \
                     patch.object(engine, '_recover', side_effect=AssertionError('must not recover')):
                    _, frames = self.worker(self.prepare_frame()+b'{"type":"commit"}\n', authorize, change)
                    self.assertIn(frames[-1]['result']['status'], {'blocked', 'conflict'})
                    mutate.assert_not_called()
                config.write_bytes(original)
                journal = self.context.paths.data/'journal'
                if journal.exists(): journal.rmdir()

    def test_rejected_preview_does_not_wait_or_write(self):
        self.installed()
        before = self.snapshot()
        _, frames = self.worker(b'{"type":"prepare","change":{"operation":"remove","project":"absent"}}\n')
        self.assertEqual(frames, [{'result': {'status': 'noop'}}])
        self.worker(self.prepare_frame())  # EOF is not consent.
        self.assertEqual(self.snapshot(), before)
        with patch.object(engine, '_set', wraps=engine._set) as mutate, \
             patch('iterm2_utils.mcp.project_worker.prepare_project_edit', side_effect=AssertionError('must authorize before prepare')) as prepare:
            def deny(): raise ValueError('secret')
            _, frames = self.worker(self.prepare_frame(), deny)
            self.assertEqual(frames, [{'result': {'status': 'blocked'}}])
            mutate.assert_not_called()
            prepare.assert_not_called()

    def test_unknown_after_native_write_preserves_journal(self):
        self.installed()
        from iterm2_utils.config import iterm
        original = engine._set
        def uncertain(resource, *args, **kwargs):
            if resource['kind'] == 'profile_bar': raise iterm.MutationUnknown()
            return original(resource, *args, **kwargs)
        with patch.object(engine, '_set', side_effect=uncertain):
            _, frames = self.worker(self.prepare_frame()+b'{"type":"commit"}\n')
        self.assertEqual(frames[-1], {'result': {'status': 'unknown'}})
        self.assertTrue((self.context.paths.data/'journal').exists())

    def test_valid_oversized_prepare_is_rejected_before_write(self):
        self.installed()
        oversized = self.prepare_frame().rstrip(b'\n') + b' '*65536 + b'\n' + b'{"type":"commit"}\n'
        before = self.snapshot()
        with patch.object(engine, '_set', wraps=engine._set) as mutate:
            _, frames = self.worker(oversized)
            self.assertEqual(frames, [{'result': {'status': 'blocked'}}])
            mutate.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        # Negative control: this exact valid request writes if the frame boundary is relaxed.
        with patch('iterm2_utils.mcp.project_worker.FRAME_LIMIT', 131072):
            _, frames = self.worker(oversized)
        self.assertEqual(frames[-1], {'result': {'status': 'applied'}})
        self.assertEqual(json.loads(self.dynamic.read_bytes())['Profiles'][0]['Name'], 'Changed')


for _name in dir(ProjectEditTests):
    if _name.startswith('test_') and _name not in ProjectWorkerTests.__dict__:
        setattr(ProjectWorkerTests, _name, None)
del ProjectEditTests
