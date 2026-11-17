import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from iterm2_utils import legacy_state, state
from iterm2_utils.models import OmpProfile, Receipt, Selection


def legacy_fixture(target='/fixture/settings.json'):
    return {'version':'1', 'selection':{'agents':['codex'], 'features':['clipboard'],
            'shortcuts':[], 'parent_profile':'Default', 'adopt_legacy':False},
            'resources':[{'kind':'json', 'target':target, 'locator':{'mode':384, 'pointer':['ours']},
                'before':{'exists':True,'value':0}, 'installed':{'exists':True,'value':1},
                'owners':['clipboard'], 'version':'1'}], 'pending_ui':[]}


class LegacyStateTests(unittest.TestCase):
    def test_v1_bare_and_pair_owners_keep_original_inverse(self):
        for owners in (['clipboard'], ['codex:clipboard'], ['shared:runtime', 'codex:clipboard']):
            raw = legacy_fixture()
            raw['resources'][0]['owners'] = owners
            saved = copy.deepcopy(raw)
            receipt = legacy_state.decode(raw)
            self.assertIsInstance(receipt, legacy_state.LegacyReceipt)
            self.assertNotIsInstance(receipt.selection, Selection)
            self.assertEqual(receipt.resources, saved['resources'])
            self.assertEqual(receipt.ui_snapshots, {})
            self.assertEqual(raw, saved)

    def test_dispatch_historical_without_promoting_to_current(self):
        with TemporaryDirectory() as root:
            path = Path(root)/'receipt.json'
            path.write_text(json.dumps(legacy_fixture()))
            receipt = state.load(path)
            self.assertIsInstance(receipt, legacy_state.LegacyReceipt)
            with self.assertRaises(ValueError):
                state.save(path, receipt)
            self.assertEqual(json.loads(path.read_text()), legacy_fixture())

    def test_malformed_or_unknown_history_grants_no_ownership(self):
        mutations = (
            lambda r:r.update(version='999'),
            lambda r:r.update(selection=[]),
            lambda r:r['selection'].update(agents=['unknown']),
            lambda r:r['selection'].update(features=['unknown']),
            lambda r:r['selection'].update(adopt_legacy=1),
            lambda r:r['resources'][0].update(owners=['foreign:clipboard']),
            lambda r:r['resources'][0].update(owners=['unknown']),
            lambda r:r['resources'][0].update(version='2'),
            lambda r:r.update(pending_ui=[{'code':1}]),
            lambda r:r.update(ui_snapshots={'unknown':[]}),
        )
        for mutate in mutations:
            raw = legacy_fixture(); mutate(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                legacy_state.decode(raw)

    def test_pairwise_historical_selection_is_preserved(self):
        raw = legacy_fixture()
        raw['selection'].update(agent_features={'codex':['clipboard']}, agent_shortcuts={'codex':[]})
        receipt = legacy_state.decode(raw)
        with TemporaryDirectory() as root:
            path = Path(root)/'receipt.json'
            state.save_recovery(path, receipt)
            stored = state.load(path)
        self.assertEqual(stored.selection.agent_features, {'codex':['clipboard']})
        self.assertEqual(stored.selection.agent_shortcuts, {'codex':[]})
        self.assertEqual(stored.resources, raw['resources'])

    def test_uninstall_journal_can_retain_owners_outside_remaining_selection(self):
        raw = legacy_fixture()
        raw['selection']['features'] = []
        raw['resources'][0]['owners'] = ['codex:clipboard']
        self.assertEqual(legacy_state.decode(raw).resources, raw['resources'])

    def test_historical_omp_bootstrap_receipt_stays_independent(self):
        raw = legacy_fixture()
        raw['selection'].update(agents=['omp'], features=['bootstrap-skill'])
        raw['resources'][0]['owners'] = ['bootstrap-skill']
        self.assertEqual(legacy_state.decode(raw).selection.agents, {'omp'})

    def test_v1_rejects_native_only_resources_accepted_by_current_v2(self):
        profile = OmpProfile(None, Path('/fixture/.omp/agent'))
        for kind, key, value, owner, filename in (
                ('omp_setting', 'terminal.programStatus', True, 'status', 'config.yml'),
                ('omp_binding', 'app.session.resume', 'Alt+R', 'shortcuts', 'keybindings.yml')):
            resource = dict(kind=kind, target=str(profile.agent_dir/filename),
                locator={'key':key,'profile':None,'agent_dir':str(profile.agent_dir),'mode':0o600},
                before={'exists':False,'value':None}, installed={'exists':True,'value':value},
                owners=[owner], version='1')
            current = Receipt('2', Selection(frozenset({owner}), frozenset(), 'Default', profile), [resource], [])
            state.validate(current)
            historical = legacy_fixture()
            historical['selection']['features'] = [owner]
            historical['resources'] = [resource]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                legacy_state.decode(historical)
