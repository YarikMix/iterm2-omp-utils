"""Approved project edits against the existing private launcher fixture."""
import copy
import json
from dataclasses import replace
from unittest.mock import patch

from iterm2_utils import engine, lifecycle, state, project_edits as edits
from iterm2_utils.config import iterm
from tests.test_project_launcher import ProjectLauncherTests as LauncherFixture


class ProjectEditTests(LauncherFixture):
    # Reuse setup and SDK fixture, not the inherited test cases.
    def installed(self, *features):
        self.assertSuccess(self.install(*features, 'project-launcher'))
        self.context.project_launcher_config = None
        self.context.omp_profile = self.profile
        self.calls.clear()

    def preview(self, operation, **kwargs):
        return edits.prepare_project_edit(self.context, self.runner, edits.ProjectChange(operation, **kwargs))

    def apply(self, preview, authorize=lambda: None):
        return edits.apply_project_edit(self.context, self.runner, preview, authorize=authorize)

    def test_catalogue_ids_and_noop_are_owned(self):
        self.assertEqual(edits.list_owned_projects(self.context.paths, self.profile).status, 'not_configured')
        self.installed()
        catalogue = edits.list_owned_projects(self.context.paths, self.profile)
        self.assertEqual(catalogue.status, 'ok')
        a, b = catalogue.projects
        self.assertEqual(edits.select_project(catalogue.projects, a.id), a)
        self.assertEqual(edits.select_project(catalogue.projects, a.name), a)
        self.assertEqual(edits.select_project(catalogue.projects, a.path), a)
        with self.assertRaises(ValueError):
            edits.select_project((a, replace(b, name=a.name)), a.name)
        self.assertEqual(edits.select_project((a, replace(b, name=a.id)), a.id), a)
        before = self.dynamic.read_bytes()
        self.assertEqual(self.apply(self.preview('add', name=a.name, path=a.path)).status, 'noop')
        self.assertEqual(self.apply(self.preview('remove', project='absent')).status, 'noop')
        alias = self.folder.with_name('alias'); alias.symlink_to(self.folder, target_is_directory=True)
        self.assertEqual(self.preview('add', name='Alias', path=str(alias)).status, 'conflict')
        self.assertFalse(any(c['operation'].startswith('write_') for c in self.calls))
        result = self.apply(self.preview('rename', project=a.id, name='Renamed'))
        self.assertEqual(result.status, 'applied')
        old, new = json.loads(before)['Profiles'], json.loads(self.dynamic.read_bytes())['Profiles']
        self.assertEqual([r['Guid'] for r in old], [r['Guid'] for r in new])
        self.assertEqual([r['Name'] for r in new], ['Renamed', b.name])

    def test_independent_repair_of_two_unavailable_paths(self):
        self.installed(); self.folder.rmdir(); self.folder_b.rmdir()
        self.assertEqual(edits.list_owned_projects(self.context.paths, self.profile).status, 'ok')
        repaired = self.folder.with_name('repaired'); repaired.mkdir()
        self.assertEqual(self.apply(self.preview('move', project='project-a', path=str(repaired))).status, 'applied')
        self.assertEqual(self.apply(self.preview('remove', project='project-b')).status, 'applied')
        self.document['projects'][0]['path'] = str(repaired); self.write_config()
        self.context.project_launcher_config = self.config
        self.assertTrue(any(f.state in lifecycle.BLOCKING for f in self.install('project-launcher').findings))

    def test_remove_last_preserves_foreign_panel_and_other_features(self):
        self.installed('status')
        self.assertEqual(self.apply(self.preview('remove', project='project-a')).status, 'applied')
        preview = self.preview('remove', project='project-b')
        self.assertTrue(preview.removes_launcher)
        self.assertEqual(self.apply(preview).status, 'applied')
        receipt = state.load(self.context.paths.data/'receipt.json')
        self.assertEqual(receipt.selection.features, {'status'})
        self.assertEqual(self.native['profiles'][0]['bar'], self.bar)
        self.assertFalse(self.dynamic.exists()); self.assertTrue(self.folder.exists())

    def test_hidden_reference_blocks_last_removal(self):
        self.installed()
        self.assertEqual(self.apply(self.preview('remove', project='project-a')).status, 'applied')
        guid = json.loads(self.dynamic.read_bytes())['Profiles'][0]['Guid']
        self.calls.clear()
        self.native['profiles'].append(dict(guid='foreign', name='Foreign', bar=copy.deepcopy(self.bar), working_directory=None, references=[guid]))
        preview = self.preview('remove', project='project-b')
        self.assertEqual(preview.status, 'conflict')
        self.assertFalse(any(c['operation'].startswith('write_') for c in self.calls))

    def test_panel_drift_and_late_inverse_conflict(self):
        self.installed()
        for target in ('native', 'config', 'dynamic', 'receipt'):
            with self.subTest(target=target):
                preview = self.preview('rename', project='project-a', name='Changed')
                path = {'config': self.context.paths.config/'iterm2-utils-project-launcher.json', 'dynamic': self.dynamic,
                        'receipt': self.context.paths.data/'receipt.json'}.get(target)
                old = path.read_bytes() if path else copy.deepcopy(self.native)
                if path: path.write_bytes(old+b' ')
                else: self.native['profiles'][0]['bar']['Show Status Bar'] = False
                self.calls.clear()
                self.assertEqual(self.apply(preview).status, 'conflict')
                self.assertFalse(any(c['operation'].startswith('write_') for c in self.calls))
                if path: path.write_bytes(old)
                else: self.native = old
        preview = self.preview('rename', project='project-a', name='Changed')
        before = self.dynamic.read_bytes(); original = engine._set
        def fail_bar(resource, *args, **kwargs):
            if resource['kind'] == 'profile_bar': raise ValueError('known no write')
            return original(resource, *args, **kwargs)
        with patch.object(engine, '_set', side_effect=fail_bar):
            self.assertEqual(self.apply(preview).status, 'rolled_back')
        self.assertEqual(self.dynamic.read_bytes(), before)
        self.assertFalse((self.context.paths.data/'journal').exists())
        def unknown_bar(resource, *args, **kwargs):
            if resource['kind'] == 'profile_bar': raise iterm.MutationUnknown()
            return original(resource, *args, **kwargs)
        preview = self.preview('rename', project='project-a', name='Changed')
        with patch.object(engine, '_set', side_effect=unknown_bar):
            self.assertEqual(self.apply(preview).status, 'unknown')
        self.assertTrue((self.context.paths.data/'journal').exists())

    def test_late_inverse_conflict_retains_journal(self):
        self.installed()
        preview = self.preview('rename', project='project-a', name='Changed')
        original = engine._set
        def conflict(resource, *args, **kwargs):
            if resource['kind'] == 'profile_bar':
                self.dynamic.write_bytes(self.dynamic.read_bytes()+b' ')
                raise ValueError('concurrent edit blocks inverse')
            return original(resource, *args, **kwargs)
        with patch.object(engine, '_set', side_effect=conflict):
            self.assertEqual(self.apply(preview).status, 'unknown')
        self.assertTrue((self.context.paths.data/'journal'/'intent.json').exists())

    def test_pending_journal_and_disabled_registration_fail_before_write(self):
        self.installed()
        preview = self.preview('rename', project='project-a', name='Changed')
        def denied(): raise ValueError('disabled registration')
        pending = self.preview('rename', project='project-a', name='Changed')
        with patch.object(engine, '_recover', side_effect=AssertionError('must not recover')):
            self.assertEqual(self.apply(preview, denied).status, 'blocked')
            journal = self.context.paths.data/'journal'; journal.mkdir()
            self.assertEqual(self.preview('rename', project='project-a', name='Other').status, 'blocked')
            self.assertEqual(self.apply(pending).status, 'blocked')
        self.assertFalse(any(c['operation'].startswith('write_') for c in self.calls))

    def test_add_appends_uuid_and_preserves_existing_rows(self):
        self.installed()
        folder = self.folder.with_name('third'); folder.mkdir()
        preview = self.preview('add', name='Third', path=str(folder))
        self.assertEqual(preview.status, 'ready')
        import uuid
        uuid.UUID(preview.after[-1].id)
        self.assertEqual(preview.after[:-1], preview.before)
        self.assertEqual(self.apply(preview).status, 'applied')
        self.assertEqual(edits.list_owned_projects(self.context.paths, self.profile).projects, preview.after)
        self.assertEqual(self.apply(preview).status, 'conflict')

    def test_unsafe_replacements_and_oversized_inputs_are_rejected(self):
        self.installed()
        config = self.context.paths.config/'iterm2-utils-project-launcher.json'
        saved = config.read_bytes()
        replacement = config.with_name('replacement'); replacement.write_bytes(saved)
        config.unlink(); config.symlink_to(replacement)
        self.assertEqual(edits.list_owned_projects(self.context.paths, self.profile).status, 'conflict')
        config.unlink(); config.write_bytes(saved)
        self.assertEqual(self.preview('add', name='X'*257, path=str(self.folder)).status, 'conflict')
        self.assertEqual(self.preview('move', project='project-a', path='relative').status, 'conflict')
        self.assertFalse(any(c['operation'].startswith('write_') for c in self.calls))

    def test_authorize_runs_under_lock_before_recovery(self):
        self.installed()
        preview = self.preview('rename', project='project-a', name='Changed')
        authorized = []
        recover = engine._recover
        def authorize():
            with self.assertRaises(BlockingIOError):
                with engine._lock(self.context):
                    pass
            authorized.append(True)
        def recovery(*args):
            self.assertEqual(authorized, [True])
            return recover(*args)
        with patch.object(engine, '_recover', side_effect=recovery):
            self.assertEqual(self.apply(preview, authorize).status, 'applied')

    def test_preview_does_not_hold_lock_and_ignores_unrelated_native_drift(self):
        self.installed()
        preview = self.preview('rename', project='project-a', name='Changed')
        with engine._lock(self.context):
            self.assertEqual(self.preview('rename', project='project-b', name='Other').status, 'ready')
        self.native['profiles'].append(dict(guid='unrelated', name='Unrelated', bar=copy.deepcopy(self.bar), working_directory=None, references=[]))
        self.assertEqual(self.apply(preview).status, 'applied')


# Avoid running inherited launcher cases twice in this module.
for _name in tuple(LauncherFixture.__dict__):
    if _name.startswith('test_') and _name not in ProjectEditTests.__dict__:
        setattr(ProjectEditTests, _name, None)
del LauncherFixture
