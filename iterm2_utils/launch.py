"""One SDK creation with independent command, identity, history and ack evidence."""
import asyncio
from dataclasses import dataclass, asdict, replace
import json
import os
from pathlib import Path
import sys
import shlex
import stat
import subprocess
import tempfile
import time
import uuid
from .launch_api import create_tab
from .launch_checks import LaunchRequest, inspect_launch
from .models import Finding
from .omp_sessions import SessionBinding, binding_record, matches_conversation
from .terminal import Terminal

_PRIVATE_LIMIT=65536


@dataclass(frozen=True)
class Handoff:
    path: Path
    request_id: str
    ack_path: Path
    cwd: Path


def _private_read(path):
    before=path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or
            before.st_mode & 0o777 != 0o600 or before.st_size>_PRIVATE_LIMIT):
        raise ValueError('Unsafe private artifact')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as source:
        opened=os.fstat(source.fileno())
        if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino):raise ValueError('Replaced artifact')
        data=source.read(_PRIVATE_LIMIT+1)
        after=os.fstat(source.fileno())
    if (len(data)>_PRIVATE_LIMIT or (after.st_size,after.st_mtime_ns)!=(opened.st_size,opened.st_mtime_ns)):
        raise ValueError('Changing artifact')
    return data,before


def prepare_handoff(cwd: Path, task: str) -> Handoff:
    """Task8 API: retain this unique private directory; never reuse/delete old ack."""
    if not cwd.is_absolute() or not cwd.is_dir() or not task.strip():raise ValueError('Invalid handoff')
    root=Path(tempfile.mkdtemp(prefix='iterm2-utils-handoff-'))
    artifact=Handoff(root/'handoff.md',str(uuid.uuid4()),root/'ack.json',cwd.resolve())
    metadata=dict(request_id=artifact.request_id,ack_path=str(artifact.ack_path),cwd=str(artifact.cwd))
    text=(json.dumps(metadata)+'\n\n'+task+'\n\nBefore acting, read the task and verify your actual cwd. '
          'Atomically write a new mode-0600 ack.json at ack_path with nonempty string fields '
          'request_id, thread_id (your ACTUAL omp session ID), cwd (actual cwd), accepted_task, first_step. '
          'Do not invent identity or acknowledge work you have not read. This receipt is not task completion.\n')
    encoded=text.encode('utf8')
    if len(encoded)>_PRIVATE_LIMIT:
        root.rmdir()
        raise ValueError('Handoff exceeds private artifact size limit')
    fd=os.open(artifact.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(encoded)
    return artifact


def read_handoff(path: Path, cwd: Path) -> Handoff:
    if not path.is_absolute():raise ValueError('Absolute handoff required')
    parent=path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.getuid() or parent.st_mode & 0o777 != 0o700:
        raise ValueError('Private handoff directory required')
    data,_=_private_read(path)
    raw=json.loads(data.splitlines()[0])
    request_id=str(uuid.UUID(raw['request_id']))
    ack=Path(raw['ack_path'])
    if raw['request_id']!=request_id or ack!=path.parent/'ack.json' or raw['cwd']!=str(cwd.resolve()):
        raise ValueError('Handoff metadata mismatch')
    return Handoff(path,request_id,ack,cwd.resolve())


def valid_ack(artifact, session_id, started_ns):
    try:
        data,info=_private_read(artifact.ack_path)
        raw=json.loads(data)
        fields=('request_id','thread_id','cwd','accepted_task','first_step')
        return (started_ns<=info.st_mtime_ns<=time.time_ns() and isinstance(raw,dict) and
                all(isinstance(raw.get(k),str) and raw[k].strip() for k in fields) and
                raw['request_id']==artifact.request_id and raw['thread_id']==session_id and raw['cwd']==str(artifact.cwd))
    except (OSError,ValueError,KeyError,TypeError):return False


def build_argv(request, inspection, overlay, artifact=None):
    identity=inspection.identity
    args=[str(identity.executable),*identity.arguments]
    # Selected profile is explicit even when the parent environment used another one.
    args+=['--profile',request.omp_profile.name or 'default','--cwd',str(request.cwd)]
    if request.mode=='resume':return [*args,'--resume',str(request.resume.path)]
    args+=['--config',str(overlay)]
    if artifact is not None:
        args+=['--','Read the handoff file at '+str(artifact.path)+
               ' and carry out the task described there. Acknowledge receipt as instructed using your actual omp session ID.']
    return args


def build_command(request, inspection, argv):
    if request.mode=='shell':
        invocation=[str(inspection.zsh),'-il']
    else:
        identity=inspection.identity
        guard=('[[ ${commands[omp]-} == '+shlex.quote(str(identity.executable))+
               ' && -z ${aliases[omp]-} && ${functions[omp]-} == '+shlex.quote(identity.wrapper)+' ]] || exit 1; ')
        profile_check=('import os,sys,shutil; from pathlib import Path; '
                       'sys.path.insert(0,'+repr(str(Path(__file__).resolve().parent.parent))+'); '
                       'from iterm2_utils.omp_profile import resolve_omp_profile; '
                       'profile_ok=resolve_omp_profile(Path.home(),dict(os.environ),sys.argv[1]).agent_dir'
                       ' == Path(sys.argv[2]); '
                       'bun=shutil.which("bun") if sys.argv[3] else None; '
                       'sys.exit(0 if profile_ok and (not sys.argv[3] or bun and Path(bun).resolve()==Path(sys.argv[3])) else 1)')
        guard+=shlex.join([sys.executable,'-c',profile_check,request.omp_profile.name or 'default',
                           str(request.omp_profile.agent_dir),str(identity.interpreter or '')])+' || exit 1; '
        # -ilc does not read a prompt command; arm the installed observer explicitly.
        guard+='if (( $+functions[_iterm2_utils_appearance_arm] )); then _iterm2_utils_appearance_arm; fi; '
        invocation=[str(inspection.zsh),'-ilc',guard+'exec '+shlex.join([
            '/usr/bin/env','OMP_PROFILE='+ (request.omp_profile.name or 'default'),
            'PI_CODING_AGENT_DIR='+str(request.omp_profile.agent_dir),*argv])]
    return shlex.join(['/bin/sh','-c','cd -- '+shlex.quote(str(request.cwd))+' && exec '+shlex.join(invocation)])


def _observed_binding(terminal, sid):
    raw=terminal.observe(sid)
    if not isinstance(raw,dict):return None
    for binding in terminal.bindings():
        if (binding.terminal_id==sid and terminal.process_start(binding.pid)==binding.process_start and
                all(raw.get(key)==value for key,value in binding_record(binding).items() if key not in {'tab_id','window_id'})):
            if not raw.get('tab_id') or not raw.get('window_id'):return None
            return replace(binding,tab_id=raw['tab_id'],window_id=raw['window_id'])
    return None


def _existing(request,terminal):
    """An uninstrumented live pane is uncertainty, not negative dialog evidence."""
    for candidate in terminal.bindings():
        plausible=(candidate.session_id==request.resume.session_id and
                   candidate.profile==request.resume.profile and candidate.cwd==request.resume.cwd)
        if not plausible and not matches_conversation(request.resume,candidate):continue
        if terminal.process_start(candidate.pid)!=candidate.process_start:continue
        actual=_observed_binding(terminal,candidate.terminal_id)
        if actual and matches_conversation(request.resume,actual):return actual,False
        return None,True
    for pane in terminal.panes():
        actual=_observed_binding(terminal,pane['terminal_id'])
        if actual is None:return None,True
        if matches_conversation(request.resume,actual):return actual,False
    return None,False


def _command_matches(line,allowed):
    # iTerm observations may be literal-space-joined or fully shell-quoted argv.
    if any(line==' '.join(argv) for argv in allowed):return True
    try:return shlex.split(line) in allowed
    except ValueError:return False


def launch(request: LaunchRequest, paths, runner):
    inspection,findings=inspect_launch(paths,request,runner)
    output=dict(mode='shell' if request.mode=='shell' else 'launch_omp',launch_mode=request.mode,status='blocked',
                window_id=None,tab_id=None,session_id=None,profile=request.profile,command='unverified',
                identity='unverified',history='not_requested',ack='not_requested',findings=[asdict(f) for f in findings])
    if inspection is None:return 2,output
    terminal=Terminal(inspection.it2,runner,paths.data/'identity')
    artifact=None
    try:
        if request.mode=='resume' and not request.allow_duplicate:
            existing,ambiguous=_existing(request,terminal)
            if existing:
                output.update(status='already_open',window_id=existing.window_id,tab_id=existing.tab_id,
                              session_id=existing.terminal_id,identity='verified',history='verified')
                return 0,output
            if ambiguous:
                output['findings'].append(asdict(Finding('launch','omp','launch_live_candidate_incomplete','unavailable',
                    'A live dialog candidate cannot be independently resolved; no duplicate was created.')))
                return 2,output
        if request.mode=='handoff':
            artifact=read_handoff(request.handoff,request.cwd)
            if artifact.ack_path.exists() or artifact.ack_path.is_symlink():raise ValueError('Ack already exists')
        overlay=None
        if request.mode in {'new','handoff'}:
            root=Path(tempfile.mkdtemp(prefix='iterm2-utils-launch-'))
            overlay=root/'fresh.json'
            fd=os.open(overlay,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as stream:json.dump({'autoResume':False},stream)
        argv=None if request.mode=='shell' else build_argv(request,inspection,overlay,artifact)
        command=build_command(request,inspection,argv)
        started_ns=time.time_ns()
        creation=asyncio.run(create_tab(inspection.window_id,request.profile,inspection.profile_guid,command,
                                       window_basis=inspection.window_basis))
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
        output['findings'].append(asdict(Finding('launch','omp','launch_precreate_unverified','unavailable','Launch preparation could not be verified.')))
        return 2,output
    output.update(window_id=creation.window_id,tab_id=creation.tab_id,session_id=creation.session_id)
    output['findings'].extend(asdict(f) for f in creation.findings)
    if creation.status=='blocked':return 2,output
    terminal.deadline=creation.deadline
    verified_binding=None
    complete=(creation.window_id==inspection.window_id and creation.tab_id and creation.session_id and creation.deadline)
    while complete and time.monotonic()<creation.deadline:
        try:
            panes=terminal.panes()
            matches=[p for p in panes if p['tab_id']==creation.tab_id]
            profile=terminal.profile(request.profile)
            exact=(matches==[dict(terminal_id=creation.session_id,tab_id=creation.tab_id,window_id=inspection.window_id)] and
                   profile.get('name')==request.profile and profile.get('guid')==inspection.profile_guid and
                   terminal.variable(creation.session_id,'session.profileName')==request.profile)
            line=terminal.variable(creation.session_id,'session.commandLine')
            job=terminal.variable(creation.session_id,'session.jobName')
            if request.mode=='shell':
                command_ok=_command_matches(line,[[str(inspection.zsh),'-il'],[str(inspection.zsh),'-l']]) and job in {'zsh','-zsh'}
            else:
                identity=inspection.identity
                allowed=[[*prefix,*argv[1:]] for prefix in identity.prefixes]
                command_ok=_command_matches(line,allowed) and job in {Path(prefix[0]).name for prefix in identity.prefixes}
            if exact and command_ok and time.monotonic()<creation.deadline:
                output.update(status='launched',command='verified')
                if request.mode=='shell':return 0,output
                verified_binding=_observed_binding(terminal,creation.session_id)
                if verified_binding and (verified_binding.tab_id!=creation.tab_id or verified_binding.window_id!=creation.window_id or
                                         verified_binding.profile!=request.omp_profile or verified_binding.cwd!=request.cwd):
                    verified_binding=None
                if verified_binding:
                    output['identity']='verified'
                    if request.mode=='resume':output['history']='verified' if matches_conversation(request.resume,verified_binding) else 'unverified'
                    break
        except (OSError,ValueError,TypeError,KeyError,AttributeError,TimeoutError,subprocess.SubprocessError):pass
        remaining=creation.deadline-time.monotonic()
        if remaining>0:time.sleep(min(.2,remaining))
    if request.mode=='resume' and output['history']=='not_requested':output['history']='unverified'
    if artifact:
        output['ack']='unconfirmed'
        if output['command']=='verified':
            terminal.deadline=time.monotonic()+120
            while time.monotonic()<terminal.deadline:
                try:
                    actual=_observed_binding(terminal,creation.session_id)
                    if (actual and actual.profile==request.omp_profile and actual.cwd==request.cwd and
                            actual.tab_id==creation.tab_id and actual.window_id==creation.window_id and
                            valid_ack(artifact,actual.session_id,started_ns)):
                        output.update(ack='received',identity='verified');break
                except (OSError,ValueError,TypeError,KeyError,TimeoutError,subprocess.SubprocessError):pass
                time.sleep(min(.2,max(0,terminal.deadline-time.monotonic())))
    if output['command']=='verified':return 0,output
    output['status']='created_unverified' if creation.tab_id or creation.session_id else 'unknown'
    return 3,output
