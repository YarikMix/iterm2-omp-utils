"""Retained native shell/appearance payloads, described without applying writes."""
import hashlib
import json
import os
import re
import shlex
from pathlib import Path
from .. import __version__
from ..config import zshrc
from ..models import ChangeSet, Context, FileEdit, SymlinkEdit, Finding, Selection

OWNER = 'shared:shell'
RUNTIME_OWNER = 'shared:runtime'
DEPENDENTS = frozenset({'shell', 'appearance'})
APPEARANCE_ASSETS = tuple(Path('assets/appearance') / (name + '.' + extension)
                          for name in ('ios', 'android', 'kotlett', 'ios-mail', 'ios-cloud',
                                       'android-mail', 'android-cloud', 'chrome-mail', 'chrome-cloud')
                          for extension in ('png', 'svg'))
# Deliberately do not flatten omp_config.ts: its ../vendor import is contractual.
BASE_PAYLOAD = {
    'runtime/omp_config.ts': 'runtime/omp_config.ts',
    'vendor/shell_integration/iterm2_shell_integration.zsh': 'vendor/shell_integration/iterm2_shell_integration.zsh',
    'vendor/shell_integration/LICENSE': 'vendor/shell_integration/LICENSE',
    'LICENSE': 'LICENSE', 'THIRD_PARTY_NOTICES.md': 'THIRD_PARTY_NOTICES.md',
}
APPEARANCE_PAYLOAD = {
    'runtime/appearance.py': 'appearance.py',
    'runtime/appearance.zsh': 'appearance.zsh',
    'runtime/terminal_identity.py': 'terminal_identity.py',
    'runtime/omp_identity.ts': 'runtime/omp_identity.ts',
}


def _source(repo, relative):
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe runtime source')
    source = repo/relative
    if any((repo/part).is_symlink() for part in (relative, *relative.parents)):
        raise ValueError('Unsafe runtime source symlink')
    if not source.is_file():
        raise ValueError('Missing runtime source dependency')
    return source.read_bytes()


def runtime_payload(context: Context, selection: Selection) -> ChangeSet:
    changes = ChangeSet([], [], [])
    consumers = selection.features & DEPENDENTS
    if not consumers:
        return changes
    repo = context.paths.repo
    files = {Path(target): _source(repo,Path(source)) for source,target in BASE_PAYLOAD.items()}
    # The committed provenance manifest is an explicit file allowlist, never a
    # recursive copy of runtime/vendor trees containing retired consumers.
    manifest = json.loads(_source(repo,Path('sources.lock.json')))
    yaml = [entry for entry in manifest['sources'] if entry['path'].startswith('vendor/yaml/')]
    if not yaml or not any(entry['path']=='vendor/yaml/dist/index.js' for entry in yaml):
        raise ValueError('Missing YAML payload manifest')
    for entry in yaml:
        relative = Path(entry['path'])
        content = _source(repo,relative)
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError('Runtime parser provenance changed')
        files[relative] = content
    if 'appearance' in consumers:
        files.update({Path(target):_source(repo,Path(source)) for source,target in APPEARANCE_PAYLOAD.items()})
        files.update({relative:_source(repo,Path('runtime')/relative) for relative in APPEARANCE_ASSETS})
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(str(name).encode()+b'\0'+content+b'\0')
    release = context.paths.data/'releases'/(__version__+'-'+digest.hexdigest()[:20])
    for name, content in sorted(files.items()):
        path = release/name
        before = path.read_bytes() if path.exists() else None
        if before is not None and before != content:
            raise ValueError('Immutable release content changed')
        changes.edits.append(FileEdit(path,before,content,0o600,RUNTIME_OWNER))
    current = context.paths.data/'current'
    if current.exists() and not current.is_symlink():
        raise ValueError('Runtime current must be a symlink')
    changes.edits.append(SymlinkEdit(current,os.readlink(current) if current.is_symlink() else None,str(release),RUNTIME_OWNER))
    changes.consumers[RUNTIME_OWNER] = frozenset(consumers)
    return changes


def build(context: Context, selection: Selection) -> ChangeSet:
    changes = ChangeSet([], [], [])
    consumers = selection.features & DEPENDENTS
    if not consumers:
        return changes
    path = context.paths.zshrc
    before = path.read_bytes() if path.exists() else None
    try:
        base = before or b''
        managed = zshrc.blocks(base)
        foreign = base
        for name in managed:
            foreign = zshrc.block(foreign,name,None)
        text = foreign.decode()
        reuse = 'shell' in consumers and bool(re.search(
            r'(?m)^\s*(?:source|\.)\s+[^\n]*iterm2_shell_integration',text))
        lines = []
        current = context.paths.data/'current'
        quote = lambda value: shlex.quote(str(value))
        if 'shell' in consumers and not reuse:
            lines.extend(['if [[ ${TERM_PROGRAM-} == iTerm.app && -z ${ITERM_SHELL_INTEGRATION_INSTALLED-} ]]; then',
                          '  source '+quote(current/'vendor/shell_integration/iterm2_shell_integration.zsh'),'fi'])
        if reuse:
            changes.findings.append(Finding('shell',None,'existing_integration','ready',
                                            'Existing shell integration is reused without ownership.'))
        if 'appearance' in consumers:
            lines.extend(['typeset -g ITERM2_UTILS_PYTHON='+quote(context.executables['python3']),
                          'typeset -g ITERM2_UTILS_APPEARANCE_CONFIG='+quote(context.paths.config/'appearance.json'),
                          'source '+quote(current/'appearance.zsh')])
        if lines or 'root' in managed:
            changes.edits.append(FileEdit(path,before,zshrc.block(base,'root','\n'.join(lines) if lines else None),0o600,OWNER))
            changes.consumers[OWNER] = frozenset(consumers)
    except (ValueError, UnicodeError):
        for feature in sorted(consumers):
            changes.findings.append(Finding(feature,None,'shell_conflict','conflict',
                'Shell startup contains malformed managed integration; explicit repair is required.'))
    return changes
