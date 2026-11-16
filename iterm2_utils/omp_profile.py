"""Pure omp profile paths, matching the existing omp-bootstrap/Node semantics."""
import os
import re
from pathlib import Path
from .models import OmpProfile


def profile_name(value: str) -> str | None:
    name = value.strip()
    if not name or name == 'default':
        return None
    if (not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', name) or name.endswith('.') or
            re.fullmatch(r'(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?', name)):
        raise ValueError('Invalid omp profile')
    return name


def resolve_omp_profile(home: Path, env: dict[str, str], explicit: str | None = None) -> OmpProfile:
    """Resolve without reading settings, expanding '~', creating paths or probing omp.

    PI_CONFIG_DIR follows Node path.join(home, config), including an absolute-looking
    config component. Only the default profile honors PI_CODING_AGENT_DIR; relative
    agent-directory overrides follow omp's process cwd, not HOME.
    """
    name = profile_name(explicit if explicit is not None else env.get('OMP_PROFILE', env.get('PI_PROFILE', '')))
    config = env.get('PI_CONFIG_DIR') or '.omp'
    base = Path(os.path.normpath(str(home) + '/' + config))
    if name is not None:
        return OmpProfile(name, base/'profiles'/name/'agent')
    override = env.get('PI_CODING_AGENT_DIR')
    return OmpProfile(None, Path(os.path.abspath(override)) if override else base/'agent')
