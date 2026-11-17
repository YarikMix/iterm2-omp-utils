"""Current receipt lifecycle; historical ownership requires explicit migration."""
import copy
import os
from dataclasses import replace
from . import engine, state
from .legacy_state import LegacyReceipt
from .models import ChangeSet, Finding, Outcome, Plan, Receipt, Selection
from .omp_profile import resolve_omp_profile
from .planner import FEATURES, plan, validate

BLOCKING = {'conflict', 'missing_dependency', 'unavailable'}
ORDER = ('shell', 'clipboard', 'shortcuts', 'status', 'notifications', 'restore', 'mcp', 'appearance', 'project-launcher')


def _empty(context):
    profile = context.omp_profile or resolve_omp_profile(context.paths.home, dict(os.environ))
    return Receipt(state.VERSION, Selection(frozenset(), frozenset(), 'Default', profile), [], [])


def _load(context):
    return state.load(context.paths.data/'receipt.json')


def _problem(context, receipt=None, code='ownership_unavailable', message='No valid ownership receipt is available.'):
    return Outcome(receipt or _empty(context), [Finding('selection', None, code, 'conflict', message)])


def _migration(context, receipt):
    return _problem(context, receipt, 'migration_required',
                    'Historical ownership requires explicit migration before current lifecycle operations.')


def _recover_pending(context, runner, dry_run):
    if dry_run or not (context.paths.data/'journal').exists():
        return None
    try:
        with engine._lock(context):
            findings = engine._recover(context, runner)
            if findings:
                return Outcome(_load(context) or _empty(context), findings)
    except (ValueError, OSError, RuntimeError):
        return _problem(context, code='recovery_unavailable',
                        message='Pending transaction recovery must finish before another mutation.')
    return None


def install(context, selection, runner, *, dry_run=False):
    recovery = _recover_pending(context, runner, dry_run)
    if recovery is not None:
        return recovery
    try:
        expected_receipt = _load(context)
        previous = expected_receipt
        if isinstance(previous, LegacyReceipt):
            return _migration(context, previous)
        if not isinstance(selection, Selection):
            return _migration(context, previous)
        state.validate_selection(selection)
        context = replace(context, omp_profile=selection.omp_profile)
        previous = previous or _empty(context)
    except (ValueError, OSError):
        return _problem(context)
    if previous.selection.features and (
            previous.selection.parent_profile != selection.parent_profile or
            previous.selection.omp_profile != selection.omp_profile):
        return _problem(context, previous, 'selection_conflict',
                        'Keep the recorded omp and parent profiles until their owned features are removed.')
    if context.project_launcher_config is not None and 'project-launcher' not in selection.features:
        return _problem(context, previous, 'project_launcher_config_selection',
                        'A project configuration requires an explicit project-launcher selection.')
    if context.appearance_config is not None and 'appearance' not in selection.features:
        return _problem(context, previous, 'appearance_config_selection',
                        'An appearance configuration requires an explicit appearance selection.')
    invalid = [f for f in validate(selection, context) if f.feature == 'selection' or f.code == 'invalid_shortcuts']
    if any(f.state in BLOCKING for f in invalid):
        return Outcome(previous, invalid)
    working, expected, findings = previous, expected_receipt, []
    for feature in ORDER:
        if feature not in selection.features:
            continue
        from .migration import legacy_blockers
        blocked = legacy_blockers(working, feature, context)
        if blocked:
            findings.extend(blocked)
            continue
        chosen = replace(selection, features=working.selection.features | {feature},
                         shortcuts=(working.selection.shortcuts | selection.shortcuts
                                    if feature == 'shortcuts' else working.selection.shortcuts),
                         resume_key=(selection.resume_key if feature=='shortcuts' and 'resume' in selection.shortcuts
                                     else working.selection.resume_key),
                         notify_errors=(selection.notify_errors if feature=='notifications'
                                        else working.selection.notify_errors))
        from .features.project_launcher import prepare
        prepared_context = prepare(context, chosen, runner)
        prepared = plan(prepared_context, chosen, runner=runner)
        prepared.changes.edits = [edit for edit in prepared.changes.edits
            if edit.owner in {feature, 'omp:'+feature} or
            feature in prepared.changes.consumers.get(edit.owner, ())]
        affected_shared = {edit.owner for edit in prepared.changes.edits if edit.owner.startswith('shared:')}
        for resource in working.resources:
            if set(resource['owners']) & {feature, 'omp:'+feature}:
                affected_shared.update(owner for owner in resource['owners'] if owner.startswith('shared:'))
        retained = {owner: set() for owner in affected_shared}
        for resource in working.resources:
            for owner in affected_shared & set(resource['owners']):
                retained[owner].update(consumer.removeprefix('omp:') for consumer in resource['owners']
                    if consumer.removeprefix('omp:') in working.selection.features)
        related = {feature, 'selection'}
        for edit in prepared.changes.edits:
            related.update(prepared.changes.consumers.get(edit.owner, ()))
        for consumers in retained.values():
            related.update(consumers)
        prepared.changes.findings = [f for f in prepared.changes.findings if f.feature in related]
        emitted = {edit.owner for edit in prepared.changes.edits}
        for owner, consumers in retained.items():
            if consumers and (owner not in emitted or not consumers <= prepared.changes.consumers.get(owner, frozenset())):
                prepared.changes.findings.append(Finding(feature, 'omp', 'recomposition_unavailable', 'conflict',
                    'A shared recomposition omitted a committed consumer; previous ownership is preserved.'))
        unchanged = all(edit.before == edit.after for edit in prepared.changes.edits)
        prepared.changes.ui = [step for step in prepared.changes.ui if step.feature == feature
            and not (unchanged and feature in working.selection.features
                     and step not in working.pending_ui)]
        for step in working.pending_ui:
            if step not in prepared.changes.ui:
                prepared.changes.ui.append(step)
        if any(f.state in BLOCKING for f in prepared.changes.findings):
            findings.extend(prepared.changes.findings)
            continue
        if dry_run:
            findings.extend(prepared.changes.findings)
            working = Receipt(state.VERSION, chosen, working.resources, prepared.changes.ui,
                              copy.deepcopy(working.legacy_cleanup))
            continue
        result = engine.apply(prepared, prepared_context, runner, expected_receipt=expected)
        findings.extend(result.findings)
        if not any(f.state in BLOCKING for f in result.findings):
            working = result.receipt
            expected = working
            pending = any(step.feature == feature for step in working.pending_ui)
            findings.append(Finding(feature, 'omp', 'feature_checkpoint', 'pending_ui' if pending else 'ready',
                                    'Resources committed; explicit UI verification remains pending.' if pending else 'Feature checkpoint committed.'))
        else:
            expected = _load(context)
            working = expected or working
    return Outcome(working, findings)


def update(context, runner, *, dry_run=False):
    recovery = _recover_pending(context, runner, dry_run)
    if recovery is not None:
        return recovery
    try:
        receipt = _load(context)
    except (ValueError, OSError):
        return _problem(context)
    if isinstance(receipt, LegacyReceipt):
        return _migration(context, receipt)
    if receipt is None:
        return _problem(context)
    if not receipt.selection.features:
        return Outcome(receipt, [])
    return install(context, receipt.selection, runner, dry_run=dry_run)


def uninstall(context, owners, runner, *, dry_run=False):
    recovery = _recover_pending(context, runner, dry_run)
    if recovery is not None:
        return recovery
    try:
        receipt = _load(context)
    except (ValueError, OSError):
        return _problem(context)
    if isinstance(receipt, LegacyReceipt):
        return _migration(context, receipt)
    if receipt is None:
        return _problem(context)
    context = replace(context, omp_profile=receipt.selection.omp_profile)
    if not owners or owners - FEATURES:
        return _problem(context, receipt, 'invalid_selection', 'Choose supported features explicitly.')
    selection = replace(receipt.selection, features=receipt.selection.features-owners,
                        shortcuts=frozenset() if 'shortcuts' in owners else receipt.selection.shortcuts,
                        resume_key=None if 'shortcuts' in owners else receipt.selection.resume_key,
                        notify_errors=False if 'notifications' in owners else receipt.selection.notify_errors)
    remove_owners = owners | frozenset('omp:'+feature for feature in owners)
    affected_shared = {owner for resource in receipt.resources
        if set(resource['owners']) & remove_owners
        for owner in resource['owners'] if owner.startswith('shared:')}
    from .features.project_launcher import prepare
    prepared_context = prepare(context, selection, runner)
    prepared = plan(prepared_context, selection, runner=runner) if selection.features else Plan(selection, ChangeSet([], [], []), 'uninstall')
    prepared.changes.edits = [edit for edit in prepared.changes.edits if edit.owner in affected_shared]
    retained = {owner: set() for owner in affected_shared}
    for resource in receipt.resources:
        for owner in affected_shared & set(resource['owners']):
            retained[owner].update(o.removeprefix('omp:') for o in resource['owners']
                                   if o.removeprefix('omp:') in selection.features)
    related = set().union(*retained.values()) if retained else set()
    prepared.changes.findings = [f for f in prepared.changes.findings if f.feature in related]
    emitted = {edit.owner for edit in prepared.changes.edits}
    for owner, consumers in retained.items():
        if consumers and owner not in emitted:
            prepared.changes.findings.append(Finding(sorted(consumers)[0], 'omp', 'recomposition_unavailable',
                'conflict', 'A retained shared resource could not be rebuilt; previous ownership is preserved.'))
    prepared.changes.ui = [step for step in receipt.pending_ui if step.feature not in owners]
    if dry_run:
        return Outcome(receipt, prepared.changes.findings + [
            Finding(feature, 'omp', 'uninstall_preview', 'ready', 'Only unchanged owned values will be removed.')
            for feature in sorted(owners)])
    result = engine.apply(prepared, prepared_context, runner, remove_owners=remove_owners, expected_receipt=receipt)
    if any(f.state in BLOCKING for f in result.findings):
        result.receipt = _load(context) or receipt
    return result


def reconcile_ui(context, code, runner):
    try:
        receipt = _load(context)
        if isinstance(receipt, LegacyReceipt):
            return _migration(context, receipt)
        if receipt is None:
            return _problem(context)
        with engine._lock(context):
            recovery = engine._recover(context, runner)
            receipt = _load(context)
            if isinstance(receipt, LegacyReceipt):
                return _migration(context, receipt)
            if receipt is None:
                return _problem(context)
            context = replace(context, omp_profile=receipt.selection.omp_profile)
            if recovery:
                return Outcome(receipt, recovery)
            steps = [step for step in receipt.pending_ui if step.code == code]
            if not steps:
                return _problem(context, receipt, 'unknown_ui_step', 'No such pending UI step exists in the receipt.')
            if code == 'appearance_api':
                from .discovery import live_appearance
                findings = [live_appearance(context, runner)]
            elif code in {'mcp_authorize', 'python_api'}:
                from .config import mcp
                findings = [mcp.probe(context, runner)]
            elif code in {'native_status','native_notifications','native_keyboard','native_restore'}:
                findings = [Finding(step.feature,'omp',code,'pending_ui',step.instruction) for step in steps]
            else:
                return _problem(context, receipt, 'unknown_ui_step', 'This pending step has no automatic verifier.')
            if any(f.state != 'ready' for f in findings):
                return Outcome(receipt, findings)
            result = copy.deepcopy(receipt)
            result.pending_ui = [step for step in result.pending_ui if step.code != code]
            ok, failed = engine._transaction([], result, context, runner)
            return Outcome(result if ok else receipt, findings+failed)
    except (ValueError, OSError, RuntimeError):
        try:
            receipt = _load(context)
        except (ValueError, OSError):
            receipt = None
        return _problem(context, receipt, 'ui_verification_failed',
                        'Verification was inconclusive; the UI step remains pending and was not retried.')


def doctor(context, receipt, runner):
    """Read-only ownership verification; no agent discovery or implicit recovery."""
    if isinstance(receipt, LegacyReceipt):
        return _migration(context, receipt).findings
    try:
        state.validate(receipt)
    except (ValueError, TypeError):
        return _problem(context).findings
    context = replace(context, omp_profile=receipt.selection.omp_profile)
    findings = ([f for f in validate(receipt.selection, context) if f.state in BLOCKING or f.state == 'limited']
                if receipt.selection.features else [])
    for resource in receipt.resources:
        owner = next((o for o in resource['owners'] if not o.startswith('shared:')), 'selection')
        feature = owner.removeprefix('omp:')
        try:
            current = engine._read(resource, runner, context)
            if not engine._same(current, resource['installed']):
                missing = resource['installed']['exists'] and not current['exists']
                findings.append(Finding(feature, 'omp', 'owned_resource_missing' if missing else 'owned_resource_changed',
                                        'conflict', 'An owned selected resource is missing or differs from its receipt.'))
        except (OSError, ValueError, TypeError, RuntimeError):
            findings.append(Finding(feature, 'omp', 'resource_unavailable', 'unavailable',
                                    'An owned selected resource could not be inspected.'))
    if 'mcp' in receipt.selection.features:
        from .config import mcp
        try:
            actual = mcp.read_server(context.omp_profile, runner)
            if not engine._same(actual, {'exists':True, 'value':mcp.definition()}):
                findings.append(Finding('mcp', 'omp', 'registration_missing' if not actual['exists'] else 'registration_changed',
                                        'conflict', 'Selected MCP server entry is missing or differs from the pinned definition.'))
        except (ValueError, OSError, RuntimeError):
            findings.append(Finding('mcp', 'omp', 'registration_unavailable', 'unavailable',
                                    'Selected MCP server entry could not be verified.'))
    return findings
