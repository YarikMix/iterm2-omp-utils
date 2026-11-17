import os
import plistlib
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.support import Fixture
from iterm2_utils.discovery import discover, resolve_paths


class DiscoveryTests(unittest.TestCase):
    def binary(self, fixture, name):
        path = fixture.bin/name
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o755)
        return path

    def test_ordinary_shell_does_not_probe_agents_or_optional_dependencies(self):
        with Fixture() as f:
            self.binary(f,'omp')
            before = f.snapshot()
            context = discover(resolve_paths(),f.runner,features=frozenset({'shell'}))
            self.assertIn('iterm2',context.executables)
            self.assertFalse({'omp','bun','uvx','terminal-notifier','fzf'} & context.executables.keys())
            self.assertFalse(any(Path(call[0][0]).name in {'omp','codex','claude','bun','uvx','cc-status'} for call in f.runner.calls))
            self.assertEqual(f.snapshot(),before)

    def test_native_capability_probes_do_not_run_it2_help_or_invent_receiver_support(self):
        with Fixture() as f:
            self.binary(f,'omp'); self.binary(f,'bun')
            f.runner.responses['omp'] = 'omp 99.0.0 --resume --cwd --config'
            context = discover(resolve_paths(),f.runner,features=frozenset({'status','notifications','restore'}))
            self.assertIn('omp:resume',context.capabilities)
            self.assertFalse({'iterm2:osc7501','iterm2:osc9'} & context.capabilities)
            calls = [call[0][1:] for call in f.runner.calls if Path(call[0][0]).name=='omp']
            self.assertEqual(calls,[['--version'],['--help']])
            self.assertFalse(any(Path(call[0][0]).name in {'it2','codex','claude','terminal-notifier','fzf','cc-status'} for call in f.runner.calls))
            self.assertTrue(all(call[1]<=10 for call in f.runner.calls))

    def test_unknown_receiver_is_not_inferred_from_version_or_old_hooks(self):
        with Fixture() as f:
            f.runner.responses['it2'] = 'set-status session-status'
            info = f.app/'Contents/Info.plist'
            data = plistlib.loads(info.read_bytes())
            data['CFBundleShortVersionString'] = '99.0.0'
            info.write_bytes(plistlib.dumps(data))
            context = discover(resolve_paths(),f.runner,features=frozenset({'status'}))
            self.assertNotIn('iterm2:osc7501',context.capabilities)
            self.assertEqual(context.installed,{})

    def test_paths_use_current_contract_and_ignore_relative_overrides(self):
        with Fixture() as f:
            with patch.dict(os.environ,{'XDG_CONFIG_HOME':'relative','ZDOTDIR':str(f.home/'shell')}):
                paths = resolve_paths()
                self.assertEqual(paths.config,f.home/'.config/iterm2-utils')
                self.assertEqual(paths.zshrc,f.home/'shell/.zshrc')
                self.assertFalse(hasattr(paths,'codex_home'))
                self.assertFalse(hasattr(paths,'claude_settings'))

    def test_invalid_app_and_failed_probes_are_private(self):
        with Fixture() as f:
            (f.app/'Contents/Info.plist').write_bytes(b'invalid')
            def fail(*args,**kwargs):
                raise subprocess.TimeoutExpired('fixture',5,output='PRIVATE')
            f.runner.run = fail
            context = discover(resolve_paths(),f.runner)
            self.assertNotIn('iterm2',context.executables)
            self.assertNotIn('PRIVATE',repr(context))

    def test_preferences_snapshot_retains_only_selected_public_addresses(self):
        with Fixture() as f:
            f.runner.responses['defaults'] = plistlib.dumps({'CopySelection':True,'PRIVATE':'secret',
                'New Bookmarks':[{'Name':'Default','Guid':'parent'}]}).decode()
            context = discover(resolve_paths(),f.runner,features=frozenset({'clipboard'}))
            self.assertEqual(context.preferences,{'com.googlecode.iterm2':{'CopySelection':True}})
            self.assertEqual(context.profiles['Default']['Guid'],'parent')
            self.assertNotIn('PRIVATE',repr(context))

    def test_terminal_address_rejects_ambiguous_inherited_sources(self):
        from runtime.terminal_identity import terminal_from_environment
        terminal = '12345678-1234-4234-8234-123456789ABC'
        self.assertEqual(terminal_from_environment({'TERM_SESSION_ID':'w0t0p0:'+terminal}),terminal)
        for environment in ({}, {'TERM_SESSION_ID':''},
                {'TERM_SESSION_ID':terminal,'ITERM_SESSION_ID':'87654321-1234-4234-8234-123456789ABC'},
                {'TERM_SESSION_ID':terminal,'ITERM_SESSION_ID':''}):
            self.assertIsNone(terminal_from_environment(environment))

    def test_fresh_profile_contexts_retire_only_unreferenced_dedicated_profiles(self):
        from iterm2_utils import lifecycle
        from iterm2_utils.features.profiles import GUID, NAME
        from iterm2_utils.models import Selection
        from tests.test_lifecycle import NativeRunner
        for feature in ('clipboard','shortcuts'):
            for referenced in (False,True):
                with self.subTest(feature=feature,referenced=referenced), Fixture() as f:
                    runner = NativeRunner()
                    runner.responses['defaults'] = plistlib.dumps({
                        'New Bookmarks':[{'Name':'Default','Guid':'parent','Keyboard Map':{}}]}).decode()
                    original_run = runner.run
                    def run(argv, **kwargs):
                        result = original_run(argv,**kwargs)
                        if argv[1:]==['-c','import iterm2; print("iterm2-sdk-ready")']:
                            return subprocess.CompletedProcess(argv,0,'iterm2-sdk-ready\n','')
                        return result
                    runner.run = run
                    preferences = {}
                    def read(runner,domain,key):
                        return {'exists':key in preferences,'value':preferences.get(key)}
                    def write(runner,domain,key,value):
                        if value['exists']:
                            preferences[key] = value['value']
                        else:
                            preferences.pop(key,None)
                    features = frozenset({feature})
                    paths = resolve_paths()
                    with patch('iterm2_utils.engine.preferences.read',side_effect=read), \
                            patch('iterm2_utils.engine.preferences.write',side_effect=write):
                        initial_context = discover(paths,runner,features=features)
                        selection = Selection(features,frozenset({'ctrl-q'}) if feature=='shortcuts' else frozenset(),
                                              'Default',initial_context.omp_profile)
                        installed = lifecycle.install(initial_context,selection,runner)
                        self.assertFalse([f for f in installed.findings if f.state in {
                            'conflict','unavailable','missing_dependency'}])
                        target = paths.profiles/'iterm2-utils.json'
                        before = target.read_bytes()
                        if referenced:
                            bar = {'Show Status Bar':False,'Status Bar Layout':{'components':[]}}
                            runner.inventory['profiles'].append({'guid':GUID,'name':NAME,'bar':bar,
                                'working_directory':None,'references':[]})
                            runner.inventory['sessions'].append({'id':'live','profile_guid':GUID,
                                'bar':bar,'references':[],'provenance':True})
                        fresh_context = discover(paths,runner,features=features)
                        self.assertIn('python3',fresh_context.executables)
                        self.assertIn('python:iterm2',fresh_context.capabilities)
                        result = lifecycle.uninstall(fresh_context,features,runner)
                        if referenced:
                            self.assertEqual(target.read_bytes(),before)
                            self.assertEqual(result.receipt.selection.features,features)
                            self.assertTrue(any(f.state=='conflict' for f in result.findings))
                        else:
                            self.assertFalse([f for f in result.findings if f.state in {
                                'conflict','unavailable','missing_dependency'}])
                            self.assertFalse(target.exists())
                            self.assertFalse(result.receipt.selection.features)

    def test_diagnostic_version_failures_do_not_erase_available_resume_capability(self):
        for failure in ('error','empty','stderr','timeout'):
            with self.subTest(failure=failure),Fixture() as f:
                omp=self.binary(f,'omp')
                original=f.runner.run
                def run(argv,**kwargs):
                    if argv==[str(omp),'--version']:
                        if failure=='timeout':raise subprocess.TimeoutExpired(argv,5)
                        return subprocess.CompletedProcess(argv,1 if failure=='error' else 0,'',
                            'omp 999.1.2' if failure=='stderr' else '')
                    if argv==[str(omp),'--help']:
                        return subprocess.CompletedProcess(argv,0,'--resume --cwd --profile','')
                    return original(argv,**kwargs)
                f.runner.run=run
                context=discover(resolve_paths(),f.runner,features=frozenset({'restore'}))
                self.assertEqual(context.executables['omp'],omp)
                self.assertIn('omp:resume',context.capabilities)
                self.assertNotIn('omp',context.versions)

    def test_required_help_capability_failure_still_blocks_restore_alone(self):
        from iterm2_utils.models import Selection
        from iterm2_utils.planner import validate
        with Fixture() as f:
            omp=self.binary(f,'omp');self.binary(f,'python3')
            original=f.runner.run
            def run(argv,**kwargs):
                if argv==[str(omp),'--help']:return subprocess.CompletedProcess(argv,1,'','private')
                if argv[1:]==['-c','import iterm2; print("iterm2-sdk-ready")']:
                    return subprocess.CompletedProcess(argv,0,'iterm2-sdk-ready','')
                return original(argv,**kwargs)
            f.runner.run=run
            context=discover(resolve_paths(),f.runner,features=frozenset({'restore','shell'}))
            selection=Selection(frozenset({'restore','shell'}),frozenset(),'Default',context.omp_profile)
            findings=validate(selection,context)
            self.assertTrue(any(item.feature=='restore' and item.code=='native_capability' for item in findings))
            self.assertFalse(any(item.feature=='shell' and item.state=='unavailable' for item in findings))
