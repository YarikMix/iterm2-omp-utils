"""Select omp's native OSC 7501 writer, never a lifecycle hook."""
from ..config import omp
from ..models import ChangeSet, Context, Selection, UiStep


def build(context: Context, selection: Selection, *, runner) -> ChangeSet:
    changes = ChangeSet([], [], [])
    if 'status' not in selection.features:
        return changes
    changes.edits.append(omp.setting_edit(selection.omp_profile, 'terminal.programStatus',
        {'exists': True, 'value': True}, runner, owner='status'))
    changes.ui.append(UiStep('native_status', 'status', 'omp',
        'In a fresh main omp TUI using the selected profile, verify native idle/working/blocked/done/error in this terminal. '
        'Local configuration readback is not effective project/overlay or OSC receiver acceptance.'))
    return changes
