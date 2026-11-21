"""Retained integration-review safety cases, using the current native consumer."""
import json
import os
from unittest.mock import patch

from iterm2_utils import lifecycle, state
from tests.test_lifecycle import LifecycleFixture


class FinalFixTests(LifecycleFixture):
    def test_doctor_reports_missing_resources_and_dependencies_without_writing(self):
        self.assertSuccess(self.install('status', 'shell'))
        (self.profile.agent_dir/'config.yml').unlink()
        self.context.executables.pop('bun')
        before = self.snapshot()
        receipt = state.load(self.context.paths.data/'receipt.json')
        findings = lifecycle.doctor(self.context, receipt, self.runner)
        self.assertTrue({'owned_resource_missing', 'missing_binary'} <= {f.code for f in findings})
        self.assertEqual(self.snapshot(), before)

    def test_doctor_reports_changed_pointer_setting_and_server_readonly(self):
        self.context.versions['python3'] = '3.12.8'
        self.context.capabilities |= {'python:mcp'}
        self.assertSuccess(self.install('status', 'shell', 'mcp'))
        (self.profile.agent_dir/'config.yml').write_text('terminal: {programStatus: false}\n')
        current = self.context.paths.data/'current'
        current.unlink()
        current.symlink_to(self.home/'missing-release')
        server = self.profile.agent_dir/'mcp.json'
        document = json.loads(server.read_bytes())
        document['mcpServers']['iterm2-observe']['command'] = 'foreign'
        server.write_text(json.dumps(document))
        before = self.snapshot()
        findings = lifecycle.doctor(self.context, state.load(self.context.paths.data/'receipt.json'), self.runner)
        self.assertTrue({'owned_resource_changed', 'registration_changed'} <= {f.code for f in findings})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(os.readlink(current), str(self.home/'missing-release'))

    def test_old_selected_python_blocks_only_features_that_need_it(self):
        self.context.versions['python3'] = '3.9.6'
        result = self.install('shell', 'clipboard', 'status', 'notifications', 'restore')
        self.assertEqual(result.receipt.selection.features, {'shell', 'clipboard', 'status', 'notifications'})
        self.assertTrue(any(f.code == 'python_version' and f.feature == 'restore' for f in result.findings))

    def test_additive_profile_change_keeps_checkpoint_when_retained_dependency_disappears(self):
        self.assertSuccess(self.install('shortcuts', shortcuts=('alt-enter',)))
        before = self.snapshot()
        receipt = state.load(self.context.paths.data/'receipt.json')
        self.context.executables.pop('bun')
        result = self.install('clipboard')
        self.assertTrue(any(f.feature == 'shortcuts' and f.code == 'missing_binary' for f in result.findings))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(result.receipt, receipt)

    def test_update_keeps_whole_shared_profile_checkpoint_on_retained_blocker(self):
        self.assertSuccess(self.install('clipboard', 'shortcuts', shortcuts=('alt-enter',)))
        before = self.snapshot()
        receipt = state.load(self.context.paths.data/'receipt.json')
        self.context.executables.pop('bun')
        result = lifecycle.update(self.context, self.runner)
        self.assertTrue(any(f.feature == 'shortcuts' and f.code == 'missing_binary' for f in result.findings))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(result.receipt, receipt)

    def test_blocked_shared_profile_keeps_independent_shell_checkpoint(self):
        self.assertSuccess(self.install('shortcuts', shortcuts=('alt-enter',)))
        profile = self.context.paths.profiles/'iterm2-utils.json'
        before = profile.read_bytes()
        receipt = state.load(self.context.paths.data/'receipt.json')
        resources = [r for r in receipt.resources if r['target'] == str(profile.resolve())]
        self.assertEqual(len(resources), 1)
        self.context.executables.pop('bun')
        result = self.install('shell', 'clipboard')
        self.assertEqual(result.receipt.selection.features, {'shortcuts', 'shell'})
        self.assertEqual(result.receipt.selection.shortcuts, {'alt-enter'})
        self.assertEqual(profile.read_bytes(), before)
        self.assertEqual([r for r in result.receipt.resources if r['target'] == str(profile.resolve())], resources)
        self.assertTrue((self.context.paths.data/'current/vendor/shell_integration/iterm2_shell_integration.zsh').is_file())

    def test_early_profile_builder_failure_preserves_committed_checkpoint(self):
        self.assertSuccess(self.install('shortcuts', shortcuts=('alt-enter',)))
        before = self.snapshot()
        receipt = state.load(self.context.paths.data/'receipt.json')
        self.context.profiles.clear()
        result = self.install('clipboard')
        self.assertTrue(any(f.code == 'missing_parent' for f in result.findings))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(result.receipt, receipt)

    def test_discovery_validates_actual_selected_interpreter_with_spaces(self):
        from iterm2_utils.discovery import discover, resolve_paths
        from dataclasses import replace
        from iterm2_utils.planner import validate
        from tests.support import Fixture
        with Fixture() as fixture:
            omp = fixture.bin/'omp'
            omp.write_text('#!/bin/sh\n')
            omp.chmod(0o700)
            fixture.runner.responses['omp'] = 'omp 99.0.0 --resume'
            fixture.runner.responses['python3'] = 'Python 3.9.6'
            context = discover(resolve_paths(), fixture.runner, features=frozenset({'restore'}))
            selected = replace(self.selection('restore'), omp_profile=context.omp_profile)
            self.assertTrue(any(f.code == 'python_version' for f in validate(selected, context)))
            custom = fixture.home/'selected python/python3'
            custom.parent.mkdir()
            custom.write_text('#!/bin/sh\n')
            custom.chmod(0o700)
            fixture.runner.responses['python3'] = 'Python 3.12.8'
            with patch.dict(os.environ, {'ITERM2_UTILS_PYTHON':str(custom)}):
                context = discover(resolve_paths(), fixture.runner, features=frozenset({'restore'}))
            self.assertEqual(context.executables['python3'], custom)
            self.assertFalse(any(f.code == 'python_version' for f in validate(selected, context)))

    def test_notifications_do_not_parse_or_mutate_unselected_profile_storage(self):
        from iterm2_utils.config import omp
        foreign = self.home/'.omp/agent/config.yml'
        foreign.parent.mkdir(parents=True)
        foreign.write_text('{broken foreign profile')
        before = foreign.read_bytes()
        result = self.install('notifications')
        self.assertSuccess(result)
        self.assertEqual(result.receipt.selection.omp_profile, self.profile)
        self.assertEqual(omp.read_setting(self.profile, 'completion.notify', self.runner),
                         {'exists':True, 'value':'on'})
        self.assertEqual(foreign.read_bytes(), before)

    def test_independent_notifications_preserve_committed_status_when_receiver_disappears(self):
        from iterm2_utils.config import omp
        self.assertSuccess(self.install('status'))
        self.context.capabilities -= {'iterm2:osc7501'}
        result = self.install('notifications')
        self.assertSuccess(result)
        self.assertEqual(result.receipt.selection.features, {'status', 'notifications'})
        self.assertEqual(omp.read_setting(self.profile, 'terminal.programStatus', self.runner),
                         {'exists':True, 'value':True})
        self.assertEqual(omp.read_setting(self.profile, 'completion.notify', self.runner),
                         {'exists':True, 'value':'on'})
