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

    def test_native_capability_probes_do_not_read_effective_config_or_start_agent(self):
        with Fixture() as f:
            self.binary(f,'omp'); self.binary(f,'bun')
            f.runner.responses['omp'] = 'omp 99.0.0 --resume --cwd --config'
            f.runner.responses['it2'] = 'OSC 7501 OSC 9 set-status get-status'
            context = discover(resolve_paths(),f.runner,features=frozenset({'status','notifications','restore'}))
            self.assertTrue({'omp:resume','iterm2:osc7501','iterm2:osc9'} <= context.capabilities)
            calls = [call[0][1:] for call in f.runner.calls if Path(call[0][0]).name=='omp']
            self.assertEqual(calls,[['--version'],['--help']])
            self.assertFalse(any(Path(call[0][0]).name in {'codex','claude','terminal-notifier','fzf','cc-status'} for call in f.runner.calls))
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
