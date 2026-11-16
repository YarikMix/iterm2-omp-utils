"""Receipt-authorized omp cutover; all storage belongs to a temporary HOME."""
import base64
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from iterm2_utils import engine, legacy_state, lifecycle, migration, state
from iterm2_utils.models import Context, OmpProfile, Paths, Receipt, Selection


class NoAgentRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(argv)
        raise AssertionError('Unexpected external process: ' + str(argv[0]))


class MigrationFixture(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        p = self.home
        self.profile = OmpProfile(None, p/'.omp/agent')
        self.context = Context(Paths(p, p/'.zshrc', p/'config', p/'cache', p/'data', p/'profiles',
                                     Path(__file__).resolve().parents[1]), {}, {}, frozenset(), {}, {},
                               omp_profile=self.profile)
        self.runner = NoAgentRunner()

    def resource(self, kind, path, locator, before, installed, owners=('status',)):
        return dict(kind=kind, target=str(path), locator=locator, before=before,
                    installed=installed, owners=list(owners), version='1')

    def value(self, value=None, exists=True):
        return {'exists':exists, 'value':value if exists else None}

    def historical(self, resources, features=(), agents=('codex',)):
        return legacy_state.LegacyReceipt('1', legacy_state.LegacySelection(
            frozenset(agents), frozenset(features), frozenset(), 'Default'), resources, [])

    def save(self, receipt, context=None):
        path = (context or self.context).paths.data/'receipt.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        state.save_recovery(path, receipt)

    def json_resource(self, path, key='ours', before=0, installed=1, owners=('status',)):
        return self.resource('json', path, {'pointer':[key], 'mode':0o600},
                             self.value(before), self.value(installed), owners)

    def snapshot(self):
        return {str(p.relative_to(self.home)):p.read_bytes()
                for p in self.home.rglob('*') if p.is_file() and not p.is_symlink()}


class MigrationTests(MigrationFixture):
    def test_cleanup_conflict_remains_retryable_without_old_binaries(self):
        path = self.home/'legacy.json'
        path.write_text('{"ours":2,"foreign":{"keep":true}}')
        resource = self.json_resource(path)
        self.save(self.historical([resource]))
        first = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertIsInstance(first.receipt, Receipt)
        self.assertEqual(first.receipt.selection.features, frozenset())
        self.assertEqual(first.receipt.legacy_cleanup[0]['resources'], [resource])
        self.assertTrue(any(f.code == 'legacy_cleanup_conflict' for f in first.findings))
        path.write_text('{"ours":1,"foreign":{"keep":true}}')
        second = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(second.receipt.legacy_cleanup, [])
        self.assertEqual(json.loads(path.read_bytes()), {'ours':0, 'foreign':{'keep':True}})
        self.assertEqual(self.runner.calls, [])

    def test_preview_never_recovers_or_creates_lock(self):
        path = self.home/'settings.json'; path.write_text('{"ours":1}')
        receipt = self.historical([self.json_resource(path)])
        self.save(receipt)
        journal = self.context.paths.data/'journal'; journal.mkdir()
        state.save_recovery(journal/'intent.json', receipt)
        before = self.snapshot()
        preview = migration.preview_omp_migration(self.context, self.runner)
        self.assertTrue(any(f.code == 'migration_recovery_required' for f in preview.changes.findings))
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.context.paths.data/'transaction.lock').exists())

    def test_apply_recovers_historical_journal_before_cleanup(self):
        path = self.home/'settings.json'; path.write_text('{"ours":1,"foreign":7}')
        receipt = self.historical([self.json_resource(path)])
        self.save(receipt)
        journal = self.context.paths.data/'journal'; journal.mkdir()
        state.save_recovery(journal/'intent.json', receipt)
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(json.loads(path.read_bytes()), {'ours':0,'foreign':7})
        self.assertFalse(journal.exists())
        self.assertEqual(result.receipt.legacy_cleanup, [])

    def test_all_three_bootstrap_receipts_clean_only_owned_files(self):
        from iterm2_utils import skill_install
        for skill in skill_install.BUNDLES:
            isolated = skill_install._context(self.context, skill)
            path = self.home/'.codex/skills'/skill/'SKILL.md'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'owned')
            neighbour = path.parent/'foreign.txt'; neighbour.write_bytes(b'keep')
            resource = self.resource('file', path, {'mode':0o644}, self.value(exists=False),
                self.value(base64.b64encode(b'owned').decode()), ('bootstrap-skill',))
            self.save(self.historical([resource], ('bootstrap-skill',)), isolated)
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertFalse(any(f.state == 'conflict' for f in result.findings), result.findings)
        for skill in skill_install.BUNDLES:
            self.assertFalse((self.home/'.codex/skills'/skill/'SKILL.md').exists())
            self.assertEqual((self.home/'.codex/skills'/skill/'foreign.txt').read_bytes(), b'keep')
            receipt = state.load(skill_install._context(self.context, skill).paths.data/'receipt.json')
            self.assertEqual(receipt.legacy_cleanup, [])

    def test_changed_bootstrap_file_is_retained_independently(self):
        from iterm2_utils import skill_install
        isolated = skill_install._context(self.context, 'iterm2-launch')
        path = self.home/'skill'; path.write_bytes(b'user')
        resource = self.resource('file', path, {'mode':0o644}, self.value(exists=False),
            self.value(base64.b64encode(b'owned').decode()), ('bootstrap-skill',))
        self.save(self.historical([resource], ('bootstrap-skill',)), isolated)
        migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        stored = state.load(isolated.paths.data/'receipt.json')
        self.assertEqual(stored.legacy_cleanup[0]['resources'], [resource])
        self.assertEqual(path.read_bytes(), b'user')

    def test_preview_fingerprint_covers_foreign_neighbours_and_all_receipts(self):
        path = self.home/'settings.json'; path.write_text('{"ours":1,"foreign":1}')
        self.save(self.historical([self.json_resource(path)]))
        first = migration.preview_omp_migration(self.context, self.runner)
        path.write_text('{"ours":1,"foreign":2}')
        second = migration.preview_omp_migration(self.context, self.runner)
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_fingerprint_revalidated_under_transaction_lock(self):
        path = self.home/'settings.json'; path.write_text('{"ours":1,"foreign":1}')
        self.save(self.historical([self.json_resource(path)]))
        original = migration.preview_omp_migration
        def stale(*args, **kwargs):
            preview = original(*args, **kwargs)
            path.write_text('{"ours":1,"foreign":2}')
            return preview
        with patch.object(migration, 'preview_omp_migration', side_effect=stale):
            result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertTrue(any(f.code == 'migration_stale_preview' for f in result.findings))
        self.assertEqual(json.loads(path.read_bytes()), {'ours':1,'foreign':2})
        self.assertIsInstance(state.load(self.context.paths.data/'receipt.json'), legacy_state.LegacyReceipt)

    def test_shared_appearance_and_launcher_preserve_guid_and_original_inverse(self):
        path = self.context.paths.profiles/'iterm2-utils-project-launcher.json'
        path.parent.mkdir(parents=True)
        content = b'{"Profiles":[{"Guid":"existing-guid","Name":"Project"}]}'
        path.write_bytes(content)
        resource = self.resource('file', path, {'mode':0o600}, self.value(exists=False),
            self.value(base64.b64encode(content).decode()), ('shared:project-launcher','codex:project-launcher'))
        self.save(self.historical([resource], ('project-launcher',)))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(result.receipt.resources[0]['before'], {'exists':False,'value':None})
        self.assertEqual(result.receipt.resources[0]['owners'], ['shared:project-launcher','project-launcher'])
        self.assertNotIn('project-launcher', result.receipt.selection.features)
        self.assertEqual(result.receipt.legacy_cleanup[0]['selection']['features'], ['project-launcher'])

    def test_feature_intent_goes_through_actual_lifecycle_builder(self):
        self.save(self.historical([], ('status',)))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertNotIn('status', result.receipt.selection.features)
        self.assertEqual(result.receipt.legacy_cleanup[0]['selection']['features'], ['status'])
        self.assertTrue(any(f.feature == 'status' and f.state in {'missing_dependency','conflict','unavailable'}
                            for f in result.findings))

    def test_unknown_registration_provenance_is_retryable_not_guessed(self):
        resource = self.resource('registration', 'codex', {'name':'iterm2-observe'},
            self.value(exists=False), self.value({'command':'uvx'}), ('mcp',))
        self.save(self.historical([resource]))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(result.receipt.legacy_cleanup[0]['resources'], [resource])
        self.assertTrue(any(f.code == 'legacy_mcp_unresolved' for f in result.findings))
        self.assertEqual(self.runner.calls, [])

    def test_exact_mcp_storage_pointer_removes_only_server(self):
        path = self.home/'config.toml'
        path.write_text('[mcp_servers.iterm2-observe]\ncommand = "uvx"\nargs = ["owned"]\n\n[mcp_servers.foreign]\ncommand = "keep"\n')
        resource = self.resource('toml', path, {'pointer':['mcp_servers','iterm2-observe'],'mode':0o600},
            self.value(exists=False), self.value({'command':'uvx','args':['owned']}), ('mcp',))
        self.save(self.historical([resource]))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        from iterm2_utils.config import tomlfile
        self.assertEqual(tomlfile.parse(path.read_bytes()), {'mcp_servers':{'foreign':{'command':'keep'}}})
        self.assertEqual(result.receipt.legacy_cleanup, [])

    def test_referenced_profile_remains_retryable(self):
        path = self.context.paths.profiles/'iterm2-utils.json'; path.parent.mkdir()
        content = b'{"Profiles":[{"Guid":"referenced","Name":"Old"}]}'
        path.write_bytes(content)
        resource = self.resource('file', path, {'mode':0o600}, self.value(exists=False),
            self.value(base64.b64encode(content).decode()), ('clipboard',))
        self.save(self.historical([resource]))
        with patch('iterm2_utils.config.iterm.ensure_unreferenced', side_effect=ValueError('live reference')):
            result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(result.receipt.legacy_cleanup[0]['resources'], [resource])

    def test_live_legacy_shell_preserves_immutable_runtime(self):
        release = self.context.paths.data/'releases/old/codex.zsh'; release.parent.mkdir(parents=True)
        release.write_bytes(b'old shell helper')
        resource = self.resource('file', release, {'mode':0o600}, self.value(exists=False),
            self.value(base64.b64encode(b'old shell helper').decode()), ('shared:runtime','status'))
        self.save(self.historical([resource]))
        with patch('iterm2_utils.config.iterm.inspect', return_value={'sessions':[{'id':'live'}]}):
            result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(release.read_bytes(), b'old shell helper')
        self.assertEqual(result.receipt.legacy_cleanup[0]['resources'], [resource])
        self.assertTrue(any(f.code == 'legacy_runtime_deferred' for f in result.findings))

    def test_safe_explicit_retry_cleans_unreferenced_old_runtime(self):
        path = self.context.paths.data/'releases/old/helper.py'; path.parent.mkdir(parents=True)
        path.write_bytes(b'old')
        resource = self.resource('file', path, {'mode':0o600}, self.value(exists=False),
            self.value(base64.b64encode(b'old').decode()), ('shared:runtime','status'))
        self.save(self.historical([resource]))
        with patch('iterm2_utils.config.iterm.inspect', return_value={'sessions':[], 'complete':True}):
            first = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
            self.assertTrue(path.exists())
            self.assertTrue(first.receipt.legacy_cleanup)
            result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertFalse(path.exists())
        self.assertEqual(result.receipt.legacy_cleanup, [])

    def test_registration_uses_only_companion_receipted_exact_storage_address(self):
        path = self.home/'custom-config.toml'
        args = ['--with','mcp<2','mcp-server-iterm2==0.1.1']
        path.write_text('[mcp_servers.iterm2-observe]\ncommand = "uvx"\nargs = ["--with", "mcp<2", "mcp-server-iterm2==0.1.1"]\n\n[mcp_servers.foreign]\ncommand = "keep"\n')
        definition = {'command':'uvx','args':args,'scope':'user','enabled':True,'environment_empty':True}
        registration = self.resource('registration', 'codex', {'name':'iterm2-observe'},
            self.value(exists=False), self.value(definition), ('mcp',))
        address = self.resource('toml', path, {'pointer':['mcp_servers','iterm2-observe'],'mode':0o600},
            self.value(exists=False), self.value({'command':'uvx','args':args}), ('mcp',))
        self.save(self.historical([registration,address]))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        from iterm2_utils.config import tomlfile
        self.assertEqual(tomlfile.parse(path.read_bytes()), {'mcp_servers':{'foreign':{'command':'keep'}}})
        self.assertEqual(result.receipt.legacy_cleanup, [])
        self.assertEqual(self.runner.calls, [])

    def test_cleanup_crash_replay_restores_intent_then_retries(self):
        path = self.home/'settings.json'; path.write_text('{"ours":1,"foreign":9}')
        self.save(self.historical([self.json_resource(path)]))
        original = engine._write_file
        def crash(target, *args, **kwargs):
            original(target, *args, **kwargs)
            raise KeyboardInterrupt('crash after resource write')
        with patch.object(engine, '_write_file', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(json.loads(path.read_bytes()), {'ours':0,'foreign':9})
        intent = state.load(self.context.paths.data/'journal/intent.json')
        self.assertIsInstance(intent, legacy_state.LegacyReceipt)
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(json.loads(path.read_bytes()), {'ours':0,'foreign':9})
        self.assertEqual(result.receipt.legacy_cleanup, [])

    def test_changed_recovery_resource_blocks_cutover_without_losing_inverse(self):
        path = self.home/'settings.json'; path.write_text('{"ours":2,"foreign":9}')
        receipt = self.historical([self.json_resource(path)])
        self.save(receipt)
        journal = self.context.paths.data/'journal'; journal.mkdir()
        state.save_recovery(journal/'intent.json', receipt)
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertTrue(any(f.code == 'rollback_unresolved' for f in result.findings))
        self.assertEqual(state.load(journal/'intent.json').resources, receipt.resources)
        self.assertEqual(json.loads(path.read_bytes()), {'ours':2,'foreign':9})

    def test_existing_omp_bootstrap_is_preserved_not_deleted(self):
        from iterm2_utils import skill_install
        isolated = skill_install._context(self.context, 'iterm2-setup')
        path = self.profile.agent_dir/'skills/iterm2-setup/SKILL.md'
        path.parent.mkdir(parents=True); path.write_bytes(b'owned omp skill')
        resource = self.resource('file', path, {'mode':0o644}, self.value(exists=False),
            self.value(base64.b64encode(b'owned omp skill').decode()), ('bootstrap-skill',))
        self.save(self.historical([resource], ('bootstrap-skill',), agents=('omp',)), isolated)
        migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        receipt = state.load(isolated.paths.data/'receipt.json')
        self.assertEqual(path.read_bytes(), b'owned omp skill')
        self.assertEqual(receipt.resources, [resource])
        self.assertEqual(receipt.legacy_cleanup, [])

    def test_exact_owned_shell_block_removal_preserves_foreign_lines(self):
        from iterm2_utils.config import zshrc
        path = self.context.paths.zshrc
        path.write_bytes(zshrc.block(b'# foreign shell line\n', 'root', 'source /owned/helper.zsh'))
        resource = self.resource('zsh', path, {'name':'root','mode':0o600},
            self.value(exists=False), self.value('source /owned/helper.zsh'))
        self.save(self.historical([resource]))
        migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(path.read_bytes(), b'# foreign shell line\n')

    def test_appearance_setting_transfer_keeps_original_inverse_without_claiming_install(self):
        path = self.context.paths.config/'appearance.json'; path.parent.mkdir()
        path.write_text('{"ours":1,"foreign":7}')
        resource = self.json_resource(path, owners=('codex:appearance',))
        self.save(self.historical([resource], ('appearance',)))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(json.loads(path.read_bytes()), {'ours':1,'foreign':7})
        self.assertEqual(result.receipt.resources[0]['before'], {'exists':True,'value':0})
        self.assertEqual(result.receipt.resources[0]['owners'], ['appearance'])
        self.assertNotIn('appearance', result.receipt.selection.features)

    def test_feature_pending_journal_is_not_overwritten_by_migration_bookkeeping(self):
        from iterm2_utils.models import Finding, Outcome
        self.save(self.historical([], ('status',)))
        journal = self.context.paths.data/'journal'
        def unknown(context, selection, runner):
            journal.mkdir()
            (journal/'intent.json').write_bytes(b'unknown-outcome-evidence')
            return Outcome(state.load(context.paths.data/'receipt.json'),
                [Finding('status','omp','native_outcome_unknown','conflict','Unknown native result.')])
        with patch.object(lifecycle, 'install', side_effect=unknown):
            result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual((journal/'intent.json').read_bytes(), b'unknown-outcome-evidence')
        self.assertFalse(any(f.code == 'migration_cleanup_complete' for f in result.findings))

    def test_source_shortcut_intent_is_not_retired_by_feature_name_alone(self):
        raw = legacy_state.encode(self.historical([], ('shortcuts',)))
        raw['selection']['shortcuts'] = ['resume']
        selection = Selection(frozenset({'shortcuts'}), frozenset(), 'Default', self.profile)
        self.save(Receipt('2', selection, [], [], [raw]))
        result = migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        self.assertEqual(result.receipt.legacy_cleanup[0]['selection']['shortcuts'], ['resume'])
        self.assertEqual(result.receipt.selection.shortcuts, frozenset())
