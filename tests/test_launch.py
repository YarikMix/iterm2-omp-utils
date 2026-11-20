"""Safety regressions with native selection and SDK boundaries isolated."""
import json
import os
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from dataclasses import replace
from unittest.mock import patch
from iterm2_utils import launch as m
from iterm2_utils.launch_checks import LaunchRequest, LaunchInspection, LaunchIdentity
from iterm2_utils.launch_api import LaunchCreation
from iterm2_utils.models import OmpProfile
from iterm2_utils.omp_sessions import SessionBinding, binding_record, resolve_resume
from iterm2_utils.terminal import Terminal


class LaunchTests(unittest.TestCase):
    def fixture(self, root, mode='new'):
        profile=OmpProfile('work',root/'agent')
        request=LaunchRequest('W','Omp',root,profile,mode)
        identity=LaunchIdentity(root/'omp',(),((str(root/'omp'),),(str(root/'bun'),str(root/'omp'))),'future')
        inspection=LaunchInspection(root/'it2',Path('/bin/zsh'),'G','W',identity)
        binding=SessionBinding('S','T','W',root/'new.jsonl','fresh',root,profile,123,'birth','generation')
        binding.session_file.write_text(json.dumps(dict(type='session',id='fresh',cwd=str(root)))+'\n')
        state=dict(argv=None,creates=0,now=0.,command_bad=False,job='bun',creation=None,bindings=[binding])
        class Transport:
            deadline=None
            def __init__(self,*args):pass
            def bindings(self):return state['bindings']
            def process_start(self,pid):return 'birth'
            def observe(self,sid):return binding_record(binding)
            def panes(self):return [dict(terminal_id='S',tab_id='T',window_id='W')]
            def profile(self,name):return dict(name='Omp',guid='G')
            def variable(self,sid,name):
                return {'session.profileName':'Omp','session.jobName':state['job'],'session.commandLine':('malformed "' if state['command_bad'] else shlex.join(state['argv']))}[name]
        async def create(w,p,g,command,**kwargs):
            nonlocal binding
            state['creates']+=1
            argv=shlex.split(command)
            login=shlex.split(argv[2].split(' && exec ',1)[1])
            inner=shlex.split(login[2].split('; exec ',1)[1]); state['argv']=inner[3:]
            if '--resume' not in state['argv']:
                settings={}
                layers=[request.omp_profile.agent_dir/'config.yml',request.cwd/'.omp/config.yml']
                layers.extend(Path(state['argv'][index+1]) for index,value in enumerate(state['argv']) if value=='--config')
                state['selection_layers']=[]
                for path in layers:
                    if path.exists():
                        settings.update(json.loads(path.read_text()))
                        state['selection_layers'].append(path)
                auto_resume=settings.get('autoResume',True)
                state['selected_session_id']='old' if auto_resume else 'fresh'
                binding=replace(binding,session_id='old' if auto_resume else 'fresh')
                state['bindings']=[binding]
                binding.session_file.write_text(json.dumps(dict(type='session',id=binding.session_id,cwd=str(root)))+'\n')
            return state['creation'] or LaunchCreation('created_unverified','W','T','S',state['now']+30,())
        return request,inspection,binding,state,Transport,create

    def test_wrong_window_profile_duplicate_session_and_extra_argv_fail_proof(self):
        for fault in ('window','profile','split','extra'):
            with self.subTest(fault=fault),TemporaryDirectory() as tmp:
                root=Path(tmp);request,inspection,binding,state,transport,create=self.fixture(root)
                if fault=='window':
                    transport.panes=lambda self:[dict(terminal_id='S',tab_id='T',window_id='other')]
                elif fault=='profile':
                    transport.profile=lambda self,name:dict(name='Omp',guid='wrong')
                elif fault=='split':
                    transport.panes=lambda self:[dict(terminal_id='S',tab_id='T',window_id='W'),dict(terminal_id='extra',tab_id='T',window_id='W')]
                else:
                    original=create
                    async def create(w,p,g,c,**kwargs):
                        result=await original(w,p,g,c)
                        state['argv']+=['--continue']
                        return result
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual((code,out['status']),(3,'created_unverified'))
                self.assertEqual(state['creates'],1)

    def test_paths_and_prompt_remain_single_literal_arguments(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);request,inspection,_,_,_,_=self.fixture(root)
            cwd=root/'space \" quote $(touch NEVER)'
            handoff=m.Handoff(root/"handoff ' quote.md",'nonce',root/'ack.json',cwd)
            request=replace(request,mode='handoff',cwd=cwd,handoff=handoff.path)
            overlay=root/'overlay \" file.json'
            argv=m.build_argv(request,inspection,overlay,handoff)
            self.assertEqual(argv[:7],[str(root/'omp'),'--profile','work','--cwd',str(cwd),'--config',str(overlay)])
            self.assertEqual(argv[7],'--')
            outer=shlex.split(m.build_command(request,inspection,argv))
            login=shlex.split(outer[2].split(' && exec ',1)[1])
            executed=shlex.split(login[2].split('; exec ',1)[1])
            self.assertEqual(executed[3:],argv)
            self.assertFalse((root/'NEVER').exists())

    def run_launch(self,root,request,inspection,state,transport,create):
        paths=SimpleNamespace(data=root/'data')
        with patch.object(m,'inspect_launch',return_value=(inspection,[])),patch.object(m,'Terminal',transport),patch.object(m,'create_tab',create),patch.object(m.time,'monotonic',side_effect=lambda:state['now']),patch.object(m.time,'sleep',side_effect=lambda n:state.update(now=state['now']+n)):
            return m.launch(request,paths,SimpleNamespace())

    def test_new_handoff_overrides_auto_resume_without_persisting(self):
        for mode in ('new','handoff'):
            with self.subTest(mode=mode),TemporaryDirectory() as tmp:
                root=Path(tmp); request,inspection,binding,state,transport,create=self.fixture(root)
                global_config=request.omp_profile.agent_dir/'config.yml'
                project_config=request.cwd/'.omp/config.yml'
                default_config=root/'.omp/agent/config.yml'
                base_overlay=root/'preserved-config.json'
                for path in (global_config,project_config,default_config,base_overlay):
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_text(json.dumps(dict(autoResume=path!=default_config,model='unchanged')))
                persisted=(global_config,project_config,default_config,base_overlay)
                before=[p.read_bytes() for p in persisted]
                inspection=replace(inspection,identity=replace(inspection.identity,arguments=('--config',str(base_overlay))))
                if mode=='handoff':
                    artifact=m.prepare_handoff(root,'Task to read'); request=replace(request,mode='handoff',handoff=artifact.path)
                    plain=create
                    async def create(w,p,g,c,**kwargs):
                        result=await plain(w,p,g,c)
                        artifact.ack_path.write_text(json.dumps(dict(request_id=artifact.request_id,thread_id=state['selected_session_id'],cwd=str(artifact.cwd),accepted_task='Read task',first_step='Inspect materials')))
                        artifact.ack_path.chmod(0o600)
                        return result
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual((code,out['status']),(0,'launched'),out)
                argv=state['argv']; configs=[argv[i+1] for i,value in enumerate(argv) if value=='--config']
                self.assertEqual(configs[0],str(base_overlay));self.assertEqual(len(configs),2)
                self.assertEqual(state['selection_layers'],[global_config,project_config,base_overlay,Path(configs[-1])])
                actual=state['bindings'][0]
                self.assertEqual(actual.session_id,'fresh')
                self.assertEqual(state['selected_session_id'],actual.session_id)
                self.assertEqual(json.loads(actual.session_file.read_text())['id'],actual.session_id)
                self.assertEqual(out['identity'],'verified')
                self.assertEqual([p.read_bytes() for p in persisted],before)
                self.assertNotIn('--session-dir',argv)
                if mode=='handoff':
                    self.assertEqual(out['ack'],'received')
                    ack=json.loads(artifact.ack_path.read_text())
                    self.assertEqual(ack['thread_id'],actual.session_id)

    def test_timeout_after_creation_does_not_create_second_tab(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);request,inspection,binding,state,transport,create=self.fixture(root)
            state['creation']=LaunchCreation('unknown','W','T',None,30,())
            code,out=self.run_launch(root,request,inspection,state,transport,create)
            self.assertEqual((code,out['status'],out['tab_id']),(3,'created_unverified','T'))
            self.assertEqual(state['creates'],1)

    def test_wrong_process_complete_argv_and_extra_options_are_unverified(self):
        for change in (dict(command_bad=True),dict(job='zsh')):
            with self.subTest(change=change),TemporaryDirectory() as tmp:
                root=Path(tmp);request,inspection,binding,state,transport,create=self.fixture(root);state.update(change)
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual((code,out['status']),(3,'created_unverified'));self.assertEqual(state['creates'],1)

    def test_moved_tab_and_incomplete_live_candidate_never_auto_duplicate(self):
        for observation in ('moved','missing'):
            with self.subTest(observation=observation),TemporaryDirectory() as tmp:
                root=Path(tmp);request,inspection,binding,state,transport,create=self.fixture(root)
                target=resolve_resume(binding.session_file,binding.session_id,binding.profile)
                request=replace(request,mode='resume',resume=target)
                transport.observe=lambda self,sid: ({**binding_record(binding),'tab_id':'moved','window_id':'other'} if observation=='moved' else None)
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual(state['creates'],0)
                self.assertEqual(out['status'],'already_open' if observation=='moved' else 'blocked')

    def test_live_matching_id_without_session_file_never_creates_duplicate(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);request,inspection,binding,state,transport,create=self.fixture(root)
            target=resolve_resume(binding.session_file,binding.session_id,binding.profile)
            request=replace(request,mode='resume',resume=target)
            incomplete=replace(binding,session_file=None)
            state['bindings']=[incomplete]
            transport.observe=lambda self,sid:binding_record(incomplete)
            code,out=self.run_launch(root,request,inspection,state,transport,create)
            self.assertEqual(state['creates'],0)
            self.assertEqual((code,out['status']),(2,'blocked'))

    def test_target_startup_profile_inputs_are_rechecked_before_exec(self):
        import subprocess
        from iterm2_utils.commands import Runner
        from iterm2_utils.launch_checks import _shell_identity
        for changed in ('HOME','PI_CONFIG_DIR','PI_CODING_AGENT_DIR'):
            with self.subTest(changed=changed),TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();target=root/'target';target.mkdir()
                caller=root/'caller';caller.mkdir()
                binary=root/'bin';binary.mkdir();omp=binary/'omp'
                marker=root/'executed'
                omp.write_text('#!/bin/sh\nprintf launched > '+shlex.quote(str(marker))+'\n')
                omp.chmod(0o700)
                (root/'.zshenv').write_text('unsetopt GLOBAL_RCS\n')
                startup=('export PATH='+shlex.quote(str(binary))+':/usr/bin:/bin\n'+
                         'if [[ $PWD == '+shlex.quote(str(target))+' ]]; then export PI_CONFIG_DIR=target-config; else export PI_CONFIG_DIR=caller-config; fi\n')
                name=None if changed=='PI_CODING_AGENT_DIR' else 'work'
                if name is None:startup+='export PI_CODING_AGENT_DIR=relative-agent\n'
                (root/'.zshrc').write_text(startup)
                env={'HOME':str(root),'ZDOTDIR':str(root),'PATH':'/usr/bin:/bin'}
                executable,args,wrapper,effective,selected=_shell_identity(Path('/bin/zsh'),Runner(),env,target,name or 'default')
                self.assertEqual(effective['PI_CONFIG_DIR'],'target-config')
                # The caller directory would resolve another named-profile storage root.
                _,_,_,caller_env,_=_shell_identity(Path('/bin/zsh'),Runner(),env,caller,name or 'default')
                self.assertEqual(caller_env['PI_CONFIG_DIR'],'caller-config')
                expected=target/'relative-agent' if name is None else root/'target-config/profiles/work/agent'
                self.assertEqual(selected,OmpProfile(name,expected))
                request=LaunchRequest('W','Omp',target,selected,'new')
                identity=LaunchIdentity(executable,tuple(args),((str(executable),),),'',wrapper)
                inspection=LaunchInspection(root/'it2',Path('/bin/zsh'),'G','W',identity)
                command=m.build_command(request,inspection,[str(omp)])
                result=subprocess.run(shlex.split(command),env=env,cwd=caller,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertTrue(marker.exists())
                marker.unlink()
                (root/'.zshrc').write_text(startup+'export '+changed+'='+shlex.quote(str(root/'drift'))+'\n')
                result=subprocess.run(shlex.split(command),env=env,cwd=caller,capture_output=True,timeout=10)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(marker.exists(),'profile-directory drift must stop before exec')

    def test_exact_resume_command_no_prompt_restore_or_fallback(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); request,inspection,binding,state,transport,create=self.fixture(root)
            request=replace(request,mode='resume',resume=resolve_resume(binding.session_file,'fresh',binding.profile))
            argv=m.build_argv(request,inspection,None)
            self.assertEqual(argv,[str(root/'omp'),'--profile','work','--cwd',str(root),'--resume',str(binding.session_file)])

    def test_ack_wrong_nonce_identity_stale_or_symlink_is_not_receipt(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); artifact=m.prepare_handoff(root,'task')
            for changes in (dict(request_id='wrong'),dict(thread_id='wrong'),dict(cwd='/wrong')):
                ack=dict(request_id=artifact.request_id,thread_id='actual',cwd=tmp,accepted_task='task',first_step='read');ack.update(changes)
                artifact.ack_path.write_text(json.dumps(ack));artifact.ack_path.chmod(0o600)
                self.assertFalse(m.valid_ack(artifact,'actual',0))
            artifact.ack_path.write_text(json.dumps(dict(request_id=artifact.request_id,thread_id='actual',cwd=str(artifact.cwd),accepted_task='task',first_step='read')))
            artifact.ack_path.chmod(0o600)
            os.utime(artifact.ack_path,ns=(1,1))
            self.assertFalse(m.valid_ack(artifact,'actual',2))
            artifact.ack_path.unlink(); artifact.ack_path.symlink_to(artifact.path)
            self.assertFalse(m.valid_ack(artifact,'actual',0))

    def test_resume_without_registry_requires_independent_dialog_evidence_or_opt_in(self):
        for situation in ('missing','unavailable','unrelated','instrumented-other','opt-in','stale'):
            with self.subTest(situation=situation),TemporaryDirectory() as tmp:
                root=Path(tmp);request,inspection,binding,state,transport,create=self.fixture(root)
                request=replace(request,mode='resume',resume=resolve_resume(binding.session_file,'fresh',binding.profile),
                                allow_duplicate=situation=='opt-in')
                state['bindings']=[] if situation!='unrelated' else [replace(binding,session_id='other')]
                if situation=='unavailable':
                    transport.bindings=lambda self: (_ for _ in ()).throw(OSError('private registry unavailable'))
                if situation=='stale':
                    state['bindings']=[binding]
                    transport.process_start=lambda self,pid:'reused-pid'
                if situation=='instrumented-other':
                    other=root/'other.jsonl'
                    other.write_text(json.dumps(dict(type='session',id='other',cwd=str(root)))+'\n')
                    current=replace(binding,session_id='other',session_file=other)
                    state['bindings']=[current]
                    transport.observe=lambda self,sid:binding_record(current)
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                allowed=situation in {'instrumented-other','opt-in'}
                self.assertEqual(state['creates'],int(allowed))
                self.assertEqual((code,out['status']),(0,'launched') if allowed else (2,'blocked'))

    def test_resume_command_proof_never_implies_foreign_fresh_fork_or_missing_history(self):
        for actual in ('foreign','fresh','fork','missing'):
            with self.subTest(actual=actual),TemporaryDirectory() as tmp:
                root=Path(tmp);request,inspection,binding,state,transport,create=self.fixture(root)
                saved=root/'requested.jsonl'
                saved.write_text(json.dumps(dict(type='session',id='requested',cwd=str(root)))+'\n')
                request=replace(request,mode='resume',resume=resolve_resume(saved,'requested',binding.profile),
                                allow_duplicate=True)
                if actual=='fork':
                    binding.session_file.write_text(json.dumps(dict(type='session',id='fresh',cwd=str(root),
                                                                   parentSession='requested'))+'\n')
                elif actual=='foreign':
                    foreign=root/'foreign';foreign.mkdir()
                    state['bindings']=[replace(binding,profile=OmpProfile(None,foreign))]
                elif actual=='missing':state['bindings']=[]
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual((code,out['status'],out['command'],out['history']),
                                 (0,'launched','verified','unverified'))
                self.assertEqual((out['window_id'],out['tab_id'],out['session_id']),('W','T','S'))
                self.assertEqual(state['creates'],1)
                if actual=='missing':self.assertEqual(out['identity'],'unverified')

    def test_handoff_ack_has_separate_120_seconds_and_never_recreates(self):
        for ack in ('late','missing','invalid'):
            with self.subTest(ack=ack),TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();request,inspection,binding,state,transport,create=self.fixture(root)
                artifact=m.prepare_handoff(root,'private task')
                self.addCleanup(__import__('shutil').rmtree,artifact.path.parent)
                request=replace(request,mode='handoff',handoff=artifact.path)
                observe=transport.observe
                def observed(self,sid):
                    if state['now']>=45 and ack!='missing' and not artifact.ack_path.exists():
                        artifact.ack_path.write_text(json.dumps(dict(request_id=artifact.request_id,
                            thread_id='fresh' if ack=='late' else 'wrong',cwd=str(root),
                            accepted_task='read',first_step='inspect')))
                        artifact.ack_path.chmod(0o600)
                    return observe(self,sid)
                transport.observe=observed
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual((code,out['command'],out['ack']),
                                 (0,'verified','received' if ack=='late' else 'unconfirmed'))
                self.assertGreaterEqual(state['now'],45 if ack=='late' else 120)
                self.assertLess(state['now'],46 if ack=='late' else 121)
                self.assertEqual((out['window_id'],out['tab_id'],out['session_id']),('W','T','S'))
                self.assertEqual(state['creates'],1)

    def test_complete_command_observation_accepts_literal_and_quoted_exact_forms(self):
        for form in ('literal','quoted','interpreter-literal','interpreter-quoted','extra','wrong-cwd','wrong-id','wrong-handoff','malformed'):
            with self.subTest(form=form),TemporaryDirectory(prefix="space ' quote ") as tmp:
                root=Path(tmp).resolve();request,inspection,binding,state,transport,create=self.fixture(root)
                target=resolve_resume(binding.session_file,'fresh',binding.profile)
                request=replace(request,mode='resume',resume=target,allow_duplicate=True)
                original=transport.variable
                def variable(self,sid,name):
                    if name!='session.commandLine':return original(self,sid,name)
                    argv=list(state['argv'])
                    if form.startswith('interpreter'):argv=[str(root/'bun'),*argv]
                    if form=='extra':argv+=['--continue']
                    if form=='wrong-cwd':argv[argv.index('--cwd')+1]='/wrong'
                    if form=='wrong-id':argv[-1]=str(root/'other.jsonl')
                    if form=='wrong-handoff':argv+=['--','Read another task']
                    line=' '.join(argv) if form.endswith('literal') else shlex.join(argv)
                    return line+" '" if form=='malformed' else line
                transport.variable=variable
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual(out['command'],'verified' if form in {
                    'literal','quoted','interpreter-literal','interpreter-quoted'} else 'unverified')
                self.assertEqual(state['creates'],1)

    def abbreviated_fixture(self, root, mode, prefix=()):
        request,inspection,binding,state,transport,create=self.fixture(root)
        request=replace(request,mode=mode,omp_profile=None if mode=='shell' else request.omp_profile)
        state.update(job='zsh' if mode=='shell' else Path(prefix[0]).name if prefix else 'omp',
                     pid=123,tty='/dev/ttys007',image=Path('/bin/zsh') if mode=='shell' else Path(prefix[0]) if prefix else root/'omp',
                     kernel_calls=0)
        original=transport.variable
        def variable(self,sid,name):
            if name=='tty':return state['tty']
            if name=='session.profileName':return 'Omp'
            if name=='session.jobName':return state['job']
            if name!='session.commandLine':return original(self,sid,name)
            argv=[str(inspection.zsh),'-il'] if mode=='shell' else [*prefix,*state['argv']]
            argv[0]=Path(argv[0]).name
            argv+=state.get('extra',[])
            if state.get('wrong_script'):argv[1]=str(root/'other-omp')
            if state.get('wrong_cwd'):argv[argv.index('--cwd')+1]='/wrong'
            line=' '.join(argv) if state.get('literal') else shlex.join(argv)
            return line+" '" if state.get('malformed') else line
        transport.variable=variable
        def job_pid(self,sid):
            runner=SimpleNamespace(run=lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(state['pid'])))
            return Terminal(Path('/it2'),runner).job_pid(sid)
        # Exercise the real numeric transport decoder beneath the launch consumer.
        transport.job_pid=job_pid
        def foreground(self,pid,birth,tty):
            state['kernel_calls']+=1
            return state.get('foreground',True) and (pid,birth,tty)==(123,'birth','/dev/ttys007')
        transport.foreground_process=foreground
        transport.process_image=lambda self,pid:str(state['image']) if state['image'] else None
        async def created(*args,**kwargs):
            if mode=='shell':
                state['creates']+=1
                return LaunchCreation('created_unverified','W','T','S',30,())
            return await create(*args,**kwargs)
        return request,inspection,state,transport,created

    def test_basename_shell_native_and_interpreter_require_kernel_job_proof(self):
        for mode,prefix,literal in (('shell',(),False),('new',(),False),('new',('bun',),False),('new',('bun',),True)):
            with self.subTest(mode=mode,prefix=prefix,literal=literal),TemporaryDirectory(prefix="space ' quote ") as tmp:
                root=Path(tmp)
                prefix=(str(root/'bun'),) if prefix else ()
                request,inspection,state,transport,create=self.abbreviated_fixture(root,mode,prefix)
                state['literal']=literal
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual((code,out['status'],out['command']),(0,'launched','verified'))
                self.assertEqual(state['creates'],1)
                self.assertGreaterEqual(state['kernel_calls'],2)

    def test_basename_wrong_tail_never_uses_kernel_evidence(self):
        for fault in ('extra','script','cwd','malformed'):
            with self.subTest(fault=fault),TemporaryDirectory() as tmp:
                root=Path(tmp)
                request,inspection,state,transport,create=self.abbreviated_fixture(root,'new',(str(root/'bun'),))
                state.update(extra=['--continue'] if fault=='extra' else [],wrong_script=fault=='script')
                state.update(wrong_cwd=fault=='cwd',malformed=fault=='malformed')
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual((code,out['command']),(3,'unverified'))
                self.assertEqual(state['kernel_calls'],0)

    def test_basename_rejects_wrong_missing_or_changing_job_evidence(self):
        for fault in ('image','missing-image','foreground','birth','dead','pid','tty','command','changed-image',
                      'changed-foreground','changed-birth','lost-liveness','changed-pid','changed-tty','changed-command','deadline'):
            with self.subTest(fault=fault),TemporaryDirectory() as tmp:
                root=Path(tmp)
                request,inspection,state,transport,create=self.abbreviated_fixture(root,'new')
                if fault=='image':state['image']=root/'foreign'
                if fault=='missing-image':state['image']=None
                if fault=='foreground':state['foreground']=False
                if fault in {'birth','dead'}:transport.process_start=lambda self,pid:None
                if fault=='pid':state['pid']=True
                if fault=='tty':state['tty']=''
                if fault=='command':state['extra']=['--continue']
                if fault.startswith('changed-') or fault in {'lost-liveness','deadline'}:
                    original=transport.process_image
                    def image(self,pid):
                        result=original(self,pid)
                        # Every attempt becomes contradictory, never just the first poll.
                        if fault=='changed-image':state['image']=root/'foreign'
                        if fault=='changed-foreground':state['foreground']=False
                        if fault=='changed-birth':transport.process_start=lambda self,pid:'reused'
                        if fault=='lost-liveness':transport.process_start=lambda self,pid:None
                        if fault=='changed-pid':state['pid']=124
                        if fault=='changed-tty':state['tty']='/dev/ttys008'
                        if fault=='changed-command':state['extra']=['--continue']
                        if fault=='deadline':state['now']=31
                        return result
                    transport.process_image=image
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual((code,out['status'],out['command']),(3,'created_unverified','unverified'))
                self.assertEqual((out['window_id'],out['tab_id'],out['session_id']),('W','T','S'))
                self.assertEqual(state['creates'],1)

    def test_full_path_command_keeps_existing_proof_without_kernel_calls(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);request,inspection,_,state,transport,create=self.fixture(root)
            def forbidden(*args):raise AssertionError('Full argv must not need kernel image proof')
            transport.job_pid=transport.foreground_process=transport.process_image=forbidden
            code,out=self.run_launch(root,request,inspection,state,transport,create)
            self.assertEqual((code,out['command']),(0,'verified'))

    def test_handoff_producer_bounds_complete_utf8_representation_without_truncation(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            for task in ('x'*65536,'界'*22000,'x'*65450):
                with self.subTest(length=len(task)),patch.object(m.tempfile,'tempdir',str(root)):
                    with self.assertRaises(ValueError):m.prepare_handoff(root,task)
                    self.assertEqual(list(root.iterdir()),[])
            task="Unicode 界 and quotes ' \""*500
            artifact=m.prepare_handoff(root,task)
            self.addCleanup(__import__('shutil').rmtree,artifact.path.parent)
            self.assertEqual(m.read_handoff(artifact.path,root),artifact)
            self.assertIn(task,artifact.path.read_text())
            self.assertLessEqual(artifact.path.stat().st_size,65536)

    def test_window_selection_provenance_reaches_sdk_create_without_retargeting(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);request,inspection,binding,state,transport,create=self.fixture(root)
            inspection=replace(inspection,window_basis=('parent','PARENT'))
            async def capture(*args,**kwargs):
                self.assertEqual(kwargs,{'window_basis':('parent','PARENT')})
                return await create(*args,**kwargs)
            code,out=self.run_launch(root,request,inspection,state,transport,capture)
            self.assertEqual((code,state['creates']),(0,1))

    def test_handoff_literal_and_quoted_complete_bun_argv_preserve_exact_prompt_path(self):
        for form in ('literal','quoted','wrong-handoff'):
            with self.subTest(form=form),TemporaryDirectory(prefix="space ' \" quote ") as tmp:
                root=Path(tmp).resolve();request,inspection,binding,state,transport,create=self.fixture(root)
                with patch.object(m.tempfile,'tempdir',str(root)):
                    artifact=m.prepare_handoff(root,'task')
                request=replace(request,mode='handoff',handoff=artifact.path)
                original=transport.variable
                def variable(self,sid,name):
                    if name!='session.commandLine':return original(self,sid,name)
                    argv=[str(root/'bun'),*state['argv']]
                    if form=='wrong-handoff':argv[-1]=argv[-1].replace(str(artifact.path),str(root/'other.md'))
                    return ' '.join(argv) if form=='literal' else shlex.join(argv)
                transport.variable=variable
                code,out=self.run_launch(root,request,inspection,state,transport,create)
                self.assertEqual((code,out['command']),(3,'unverified') if form=='wrong-handoff' else (0,'verified'))
                self.assertEqual(out['ack'],'unconfirmed')
                self.assertEqual(state['creates'],1)
