"""MCP launch boundaries; native operations are fixture-only."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from iterm2_utils.mcp import launch_tools as tools
from iterm2_utils.mcp.binding import McpBinding
from iterm2_utils.models import OmpProfile, Paths
from iterm2_utils.project_edits import Project, ProjectCatalogue
from iterm2_utils.launch_checks import LaunchInspection, LaunchIdentity
from iterm2_utils.launch_api import LaunchCreation
from iterm2_utils import launch as orchestration


class LaunchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root / "cwd ' literal"; self.cwd.mkdir()
        self.profile = OmpProfile('work', self.root/'.omp/profiles/work/agent')
        self.binding = McpBinding(self.profile, Path(__file__).resolve().parents[1], self.root/'data/receipt.json', Path(sys.executable))
        self.paths = Paths(self.root, self.root/'.zshrc', self.root/'config', self.root/'cache', self.root/'data', self.root/'profiles', self.binding.install_root)
        self.catalogue = ProjectCatalogue('ok', (Project('one', 'First', str(self.cwd)),), 'Ordinary')

    async def test_project_target_uses_installed_catalogue(self):
        with patch.object(tools, 'list_owned_projects', return_value=self.catalogue):
            request = tools.make_launch_request(self.binding, self.paths, tools.LaunchArgs('shell', project='one'))
            self.assertEqual((request.cwd, request.profile, request.omp_profile), (self.cwd, 'Ordinary', None))
            for args in (tools.LaunchArgs('shell'), tools.LaunchArgs('shell', cwd=str(self.cwd), project='one'),
                         tools.LaunchArgs('handoff', project='one', task='private', omp_profile='other')):
                with self.assertRaises(ValueError): tools.make_launch_request(self.binding, self.paths, args)
            with patch.object(tools, 'resolve_omp_profile', return_value=OmpProfile('other', self.root/'other')):
                request = tools.make_launch_request(self.binding, self.paths, tools.LaunchArgs('handoff', cwd=str(self.cwd), task='private', omp_profile='other'))
                self.assertEqual(request.omp_profile.agent_dir, self.root/'other')

    async def test_no_guess_or_private_payload_in_result(self):
        with patch.object(tools, 'list_owned_projects', return_value=ProjectCatalogue('not_configured')):
            with self.assertRaises(ValueError): tools.make_launch_request(self.binding, self.paths, tools.LaunchArgs('shell', cwd=str(self.cwd)))
            request = tools.make_launch_request(self.binding, self.paths, tools.LaunchArgs('shell', cwd=str(self.cwd), shell_profile='Chosen', window_id='Explicit'))
            self.assertEqual((request.window_id, request.profile), ('Explicit', 'Chosen'))
            request = tools.make_launch_request(self.binding, self.paths, tools.LaunchArgs('shell', cwd=str(self.cwd), shell_profile='Chosen'))
            self.assertEqual(request.window_id, '')
            for bad in (dict(mode='new'), dict(mode='shell', task='secret'), dict(mode='handoff', task=''), dict(mode='shell', window_id=42)):
                with self.assertRaises(ValueError): tools.LaunchArgs(**bad)
            with self.assertRaises(ValueError): tools.make_launch_request(self.binding, self.paths, tools.LaunchArgs('handoff', cwd=str(self.cwd), task='x'*65536))
        safe = tools.safe_result(dict(status='unknown', window_id='W', tab_id='T', session_id='S', command='unverified', identity='unverified', history='not_requested', ack='unconfirmed', findings=[], argv=['secret'], task='secret'))
        self.assertNotIn('secret', json.dumps(safe))
        self.assertEqual(safe['tab_id'], 'T')

    def test_shell_and_handoff_keep_same_pty(self):
        for mode, exit_code in (('shell', 0), ('handoff', 0), ('handoff', 23)):
            with self.subTest(mode=mode, exit_code=exit_code):
                binary = self.root/'bin'; binary.mkdir(exist_ok=True)
                omp = binary/'omp'; evidence = self.root/'pty.json'
                omp.write_text('#!'+sys.executable+'\nimport os,json\njson.dump(dict(tty=os.ttyname(0),cwd=os.getcwd()),open('+repr(str(evidence))+',"w"))\nraise SystemExit('+str(exit_code)+')\n'); omp.chmod(0o700)
                (self.root/'.zshenv').write_text('unsetopt GLOBAL_RCS\n')
                (self.root/'.zshrc').write_text('export PATH='+shlex.quote(str(binary))+':/usr/bin:/bin\nPROMPT="READY> "\n')
                identity = None if mode == 'shell' else LaunchIdentity(omp, (), ((str(omp),),), '')
                inspection = LaunchInspection(self.root/'it2', Path('/bin/zsh'), 'G', 'W', identity)
                captured = []
                async def create(window, profile, guid, command, **kwargs):
                    captured.append(command)
                    return LaunchCreation('unknown', 'W', 'T', 'S', time.monotonic(), ())
                with patch.object(tools, 'list_owned_projects', return_value=self.catalogue):
                    request = tools.make_launch_request(self.binding, self.paths, tools.LaunchArgs(mode, cwd=str(self.cwd), task='private task' if mode=='handoff' else None))
                with patch.object(orchestration, 'inspect_launch', return_value=(inspection, [])), patch.object(orchestration, 'create_tab', create):
                    _, result = orchestration.launch(request, self.paths, SimpleNamespace())
                self.assertEqual(len(captured), 1)
                self.assertEqual((request.mode, request.cwd, request.profile), (mode, self.cwd, 'Ordinary' if mode=='shell' else 'iterm2-utils:omp'))
                self.assertNotIn('private task', json.dumps(result))
                pid, fd = pty.fork()
                if pid == 0:
                    os.execve('/bin/sh', shlex.split(captured[0]), dict(HOME=str(self.root), ZDOTDIR=str(self.root), PATH='/usr/bin:/bin', TERM='xterm'))
                output = b''
                def until(marker):
                    nonlocal output
                    deadline = time.monotonic()+5
                    while marker not in output and time.monotonic()<deadline:
                        if select.select([fd], [], [], .1)[0]:
                            try: output += os.read(fd, 65536)
                            except OSError: break
                    self.assertIn(marker, output)
                try:
                    until(b'READY> '); output=b''
                    os.write(fd, b"print -r -- PTY_$((6*7)); /bin/pwd; /usr/bin/tty && print -r -- TTY_$((6*7))\n")
                    until(b'PTY_42'); until(str(self.cwd).encode()); until(b'TTY_42')
                    if mode=='handoff':
                        child = json.loads(evidence.read_text())
                        self.assertIn(child['tty'].encode(), output.splitlines())
                        self.assertEqual(child['cwd'], str(self.cwd))
                finally:
                    os.write(fd,b'exit\n')
                    for force in (False, True):
                        if force:
                            try: os.kill(pid, signal.SIGKILL)
                            except ProcessLookupError: pass
                        deadline=time.monotonic()+2
                        while time.monotonic()<deadline:
                            if select.select([fd],[],[],.02)[0]:
                                try: os.read(fd,65536)
                                except OSError: pass
                            if os.waitpid(pid,os.WNOHANG)[0]: break
                        else: continue
                        break
                    else: self.fail('Fixture PTY did not reap')
                    os.close(fd)

    async def test_non_launcher_receipt_supplies_only_verified_parent(self):
        from iterm2_utils import state
        from iterm2_utils.models import Receipt, Selection
        args=tools.LaunchArgs('shell',cwd=str(self.cwd))
        self.paths.data.mkdir()
        with self.assertRaises(ValueError): tools.make_launch_request(self.binding,self.paths,args)
        receipt=Receipt('2',Selection(frozenset({'clipboard'}),frozenset(),'Recorded Ordinary',self.profile),[],[])
        state.save(self.binding.receipt_path,receipt)
        request=tools.make_launch_request(self.binding,self.paths,args)
        self.assertEqual(request.profile,'Recorded Ordinary')
        catalogue=tools.list_owned_projects(self.paths,self.profile)
        self.assertEqual((catalogue.status,catalogue.projects),('not_configured',()))
        other=replace(self.binding,profile=OmpProfile('other',self.root/'other'))
        with self.assertRaises(ValueError): tools.make_launch_request(other,self.paths,args)
        self.binding.receipt_path.write_text('{}')
        with self.assertRaises(ValueError): tools.make_launch_request(self.binding,self.paths,args)

    async def test_cancelled_launch_is_not_retried(self):
        await self._exercise_worker_loss()

    async def test_outer_deadline_reaps_created_worker_without_retry(self):
        await self._exercise_worker_loss(deadline=True)

    async def test_loss_negative_controls_detect_missing_protections(self):
        with self.assertRaisesRegex(AssertionError, 'Retained created IDs'):
            await self._exercise_worker_loss(publish=False)
        with self.assertRaisesRegex(AssertionError, 'Worker outer deadline'):
            await self._exercise_worker_loss(deadline=True, enforce_timeout=False)

    async def _exercise_worker_loss(self, *, deadline=False, publish=True, enforce_timeout=True):
        # Run the actual worker and launch(), replacing only native boundaries.
        fixture = r'''
import json,os,signal,sys,time
from pathlib import Path
from iterm2_utils import launch
from iterm2_utils.launch_checks import LaunchInspection,LaunchIdentity
from iterm2_utils.launch_api import LaunchCreation
from iterm2_utils.mcp.launch_worker import main
root=Path(sys.argv[1])
identity=LaunchIdentity(Path('/fixture/omp'),(),(('/fixture/omp',),),'')
launch.inspect_launch=lambda paths,request,runner:(LaunchInspection(Path('/fixture/it2'),Path('/bin/zsh'),'G','W',identity),[])
async def create(*args,**kwargs):
    with (root/'creates').open('a') as log: log.write('create\n')
    print('PRIVATE SDK OUTPUT')
    return LaunchCreation('created_unverified','W','T','S',time.monotonic()+30,())
def paused_observation(self):
    # Simulate unrecoverable final observations; never emit a replacement result.
    signal.signal(signal.SIGTERM,lambda *unused:(time.sleep(.2),os._exit(0)))
    (root/'observing').touch()
    time.sleep(30)
    raise TimeoutError()
launch.create_tab=create
launch.Terminal.panes=paused_observation
if sys.argv[2]=='0':
    class DropProgress:
        def write(self,text):
            if 'progress' not in json.loads(text): sys.__stdout__.write(text)
        def flush(self): sys.__stdout__.flush()
    sys.stdout=DropProgress()
main()
'''
        for name in ('creates','observing'):
            (self.root/name).unlink(missing_ok=True)
        real_spawn=asyncio.create_subprocess_exec
        real_timeout=asyncio.timeout
        children=[]
        async def spawn(*argv, **kwargs):
            self.assertNotIn('private task',repr(argv))
            child=await real_spawn(sys.executable,'-c',fixture,str(self.root),str(int(publish)),**kwargs)
            children.append(child)
            return child
        def timeout(seconds):
            return real_timeout(seconds if enforce_timeout else None)
        task=None
        try:
            with patch.object(tools,'list_owned_projects',return_value=self.catalogue), patch.object(tools.asyncio,'create_subprocess_exec',spawn), patch.object(tools,'WORKER_SECONDS',1 if deadline else 10), patch.object(tools.asyncio,'timeout',timeout):
                task=asyncio.create_task(tools.run_launch(self.binding,tools.LaunchArgs('handoff',cwd=str(self.cwd),task='private task')))
                ready_by=time.monotonic()+3
                while not (self.root/'observing').exists() and not task.done() and time.monotonic()<ready_by:
                    await asyncio.sleep(.01)
                self.assertTrue((self.root/'observing').exists(),'Real worker never reached post-create observation')
                if deadline:
                    done,_=await asyncio.wait({task},timeout=2)
                    met_deadline=bool(done)
                    if not done: task.cancel()
                else:
                    met_deadline=True
                    task.cancel()
                    await asyncio.sleep(.05)
                    task.cancel()
                result=await task
            self.assertEqual(len(children),1)
            self.assertIsNotNone(children[0].returncode,'Private worker was not reaped')
            self.assertEqual((self.root/'creates').read_text(),'create\n','Native creation was retried')
            self.assertTrue(met_deadline,'Worker outer deadline did not terminate observations')
            self.assertEqual((result['status'],result['window_id'],result['tab_id'],result['session_id']),('created_unverified','W','T','S'),'Retained created IDs were lost')
            self.assertNotIn('private task',json.dumps(result))
            self.assertNotIn('PRIVATE SDK OUTPUT',json.dumps(result))
        finally:
            if task is not None and not task.done():
                task.cancel()
                await task

    async def test_worker_runs_real_orchestration_without_stdout_payload(self):
        fixture = r'''
import sys,time
from pathlib import Path
from iterm2_utils import launch
from iterm2_utils.launch_checks import LaunchInspection
from iterm2_utils.launch_api import LaunchCreation
from iterm2_utils.mcp.launch_worker import main
launch.inspect_launch=lambda paths,request,runner:(LaunchInspection(Path('/fixture/it2'),Path('/bin/zsh'),'G','W',None),[])
async def create(*args,**kwargs):
    print('PRIVATE SDK OUTPUT')
    return LaunchCreation('unknown','W','T','S',time.monotonic(),())
launch.create_tab=create
main()
'''
        real_spawn=asyncio.create_subprocess_exec
        async def spawn(*argv, **kwargs):
            return await real_spawn(sys.executable, '-c', fixture, **kwargs)
        with patch.object(tools, 'list_owned_projects', return_value=self.catalogue), patch.object(tools.asyncio, 'create_subprocess_exec', spawn):
            result=await tools.run_launch(self.binding, tools.LaunchArgs('shell', cwd=str(self.cwd), shell_profile='Ordinary'))
        self.assertEqual((result['status'],result['tab_id'],result['session_id']),('created_unverified','T','S'))
        self.assertNotIn('PRIVATE',json.dumps(result))
