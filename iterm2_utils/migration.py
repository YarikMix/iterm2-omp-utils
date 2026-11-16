"""Explicit, receipt-authorized historical cutover; no historical executable API."""
import base64
import copy
import hashlib
import json
from contextlib import ExitStack
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from . import engine, legacy_state, state
from .config import iterm, jsonfile, legacy_mcp
from .models import ChangeSet, Context, Finding, Outcome, Plan, Receipt, Selection
from .omp_profile import resolve_omp_profile
from .commands import Runner

RETIRED = frozenset({'restore', 'bootstrap-skill'})
TRANSFERABLE = frozenset({'appearance', 'project-launcher', 'shell'})


def _finding(code, message, status='ready', feature='migration'):
    return Finding(feature, None, code, status, message)


def _scopes(context):
    from .skill_install import BUNDLES, _context
    return [('features', context), *[(skill, _context(context, skill)) for skill in BUNDLES]]


def _empty(context, parent='Default'):
    profile = context.omp_profile or resolve_omp_profile(context.paths.home, {})
    return Receipt(state.VERSION, Selection(frozenset(), frozenset(), parent, profile), [], [])


def _features(resource):
    return {owner.split(':', 1)[-1] for owner in resource['owners'] if not owner.startswith('shared:')}


def external_writer(resource):
    """Only known receipt inverses that would reactivate an adopted writer."""
    before, installed = resource['before'], resource['installed']
    if resource['kind'] == 'zsh':
        return (resource['locator']['name'] in {'legacy-status','legacy-restore'} and
                before['exists'] and not installed['exists'])
    if resource['kind'] == 'hook':
        return before['exists'] and not installed['exists']
    pointer = resource['locator'].get('pointer', [])
    return (resource['kind'] == 'toml' and len(pointer) == 3 and
            pointer[0] == 'plugins' and pointer[2] == 'enabled' and
            pointer[1].split('@', 1)[0] in {'iterm2-status','codex-iterm2-status'} and
            before == {'exists':True,'value':True} and installed == {'exists':True,'value':False})


def _runtime(resource, context):
    target = Path(resource['target'])
    data = context.paths.data.resolve()
    return (resource['kind'] == 'file' and target.is_relative_to(data/'releases') or
            resource['kind'] == 'symlink' and target == data/'current')


def _active_runtime_references(resources, historical, context, runner, observations):
    """Retained/current consumers must detach before their old code is deleted."""
    data = context.paths.data.resolve()
    releases = data/'releases'
    roots = {releases/Path(resource['target']).relative_to(releases).parts[0]
             for resource in historical if resource['kind'] == 'file' and _runtime(resource, context)}
    current = data/'current'
    paths = set(roots)
    if (any(current.resolve().is_relative_to(root) for root in roots) or
            any(resource['kind'] == 'symlink' and _runtime(resource, context) and
                engine._same(_observe(resource, context, runner), resource['installed'])
                for resource in historical)):
        paths.add(current)
    # Managed shell sources and serialized appearance paths are literal storage
    # references; account for shell apostrophe quoting and JSON Unicode escapes.
    patterns = {text.encode() for path in paths for text in (
        str(path), str(path).replace("'", "'\"'\"'"), json.dumps(str(path), ensure_ascii=True)[1:-1])}
    def references(value):
        if isinstance(value, str):
            return any(pattern in value.encode() for pattern in patterns)
        if isinstance(value, dict):
            return any(references(key) or references(item) for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return any(references(item) for item in value)
        return False
    for resource in resources:
        value = _observe(resource, context, runner)
        observations.append(('runtime_consumer', resource, value))
        if not engine._same(value, resource['installed']):
            return True  # Changed consumers do not prove detachment.
        if not value['exists']:
            continue
        if resource['kind'] == 'file':
            if any(Path(resource['target']).is_relative_to(root) for root in roots):
                return True  # A live owned file also keeps its release siblings.
            payload = base64.b64decode(value['value'], validate=True)
            if Path(resource['target']).suffix == '.json':
                if references(jsonfile.parse(payload)):
                    return True
            elif any(pattern in payload for pattern in patterns):
                return True
        elif references(value['value']):
            return True
    return False


def _compatible_transfer(resource, context):
    features = _features(resource)
    if not features or not features <= TRANSFERABLE or _runtime(resource, context):
        return False
    target = Path(resource['target'])
    if resource['kind'] == 'json' and target == context.paths.config/'appearance.json':
        return features <= {'appearance'}
    if resource['kind'] == 'zsh':
        body = resource['installed']['value'] or ''
        return (features <= {'shell','appearance'} and
                not any(word in body.lower() for word in ('codex','claude','restore','hook.py')))
    if resource['kind'] == 'file':
        return target in {context.paths.config/'appearance.json',
                          context.paths.config/'iterm2-utils-project-launcher.json',
                          context.paths.profiles/'iterm2-utils-project-launcher.json'}
    return resource['kind'] in {'preference','profile_bar','status_bar_position'} and features <= {'appearance'}


def _transfer(resource):
    result = copy.deepcopy(resource)
    result['owners'] = list(dict.fromkeys(owner if owner.startswith('shared:') else owner.split(':',1)[-1]
                                         for owner in result['owners']))
    return result


def _profile_cleanup(resource, context, runner):
    if (resource['kind'] != 'file' or Path(resource['target']) not in {
            context.paths.profiles/'iterm2-utils.json',
            context.paths.profiles/'iterm2-utils-project-launcher.json'}):
        return
    def decoded(value):
        return base64.b64decode(value['value'], validate=True) if value['exists'] else None
    installed = engine._project_guids(decoded(resource['installed']))
    remaining = engine._project_guids(decoded(resource['before']))
    removed = installed - remaining
    if removed:
        iterm.ensure_unreferenced(removed, installed, context, runner)


def _observe(resource, context, runner):
    if resource['kind'] in {'file','json','toml','zsh','hook','symlink'}:
        target = Path(resource['target'])
        resolved = target.parent.resolve()/target.name if resource['kind'] == 'symlink' else target.resolve()
        if resolved != target:
            raise ValueError('Historical storage path changed')
    return engine._read(resource, runner, context)


def _missing_hook_is_ambiguous(resource, context):
    if resource['kind'] != 'hook' or not resource['installed']['exists']:
        return False
    raw = engine._bytes(Path(resource['target']))
    entries = engine._lookup(jsonfile.parse(raw or b'{}'), resource['locator']['pointer'])
    return entries['exists'] and bool(entries['value'])


def _intent_features(raw):
    return legacy_state.decode(raw).selection.features - RETIRED


def _intent_complete(raw, selection):
    historical = legacy_state.decode(raw).selection
    features = historical.features - RETIRED
    return (features <= selection.features and
            ('shortcuts' not in features or historical.shortcuts <= selection.shortcuts))


def _prepare_scope(context, runner, *, restore_external, bootstrap):
    previous = state.load(context.paths.data/'receipt.json')
    if isinstance(previous, legacy_state.LegacyReceipt):
        result = _empty(context, previous.selection.parent_profile)
        historical = [legacy_state.encode(previous)]
    else:
        result = copy.deepcopy(previous) if previous else _empty(context)
        historical = copy.deepcopy(result.legacy_cleanup)
    changes, findings, observations, retained = [], [], [], []
    active = {engine._identity(resource):resource for resource in result.resources}
    runtime_safe = None
    all_resources = [resource for raw in historical for resource in raw['resources']]
    for raw in historical:
        existing_omp_bootstrap = bootstrap and legacy_state.decode(raw).selection.agents == {'omp'}
        pending = copy.deepcopy(raw)
        pending['resources'] = []
        for original in raw['resources']:
            resource = original
            first_finding = len(findings)
            try:
                if resource['kind'] in {'json','toml'} and not resource['locator']['pointer']:
                    raise ValueError('Historical whole-configuration ownership is not an exact entry')
                if resource['kind'] == 'registration':
                    resource = legacy_mcp.storage_resource(resource, all_resources)
                elif legacy_mcp.is_address(resource):
                    legacy_mcp.validate_address(resource)
                current = _observe(resource, context, runner)
                observations.append((resource, current, engine._bytes(Path(resource['target']))
                    if resource['kind'] in {'file','json','toml','zsh','hook'} else None))
                own = active.get(engine._identity(resource))
                if own is not None:
                    if not engine._same(own['installed'], current) or not engine._same(own['before'], resource['before']):
                        raise ValueError('Conflicting current ownership')
                    continue
                if existing_omp_bootstrap:
                    if (resource['kind'] != 'file' or
                            not Path(resource['target']).is_relative_to(result.selection.omp_profile.agent_dir/'skills') or
                            not engine._same(current, resource['installed'])):
                        raise ValueError('Existing omp bootstrap address changed')
                    result.resources.append(_transfer(resource))
                    result.selection = replace(result.selection, features=frozenset({'bootstrap-skill'}))
                    findings.append(_finding('omp_bootstrap_preserved',
                        'Existing owned omp skill file and original inverse are preserved.'))
                    continue
                if external_writer(resource) and not restore_external:
                    if not engine._same(current, resource['installed']):
                        raise ValueError('Adopted external writer changed')
                    pending['resources'].append(copy.deepcopy(original))
                    findings.append(_finding('legacy_external_kept',
                        'Previously disabled external writer stays disabled; its original inverse remains historical, not uninstall ownership.',
                        'pending_ui'))
                    continue
                if external_writer(resource) and restore_external:
                    if result.selection.features & {'status','notifications','shell','appearance'}:
                        raise ValueError('External restoration would conflict with an active omp writer')
                    if not (engine._same(current, resource['before']) or engine._same(current, resource['installed'])):
                        raise ValueError('Adopted external writer changed')
                    if _intent_features(raw) & {'status','notifications','shell','appearance'}:
                        pending['resources'].append(copy.deepcopy(original))
                    if engine._same(current, resource['before']):
                        findings.append(_finding('legacy_external_restore',
                            'The explicitly restored external writer remains active; conflicting native feature intent is retained, not installed.'))
                        continue
                if engine._same(current, resource['before']) and not engine._same(current, resource['installed']):
                    if _missing_hook_is_ambiguous(resource, context):
                        raise ValueError('Removed or modified hook cannot be distinguished')
                    continue
                if not engine._same(current, resource['installed']):
                    raise ValueError('Historical owned value changed')
                if _runtime(resource, context):
                    if runtime_safe is None:
                        try:
                            inventory = iterm.inspect(context, runner)
                            detached = isinstance(previous, Receipt) and all(
                                _runtime(other, context) or (external_writer(other) and
                                    engine._same(_observe(other, context, runner), other['installed']))
                                for other in all_resources)
                            if detached:
                                detached = not _active_runtime_references(
                                    result.resources, all_resources, context, runner, observations)
                            runtime_safe = detached and inventory.get('complete') is True and not inventory['sessions']
                            observations.append(('runtime_inventory', inventory))
                        except (ValueError, OSError, RuntimeError, KeyError):
                            runtime_safe = False
                            observations.append(('runtime_inventory', 'unavailable'))
                    if not runtime_safe:
                        pending['resources'].append(copy.deepcopy(original))
                        findings.append(_finding('legacy_runtime_deferred',
                            'Old immutable runtime is retained for persisted consumers, existing shells or incomplete inventory; retry explicit migration after references detach and old shells exit.',
                            'pending_ui'))
                        continue
                if _compatible_transfer(resource, context):
                    transferred = _transfer(resource)
                    state.validate_resources([transferred])
                    result.resources.append(transferred)
                    active[engine._identity(resource)] = transferred
                    findings.append(_finding('legacy_resource_transferred',
                        'Compatible shared resource transfers unchanged, preserving its GUID and original inverse.'))
                    continue
                _profile_cleanup(resource, context, runner)
                inverse = dict(copy.deepcopy(resource), before=resource['installed'], installed=resource['before'])
                identical = next((r for r in changes if engine._identity(r) == engine._identity(inverse)), None)
                if identical is not None and (not engine._same(identical['before'], inverse['before']) or
                                              not engine._same(identical['installed'], inverse['installed'])):
                    raise ValueError('Ambiguous historical ownership')
                if identical is None:
                    changes.append(inverse)
                findings.append(_finding('legacy_external_restore' if external_writer(resource) else 'legacy_resource_cleanup',
                    'Explicitly restore the recorded external writer value.' if external_writer(resource) else
                    'Restore only this unchanged receipt-owned storage address; neighbours remain untouched.'))
            except (ValueError, OSError, RuntimeError, KeyError, TypeError, AttributeError):
                pending['resources'].append(copy.deepcopy(original))
                observations.append(('unresolved', original))
                findings.append(_finding('legacy_mcp_unresolved' if original['kind'] == 'registration' else 'legacy_cleanup_conflict',
                    'Historical storage provenance or current value could not be verified; the original inverse remains retryable.',
                    'conflict'))
            finally:
                address = {'kind':original['kind'], 'target':original['target']}
                for key in ('pointer','name','key'):
                    if key in original['locator']:
                        address[key] = original['locator'][key]
                description = json.dumps(address, ensure_ascii=True, sort_keys=True)
                for finding in findings[first_finding:]:
                    finding.message += ' Address: '+description[:1024]
        # A full strict historical envelope retains source intent independently
        # of active selection, including old UI evidence until actual replacement.
        if pending['resources'] or (not bootstrap and not _intent_complete(pending, result.selection)):
            retained.append(pending)
        if raw['selection']['features'] and 'restore' in raw['selection']['features']:
            findings.append(_finding('legacy_restore_retired', 'Historical restore is retired; no old executable or dialog continuation is invoked.'))
    result.legacy_cleanup = retained
    state.validate(result)
    return previous, result, changes, findings, observations


def _prepare(context, runner, restore_external):
    if type(restore_external) is not bool:
        raise ValueError('Explicit external restoration choice required')
    jobs, findings, evidence = [], [], [('restore_external', restore_external)]
    for name, isolated in _scopes(context):
        for relative in ('receipt.json','journal/intent.json','journal/result.json','journal/phase'):
            evidence.append((name, relative, engine._bytes(isolated.paths.data/relative)))
        if (isolated.paths.data/'journal').exists():
            findings.append(_finding('migration_recovery_required',
                'Pending historical/current journal must recover before migration; preview never recovers it.', 'conflict'))
        previous, result, changes, notes, observations = _prepare_scope(
            isolated, runner, restore_external=restore_external, bootstrap=name != 'features')
        jobs.append((name, isolated, previous, result, changes))
        findings.extend(notes)
        evidence.append((name, previous, result, changes, observations))
        findings.append(_finding('migration_scope', 'Ownership inspected for '+name+'.'))
    def canonical(value):
        if is_dataclass(value):
            return canonical(asdict(value))
        if isinstance(value, dict):
            return {key:canonical(item) for key, item in value.items()}
        if isinstance(value, (set, frozenset)):
            return sorted(canonical(item) for item in value)
        if isinstance(value, (tuple, list)):
            return [canonical(item) for item in value]
        if isinstance(value, bytes):
            return {'sha256':hashlib.sha256(value).hexdigest()}
        if isinstance(value, Path):
            return str(value)
        return value
    digest = hashlib.sha256(json.dumps(canonical(evidence), sort_keys=True, allow_nan=False).encode()).hexdigest()
    return Plan(jobs[0][3].selection, ChangeSet([], [], findings), digest), jobs


def preview_omp_migration(context: Context, runner: Runner, *, restore_external: bool = False) -> Plan:
    """Pure storage preview: never creates locks, recovers journals or invokes agents."""
    try:
        return _prepare(context, runner, restore_external)[0]
    except (ValueError, OSError, RuntimeError, TypeError, KeyError):
        return Plan(_empty(context).selection, ChangeSet([], [], [_finding('migration_ownership_unavailable',
            'A receipt or storage address is invalid; no migration is authorized.', 'conflict')]), '')


def legacy_blockers(receipt, feature, context):
    """Retained historical writers must not gain a second conflicting consumer."""
    findings = []
    for raw in receipt.legacy_cleanup:
        for resource in raw['resources']:
            if external_writer(resource):
                try:
                    if engine._same(_observe(resource, context, None), resource['installed']):
                        continue  # Proven disabled, not merely recorded disabled.
                except (ValueError, OSError, RuntimeError, TypeError):
                    pass
            if _runtime(resource, context) and resource['kind'] == 'file':
                continue  # Immutable code is not an active writer.
            affected = _features(resource)
            if external_writer(resource):
                affected |= {'status','notifications','shell','appearance'}
            if resource['kind'] in {'hook','zsh'} and affected & {'status','notifications','restore'}:
                affected |= {'status','notifications','shell'}
            if _runtime(resource, context):
                affected |= {'shell','appearance'}
            if feature in affected:
                findings.append(_finding('legacy_writer_conflict',
                    'Retryable historical cleanup still owns a conflicting writer/address; independent omp checkpoints remain available.',
                    'conflict', feature))
    return findings


def _desired(receipt):
    features, shortcuts = set(receipt.selection.features), set(receipt.selection.shortcuts)
    for raw in receipt.legacy_cleanup:
        features.update(_intent_features(raw))
        if 'shortcuts' in _intent_features(raw):
            shortcuts.update(raw['selection']['shortcuts'])
    return replace(receipt.selection, features=frozenset(features), shortcuts=frozenset(shortcuts))


def migrate_to_omp(context: Context, runner: Runner, *, dry_run: bool = True, restore_external: bool = False) -> Outcome:
    """Recover first on apply, checkpoint exact cleanup, then invoke real builders."""
    preview = preview_omp_migration(context, runner, restore_external=restore_external)
    if dry_run:
        try:
            receipt = state.load(context.paths.data/'receipt.json') or _empty(context)
        except (ValueError, OSError):
            receipt = _empty(context)
        return Outcome(receipt, preview.changes.findings)
    findings = []
    try:
        with ExitStack() as locks:
            scopes = _scopes(context)
            for _, isolated in scopes:
                locks.enter_context(engine._lock(isolated))
            recovered = any((isolated.paths.data/'journal').exists() for _, isolated in scopes)
            for _, isolated in scopes:
                failures = engine._recover(isolated, runner)
                if failures:
                    return Outcome(state.load(context.paths.data/'receipt.json') or _empty(context), failures)
            # Recovery intentionally changes addresses/receipts. Obtain a new
            # pure preview only after it completes, then revalidate under locks.
            if recovered:
                preview = preview_omp_migration(context, runner, restore_external=restore_external)
            current, jobs = _prepare(context, runner, restore_external)
            if not preview.fingerprint or current.fingerprint != preview.fingerprint:
                return Outcome(state.load(context.paths.data/'receipt.json') or _empty(context),
                    [_finding('migration_stale_preview', 'Receipts or affected storage changed since preview; run migration again.', 'conflict')])
            findings.extend(current.changes.findings)
            for name, isolated, previous, result, changes in jobs:
                if previous is None or previous == result:
                    continue
                if state.load(isolated.paths.data/'receipt.json') != previous:
                    raise ValueError('Receipt changed during migration')
                source = previous if isinstance(previous, legacy_state.LegacyReceipt) else (
                    legacy_state.decode(previous.legacy_cleanup[0]) if changes and previous.legacy_cleanup else None)
                ok, failures = engine._transaction(changes, result, isolated, runner, intent_receipt=source)
                findings.extend(failures)
                if not ok:
                    return Outcome(state.load(context.paths.data/'receipt.json') or _empty(context), findings)
        from . import lifecycle
        receipt = state.load(context.paths.data/'receipt.json') or _empty(context)
        if isinstance(receipt, Receipt):
            desired = _desired(receipt)
            if desired != receipt.selection:
                installed = lifecycle.install(context, desired, runner)
                findings.extend(installed.findings)
                receipt = installed.receipt
            # Actual committed selection, never rewritten historical flags, is
            # the evidence for retiring source intent and superseded old UI.
            with engine._lock(context):
                stored = state.load(context.paths.data/'receipt.json')
                if (context.paths.data/'journal').exists():
                    return Outcome(stored or receipt, findings+[_finding('migration_recovery_required',
                        'A feature checkpoint left pending recovery; its durable intent is preserved before any migration bookkeeping.', 'conflict')])
                if stored is not None and isinstance(stored, Receipt):
                    trimmed = copy.deepcopy(stored)
                    trimmed.legacy_cleanup = [raw for raw in stored.legacy_cleanup
                        if raw['resources'] or not _intent_complete(raw, stored.selection)]
                    if trimmed != stored:
                        ok, failures = engine._transaction([], trimmed, context, runner)
                        findings.extend(failures)
                        receipt = trimmed if ok else stored
                    else:
                        receipt = stored
        pending = any(isinstance(stored := state.load(isolated.paths.data/'receipt.json'), Receipt) and stored.legacy_cleanup
                      for _, isolated in _scopes(context))
        findings.append(_finding('migration_cleanup_pending' if pending else 'migration_cleanup_complete',
            'Persisted cutover retains retryable/deferred cleanup or uninstalled source feature intent; existing processes were not restarted.'
            if pending else 'Receipt-authorized persisted cleanup completed; existing processes were not restarted.',
            'pending_ui' if pending else 'ready'))
        return Outcome(receipt, findings)
    except (ValueError, OSError, RuntimeError, TypeError, KeyError):
        try:
            receipt = state.load(context.paths.data/'receipt.json') or _empty(context)
        except (ValueError, OSError):
            receipt = _empty(context)
        return Outcome(receipt, findings+[_finding('migration_ownership_unavailable',
            'Migration could not verify ownership/recovery; no unverified cleanup is reported complete.', 'conflict')])
