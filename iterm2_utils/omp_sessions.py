"""Saved omp headers and live identity; no title/filename history inference."""
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import stat
from .models import OmpProfile


@dataclass(frozen=True)
class ResumeTarget:
    path: Path
    session_id: str
    cwd: Path
    profile: OmpProfile


@dataclass(frozen=True)
class SessionBinding:
    terminal_id: str
    tab_id: str | None
    window_id: str | None
    session_file: Path | None
    session_id: str
    cwd: Path
    profile: OmpProfile
    pid: int
    process_start: str
    generation: str


def _header(path: Path) -> dict:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError('Session requires an absolute regular file')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError('Session is not a regular file')
            record = json.loads(source.readline(65537))
            # Current native persistence puts a fixed title slot before the header.
            if record.get('type') == 'title':
                record = json.loads(source.readline(65537))
        if (record.get('type') != 'session' or not isinstance(record.get('id'),str) or
                not record['id'] or not isinstance(record.get('cwd'),str) or
                not Path(record['cwd']).is_absolute()):
            raise ValueError('Invalid session header')
        return record
    except (OSError, ValueError, TypeError, AttributeError) as error:
        raise ValueError('Session header unavailable or invalid') from error


def resolve_resume(path: Path, expected_id: str, profile: OmpProfile) -> ResumeTarget:
    """Explicit profile is provenance supplied by the caller, not guessed from paths.

    Native --session-dir overrides are legitimate; a session header has no profile
    field. The launch consumer must supply its resolved selected profile unchanged.
    """
    header = _header(path)
    if header['id'] != expected_id or not profile.agent_dir.is_absolute():
        raise ValueError('Session identity mismatch')
    cwd = Path(header['cwd'])
    if not cwd.is_dir():
        raise ValueError('Session working directory unavailable')
    return ResumeTarget(path, expected_id, cwd, profile)


def matches_conversation(target: ResumeTarget, actual: SessionBinding) -> bool:
    if actual.profile != target.profile or actual.session_file is None or actual.cwd != target.cwd:
        return False
    try:
        root = _header(target.path)
        current = _header(actual.session_file)
        if root['id'] != target.session_id or Path(root['cwd']) != target.cwd:
            return False
        if current['id'] != actual.session_id or Path(current['cwd']) != actual.cwd:
            return False
        if actual.session_id == target.session_id:
            return actual.session_file == target.path
        # Native continuations live in the same directory; forks only parentSession.
        if actual.session_file.parent != target.path.parent:
            return False
        headers, paths = {}, {}
        for path in target.path.parent.glob('*.jsonl'):
            try:
                header = _header(path)
            except ValueError:
                continue
            if header['id'] in headers:
                return False  # Ambiguous substituted/copy identity is not evidence.
            headers[header['id']] = header
            paths[header['id']] = path
        seen = set()
        while current['id'] != target.session_id:
            if current['id'] in seen:
                return False
            seen.add(current['id'])
            parent = current.get('continuationOf')
            if not parent or parent != current.get('parentSession') or parent not in headers:
                return False
            if not _holds_latest_turn(paths[parent], paths[current['id']]):
                return False
            current = headers[parent]
            if Path(current['cwd']) != target.cwd:
                return False
        return True
    except (ValueError, OSError, TypeError, KeyError, AttributeError):
        return False


def binding_record(binding: SessionBinding) -> dict:
    record = asdict(binding)
    record['session_file'] = str(binding.session_file) if binding.session_file else None
    record['cwd'] = str(binding.cwd)
    record['profile']['agent_dir'] = str(binding.profile.agent_dir)
    return record


def find_open(target: ResumeTarget, transport) -> SessionBinding | None:
    """Transport supplies bindings(), process_start(pid), observe(terminal_id).

    observe returns independently scoped SDK user-variable identity plus actual
    terminal/tab/window IDs, never a registry echo or active-tab observation.
    """
    for binding in transport.bindings():
        if not matches_conversation(target, binding):
            continue
        if transport.process_start(binding.pid) != binding.process_start:
            continue
        observed = transport.observe(binding.terminal_id)
        expected = binding_record(binding)
        if isinstance(observed,dict) and all(observed.get(key) == value for key,value in expected.items()):
            return binding
    return None


def read_bindings(registry: Path) -> list[SessionBinding]:
    """Convert the shared standalone validator's records to the public type."""
    from runtime.terminal_identity import read_identity_records
    return [SessionBinding(**{key: value for key, value in raw.items()
                              if key not in {'schema', 'profile', 'cwd', 'session_file'}},
                           profile=OmpProfile(raw['profile']['name'], Path(raw['profile']['agent_dir'])),
                           cwd=Path(raw['cwd']),
                           session_file=Path(raw['session_file']) if raw['session_file'] else None)
            for raw in read_identity_records(registry)]


def _holds_latest_turn(parent: Path, child: Path) -> bool:
    """A continuation must contain the parent's newest conversation entry."""
    latest = None
    with parent.open('rb') as source:
        for line in source:
            entry = json.loads(line)
            message = entry.get('message')
            custom_type = entry.get('customType') if entry.get('type') == 'custom_message' else (
                message.get('customType') if isinstance(message,dict) else None)
            if (entry.get('type') in {'message','custom_message','branch_summary','reset_boundary'}
                    and custom_type != 'eval-state-context'):
                latest = entry.get('id')
    if latest is None:
        return True
    with child.open('rb') as source:
        return any(entry.get('type') != 'session' and entry.get('id') == latest
                   for entry in (json.loads(line) for line in source))
