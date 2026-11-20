"""Pure opt-in native omp MCP configuration."""
from ..config.mcp import server_edit
from ..models import ChangeSet, Context, Selection, UiStep


def build(context: Context, selection: Selection) -> ChangeSet:
    changes = ChangeSet([], [], [])
    if 'mcp' not in selection.features:
        return changes
    changes.edits.append(server_edit(selection.omp_profile))
    changes.ui.append(UiStep('mcp_authorize', 'mcp', 'omp',
        'Enable iTerm2 Python API and authorize the pinned observe server; '
        'start a fresh selected-profile omp session and run the live MCP connection probe. '
        'uvx may fetch its separate Python >=3.12 runtime.'))
    return changes
