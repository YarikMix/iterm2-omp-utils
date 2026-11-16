"""Self-contained skill copies, owned separately from feature installation.

A bootstrap never probes or installs an agent and never selects terminal features.
The regular CAS transaction engine maintains its own bootstrap receipt.
"""
import base64
from dataclasses import replace
from . import engine, state
from .models import ChangeSet, Context, FileEdit, Finding, Plan, Selection
from .legacy_state import LegacyReceipt
from .omp_profile import resolve_omp_profile

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


def _destination(context, skill):
    profile = context.omp_profile or resolve_omp_profile(context.paths.home, {})
    return profile.agent_dir/'skills'/skill


def _conflict(agent, code, message):
    return Finding('skill', agent, code, 'conflict', message)


def build(context: Context, *, skill='iterm2-setup') -> ChangeSet:
    """Prepare selected destinations only; existing foreign directories are refused."""
    changes = ChangeSet([], [], [])
    if skill not in BUNDLES:
        changes.findings.append(_conflict(None, 'invalid_skill', 'Select iterm2-setup, iterm2-launch or iterm2-projects.'))
        return changes
    try:
        receipt = state.load(_context(context, skill).paths.data/'receipt.json')
        if isinstance(receipt, LegacyReceipt):
            changes.findings.append(_conflict(None, 'migration_required',
                'Migrate this independent historical bootstrap receipt before copying current omp skills.'))
            return changes
        if receipt is not None and receipt.legacy_cleanup:
            changes.findings.append(_conflict(None, 'migration_required',
                'Resolve this bootstrap receipt’s historical cleanup before replacing its owned bundle.'))
            return changes
        owned = {r['target']: r['installed'] for r in receipt.resources
                 if r['kind'] == 'file' and r['owners'] == [OWNER]} if receipt else {}
        source = context.paths.repo/'skills'/skill
        payload = {}
        for name in BUNDLES[skill]:
            path = source/name
            if path.is_symlink() or not path.is_file():
                raise ValueError('Invalid public skill bundle')
            payload[name] = path.read_bytes()
        destination = _destination(context, skill)
        if destination.is_symlink() or (destination.exists() and
                (not destination.is_dir() or str((destination/'SKILL.md').resolve()) not in owned)):
            changes.findings.append(_conflict('omp', 'foreign_skill',
                f'Existing {skill} path is not owned by this bootstrap; preserve it and choose a resolution.'))
            return changes
        for name, content in payload.items():
            path = destination/name
            if path.resolve() != path or any(parent.is_symlink() for parent in path.parents):
                raise ValueError('Invalid skill symlink')
            before = path.read_bytes() if path.exists() else None
            installed = owned.get(str(path))
            if installed is not None:
                expected = base64.b64decode(installed['value'], validate=True) if installed['exists'] else None
                if before != expected:
                    raise ValueError('User-changed skill file')
            elif before is not None:
                raise ValueError('Foreign skill file')
            changes.edits.append(FileEdit(path, before, content, 0o644, OWNER))
        changes.findings.append(Finding('skill', 'omp', 'skill_prepared', 'ready',
            'Self-contained skill prepared for the selected omp profile; terminal features and agent binaries are unchanged.'))
    except (ValueError, OSError, TypeError, KeyError):
        changes.edits.clear()
        changes.findings.append(_conflict(None, 'skill_ownership_unavailable', 'Skill bundle or bootstrap ownership could not be verified; no copy was prepared.'))
    return changes


def install(context, runner, *, dry_run=False, skill='iterm2-setup') -> list[Finding]:
    """Apply a profile-scoped skill transaction without selecting terminal features."""
    if skill not in BUNDLES:
        return build(context, skill=skill).findings
    isolated = _context(context, skill)
    if not dry_run and (isolated.paths.data/'journal').exists():
        try:
            with engine._lock(isolated):
                failures = engine._recover(isolated, runner)
                if failures:
                    return failures
        except (ValueError, OSError, RuntimeError):
            return [_conflict(None, 'skill_recovery_unavailable', 'Bootstrap recovery must finish before copying.')]
    changes = build(context, skill=skill)
    if dry_run or any(f.state == 'conflict' for f in changes.findings):
        return changes.findings
    try:
        receipt = state.load(isolated.paths.data/'receipt.json')
        profile = context.omp_profile or resolve_omp_profile(context.paths.home, {})
        if receipt is not None and receipt.selection.omp_profile != profile:
            return [_conflict(None, 'skill_profile_conflict',
                'Keep the recorded omp profile until its owned skill copy is explicitly removed.')]
    except (ValueError, OSError):
        return [_conflict(None, 'skill_ownership_unavailable', 'Bootstrap ownership is unavailable.')]
    selection = Selection(frozenset({OWNER}), frozenset(), 'Default', profile)
    return engine.apply(Plan(selection, changes, 'skill-bootstrap'), isolated, runner,
                        expected_receipt=receipt).findings
