"""Manual handoff uses temporary files and the real bounded adapter only."""
import copy
import json
import os
import unittest

from iterm2_utils import state
from iterm2_utils.discovery import discover, resolve_paths
from iterm2_utils.features import project_launcher as launcher
from iterm2_utils.models import OmpProfile, Receipt, Selection
from tests.support import Fixture


class HandoffTests(unittest.TestCase):
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
