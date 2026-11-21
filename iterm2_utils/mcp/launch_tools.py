"""Strict MCP launch inputs and one private, never-retried launch worker."""
import asyncio
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path

from ..discovery import resolve_paths
from ..launch import prepare_handoff
from ..launch_checks import LaunchRequest, validate_request
from ..models import Paths
from ..omp_profile import resolve_omp_profile
from ..project_edits import list_owned_projects, select_project
from .binding import McpBinding

WORKER_SECONDS = 270
FRAME_LIMIT = 65536
REQUEST_LIMIT = 524288  # JSON escaping can expand a bounded UTF-8 handoff.


@dataclass(frozen=True)
class LaunchArgs:
    mode: str
    cwd: str | None = None
    project: str | None = None
    window_id: str | None = None
    shell_profile: str | None = None
    task: str | None = None
    omp_profile: str | None = None

    def __post_init__(self):
        if self.mode not in {'shell', 'handoff'}:
            raise ValueError('Invalid launch mode')
        for field in ('cwd', 'project', 'window_id', 'shell_profile', 'omp_profile'):
            value = getattr(self, field)
            if value is not None and (type(value) is not str or not value.strip() or len(value)>4096 or any(ord(c)<32 or ord(c)==127 for c in value)):
                raise ValueError('Invalid launch input')
        if self.mode == 'shell':
            if self.task is not None or self.omp_profile is not None:
                raise ValueError('Invalid shell input')
        elif self.shell_profile is not None or type(self.task) is not str or not self.task.strip() or len(self.task.encode('utf8'))>65536:
            raise ValueError('Invalid handoff input')


def bound_paths(binding: McpBinding) -> Paths:
    return replace(resolve_paths(), data=binding.receipt_path.parent, repo=binding.install_root)


def make_launch_request(binding: McpBinding, paths: Paths, args: LaunchArgs) -> LaunchRequest:
    if (args.cwd is None) == (args.project is None):
        raise ValueError('Choose exactly one launch destination')
    catalogue = list_owned_projects(paths, binding.profile)
    selected = binding.profile if args.omp_profile is None else resolve_omp_profile(paths.home, dict(os.environ), args.omp_profile)
    if args.project is not None:
        if catalogue.status != 'ok' or selected.agent_dir.resolve() != binding.profile.agent_dir.resolve():
            raise ValueError('Project catalogue unavailable for selected profile')
        project = select_project(catalogue.projects, args.project)
        if project is None:
            raise ValueError('Project unavailable')
        cwd = Path(project.path)
    else:
        cwd = Path(args.cwd)
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError('Launch directory unavailable')
    profile = 'iterm2-utils:omp' if args.mode == 'handoff' else args.shell_profile or catalogue.parent_profile
    if profile is None:
        raise ValueError('Choose an ordinary shell profile')
    artifact = prepare_handoff(cwd, args.task) if args.mode == 'handoff' else None
    request = LaunchRequest(args.window_id or '', profile, cwd, selected if args.mode == 'handoff' else None,
                            args.mode, artifact.path if artifact else None)
    validate_request(request)
    return request


def safe_result(raw: dict) -> dict:
    """Only launch's public evidence, never an invocation or arbitrary payload."""
    choices = dict(status={'blocked','launched','created_unverified','unknown'}, command={'verified','unverified'},
                   identity={'verified','unverified'}, history={'not_requested','verified','unverified'},
                   ack={'not_requested','received','unconfirmed'})
    result = {}
    for key, allowed in choices.items():
        value = raw.get(key)
        if value not in allowed:
            raise ValueError('Invalid launch evidence')
        result[key] = value
    for key in ('window_id','tab_id','session_id'):
        value = raw.get(key)
        if value is not None and (type(value) is not str or not value or len(value)>256 or any(ord(c)<32 for c in value)):
            raise ValueError('Invalid launch identifier')
        result[key] = value
    findings = raw.get('findings', [])
    if not isinstance(findings, list) or len(findings)>64:
        raise ValueError('Invalid findings')
    result['findings'] = [{key: row[key] for key in ('feature','agent','code','state','message')} for row in findings]
    if len(json.dumps(result).encode())>FRAME_LIMIT:
        raise ValueError('Oversized launch evidence')
    return result


def uncertain(known):
    return dict(status='created_unverified' if known.get('tab_id') or known.get('session_id') else 'unknown',
                window_id=known.get('window_id'), tab_id=known.get('tab_id'), session_id=known.get('session_id'),
                command='unverified', identity='unverified', history='not_requested', ack='unconfirmed', findings=[])


async def run_launch(binding: McpBinding, args: LaunchArgs) -> dict:
    paths = bound_paths(binding)
    request = make_launch_request(binding, paths, args)
    payload = dict(request=asdict(request), paths=asdict(paths))
    encoded = json.dumps(payload, default=str).encode()+b'\n'
    if len(encoded)>REQUEST_LIMIT or not binding.python.is_absolute() or not binding.install_root.is_absolute():
        raise ValueError('Invalid worker request')
    known = {}; child = None; reader = None; spawning = None

    async def read():
        while True:
            line = await child.stdout.readline()
            if not line or len(line)>FRAME_LIMIT or not line.endswith(b'\n'):
                raise ValueError('Invalid worker result')
            frame = json.loads(line)
            if set(frame) == {'progress'}:
                progress = frame['progress']
                checked = safe_result(dict(uncertain(progress), **progress))
                for key in ('window_id','tab_id','session_id'):
                    value = checked[key]
                    if value is not None:
                        if key in known and known[key] != value:
                            raise ValueError('Worker target changed')
                        known[key] = value
            elif set(frame) == {'result'}:
                result = safe_result(frame['result'])
                if any(result.get(key)!=value for key,value in known.items()):
                    raise ValueError('Worker target changed')
                return result
            else:
                raise ValueError('Invalid worker frame')

    try:
        async with asyncio.timeout(WORKER_SECONDS):
            spawning = asyncio.create_task(asyncio.create_subprocess_exec(
                str(binding.python), '-I', '-c',
                'import runpy,sys; sys.path.insert(0,sys.argv[1]); runpy.run_module("iterm2_utils.mcp.launch_worker",run_name="__main__")',
                str(binding.install_root), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=FRAME_LIMIT, cwd=str(binding.install_root)))
            child = await asyncio.shield(spawning)
            child.stdin.write(encoded); await child.stdin.drain(); child.stdin.close()
            reader = asyncio.create_task(read())
            result = await asyncio.shield(reader)
            await child.wait()
            return result
    except (Exception, asyncio.CancelledError):
        pass  # Cancellation is loss of observation, never proof of no creation.
    finally:
        async def cleanup():
            nonlocal child
            if child is None and spawning is not None:
                try: child = await spawning
                except Exception: return
            if child is not None:
                if not child.stdin.is_closing(): child.stdin.close()
                if child.returncode is None:
                    try: child.terminate()
                    except ProcessLookupError: pass
                    try: await asyncio.wait_for(child.wait(), 2)
                    except TimeoutError:
                        try: child.kill()
                        except ProcessLookupError: pass
                        await child.wait()
                if reader is not None:
                    if not reader.done(): reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
        closing = asyncio.create_task(cleanup())
        while not closing.done():
            try: await asyncio.shield(closing)
            except asyncio.CancelledError: pass
        closing.result()
    if reader is not None and reader.done() and not reader.cancelled():
        try: return reader.result()
        except Exception: pass
    return uncertain(known)
