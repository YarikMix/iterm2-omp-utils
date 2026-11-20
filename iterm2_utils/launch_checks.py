"""Operation-specific capability checks; no agent version or settings pin."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
from .commands import Runner
from .discovery import _iterm
from .models import Finding, OmpProfile, Paths
from .omp_sessions import ResumeTarget, resolve_resume
from .terminal import Terminal


@dataclass(frozen=True)
class LaunchRequest:
    window_id: str
    profile: str
    cwd: Path
    omp_profile: OmpProfile | None
    mode: str
    handoff: Path | None = None
    resume: ResumeTarget | None = None
    allow_duplicate: bool = False


@dataclass(frozen=True)
class LaunchIdentity:
    executable: Path
    arguments: tuple[str, ...]
    prefixes: tuple[tuple[str, ...], ...]
    version: str
    wrapper: str = ''
    interpreter: Path | None = None


@dataclass(frozen=True)
class LaunchInspection:
    it2: Path
    zsh: Path
    profile_guid: str
    window_id: str
    identity: LaunchIdentity | None
    window_basis: tuple[str,str] = ('explicit','')


def validate_request(request):
    if (type(request.allow_duplicate) is not bool or request.allow_duplicate and request.mode!='resume' or
            request.mode not in {'shell','new','handoff','resume'} or not isinstance(request.window_id,str) or
            not isinstance(request.profile,str) or not request.profile.strip() or
            any(ord(c)<32 or ord(c)==127 for c in request.window_id+request.profile)):
        raise ValueError('launch_invalid_target')
    if not isinstance(request.cwd,Path) or not request.cwd.is_absolute() or not request.cwd.is_dir():
        raise ValueError('launch_invalid_path')
    if request.mode=='shell':
        if request.omp_profile is not None:
            raise ValueError('launch_shell_agent_profile')
    elif not isinstance(request.omp_profile,OmpProfile) or not request.omp_profile.agent_dir.is_absolute():
        raise ValueError('launch_invalid_path')
    if (request.handoff is not None) != (request.mode == 'handoff') or (request.resume is not None) != (request.mode == 'resume'):
        raise ValueError('launch_invalid_mode')
    if request.handoff is not None:
        from .launch import read_handoff
        read_handoff(request.handoff,request.cwd)
    if request.resume is not None:
        target=resolve_resume(request.resume.path,request.resume.session_id,request.omp_profile)
        if target != request.resume or target.cwd != request.cwd:
            raise ValueError('launch_resume_mismatch')


def wrapper_arguments(body):
    if not body.strip():
        return []
    # Only a single literal passthrough. Never evaluate a wrapper to learn its effects.
    match=re.fullmatch(r'\s*command\s+omp\s+(.*?)\s*"\$@"\s*',body,re.S)
    if not match:
        raise ValueError('launch_wrapper_unverified')
    quote=None
    for char in match[1]:
        if char in '\n\r':
            raise ValueError('launch_wrapper_unverified')
        if quote=="'":
            if char=="'":quote=None
        elif quote=='"':
            if char=='"':quote=None
            elif char in '$`\\':raise ValueError('launch_wrapper_unverified')
        elif char in "'\"":
            quote=char
        elif not (char.isalnum() or char in ' \t_./:=+,%@-'):
            raise ValueError('launch_wrapper_unverified')
    if quote is not None:
        raise ValueError('launch_wrapper_unverified')
    args=shlex.split(match[1])
    allowed={'--profile','--model','--provider','--thinking','--config'}
    index=0
    while index<len(args):
        key,sep,value=args[index].partition('=')
        if key=='--no-daemon' and not sep:
            if args.count('--no-daemon')>2:raise ValueError('launch_wrapper_unverified')
            index+=1
            continue
        if key not in allowed:
            raise ValueError('launch_wrapper_unverified')
        if not sep:
            index+=1
            if index>=len(args):raise ValueError('launch_wrapper_unverified')
            value=args[index]
        if not value or value.startswith('-'):raise ValueError('launch_wrapper_unverified')
        index+=1
    return args


def executable_prefixes(executable,environment):
    real=executable.resolve(strict=True)
    if not real.is_file() or not os.access(real,os.X_OK):
        raise ValueError('launch_executable_unavailable')
    with real.open('rb') as source:
        header=source.readline(256)
    prefixes=[(str(executable),),(str(real),)]
    if header.strip() == b'#!/usr/bin/env bun':
        bun=shutil.which('bun',path=environment.get('PATH',os.defpath))
        if not bun or not Path(bun).is_absolute():raise ValueError('launch_bun_unavailable')
        # The verified login shell selects the interpreter, not the caller's PATH.
        interpreter=Path(bun).resolve(strict=True)
        if not interpreter.is_file() or not os.access(interpreter,os.X_OK):raise ValueError('launch_bun_unavailable')
        prefixes.extend((str(interpreter),str(script)) for script in (executable,real))
    elif header.startswith(b'#!'):
        raise ValueError('launch_interpreter_unverified')
    return tuple(dict.fromkeys(prefixes))


def _shell_identity(zsh,runner,env,cwd,profile_name):
    code=('import json,sys,os; from pathlib import Path; '
          'sys.path.insert(0,'+repr(str(Path(__file__).resolve().parent.parent))+'); '
          'from iterm2_utils.omp_profile import resolve_omp_profile; '
          'raw=dict(zip(("executable","alias","function"),sys.argv[1:4])); '
          'raw["environment"]=dict(os.environ); '
          'profile=resolve_omp_profile(Path.home(),dict(os.environ),sys.argv[4]); '
          'raw["profile"]={"name":profile.name,"agent_dir":str(profile.agent_dir)}; print(json.dumps(raw))')
    script=(shlex.join([sys.executable,'-c',code])+
            ' "${commands[omp]-}" "${aliases[omp]-}" "${functions[omp]-}" '+shlex.quote(profile_name))
    command='cd -- '+shlex.quote(str(cwd))+' && exec '+shlex.join([str(zsh),'-ilc',script])
    result=runner.run(['/bin/sh','-c',command],timeout=10,env=env)
    if result.returncode:raise ValueError('launch_wrapper_unverified')
    # Startup output stays private; require exactly one valid final identity frame.
    raw=json.loads(result.stdout.splitlines()[-1])
    if raw['alias']:raise ValueError('launch_wrapper_unverified')
    selected=OmpProfile(raw['profile']['name'],Path(raw['profile']['agent_dir']))
    return Path(raw['executable']),wrapper_arguments(raw['function']),raw['function'],raw['environment'],selected


def inspect_launch(paths: Paths, request: LaunchRequest, runner: Runner) -> tuple[LaunchInspection | None, list[Finding]]:
    try:
        validate_request(request)
        if platform.system() != 'Darwin':raise ValueError('launch_platform')
        app,_=_iterm(paths)
        zsh=shutil.which('zsh')
        if not app or not zsh or not Path(zsh).is_absolute():raise ValueError('launch_dependency')
        it2=app/'Contents/Resources/utilities/it2'
        terminal=Terminal(it2,runner)
        window=terminal.select_window(request.window_id,dict(os.environ))
        parents=[value.rsplit(':',1)[-1] for key in ('ITERM_SESSION_ID','TERM_SESSION_ID') if (value:=os.environ.get(key))]
        basis=('explicit','') if request.window_id else ('parent',parents[0]) if parents else ('sole','')
        profiles=terminal.profiles()
        matches=[p for p in profiles if p.get('name') == request.profile]
        if len(matches)!=1 or not isinstance(matches[0].get('guid'),str) or not matches[0]['guid']:
            raise ValueError('launch_profile_unverified')
        guid=matches[0]['guid']
        if sum(p.get('guid')==guid for p in profiles)!=1:raise ValueError('launch_profile_unverified')
        profile=terminal.profile(request.profile)
        if profile.get('name')!=request.profile or profile.get('guid')!=guid or profile.get('command') not in (None,''):
            raise ValueError('launch_profile_startup_command')
        if request.mode=='shell':return LaunchInspection(it2,Path(zsh),guid,window,None,basis),[]
        env=dict(os.environ)
        for key in ('ITERM_SESSION_ID','TERM_SESSION_ID'):env.pop(key,None)
        explicit=request.omp_profile.name or 'default'
        executable,args,wrapper,effective_env,selected=_shell_identity(Path(zsh),runner,env,request.cwd,explicit)
        if not executable.is_absolute():raise ValueError('launch_executable_unavailable')
        for key in ('ITERM_SESSION_ID','TERM_SESSION_ID'):effective_env.pop(key,None)
        prefixes=executable_prefixes(executable,effective_env)
        for i,arg in enumerate(args):
            if arg=='--profile' and args[i+1]!=explicit or arg.startswith('--profile=') and arg.split('=',1)[1]!=explicit:
                raise ValueError('launch_profile_mismatch')
        if selected!=request.omp_profile:
            raise ValueError('launch_profile_mismatch')
        help_result=runner.run([str(executable),'--help'],timeout=10,env=effective_env)
        required=['--cwd','--profile']+(['--resume'] if request.mode=='resume' else ['--config'])
        if help_result.returncode or any(flag not in help_result.stdout for flag in required):
            raise ValueError('launch_capability_unavailable')
        version_text=''
        try:
            version=runner.run([str(executable),'--version'],timeout=10,env=effective_env)
            if version.returncode==0:version_text=version.stdout.strip()[:128]
        except (OSError,subprocess.SubprocessError):
            pass  # Version output is informational, never a capability gate.
        interpreter=next((Path(prefix[0]) for prefix in prefixes if len(prefix)==2),None)
        identity=LaunchIdentity(executable,tuple(args),prefixes,version_text,wrapper,interpreter)
        return LaunchInspection(it2,Path(zsh),guid,window,identity,basis),[]
    except (OSError,ValueError,KeyError,IndexError,TypeError,AttributeError,subprocess.SubprocessError):
        return None,[Finding('launch',None if request.mode=='shell' else 'omp','launch_preflight_unverified','unavailable',
                             'Launch inputs, terminal target, profile or executable capabilities could not be verified.')]
