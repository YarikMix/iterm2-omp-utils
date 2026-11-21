"""Private single-request worker. Stdout contains only bounded evidence frames."""
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import signal
import sys

from .. import launch as orchestration
from ..commands import Runner
from ..launch_checks import LaunchRequest, validate_request
from ..models import OmpProfile, Paths
from .launch_tools import FRAME_LIMIT, REQUEST_LIMIT, safe_result, uncertain


def main():
    protocol = sys.stdout
    known = {}
    def emit(frame):
        data = json.dumps(frame)
        if len(data.encode())+1 > FRAME_LIMIT:
            raise ValueError('Oversized worker frame')
        protocol.write(data+'\n'); protocol.flush()
    def stop(*unused):
        try: task = asyncio.current_task()
        except RuntimeError: task = None
        if task is not None: task.cancel()
        else: raise InterruptedError('Worker stopped')
    signal.signal(signal.SIGTERM, stop)
    result = uncertain(known)
    with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
        try:
            line = sys.stdin.buffer.readline(REQUEST_LIMIT+1)
            if len(line)>REQUEST_LIMIT or not line.endswith(b'\n'):
                raise ValueError('Invalid worker request')
            payload = json.loads(line)
            if set(payload) != {'request','paths'}:
                raise ValueError('Invalid worker request')
            paths = Paths(**{k:Path(v) for k,v in payload['paths'].items()})
            raw = payload['request']
            if raw.get('mode') not in {'shell','handoff'} or raw.get('resume') is not None or raw.get('allow_duplicate') is not False:
                raise ValueError('Invalid worker mode')
            raw['cwd'] = Path(raw['cwd'])
            if raw['handoff'] is not None: raw['handoff'] = Path(raw['handoff'])
            if raw['omp_profile'] is not None:
                profile = raw['omp_profile']
                raw['omp_profile'] = OmpProfile(profile['name'], Path(profile['agent_dir']))
            request = LaunchRequest(**raw)
            validate_request(request)
            native_create = orchestration.create_tab
            async def create(*args, **kwargs):
                known['window_id'] = args[0]
                emit({'progress': dict(known)})
                creation = await native_create(*args, **kwargs)
                for key in ('window_id','tab_id','session_id'):
                    value = getattr(creation,key)
                    if value is not None: known[key] = value
                emit({'progress': dict(known)})
                return creation
            # The module's existing launch orchestration owns all SDK/ack deadlines.
            original = orchestration.create_tab
            try:
                orchestration.create_tab = create
                _, result = orchestration.launch(request, paths, Runner())
                result = safe_result(result)
            finally:
                orchestration.create_tab = original
        except (Exception, SystemExit, asyncio.CancelledError):
            result = uncertain(known)
    emit({'result': result})


if __name__ == '__main__':
    main()
