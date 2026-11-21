"""Private TUI-only protocol. Approval is an ephemeral plan in this process."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
import json
import os
import sys
from typing import Callable

from .. import state
from ..commands import Runner
from ..discovery import discover
from ..project_edits import ProjectChange, prepare_project_edit, apply_project_edit
from .binding import McpBinding
from .launch_tools import bound_paths

FRAME_LIMIT = 65536


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate field')
        result[key] = value
    return result


def _frame(stream):
    line = stream.readline(FRAME_LIMIT+1)
    if not line:
        return None
    if len(line) > FRAME_LIMIT or not line.endswith(b'\n'):
        raise ValueError('Invalid frame')
    value = json.loads(line, object_pairs_hook=_object)
    if type(value) is not dict:
        raise ValueError('Invalid frame')
    return value


def _change(raw):
    fields = {'add': {'operation', 'name', 'path'}, 'rename': {'operation', 'project', 'name'},
              'move': {'operation', 'project', 'path'}, 'remove': {'operation', 'project'}}
    if type(raw) is not dict or type(raw.get('operation')) is not str or set(raw) != fields.get(raw['operation']):
        raise ValueError('Invalid change')
    for key, value in raw.items():
        limit = 256 if key == 'name' else 4096
        if type(value) is not str or not value.strip() or len(value) > limit or any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError('Invalid change')
    if 'path' in raw and not raw['path'].startswith('/'):
        raise ValueError('Invalid path')
    return ProjectChange(**raw)


def main(binding: McpBinding, *, authorize: Callable[[], None]) -> int:
    protocol, source = sys.stdout, sys.stdin.buffer
    def emit(frame):
        encoded = json.dumps(frame, ensure_ascii=True)+'\n'
        if len(encoded.encode()) > FRAME_LIMIT:
            raise ValueError('Oversized frame')
        protocol.write(encoded)
        protocol.flush()
    status = 'blocked'
    reason = None
    committing = False
    with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
        try:
            frame = _frame(source)
            if frame is None or set(frame) != {'type', 'change'} or frame['type'] != 'prepare':
                raise ValueError('Prepare required')
            change = _change(frame['change'])
            authorize()  # No owned/native reads or planning before current authorization.
            paths = bound_paths(binding)
            receipt = state.load(binding.receipt_path)
            runner = Runner()
            context = discover(paths, runner, features=receipt.selection.features,
                               omp_profile=binding.profile, python=binding.python)
            preview = prepare_project_edit(context, runner, change)
            status = preview.status
            if status == 'blocked' and preview.reason == 'handoff_requires_uninstall':
                reason = 'handoff_requires_uninstall'
            if status == 'ready':
                emit({'preview': dict(status=status, before=[asdict(p) for p in preview.before],
                                      after=[asdict(p) for p in preview.after], removes_launcher=preview.removes_launcher)})
                frame = _frame(source)
                status = 'declined'
                if frame is not None:
                    # EOF seals the sole commit; queued extra frames are rejected before any write.
                    if frame != {'type': 'commit'} or source.read(1):
                        raise ValueError('Invalid confirmation')
                    committing = True
                    status = apply_project_edit(context, runner, preview, authorize=authorize).status
        except Exception:
            status = 'unknown' if committing else 'blocked'
        try:
            result = {'status': status}
            if status == 'blocked' and reason is not None:
                result['reason'] = reason
            emit({'result': result})
        except (OSError, ValueError):
            return 1
    return 0
