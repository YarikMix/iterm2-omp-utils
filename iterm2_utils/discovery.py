"""Bounded selected-feature inspection: no startup scripts, agents or config CLI."""
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
from pathlib import Path
from .commands import Runner
from .models import Context, Finding, OmpProfile, Paths
from .omp_profile import resolve_omp_profile


def resolve_paths() -> Paths:
    home = Path.home().absolute()
    def location(key, default):
        value = Path(os.environ.get(key,str(default))).expanduser()
        return value if value.is_absolute() else default
    return Paths(home,location('ZDOTDIR',home)/'.zshrc',
                 location('XDG_CONFIG_HOME',home/'.config')/'iterm2-utils',
                 location('XDG_CACHE_HOME',home/'.cache')/'iterm2-utils',
                 location('XDG_DATA_HOME',home/'.local/share')/'iterm2-utils',
                 home/'Library/Application Support/iTerm2/DynamicProfiles',
                 Path(__file__).resolve().parent.parent)


def _probe(runner, binary, args):
    try:
        result = runner.run([str(binary),*args],timeout=5)
        return result.stdout if result.returncode==0 else ''
    except (OSError,subprocess.SubprocessError,UnicodeError):
        return ''


def _version(output):
    match = re.search(r'(?<![\w.+-])\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)*(?![\w.+-])',output)
    return match.group() if match else 'unknown'


def _iterm(paths):
    override = os.environ.get('ITERM2_APP')
    candidates = [Path(override).expanduser()] if override else [
        Path('/Applications/iTerm.app'),paths.home/'Applications/iTerm.app']
    for app in candidates:
        if not app.is_absolute():
            continue
        try:
            info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
            name = info.get('CFBundleExecutable','iTerm2')
            if info.get('CFBundleIdentifier')!='com.googlecode.iterm2' or not isinstance(name,str) or Path(name).name!=name:
                continue
            binary = app/'Contents/MacOS'/name
            if binary.is_file() and os.access(binary,os.X_OK):
                return app,info
        except (OSError,ValueError,plistlib.InvalidFileException,AttributeError):
            continue
    return None,{}


def discover(paths: Paths, runner: Runner, *, features: frozenset[str] = frozenset(),
             omp_profile: OmpProfile | None = None) -> Context:
    """Probe selected dependencies, preserving supplied profile authority.

    Standalone discovery resolves ambient storage once when no selection was
    supplied; CLI callers pass their explicit or recorded profile unchanged.
    """
    executables,versions,capabilities = {},{},set()
    if platform.system()=='Darwin':
        capabilities.add('macos')
    names = {'zsh'}
    if features & {'status','notifications','restore'}:
        names.add('omp')
    if features & {'status','notifications','shortcuts'}:
        names.add('bun')
    if features & {'clipboard','shortcuts','appearance','restore','project-launcher'}:
        names.add('python3')
    if 'mcp' in features:
        names.add('uvx')
    for name in sorted(names):
        found = (os.environ.get('ITERM2_UTILS_PYTHON') or shutil.which(name)) if name=='python3' else shutil.which(name)
        if not found or not Path(found).is_absolute():
            continue
        binary = Path(found).absolute()
        output = _probe(runner,binary,['--version'])
        if not output:
            continue
        executables[name],versions[name] = binary,_version(output)
        if name=='omp':
            help_output = _probe(runner,binary,['--help'])
            if re.search(r'(?<![\w-])--resume(?![\w-])',help_output):
                capabilities.add('omp:resume')
        if name=='python3':
            if _probe(runner,binary,['-c','import iterm2; print("iterm2-sdk-ready")']).strip()=='iterm2-sdk-ready':
                capabilities.add('python:iterm2')
    app,info = _iterm(paths)
    if app:
        executables['iterm2'] = app
        versions['iterm2'] = _version(str(info.get('CFBundleShortVersionString','')))
        if features & {'status','notifications'}:
            it2 = app/'Contents/Resources/utilities/it2'
            if it2.is_file() and os.access(it2,os.X_OK) and not it2.is_symlink():
                output = _probe(runner,it2,['--help'])
                if output:
                    executables['it2'] = it2
                if 'get-status' in output:
                    capabilities.add('iterm2:session-status')
                # API availability or a version string does not prove an OSC
                # receiver. Only explicit advertised protocol support is credited;
                # otherwise the feature stays unverified, without hook fallback.
                for code in ('7501','9'):
                    if re.search(r'\bOSC[\s_-]+'+code+r'\b',output,re.I):
                        capabilities.add('iterm2:osc'+code)
    preferences,profiles = {},{}
    if app and features & {'clipboard','shortcuts','appearance','project-launcher'}:
        try:
            result = runner.run(['defaults','export','com.googlecode.iterm2','-'],timeout=5)
            values = plistlib.loads(result.stdout.encode()) if result.returncode==0 else {}
            preferences['com.googlecode.iterm2'] = {
                key:values[key] for key in ('CopySelection',) if key in values and type(values[key]) is bool}
            for profile in values.get('New Bookmarks',[]):
                if isinstance(profile,dict) and isinstance(profile.get('Name'),str):
                    profiles[profile['Name']] = profile
        except (OSError,ValueError,TypeError,AttributeError,plistlib.InvalidFileException,subprocess.SubprocessError):
            pass
    if features & {'clipboard','shortcuts','appearance','project-launcher'} and paths.profiles.is_dir():
        for path in sorted(paths.profiles.glob('*.json')):
            try:
                for profile in json.loads(path.read_bytes()).get('Profiles',[]):
                    if isinstance(profile,dict) and isinstance(profile.get('Name'),str):
                        profiles[profile['Name']] = profile
            except (OSError,ValueError,AttributeError,TypeError):
                continue
    return Context(paths,executables,versions,frozenset(capabilities),profiles,{},preferences,
                   omp_profile=omp_profile if omp_profile is not None else resolve_omp_profile(paths.home,dict(os.environ)))


def live_status(context: Context, runner: Runner, selection=None) -> list:
    """API readback is connectivity only, never native OSC delivery acceptance."""
    from runtime.terminal_identity import terminal_from_environment
    if selection is None or 'status' not in selection.features:
        return []
    terminal = terminal_from_environment(os.environ)
    ready = False
    if terminal and not os.environ.get('TMUX') and 'iterm2:session-status' in context.capabilities and 'it2' in context.executables:
        try:
            result = runner.run([str(context.executables['it2']),'session','get-status','--session',terminal],timeout=2)
            value = json.loads(result.stdout)
            ready = result.returncode==0 and isinstance(value,dict) and isinstance(value.get('status'),str) and value['status'] in {
                '','idle','working','blocked','waiting','done','error'}
        except (OSError,ValueError,subprocess.SubprocessError):
            pass
    return [Finding('status','omp','status_api','ready' if ready else 'pending_ui',
        'Explicit-session status API is reachable; native OSC 7501 event delivery remains unverified.' if ready else
        'Use an explicit consistent iTerm2 session address outside TMUX and authorize the native API.')]


def live_appearance(context, runner):
    """Read-only explicit-session access probe; never verifies rendered appearance."""
    ready = False
    if 'python:iterm2' in context.capabilities and 'python3' in context.executables:
        try:
            result = runner.run([str(context.executables['python3']),str(context.paths.data/'current/appearance.py'),'--probe'],timeout=5)
            ready = result.returncode==0 and result.stdout.strip()=='ready'
        except (OSError,subprocess.SubprocessError,UnicodeError):
            pass
    return Finding('appearance','omp','appearance_api','ready' if ready else 'pending_ui',
        'Explicit session API access verified; rendered color and icon remain unverified.' if ready else
        'Explicit session API access is not verified; authorize the Python API and retry in an explicit iTerm2 session.')
