import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from iterm2_utils import engine, state
from iterm2_utils.commands import Runner
from iterm2_utils.config import omp
from iterm2_utils.models import ChangeSet, Context, OmpProfile, Paths, Plan, Selection

ABSENT = {'exists': False, 'value': None}

def present(value):
    return {'exists': True, 'value': value}


class NativeConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.profile = OmpProfile('work', self.home/'.omp/profiles/work/agent')
        self.profile.agent_dir.mkdir(parents=True)
        self.bun = shutil.which('bun')
        self.assertIsNotNone(self.bun, 'Task10 native-config assertions require Bun')
        self.runner = Runner()
        self.env = patch.dict(os.environ, {'HOME': str(self.home)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        repo = Path(__file__).resolve().parents[1]
        self.paths = Paths(self.home, self.home/'.zshrc', self.home/'config', self.home/'cache', self.home/'data', self.home/'profiles', repo)
        self.context = Context(self.paths, {}, {}, frozenset(), {}, {}, omp_profile=self.profile)
        self.selection = Selection(frozenset({'status', 'shortcuts'}), frozenset({'resume'}), 'Default', self.profile)

    def test_nested_setting_and_literal_binding_preserve_neighbours(self):
        settings = self.profile.agent_dir/'config.yml'
        bindings = self.profile.agent_dir/'keybindings.yml'
        settings.write_text('# private comment\nterminal:\n  programStatus: false\n  other: keep # neighbour\nmodel: unchanged\n')
        bindings.write_text('# binding comment\napp.history.search: Ctrl+R\n')
        original_settings = settings.read_bytes()
        original_binding = bindings.read_bytes()
        changes = ChangeSet([
            omp.setting_edit(self.profile, 'terminal.programStatus', present(True), self.runner, owner='status'),
            omp.binding_edit(self.profile, 'app.session.resume', present('Alt+R'), self.runner, owner='shortcuts'),
        ], [], [])
        result = engine.apply(Plan(self.selection, changes, ''), self.context, self.runner)
        self.assertFalse(result.findings)
        self.assertEqual(omp.read_setting(self.profile, 'terminal.programStatus', self.runner), present(True))
        self.assertEqual(omp.read_binding(self.profile, 'app.session.resume', self.runner), present('Alt+R'))
        self.assertIn(b'other: keep # neighbour', settings.read_bytes())
        self.assertIn(b'model: unchanged', settings.read_bytes())
        self.assertIn(b'# binding comment', bindings.read_bytes())
        self.assertIn(b'app.history.search: Ctrl+R', bindings.read_bytes())
        self.assertEqual({r['kind'] for r in result.receipt.resources}, {'omp_setting', 'omp_binding'})
        self.assertTrue(all(r['version'] == '1' for r in result.receipt.resources))
        reverted = engine.revert(result.receipt, self.context, self.runner, frozenset({'status', 'shortcuts'}))
        self.assertFalse(reverted.findings)
        self.assertEqual(omp.read_setting(self.profile, 'terminal.programStatus', self.runner), present(False))
        self.assertEqual(omp.read_binding(self.profile, 'app.session.resume', self.runner), ABSENT)
        self.assertEqual(settings.read_bytes(), original_settings)
        self.assertIn(b'app.history.search: Ctrl+R', bindings.read_bytes())
        self.assertIn(original_binding.splitlines()[0], bindings.read_bytes())

    def test_notification_values_and_explicit_null_inverse(self):
        path = self.profile.agent_dir/'config.yml'
        path.write_text('completion:\n  notify: null\n')
        self.assertEqual(omp.read_setting(self.profile, 'completion.notify', self.runner), present(None))
        for key in ('completion.notify', 'error.notify'):
            before = omp.read_setting(self.profile, key, self.runner)
            omp.set_setting(self.profile, key, present('on'), self.runner, expected=before)
            self.assertEqual(omp.read_setting(self.profile, key, self.runner), present('on'))
            omp.set_setting(self.profile, key, before, self.runner, expected=present('on'))
            self.assertEqual(omp.read_setting(self.profile, key, self.runner), before)

    def test_changed_owned_values_block_revert(self):
        edit = omp.setting_edit(self.profile, 'terminal.programStatus', present(True), self.runner, owner='status')
        result = engine.apply(Plan(self.selection, ChangeSet([edit], [], []), ''), self.context, self.runner)
        path = self.profile.agent_dir/'config.yml'
        path.write_text('terminal:\n  programStatus: false\nforeign: keep\n')
        reverted = engine.revert(result.receipt, self.context, self.runner, frozenset({'status'}))
        self.assertTrue(reverted.findings)
        self.assertEqual(path.read_text(), 'terminal:\n  programStatus: false\nforeign: keep\n')
        self.assertEqual(len(reverted.receipt.resources), 1)

    def test_named_profile_overrides_selected_action_without_writing_inherited_file(self):
        base = self.home/'.omp/agent'
        base.mkdir(parents=True)
        inherited = base/'keybindings.yml'
        inherited.write_text('app.session.resume: F7\napp.history.search: Ctrl+R\n')
        before = inherited.read_bytes()
        omp.set_binding(self.profile, 'app.session.resume', present('Alt+R'), self.runner, expected=ABSENT)
        self.assertEqual(inherited.read_bytes(), before)
        self.assertEqual(omp.read_binding(self.profile, 'app.session.resume', self.runner), present('Alt+R'))
        self.assertEqual(omp.effective_binding(self.profile, 'app.session.resume', self.runner), present('Alt+R'))
        omp.set_binding(self.profile, 'app.session.resume', ABSENT, self.runner, expected=present('Alt+R'))
        self.assertEqual(omp.effective_binding(self.profile, 'app.session.resume', self.runner), present('F7'))

    def test_inherited_binding_collision_is_reported_without_overwrite(self):
        base = self.home/'.omp/agent'
        base.mkdir(parents=True)
        path = base/'keybindings.yml'
        path.write_text('app.history.search: Alt+R\n')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            omp.binding_edit(self.profile, 'app.session.resume', present('alt+r'), self.runner, owner='shortcuts')
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.profile.agent_dir/'keybindings.yml').exists())

    def test_inherited_change_between_plan_and_apply_blocks_mutation(self):
        edit = omp.binding_edit(self.profile, 'app.session.resume', present('Alt+R'), self.runner, owner='shortcuts')
        base = self.home/'.omp/agent'
        base.mkdir(parents=True)
        (base/'keybindings.yml').write_text('app.history.search: Alt+R\n')
        result = engine.apply(Plan(self.selection, ChangeSet([edit], [], []), ''), self.context, self.runner)
        self.assertTrue(result.findings)
        self.assertFalse((self.profile.agent_dir/'keybindings.yml').exists())

    def test_yaml_fallback_and_legacy_ambiguity_are_not_silently_overwritten(self):
        path = self.profile.agent_dir/'config.yaml'
        path.write_text('terminal: {programStatus: false}\n')
        omp.set_setting(self.profile, 'terminal.programStatus', present(True), self.runner, expected=present(False))
        self.assertFalse((path.parent/'config.yml').exists())
        self.assertIn('programStatus: true', path.read_text())
        path.unlink()
        (path.parent/'settings.json').write_text('{"terminal":{"programStatus":false}}')
        with self.assertRaises(ValueError):
            omp.read_setting(self.profile, 'terminal.programStatus', self.runner)
        self.assertFalse((path.parent/'config.yml').exists())

    def test_malformed_storage_is_never_replaced(self):
        path = self.profile.agent_dir/'config.yml'
        for source in ('terminal: [', 'null', 'terminal: null\n', 'terminal: {programStatus: false, programStatus: true}'):
            path.write_text(source)
            with self.assertRaises(ValueError):
                omp.set_setting(self.profile, 'terminal.programStatus', present(True), self.runner, expected=ABSENT)
            self.assertEqual(path.read_text(), source)

    def test_bounded_transport_is_private_and_does_not_invoke_omp(self):
        class Capture:
            def run(inner, argv, **kwargs):
                self.assertEqual(Path(argv[0]).name, 'bun')
                self.assertEqual(Path(argv[-1]).name, 'omp_config.ts')
                self.assertEqual(kwargs['timeout'], 5)
                self.assertNotIn('terminal.programStatus', ' '.join(argv))
                self.assertIn('terminal.programStatus', kwargs['stdin'])
                self.assertIn('--no-install', argv)
                self.assertIn('--no-env-file', argv)
                self.assertNotIn('BUN_OPTIONS', kwargs['env'])
                self.assertNotIn('LOG_STREAM', kwargs['env'])
                self.assertEqual(kwargs['env']['BUN_RUNTIME_TRANSPILER_CACHE_PATH'], '0')
                return subprocess.CompletedProcess(argv, 1, '', 'private settings source')
        with self.assertRaisesRegex(ValueError, '^Native omp configuration helper failed$'):
            omp.read_setting(self.profile, 'terminal.programStatus', Capture())

    def test_bytes_cas_preserves_concurrent_neighbour_write(self):
        path = self.profile.agent_dir/'config.yml'
        path.write_text('terminal: {programStatus: false}\nforeign: old\n')
        original = state.durable_write
        def racing(path_arg, content, mode=0o600, *, before_replace=None):
            path.write_text('terminal: {programStatus: false}\nforeign: new\n')
            return original(path_arg, content, mode, before_replace=before_replace)
        with patch.object(state, 'durable_write', racing), self.assertRaises(ValueError):
            omp.set_setting(self.profile, 'terminal.programStatus', present(True), self.runner, expected=present(False))
        self.assertEqual(path.read_text(), 'terminal: {programStatus: false}\nforeign: new\n')

    def test_matching_foreign_setting_is_not_adopted(self):
        path = self.profile.agent_dir/'config.yml'
        path.write_text('terminal: {programStatus: true}\n')
        edit = omp.setting_edit(self.profile, 'terminal.programStatus', present(True), self.runner, owner='status')
        result = engine.apply(Plan(self.selection, ChangeSet([edit], [], []), ''), self.context, self.runner)
        self.assertFalse(result.findings)
        self.assertEqual(result.receipt.resources, [])

    def test_native_receipt_validation_rejects_corrupt_addresses_and_values(self):
        import copy
        edit = omp.setting_edit(self.profile, 'terminal.programStatus', present(True), self.runner, owner='status')
        resource = engine._compile(edit)[0]
        state.validate_resources([resource])
        for key, value in (('key', 'model'), ('agent_dir', 'relative'), ('profile', '../other'), ('mode', True)):
            corrupt = copy.deepcopy(resource)
            corrupt['locator'][key] = value
            with self.assertRaises(ValueError):
                state.validate_resources([corrupt])
        corrupt = copy.deepcopy(resource)
        corrupt['installed'] = present(1)
        with self.assertRaises(ValueError):
            state.validate_resources([corrupt])

    def test_storage_precedence_change_after_plan_preserves_both_files(self):
        fallback = self.profile.agent_dir/'config.yaml'
        fallback.write_text('terminal: {programStatus: false}\n')
        edit = omp.setting_edit(self.profile, 'terminal.programStatus', present(True), self.runner, owner='status')
        preferred = self.profile.agent_dir/'config.yml'
        preferred.write_text('terminal: {programStatus: false}\nforeign: keep\n')
        result = engine.apply(Plan(self.selection, ChangeSet([edit], [], []), ''), self.context, self.runner)
        self.assertTrue(result.findings)
        self.assertEqual(fallback.read_text(), 'terminal: {programStatus: false}\n')
        self.assertEqual(preferred.read_text(), 'terminal: {programStatus: false}\nforeign: keep\n')

    def test_malformed_inherited_binding_storage_is_not_treated_as_absent(self):
        base = self.home/'.omp/agent'
        base.mkdir(parents=True)
        inherited = base/'keybindings.yml'
        inherited.write_text('app.history.search: [')
        with self.assertRaises(ValueError):
            omp.binding_edit(self.profile, 'app.session.resume', present('Alt+R'), self.runner)
        self.assertEqual(inherited.read_text(), 'app.history.search: [')
        self.assertFalse((self.profile.agent_dir/'keybindings.yml').exists())

    def test_empty_leaf_null_is_restorable_and_setting_modes_are_retained(self):
        path = self.profile.agent_dir/'config.yml'
        path.write_text('# сохранено\nterminal:\n  programStatus:\n  other: keep\n')
        path.chmod(0o640)
        omp.set_setting(self.profile, 'terminal.programStatus', present(True), self.runner, expected=present(None))
        self.assertEqual(omp.read_setting(self.profile, 'terminal.programStatus', self.runner), present(True))
        omp.set_setting(self.profile, 'terminal.programStatus', present(None), self.runner, expected=present(True))
        self.assertEqual(omp.read_setting(self.profile, 'terminal.programStatus', self.runner), present(None))
        self.assertIn('# сохранено', path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
