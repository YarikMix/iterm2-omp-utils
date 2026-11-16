from iterm2_utils import engine, lifecycle
from iterm2_utils.config import omp
from iterm2_utils.models import OmpEdit, Plan
from iterm2_utils.features import status, notifications
from tests.native_features_support import NativeFixture


class StatusFeatureTests(NativeFixture):
    def test_status_only_enables_native_program_status(self):
        changes = status.build(self.context, self.selection('status'))
        self.assertEqual([(e.kind,e.key,e.after) for e in changes.edits],
                         [('setting','terminal.programStatus',{'exists':True,'value':True})])
        self.assertTrue(all(isinstance(e,OmpEdit) for e in changes.edits))
        self.assertEqual([s.code for s in changes.ui], ['native_status'])

    def test_native_features_do_not_install_second_event_writer(self):
        path = self.profile.agent_dir/'config.yml'
        path.write_text('model: preserve\nterminal:\n  programStatus: false\n  foreign: keep\n')
        selection = self.selection('status','notifications')
        changes = status.build(self.context,selection)
        other = notifications.build(self.context,selection)
        changes.edits.extend(other.edits)
        changes.ui.extend(other.ui)
        result = engine.apply(Plan(selection,changes,'native'),self.context,self.runner)
        self.assertSuccess(result)
        self.assertEqual({r['kind'] for r in result.receipt.resources},{'omp_setting'})
        self.assertEqual(omp.read_setting(self.profile,'terminal.programStatus',self.runner),
                         {'exists':True,'value':True})
        self.assertEqual(omp.read_setting(self.profile,'completion.notify',self.runner),
                         {'exists':True,'value':'on'})
        self.assertEqual(omp.read_setting(self.profile,'error.notify',self.runner),
                         {'exists':True,'value':'off'})
        self.assertIn('model: preserve',path.read_text())
        self.assertIn('foreign: keep',path.read_text())
        self.assertFalse((self.context.paths.data/'current').exists())

    def test_identical_foreign_setting_is_not_adopted(self):
        (self.profile.agent_dir/'config.yml').write_text('terminal: {programStatus: true}\n')
        result = lifecycle.install(self.context,self.selection('status'),self.runner)
        self.assertSuccess(result)
        self.assertEqual(result.receipt.resources,[])
        self.assertEqual(result.receipt.selection.features,{'status'})

    def test_missing_receiver_blocks_only_status_checkpoint(self):
        self.context.capabilities -= {'iterm2:osc7501'}
        result = lifecycle.install(self.context,self.selection('status','shell'),self.runner)
        self.assertEqual(result.receipt.selection.features,{'shell'})
        self.assertTrue(any(f.feature=='status' and f.state=='unavailable' for f in result.findings))
