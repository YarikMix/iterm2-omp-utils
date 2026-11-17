import json
from iterm2_utils.features.profiles import build
from iterm2_utils.models import FileEdit, OmpEdit, PreferenceEdit
from tests.native_features_support import NativeFixture


class ProfileTests(NativeFixture):
    def generated_profile(self, changes):
        edit = next(e for e in changes.edits if isinstance(e,FileEdit))
        return json.loads(edit.after)['Profiles'][0]

    def test_dedicated_profile_has_no_job_or_bun_automatic_matching(self):
        changes = build(self.context,self.selection('clipboard'),runner=self.runner)
        profile = self.generated_profile(changes)
        self.assertEqual(profile['Name'],'iterm2-utils:omp')
        self.assertEqual(profile['Dynamic Profile Parent Name'],'Default')
        self.assertEqual(profile['Keyboard Map'],{})
        self.assertEqual(profile['Bound Hosts'],[])
        self.assertEqual(profile['Custom Command'],'No')
        self.assertEqual(profile['Command'],'')
        self.assertEqual([(e.key,e.after) for e in changes.edits if isinstance(e,PreferenceEdit)],
                         [('CopySelection',False)])
        self.assertFalse(any(isinstance(e,OmpEdit) for e in changes.edits))

    def test_parent_agent_keyboard_map_is_not_inherited(self):
        self.context.profiles['Default']['Keyboard Map'] = {
            '0x63-0x100000-0x8-0x1':{'Action':11,'Text':'0x03'},
            '0x71-0x40000-0xc-0x1':{'Action':11,'Text':'0x03 0x03'}}
        profile = self.generated_profile(build(self.context,self.selection('clipboard'),runner=self.runner))
        self.assertEqual(profile['Keyboard Map'],{})

    def test_selected_normalization_preserves_ctrl_c_and_ctrl_q(self):
        changes = build(self.context,self.selection('shortcuts',shortcuts=('alt-enter','ctrl-v-ru','ctrl-q')),runner=self.runner)
        keys = self.generated_profile(changes)['Keyboard Map']
        self.assertEqual(keys,{
            '0xd-0x20000-0x24-0x1':{'Action':11,'Text':'0x0a'},
            '0x43c-0x40000-0x9-0x1':{'Action':11,'Text':'0x16'}})
        self.assertFalse(any(isinstance(e,PreferenceEdit) for e in changes.edits))

    def test_resume_requires_explicit_chord_and_native_action(self):
        invalid = build(self.context,self.selection('shortcuts',shortcuts=('resume',)),runner=self.runner)
        self.assertEqual(invalid.edits,[])
        self.assertTrue(any(f.code=='resume_key_required' for f in invalid.findings))
        changes = build(self.context,self.selection('shortcuts',shortcuts=('resume',),resume_key='F8'),runner=self.runner)
        native = [e for e in changes.edits if isinstance(e,OmpEdit)]
        self.assertEqual([(e.key,e.after['value']) for e in native],[('app.session.resume','F8')])
        self.assertEqual(self.generated_profile(changes)['Keyboard Map'],{})

    def test_inherited_resume_collision_is_not_overwritten(self):
        default = self.home/'.omp/agent'
        default.mkdir(parents=True)
        (default/'keybindings.yml').write_text('app.history.search: F8\n')
        with self.assertRaises(ValueError):
            build(self.context,self.selection('shortcuts',shortcuts=('resume',),resume_key='F8'),runner=self.runner)

    def test_only_selected_normalizations_are_present(self):
        changes = build(self.context,self.selection('shortcuts',shortcuts=('ctrl-q',)),runner=self.runner)
        self.assertEqual(self.generated_profile(changes)['Keyboard Map'],{})

    def test_resume_cannot_steal_native_control_keys(self):
        from iterm2_utils.planner import validate
        for chord in ('Ctrl+C','Ctrl+Q','Ctrl+J','Ctrl+V','Alt+R','Ctrl+R'):
            findings = validate(self.selection('shortcuts',shortcuts=('resume',),resume_key=chord),self.context)
            self.assertTrue(any(f.code=='resume_key_conflict' for f in findings))

    def test_normalization_preserves_inherited_native_alternatives_and_neighbours(self):
        default = self.home/'.omp/agent'
        default.mkdir(parents=True)
        inherited = default/'keybindings.yml'
        inherited.write_text('tui.input.newLine: Alt+N\napp.history.search: Ctrl+R\n')
        before = inherited.read_bytes()
        changes = build(self.context,self.selection('shortcuts',shortcuts=('alt-enter',)),runner=self.runner)
        edit = next(e for e in changes.edits if isinstance(e,OmpEdit))
        self.assertEqual(edit.key,'tui.input.newLine')
        self.assertEqual(edit.before,{'exists':False,'value':None})
        self.assertEqual(edit.after,{'exists':True,'value':['Alt+N','ctrl+j']})
        self.assertEqual(inherited.read_bytes(),before)

    def test_newline_collision_blocks_instead_of_installing_wrong_action(self):
        path = self.profile.agent_dir/'keybindings.yml'
        path.write_text('app.history.search: Ctrl+J\n')
        with self.assertRaises(ValueError):
            build(self.context,self.selection('shortcuts',shortcuts=('alt-enter',)),runner=self.runner)

    def test_resume_refuses_inherited_modifier_order_collision(self):
        from iterm2_utils import lifecycle
        default = self.home/'.omp/agent'
        default.mkdir(parents=True)
        inherited = default/'keybindings.yml'
        inherited.write_text('app.history.search: Shift+Ctrl+F8\n')
        before = inherited.read_bytes()
        selection = self.selection('shortcuts',shortcuts=('resume',),resume_key='Ctrl+Shift+F8')
        result = lifecycle.install(self.context,selection,self.runner)
        self.assertTrue(any(f.feature=='shortcuts' and f.state=='conflict' for f in result.findings))
        self.assertFalse(result.receipt.selection.features)
        self.assertEqual(inherited.read_bytes(),before)
        self.assertFalse((self.profile.agent_dir/'keybindings.yml').exists())
        self.assertFalse((self.context.paths.profiles/'iterm2-utils.json').exists())
