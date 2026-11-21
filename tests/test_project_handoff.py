"""Manual handoff uses temporary files and the real bounded adapter only."""
import copy
import json
import os
import unittest
import base64
import io
from contextlib import contextmanager, redirect_stdout
from unittest.mock import patch

from iterm2_utils import state
from iterm2_utils.discovery import discover, resolve_paths
from iterm2_utils.features import project_launcher as launcher
from iterm2_utils.models import OmpProfile, Receipt, Selection
from tests.support import Fixture


class HandoffTests(unittest.TestCase):
    def test_deep_source_and_sibling_return_bounded_cli_conflict(self):
        from iterm2_utils import cli
        nested = b'[' * 2000 + b'0' + b']' * 2000
        for sibling in (False, True):
            with self.subTest(sibling=sibling):
                self.write_source()
                target = self.paths.profiles/'sibling.json' if sibling else self.source
                target.write_bytes(nested)
                before = self.fixture.snapshot()
                output = io.StringIO()
                # Exercise the recursive stdlib parser even on Python with an iterative C decoder.
                with patch.object(cli, 'Runner', return_value=self.runner), \
                     patch.object(cli, 'discover', return_value=self.context), \
                     patch('json.scanner.make_scanner', json.scanner.py_make_scanner), redirect_stdout(output):
                    code = cli.main(['handoff-project-launcher', '--source', str(self.source),
                        '--profile', 'Default', '--profile', 'Panel', '--json'])
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(output.getvalue()), {'mode':'handoff_preview','status':'conflict','fingerprint':None})
                self.assertEqual(self.fixture.snapshot(), before)

    def setUp(self):
        self.fixture = Fixture().__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        self.context = discover(resolve_paths(), self.fixture.runner, features=frozenset({'project-launcher'}))
        self.runner = self.fixture.runner
        self.paths = self.context.paths
        self.paths.profiles.mkdir(parents=True, exist_ok=True)
        self.paths.data.mkdir(parents=True, exist_ok=True)
        self.source = self.paths.profiles/'manual.json'
        self.guids = ['A1234567-1234-4123-8123-123456789ABC', 'B1234567-1234-4123-8123-123456789ABC']
        self.projects = []
        for i in range(2):
            folder = self.paths.home/f'project-{i}'; folder.mkdir()
            self.projects.append(dict(id=self.guids[i], name=f'Project {i}', path=str(folder)))
        document = dict(handoff=dict(guids=dict(zip(self.guids, self.guids))))
        self.bar = {'Show Status Bar': True, 'Status Bar Layout': {'components':
            [launcher._component(p, document) for p in self.projects]}}
        self.rows = [dict(Name=p['name'], Guid=p['id'], **{'Dynamic Profile Parent GUID':'parent',
            'Custom Directory':'Yes', 'Working Directory':p['path'], **copy.deepcopy(self.bar)}) for p in self.projects]
        self.profile = OmpProfile(None, self.paths.home/'.omp')
        selection = Selection(frozenset({'status'}), frozenset(), 'Default', self.profile)
        state.save(self.paths.data/'receipt.json', Receipt(state.VERSION, selection, [], []))
        self.context.omp_profile = self.profile
        self.native = dict(complete=True, profiles=[], sessions=[], default_guid='parent', position=1)
        for guid, name in [('parent','Default'), ('panel','Panel')]:
            self.native['profiles'].append(dict(guid=guid, name=name, bar=copy.deepcopy(self.bar),
                working_directory=None, references=[]))
        for row in self.rows:
            self.native['profiles'].append(dict(guid=row['Guid'], name=row['Name'], bar=copy.deepcopy(self.bar),
                working_directory=row['Working Directory'], references=[], launch={
                    'parent_guid':'parent', 'custom_directory':'Yes', 'custom_command':'No', 'command':''}))
        self.native['sessions'] = [dict(id='buried-or-visible', profile_guid='panel',
            bar=copy.deepcopy(self.bar), references=[], provenance=True)]
        self.write_source()

    def write_source(self):
        self.source.write_text(json.dumps({'Profiles':self.rows}))

    def preview(self):
        from iterm2_utils import project_handoff
        self.runner.responses['python3'] = json.dumps({'status':'ok', 'value':self.native})
        return project_handoff.prepare_handoff(self.context, self.runner, self.source, ('Default','Panel'))

    def test_matching_manual_panel_previews_with_no_writes(self):
        before = self.fixture.snapshot(); info = self.source.stat()
        preview = self.preview()
        self.assertEqual(preview.status, 'ready')
        self.assertEqual(list(preview._checkpoint['document']['handoff']['guids'].values()), self.guids)
        self.assertEqual([p['name'] for p in preview._checkpoint['document']['projects']], ['Project 0','Project 1'])
        self.assertEqual(preview._checkpoint['receipt'].selection.omp_profile, self.profile)
        self.assertEqual(preview.fingerprint, self.preview().fingerprint)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.source.stat().st_mtime_ns, info.st_mtime_ns)
        self.assertTrue(all(json.loads(c[2])['operation'] == 'inspect' for c in self.runner.calls if c[2]))

    def test_competing_dynamic_definition_and_incomplete_provenance_block(self):
        decoy = self.paths.profiles/'decoy.json'
        for kind in ('duplicate', 'symlink', 'malformed', 'nested', 'oversized'):
            with self.subTest(kind=kind):
                if kind == 'duplicate':
                    decoy.write_text(json.dumps({'Profiles':[self.rows[0]]}))
                elif kind == 'symlink':
                    decoy.symlink_to(self.source)
                elif kind == 'malformed':
                    decoy.write_text('{')
                elif kind == 'nested':
                    decoy.mkdir()
                    (decoy/'hidden.json').write_text(json.dumps({'Profiles':[self.rows[0]]}))
                else:
                    decoy.write_bytes(b' ' * 1048577)
                try:
                    before = self.fixture.snapshot()
                    self.assertEqual(self.preview().status, 'conflict')
                    self.assertEqual(self.fixture.snapshot(), before)
                finally:
                    if decoy.is_dir():
                        (decoy/'hidden.json').unlink(); decoy.rmdir()
                    else:
                        decoy.unlink()

    def test_source_provenance_is_bound_into_witness(self):
        decoy = self.paths.profiles/'unrelated.json'
        decoy.write_text(json.dumps({'Profiles':[{'Guid':'unrelated'}]}))
        preview = self.preview()
        self.assertEqual(preview.status, 'ready')
        decoy.write_bytes(decoy.read_bytes()+b' ')
        self.assertNotEqual(self.preview().fingerprint, preview.fingerprint)

    def test_source_visibility_accepts_only_native_boolean_forms(self):
        for value in (True, 1, False, 0, 2, '1', None, 1.0):
            with self.subTest(value=value, type=type(value)):
                self.rows[0]['Show Status Bar'] = value
                self.write_source()
                self.assertEqual(self.preview().status, 'ready' if value is True or type(value) is int and value == 1 else 'conflict')

    def test_untrusted_manual_panel_does_not_preview(self):
        cases = ['foreign-field','foreign-row','duplicate-path','command','directory','parent','live-command',
            'reordered','other-panel','source-bar','default','source-session','unknown-provenance',
            'hidden-profile','hidden-session','unselected','position','incomplete','source-order',
            'catalogue','standard-source','symlink','hardlink','outside','oversized','journal','receipt-profile',
            'hidden-widget']
        for case in cases:
            with self.subTest(case=case):
                # Each case has an independent fixture and no preexisting managed data.
                test = HandoffTests(); test.setUp()
                try:
                    rows, native = test.rows, test.native
                    if case == 'foreign-field': rows[0]['Foreign'] = True
                    elif case == 'foreign-row': rows.append(copy.deepcopy(rows[0]))
                    elif case == 'duplicate-path': rows[1]['Working Directory'] = rows[0]['Working Directory']
                    elif case == 'command': rows[0]['Command'] = 'echo unsafe'
                    elif case == 'directory': rows[0]['Custom Directory'] = 'No'
                    elif case == 'parent': rows[0]['Dynamic Profile Parent GUID'] = 'panel'
                    elif case == 'live-command': native['profiles'][2]['launch']['custom_command'] = 'Yes'
                    elif case == 'reordered': native['profiles'][0]['bar']['Status Bar Layout']['components'].reverse()
                    elif case == 'other-panel': native['profiles'][1]['bar']['Show Status Bar'] = False
                    elif case == 'source-bar': rows[0]['Show Status Bar'] = False
                    elif case == 'default': native['default_guid'] = test.guids[0]
                    elif case == 'source-session': native['sessions'][0]['profile_guid'] = test.guids[0]
                    elif case == 'unknown-provenance': native['sessions'][0]['provenance'] = False
                    elif case == 'hidden-profile': native['profiles'][0]['references'] = [test.guids[0]]
                    elif case == 'hidden-session': native['sessions'][0]['references'] = [test.guids[0]]
                    elif case == 'unselected': native['profiles'].append(dict(guid='foreign', name='Foreign',
                        bar=copy.deepcopy(test.bar), working_directory=None, references=[test.guids[0]]))
                    elif case == 'position': native['position'] = 0
                    elif case == 'incomplete': native['complete'] = False
                    elif case == 'source-order': rows.reverse()
                    elif case == 'catalogue':
                        test.paths.config.mkdir(parents=True, exist_ok=True)
                        (test.paths.config/launcher.FILENAME).write_text('{}')
                    elif case == 'standard-source': (test.paths.profiles/launcher.FILENAME).write_text('{}')
                    elif case == 'journal': (test.paths.data/'journal').mkdir()
                    elif case == 'hidden-widget':
                        native['profiles'][1]['bar']['Status Bar Layout']['components'].append(
                            {'class':'foreign', 'hidden':test.guids[0]})
                    elif case == 'receipt-profile': test.context.omp_profile = OmpProfile('other', test.paths.home/'other')
                    test.write_source()
                    if case == 'symlink':
                        target = test.source.with_name('target.json'); test.source.rename(target); test.source.symlink_to(target)
                    elif case == 'hardlink': os.link(test.source, test.source.with_name('alias.json'))
                    elif case == 'outside':
                        target = test.paths.home/'outside.json'; test.source.rename(target); test.source = target
                    elif case == 'oversized': test.source.write_bytes(b' ' * 1048577)
                    before = test.fixture.snapshot()
                    result = test.preview()
                    self.assertIn(result.status, {'blocked','conflict'})
                    self.assertIsNone(result._checkpoint)
                    self.assertIsNone(result.fingerprint)
                    self.assertNotIn(str(test.source), repr(result))
                    self.assertEqual(test.fixture.snapshot(), before)
                finally:
                    test.doCleanups()

    def test_witness_binds_bytes_mode_receipt_and_relevant_native_evidence(self):
        original = self.preview().fingerprint
        self.source.write_bytes(self.source.read_bytes()+b' ')
        self.assertNotEqual(self.preview().fingerprint, original)
        original = self.preview().fingerprint
        self.source.chmod(0o640)
        self.assertNotEqual(self.preview().fingerprint, original)
        original = self.preview().fingerprint
        receipt = self.paths.data/'receipt.json'; receipt.write_bytes(receipt.read_bytes()+b' ')
        self.assertNotEqual(self.preview().fingerprint, original)
        original = self.preview().fingerprint
        self.native['profiles'].append(dict(guid='unrelated', name='Unrelated', bar=copy.deepcopy(self.bar),
            working_directory='/unrelated', references=[]))
        self.assertEqual(self.preview().fingerprint, original)
        self.native['sessions'][0]['id'] = 'changed-session'
        self.assertNotEqual(self.preview().fingerprint, original)

    def apply(self, fingerprint=None, profiles=('Default','Panel')):
        from iterm2_utils import project_handoff
        if fingerprint is None:
            fingerprint = self.preview().fingerprint
        return project_handoff.apply_handoff(self.context, self.runner, self.source, profiles, fingerprint)

    def test_apply_handoff_keeps_live_panel_and_owns_exact_checkpoint(self):
        from iterm2_utils import engine, project_edits
        from iterm2_utils.models import UiStep
        receipt = state.load(self.paths.data/'receipt.json')
        foreign = self.paths.home/'unrelated'; foreign.write_bytes(b'keep')
        resource = engine._resource('file', foreign, {'mode':0o600},
            engine._encode(None), engine._encode(b'keep'), 'status')
        receipt.resources.append(resource)
        receipt.pending_ui.append(UiStep('test_pending','status',None,'Keep pending'))
        state.save(self.paths.data/'receipt.json', receipt)
        raw, info = self.source.read_bytes(), self.source.stat()
        native = copy.deepcopy(self.native)
        result = self.apply()
        self.assertFalse(result.findings)
        saved = state.load(self.paths.data/'receipt.json')
        self.assertEqual(saved, result.receipt)
        self.assertEqual(saved.selection.features, frozenset({'status','project-launcher'}))
        self.assertEqual(saved.selection.omp_profile, receipt.selection.omp_profile)
        self.assertEqual(saved.pending_ui, receipt.pending_ui)
        self.assertIn(resource, saved.resources)
        self.assertEqual(self.source.read_bytes(), raw)
        self.assertEqual((self.source.stat().st_mode, self.source.stat().st_mtime_ns),
            (info.st_mode, info.st_mtime_ns))
        self.assertEqual(self.native, native)
        owned = [r for r in saved.resources if launcher.OWNER in r['owners']]
        self.assertEqual(len(owned), 5)  # Source, catalogue, two panels, global position.
        for r in owned:
            self.assertEqual(r['owners'], [launcher.OWNER, launcher.FEATURE])
            if r['target'] != str((self.paths.config/launcher.FILENAME).resolve()):
                self.assertEqual(r['before'], r['installed'])
        source = next(r for r in owned if r['target'] == str(self.source.resolve()))
        self.assertEqual(base64.b64decode(source['before']['value']), raw)
        catalogue = self.paths.config/launcher.FILENAME
        self.assertEqual(catalogue.stat().st_mode & 0o777, 0o600)
        listed = project_edits.list_owned_projects(self.paths, self.profile)
        self.assertEqual(listed.status, 'ok')
        self.assertEqual([p.id for p in listed.projects], self.guids)
        self.assertTrue(all(json.loads(c[2])['operation'] == 'inspect' for c in self.runner.calls if c[2]))
        self.assertFalse((self.paths.data/'journal').exists())

    def test_apply_rejects_stale_witness_under_lock(self):
        from iterm2_utils import engine
        for drift in ('bytes','mode','receipt','session','bar','position','scope'):
            with self.subTest(drift=drift):
                test = HandoffTests(); test.setUp()
                try:
                    fingerprint = test.preview().fingerprint
                    lock = engine._lock
                    baseline = {}
                    @contextmanager
                    def changed(context):
                        with lock(context):
                            if drift == 'bytes': test.source.write_bytes(test.source.read_bytes()+b' ')
                            elif drift == 'mode': test.source.chmod(0o640)
                            elif drift == 'receipt':
                                path = test.paths.data/'receipt.json'; path.write_bytes(path.read_bytes()+b' ')
                            elif drift == 'session': test.native['sessions'][0]['id'] = 'changed'
                            elif drift == 'bar': test.native['profiles'][1]['bar']['Show Status Bar'] = False
                            elif drift == 'position': test.native['position'] = 0
                            test.runner.responses['python3'] = json.dumps({'status':'ok','value':test.native})
                            baseline.update(test.fixture.snapshot())
                            yield
                    with patch.object(engine, '_lock', changed):
                        result = test.apply(fingerprint, ('Default',) if drift == 'scope' else ('Default','Panel'))
                    self.assertTrue(result.findings)
                    if baseline:
                        self.assertEqual(test.fixture.snapshot(), baseline)
                    self.assertFalse((test.paths.config/launcher.FILENAME).exists())
                finally:
                    test.doCleanups()

    def test_handoff_interrupted_commit_recovers_without_readoption(self):
        from iterm2_utils import engine
        for committed in (False, True):
            with self.subTest(committed=committed):
                test = HandoffTests(); test.setUp()
                try:
                    fingerprint = test.preview().fingerprint
                    previous = state.load(test.paths.data/'receipt.json')
                    raw, save = test.source.read_bytes(), state.save
                    def interrupted(path, receipt):
                        if path == (test.paths.data/'receipt.json' if committed else test.paths.data/'journal/result.json'):
                            raise KeyboardInterrupt()
                        save(path, receipt)
                    with patch.object(state, 'save', interrupted):
                        with self.assertRaises(KeyboardInterrupt):
                            test.apply(fingerprint)
                    self.assertTrue((test.paths.data/'journal').exists())
                    self.assertEqual(state.load(test.paths.data/'receipt.json'), previous)
                    with engine._lock(test.context):
                        self.assertEqual(engine._recover(test.context, test.runner), [])
                    recovered = state.load(test.paths.data/'receipt.json')
                    self.assertEqual(launcher.FEATURE in recovered.selection.features, committed)
                    self.assertEqual(test.source.read_bytes(), raw)
                    if committed:
                        before = test.fixture.snapshot()
                        self.assertTrue(test.apply(fingerprint).findings)
                        self.assertEqual(test.fixture.snapshot(), before)
                    else:
                        self.assertFalse((test.paths.config/launcher.FILENAME).exists())
                    self.assertTrue(all(json.loads(c[2])['operation'] == 'inspect' for c in test.runner.calls if c[2]))
                finally:
                    test.doCleanups()

    def test_normal_install_never_claims_unchanged_foreign_values(self):
        from iterm2_utils import engine
        from iterm2_utils.models import ChangeSet, FileEdit, Plan
        path = self.paths.home/'foreign'; path.write_bytes(b'foreign')
        receipt = state.load(self.paths.data/'receipt.json')
        plan = Plan(receipt.selection, ChangeSet([FileEdit(path,b'foreign',b'foreign',0o600,'status')],[],[]), '')
        result = engine.apply(plan, self.context, self.runner)
        self.assertFalse(result.findings)
        self.assertEqual(result.receipt.resources, [])

    def test_cli_handoff_requires_confirmed_fingerprint_for_apply(self):
        from iterm2_utils import cli
        fingerprint = self.preview().fingerprint
        argv = ['handoff-project-launcher','--source',str(self.source),
            '--profile','Default','--profile','Panel','--json']
        def invoke(extra):
            output = io.StringIO()
            with patch.object(cli, 'Runner', return_value=self.runner), patch.object(cli, 'discover', return_value=self.context), redirect_stdout(output):
                code = cli.main(argv+extra)
            for private in (self.source.name, str(self.source), str(self.paths.home), 'Project 0', 'Working Directory'):
                self.assertNotIn(private, output.getvalue())
            return code, json.loads(output.getvalue())
        before = self.fixture.snapshot()
        self.assertEqual(invoke([]), (0, {'mode':'handoff_preview','status':'ready','fingerprint':fingerprint}))
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(invoke(['--expect-fingerprint',fingerprint])[0], 0)
        self.assertEqual(invoke(['--apply'])[0], 2)
        self.assertEqual(invoke(['--apply','--expect-fingerprint','0'*64])[0], 2)
        self.assertEqual(self.fixture.snapshot(), before)
        code, output = invoke(['--apply','--expect-fingerprint',fingerprint])
        self.assertEqual((code, output['status']), (0,'applied'))
        self.assertIn(launcher.FEATURE, state.load(self.paths.data/'receipt.json').selection.features)

    def test_pending_journal_requires_existing_recovery_without_handoff_writes(self):
        fingerprint = self.preview().fingerprint
        journal = self.paths.data/'journal'; journal.mkdir()
        before = self.fixture.snapshot()
        for confirmation in ('0'*64, fingerprint):
            result = self.apply(confirmation)
            self.assertTrue(result.findings)
            self.assertEqual(self.fixture.snapshot(), before)
            self.assertTrue(journal.exists())

    def test_late_native_drift_rolls_back_only_staged_catalogue(self):
        from iterm2_utils import engine
        fingerprint = self.preview().fingerprint
        previous = state.load(self.paths.data/'receipt.json')
        write = engine._write_file
        def changed(path, content, mode, **kwargs):
            write(path, content, mode, **kwargs)
            if path == (self.paths.config/launcher.FILENAME).resolve() and content is not None:
                self.native['sessions'][0]['id'] = 'late-session'
                self.runner.responses['python3'] = json.dumps({'status':'ok', 'value':self.native})
        with patch.object(engine, '_write_file', changed):
            result = self.apply(fingerprint)
        self.assertTrue(result.findings)
        self.assertEqual(state.load(self.paths.data/'receipt.json'), previous)
        self.assertFalse((self.paths.config/launcher.FILENAME).exists())
        self.assertFalse((self.paths.data/'journal').exists())
        self.assertTrue(all(json.loads(c[2])['operation'] == 'inspect' for c in self.runner.calls if c[2]))
