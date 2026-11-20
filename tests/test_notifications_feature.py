from iterm2_utils import lifecycle
from iterm2_utils.config import omp
from iterm2_utils.features import notifications
from tests.native_features_support import NativeFixture


class NotificationFeatureTests(NativeFixture):
    def test_notifications_alone_preserve_native_default_policy(self):
        changes = notifications.build(self.context,self.selection('notifications'),runner=self.runner)
        self.assertEqual([(e.key,e.after['value']) for e in changes.edits],
                         [('completion.notify','on'),('error.notify','off')])
        self.assertFalse(any(e.owner=='status' for e in changes.edits))

    def test_error_notifications_require_explicit_opt_in_and_restore_inverse(self):
        path = self.profile.agent_dir/'config.yml'
        path.write_text('completion: {notify: off}\nerror: {notify: off}\nforeign: keep\n')
        first = lifecycle.install(self.context,self.selection('notifications',notify_errors=True),self.runner)
        self.assertSuccess(first)
        self.assertEqual(omp.read_setting(self.profile,'error.notify',self.runner)['value'],'on')
        result = lifecycle.uninstall(self.context,frozenset({'notifications'}),self.runner)
        self.assertSuccess(result)
        self.assertEqual(omp.read_setting(self.profile,'completion.notify',self.runner)['value'],'off')
        self.assertEqual(omp.read_setting(self.profile,'error.notify',self.runner)['value'],'off')
        self.assertIn('foreign: keep',path.read_text())

    def test_future_version_same_capabilities_is_not_rejected(self):
        from iterm2_utils.planner import validate
        for version in ('18.20.2','99.7.1-next'):
            self.context.versions['omp'] = version
            self.assertFalse([f for f in validate(self.selection('notifications'),self.context)
                              if f.state in {'unavailable','conflict','missing_dependency'}])

    def test_unknown_notification_receiver_leaves_both_selected_native_surfaces_pending(self):
        self.context.capabilities -= {'iterm2:osc9'}
        result = lifecycle.install(self.context,self.selection('status','notifications'),self.runner)
        self.assertSuccess(result)
        self.assertEqual(result.receipt.selection.features,{'status','notifications'})
        self.assertEqual({step.code for step in result.receipt.pending_ui},{'native_status','native_notifications'})
