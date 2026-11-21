"""Read-only catalogue and ephemeral, single-use approval checkpoints.

No durable edit format: the existing lifecycle, CAS and recovery journal own writes.
"""
import base64
import copy
import json
import os
import stat
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from . import engine, lifecycle, state
from .commands import Runner
from .config import iterm
from .features import project_launcher as launcher
from .models import Context, FileEdit, OmpProfile, Paths, ProfileBarEdit, Receipt
from .profile_api import _refs


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: str


@dataclass(frozen=True)
class ProjectCatalogue:
    status: str
    projects: tuple[Project, ...] = ()
    parent_profile: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ProjectChange:
    operation: str
    project: str | None = None
    name: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class ProjectPreview:
    status: str
    before: tuple[Project, ...] = ()
    after: tuple[Project, ...] = ()
    removes_launcher: bool = False
    _witness: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ProjectEditResult:
    status: str


FILE_LIMIT = 1024 * 1024
RECEIPT_LIMIT = 16 * 1024 * 1024

def _safe_bytes(path, *, limit=FILE_LIMIT):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError('Unsafe owned file')
        raw = stream.read(limit+1)
        if len(raw) > limit:
            raise ValueError('Owned file too large')
        return raw


def read_receipt(path):
    """Decode exactly the bounded no-follow bytes, never reopen after validation."""
    from .config.jsonfile import parse
    raw = _safe_bytes(path, limit=RECEIPT_LIMIT)
    receipt = state.decode(parse(raw))
    if not isinstance(receipt, Receipt):
        raise ValueError('Current ownership required')
    return raw, receipt


def _owned_receipt(paths, profile):
    receipt_raw, receipt = read_receipt(paths.data/'receipt.json')
    if not isinstance(receipt, Receipt) or receipt.selection.omp_profile != profile:
        raise ValueError('Ownership profile mismatch')
    return receipt_raw, receipt


def _owned(paths, profile, *, receipt_state=None):
    receipt_raw, receipt = _owned_receipt(paths, profile) if receipt_state is None else receipt_state
    if launcher.FEATURE not in receipt.selection.features:
        return None
    raw = {}
    for path in (paths.config/launcher.FILENAME, paths.profiles/launcher.FILENAME):
        value = _safe_bytes(path)
        resource = next((r for r in receipt.resources if r['kind'] == 'file' and
            r['target'] == str(path.resolve()) and launcher.OWNER in r['owners'] and
            launcher.FEATURE in r['owners']), None)
        if resource is None or resource['installed'] != {'exists': True, 'value': base64.b64encode(value).decode()}:
            raise ValueError('Owned file mismatch')
        raw[str(path)] = value
    document = launcher._config(raw[str(paths.config/launcher.FILENAME)], historical=True)
    rows = json.loads(raw[str(paths.profiles/launcher.FILENAME)])['Profiles']
    projects = tuple(Project(**p) for p in document['projects'])
    if len(rows) != len(projects) or any(row['Guid'] != launcher.guid(p.id) or
            row['Name'] != p.name or row['Working Directory'] != p.path for row, p in zip(rows, projects)):
        raise ValueError('Installed project identity mismatch')
    _physical_unique(projects)
    return receipt, document, projects, (receipt_raw, raw)


def list_owned_projects(paths: Paths, profile: OmpProfile) -> ProjectCatalogue:
    try:
        if not (paths.data/'receipt.json').exists():
            return ProjectCatalogue('not_configured')
        receipt_state = _owned_receipt(paths, profile)
        owned = _owned(paths, profile, receipt_state=receipt_state)
        if owned is None:
            return ProjectCatalogue('not_configured', parent_profile=receipt_state[1].selection.parent_profile)
        receipt, _, projects, _ = owned
        return ProjectCatalogue('ok', projects, receipt.selection.parent_profile)
    except (OSError, ValueError, TypeError, KeyError):
        return ProjectCatalogue('conflict')


def select_project(projects: tuple[Project, ...], selector: str) -> Project | None:
    if type(selector) is not str or len(selector) > 4096 or any(ord(c) < 32 for c in selector):
        raise ValueError('Invalid project selector')
    for matches in ([p for p in projects if p.id == selector], [p for p in projects if p.name == selector],
                    [p for p in projects if Path(selector).is_absolute() and Path(p.path).resolve() == Path(selector).resolve()]):
        if len(matches) > 1:
            raise ValueError('Ambiguous project selector')
        if matches:
            return matches[0]
    return None


def _physical_unique(projects):
    paths = [Path(p.path).resolve() for p in projects]
    if len(set(paths)) != len(paths) or len({p.name for p in projects}) != len(projects):
        raise ValueError('Project name or physical path conflict')


def _snapshot(context, runner, receipt, document, projects):
    guids = {launcher.guid(p.id) for p in projects}
    guids.update(r['target'] for r in receipt.resources if r['kind'] == 'profile_bar' and launcher.OWNER in r['owners'])
    for resource in receipt.resources:
        if resource['kind'] == 'file' and resource['target'] == str((context.paths.profiles/launcher.FILENAME).resolve()):
            guids.update(engine._project_guids(base64.b64decode(resource['installed']['value'])))
    inventory = iterm.validate_launcher_inventory(iterm._request(context, runner,
        {'operation': 'inspect', 'reference_guids': sorted(guids)}))
    # The inspector excludes bar properties before deduplicating hidden edges.
    replaced_bars = [dict(guid=row['guid'], bar=row['bar'])
                     for row in inventory['profiles'] if row['guid'] in guids]
    inventory = iterm.validate_launcher_inventory(iterm._request(context, runner,
        {'operation': 'inspect', 'reference_guids': sorted(guids), 'replaced_bars': replaced_bars}))
    names = set(document['profiles']) | {receipt.selection.parent_profile} | {p.name for p in projects}
    relevant = guids | {p['guid'] for p in inventory['profiles'] if p['name'] in names}
    profiles = []
    for row in inventory['profiles']:
        edges = sorted(relevant.intersection(row['references']))
        if row['guid'] in relevant:
            profiles.append(dict(copy.deepcopy(row), references=edges))
        elif edges:
            profiles.append(dict(guid=row['guid'], references=edges))
    sessions = [dict(copy.deepcopy(row), references=sorted(relevant.intersection(row['references'])))
                for row in inventory['sessions'] if not row['provenance'] or
                row['profile_guid'] in relevant or relevant.intersection(row['references'])]
    return dict(profiles=sorted(profiles, key=lambda p:p['guid']), sessions=sorted(sessions, key=lambda s:s['id']),
                position=inventory['position'], default_removed=inventory['default_guid'] in guids), inventory


def _checkpoint(context, runner, receipt, document, projects):
    if projects:
        candidate = dict(document, projects=[dict(id=p.id, name=p.name, path=p.path) for p in projects])
        raw = json.dumps(candidate, ensure_ascii=False).encode()
        candidate_context = replace(context, project_launcher_config=launcher._Candidate(raw))
        prepared_context, plan = lifecycle.prepare_install_checkpoint(candidate_context, receipt.selection, receipt, launcher.FEATURE, runner)
        return prepared_context, plan, frozenset()
    prepared_context, plan, owners = lifecycle.prepare_uninstall_checkpoint(
        replace(context, project_launcher_config=None), receipt, frozenset({launcher.FEATURE}), runner)
    return prepared_context, plan, owners


def _check_removal(receipt, projects, plan, inventory):
    owned = set()
    for resource in receipt.resources:
        if resource['kind'] == 'file' and launcher.OWNER in resource['owners']:
            doc = json.loads(base64.b64decode(resource['installed']['value']))
            if 'Profiles' in doc:
                owned = {row['Guid'] for row in doc['Profiles']}
    removed = owned - {launcher.guid(p.id) for p in projects}
    if not removed:
        return
    replacements = {e.guid: e.after for e in plan.changes.edits if isinstance(e, ProfileBarEdit)}
    if not projects:
        replacements.update({r['target']: r['before']['value'] for r in receipt.resources
            if r['kind'] == 'profile_bar' and launcher.OWNER in r['owners']})
    for edit in plan.changes.edits:
        if isinstance(edit, FileEdit) and edit.owner == launcher.OWNER and edit.after is not None:
            rows = json.loads(edit.after).get('Profiles', ())
            replacements.update({row['Guid']: {key: row[key] for key in iterm.BAR_KEYS} for row in rows})
    if inventory['default_guid'] in removed:
        raise ValueError('Removed profile is default')
    for row in inventory['profiles']:
        if row['guid'] in removed:
            continue
        refs = set(row['references'])
        if row['guid'] in replacements:
            refs.update(_refs(replacements[row['guid']], removed, {}))
        if removed & refs:
            raise ValueError('Surviving reference')
    for row in inventory['sessions']:
        if not row['provenance'] or row['profile_guid'] in removed or removed.intersection(row['references']):
            raise ValueError('Live reference')


def prepare_project_edit(context: Context, runner: Runner, change: ProjectChange) -> ProjectPreview:
    if (context.paths.data/'journal').exists():
        return ProjectPreview('blocked')
    try:
        owned = _owned(context.paths, context.omp_profile)
        if owned is None:
            return ProjectPreview('blocked')
        receipt, document, before, files = owned
        after = list(before)
        operation = change.operation
        if operation == 'add':
            name = launcher._text(change.name)
            path = str(Path(change.path).resolve())
            if not Path(change.path).is_absolute() or not Path(path).is_dir():
                raise ValueError('Project directory unavailable')
            matching = [p for p in before if p.name == name or Path(p.path).resolve() == Path(path)]
            if matching:
                if len(matching) != 1 or matching[0].name != name or Path(matching[0].path).resolve() != Path(path):
                    raise ValueError('Project conflict')
            else:
                after.append(Project(str(uuid.uuid4()), name, path))
        elif operation in {'rename', 'move', 'remove'}:
            project = select_project(before, change.project)
            if project is None and operation != 'remove':
                raise ValueError('Project unavailable')
            if project is not None:
                index = after.index(project)
                if operation == 'remove':
                    after.pop(index)
                elif operation == 'rename':
                    after[index] = replace(project, name=launcher._text(change.name))
                else:
                    path = Path(change.path)
                    if not path.is_absolute() or not path.is_dir():
                        raise ValueError('Project directory unavailable')
                    after[index] = replace(project, path=str(path.resolve()))
        else:
            raise ValueError('Unsupported operation')
        after = tuple(after)
        _physical_unique(after)
        snapshot, inventory = _snapshot(context, runner, receipt, document, after)
        prepared_context, plan, owners = _checkpoint(context, runner, receipt, document, after)
        if any(f.state in lifecycle.BLOCKING for f in plan.changes.findings):
            raise ValueError('Checkpoint unavailable')
        _check_removal(receipt, after, plan, inventory)
        witness = dict(context=copy.deepcopy(context), receipt=receipt, files=files, document=document,
                       snapshot=snapshot, plan=plan, prepared_context=prepared_context, owners=owners, used=False)
        return ProjectPreview('noop' if before == after else 'ready', before, after, not after, witness)
    except FileNotFoundError:
        return ProjectPreview('blocked')
    except (OSError, ValueError, TypeError, KeyError):
        return ProjectPreview('conflict')


def apply_project_edit(context: Context, runner: Runner, preview: ProjectPreview, *, authorize: Callable[[], None]) -> ProjectEditResult:
    witness = preview._witness
    if preview.status not in {'ready', 'noop'} or not isinstance(witness, dict) or witness['used']:
        return ProjectEditResult('blocked' if preview.status == 'blocked' else 'conflict')
    witness['used'] = True
    failure = None
    def check():
        nonlocal failure
        try:
            authorize()
        except Exception:
            failure = 'blocked'
            raise ValueError('Authorization unavailable') from None
        if (context.paths.data/'journal').exists():
            failure = 'blocked'
            raise ValueError('Recovery required')
        if context != witness['context']:
            raise ValueError('Binding changed')
        owned = _owned(context.paths, context.omp_profile)
        if owned is None or owned[0] != witness['receipt'] or owned[3] != witness['files']:
            raise ValueError('Owned checkpoint changed')
        snapshot, _ = _snapshot(context, runner, owned[0], witness['document'], preview.after)
        if snapshot != witness['snapshot']:
            raise ValueError('Native checkpoint changed')
        _, fresh, owners = _checkpoint(context, runner, owned[0], witness['document'], preview.after)
        if (fresh.selection != witness['plan'].selection or fresh.changes != witness['plan'].changes or
                owners != witness['owners']):
            raise ValueError('Prepared effect changed')
    if preview.status == 'noop':
        try:
            with engine._lock(context):
                check()
            return ProjectEditResult('noop')
        except Exception:
            return ProjectEditResult(failure or 'conflict')
    outcome = engine.apply(witness['plan'], witness['prepared_context'], runner,
        remove_owners=witness['owners'], expected_receipt=witness['receipt'], prewrite_check=check)
    codes = {f.code for f in outcome.findings}
    if codes & {'native_outcome_unknown', 'rollback_unresolved', 'commit_pending'}:
        return ProjectEditResult('unknown')
    if 'transaction_rolled_back' in codes:
        return ProjectEditResult('rolled_back')
    if any(f.state in lifecycle.BLOCKING for f in outcome.findings):
        return ProjectEditResult(failure or 'conflict')
    return ProjectEditResult('applied')
