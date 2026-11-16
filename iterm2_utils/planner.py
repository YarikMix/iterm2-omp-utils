"""Validate explicit choices and produce a read-only readiness preview."""
import hashlib
import json
import re

from .models import ChangeSet, Context, Finding, Plan, Selection
from .legacy_state import LegacySelection

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


def plan(context: Context, selection: Selection) -> Plan:
    if not isinstance(selection, Selection):
        raise ValueError('Historical feature selections require explicit owned-resource migration')
    return _omp_plan(context, selection)


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
