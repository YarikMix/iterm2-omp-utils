"""Native picker and exact-file resume; no shell restorer or event callbacks."""
from ..models import ChangeSet, Context, Selection, UiStep


def build(context: Context, selection: Selection) -> ChangeSet:
    changes = ChangeSet([], [], [])
    if 'restore' in selection.features:
        changes.ui.append(UiStep('native_restore', 'restore', 'omp',
            'Use the native app.session.resume picker in the selected omp profile. '
            'For terminal launch use launch-omp with an exact validated --resume session file; '
            'history/continuation identity must be confirmed separately. No latest/fork/restore fallback.'))
    return changes
