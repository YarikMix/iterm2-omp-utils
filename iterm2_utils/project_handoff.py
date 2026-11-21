"""Explicit proof and durable in-place ownership of a dedicated manual panel."""
import copy
import hashlib
import json
import os
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

from .commands import Runner
from .config import iterm
from .features import project_launcher as launcher
from .models import Context, Outcome, Selection, OmpProfile
from .profile_api import _refs
from .project_edits import read_receipt


@dataclass(frozen=True)
class HandoffPreview:
    status: str
    fingerprint: str | None = None
    _checkpoint: object = field(default=None, repr=False, compare=False)


def _source(path, directory):
    if (not path.is_absolute() or path.is_symlink() or
            path.parent.resolve() != directory.resolve() or directory.is_symlink()):
        raise ValueError('Unsafe source address')
    launcher.dynamic_path(directory, {'handoff': {'source':path.name}})
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_nlink != 1 or info.st_size > 1048576):
                raise ValueError('Unsafe source file')
            raw = stream.read(1048577)
            if len(raw) > 1048576:
                raise ValueError('Source too large')
            return raw, stat.S_IMODE(info.st_mode)
    finally:
        os.close(directory_fd)


def _source_provenance(directory, source, guids, raw, mode):
    """Prove no competing definition, not merely one SDK effective row."""
    proof, total = [], 0
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(proof) >= 256:
                    raise ValueError('Dynamic source inventory too large')
                path = directory/entry.name
                content, file_mode = _source(path, directory)
                total += len(content)
                if total > 16 * 1048576:
                    raise ValueError('Dynamic source inventory too large')
                document = json.loads(content, object_pairs_hook=launcher._unique_object)
                if (type(document) is not dict or type(document.get('Profiles')) is not list or
                        len(document['Profiles']) > 4096):
                    raise ValueError('Dynamic source inventory incomplete')
                ids = [iterm.identifier(row['Guid']) for row in document['Profiles']]
                if path.resolve() == source:
                    if content != raw or file_mode != mode:
                        raise ValueError('Source changed')
                elif guids.intersection(ids):
                    raise ValueError('Competing dynamic definition')
                proof.append(dict(name=entry.name, digest=hashlib.sha256(content).hexdigest(), mode=file_mode))
        address = os.stat(directory, follow_symlinks=False)
        opened = os.fstat(fd)
        if (address.st_dev, address.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError('Dynamic source directory changed')
    finally:
        os.close(fd)
    if source.name not in {row['name'] for row in proof}:
        raise ValueError('Source inventory incomplete')
    return sorted(proof, key=lambda row:row['name'])


def _buttons(bar, projects, document):
    if bar['Show Status Bar'] is not True:
        raise ValueError('Panel is not visible')
    expected = [launcher._component(p, document) for p in projects]
    components = bar['Status Bar Layout']['components']
    # Every action component belongs to this dedicated catalogue or is rejected.
    actual = [c for c in components if c['class'] == 'iTermStatusBarActionComponent']
    if not iterm.same(actual, expected):
        raise ValueError('Panel catalogue differs')
    unowned = copy.deepcopy(bar)
    unowned['Status Bar Layout']['components'] = [
        c for c in components if c['class'] != 'iTermStatusBarActionComponent']
    if _refs(unowned, set(document['handoff']['guids'].values()), {}):
        raise ValueError('Unowned panel reference')


def prepare_handoff(context: Context, runner: Runner, source: Path,
                    profiles: tuple[str, ...]) -> HandoffPreview:
    """Validate only; never acquire a lock, recover, or dispatch a native write."""
    paths = context.paths
    if os.path.lexists(paths.data/'journal'):
        return HandoffPreview('blocked')
    try:
        raw, mode = _source(source, paths.profiles)
        source = source.resolve()
        receipt_raw, receipt = read_receipt(paths.data/'receipt.json')
        if (launcher.FEATURE in receipt.selection.features or
                context.omp_profile not in (None, receipt.selection.omp_profile)):
            raise ValueError('Current ownership conflicts')
        catalogue = paths.config/launcher.FILENAME
        standard = paths.profiles/launcher.FILENAME
        if os.path.lexists(catalogue) or (standard != source and os.path.lexists(standard)):
            raise ValueError('Launcher files already exist')
        if any(launcher.OWNER in r['owners'] or r['kind'] == 'file' and
                r['target'] in {str(source), str(catalogue.resolve())} for r in receipt.resources):
            raise ValueError('Launcher ownership already exists')
        if type(profiles) is not tuple or not profiles or len(profiles) > 256:
            raise ValueError('Explicit panels required')
        if len({launcher._text(p) for p in profiles}) != len(profiles):
            raise ValueError('Duplicate panels')
        source_document = json.loads(raw, object_pairs_hook=launcher._unique_object)
        if type(source_document) is not dict or set(source_document) != {'Profiles'}:
            raise ValueError('Dedicated source required')
        rows = source_document['Profiles']
        if type(rows) is not list or not rows or len(rows) > 256:
            raise ValueError('Dedicated source required')
        required = {'Name','Guid','Dynamic Profile Parent GUID','Custom Directory','Working Directory', *iterm.BAR_KEYS}
        projects, guids, physical = [], set(), set()
        for row in rows:
            if type(row) is not dict or not required <= set(row) or set(row) - required - {'Custom Command','Command'}:
                raise ValueError('Unknown source fields')
            guid = iterm.identifier(row['Guid'])
            project = dict(id=guid, name=launcher._text(row['Name']), path=row['Working Directory'])
            # Reuse the catalogue's boundary validation without inventing a second schema.
            launcher._config(json.dumps(dict(profiles=list(profiles), projects=[project])).encode())
            path = Path(project['path']).resolve()
            identity = (path.stat().st_dev, path.stat().st_ino)
            if guid in guids or identity in physical:
                raise ValueError('Ambiguous project identity')
            guids.add(guid); physical.add(identity); projects.append(project)
            if (row['Custom Directory'] != 'Yes' or row.get('Custom Command','No') != 'No' or
                    row.get('Command','') != ''):
                raise ValueError('Unsupported launch action')
        document = dict(profiles=list(profiles), projects=projects,
            handoff=dict(source=source.name, guids={p['id']:p['id'] for p in projects}))
        launcher._owned_config(json.dumps(document).encode())
        provenance = _source_provenance(paths.profiles, source, guids, raw, mode)
        query = dict(operation='inspect', reference_guids=sorted(guids), launch_guids=sorted(guids))
        inventory = iterm.validate_launcher_inventory(iterm._request(context, runner, query))
        native = {p['name']:p for p in inventory['profiles']}
        parent = native[receipt.selection.parent_profile]
        targets = [native[name] for name in profiles]
        if guids.intersection(p['guid'] for p in targets) or parent['guid'] in guids:
            raise ValueError('Project cannot be a target panel')
        relevant = guids | {p['guid'] for p in targets} | {parent['guid']}
        by_guid = {p['guid']:p for p in inventory['profiles']}
        for row, project in zip(rows, projects):
            live = by_guid[row['Guid']]
            if (live['name'] != project['name'] or live['working_directory'] != project['path'] or
                    row['Dynamic Profile Parent GUID'] != parent['guid'] or
                    not iterm.same(live.get('launch'), dict(parent_guid=parent['guid'],
                        custom_directory='Yes', custom_command='No', command='')) or
                    not iterm.same(live['bar'], iterm.source_bar(row)) or
                    not iterm.same(live['bar'], parent['bar'])):
                raise ValueError('Source and effective profile differ')
        for target in targets:
            _buttons(target['bar'], projects, document)
        for row in rows:
            _buttons(iterm.source_bar(row), projects, document)
        if inventory['position'] != iterm.POSITION_BOTTOM or inventory['default_guid'] in guids:
            raise ValueError('Native checkpoint differs')
        selected = {p['guid'] for p in targets}
        replacements = [dict(guid=g, bar=by_guid[g]['bar']) for g in sorted(guids | selected)]
        filtered = iterm.validate_launcher_inventory(iterm._request(context, runner,
            dict(query, replaced_bars=replacements)))
        # A second read excludes only proven matching bars, never hidden references.
        for key in ('profiles','sessions','default_guid','position'):
            first, second = copy.deepcopy(inventory[key]), copy.deepcopy(filtered[key])
            if key in {'profiles','sessions'}:
                for row in (*first, *second):
                    row.pop('references')
            if not iterm.same(first, second):
                raise ValueError('Native checkpoint changed')
        for row in filtered['profiles']:
            if guids.intersection(row['references']):
                raise ValueError('External or hidden reference')
        for row in filtered['sessions']:
            if (not row['provenance'] or row['profile_guid'] in guids or
                    guids.intersection(row['references']) or
                    row['profile_guid'] in selected and not iterm.same(row['bar'], by_guid[row['profile_guid']]['bar'])):
                raise ValueError('Session checkpoint unavailable')
        evidence = dict(profiles=sorted([p for p in filtered['profiles'] if p['guid'] in relevant], key=lambda p:p['guid']),
            sessions=sorted([s for s in filtered['sessions'] if s['profile_guid'] in relevant], key=lambda s:s['id']),
            default_guid=filtered['default_guid'], position=filtered['position'])
        if provenance != _source_provenance(paths.profiles, source, guids, raw, mode):
            raise ValueError('Dynamic source provenance changed')
        witness = dict(source=str(source), source_digest=hashlib.sha256(raw).hexdigest(), mode=mode,
            receipt_digest=hashlib.sha256(receipt_raw).hexdigest(), document=document, evidence=evidence,
            source_provenance=provenance)
        fingerprint = hashlib.sha256(json.dumps(witness, sort_keys=True, allow_nan=False).encode()).hexdigest()
        checkpoint = dict(context=copy.deepcopy(context), source=source, raw=raw, mode=mode,
            receipt_raw=receipt_raw, receipt=receipt, document=document, inventory=filtered, evidence=evidence,
            source_provenance=provenance)
        return HandoffPreview('ready', fingerprint, checkpoint)
    except FileNotFoundError:
        return HandoffPreview('blocked')
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return HandoffPreview('conflict')


def apply_handoff(context: Context, runner: Runner, source: Path,
                  profiles: tuple[str, ...], expected_fingerprint: str) -> Outcome:
    """Only this entry may acquire unchanged manual launcher resources."""
    from . import engine, state
    previous = engine._empty(Selection(frozenset(), frozenset(), 'Default',
        context.omp_profile or OmpProfile(None, context.paths.home/'.omp')))
    def conflict():
        return Outcome(previous, [engine._finding('handoff_conflict',
            'The explicit launcher checkpoint could not be verified.', launcher.FEATURE)])
    try:
        if (type(expected_fingerprint) is not str or len(expected_fingerprint) != 64 or
                any(c not in '0123456789abcdef' for c in expected_fingerprint)):
            return conflict()
        # Invalid confirmations do not even create a lock file. Revalidation below
        # is authoritative; the outside read is not permission to commit.
        preview = prepare_handoff(context, runner, source, profiles)
        if preview.status != 'ready' or preview.fingerprint != expected_fingerprint:
            return conflict()
        with engine._lock(context):
            preview = prepare_handoff(context, runner, source, profiles)
            if preview.status != 'ready' or preview.fingerprint != expected_fingerprint:
                return conflict()
            checkpoint = preview._checkpoint
            previous = checkpoint['receipt']
            document, inventory = checkpoint['document'], checkpoint['inventory']
            source = checkpoint['source']
            catalogue = (context.paths.config/launcher.FILENAME).resolve()
            raw = (json.dumps(document, sort_keys=True, indent=2)+'\n').encode()
            records = [
                engine._resource('file', source, {'mode':checkpoint['mode']},
                    engine._encode(checkpoint['raw']), engine._encode(checkpoint['raw']), launcher.OWNER),
                engine._resource('file', catalogue, {'mode':0o600},
                    engine._encode(None), engine._encode(raw), launcher.OWNER)]
            for row in inventory['profiles']:
                if row['name'] in profiles:
                    value = engine._value(row['bar'])
                    records.append(engine._resource('profile_bar', row['guid'], {},
                        value, copy.deepcopy(value), launcher.OWNER))
            value = engine._value(inventory['position'])
            records.append(engine._resource('status_bar_position', iterm.DOMAIN, {},
                value, copy.deepcopy(value), launcher.OWNER))
            addresses = {engine._identity(r) for r in records}
            if any(engine._identity(r) in addresses for r in previous.resources):
                return conflict()
            for record in records:
                record['owners'].append(launcher.FEATURE)
            result = copy.deepcopy(previous)
            result.selection = replace(previous.selection, features=previous.selection.features | {launcher.FEATURE})
            result.resources.extend(records)
            state.validate(result)
            guids = set(document['handoff']['guids'].values())
            selected = {r['target'] for r in records if r['kind'] == 'profile_bar'}
            query = dict(operation='inspect', reference_guids=sorted(guids), launch_guids=sorted(guids),
                replaced_bars=[dict(guid=p['guid'], bar=p['bar']) for p in inventory['profiles']
                    if p['guid'] in guids | selected])
            def verify():
                if (read_receipt(context.paths.data/'receipt.json')[0] != checkpoint['receipt_raw'] or
                        _source(source, context.paths.profiles) != (checkpoint['raw'], checkpoint['mode']) or
                        _source_provenance(context.paths.profiles, source, guids,
                            checkpoint['raw'], checkpoint['mode']) != checkpoint['source_provenance']):
                    raise ValueError('File checkpoint changed')
                current = iterm.validate_launcher_inventory(iterm._request(context, runner, query))
                if not iterm.same(current, inventory):
                    raise ValueError('Native checkpoint changed')
                for record in records:
                    if record['kind'] == 'file' and not engine._same(
                            engine._read(record, runner, context), record['installed']):
                        raise ValueError('Ownership checkpoint changed')
                if stat.S_IMODE(catalogue.stat().st_mode) != 0o600:
                    raise ValueError('Catalogue mode changed')
            ok, findings = engine._transaction([records[1]], result, context, runner,
                precommit_check=verify)
            return Outcome(result if ok else previous, findings)
    except Exception:
        return conflict()
