"""Self-contained skill copies, owned separately from feature installation.

A bootstrap never probes or installs an agent and never selects terminal features.
The regular CAS transaction engine maintains its own bootstrap receipt.
"""
import base64
import os
import re
from dataclasses import replace
from pathlib import Path
from . import engine, state
from .models import ChangeSet, Context, FileEdit, Finding, Plan, Selection

AGENTS = frozenset({'codex', 'claude', 'omp'})
OWNER = 'bootstrap-skill'
FILES = ('SKILL.md', 'references/features.md', 'references/ui.md', 'references/troubleshooting.md')
BUNDLES = {
    'iterm2-setup': FILES,
    'iterm2-launch': ('SKILL.md', 'references/handoff.md', 'references/resume.md'),
    'iterm2-projects': ('SKILL.md', 'references/projects.md'),
}


def _context(context, skill):
    receipt = OWNER if skill == 'iterm2-setup' else OWNER+'-'+skill
    return replace(context, paths=replace(context.paths, data=context.paths.data/receipt))


def _omp_agent_dir(home: Path) -> Path:
    """Match omp's macOS profile/env directories without inspecting its settings."""
    profile = os.environ.get('OMP_PROFILE', os.environ.get('PI_PROFILE', '')).strip()
    if profile == 'default':
        profile = ''
    if profile and (not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', profile)
                    or profile.endswith('.')
                    or re.fullmatch(r'(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?', profile)):
        raise ValueError('Invalid omp profile')
    config = os.environ.get('PI_CONFIG_DIR') or '.omp'
    # Node path.join(home, config) prefixes even an absolute-looking config value.
    root = Path(os.path.normpath(str(home) + '/' + config))
    if profile:
        return root/'profiles'/profile/'agent'
    override = os.environ.get('PI_CODING_AGENT_DIR')
    return Path(os.path.abspath(override)) if override else root/'agent'


def _destination(context, agent, skill):
    if agent == 'codex':
        root = context.paths.codex_home
    elif agent == 'claude':
        root = context.paths.home/'.claude'
    elif agent == 'omp':
        root = _omp_agent_dir(context.paths.home)
    else:
        raise ValueError('Invalid skill host')
    return root/'skills'/skill


def _conflict(agent, code, message):
    return Finding('skill', agent, code, 'conflict', message)


def build(context: Context, agents: frozenset[str], *, skill='iterm2-setup') -> ChangeSet:
    """Prepare selected destinations only; existing foreign directories are refused."""
    changes = ChangeSet([], [], [])
    if skill not in BUNDLES:
        changes.findings.append(_conflict(None, 'invalid_skill', 'Select iterm2-setup, iterm2-launch or iterm2-projects.'))
        return changes
    if not agents or agents - AGENTS:
        changes.findings.append(_conflict(None, 'invalid_agents', 'Select codex, claude, omp or both (codex and claude).'))
        return changes
    if skill == 'iterm2-launch' and agents not in (frozenset({'codex'}), frozenset({'omp'})):
        changes.findings.append(_conflict(None, 'invalid_agents', 'Select codex or omp as host for the Codex launch skill.'))
        return changes
    try:
        receipt = state.load(_context(context, skill).paths.data/'receipt.json')
        owned = {r['target']: r['installed'] for r in receipt.resources
                 if r['kind'] == 'file' and r['owners'] == [OWNER]} if receipt else {}
        source = context.paths.repo/'skills'/skill
        payload = {}
        for name in BUNDLES[skill]:
            path = source/name
            if path.is_symlink() or not path.is_file():
                raise ValueError('Invalid public skill bundle')
            payload[name] = path.read_bytes()
        for agent in sorted(agents):
            destination = _destination(context, agent, skill)
            if destination.is_symlink() or (destination.exists() and
                    (not destination.is_dir() or str((destination/'SKILL.md').resolve()) not in owned)):
                changes.findings.append(_conflict(agent, 'foreign_skill', f'Existing {skill} path is not owned by this bootstrap; preserve it and choose a resolution.'))
                continue
            edits = []
            for name, content in payload.items():
                path = destination/name
                # Do not follow an injected references directory or file symlink.
                if path.is_symlink() or (path.parent != destination and path.parent.is_symlink()):
                    raise ValueError('Invalid skill symlink')
                before = path.read_bytes() if path.exists() else None
                installed = owned.get(str(path.resolve()))
                if installed is not None:
                    expected = base64.b64decode(installed['value']) if installed['exists'] else None
                    if before != expected:
                        raise ValueError('User-changed skill file')
                elif before is not None:
                    raise ValueError('Foreign skill file')
                edits.append(FileEdit(path, before, content, 0o644, OWNER))
            changes.edits.extend(edits)
            changes.findings.append(Finding('skill', agent, 'skill_prepared', 'ready',
                'Self-contained skill prepared; terminal features and agent binaries are unchanged.'))
    except (ValueError, OSError, TypeError, KeyError):
        changes.edits.clear()
        changes.findings.append(_conflict(None, 'skill_ownership_unavailable', 'Skill bundle or bootstrap ownership could not be verified; no copy was prepared.'))
    return changes


def install(context, agents, runner, *, dry_run=False, skill='iterm2-setup') -> list[Finding]:
    """Apply a skill-only transaction without touching the feature receipt."""
    changes = build(context, agents, skill=skill)
    if dry_run or any(f.state == 'conflict' for f in changes.findings):
        return changes.findings
    isolated = _context(context, skill)
    try:
        receipt = state.load(isolated.paths.data/'receipt.json')
        selected = agents | (receipt.selection.agents if receipt else frozenset())
    except (ValueError, OSError):
        return [_conflict(None, 'skill_ownership_unavailable', 'Bootstrap ownership is unavailable.')]
    selection = Selection(selected, frozenset({OWNER}), frozenset(), 'Default')
    result = engine.apply(Plan(selection, changes, 'skill-bootstrap'), isolated, runner, expected_receipt=receipt)
    return result.findings
