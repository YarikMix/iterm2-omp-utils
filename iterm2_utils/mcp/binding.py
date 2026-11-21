"""Explicit installation identity; production authorization is supplied by the host."""
from dataclasses import dataclass
from pathlib import Path

from ..models import OmpProfile


@dataclass(frozen=True)
class McpBinding:
    profile: OmpProfile
    install_root: Path
    receipt_path: Path
    python: Path
