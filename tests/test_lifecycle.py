import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from iterm2_utils import lifecycle, state
from iterm2_utils.models import Selection
from tests.native_features_support import NativeFixture
from tests.support import FakeRunner
from iterm2_utils.commands import Runner


class NativeRunner(FakeRunner):
    def __init__(self):
        super().__init__()
        self.inventory = {'complete':True,'profiles':[{
            'guid':'parent','name':'Default','bar':{'Show Status Bar':False,
                'Status Bar Layout':{'components':[]}},'working_directory':None,'references':[]}],
            'sessions':[],'default_guid':'parent','position':0}

    def run(self, argv, **kwargs):
        if Path(argv[0]).name=='bun':
            return Runner().run(argv,**kwargs)
        if kwargs.get('stdin') and any('iterm2_utils.profile_api' in word for word in argv):
            import subprocess
            self.calls.append((argv,kwargs['timeout'],kwargs['stdin']))
            self.environments.append(kwargs.get('env'))
            request = json.loads(kwargs['stdin'])
            if request['operation']=='inspect':
                return subprocess.CompletedProcess(argv,0,json.dumps({'status':'ok','value':self.inventory}),'')
        return super().run(argv,**kwargs)


class LifecycleFixture(NativeFixture):
    def setUp(self):
        super().setUp()
        self.runner = NativeRunner()
        self.preferences = {}
        def read(runner,domain,key):
            return {'exists':key in self.preferences,'value':self.preferences.get(key)}
        def write(runner,domain,key,value):
            if value['exists']:
                self.preferences[key] = value['value']
            else:
                self.preferences.pop(key,None)
        for name,side in (('read',read),('write',write)):
            mock = patch('iterm2_utils.engine.preferences.'+name,side_effect=side)
            mock.start()
            self.addCleanup(mock.stop)

    def snapshot(self):
        return {str(p.relative_to(self.home)):p.read_bytes() for p in self.home.rglob('*') if p.is_file()}

    def install(self,*features,**kwargs):
        if 'mcp' in features:
            # Simulated selected optional-SDK interpreter; no host imports/install.
            self.context.versions['python3']='3.12.0'
            self.context.capabilities |= {'python:mcp'}
        return lifecycle.install(self.context,self.selection(*features,**kwargs),self.runner)


class LifecycleTests(LifecycleFixture):
    def test_failed_feature_does_not_rollback_independent_completed_feature(self):
        (self.profile.agent_dir/'config.yml').write_text('terminal: {programStatus: invalid}\n')
        result = self.install('status','notifications')
        self.assertEqual(result.receipt.selection.features,{'notifications'})
        self.assertTrue(any(f.feature=='status' and f.state=='conflict' for f in result.findings))

    def test_partial_uninstall_drops_unused_runtime_without_disabling_native_status(self):
        self.assertSuccess(self.install('status','shell'))
        result = lifecycle.uninstall(self.context,frozenset({'shell'}),self.runner)
        self.assertSuccess(result)
        self.assertEqual(result.receipt.selection.features,{'status'})
        self.assertFalse((self.context.paths.data/'current').exists())
        from iterm2_utils.config import omp
        self.assertTrue(omp.read_setting(self.profile,'terminal.programStatus',self.runner)['value'])

    def test_partial_clipboard_removal_recomposes_profile(self):
        self.assertSuccess(self.install('clipboard','shortcuts',shortcuts=('resume',),resume_key='F8'))
        result = lifecycle.uninstall(self.context,frozenset({'clipboard'}),self.runner)
        self.assertSuccess(result)
        profile = json.loads((self.context.paths.profiles/'iterm2-utils.json').read_bytes())['Profiles'][0]
        self.assertEqual(profile['Keyboard Map'],{})
        self.assertEqual(result.receipt.selection.resume_key,'F8')
        result = lifecycle.uninstall(self.context,frozenset({'shortcuts'}),self.runner)
        self.assertSuccess(result)
        self.assertFalse((self.context.paths.profiles/'iterm2-utils.json').exists())
        self.assertIsNone(result.receipt.selection.resume_key)

    def test_plan_and_dryrun_do_not_create_state(self):
        from iterm2_utils.planner import plan
        before = self.snapshot()
        plan(self.context,self.selection('status','shell'))
        lifecycle.install(self.context,self.selection('status','shell'),self.runner,dry_run=True)
        self.assertEqual(self.snapshot(),before)

    def test_update_without_receipt_has_no_implicit_selection(self):
        before = self.snapshot()
        result = lifecycle.update(self.context,self.runner)
        self.assertFalse(result.receipt.selection.features)
        self.assertEqual(self.snapshot(),before)
        self.assertTrue(any(f.code=='ownership_unavailable' for f in result.findings))

    def test_user_modified_mcp_is_not_removed(self):
        self.assertSuccess(self.install('mcp'))
        path = self.profile.agent_dir/'mcp.json'
        document = json.loads(path.read_bytes())
        document['mcpServers']['iterm2-observe']['command'] = 'user'
        path.write_text(json.dumps(document))
        before = path.read_bytes()
        result = lifecycle.uninstall(self.context,frozenset({'mcp'}),self.runner)
        self.assertEqual(path.read_bytes(),before)
        self.assertTrue(any(f.code=='uninstall_changed' for f in result.findings))

    def test_repeat_update_partial_full_uninstall_preserves_foreign_neighbours(self):
        path = self.profile.agent_dir/'config.yml'
        path.write_text('model: keep\n')
        features = ('clipboard','shortcuts','shell','status','notifications','restore','mcp')
        first = self.install(*features,shortcuts=('resume',),resume_key='F8')
        self.assertSuccess(first)
        profile = self.context.paths.profiles/'iterm2-utils.json'
        mtime = profile.stat().st_mtime_ns
        self.assertSuccess(self.install(*features,shortcuts=('resume',),resume_key='F8'))
        self.assertSuccess(lifecycle.update(self.context,self.runner))
        self.assertEqual(profile.stat().st_mtime_ns,mtime)
        self.assertSuccess(lifecycle.uninstall(self.context,frozenset({'clipboard','shell','status'}),self.runner))
        result = lifecycle.uninstall(self.context,frozenset(features),self.runner)
        self.assertSuccess(result)
        self.assertIn('model: keep',path.read_text())
        self.assertFalse(profile.exists())
        self.assertFalse(result.receipt.resources)

    def test_foreign_native_setting_changes_survive_uninstall(self):
        self.assertSuccess(self.install('status'))
        path = self.profile.agent_dir/'config.yml'
        path.write_text('terminal: {programStatus: false}\nforeign: keep\n')
        before = path.read_bytes()
        result = lifecycle.uninstall(self.context,frozenset({'status'}),self.runner)
        self.assertTrue(any(f.state=='conflict' for f in result.findings))
        self.assertEqual(path.read_bytes(),before)
        self.assertIn('status',result.receipt.selection.features)

    def test_user_modified_profile_and_shell_are_preserved(self):
        self.assertSuccess(self.install('clipboard','shell'))
        profile = self.context.paths.profiles/'iterm2-utils.json'
        document = json.loads(profile.read_bytes())
        document['Profiles'][0]['UserSetting'] = 'mine'
        profile.write_text(json.dumps(document))
        shell = self.context.paths.zshrc
        shell.write_text(shell.read_text().replace('source ','# custom\n  source '))
        before = (profile.read_bytes(),shell.read_bytes())
        result = lifecycle.uninstall(self.context,frozenset({'clipboard','shell'}),self.runner)
        self.assertEqual((profile.read_bytes(),shell.read_bytes()),before)
        self.assertTrue(any(f.code=='uninstall_changed' for f in result.findings))

    def test_failure_rolls_back_only_current_checkpoint(self):
        from iterm2_utils.config import omp
        with patch.object(omp,'set_address',side_effect=OSError('PRIVATE_ERROR')):
            result = self.install('shell','status')
        self.assertEqual(result.receipt.selection.features,{'shell'})
        self.assertNotIn('PRIVATE_ERROR',repr(result))
        self.assertFalse((self.profile.agent_dir/'config.yml').exists())

    def test_independent_install_preserves_notification_policy_and_resume_key(self):
        self.assertSuccess(self.install('notifications',notify_errors=True))
        self.assertSuccess(self.install('shortcuts',shortcuts=('resume',),resume_key='F8'))
        result = self.install('shell')
        self.assertSuccess(result)
        self.assertTrue(result.receipt.selection.notify_errors)
        self.assertEqual(result.receipt.selection.resume_key,'F8')

    def test_unavailable_existing_feature_does_not_block_independent_update(self):
        self.assertSuccess(self.install('shell','mcp'))
        self.context.executables.pop('python3')
        result = lifecycle.update(self.context,self.runner)
        self.assertIn('shell',[f.feature for f in result.findings if f.code=='feature_checkpoint'])
        self.assertEqual(result.receipt.selection.features,{'shell','mcp'})

    def test_partial_uninstall_keeps_checkpoint_when_profile_recomposition_fails(self):
        initial = self.install('clipboard','shortcuts',shortcuts=('resume',),resume_key='F8')
        self.assertSuccess(initial)
        before = self.snapshot()
        self.context.profiles.clear()
        result = lifecycle.uninstall(self.context,frozenset({'clipboard'}),self.runner)
        self.assertTrue(any(f.code=='missing_parent' for f in result.findings))
        self.assertEqual(result.receipt,initial.receipt)
        self.assertEqual(self.snapshot(),before)

    def test_referenced_dedicated_profile_is_retained_without_closing_sessions(self):
        from iterm2_utils.features.profiles import GUID
        self.assertSuccess(self.install('clipboard'))
        path = self.context.paths.profiles/'iterm2-utils.json'
        before = path.read_bytes()
        self.runner.inventory['sessions'] = [{'id':'session','profile_guid':GUID,
            'bar':{'Show Status Bar':False,'Status Bar Layout':{'components':[]}},
            'references':[],'provenance':False}]
        result = lifecycle.uninstall(self.context,frozenset({'clipboard'}),self.runner)
        self.assertEqual(path.read_bytes(),before)
        self.assertIn('clipboard',result.receipt.selection.features)
        self.assertTrue(any(f.state=='conflict' for f in result.findings))
        self.assertFalse(any('write_' in str(call[0]) or 'close' in str(call[0]) for call in self.runner.calls))

    def test_incremental_shortcut_install_preserves_recorded_resume_key(self):
        from iterm2_utils.config import omp
        self.assertSuccess(self.install('shortcuts',shortcuts=('resume',),resume_key='F8'))
        result = self.install('shortcuts',shortcuts=('alt-enter',))
        self.assertSuccess(result)
        self.assertEqual(result.receipt.selection.shortcuts,{'resume','alt-enter'})
        self.assertEqual(result.receipt.selection.resume_key,'F8')
        self.assertEqual(omp.read_binding(self.profile,'app.session.resume',self.runner),
                         {'exists':True,'value':'F8'})
        self.assertIn('ctrl+j',omp.read_binding(self.profile,'tui.input.newLine',self.runner)['value'])

    def test_conflicting_uninstall_persists_exact_policy_ui_and_retry_clears_only_removed_debt(self):
        from iterm2_utils.config import omp
        settings=self.profile.agent_dir/'config.yml'
        bindings=self.profile.agent_dir/'keybindings.yml'
        settings.write_text('completion: {notify: off}\nerror: {notify: off}\nforeign: keep\n')
        bindings.write_text('app.session.resume: F7\napp.history.search: Ctrl+R\n')
        initial=self.install('shortcuts','notifications','status',shortcuts=('resume',),
                             resume_key='F8',notify_errors=True)
        self.assertSuccess(initial)
        pending=list(initial.receipt.pending_ui)
        omp.set_binding(self.profile,'app.session.resume',{'exists':True,'value':'F10'},self.runner,
                        expected={'exists':True,'value':'F8'})
        omp.set_setting(self.profile,'error.notify',{'exists':True,'value':'off'},self.runner,
                        expected={'exists':True,'value':'on'})
        result=lifecycle.uninstall(self.context,frozenset({'shortcuts','notifications'}),self.runner)
        stored=state.load(self.context.paths.data/'receipt.json')
        self.assertEqual(stored,result.receipt)
        self.assertEqual(stored.selection.features,{'shortcuts','notifications','status'})
        self.assertEqual((stored.selection.resume_key,stored.selection.notify_errors),('F8',True))
        self.assertCountEqual(stored.pending_ui,pending)
        self.assertEqual(omp.read_binding(self.profile,'app.session.resume',self.runner)['value'],'F10')
        omp.set_binding(self.profile,'app.session.resume',{'exists':True,'value':'F8'},self.runner,
                        expected={'exists':True,'value':'F10'})
        self.assertSuccess(lifecycle.uninstall(self.context,frozenset({'shortcuts'}),self.runner))
        stored=state.load(self.context.paths.data/'receipt.json')
        self.assertEqual(stored.selection.features,{'notifications','status'})
        self.assertIsNone(stored.selection.resume_key)
        self.assertTrue(stored.selection.notify_errors)
        self.assertCountEqual(stored.pending_ui,[step for step in pending if step.feature!='shortcuts'])
        self.assertEqual(omp.read_binding(self.profile,'app.session.resume',self.runner)['value'],'F7')
        omp.set_setting(self.profile,'error.notify',{'exists':True,'value':'on'},self.runner,
                        expected={'exists':True,'value':'off'})
        self.assertSuccess(lifecycle.uninstall(self.context,frozenset({'notifications'}),self.runner))
        stored=state.load(self.context.paths.data/'receipt.json')
        self.assertEqual(stored.selection.features,{'status'})
        self.assertFalse(stored.selection.notify_errors)
        self.assertCountEqual(stored.pending_ui,[step for step in pending if step.feature=='status'])
        self.assertEqual(omp.read_setting(self.profile,'error.notify',self.runner)['value'],'off')
        self.assertIn('foreign: keep',settings.read_text())
        self.assertIn('app.history.search: Ctrl+R',bindings.read_text())

    def test_native_planning_uses_supplied_runner_without_global_bun_or_writes(self):
        import subprocess
        class Parser:
            def run(inner,argv,**kwargs):
                request=json.loads(kwargs['stdin'])
                root=json.loads(request['raw'] or '{}')
                node=root
                exists=True
                for part in request['pointer']:
                    if not isinstance(node,dict) or part not in node:
                        exists=False;node=None;break
                    node=node[part]
                if request['op']=='read':
                    result={'value':{'exists':exists,'value':node}}
                else:
                    target=root
                    for part in request['pointer'][:-1]:target=target.setdefault(part,{})
                    target[request['pointer'][-1]]=request['next']['value']
                    result={'raw':json.dumps(root)}
                return subprocess.CompletedProcess(argv,0,json.dumps(result),'')
        parser=Parser()
        before=self.snapshot()
        with patch.object(Runner,'run',side_effect=AssertionError('escaped supplied adapter')):
            result=lifecycle.install(self.context,self.selection('status','notifications','shortcuts',
                shortcuts=('resume',),resume_key='F8',notify_errors=True),parser,dry_run=True)
        self.assertSuccess(result)
        self.assertEqual(result.receipt.selection.features,{'status','notifications','shortcuts'})
        self.assertEqual({step.code for step in result.receipt.pending_ui},
                         {'native_status','native_notifications','native_keyboard'})
        self.assertEqual(self.snapshot(),before)


from tests.test_migration import MigrationFixture


class MigrationLifecycleTests(MigrationFixture):
    def test_unresolved_writer_does_not_block_independent_checkpoint(self):
        from iterm2_utils import migration
        from iterm2_utils.models import ChangeSet, FileEdit, Finding, Plan
        path = self.home/'legacy.json'; path.write_text('{"ours":2,"foreign":7}')
        resource = self.json_resource(path)
        self.save(self.historical([resource]))
        migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        target = self.home/'clipboard-state'
        chosen = Selection(frozenset({'status','clipboard'}), frozenset(), 'Default', self.profile)
        def planned(context, selection, *, runner=None):
            return Plan(selection, ChangeSet([FileEdit(target, None, b'clipboard', 0o600, 'clipboard')], [],
                [Finding('clipboard','omp','prepared','ready','Prepared independent clipboard fixture.')]), 'fixture')
        with patch.object(lifecycle, 'validate', return_value=[]), patch.object(lifecycle, 'plan', side_effect=planned):
            outcome = lifecycle.install(self.context, chosen, self.runner)
        self.assertEqual(target.read_bytes(), b'clipboard')
        self.assertEqual(outcome.receipt.selection.features, {'clipboard'})
        self.assertEqual(outcome.receipt.legacy_cleanup[0]['resources'], [resource])
        self.assertEqual(json.loads(path.read_bytes()), {'ours':2,'foreign':7})
        self.assertTrue(any(f.code == 'legacy_writer_conflict' for f in outcome.findings))

    def test_ordinary_uninstall_preserves_deferred_cleanup_and_original_inverse(self):
        from iterm2_utils.models import Receipt
        legacy = self.historical([self.json_resource(self.home/'legacy.json')])
        from iterm2_utils import legacy_state
        receipt = Receipt('2', Selection(frozenset(), frozenset(), 'Default', self.profile),
                          [], [], [legacy_state.encode(legacy)])
        self.save(receipt)
        result = lifecycle.uninstall(self.context, frozenset({'status'}), self.runner)
        self.assertEqual(result.receipt.legacy_cleanup, receipt.legacy_cleanup)
