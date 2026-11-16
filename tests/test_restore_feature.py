from iterm2_utils.features import restore, shell
from iterm2_utils.planner import validate
from tests.native_features_support import NativeFixture


class RestoreFeatureTests(NativeFixture):
    def test_restore_uses_native_picker_without_shell_dispatcher(self):
        selection = self.selection('restore')
        changes = restore.build(self.context,selection)
        self.assertEqual(changes.edits,[])
        self.assertEqual(shell.build(self.context,selection).edits,[])
        self.assertEqual([s.code for s in changes.ui],['native_restore'])
        self.assertIn('app.session.resume',changes.ui[0].instruction)
        self.assertNotIn('fzf',repr(changes))
        self.assertFalse([f for f in validate(selection,self.context) if f.state=='missing_dependency'])

    def test_absent_native_resume_capability_is_feature_specific(self):
        self.context.capabilities -= {'omp:resume'}
        findings = validate(self.selection('restore','shell'),self.context)
        self.assertTrue(any(f.feature=='restore' and f.state=='unavailable' for f in findings))
        self.assertTrue(any(f.feature=='shell' and f.state=='ready' for f in findings))
