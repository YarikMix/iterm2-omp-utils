import unittest
from tests.support import Fixture
from iterm2_utils.discovery import discover, resolve_paths
from iterm2_utils.models import Selection
from iterm2_utils.planner import FEATURES, plan, validate
from tests.native_features_support import NativeFixture


class SelectionTests(NativeFixture):
    def test_all_nine_features_are_retained(self):
        self.assertEqual(FEATURES,{'clipboard','shortcuts','status','notifications','restore',
                                   'mcp','shell','appearance','project-launcher'})

    def test_shortcuts_require_explicit_valid_selection(self):
        for features,shortcuts in ((('shell',),('ctrl-q',)), (('shortcuts',),()), (('shortcuts',),('unknown',))):
            findings = validate(self.selection(*features,shortcuts=shortcuts),self.context)
            self.assertTrue(any(f.state=='conflict' for f in findings))

    def test_resume_requires_explicit_key_without_changing_independent_feature(self):
        selection = self.selection('shortcuts','shell',shortcuts=('resume',))
        findings = validate(selection,self.context)
        self.assertTrue(any(f.feature=='shortcuts' and f.code=='resume_key_required' for f in findings))
        self.assertTrue(any(f.feature=='shell' and f.state=='ready' for f in findings))

    def test_mcp_is_native_profile_scoped_and_foreign_neighbours_survive(self):
        self.context.versions['python3'] = '3.12.8'
        self.context.capabilities |= {'python:mcp'}
        from iterm2_utils import lifecycle
        import json
        path = self.profile.agent_dir/'mcp.json'
        path.write_text('{"mcpServers":{"foreign":{"command":"keep"}},"foreign":7}')
        result = lifecycle.install(self.context,self.selection('mcp'),self.runner)
        self.assertSuccess(result)
        self.assertEqual(json.loads(path.read_text())['foreign'],7)
        self.assertEqual(json.loads(path.read_text())['mcpServers']['foreign'],{'command':'keep'})
        pointers = [r['locator']['pointer'] for r in result.receipt.resources if r['kind'] == 'json']
        self.assertEqual(pointers, [['mcpServers','iterm2-observe']])
        files = [r for r in result.receipt.resources if r['kind'] == 'file']
        self.assertTrue(any(r['target'].endswith('/runtime/iterm2_mcp_entry.py') for r in files))
        self.assertTrue(any(r['target'].endswith('/extensions/iterm2-utils-projects.ts') for r in files))
        self.assertTrue(all(r['owners'] == ['mcp'] for r in result.receipt.resources))

    def test_shell_has_no_omp_bun_or_python_prerequisite(self):
        self.context.executables = {k:v for k,v in self.context.executables.items() if k in {'iterm2','zsh'}}
        findings = validate(self.selection('shell'),self.context)
        self.assertFalse([f for f in findings if f.state in {'unavailable','conflict','missing_dependency'}])

    def test_proven_transferred_launcher_configuration_does_not_require_installed_selection(self):
        import json
        from iterm2_utils import engine, state
        from iterm2_utils.features import project_launcher
        from iterm2_utils.models import FileEdit, Receipt
        source = {'profiles':['Default'],'projects':[{'id':'a','name':'Project A','path':str(self.home)}]}
        path = self.context.paths.config/project_launcher.FILENAME
        path.parent.mkdir(parents=True)
        content = json.dumps(source).encode()
        path.write_bytes(content)
        resource = engine._compile(FileEdit(path,None,content,0o600,project_launcher.OWNER))[0]
        state.save(self.context.paths.data/'receipt.json',Receipt('2',self.selection(),[resource],[]))
        config, receipt = project_launcher._load(self.context)
        self.assertEqual(config,source)
        self.assertNotIn('project-launcher',receipt.selection.features)

    def test_proven_transferred_appearance_configuration_can_be_explicitly_selected(self):
        import json
        from iterm2_utils import engine, state
        from iterm2_utils.features import appearance
        from iterm2_utils.models import FileEdit, Receipt
        path = self.context.paths.config/'appearance.json'
        path.parent.mkdir(parents=True)
        content = json.dumps({'projects':[{'root':str(self.home),'color':'#123456','icon':'ios'}]}).encode()
        path.write_bytes(content)
        resources = engine._compile(FileEdit(path,None,content,0o600,'appearance'))
        state.save(self.context.paths.data/'receipt.json',Receipt('2',self.selection(),resources,[]))
        changes = appearance.build(self.context,self.selection('appearance'))
        self.assertTrue(changes.edits)
        self.assertFalse([f for f in changes.findings if f.state=='conflict'])

    def test_foreign_mcp_collision_blocks_only_mcp(self):
        self.context.versions['python3'] = '3.12.8'
        self.context.capabilities |= {'python:mcp'}
        from iterm2_utils import lifecycle
        path = self.profile.agent_dir/'mcp.json'
        path.write_text('{"mcpServers":{"iterm2-observe":{"command":"foreign"}}}')
        before = path.read_bytes()
        result = lifecycle.install(self.context,self.selection('mcp','shell'),self.runner)
        self.assertEqual(result.receipt.selection.features,{'shell'})
        self.assertEqual(path.read_bytes(),before)
        self.assertTrue(any(f.feature=='mcp' and f.state=='conflict' for f in result.findings))

    def test_identical_foreign_mcp_entry_is_not_adopted(self):
        import json
        from iterm2_utils import lifecycle, engine
        from iterm2_utils.features import mcp
        from unittest.mock import patch
        self.context.versions['python3'] = '3.12.8'
        self.context.capabilities |= {'python:mcp'}
        path = self.profile.agent_dir/'mcp.json'
        changes = mcp.build(self.context, self.selection('mcp'))
        registration = next(edit for edit in changes.edits if edit.path == path)
        value = json.loads(registration.after)['mcpServers']['iterm2-observe']
        path.write_text(json.dumps({'mcpServers':{'iterm2-observe':value},'foreign':7}))
        before = path.read_bytes()
        with patch.object(engine, '_set', side_effect=AssertionError('Foreign entry must not write')) as write:
            result = lifecycle.install(self.context,self.selection('mcp'),self.runner)
        self.assertTrue(any(f.feature == 'mcp' and f.state == 'conflict' for f in result.findings))
        write.assert_not_called()
        self.assertEqual(result.receipt.resources,[])
        self.assertFalse((self.context.paths.data/'receipt.json').exists())
        self.assertFalse((self.context.paths.data/'mcp/releases').exists())
        self.assertEqual(path.read_bytes(),before)


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
            def builder(context, chosen, *, runner=None):
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
            def builder(context, chosen, *, runner=None):
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
            with patch.object(lifecycle, 'plan', side_effect=lambda context, chosen, **kwargs: Plan(chosen,ChangeSet([],[],[]),'fixture')):
                result = lifecycle.uninstall(context,frozenset({'shell'}),None)
            self.assertTrue(any(f.code=='recomposition_unavailable' for f in result.findings))
            self.assertEqual(target.read_bytes(),b'shared')
            self.assertEqual(state.load(context.paths.data/'receipt.json'),initial.receipt)
            self.assertEqual(result.receipt,initial.receipt)

    def test_current_checkpoint_preserves_retained_shared_consumer_requirements(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from iterm2_utils import engine, lifecycle, state
        from iterm2_utils.models import ChangeSet, FileEdit, Finding, Plan, Selection
        for emit_shared in (True, False):
            for report_blocker in (True, False):
                with self.subTest(emit_shared=emit_shared, report_blocker=report_blocker), TemporaryDirectory() as root:
                    context = self.context(root)
                    shared, exclusive = context.paths.home/'shared', context.paths.home/'shell'
                    selection = Selection(frozenset({'shell','status'}),frozenset(),'Default',context.omp_profile)
                    initial_changes = ChangeSet([
                        FileEdit(shared,None,b'shell and status',0o600,'shared:runtime'),
                        FileEdit(exclusive,None,b'shell v1',0o600,'shell')],[],[],
                        {'shared:runtime':frozenset({'shell','status'})})
                    initial = engine.apply(Plan(selection,initial_changes,'initial'),context,None)
                    self.assertFalse(initial.findings)
                    receipt_path = context.paths.data/'receipt.json'
                    committed = receipt_path.read_bytes()
                    def incomplete(context, chosen, *, runner=None):
                        edits = [FileEdit(exclusive,b'shell v1',b'shell v2',0o600,'shell')]
                        consumers = {}
                        if emit_shared:
                            edits.append(FileEdit(shared,b'shell and status',b'shell only',0o600,'shared:runtime'))
                            consumers['shared:runtime'] = frozenset({'shell'})
                        findings = ([Finding('status','omp','retained_status_blocker','conflict',
                                             'The retained status consumer could not be rebuilt.')]
                                    if report_blocker else [])
                        return Plan(chosen,ChangeSet(edits,[],findings,consumers),'incomplete')
                    requested = Selection(frozenset({'shell'}),frozenset(),'Default',context.omp_profile)
                    with patch.object(lifecycle,'plan',side_effect=incomplete):
                        result = lifecycle.install(context,requested,None)
                    self.assertEqual(shared.read_bytes(),b'shell and status')
                    self.assertEqual(exclusive.read_bytes(),b'shell v1')
                    self.assertEqual(receipt_path.read_bytes(),committed)
                    self.assertEqual(state.load(receipt_path),initial.receipt)
                    self.assertEqual(result.receipt,initial.receipt)
                    self.assertTrue(any(f.state=='conflict' for f in result.findings))
                    self.assertTrue(any(f.code=='recomposition_unavailable' for f in result.findings))
                    if report_blocker:
                        self.assertTrue(any(f.code=='retained_status_blocker' for f in result.findings))

    def test_current_checkpoint_accepts_complete_retained_shared_consumers(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from iterm2_utils import engine, lifecycle, state
        from iterm2_utils.models import ChangeSet, FileEdit, Plan, Selection
        with TemporaryDirectory() as root:
            context = self.context(root)
            target = context.paths.home/'shared'
            selection = Selection(frozenset({'shell','status'}),frozenset(),'Default',context.omp_profile)
            consumers = {'shared:runtime':frozenset({'shell','status'})}
            initial = engine.apply(Plan(selection,ChangeSet([
                FileEdit(target,None,b'both v1',0o600,'shared:runtime')],[],[],consumers),'initial'),context,None)
            self.assertFalse(initial.findings)
            def complete(context, chosen, *, runner=None):
                return Plan(chosen,ChangeSet([
                    FileEdit(target,b'both v1',b'both v2',0o600,'shared:runtime')],[],[],consumers),'complete')
            requested = Selection(frozenset({'shell'}),frozenset(),'Default',context.omp_profile)
            with patch.object(lifecycle,'plan',side_effect=complete):
                result = lifecycle.install(context,requested,None)
            self.assertFalse(any(f.state=='conflict' for f in result.findings))
            self.assertEqual(target.read_bytes(),b'both v2')
            self.assertEqual(result.receipt.resources[0]['before'],initial.receipt.resources[0]['before'])
            self.assertEqual(set(result.receipt.resources[0]['owners']),{'shared:runtime','shell','status'})
            self.assertEqual(result.receipt.selection.features,{'shell','status'})
            self.assertEqual(state.load(context.paths.data/'receipt.json'),result.receipt)

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
            def builder(context, chosen, *, runner=None):
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
