import unittest
from tests.support import Fixture
from iterm2_utils.discovery import discover, resolve_paths
from iterm2_utils.legacy_state import LegacySelection
from iterm2_utils.planner import plan, validate


class SelectionTests(unittest.TestCase):
    def test_appearance_pairs_are_codex_only_even_for_legacy_both_selection(self):
        from iterm2_utils.legacy_state import resource_pairs
        with Fixture() as f:
            context=discover(resolve_paths(),f.runner)
            selection=LegacySelection(frozenset({'codex','claude'}),frozenset({'appearance','shell'}),frozenset(),'Default')
            self.assertEqual(selection.agents_for('appearance'),{'codex'})
            self.assertEqual(selection.explicit().features_for('claude'),{'shell'})
            self.assertEqual(resource_pairs(selection,'appearance','',context),{'codex:appearance'})

    def test_missing_binary_blocks_only_affected_feature(self):
        with Fixture() as f:
            (f.bin / 'terminal-notifier').unlink()
            context = discover(resolve_paths(), f.runner)
            findings = validate(LegacySelection(frozenset({'codex'}), frozenset({'notifications', 'shell'}), frozenset(), 'Default'), context)
            self.assertTrue(any(x.feature == 'notifications' and x.state == 'missing_dependency' for x in findings))
            self.assertTrue(any(x.feature == 'shell' and x.state == 'ready' for x in findings))

    def test_claude_does_not_select_codex_only_features(self):
        with Fixture() as f:
            context = discover(resolve_paths(), f.runner)
            result = plan(context, LegacySelection(frozenset({'claude'}), frozenset({'clipboard', 'shell'}), frozenset(), 'Default'))
            self.assertNotIn('clipboard', result.selection.features)
            self.assertIn('shell', result.selection.features)
            self.assertTrue(any(x.feature == 'clipboard' and x.state == 'unavailable' for x in result.changes.findings))
            self.assertTrue(result.changes.edits)
            self.assertFalse(any(e.owner == 'clipboard' for e in result.changes.edits))
            startup=next(e.after for e in result.changes.edits if e.path==context.paths.zshrc)
            self.assertNotIn(b'codex.zsh',startup)
            self.assertIn(b'shell_integration',startup)

    def test_shortcuts_require_explicit_valid_selection(self):
        with Fixture() as f:
            context = discover(resolve_paths(), f.runner)
            for features, shortcuts in (({'shell'}, {'ctrl-q'}), ({'shortcuts'}, set()), ({'shortcuts'}, {'unknown'})):
                findings = validate(LegacySelection(frozenset({'codex'}), frozenset(features), frozenset(shortcuts), 'Default'), context)
                self.assertTrue(any(x.state == 'conflict' for x in findings))

    def test_legacy_status_reuse_does_not_install_second_shell_wrapper(self):
        with Fixture() as f:
            from dataclasses import replace
            context=replace(discover(resolve_paths(),f.runner),installed={'codex-status':{'enabled':True}})
            selection=LegacySelection(frozenset({'codex'}),frozenset({'status'}),frozenset(),'Default')
            result=plan(context,selection)
            self.assertFalse(result.changes.edits)
            self.assertTrue(any(f.code=='existing_status' for f in result.changes.findings))


class CurrentLifecycleTests(unittest.TestCase):
    def context(self, root):
        from pathlib import Path
        from iterm2_utils.models import Context, OmpProfile, Paths
        root = Path(root)
        profile = OmpProfile(None, root/'.omp/agent')
        paths = Paths(root, root/'.zshrc', root/'config', root/'cache', root/'data', root/'profiles', root)
        return Context(paths, {'iterm2':root/'iterm', 'zsh':root/'zsh', 'omp':root/'omp', 'python3':root/'python'},
                       {'python3':'3.11.9'}, frozenset({'macos'}), {}, {}, omp_profile=profile)

    def test_historical_lifecycle_requires_migration_without_discovery(self):
        import json
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from iterm2_utils import lifecycle, state
        from iterm2_utils.models import Selection
        from tests.test_legacy_state import legacy_fixture
        with TemporaryDirectory() as root:
            context = self.context(root)
            context.paths.data.mkdir()
            path = context.paths.data/'receipt.json'
            raw = legacy_fixture()
            path.write_text(json.dumps(raw))
            selection = Selection(frozenset({'shell'}),frozenset(),'Default',context.omp_profile)
            with patch('iterm2_utils.discovery.discover',side_effect=AssertionError('historical discovery')), \
                    patch.object(lifecycle, 'plan', side_effect=AssertionError('historical builder')):
                for result in (lifecycle.install(context,selection,None), lifecycle.update(context,None),
                               lifecycle.uninstall(context,frozenset({'clipboard'}),None),
                               lifecycle.reconcile_ui(context,'unknown',None)):
                    self.assertTrue(any(f.code=='migration_required' for f in result.findings))
                self.assertTrue(any(f.code=='migration_required' for f in lifecycle.doctor(context,state.load(path),None)))
            self.assertEqual(json.loads(path.read_text()), raw)

    def test_current_checkpoints_commit_independently_and_keep_original_inverse(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from iterm2_utils import lifecycle, state
        from iterm2_utils.models import ChangeSet, FileEdit, Plan, Selection
        with TemporaryDirectory() as root:
            context = self.context(root)
            first, second = context.paths.home/'shell', context.paths.home/'clipboard'
            first.write_bytes(b'original')
            second.write_bytes(b'user change')
            selection = Selection(frozenset({'shell','clipboard'}),frozenset(),'Default',context.omp_profile)
            def builder(context, chosen):
                edits = [FileEdit(first,first.read_bytes(),b'installed',0o600,'shell')]
                if 'clipboard' in chosen.features:
                    edits.append(FileEdit(second,b'expected',b'installed',0o600,'clipboard'))
                return Plan(chosen,ChangeSet(edits,[],[]),'fixture')
            with patch.object(lifecycle, 'plan', side_effect=builder):
                result = lifecycle.install(context,selection,None)
            self.assertEqual(first.read_bytes(),b'installed')
            self.assertEqual(second.read_bytes(),b'user change')
            self.assertEqual(result.receipt.selection.features,{'shell'})
            self.assertTrue(any(f.code=='feature_checkpoint' for f in result.findings))
            self.assertTrue(any(f.code=='apply_conflict' for f in result.findings))
            self.assertEqual(state.load(context.paths.data/'receipt.json'),result.receipt)
            restored = lifecycle.uninstall(context,frozenset({'shell'}),None)
            self.assertEqual(first.read_bytes(),b'original')
            self.assertEqual(restored.receipt.resources,[])

    def test_current_lifecycle_recovers_intent_before_building(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from iterm2_utils import lifecycle, state
        from iterm2_utils.models import ChangeSet, FileEdit, Plan, Receipt, Selection
        with TemporaryDirectory() as root:
            context = self.context(root)
            target = context.paths.home/'settings.json'
            target.write_bytes(b'{"ours":1,"foreign":7}')
            selection = Selection(frozenset({'shell'}),frozenset(),'Default',context.omp_profile)
            resource = dict(kind='json',target=str(target),locator={'mode':384,'pointer':['ours']},
                before={'exists':True,'value':0},installed={'exists':True,'value':1},owners=['shell'],version='1')
            journal = context.paths.data/'journal'
            state.save(journal/'intent.json',Receipt('2',selection,[resource],[]))
            def builder(context, chosen):
                import json
                self.assertEqual(json.loads(target.read_bytes()),{'ours':0,'foreign':7})
                return Plan(chosen,ChangeSet([FileEdit(context.paths.home/'new',None,b'installed',0o600,'shell')],[],[]),'fixture')
            with patch.object(lifecycle, 'plan', side_effect=builder):
                result = lifecycle.install(context,selection,None)
            self.assertFalse(any(f.state=='conflict' for f in result.findings))
            self.assertEqual((context.paths.home/'new').read_bytes(),b'installed')
            self.assertFalse(journal.exists())

    def test_current_uninstall_keeps_shared_consumers_if_recomposition_is_unavailable(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from iterm2_utils import engine, lifecycle, state
        from iterm2_utils.models import ChangeSet, FileEdit, Plan, Selection
        with TemporaryDirectory() as root:
            context = self.context(root)
            target = context.paths.home/'shared'
            selection = Selection(frozenset({'shell','status'}),frozenset(),'Default',context.omp_profile)
            changes = ChangeSet([FileEdit(target,None,b'shared',0o600,'shared:runtime')],[],[],
                                {'shared:runtime':frozenset({'shell','status'})})
            initial = engine.apply(Plan(selection,changes,'fixture'),context,None)
            with patch.object(lifecycle, 'plan', side_effect=lambda context, chosen: Plan(chosen,ChangeSet([],[],[]),'fixture')):
                result = lifecycle.uninstall(context,frozenset({'shell'}),None)
            self.assertTrue(any(f.code=='recomposition_unavailable' for f in result.findings))
            self.assertEqual(target.read_bytes(),b'shared')
            self.assertEqual(state.load(context.paths.data/'receipt.json'),initial.receipt)
            self.assertEqual(result.receipt,initial.receipt)

    def test_bootstrap_receipt_path_is_not_recovered_by_feature_lifecycle(self):
        from tempfile import TemporaryDirectory
        from iterm2_utils import lifecycle, state
        from iterm2_utils.models import Receipt, Selection
        with TemporaryDirectory() as root:
            context = self.context(root)
            selection = Selection(frozenset(),frozenset(),'Default',context.omp_profile)
            state.save(context.paths.data/'receipt.json',Receipt('2',selection,[],[]))
            journal = context.paths.data/'bootstrap-skill-iterm2-launch/journal'
            journal.mkdir(parents=True)
            (journal/'intent.json').write_bytes(b'not feature state')
            result = lifecycle.update(context,None)
            self.assertEqual(result.findings,[])
            self.assertEqual((journal/'intent.json').read_bytes(),b'not feature state')

    def test_current_shell_preflight_is_independent_of_omp_and_python(self):
        from dataclasses import replace
        from tempfile import TemporaryDirectory
        from iterm2_utils.models import Selection
        with TemporaryDirectory() as root:
            context = self.context(root)
            context = replace(context, executables={k:v for k,v in context.executables.items() if k in {'iterm2','zsh'}},
                              versions={})
            selection = Selection(frozenset({'shell'}),frozenset(),'Default',context.omp_profile)
            findings = validate(selection,context)
            self.assertTrue(any(f.feature=='shell' and f.state=='ready' for f in findings))
            self.assertFalse(any(f.state in {'conflict','missing_dependency','unavailable'} for f in findings))

    def test_current_profile_choice_is_shared_with_builder_and_receipt(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from iterm2_utils import lifecycle
        from iterm2_utils.models import ChangeSet, FileEdit, OmpProfile, Plan, Selection
        with TemporaryDirectory() as root:
            context = self.context(root)
            profile = OmpProfile('work',context.paths.home/'.omp/profiles/work/agent')
            selection = Selection(frozenset({'shell'}),frozenset(),'Default',profile)
            def builder(context, chosen):
                self.assertEqual(context.omp_profile,profile)
                return Plan(chosen,ChangeSet([FileEdit(context.paths.home/'shell',None,b'installed',0o600,'shell')],[],[]),'fixture')
            with patch.object(lifecycle,'plan',side_effect=builder):
                result = lifecycle.install(context,selection,None)
            self.assertEqual(result.receipt.selection.omp_profile,profile)
            self.assertFalse(any(f.state=='conflict' for f in result.findings))

    def test_cli_historical_update_stops_before_old_agent_discovery(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        from iterm2_utils.cli import main
        from tests.test_legacy_state import legacy_fixture
        with Fixture():
            paths = resolve_paths()
            paths.data.mkdir(parents=True)
            (paths.data/'receipt.json').write_text(json.dumps(legacy_fixture()))
            output = io.StringIO()
            with patch('iterm2_utils.cli.discover',side_effect=AssertionError('old agent discovery')), contextlib.redirect_stdout(output):
                status = main(['update','--json'])
            self.assertEqual(status,2)
            self.assertTrue(any(f['code']=='migration_required' for f in json.loads(output.getvalue())['findings']))
