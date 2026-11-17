"""Use omp's native completion/error notification policy and OSC 9 only."""
from ..config import omp
from ..models import ChangeSet, Context, Selection, UiStep


def build(context: Context, selection: Selection, *, runner) -> ChangeSet:
    changes = ChangeSet([], [], [])
    if 'notifications' not in selection.features:
        return changes
    for key, value in (('completion.notify', 'on'),
                       ('error.notify', 'on' if selection.notify_errors else 'off')):
        changes.edits.append(omp.setting_edit(selection.omp_profile, key,
            {'exists': True, 'value': value}, runner, owner='notifications'))
    changes.ui.append(UiStep('native_notifications', 'notifications', 'omp',
        'Verify one native completion banner from a fresh selected-profile omp TUI; '
        'verify error policy only as explicitly selected. Local YAML does not prove effective overlays or banner delivery.'))
    return changes
