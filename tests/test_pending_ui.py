from unittest.mock import patch
from iterm2_utils import lifecycle, state
from tests.native_features_support import NativeFixture


class PendingUiTests(NativeFixture):
    def test_native_event_acceptance_stays_pending_after_storage_readback(self):
        installed = lifecycle.install(self.context,self.selection('status'),self.runner)
        self.assertSuccess(installed)
        result = lifecycle.reconcile_ui(self.context,'native_status',self.runner)
        self.assertTrue(result.receipt.pending_ui)
        self.assertTrue(any(f.state=='pending_ui' for f in result.findings))
        self.assertFalse(any(r['kind']=='hook' for r in result.receipt.resources))
        self.assertEqual(result.receipt.resources,installed.receipt.resources)

    def test_repeat_update_does_not_duplicate_pending_steps_or_change_inverse(self):
        first = lifecycle.install(self.context,self.selection('status','notifications'),self.runner)
        result = lifecycle.update(self.context,self.runner)
        self.assertSuccess(result)
        self.assertEqual(result.receipt.resources,first.receipt.resources)
        self.assertEqual(result.receipt.pending_ui,first.receipt.pending_ui)

    def test_failed_mcp_connection_is_not_retried_or_marked_ready(self):
        installed = lifecycle.install(self.context,self.selection('mcp'),self.runner)
        self.assertSuccess(installed)
        with patch.object(self.runner,'mcp_probe',side_effect=TimeoutError) as probe:
            result = lifecycle.reconcile_ui(self.context,'mcp_authorize',self.runner)
        self.assertEqual(probe.call_count,1)
        self.assertEqual(result.receipt.pending_ui,installed.receipt.pending_ui)
        self.assertEqual(state.load(self.context.paths.data/'receipt.json'),installed.receipt)
