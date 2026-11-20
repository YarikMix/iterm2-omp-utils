from pathlib import Path
from tests.native_features_support import NativeFixture
from iterm2_utils.features import shell

class IdentityInstallation(NativeFixture):
    def test_restore_installs_standalone_extension_in_selected_profile(self):
        changes = shell.identity_extension(self.context,self.selection('restore'))
        target = self.profile.agent_dir/'extensions/iterm2-utils-identity.ts'
        edit = next(edit for edit in changes.edits if edit.path == target)
        self.assertIn(str(self.context.paths.data/'identity').encode(),edit.after)
        self.assertIn(str(self.profile.agent_dir).encode(),edit.after)
        self.assertIn(str(self.context.executables['python3']).encode(),edit.after)
        self.assertEqual(changes.consumers['shared:identity'],frozenset({'restore'}))
        self.assertFalse(any(edit.path == self.home/'.omp/agent/extensions/iterm2-utils-identity.ts' for edit in changes.edits))

    def test_foreign_extension_name_collision_is_not_overwritten(self):
        target = self.profile.agent_dir/'extensions/iterm2-utils-identity.ts'
        target.parent.mkdir()
        target.write_text('// foreign')
        with self.assertRaises(ValueError):
            shell.identity_extension(self.context,self.selection('appearance'))
        self.assertEqual(target.read_text(),'// foreign')

    def test_shell_only_does_not_install_identity(self):
        self.assertEqual(shell.identity_extension(self.context,self.selection('shell')).edits,[])
