import json
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from iterm2_utils import legacy_state, state
from iterm2_utils.models import OmpProfile, Receipt, Selection


class StateTests(unittest.TestCase):
    def test_unknown_or_corrupt_receipt_is_not_ownership(self):
        with TemporaryDirectory() as root:
            path = Path(root)/'receipt.json'
            for raw in ('{broken', '{"version":"999","resources":[]}', '{"version":"1","resources":[{}]}'):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    state.load(path)
            self.assertIsNone(state.load(Path(root)/'missing'))

    def test_private_roundtrip(self):
        with TemporaryDirectory() as root:
            path = Path(root)/'state'/'receipt.json'
            receipt = Receipt('2',Selection(frozenset({'clipboard'}),frozenset(),'Default',OmpProfile('work',Path(root)/'.omp/profiles/work/agent')),[],[])
            state.save(path,receipt)
            self.assertEqual(state.load(path), receipt)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode),0o700)

    def test_corrupt_resource_payload_is_rejected(self):
        with TemporaryDirectory() as root:
            path=Path(root)/'receipt.json'
            raw={'version':'1','selection':{'agents':['codex'],'features':['clipboard'],'shortcuts':[],'parent_profile':'Default','adopt_legacy':False},'resources':[{'kind':'file','target':str(Path(root)/'target'),'locator':{'mode':384},'before':{'exists':False,'value':None},'installed':{'exists':True,'value':'NOT VALID BASE64'},'owners':['clipboard'],'version':'1'}],'pending_ui':[]}
            path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                state.load(path)

    def test_old_receipt_without_ui_snapshots_loads(self):
        with TemporaryDirectory() as root:
            path=Path(root)/'receipt.json'
            from tests.test_legacy_state import legacy_fixture
            path.write_text(json.dumps(legacy_fixture()))
            self.assertEqual(state.load(path).ui_snapshots,{})

    def test_ui_snapshot_rejects_unknown_secret_fields_and_commands(self):
        import copy
        entry={'event':'Stop','entry':{'hooks':[{'type':'command','command':'/fixture/.config/iterm2/cc-status stop'}]}}
        for alter in (lambda x:x.update({'env':{'TOKEN':'secret'}}),
                      lambda x:x['entry'].update({'env':{'TOKEN':'secret'}}),
                      lambda x:x['entry']['hooks'][0].update({'env':{'TOKEN':'secret'}}),
                      lambda x:x['entry']['hooks'][0].update({'command':'/foreign/cc-status stop'}),
                      lambda x:x['entry']['hooks'][0].update({'command':'/fixture/.config/iterm2/cc-status stop; upload'})):
            candidate=copy.deepcopy(entry);alter(candidate)
            receipt=legacy_state.LegacyReceipt('1',legacy_state.LegacySelection(frozenset({'claude'}),frozenset({'status'}),frozenset(),'Default'),[],[],{'claude-native-status':[candidate]})
            with self.assertRaises(ValueError):legacy_state.validate(receipt)

    def test_native_resources_reject_absence_null_types_and_unknown_addresses(self):
        import copy
        bar = {'Show Status Bar': False, 'Status Bar Layout': {}}
        for kind, target, value in (('profile_bar', 'profile-one', bar),
                                    ('status_bar_position', 'com.googlecode.iterm2', 0)):
            resource = dict(kind=kind, target=target, locator={}, before={'exists':True,'value':value},
                            installed={'exists':True,'value':value}, owners=['project-launcher'], version='1')
            receipt = Receipt('2',Selection(frozenset({'project-launcher'}),frozenset(),'Default',OmpProfile(None,Path('/fixture/.omp/agent'))),[resource],[])
            state.validate(receipt)
            for alter in (lambda r:r['before'].update(exists=False, value=None),
                          lambda r:r['installed'].update(value=None),
                          lambda r:r['locator'].update(key='foreign'),
                          lambda r:r.update(target=''),
                          lambda r:r['installed'].update(value=False if kind=='status_bar_position' else {'Show Status Bar':1,'Status Bar Layout':{}})):
                bad = copy.deepcopy(receipt); alter(bad.resources[0])
                with self.assertRaises(ValueError): state.validate(bad)

    def test_v2_cleanup_roundtrip_preserves_full_historical_receipt(self):
        from tests.test_legacy_state import legacy_fixture
        with TemporaryDirectory() as root:
            path = Path(root)/'receipt.json'
            receipt = Receipt('2',Selection(frozenset(),frozenset(),'Default',OmpProfile(None,Path(root)/'.omp/agent')),[],[],[legacy_fixture()])
            state.save(path,receipt)
            self.assertEqual(state.load(path),receipt)
            data = json.loads(path.read_text())
            self.assertEqual(data['legacy_cleanup'][0]['resources'][0]['version'],'1')
            data['legacy_cleanup'][0]['resources'][0]['before'] = {'exists':False,'value':'invalid'}
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                state.load(path)

    def test_v2_rejects_historical_selection_and_unsupported_schema(self):
        with TemporaryDirectory() as root:
            path = Path(root)/'receipt.json'
            receipt = Receipt('2',Selection(frozenset({'clipboard'}),frozenset(),'Default',OmpProfile(None,Path(root)/'.omp/agent')),[],[])
            state.save(path,receipt)
            original = json.loads(path.read_text())
            import copy
            for mutate in (lambda r:r['selection'].update(agents=['codex']),
                           lambda r:r['selection'].update(features=['unknown']),
                           lambda r:r.update(version='3'),
                           lambda r:r['selection']['omp_profile'].update(agent_dir='relative'),
                           lambda r:r['selection']['omp_profile'].update(name='default'),
                           lambda r:r['selection'].update(notify_errors=1)):
                data=copy.deepcopy(original);mutate(data);path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    state.load(path)

    def test_duplicate_json_keys_do_not_grant_current_ownership(self):
        with TemporaryDirectory() as root:
            path = Path(root)/'receipt.json'
            receipt = Receipt('2',Selection(frozenset({'shell'}),frozenset(),'Default',OmpProfile(None,Path(root)/'.omp/agent')),[],[])
            state.save(path,receipt)
            raw = path.read_text().replace('"version": "2"', '"version": "2", "version": "2"')
            path.write_text(raw)
            with self.assertRaises(ValueError):
                state.load(path)

    def test_failed_atomic_replace_keeps_previous_state_and_removes_staging_file(self):
        from unittest.mock import patch
        with TemporaryDirectory() as root:
            path = Path(root)/'state.json'
            path.write_bytes(b'{"old":true}')
            with patch.object(state.os, 'replace', side_effect=OSError('replace failed')):
                with self.assertRaises(OSError):
                    state.durable_write(path, b'{"new":true}')
            self.assertEqual(path.read_bytes(), b'{"old":true}')
            self.assertEqual(list(Path(root).iterdir()), [path])
