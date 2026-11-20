"""Public parser and real orchestration against temporary storage/native adapters."""
import contextlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch
from tests.test_migration import MigrationFixture
from iterm2_utils import cli, launch
from iterm2_utils.launch_checks import LaunchIdentity, LaunchInspection
from iterm2_utils.launch_api import LaunchCreation


class CliTests(MigrationFixture):
    def invoke(self, argv, *, environment=None):
        out, err = io.StringIO(), io.StringIO()
        environment = {'HOME':str(self.home), 'OMP_PROFILE':'default', 'PI_CONFIG_DIR':'.omp',
                       **(environment or {})}
        environment = {key:value for key,value in environment.items() if value is not None}
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(cli, 'resolve_paths', return_value=self.context.paths), \
             patch.object(cli, 'Runner', return_value=self.runner), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_invalid_and_removed_inputs_never_discover_or_create(self):
        common = ['launch-omp','--profile','Shell','--cwd',str(self.home)]
        cases = [common, common+['--mode','new','--handoff','/unused'],
                 common+['--mode','shell','--resume-id','x'],
                 common+['--mode','resume','--resume-file','/unused'],
                 common+['--mode','handoff'], common+['--mode','new','--allow-duplicate'],
                 ['launch-codex'], ['plan','--agent','codex','--features','shell'],
                 ['bootstrap-skill','--agent','claude'],
                 ['migrate-omp','--apply','--dry-run'],
                 ['plan','--features','shell','--appearance-config','/unused'],
                 ['plan','--features','bogus']]
        before = self.snapshot()
        with patch.object(cli,'discover',side_effect=AssertionError('discovery')), \
             patch.object(launch,'create_tab',side_effect=AssertionError('creation')):
            for args in cases:
                with self.subTest(args=args):
                    code, out, err = self.invoke(args)
                    self.assertEqual(code,2,out+err)
                    self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.runner.calls,[])

    def test_bootstrap_never_discovers_and_resolves_named_profile(self):
        with patch.object(cli,'discover',side_effect=AssertionError('discovery')):
            before = self.snapshot()
            code,out,err = self.invoke(['bootstrap-skill','--skill','iterm2-launch',
                                      '--omp-profile','work','--dry-run','--json'])
            self.assertEqual(code,0,out+err)
            self.assertEqual(self.snapshot(),before)
            code,out,err = self.invoke(['bootstrap-skill','--skill','iterm2-launch',
                                      '--omp-profile','work','--json'])
            self.assertEqual(code,0,out+err)
        destination = self.home/'.omp/profiles/work/agent/skills/iterm2-launch'
        self.assertTrue((destination/'references/resume.md').is_file())
        self.assertFalse((destination.parent/'iterm2-setup').exists())
        self.assertFalse((self.home/'.omp/profiles/work/agent/config.yml').exists())
        self.assertEqual(self.runner.calls,[])

    def test_legacy_install_update_stop_before_discovery_and_redact_snapshots(self):
        path = self.home/'legacy.json'
        self.save(self.historical([self.json_resource(path, before='PRIVATE_SNAPSHOT')]))
        before = self.snapshot()
        with patch.object(cli,'discover',side_effect=AssertionError('discovery')):
            for args in (['install','--features','status'], ['update'], ['doctor']):
                code,out,err = self.invoke([*args,'--json'])
                self.assertEqual(code,2,out+err)
                self.assertIn('migration_required',out)
                self.assertNotIn('PRIVATE_SNAPSHOT',out+err)
                self.assertNotIn('resources',json.loads(out))
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.runner.calls,[])

    def test_migration_defaults_preview_then_cleans_without_agent_discovery(self):
        path = self.home/'legacy.json'; path.write_text('{"ours":1,"private":"PRIVATE_SETTINGS"}')
        self.save(self.historical([self.json_resource(path, before='PRIVATE_SNAPSHOT')]))
        before = self.snapshot()
        with patch.object(cli,'discover',side_effect=AssertionError('discovery')):
            for extra in ([],['--dry-run']):
                code,out,err = self.invoke(['migrate-omp',*extra,'--json'])
                self.assertEqual(code,0,out+err)
                self.assertEqual(self.snapshot(),before)
                self.assertFalse(json.loads(out)['restore_external'])
                self.assertNotIn('PRIVATE_',out+err)
            code,out,err = self.invoke(['migrate-omp','--apply','--json'])
        self.assertEqual(code,0,out+err)
        self.assertEqual(json.loads(path.read_text()),{'ours':'PRIVATE_SNAPSHOT','private':'PRIVATE_SETTINGS'})
        self.assertNotIn('PRIVATE_',out+err)
        self.assertEqual(self.runner.calls,[])

    def test_migration_preview_reports_retirement_without_agent_discovery(self):
        import base64
        import sys
        from types import SimpleNamespace
        from iterm2_utils import legacy_state
        from iterm2_utils.models import Receipt, Selection
        path = self.context.paths.data/'releases/old/helper.py'; path.parent.mkdir(parents=True)
        path.write_bytes(b'old')
        current = self.context.paths.data/'current'; current.symlink_to(path.parent)
        resources = [
            self.resource('file', path, {'mode':0o600}, self.value(exists=False),
                self.value(base64.b64encode(b'old').decode()), ('shared:runtime','status')),
            self.resource('symlink', current, {}, self.value(exists=False),
                self.value(str(path.parent)), ('shared:runtime','status')),
        ]
        self.save(Receipt('2', Selection(frozenset(), frozenset(), 'Default', self.profile),
            [], [], [legacy_state.encode(self.historical(resources))]))
        before = self.snapshot()
        def respond(argv, **kwargs):
            self.assertEqual(argv[0], sys.executable)
            self.assertEqual(json.loads(kwargs['stdin']), {'operation':'sessions_empty'})
            self.assertEqual(kwargs['timeout'], 10)
            return SimpleNamespace(returncode=0, stdout=json.dumps(response))
        with patch.object(cli, 'discover', side_effect=AssertionError('discovery')), \
             patch.object(self.runner, 'run', side_effect=respond):
            for response, expected, exit_code in (
                    ({'status':'ok','value':True}, 'legacy_resource_cleanup', 0),
                    ({'status':'conflict'}, 'legacy_runtime_deferred', 3)):
                code, out, err = self.invoke(['migrate-omp','--dry-run','--json'])
                self.assertEqual(code, exit_code, out+err)
                self.assertIn(expected, out)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(current.readlink(), path.parent)
                self.assertFalse((self.context.paths.data/'transaction.lock').exists())

    def test_invalid_receipt_is_not_treated_as_empty_install(self):
        path = self.context.paths.data/'receipt.json'
        path.parent.mkdir(parents=True); path.write_text('{PRIVATE_INVALID')
        before = self.snapshot()
        with patch.object(cli,'discover',side_effect=AssertionError('discovery')):
            for args in (['install','--features','shell'],['plan','--features','shell'],['doctor']):
                code,out,err = self.invoke([*args,'--json'])
                self.assertEqual(code,2,out+err)
                self.assertIn('ownership_unavailable',out)
                self.assertNotIn('PRIVATE_INVALID',out+err)
        self.assertEqual(self.snapshot(),before)

    def test_launch_modes_reach_real_orchestration_and_exact_native_command(self):
        import shlex
        from iterm2_utils.omp_sessions import SessionBinding, binding_record
        from types import SimpleNamespace
        from iterm2_utils import launch_checks
        executable = self.home/'omp'
        executable.write_text('fixture binary'); executable.chmod(0o700)
        def run(argv,**kwargs):
            self.assertNotEqual(mode,'shell','Shell must not run any agent probe')
            self.assertIn(argv,([str(executable),'--help'],[str(executable),'--version']))
            return SimpleNamespace(returncode=0,stdout='--cwd --profile --config --resume')
        for mode in ('shell','new','handoff','resume'):
            with self.subTest(mode=mode):
                sid = 'abcdefab-1234-4123-8123-abcdefabcdef'
                saved = self.home/'dialog.jsonl'
                saved.write_text(json.dumps(dict(type='session',id=sid,cwd=str(self.home)))+'\n')
                artifact = launch.prepare_handoff(self.home,'PRIVATE_TASK') if mode=='handoff' else None
                if artifact:
                    self.addCleanup(__import__('shutil').rmtree,artifact.path.parent)
                observed = dict(argv=None,creates=0,now=0.)
                profile = self.profile
                binding = SessionBinding('S','T','W',saved,sid,self.home,profile,123,'birth','generation')
                class Terminal:
                    deadline=None
                    def __init__(self,*args):pass
                    def bindings(self):return [binding] if observed['creates'] else []
                    def process_start(self,pid):return 'birth'
                    def observe(self,terminal_id):return binding_record(binding)
                    def select_window(self,window,environment):
                        self_outer.assertEqual(window,'W')
                        return 'W'
                    def profiles(self):
                        return [dict(name='Shell' if mode=='shell' else 'Omp',guid='G')]
                    def panes(self):return [dict(terminal_id='S',tab_id='T',window_id='W')] if observed['creates'] else []
                    def complete_panes(self):return self.panes()
                    def profile(self,name):return dict(name='Shell' if mode=='shell' else 'Omp',guid='G')
                    def variable(self,terminal_id,name):
                        return {'session.profileName':'Shell' if mode=='shell' else 'Omp',
                                'session.jobName':'zsh' if mode=='shell' else 'omp',
                                'session.commandLine':shlex.join(['/bin/zsh','-il'] if mode=='shell' else observed['argv'] or [])}[name]
                async def create(window,profile,guid,command,**kwargs):
                    observed['creates'] += 1
                    self.assertEqual((window,profile,guid),('W','Shell' if mode=='shell' else 'Omp','G'))
                    if mode!='shell':
                        outer=shlex.split(command)
                        login=shlex.split(outer[2].split(' && exec ',1)[1])
                        observed['argv']=shlex.split(login[2].split('; exec ',1)[1])[3:]
                    else:
                        outer=shlex.split(command)
                        self.assertEqual(shlex.split(outer[2].split(' && exec ',1)[1]),['/bin/zsh','-il'])
                    if artifact:
                        artifact.ack_path.write_text(json.dumps(dict(request_id=artifact.request_id,
                            thread_id=sid,cwd=str(self.home),accepted_task='PRIVATE_ACK',first_step='read')))
                        artifact.ack_path.chmod(0o600)
                    return LaunchCreation('created_unverified','W','T','S',30,())
                self_outer = self
                def shell_identity(zsh,runner,environment,cwd,name):
                    self.assertNotEqual(mode,'shell','Shell must not probe omp')
                    self.assertEqual((cwd,name),(self.home,'default'))
                    return executable,[],'',{'HOME':str(self.home)},self.profile
                args=['launch-omp','--mode',mode,'--window','W','--profile',
                      'Shell' if mode=='shell' else 'Omp','--cwd',str(self.home),'--json']
                if artifact:args += ['--handoff',str(artifact.path)]
                if mode=='resume':args += ['--resume-file',str(saved),'--resume-id',sid]
                with patch.object(cli,'discover',side_effect=AssertionError('discovery')), \
                     patch.object(launch_checks.platform,'system',return_value='Darwin'), \
                     patch.object(launch_checks,'_iterm',return_value=(self.home,{})), \
                     patch.object(launch_checks.shutil,'which',return_value='/bin/zsh'), \
                     patch.object(launch_checks,'_shell_identity',side_effect=shell_identity), \
                     patch.object(self.runner,'run',side_effect=run), \
                     patch.object(launch_checks,'Terminal',Terminal), \
                     patch.object(launch,'Terminal',Terminal),patch.object(launch,'create_tab',create), \
                     patch.object(launch.time,'monotonic',side_effect=lambda:observed['now']), \
                     patch.object(launch.time,'sleep',side_effect=lambda n:observed.update(now=observed['now']+n)):
                    code,out,err=self.invoke(args)
                self.assertEqual(code,0,out+err)
                self.assertEqual(observed['creates'],1)
                self.assertEqual(json.loads(out)['status'],'launched')
                self.assertNotIn('PRIVATE_',out+err)
                if mode=='shell':self.assertIsNone(observed['argv'])
                elif mode=='resume':
                    self.assertEqual(observed['argv'],[str(self.home/'omp'),'--profile','default','--cwd',str(self.home),'--resume',str(saved)])
                    self.assertEqual(json.loads(out)['history'],'verified')
                else:
                    argv=observed['argv']
                    self.assertEqual(argv[:5],[str(self.home/'omp'),'--profile','default','--cwd',str(self.home)])
                    self.assertEqual(json.loads(Path(argv[6]).read_text()),{'autoResume':False})
                    self.addCleanup(__import__('shutil').rmtree,Path(argv[6]).parent)
                    if mode=='handoff':self.assertEqual(json.loads(out)['ack'],'received')
                    else:self.assertEqual(len(argv),7)

    def test_historical_journal_without_receipt_requires_explicit_migration(self):
        journal = self.context.paths.data/'journal'; journal.mkdir(parents=True)
        from iterm2_utils import state
        state.save_recovery(journal/'intent.json',self.historical([],('shell',)))
        before = self.snapshot()
        with patch.object(cli,'discover',side_effect=AssertionError('discovery')):
            code,out,err = self.invoke(['install','--features','shell','--json'])
        self.assertEqual(code,2,out+err)
        self.assertIn('migration_required',out)
        self.assertEqual(self.snapshot(),before)

    def test_unknown_creation_keeps_ids_and_redaction_without_retry(self):
        observed = dict(creates=0,now=0.)
        overlay = self.home/'unknown-launch'; overlay.mkdir(mode=0o700)
        class Terminal:
            def __init__(self,*args):pass
            def panes(self):return []
            def profile(self,name):return dict(name='Omp',guid='G')
            def variable(self,sid,name):return ''
        async def create(*args,**kwargs):
            self.assertEqual(kwargs,{'window_basis':('explicit','')})
            observed['creates'] += 1
            return LaunchCreation('unknown','W','T',None,30,())
        identity = LaunchIdentity(self.home/'omp',(),((str(self.home/'omp'),),),'future')
        inspection = LaunchInspection(self.home/'it2',Path('/bin/zsh'),'G','W',identity)
        with patch.object(launch,'inspect_launch',return_value=(inspection,[])), \
             patch.object(launch,'Terminal',Terminal),patch.object(launch,'create_tab',create), \
             patch.object(launch.tempfile,'mkdtemp',return_value=str(overlay)), \
             patch.object(launch.time,'monotonic',side_effect=lambda:observed['now']), \
             patch.object(launch.time,'sleep',side_effect=lambda n:observed.update(now=observed['now']+n)):
            code,out,err=self.invoke(['launch-omp','--mode','new','--window','W',
                '--profile','Omp','--cwd',str(self.home),'--json'])
        self.assertEqual(code,3,out+err)
        output=json.loads(out)
        self.assertEqual((output['status'],output['window_id'],output['tab_id'],output['session_id']),
                         ('created_unverified','W','T',None))
        self.assertEqual(observed['creates'],1)
        self.assertEqual(output['command'],'unverified')
        self.assertNotIn('argv',output)

    def test_missing_resume_file_is_blocked_and_never_falls_back_to_new(self):
        with patch.object(launch,'create_tab',side_effect=AssertionError('creation')):
            code,out,err=self.invoke(['launch-omp','--mode','resume','--profile','Omp',
                '--cwd',str(self.home),'--resume-file',str(self.home/'missing.jsonl'),
                '--resume-id','abcdefab-1234-4123-8123-abcdefabcdef','--json'])
        self.assertEqual(code,2,out+err)
        output=json.loads(out)
        self.assertEqual(output['status'],'blocked')
        self.assertIsNone(output['tab_id'])
        self.assertEqual(self.runner.calls,[])

    def test_plain_launch_output_exposes_each_proof_and_known_ids_without_private_payload(self):
        from types import SimpleNamespace
        for mode in ('resume','handoff'):
            out=io.StringIO()
            output=dict(mode='launch_omp',status='launched',window_id='W',tab_id='T',session_id='S',
                profile='Omp',command='verified',identity='unverified',
                history='unverified' if mode=='resume' else 'not_requested',
                ack='unconfirmed' if mode=='handoff' else 'not_requested',findings=[],
                argv=['PRIVATE_PROMPT'],screen='PRIVATE_SCREEN')
            with contextlib.redirect_stdout(out):
                code=cli._emit(SimpleNamespace(json=False,command='launch-omp'),output)
            self.assertEqual(code,0)
            text=out.getvalue()
            for key in ('window_id','tab_id','session_id','profile','command','identity','history','ack'):
                self.assertIn(key+'='+json.dumps(output[key]),text)
            self.assertNotIn('PRIVATE_',text)

    def test_explicit_external_restore_choice_is_visible_in_migration_preview(self):
        before = self.snapshot()
        code,out,err=self.invoke(['migrate-omp','--restore-external','--json'])
        self.assertEqual(code,0,out+err)
        self.assertTrue(json.loads(out)['restore_external'])
        self.assertEqual(self.snapshot(),before)

    def test_shell_mode_does_not_probe_or_launch_omp(self):
        import shlex
        from iterm2_utils import launch_checks
        sdk = self.home/'fake-sdk'; sdk.mkdir()
        log = sdk/'creates.jsonl'
        (sdk/'iterm2.py').write_text("""
import json, os
from pathlib import Path
from types import SimpleNamespace
async def close(): pass
async def connect(): return SimpleNamespace(websocket=SimpleNamespace(close=close))
async def profiles(connection): return [SimpleNamespace(name='Shell',guid='G',command='')]
class Window:
    window_id = 'W'
    async def async_create_tab(self,profile=None,command=None,select=True):
        with Path(os.environ['FAKE_SDK_LOG']).open('a') as stream:
            stream.write(json.dumps([self.window_id,profile,command,select])+'\\n')
        return SimpleNamespace(tab_id='T',all_sessions=[SimpleNamespace(session_id='S')])
async def async_get_app(connection):
    return SimpleNamespace(get_window_by_id=lambda identifier: Window() if identifier=='W' else None)
Connection = SimpleNamespace(async_create=connect)
Profile = SimpleNamespace(async_get=profiles)
""")
        class Terminal:
            def __init__(self,*args):pass
            def select_window(self,window,environment):return 'W'
            def profiles(self):return [dict(name='Shell',guid='G')]
            def profile(self,name):return dict(name='Shell',guid='G',command='')
            def panes(self):return [dict(terminal_id='S',tab_id='T',window_id='W')]
            def variable(self,sid,name):
                return {'session.profileName':'Shell','session.jobName':'zsh',
                        'session.commandLine':'/bin/zsh -il'}[name]
        before = self.snapshot()
        invalid = {'OMP_PROFILE':'Work','PI_PROFILE':'INVALID!',
                   'PI_CONFIG_DIR':'unused-config','PI_CODING_AGENT_DIR':'unused-agent',
                   'PYTHONPATH':str(sdk)+os.pathsep+str(self.context.paths.repo),
                   'PYTHONDONTWRITEBYTECODE':'1','FAKE_SDK_LOG':str(log)}
        with patch.object(launch_checks.platform,'system',return_value='Darwin'), \
             patch.object(launch_checks,'_iterm',return_value=(self.home,{})), \
             patch.object(launch_checks.shutil,'which',return_value='/bin/zsh'), \
             patch.object(launch_checks,'_shell_identity',side_effect=AssertionError('agent shell/config probe')), \
             patch.object(cli,'resolve_omp_profile',side_effect=AssertionError('agent storage resolution')), \
             patch.object(self.runner,'run',side_effect=AssertionError('agent help/version/config probe')), \
             patch.object(launch,'prepare_handoff',side_effect=AssertionError('handoff')), \
             patch.object(launch,'read_handoff',side_effect=AssertionError('handoff/ack')), \
             patch.object(launch.tempfile,'mkdtemp',side_effect=AssertionError('launch artifact')), \
             patch.object(launch_checks,'Terminal',Terminal),patch.object(launch,'Terminal',Terminal):
            code,out,err=self.invoke(['launch-omp','--mode','shell','--window','W','--profile','Shell',
                                      '--cwd',str(self.home),'--json'],environment=invalid)
        self.assertEqual(code,0,out+err)
        creates = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(len(creates),1)
        self.assertEqual(creates[0][:2],['W','Shell'])
        self.assertTrue(creates[0][3])
        self.assertEqual(shlex.split(creates[0][2]),['/bin/sh','-c',
                         'cd -- '+shlex.quote(str(self.home))+' && exec /bin/zsh -il'])
        output=json.loads(out)
        self.assertEqual((output['status'],output['command'],output['ack']),
                         ('launched','verified','not_requested'))
        after = self.snapshot()
        after.pop(str(log.relative_to(self.home)))
        self.assertEqual(after,before,'Shell must create no handoff, ack or config files')

    def test_real_discovery_honors_explicit_and_recorded_profiles_over_invalid_environment(self):
        from types import SimpleNamespace
        from iterm2_utils import discovery
        invalid_environments = ({'OMP_PROFILE':'Work','PI_PROFILE':'INVALID!'},
                                {'OMP_PROFILE':None,'PI_PROFILE':'INVALID!'})
        for invalid in invalid_environments:
            with self.subTest(environment=invalid):
                def run(argv,**kwargs):
                    self.assertEqual(argv,['/bin/zsh','--version'])
                    return SimpleNamespace(returncode=0,stdout='zsh 99.0.0',stderr='')
                with patch.object(discovery.platform,'system',return_value='Darwin'), \
                     patch.object(discovery,'_iterm',return_value=(self.home,{})), \
                     patch.object(discovery.shutil,'which',return_value='/bin/zsh'), \
                     patch.object(self.runner,'run',side_effect=run):
                    for command in ('plan','install'):
                        code,out,err=self.invoke([command,'--features','shell','--omp-profile','work','--json'],
                                                 environment=invalid)
                        self.assertEqual(code,0,out+err)
                        self.assertEqual(json.loads(out)['selection']['omp_profile'],
                            {'name':'work','agent_dir':str(self.home/'.omp/profiles/work/agent')})
                    for command in ('doctor','update'):
                        code,out,err=self.invoke([command,'--json'],environment=invalid)
                        self.assertEqual(code,0,out+err)
                        self.assertEqual(json.loads(out)['selection']['omp_profile']['name'],'work')
                    code,out,err=self.invoke(['uninstall','--features','shell','--json'],environment=invalid)
                    self.assertEqual(code,0,out+err)
