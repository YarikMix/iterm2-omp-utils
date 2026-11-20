"""Historical single-writer cutover, not active legacy agent integration."""
import json
from unittest.mock import patch
from iterm2_utils import engine, migration, state
from iterm2_utils.config import tomlfile
from tests.test_migration import MigrationFixture


class NativeMigrationTests(MigrationFixture):
    def adopted(self):
        path = self.home/'config.toml'
        path.write_text('[plugins."iterm2-status@local"]\nenabled = false\n\n[foreign]\nkeep = true\n')
        resource = self.resource('toml', path,
            {'pointer':['plugins','iterm2-status@local','enabled'],'mode':0o600},
            self.value(True), self.value(False))
        self.save(self.historical([resource]))
        return path, resource

    def test_adopted_external_stays_disabled_and_inverse_is_not_active(self):
        path, resource = self.adopted()
        preview = migration.preview_omp_migration(self.context, self.runner)
        self.assertTrue(any(f.code == 'legacy_external_kept' for f in preview.changes.findings))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertFalse(tomlfile.parse(path.read_bytes())['plugins']['iterm2-status@local']['enabled'])
        self.assertEqual(result.receipt.resources, [])
        self.assertEqual(result.receipt.legacy_cleanup[0]['resources'], [resource])
        # Generic uninstall cannot reactivate a foreign integration.
        reverted = engine.revert(result.receipt, self.context, self.runner, frozenset({'status'}))
        self.assertFalse(tomlfile.parse(path.read_bytes())['plugins']['iterm2-status@local']['enabled'])
        self.assertEqual(reverted.receipt.legacy_cleanup, result.receipt.legacy_cleanup)

    def test_explicit_restore_external_restores_recorded_value_only(self):
        path, _ = self.adopted()
        before = migration.preview_omp_migration(self.context, self.runner)
        chosen = migration.preview_omp_migration(self.context, self.runner, restore_external=True)
        self.assertNotEqual(before.fingerprint, chosen.fingerprint)
        self.assertTrue(any(f.code == 'legacy_external_restore' for f in chosen.changes.findings))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False, restore_external=True)
        self.assertEqual(tomlfile.parse(path.read_bytes()),
                         {'plugins':{'iterm2-status@local':{'enabled':True}},'foreign':{'keep':True}})
        self.assertEqual(result.receipt.legacy_cleanup, [])

    def test_external_choice_is_in_durable_result_before_commit(self):
        path, resource = self.adopted()
        original = state.durable_write
        def fail_commit(target, content, *args, **kwargs):
            if target.name == 'phase':
                raise KeyboardInterrupt('crash before commit marker')
            return original(target, content, *args, **kwargs)
        with patch.object(state, 'durable_write', side_effect=fail_commit):
            with self.assertRaises(KeyboardInterrupt):
                migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        saved = state.load(self.context.paths.data/'journal/result.json')
        self.assertEqual(saved.legacy_cleanup[0]['resources'], [resource])
        self.assertFalse(tomlfile.parse(path.read_bytes())['plugins']['iterm2-status@local']['enabled'])
        retry = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(retry.receipt.legacy_cleanup[0]['resources'], [resource])

    def hook(self):
        return {'hooks':[{'type':'command','command':'/owned/helper status','timeout':3}]}

    def test_exact_owned_hook_removed_preserving_foreign_hook(self):
        path = self.home/'hooks.json'
        ours = self.hook()
        foreign = {'hooks':[{'type':'command','command':'/foreign/helper'}]}
        path.write_text(json.dumps({'hooks':{'Stop':[ours,foreign]},'foreign':7}))
        resource = self.resource('hook', path, {'pointer':['hooks','Stop'],'entry':ours,'mode':0o600},
                                 self.value(exists=False), self.value(ours))
        self.save(self.historical([resource]))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(json.loads(path.read_bytes()), {'hooks':{'Stop':[foreign]},'foreign':7})
        self.assertEqual(result.receipt.legacy_cleanup, [])

    def test_duplicate_hook_is_unresolved_without_broad_array_deletion(self):
        path = self.home/'hooks.json'; ours = self.hook()
        path.write_text(json.dumps({'hooks':{'Stop':[ours,ours]}}))
        resource = self.resource('hook', path, {'pointer':['hooks','Stop'],'entry':ours,'mode':0o600},
                                 self.value(exists=False), self.value(ours))
        self.save(self.historical([resource]))
        original = path.read_bytes()
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(result.receipt.legacy_cleanup[0]['resources'], [resource])

    def test_changed_writer_blocks_only_conflicting_native_checkpoint(self):
        path = self.home/'hooks.json'; ours = self.hook()
        changed = {'hooks':[{'type':'command','command':'/owned/helper status --user-edit'}]}
        path.write_text(json.dumps({'hooks':{'Stop':[changed]}}))
        resource = self.resource('hook', path, {'pointer':['hooks','Stop'],'entry':ours,'mode':0o600},
                                 self.value(exists=False), self.value(ours))
        self.save(self.historical([resource], ('status',)))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertNotIn('status', result.receipt.selection.features)
        self.assertEqual(result.receipt.legacy_cleanup[0]['resources'], [resource])
        self.assertTrue(any(f.code == 'legacy_writer_conflict' for f in result.findings))

    def test_real_beta1_receipt_cleans_hooks_without_old_executables(self):
        from pathlib import Path
        from iterm2_utils import legacy_state
        source = Path(__file__).parent/'fixtures/beta1-hooks.json'
        fixture = json.loads(source.read_bytes())
        self.assertEqual(fixture['source_commit'], '8c5643ed574f016bca46952ae6cd804d09195580')
        def expand(text):
            return text.replace('@HOME@', str(self.home))
        raw = json.loads(expand(json.dumps(fixture['receipt'])))
        self.save(legacy_state.decode(raw))
        for name, value in fixture['files'].items():
            path = self.home/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expand(value['text']))
        hooks = self.home/'codex/hooks.json'
        document = json.loads(hooks.read_bytes())
        foreign = {'hooks':[{'type':'command','command':'/foreign/helper'}]}
        document['hooks']['Stop'].append(foreign)
        hooks.write_text(json.dumps(document))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        current = json.loads(hooks.read_bytes())['hooks']
        self.assertEqual(current['Stop'], [foreign])
        self.assertEqual(sum(len(entries) for entries in current.values()), 1)
        self.assertEqual(sum(len(entries) for entries in
            json.loads((self.home/'claude/settings.json').read_bytes())['hooks'].values()), 0)
        self.assertEqual(self.runner.calls, [])
        self.assertTrue(result.receipt.legacy_cleanup)

    def test_restored_external_writer_does_not_install_second_native_writer(self):
        path, resource = self.adopted()
        self.save(self.historical([resource], ('status',)))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False, restore_external=True)
        self.assertTrue(tomlfile.parse(path.read_bytes())['plugins']['iterm2-status@local']['enabled'])
        self.assertNotIn('status', result.receipt.selection.features)
        self.assertEqual(result.receipt.legacy_cleanup[0]['resources'], [resource])
        self.assertTrue(any(f.code == 'legacy_writer_conflict' for f in result.findings))

    def test_changed_disabled_external_writer_is_not_assumed_safe(self):
        from iterm2_utils import lifecycle
        from iterm2_utils.models import Selection
        path, resource = self.adopted()
        migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        path.write_text('[plugins."iterm2-status@local"]\nenabled = true\n')
        result = lifecycle.install(self.context,
            Selection(frozenset({'status'}), frozenset(), 'Default', self.profile), self.runner)
        self.assertNotIn('status', result.receipt.selection.features)
        self.assertEqual(result.receipt.legacy_cleanup[0]['resources'], [resource])
        self.assertTrue(any(f.code == 'legacy_writer_conflict' for f in result.findings))
