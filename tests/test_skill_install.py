"""Current omp bootstrap copies and independent historical ownership."""
from unittest.mock import patch
from iterm2_utils import skill_install, state
from iterm2_utils.models import OmpProfile
from tests.test_migration import MigrationFixture


class SkillInstallTests(MigrationFixture):
    def test_three_bundles_install_only_in_selected_omp_profile(self):
        self.context.omp_profile = OmpProfile('work', self.home/'.omp/profiles/work/agent')
        for skill, files in skill_install.BUNDLES.items():
            findings = skill_install.install(self.context, self.runner, skill=skill)
            self.assertFalse(any(f.state == 'conflict' for f in findings), findings)
            destination = self.context.omp_profile.agent_dir/'skills'/skill
            self.assertEqual(sorted(str(path.relative_to(destination)) for path in destination.rglob('*')
                                    if path.is_file()), sorted(files))
            for name in files:
                self.assertEqual((destination/name).read_bytes(),
                                 (self.context.paths.repo/'skills'/skill/name).read_bytes())
                self.assertEqual((destination/name).stat().st_mode & 0o777, 0o644)
            receipt = state.load(skill_install._context(self.context, skill).paths.data/'receipt.json')
            self.assertEqual(receipt.selection.omp_profile, self.context.omp_profile)
        self.assertFalse((self.home/'.codex').exists())
        self.assertFalse((self.home/'.claude').exists())
        self.assertFalse((self.context.paths.data/'receipt.json').exists())
        self.assertEqual(self.runner.calls, [])

    def test_dry_run_never_recovers_journal_or_probes_agent(self):
        isolated = skill_install._context(self.context, 'iterm2-setup')
        journal = isolated.paths.data/'journal'; journal.mkdir(parents=True)
        (journal/'phase').write_bytes(b'commit')
        before = self.snapshot()
        skill_install.install(self.context, self.runner, dry_run=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.runner.calls, [])

    def test_historical_bootstrap_requires_migration_not_implicit_upgrade(self):
        isolated = skill_install._context(self.context, 'iterm2-setup')
        self.save(self.historical([], ('bootstrap-skill',)), isolated)
        before = self.snapshot()
        findings = skill_install.install(self.context, self.runner)
        self.assertTrue(any(f.code == 'migration_required' for f in findings))
        self.assertEqual(self.snapshot(), before)

    def test_owned_update_is_idempotent_and_preserves_changed_file(self):
        skill_install.install(self.context, self.runner)
        target = self.profile.agent_dir/'skills/iterm2-setup/SKILL.md'
        stamp = target.stat().st_mtime_ns
        findings = skill_install.install(self.context, self.runner)
        self.assertFalse(any(f.state == 'conflict' for f in findings))
        self.assertEqual(target.stat().st_mtime_ns, stamp)
        target.write_text('user notes')
        before = self.snapshot()
        for dry_run in (True, False):
            findings = skill_install.install(self.context, self.runner, dry_run=dry_run)
            self.assertTrue(any(f.state == 'conflict' for f in findings))
            self.assertEqual(target.read_text(), 'user notes')
            self.assertEqual(self.snapshot(), before)

    def test_owned_update_adds_new_reference_but_does_not_adopt_foreign_file(self):
        for foreign in (False, True):
            skill = 'iterm2-launch' if not foreign else 'iterm2-projects'
            original = skill_install.BUNDLES[skill]
            with patch.dict(skill_install.BUNDLES, {skill:('SKILL.md',)}):
                skill_install.install(self.context, self.runner, skill=skill)
            target = self.profile.agent_dir/'skills'/skill/original[-1]
            if foreign:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('foreign reference')
            findings = skill_install.install(self.context, self.runner, skill=skill)
            if foreign:
                self.assertTrue(any(f.state == 'conflict' for f in findings))
                self.assertEqual(target.read_text(), 'foreign reference')
            else:
                self.assertFalse(any(f.state == 'conflict' for f in findings), findings)
                self.assertEqual(target.read_bytes(), (self.context.paths.repo/'skills'/skill/original[-1]).read_bytes())

    def test_profile_change_cannot_reassign_existing_skill_ownership(self):
        skill_install.install(self.context, self.runner)
        self.context.omp_profile = OmpProfile('other', self.home/'.omp/profiles/other/agent')
        findings = skill_install.install(self.context, self.runner)
        self.assertTrue(any(f.code == 'skill_profile_conflict' for f in findings))
        self.assertFalse(self.context.omp_profile.agent_dir.exists())

    def test_foreign_skill_symlink_is_preserved(self):
        destination = self.profile.agent_dir/'skills/iterm2-setup'
        foreign = self.home/'foreign'; foreign.mkdir()
        destination.parent.mkdir(parents=True)
        destination.symlink_to(foreign, target_is_directory=True)
        findings = skill_install.install(self.context, self.runner)
        self.assertTrue(any(f.state == 'conflict' for f in findings))
        self.assertEqual(list(foreign.iterdir()), [])
        self.assertTrue(destination.is_symlink())

    def test_current_bootstrap_recovers_before_planning_update(self):
        skill_install.install(self.context, self.runner)
        isolated = skill_install._context(self.context, 'iterm2-setup')
        receipt = state.load(isolated.paths.data/'receipt.json')
        target = self.profile.agent_dir/'skills/iterm2-setup/SKILL.md'
        original = target.read_bytes()
        journal = isolated.paths.data/'journal'; journal.mkdir()
        state.save(journal/'result.json', receipt)
        (journal/'phase').write_bytes(b'commit')
        (isolated.paths.data/'receipt.json').unlink()
        findings = skill_install.install(self.context, self.runner)
        self.assertFalse(any(f.state == 'conflict' for f in findings), findings)
        self.assertFalse(journal.exists())
        self.assertEqual(target.read_bytes(), original)

    def test_invalid_skill_does_not_recover_feature_journal(self):
        journal = self.context.paths.data/'journal'; journal.mkdir(parents=True)
        (journal/'phase').write_bytes(b'commit')
        before = self.snapshot()
        findings = skill_install.install(self.context, self.runner, skill='../foreign')
        self.assertTrue(any(f.code == 'invalid_skill' for f in findings))
        self.assertEqual(self.snapshot(), before)

    def test_changed_existing_omp_bootstrap_is_preserved_after_resolution(self):
        import base64
        from iterm2_utils import migration
        isolated = skill_install._context(self.context, 'iterm2-setup')
        path = self.profile.agent_dir/'skills/iterm2-setup/SKILL.md'
        path.parent.mkdir(parents=True); path.write_bytes(b'user edit')
        resource = self.resource('file', path, {'mode':0o644}, self.value(exists=False),
            self.value(base64.b64encode(b'owned omp skill').decode()), ('bootstrap-skill',))
        self.save(self.historical([resource], ('bootstrap-skill',), agents=('omp',)), isolated)
        migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        stored = state.load(isolated.paths.data/'receipt.json')
        self.assertEqual(stored.legacy_cleanup[0]['resources'], [resource])
        path.write_bytes(b'owned omp skill')
        migration.migrate_to_omp(self.context, self.runner, dry_run=False)
        stored = state.load(isolated.paths.data/'receipt.json')
        self.assertEqual(stored.resources, [resource])
        self.assertEqual(stored.legacy_cleanup, [])
        self.assertEqual(path.read_bytes(), b'owned omp skill')
