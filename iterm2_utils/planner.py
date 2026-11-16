"""Validate explicit omp features and compose existing transactional builders."""
import hashlib
import json
import re
from dataclasses import replace
from . import state
from .models import ChangeSet, Context, Finding, Plan, Selection

FEATURES = frozenset({'clipboard', 'status', 'notifications', 'restore', 'mcp', 'shell', 'shortcuts', 'appearance', 'project-launcher'})
SHORTCUTS = frozenset({'ctrl-v-ru', 'alt-enter', 'ctrl-q', 'resume'})
BLOCKING = frozenset({'conflict','missing_dependency','unavailable'})
DESCRIPTIONS = {
    'clipboard': 'Terminal selection and Cmd+C; selected CopySelection only.',
    'shortcuts': 'Selected RU paste/newline normalization and native resume; Ctrl+C and Ctrl+Q remain native.',
    'status': 'Native omp terminal.programStatus (OSC 7501); no second event writer.',
    'notifications': 'Native completion-on/error-off policy (OSC 9); errors require explicit opt-in.',
    'restore': 'Native picker and exact-file resume; no shell dispatcher.',
    'mcp': 'Optional pinned observe server in the selected omp profile.',
    'shell': 'Official zsh shell integration, restricted to iTerm2.',
    'appearance': 'Retained repository appearance; explicit-session API and visual acceptance remain separate.',
    'project-launcher': 'Explicit project buttons open shell tabs, never implicitly launch omp.',
}


def validate(selection: Selection, context: Context) -> list[Finding]:
    try:
        state.validate_selection(selection)
    except ValueError:
        return [Finding('selection','omp','invalid_selection','conflict','Choose a valid omp profile and explicit selection.')]
    findings = []
    def add(feature, code, status, message):
        findings.append(Finding(feature,'omp',code,status,message))
    if selection.features-FEATURES:
        add('selection','invalid_features','conflict','Choose supported features explicitly.')
    if (selection.shortcuts-SHORTCUTS or selection.shortcuts and 'shortcuts' not in selection.features or
            'shortcuts' in selection.features and not selection.shortcuts):
        add('shortcuts','invalid_shortcuts','conflict','Select supported shortcuts explicitly.')
    if 'resume' in selection.shortcuts and not selection.resume_key:
        add('shortcuts','resume_key_required','conflict','Use --resume-key to choose a native app.session.resume binding.')
    if selection.resume_key:
        from .features.profiles import resume_key_conflict
        if resume_key_conflict(selection.resume_key):
            add('shortcuts','resume_key_conflict','conflict','Choose an unused native resume chord; core input is preserved.')
    if selection.resume_key and 'resume' not in selection.shortcuts:
        add('shortcuts','resume_key_selection','conflict','A resume key requires the explicit resume shortcut.')
    if selection.notify_errors and 'notifications' not in selection.features:
        add('notifications','notify_errors_selection','conflict','Error notifications require selecting notifications.')
    for feature in sorted(selection.features & FEATURES):
        dependencies = {'iterm2','zsh'}
        if feature in {'status','notifications','restore'}:
            dependencies.add('omp')
        if feature in {'status','notifications'} or feature=='shortcuts' and selection.shortcuts-{'ctrl-q'}:
            dependencies.add('bun')
        if feature in {'appearance','project-launcher'}:
            dependencies.add('python3')
        if feature=='mcp':
            dependencies.add('uvx')
        missing = sorted(dependencies-context.executables.keys())
        if missing:
            add(feature,'missing_binary','missing_dependency','Required executables: '+', '.join(missing))
            continue
        if 'macos' not in context.capabilities:
            add(feature,'unsupported_platform','unavailable','This package supports macOS and zsh.')
            continue
        if 'python3' in dependencies:
            version = re.fullmatch(r'(\d+)\.(\d+)(?:\.\d+)?',context.versions.get('python3',''))
            if not version or tuple(map(int,version.groups())) < (3,11):
                add(feature,'python_version','missing_dependency','Select Python 3.11+ explicitly.')
                continue
            if 'python:iterm2' not in context.capabilities:
                add(feature,'python_sdk','missing_dependency','The selected Python must import the iTerm2 SDK.')
                continue
        capability = {'status':'iterm2:osc7501','notifications':'iterm2:osc9','restore':'omp:resume'}.get(feature)
        if capability and capability not in context.capabilities:
            add(feature,'native_capability','unavailable','Required native surface is unverified: '+capability+'. No hook fallback is installed.')
            continue
        add(feature,'preview','ready',DESCRIPTIONS[feature])
    return findings


def plan(context: Context, selection: Selection) -> Plan:
    if not isinstance(selection,Selection):
        raise ValueError('Historical feature selections require explicit owned-resource migration')
    from .features import profiles, shell, status, notifications, restore, mcp, appearance, project_launcher
    findings = validate(selection,context)
    changes = ChangeSet([],[],findings)
    blocked = {f.feature for f in findings if f.state in BLOCKING}
    available = selection.features-blocked if 'selection' not in blocked else frozenset()
    effective = replace(selection,features=available,
                        shortcuts=selection.shortcuts if 'shortcuts' in available else frozenset())
    builders = (
        (profiles.build,{'clipboard','shortcuts'}),
        (shell.runtime_payload,{'shell','appearance'}),
        (shell.build,{'shell','appearance'}),
        (status.build,{'status'}), (notifications.build,{'notifications'}),
        (restore.build,{'restore'}), (mcp.build,{'mcp'}),
        (appearance.build,{'appearance'}), (project_launcher.build,{'project-launcher'}),
    )
    for builder,features in builders:
        if not available & features:
            continue
        try:
            built = builder(context,effective)
            changes.edits.extend(built.edits)
            changes.ui.extend(built.ui)
            changes.findings.extend(built.findings)
            changes.consumers.update(built.consumers)
        except (ValueError,OSError,KeyError,TypeError,AttributeError):
            for feature in sorted(available & features):
                changes.findings.append(Finding(feature,'omp','builder_conflict','conflict',
                    'A selected resource or its retained runtime dependency could not be safely prepared.'))
    payload = {'features':sorted(selection.features),'shortcuts':sorted(selection.shortcuts),
               'parent_profile':selection.parent_profile,
               'omp_profile':{'name':selection.omp_profile.name,'agent_dir':str(selection.omp_profile.agent_dir)},
               'resume_key':selection.resume_key,'notify_errors':selection.notify_errors}
    digest = hashlib.sha256(json.dumps(payload,sort_keys=True).encode())
    for edit in changes.edits:
        digest.update(repr(edit).encode())
    return Plan(selection,changes,digest.hexdigest())
