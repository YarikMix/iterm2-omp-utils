"""Validate explicit choices and produce a read-only readiness preview."""
import hashlib
import json
import re
from dataclasses import replace

from .models import ChangeSet, Context, Finding, Plan, Selection, UiStep
from .legacy_state import LegacySelection, resource_pairs

AGENTS = frozenset({'codex', 'claude'})
FEATURES = frozenset({'clipboard', 'status', 'notifications', 'restore', 'mcp', 'shell', 'shortcuts', 'appearance', 'project-launcher'})
SHORTCUTS = frozenset({'ctrl-v-ru', 'alt-enter', 'ctrl-q', 'resume'})
CODEX_ONLY = frozenset({'clipboard', 'restore', 'appearance'})
DESCRIPTIONS = {
    'project-launcher': 'Explicit project buttons open a new shell tab in the same window.',
    'appearance': 'Codex-only repository tab color and icon; explicit session API verification remains pending.',
    'clipboard': 'Codex-only profile (&codex); tui.copy_on_select = "never"; shared iTerm2 CopySelection = false.',
    'status': 'Native cc-status for explicit tab UUIDs; Codex API error-event support is limited and reported separately.',
    'notifications': 'macOS notifications via terminal-notifier; separate from visible statuses.',
    'restore': 'Codex-only conversation chooser; never launches conversations without selection.',
    'mcp': 'Separate MCP runtime: mcp-server-iterm2==0.1.1, mcp<2. Gives access to terminal text.',
    'shell': 'Official zsh shell integration, restricted to iTerm2.',
    'shortcuts': 'Only explicitly selected shortcuts in agent profiles; ctrl-q can interrupt/exit.',
}


def validate(selection: LegacySelection, context: Context) -> list[Finding]:
    findings = []
    if isinstance(selection, Selection):
        return _omp_validate(selection, context)

    def add(feature, agent, code, state, message):
        findings.append(Finding(feature, agent, code, state, message))

    if not selection.agents or selection.agents - AGENTS:
        add('selection', None, 'invalid_agents', 'conflict', 'Select codex, claude or both.')
    if not selection.features or selection.features - FEATURES:
        add('selection', None, 'invalid_features', 'conflict', 'Choose at least one supported feature explicitly.')
    if (selection.shortcuts - SHORTCUTS or
            (selection.shortcuts and 'shortcuts' not in selection.features) or
            ('shortcuts' in selection.features and not selection.shortcuts)):
        add('shortcuts', None, 'invalid_shortcuts', 'conflict', 'Select supported shortcuts explicitly with the shortcuts feature.')
    if not selection.parent_profile.strip():
        add('selection', None, 'invalid_parent', 'conflict', 'A parent profile name is required.')
    for feature in sorted(selection.features & FEATURES):
        for agent in sorted(a for a in selection.agents & AGENTS if feature in selection.features_for(a)):
            if feature in CODEX_ONLY and agent != 'codex':
                add(feature, agent, 'codex_only', 'unavailable', 'This feature is supported only for Codex; Claude is unchanged.')
                continue
            dependencies = {'iterm2', 'zsh'}
            if feature not in {'shell','project-launcher'}:
                dependencies.add(agent)
            if feature in {'status', 'notifications', 'restore', 'mcp', 'appearance', 'project-launcher'}:
                dependencies.add('python3')
            if feature == 'notifications':
                dependencies.update({'terminal-notifier', 'it2', 'osascript'})
            missing = sorted(dependencies - context.executables.keys())
            if missing:
                add(feature, agent, 'missing_binary', 'missing_dependency', 'Required executables: ' + ', '.join(missing))
                continue
            if 'python3' in dependencies:
                version = re.fullmatch(r'(\d+)\.(\d+)(?:\.\d+)?', context.versions.get('python3', ''))
                if not version or tuple(map(int, version.groups())) < (3, 11):
                    add(feature, agent, 'python_version', 'missing_dependency', 'Select a verified runtime Python 3.11+ with ITERM2_UTILS_PYTHON; its version is missing or unsupported.')
                    continue
            if feature == 'appearance' and 'python:iterm2' not in context.capabilities:
                add(feature, agent, 'appearance_sdk', 'missing_dependency', 'The selected runtime Python must import iterm2; select an existing SDK interpreter with ITERM2_UTILS_PYTHON.')
                continue
            if 'macos' not in context.capabilities:
                add(feature, agent, 'unsupported_platform', 'unavailable', 'The first release supports macOS and zsh.')
                continue
            add(feature, agent, 'preview', 'ready', DESCRIPTIONS[feature])
            if feature == 'mcp':
                add(feature, agent, 'python_api', 'pending_ui', 'Verify iTerm2 Settings > General > Magic > Enable Python API; connection and authorization are not yet verified.')
            if feature == 'restore' and agent == 'codex' and 'codex:no-daemon' not in context.capabilities:
                add(feature, agent, 'no_daemon', 'unavailable', 'Codex --no-daemon capability was not detected; hook tab identity cannot be guaranteed.')
    from .discovery import native_status_findings
    findings.extend(native_status_findings(context, selection))
    return findings


def plan(context: Context, selection: LegacySelection) -> Plan:
    if isinstance(selection, Selection):
        return _omp_plan(context, selection)
    findings = validate(selection, context)
    from .features import profiles, shell, status, notifications, restore, mcp, appearance, project_launcher
    from . import migration
    supported = selection.features - CODEX_ONLY if 'codex' not in selection.agents else selection.features
    selected = replace(selection, features=frozenset(supported))
    payload = {'agents': sorted(selected.agents), 'features': sorted(selected.features),
               'shortcuts': sorted(selected.shortcuts), 'parent_profile': selected.parent_profile,
               'adopt_legacy': selected.adopt_legacy, 'agent_features': selected.agent_features,
               'agent_shortcuts': selected.agent_shortcuts, 'coexist_notifications': selected.coexist_notifications,
               'notification_coexist_agents': selected.notification_coexist_agents, 'versions': context.versions,
               'capabilities': sorted(context.capabilities)}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    changes = ChangeSet([], [], findings)
    # Legacy reuse keeps its shell path; native reuse still needs --no-daemon.
    reused = (context.installed.get('codex-status',{}).get('enabled')
              and not context.installed.get('codex-native-status') and not selected.adopt_legacy)
    runtime_selection = selected.without({'status'}, {'codex'}) if reused else selected
    for builder, choice in ((migration.build,selected),(restore.build,selected),(profiles.build,selected),
                            (shell.runtime_payload,runtime_selection),(shell.build,runtime_selection),
                            (status.build,selected),(notifications.build,selected),(mcp.build,selected),
                            (appearance.build,selected),(project_launcher.build,selected)):
        try:
            built = builder(context, choice)
            if selected.agent_features is not None:
                for edit in built.edits:
                    target = getattr(edit, 'path', getattr(edit, 'agent', ''))
                    if edit.owner.startswith('shared:'):
                        consumers = built.consumers[edit.owner]
                        if not any(':' in f for f in consumers):
                            built.consumers[edit.owner] = frozenset().union(*(
                                resource_pairs(selected, f, target, context, edit.owner) for f in consumers))
                    else:
                        pairs = resource_pairs(selected, edit.owner, target, context)
                        if len(pairs) != 1:
                            raise ValueError('Exclusive owner requires one consumer')
                        edit.owner = next(iter(pairs))
            changes.edits.extend(built.edits)
            changes.ui.extend(built.ui)
            changes.findings.extend(built.findings)
            changes.consumers.update(built.consumers)
        except (ValueError, OSError, KeyError, TypeError):
            affected = ({'shell','status','notifications','restore','appearance'} if builder in {shell.build,shell.runtime_payload} else
                        {'clipboard','shortcuts'} if builder == profiles.build else
                        {'status','notifications','restore'} if builder == status.build else
                        {'status','restore'} if builder == migration.build else
                        {'notifications'} if builder == notifications.build else
                        {'restore'} if builder == restore.build else
                        {'appearance'} if builder == appearance.build else
                        {'project-launcher'} if builder == project_launcher.build else {'mcp'})
            for feature in sorted(choice.features & affected):
                changes.findings.append(Finding(feature,None,'builder_conflict','conflict','A selected resource could not be safely prepared.'))
    if not selected.features & {'appearance','project-launcher'}:
        return Plan(selected, changes, fingerprint)
    from .models import FileEdit, ProfileBarEdit, StatusBarPositionEdit
    digest = hashlib.sha256(fingerprint.encode())
    for edit in changes.edits:
        if isinstance(edit, FileEdit):
            digest.update(str(edit.path).encode()+b'\0'+(edit.after or b'')+b'\0')
        elif isinstance(edit, (ProfileBarEdit, StatusBarPositionEdit)):
            digest.update(json.dumps(edit.__dict__,sort_keys=True).encode())
    return Plan(selected, changes, digest.hexdigest())


def _omp_validate(selection, context):
    from . import state
    try:
        state.validate_selection(selection)
    except ValueError:
        return [Finding('selection', 'omp', 'invalid_selection', 'conflict', 'Choose a valid omp profile and explicit selection.')]
    findings = []
    supported = FEATURES - {'restore'}
    if not selection.features or selection.features - supported:
        findings.append(Finding('selection', 'omp', 'invalid_features', 'conflict', 'Choose supported features explicitly.'))
    if (selection.shortcuts - SHORTCUTS or
            (selection.shortcuts and 'shortcuts' not in selection.features) or
            ('shortcuts' in selection.features and not selection.shortcuts)):
        findings.append(Finding('shortcuts', 'omp', 'invalid_shortcuts', 'conflict', 'Select supported shortcuts explicitly.'))
    for feature in sorted(selection.features & supported):
        dependencies = {'iterm2', 'zsh'}
        if feature not in {'shell', 'project-launcher', 'appearance'}:
            dependencies.add('omp')
        if feature in {'status', 'notifications', 'mcp', 'appearance', 'project-launcher'}:
            dependencies.add('python3')
        if feature == 'notifications':
            dependencies.update({'terminal-notifier', 'it2', 'osascript'})
        missing = sorted(dependencies - context.executables.keys())
        python = re.fullmatch(r'(\d+)\.(\d+)(?:\.\d+)?', context.versions.get('python3', ''))
        if missing:
            findings.append(Finding(feature, 'omp', 'missing_binary', 'missing_dependency', 'Required executables: '+', '.join(missing)))
        elif 'python3' in dependencies and (not python or tuple(map(int, python.groups())) < (3, 11)):
            findings.append(Finding(feature, 'omp', 'python_version', 'missing_dependency', 'Select a verified Python 3.11+ runtime.'))
        elif feature == 'appearance' and 'python:iterm2' not in context.capabilities:
            findings.append(Finding(feature, 'omp', 'appearance_sdk', 'missing_dependency', 'The selected Python must import the iTerm2 SDK.'))
        elif 'macos' not in context.capabilities:
            findings.append(Finding(feature, 'omp', 'unsupported_platform', 'unavailable', 'This package supports macOS and zsh.'))
        else:
            findings.append(Finding(feature, 'omp', 'preview', 'ready', 'Explicit selected feature is ready for planning.'))
    return findings


def _omp_plan(context, selection):
    """Build through the shared transaction contract, never an old-agent selection."""
    from .features import profiles, shell, status, notifications, mcp, appearance, project_launcher
    findings = _omp_validate(selection, context)
    changes = ChangeSet([], [], findings)
    builders = (
        (profiles.build, {'clipboard', 'shortcuts'}),
        (shell.runtime_payload, {'shell', 'status', 'notifications', 'appearance'}),
        (shell.build, {'shell', 'status', 'notifications', 'appearance'}),
        (status.build, {'status'}),
        (notifications.build, {'notifications'}),
        (mcp.build, {'mcp'}),
        (appearance.build, {'appearance'}),
        (project_launcher.build, {'project-launcher'}),
    )
    for builder, features in builders:
        if not selection.features & features:
            continue
        try:
            built = builder(context, selection)
            changes.edits.extend(built.edits)
            changes.ui.extend(built.ui)
            changes.findings.extend(built.findings)
            changes.consumers.update(built.consumers)
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            for feature in sorted(selection.features & features):
                changes.findings.append(Finding(feature, 'omp', 'builder_conflict', 'conflict',
                                               'A selected resource could not be safely prepared.'))
    payload = {'features': sorted(selection.features), 'shortcuts': sorted(selection.shortcuts),
               'parent_profile': selection.parent_profile,
               'omp_profile': {'name': selection.omp_profile.name, 'agent_dir': str(selection.omp_profile.agent_dir)},
               'resume_key': selection.resume_key, 'notify_errors': selection.notify_errors}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode())
    for edit in changes.edits:
        digest.update(repr(edit).encode())
    return Plan(selection, changes, digest.hexdigest())
