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
                def identity_probe(zsh, runner_arg, env, cwd, name):
                    self.assertEqual((cwd,name),(request.cwd,'work'))
                    return omp,[],'',{'HOME':str(root)},selected
                with patch('iterm2_utils.launch_checks.platform.system',return_value='Darwin'),patch('iterm2_utils.launch_checks._iterm',return_value=(root,[])),patch('iterm2_utils.launch_checks.Terminal',return_value=terminal),patch('iterm2_utils.launch_checks.shutil.which',return_value='/bin/zsh'),patch('iterm2_utils.launch_checks._shell_identity',side_effect=identity_probe):
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

    def test_expansion_bearing_wrapper_arguments_are_rejected_without_execution(self):
        for value in ('~/.omp/custom.yml','/tmp/*.yml','/tmp/file?.yml','/tmp/[ab].yml','/tmp/a{b,c}.yml'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                wrapper_arguments('command omp --config '+value+' "$@"')

    def test_quoted_expansion_characters_remain_literal_wrapper_values(self):
        self.assertEqual(wrapper_arguments('command omp --config "~/.omp/custom*.yml" --model \'literal?[ab]{x}\' "$@"'),
                         ['--config','~/.omp/custom*.yml','--model','literal?[ab]{x}'])

    def test_bun_evidence_is_tied_to_exact_selected_script(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); script = root/'cli.js'; script.write_text('#!/usr/bin/env bun\n// @bun\n')
            bun = root/'bun'; bun.write_text('binary'); bun.chmod(0o700)
            script.chmod(0o700)
            prefixes = executable_prefixes(script,{'PATH':str(root)})
            self.assertIn((str(bun), str(script)), prefixes)
            self.assertNotIn(('bun',), prefixes)

    def test_executable_alias_preserves_selected_and_physical_prefixes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            physical = root/'physical'; physical.mkdir()
            alias = root/'alias'; alias.symlink_to(physical, target_is_directory=True)
            binary = physical/'omp'; binary.write_bytes(b'\xcf\xfa\xed\xfe'+b'\x00'*300)
            binary.chmod(0o700)
            self.assertEqual(executable_prefixes(alias/'omp', {}),
                             ((str(alias/'omp'),), (str(binary),)))

    def test_modes_and_exact_resume_header_are_validated(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); profile=OmpProfile(None, root/'agent')
            req=LaunchRequest('', 'Shell', root, None, 'shell')
            validate_request(req)
            with self.assertRaises(ValueError): validate_request(replace(req,omp_profile=profile))
            with self.assertRaises(ValueError): validate_request(replace(req,mode='new'))
            for mode in ('invalid', 'handoff', 'resume'):
                with self.assertRaises(ValueError): validate_request(replace(req, mode=mode))
            from iterm2_utils.omp_sessions import resolve_resume
            history=root/'history.jsonl'; history.write_text(json.dumps(dict(type='session',id='exact-id',cwd=tmp))+'\n')
            target=resolve_resume(history,'exact-id',profile)
            validate_request(replace(req,mode='resume',omp_profile=profile,resume=target))
            history.write_text(json.dumps(dict(type='session',id='substituted',cwd=tmp))+'\n')
            with self.assertRaises(ValueError): validate_request(replace(req,mode='resume',omp_profile=profile,resume=target))

    def test_shell_mode_does_not_probe_omp(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); req=LaunchRequest('W','Shell',root,None,'shell')
            from types import SimpleNamespace
            terminal=SimpleNamespace(select_window=lambda *a:'W', profile=lambda *a:dict(name='Shell',guid='G',command=''), profiles=lambda:[dict(name='Shell',guid='G')])
            runner=SimpleNamespace(run=lambda *a,**kw: self.fail('shell must not run omp or login shell probes'))
            with patch('iterm2_utils.launch_checks.platform.system',return_value='Darwin'), patch('iterm2_utils.launch_checks._iterm',return_value=(root,[])), patch('iterm2_utils.launch_checks.Terminal',return_value=terminal), patch('iterm2_utils.launch_checks.shutil.which',return_value='/bin/zsh'):
                inspection, findings=inspect_launch(SimpleNamespace(),req,runner)
            self.assertEqual(findings,[]); self.assertIsNone(inspection.identity)

    def test_native_macho_header_is_not_decoded_as_text(self):
        with TemporaryDirectory() as tmp:
            binary=Path(tmp).resolve()/'omp';binary.write_bytes(b'\xcf\xfa\xed\xfe'+b'\x00'*300);binary.chmod(0o700)
            self.assertEqual(executable_prefixes(binary,{}),((str(binary),),))
            binary.write_bytes(b'#!/bin/sh\n')
            with self.assertRaises(ValueError):executable_prefixes(binary,{})

    def test_wrapper_accepts_only_zero_to_two_literal_no_daemon_flags(self):
        for count in range(3):
            body='command omp '+'--no-daemon '*count+'--model provider/model "$@"'
            self.assertEqual(wrapper_arguments(body),['--no-daemon']*count+['--model','provider/model'])
        for flags in ('--no-daemon '*3,'--no-daemon=true','--no-daemon $VALUE'):
            with self.subTest(flags=flags),self.assertRaises(ValueError):
                wrapper_arguments('command omp '+flags+' "$@"')

    def test_login_shell_selects_bun_and_capability_environment_not_cli_path(self):
        from types import SimpleNamespace
        from iterm2_utils.commands import Runner
        for cli_bun in (False,True):
            with self.subTest(cli_bun=cli_bun),TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();selected_bin=root/'login-bin';selected_bin.mkdir()
                caller_bin=root/'cli-bin';caller_bin.mkdir()
                omp=selected_bin/'omp';omp.write_text('#!/usr/bin/env bun\n');omp.chmod(0o700)
                bun=selected_bin/'bun'
                bun.write_text('#!/bin/sh\n[ "$KEEP_ENDPOINT" = fixture-endpoint ] || exit 1\n'
                               'case "$2" in --help) echo "--cwd --profile --config --resume";; --version) exit 1;; *) exit 1;; esac\n')
                bun.chmod(0o700)
                if cli_bun:
                    wrong=caller_bin/'bun';wrong.write_text('#!/bin/sh\nexit 88\n');wrong.chmod(0o700)
                (root/'.zshenv').write_text('unsetopt GLOBAL_RCS\n')
                (root/'.zshrc').write_text('export PATH='+str(selected_bin)+':/usr/bin:/bin\n'
                    'export KEEP_ENDPOINT=fixture-endpoint\n'
                    'omp() { command omp --no-daemon --no-daemon --model provider/model "$@"; }\n')
                env=dict(HOME=str(root),ZDOTDIR=str(root),PATH=str(caller_bin)+':/usr/bin:/bin',
                         PI_CONFIG_DIR='.omp',PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
                request=LaunchRequest('W','Omp',root,OmpProfile('work',root/'.omp/profiles/work/agent'),'new')
                terminal=SimpleNamespace(select_window=lambda *a:'W',profiles=lambda:[dict(name='Omp',guid='G')],
                    profile=lambda *a:dict(name='Omp',guid='G',command=''))
                with patch.dict(os.environ,env,clear=True),patch('iterm2_utils.launch_checks.platform.system',return_value='Darwin'), \
                        patch('iterm2_utils.launch_checks._iterm',return_value=(root,{})), \
                        patch('iterm2_utils.launch_checks.Terminal',return_value=terminal):
                    inspection,findings=inspect_launch(SimpleNamespace(home=root),request,Runner())
                self.assertEqual(findings,[])
                self.assertEqual(inspection.identity.arguments,('--no-daemon','--no-daemon','--model','provider/model'))
                self.assertIn((str(bun),str(omp)),inspection.identity.prefixes)
                self.assertNotIn((str(caller_bin/'bun'),str(omp)),inspection.identity.prefixes)
                self.assertEqual(inspection.identity.version,'')
                from iterm2_utils.launch import build_command
                command=build_command(request,inspection,[str(omp),'--help'])
                import shlex
                result=subprocess.run(shlex.split(command),env=env,cwd=root,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                (root/'.zshrc').write_text('export PATH='+str(caller_bin)+':'+str(selected_bin)+':/usr/bin:/bin\n'
                    'export KEEP_ENDPOINT=fixture-endpoint\n'
                    'omp() { command omp --no-daemon --no-daemon --model provider/model "$@"; }\n')
                wrong=caller_bin/'bun';wrong.write_text('#!/bin/sh\nexit 88\n');wrong.chmod(0o700)
                result=subprocess.run(shlex.split(command),env=env,cwd=root,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,1,'interpreter drift must refuse before executing the alternate Bun')

    def test_preflight_keeps_parent_and_sole_selection_basis(self):
        from types import SimpleNamespace
        for env,basis in (({'ITERM_SESSION_ID':'w0t0p0:PARENT'},('parent','PARENT')),({},('sole',''))):
            with self.subTest(basis=basis),TemporaryDirectory() as tmp:
                root=Path(tmp)
                request=LaunchRequest('','Shell',root,None,'shell')
                terminal=SimpleNamespace(select_window=lambda *a:'W',profiles=lambda:[dict(name='Shell',guid='G')],
                    profile=lambda *a:dict(name='Shell',guid='G',command=''))
                with patch.dict(os.environ,env,clear=True),patch('iterm2_utils.launch_checks.platform.system',return_value='Darwin'), \
                        patch('iterm2_utils.launch_checks._iterm',return_value=(root,{})), \
                        patch('iterm2_utils.launch_checks.shutil.which',return_value='/bin/zsh'), \
                        patch('iterm2_utils.launch_checks.Terminal',return_value=terminal):
                    inspection,findings=inspect_launch(SimpleNamespace(),request,SimpleNamespace())
                self.assertEqual(findings,[])
                self.assertEqual(inspection.window_basis,basis)

    def test_new_window_does_not_select_existing_target(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            artifact=__import__('iterm2_utils.launch',fromlist=['prepare_handoff']).prepare_handoff(root,'task')
            self.addCleanup(__import__('shutil').rmtree,artifact.path.parent)
            for mode in ('shell','handoff'):
                request=LaunchRequest('','Shell',root,None if mode=='shell' else OmpProfile('work',root/'agent'),
                                      mode,handoff=artifact.path if mode=='handoff' else None,new_window=True)
                for windows in ([],['old','other']):
                    terminal=SimpleNamespace(select_window=lambda *a:self.fail('must not select an existing window'),
                        windows=lambda:windows,profiles=lambda:[dict(name='Shell',guid='G')],
                        profile=lambda *a:dict(name='Shell',guid='G',command=''))
                    identity=(root/'omp',[],'',{},request.omp_profile)
                    runner=SimpleNamespace(run=lambda *a,**kw:SimpleNamespace(returncode=0,stdout='--cwd --profile --config'))
                    with self.subTest(mode=mode,windows=windows),patch.dict(os.environ,{'ITERM_SESSION_ID':'old:PARENT'}), \
                            patch('iterm2_utils.launch_checks.platform.system',return_value='Darwin'), \
                            patch('iterm2_utils.launch_checks._iterm',return_value=(root,[])), \
                            patch('iterm2_utils.launch_checks.shutil.which',return_value='/bin/zsh'), \
                            patch('iterm2_utils.launch_checks.Terminal',return_value=terminal), \
                            patch('iterm2_utils.launch_checks._shell_identity',return_value=identity), \
                            patch('iterm2_utils.launch_checks.executable_prefixes',return_value=((str(root/'omp'),),)):
                        inspection,findings=inspect_launch(SimpleNamespace(),request,runner)
                    self.assertEqual(findings,[])
                    self.assertEqual((inspection.window_id,inspection.window_basis),('',('new','')))
            request=LaunchRequest('','Shell',root,None,'shell',new_window=True)
            for changes in (dict(window_id='W'),dict(mode='new'),dict(mode='resume'),
                            dict(new_window=1),dict(new_window='true'),dict(new_window=None)):
                with self.subTest(changes=changes),self.assertRaises(ValueError):
                    validate_request(replace(request,**changes))
            with patch('iterm2_utils.launch.read_handoff',side_effect=AssertionError('validation must precede handoff')):
                with self.assertRaises(ValueError):
                    validate_request(replace(request,mode='handoff',window_id='W',handoff=root/'missing'))
