"""Offline launch boundary assertions; execution reserved for Task 10."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from dataclasses import replace
from unittest.mock import patch
from iterm2_utils.launch_checks import LaunchRequest, validate_request, wrapper_arguments, executable_prefixes, inspect_launch
from iterm2_utils.models import OmpProfile


class LaunchChecksTests(unittest.TestCase):
    def test_newer_or_missing_version_is_not_a_launch_gate(self):
        from types import SimpleNamespace
        for version in ('omp/999.123.4', None):
            with self.subTest(version=version),TemporaryDirectory() as tmp:
                root=Path(tmp); omp=root/'omp';omp.write_bytes(b'\\x7fELF');omp.chmod(0o700)
                selected=OmpProfile('work',root/'.omp/profiles/work/agent')
                request=LaunchRequest('W','Omp',root,selected,'new')
                terminal=SimpleNamespace(select_window=lambda *a:'W',profile=lambda *a:dict(name='Omp',guid='G',command=''),profiles=lambda:[dict(name='Omp',guid='G')])
                calls=[]
                def run(argv,**kwargs):
                    calls.append((argv,kwargs))
                    self.assertLessEqual(kwargs['timeout'],10)
                    self.assertNotIn('ITERM_SESSION_ID',kwargs.get('env',{}))
                    self.assertNotIn('TERM_SESSION_ID',kwargs.get('env',{}))
                    if argv[-1]=='--version':
                        if version is None:raise subprocess.TimeoutExpired(argv,10)
                        return SimpleNamespace(returncode=0,stdout=version)
                    self.assertEqual(argv,[str(omp),'--help'])
                    return SimpleNamespace(returncode=0,stdout='--cwd --profile --config --resume')
                runner=SimpleNamespace(run=run)
                with patch('iterm2_utils.launch_checks.platform.system',return_value='Darwin'),patch('iterm2_utils.launch_checks._iterm',return_value=(root,[])),patch('iterm2_utils.launch_checks.Terminal',return_value=terminal),patch('iterm2_utils.launch_checks.shutil.which',return_value='/bin/zsh'),patch('iterm2_utils.launch_checks._shell_identity',return_value=(omp,[],'',{'HOME':str(root)})):
                    inspection,findings=inspect_launch(SimpleNamespace(home=root),request,runner)
                self.assertEqual(findings,[])
                self.assertIsNotNone(inspection)
    def test_transparent_wrapper_preserves_profile_model_endpoint_and_config(self):
        self.assertEqual(wrapper_arguments('command omp --profile work --model "provider/model x" --provider endpoint --config /tmp/base "$@"'),
                         ['--profile', 'work', '--model', 'provider/model x', '--provider', 'endpoint', '--config', '/tmp/base'])
        self.assertEqual(wrapper_arguments(''), [])

    def test_injected_resume_goal_approval_and_unknown_args_are_rejected(self):
        for flag in ('--continue', '--resume /tmp/history', '--goal task', '--auto-approve', '--unknown', '--session-dir /tmp/private', '--mode rpc'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                wrapper_arguments('command omp '+flag+' "$@"')
        for body in ('echo secret; command omp "$@"', 'omp "$@"', 'command omp "$@" extra', 'command omp $(evil) "$@"'):
            with self.subTest(body=body), self.assertRaises(ValueError): wrapper_arguments(body)

    def test_bun_evidence_is_tied_to_exact_selected_script(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); script = root/'cli.js'; script.write_text('#!/usr/bin/env bun\n// @bun\n')
            bun = root/'bun'; bun.write_text('binary'); bun.chmod(0o700)
            script.chmod(0o700)
            with patch('iterm2_utils.launch_checks.shutil.which', return_value=str(bun)):
                prefixes = executable_prefixes(script)
            self.assertIn((str(bun), str(script)), prefixes)
            self.assertNotIn(('bun',), prefixes)

    def test_modes_and_exact_resume_header_are_validated(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); profile=OmpProfile(None, root/'agent')
            req=LaunchRequest('', 'Shell', root, profile, 'shell')
            validate_request(req)
            for mode in ('invalid', 'handoff', 'resume'):
                with self.assertRaises(ValueError): validate_request(replace(req, mode=mode))
            from iterm2_utils.omp_sessions import resolve_resume
            history=root/'history.jsonl'; history.write_text(json.dumps(dict(type='session',id='exact-id',cwd=tmp))+'\n')
            target=resolve_resume(history,'exact-id',profile)
            validate_request(replace(req,mode='resume',resume=target))
            history.write_text(json.dumps(dict(type='session',id='substituted',cwd=tmp))+'\n')
            with self.assertRaises(ValueError): validate_request(replace(req,mode='resume',resume=target))

    def test_shell_mode_does_not_probe_omp(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); req=LaunchRequest('W','Shell',root,OmpProfile(None,root/'agent'),'shell')
            from types import SimpleNamespace
            terminal=SimpleNamespace(select_window=lambda *a:'W', profile=lambda *a:dict(name='Shell',guid='G',command=''), profiles=lambda:[dict(name='Shell',guid='G')])
            runner=SimpleNamespace(run=lambda *a,**kw: self.fail('shell must not run omp or login shell probes'))
            with patch('iterm2_utils.launch_checks.platform.system',return_value='Darwin'), patch('iterm2_utils.launch_checks._iterm',return_value=(root,[])), patch('iterm2_utils.launch_checks.Terminal',return_value=terminal), patch('iterm2_utils.launch_checks.shutil.which',return_value='/bin/zsh'):
                inspection, findings=inspect_launch(SimpleNamespace(),req,runner)
            self.assertEqual(findings,[]); self.assertIsNone(inspection.identity)
