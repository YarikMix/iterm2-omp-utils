"""Isolated entry: all authority comes from installer argv and this release."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def main():
    import argparse
    from iterm2_utils.config.mcp import authorize_binding
    from iterm2_utils.mcp.binding import McpBinding
    from iterm2_utils.models import OmpProfile
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-worker', action='store_true')
    parser.add_argument('--omp-profile', required=True)
    parser.add_argument('--receipt', required=True)
    args = parser.parse_args()
    profile, receipt = Path(args.omp_profile), Path(args.receipt)
    if not profile.is_absolute() or not receipt.is_absolute():
        return 2
    # Profile name is persisted authority, never ambient OMP_PROFILE.
    from iterm2_utils.project_edits import read_receipt
    try:
        _, saved = read_receipt(receipt)
        name = saved.selection.omp_profile.name
    except (OSError, ValueError):
        name = None
    binding = McpBinding(OmpProfile(name, profile), ROOT, receipt, Path(sys.executable).absolute())
    if args.project_worker:
        from iterm2_utils.mcp.project_worker import main as worker
        return worker(binding, authorize=lambda: authorize_binding(binding))
    from iterm2_utils.mcp.__main__ import main as stdio
    async def authorize():
        authorize_binding(binding)
    return stdio(binding, authorize=authorize)


if __name__ == '__main__':
    raise SystemExit(main())
