"""Dedicated explicitly selected omp profile, with no inherited agent key maps."""
import base64
import json
import uuid
import re
from .. import state
from ..commands import Runner
from ..config import omp
from ..models import ChangeSet, Context, FileEdit, PreferenceEdit, Finding, Selection, UiStep

DOMAIN = 'com.googlecode.iterm2'
OWNER = 'shared:agent-profiles'
NAME = 'iterm2-utils:omp'
GUID = str(uuid.uuid5(uuid.NAMESPACE_URL, NAME))
SHORTCUTS = {
    'ctrl-v-ru': ('0x43c-0x40000-0x9-0x1', '0x16'),
    'alt-enter': ('0xd-0x20000-0x24-0x1', '0x0a'),
}
# Native pi-tui app-keybindings defaults observed with omp 18.20.2. Keep these
# reserved even when locally remapped; a resume chord must not steal core input.
RESERVED_KEYS = frozenset('''
up down left right ctrl+b ctrl+f alt+left ctrl+left alt+b alt+right ctrl+right alt+f
home ctrl+a end ctrl+e ctrl+] ctrl+alt+] pageup pagedown backspace delete ctrl+d
ctrl+w alt+backspace ctrl+backspace super+alt+backspace alt+delete alt+d ctrl+delete
super+alt+delete super+alt+d ctrl+u ctrl+k ctrl+y alt+y ctrl+- ctrl+_ ctrl+.
shift+enter ctrl+j enter tab ctrl+c escape ctrl+z alt+l shift+tab ctrl+t ctrl+p
shift+ctrl+p alt+m alt+p ctrl+o ctrl+shift+o alt+h n alt+n ctrl+enter ctrl+q ctrl+g
alt+g f5 alt+r alt+up shift+up alt+i ctrl+v ctrl+shift+v alt+shift+v alt+shift+l
alt+shift+c alt+a ctrl+s ctrl+r alt+k alt+shift+k alt+shift+p alt+o space ctrl+l
'''.split())


def _chord(value):
    parts = value.lower().split('+') if isinstance(value,str) else []
    modifiers = parts[:-1]
    if (not parts or not parts[-1] or any(m not in {'ctrl','alt','shift','super'} for m in modifiers)
            or len(set(modifiers))!=len(modifiers) or any(c.isspace() for c in value)
            or not (len(parts[-1])==1 or parts[-1] in {
                'up','down','left','right','home','end','pageup','pagedown',
                'enter','tab','escape','backspace','delete','space'} or
                re.fullmatch(r'f(?:[1-9]|1[0-9]|2[0-4])',parts[-1]))):
        return None
    return tuple(sorted(modifiers)),parts[-1]


def resume_key_conflict(value):
    chord = _chord(value)
    return chord is None or chord in {_chord(key) for key in RESERVED_KEYS}


def build(context: Context, selection: Selection) -> ChangeSet:
    changes = ChangeSet([], [], [])
    consumers = selection.features & {'clipboard', 'shortcuts'}
    if not consumers:
        return changes
    feature = 'shortcuts' if 'shortcuts' in consumers else 'clipboard'
    def fail(code, message):
        changes.findings.append(Finding(feature, 'omp', code, 'conflict', message))
        return changes
    parent = context.profiles.get(selection.parent_profile)
    if not isinstance(parent, dict):
        return fail('missing_parent', 'The selected parent profile must exist.')
    if selection.parent_profile == NAME:
        return fail('invalid_parent', 'The dedicated omp profile cannot inherit itself.')
    if 'resume' in selection.shortcuts and not selection.resume_key:
        return fail('resume_key_required', 'Select --resume-key explicitly; no text-injection resume shortcut is installed.')
    if 'resume' in selection.shortcuts and resume_key_conflict(selection.resume_key):
        return fail('resume_key_conflict', 'The resume key is invalid or conflicts with native input; choose an unused chord.')
    keys = {key: {'Action': 11, 'Text': text}
            for name, (key, text) in SHORTCUTS.items() if name in selection.shortcuts}
    profile = {'Name': NAME, 'Guid': GUID,
               'Dynamic Profile Parent Name': selection.parent_profile,
               'Custom Command': 'No', 'Command': '', 'Bound Hosts': [],
               'Keyboard Map': keys}
    # A Bun job is not an omp identity. Only explicit launch selects this profile.
    document = {'Profiles': [profile]}
    path = context.paths.profiles/'iterm2-utils.json'
    before = path.read_bytes() if path.exists() else None
    if before is not None:
        receipt = state.load(context.paths.data/'receipt.json')
        owned = any(r['kind']=='file' and r['target']==str(path.resolve()) and OWNER in r['owners']
                    and r['installed']=={'exists':True,'value':base64.b64encode(before).decode()}
                    for r in receipt.resources) if receipt else False
        if not owned and json.loads(before) != document:
            return fail('profile_conflict', 'The dedicated profile document is foreign or changed; resolve ownership first.')
    after = before if before is not None and json.loads(before)==document else (
        json.dumps(document,sort_keys=True,indent=2)+'\n').encode()
    changes.edits.append(FileEdit(path,before,after,0o600,OWNER))
    runner = Runner()
    for shortcut, action, chord, defaults in (
            ('alt-enter','tui.input.newLine','ctrl+j',['shift+enter','ctrl+j']),
            ('ctrl-v-ru','app.clipboard.pasteImage','ctrl+v',['ctrl+v'])):
        if shortcut not in selection.shortcuts:
            continue
        effective = omp.effective_binding(selection.omp_profile,action,runner)
        value = effective['value'] if effective['exists'] else defaults
        alternatives = list(value) if isinstance(value,list) else [] if value is None else [value]
        if not any(_chord(key)==_chord(chord) for key in alternatives):
            alternatives.append(chord)
        changes.edits.append(omp.binding_edit(selection.omp_profile,action,
            {'exists':True,'value':alternatives},runner,owner='shortcuts'))
    changes.consumers[OWNER] = frozenset(consumers)
    if 'resume' in selection.shortcuts:
        changes.edits.append(omp.binding_edit(selection.omp_profile,'app.session.resume',
            {'exists':True,'value':selection.resume_key},Runner(),owner='shortcuts'))
    if 'clipboard' in consumers:
        preferences = context.preferences.get(DOMAIN,{})
        changes.edits.append(PreferenceEdit(DOMAIN,'CopySelection',preferences.get('CopySelection'),False,'clipboard'))
    changes.ui.append(UiStep('native_keyboard',feature,'omp',
        'Select the dedicated omp profile explicitly; verify Cmd+C selection copy, Ctrl+C clear/cancel, '
        'native Ctrl+Q follow-up/approval and only the selected RU paste/newline/resume keys. '
        'No automatic Bun job matching or parent agent keyboard-map inheritance is installed.'))
    return changes
