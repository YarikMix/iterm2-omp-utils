import contextlib
import io
import json
import shutil
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from tests.support import Fixture
from tools import check_skill
from iterm2_utils import skill_install
from iterm2_utils.cli import main
from iterm2_utils.discovery import resolve_paths
from iterm2_utils.models import Context


class SkillInstallTests(unittest.TestCase):
    def context(self):
        return Context(resolve_paths(), {}, {}, frozenset(), {}, {})

    def invoke(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(['bootstrap-skill', *args, '--json'])
        return code, json.loads(out.getvalue()) if out.getvalue() else None

    def test_omp_bootstraps_all_bundles(self):
        for skill, files in (
                ('iterm2-setup', ('SKILL.md', 'references/features.md', 'references/ui.md', 'references/troubleshooting.md')),
                ('iterm2-launch', ('SKILL.md', 'references/handoff.md', 'references/resume.md')),
                ('iterm2-projects', ('SKILL.md', 'references/projects.md'))):
            with self.subTest(skill=skill), Fixture() as f:
                code, output = self.invoke('--skill', skill, '--agent', 'omp')
                self.assertEqual(code, 0, output)
                self.assertEqual(output['selection']['agents'], ['omp'])
                self.assertEqual(output['selection']['features'], [])
                target = f.home/'.omp/agent/skills'/skill
                for name in files:
                    self.assertEqual((target/name).read_bytes(),
                                     (resolve_paths().repo/'skills'/skill/name).read_bytes())
                self.assertFalse((f.home/'.codex').exists())
                self.assertFalse((f.home/'.claude').exists())
                self.assertFalse((resolve_paths().data/'receipt.json').exists())

    def test_omp_dry_run_has_no_writes_or_probes(self):
        with Fixture() as f:
            before = f.snapshot()
            with patch('iterm2_utils.cli.Runner', return_value=f.runner), \
                    patch('iterm2_utils.cli.discover', side_effect=AssertionError('agent inspection')):
                code, output = self.invoke('--agent', 'omp', '--dry-run')
            self.assertEqual(code, 0, output)
            self.assertEqual(f.snapshot(), before)
            self.assertEqual(f.runner.calls, [])

    def test_omp_profile_destination(self):
        for env, relative in (
                ({}, '.omp/agent'),
                ({'OMP_PROFILE': 'work'}, '.omp/profiles/work/agent'),
                ({'PI_PROFILE': 'legacy'}, '.omp/profiles/legacy/agent'),
                ({'OMP_PROFILE': 'work', 'PI_PROFILE': 'legacy'}, '.omp/profiles/work/agent'),
                ({'OMP_PROFILE': '', 'PI_PROFILE': 'legacy'}, '.omp/agent'),
                ({'OMP_PROFILE': '  ', 'PI_PROFILE': 'legacy'}, '.omp/agent'),
                ({'OMP_PROFILE': 'default'}, '.omp/agent'),
                ({'OMP_PROFILE': ' work '}, '.omp/profiles/work/agent'),
                ({'OMP_PROFILE': 'a'*64}, '.omp/profiles/'+'a'*64+'/agent'),
                ({'OMP_PROFILE': 'a.b_c-0'}, '.omp/profiles/a.b_c-0/agent')):
            with self.subTest(env=env), Fixture() as f, patch.dict('os.environ', env):
                code, output = self.invoke('--agent', 'omp')
                self.assertEqual(code, 0, output)
                self.assertTrue((f.home/relative/'skills/iterm2-setup/SKILL.md').is_file())

    def test_omp_invalid_profiles_fail_without_writes(self):
        for profile in ('.', '..', '../escape', 'a/b', 'a\\b', 'Work', 'a'*65,
                        'work.', 'con', 'prn.txt', 'aux', 'nul', 'com0', 'com9.txt', 'lpt0', 'lpt9'):
            with self.subTest(profile=profile), Fixture() as f, \
                    patch.dict('os.environ', {'OMP_PROFILE': profile}):
                before = f.snapshot()
                code, output = self.invoke('--agent', 'omp')
                self.assertEqual(code, 2, output)
                self.assertIsNotNone(output, 'Expected a structured conflict, not parser rejection')
                self.assertTrue(any(x['state'] == 'conflict' for x in output['findings']))
                self.assertEqual(f.snapshot(), before)

    def test_omp_directory_overrides(self):
        for env, relative in (
                ({'PI_CONFIG_DIR': ''}, '.omp/agent'),
                ({'PI_CONFIG_DIR': 'custom/config'}, 'custom/config/agent'),
                ({'PI_CONFIG_DIR': '/custom/config'}, 'custom/config/agent'),
                ({'PI_CONFIG_DIR': './custom/../config'}, 'config/agent'),
                ({'PI_CONFIG_DIR': 'custom', 'OMP_PROFILE': 'work'}, 'custom/profiles/work/agent'),
                ({'PI_CODING_AGENT_DIR': ''}, '.omp/agent'),
                ({'PI_CODING_AGENT_DIR': 'relative/agent'}, 'relative/agent'),
                ({'PI_CODING_AGENT_DIR': '~/agent'}, '~/agent'),
                ({'PI_CODING_AGENT_DIR': 'elsewhere', 'OMP_PROFILE': 'work'}, '.omp/profiles/work/agent')):
            with self.subTest(env=env), Fixture() as f, patch.dict('os.environ', env), \
                    contextlib.chdir(f.home):
                code, output = self.invoke('--agent', 'omp')
                self.assertEqual(code, 0, output)
                self.assertTrue((f.home/relative/'skills/iterm2-setup/SKILL.md').is_file())
        with Fixture() as f, patch.dict('os.environ', {'PI_CODING_AGENT_DIR': str(f.home/'absolute-agent')}):
            self.assertEqual(self.invoke('--agent', 'omp')[0], 0)
            self.assertTrue((f.home/'absolute-agent/skills/iterm2-setup/SKILL.md').is_file())
            self.assertFalse((f.home/'.omp').exists())

    def test_omp_owned_updates_and_conflicts(self):
        for case in ('modified', 'foreign', 'reference_symlink', 'corrupt_receipt'):
            with self.subTest(case=case), Fixture() as f:
                target = f.home/'.omp/agent/skills/iterm2-setup'
                if case == 'foreign':
                    target.mkdir(parents=True)
                    (target/'mine').write_text('foreign')
                else:
                    self.assertEqual(self.invoke('--agent', 'omp')[0], 0)
                    skill = target/'SKILL.md'
                    stamp = skill.stat().st_mtime_ns
                    self.assertEqual(self.invoke('--agent', 'omp')[0], 0)
                    self.assertEqual(skill.stat().st_mtime_ns, stamp)
                    if case == 'modified':
                        skill.write_text('user edit')
                    elif case == 'reference_symlink':
                        reference = target/'references/features.md'
                        reference.unlink()
                        foreign = f.home/'foreign.md'
                        foreign.write_text('foreign')
                        reference.symlink_to(foreign)
                    else:
                        (resolve_paths().data/'bootstrap-skill/receipt.json').write_text('{BROKEN')
                before = f.snapshot()
                code, output = self.invoke('--agent', 'omp')
                self.assertEqual(code, 2, output)
                self.assertEqual(f.snapshot(), before)

    def test_omp_cumulative_host_receipts(self):
        with Fixture() as f:
            context = self.context()
            source = f.home/'source'
            shutil.copytree(context.paths.repo/'skills/iterm2-setup', source/'skills/iterm2-setup')
            context.paths = replace(context.paths, repo=source)
            for host in ('codex', 'omp'):
                findings = skill_install.install(context, frozenset({host}), f.runner)
                self.assertFalse(any(x.state == 'conflict' for x in findings), findings)
            codex = f.home/'.codex/skills/iterm2-setup/references/features.md'
            omp = f.home/'.omp/agent/skills/iterm2-setup/references/features.md'
            codex.write_text('user edit in unselected host')
            (source/'skills/iterm2-setup/references/features.md').write_text('updated reference\n')
            findings = skill_install.install(context, frozenset({'omp'}), f.runner)
            self.assertFalse(any(x.state == 'conflict' for x in findings), findings)
            self.assertEqual(omp.read_text(), 'updated reference\n')
            self.assertEqual(codex.read_text(), 'user edit in unselected host')
            receipt = json.loads((context.paths.data/'bootstrap-skill/receipt.json').read_text())
            self.assertEqual(receipt['selection']['agents'], ['codex', 'omp'])
            targets = {r['target'] for r in receipt['resources']}
            self.assertIn(str(codex.resolve()), targets)
            self.assertIn(str(omp.resolve()), targets)
            self.assertFalse((context.paths.data/'receipt.json').exists())

    def test_existing_bootstraps_ignore_omp_environment(self):
        for agent in ('codex', 'claude', 'both'):
            with self.subTest(agent=agent), Fixture() as f, \
                    patch.dict('os.environ', {'OMP_PROFILE': '../invalid'}):
                self.assertEqual(self.invoke('--agent', agent)[0], 0)
                self.assertFalse((f.home/'.omp').exists())
                for host in (('codex', 'claude') if agent == 'both' else (agent,)):
                    self.assertTrue((f.home/('.'+host)/'skills/iterm2-setup/SKILL.md').is_file())
                before = f.snapshot()
                for command in ('plan', 'install'):
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(main([command, '--agent', 'omp', '--features', 'shell']), 2)
                self.assertEqual(f.snapshot(), before)

    def test_projects_bootstrap_selected_hosts(self):
        with Fixture() as f:
            code, out = self.invoke('--skill', 'iterm2-projects', '--agent', 'both')
            self.assertEqual(code, 0, out)
            self.assertEqual(out['selection']['features'], [])
            self.assertEqual(out['selection']['shortcuts'], [])
            for host in ('.codex', '.claude'):
                target = f.home/host/'skills/iterm2-projects'
                self.assertEqual(sorted(str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()),
                                 ['SKILL.md', 'references/projects.md'])
            self.assertTrue((resolve_paths().data/'bootstrap-skill-iterm2-projects/receipt.json').is_file())
            self.assertFalse((resolve_paths().data/'receipt.json').exists())

    def test_projects_dry_run_does_not_probe_or_write(self):
        with Fixture() as f:
            before = f.snapshot()
            with patch('iterm2_utils.cli.discover', side_effect=AssertionError('agent inspection')):
                code, out = self.invoke('--skill', 'iterm2-projects', '--agent', 'both', '--dry-run')
            self.assertEqual(code, 0, out)
            self.assertEqual(f.snapshot(), before)
            self.assertEqual(f.runner.calls, [])

    def test_projects_foreign_changes_are_preserved(self):
        with Fixture() as f:
            self.assertEqual(self.invoke('--skill', 'iterm2-projects', '--agent', 'codex')[0], 0)
            target = f.home/'.codex/skills/iterm2-projects/SKILL.md'
            target.write_text('user edit')
            before = f.snapshot()
            code, out = self.invoke('--skill', 'iterm2-projects', '--agent', 'codex')
            self.assertEqual(code, 2, out)
            self.assertEqual(f.snapshot(), before)
            self.assertEqual(target.read_text(), 'user edit')

    def test_default_bootstrap_retains_legacy_receipt(self):
        with Fixture() as f:
            code, output = self.invoke('--agent', 'both')
            self.assertEqual(code, 0, output)
            receipt = resolve_paths().data/'bootstrap-skill/receipt.json'
            resources = json.loads(receipt.read_text())['resources']
            self.assertEqual(len(resources), 8)
            self.assertTrue(all(r['owners'] == ['bootstrap-skill'] for r in resources))
            for agent in ('.codex', '.claude'):
                target = f.home/agent/'skills/iterm2-setup'
                self.assertEqual(sorted(str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()),
                                 ['SKILL.md', 'references/features.md', 'references/troubleshooting.md', 'references/ui.md'])
                for name in skill_install.FILES:
                    self.assertEqual((target/name).read_bytes(),
                                     (resolve_paths().repo/'skills/iterm2-setup'/name).read_bytes())
                self.assertFalse((f.home/agent/'skills/iterm2-launch').exists())
            self.assertFalse((resolve_paths().data/'bootstrap-skill-iterm2-launch').exists())

    def test_launch_bootstrap_rejects_unsupported_hosts(self):
        with Fixture() as f:
            context = self.context()
            before = f.snapshot()
            for agents in (frozenset({'claude'}), frozenset({'codex', 'claude'})):
                with self.subTest(agents=agents), \
                        patch('iterm2_utils.skill_install.state.load', side_effect=AssertionError('receipt inspection')), \
                        patch.object(Path, 'is_symlink', side_effect=AssertionError('file inspection')):
                    changes = skill_install.build(context, agents, skill='iterm2-launch')
                    self.assertEqual(changes.edits, [])
                    self.assertEqual(changes.findings[0].state, 'conflict')
                    findings = skill_install.install(context, agents, f.runner, skill='iterm2-launch')
                    self.assertEqual(findings[0].state, 'conflict')
                    code, output = self.invoke('--skill', 'iterm2-launch', '--agent',
                                               'both' if len(agents) == 2 else 'claude')
                    self.assertEqual(code, 2, output)
                    self.assertEqual(output['findings'][0]['state'], 'conflict')
            self.assertEqual(f.snapshot(), before)
            self.assertEqual(f.runner.calls, [])
            code, output = self.invoke('--skill', 'iterm2-launch', '--agent', 'codex')
            self.assertEqual(code, 0, output)
            target = f.home/'.codex/skills/iterm2-launch'
            self.assertEqual(sorted(str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()),
                             ['SKILL.md', 'references/handoff.md', 'references/resume.md'])
            for name in ('SKILL.md', 'references/handoff.md', 'references/resume.md'):
                self.assertEqual((target/name).read_bytes(),
                                 (context.paths.repo/'skills/iterm2-launch'/name).read_bytes())
                self.assertEqual((target/name).stat().st_mode & 0o777, 0o644)
            self.assertFalse((f.home/'.codex/skills/iterm2-setup').exists())
            self.assertFalse((f.home/'.claude').exists())
            self.assertTrue((context.paths.data/'bootstrap-skill-iterm2-launch/receipt.json').is_file())
            self.assertFalse((context.paths.data/'bootstrap-skill').exists())
            self.assertFalse((context.paths.data/'receipt.json').exists())

    def test_launch_update_copies_resume_reference_preserving_foreign_changes(self):
        # A legacy receipt must own updates without adopting a foreign new file.
        reference = Path(__file__).resolve().parents[1]/'skills/iterm2-launch/references/resume.md'
        self.assertTrue(reference.is_file(), 'resume reference missing from public bundle')
        for foreign in (False, True):
            with self.subTest(foreign=foreign), Fixture() as f:
                context = self.context()
                agents = frozenset({'codex'})
                legacy = ('SKILL.md', 'references/handoff.md')
                with patch.dict(skill_install.BUNDLES, {'iterm2-launch': legacy}):
                    findings = skill_install.install(context, agents, f.runner, skill='iterm2-launch')
                self.assertFalse(any(x.state == 'conflict' for x in findings), findings)
                target = context.paths.codex_home/'skills/iterm2-launch/references/resume.md'
                self.assertFalse(target.exists())
                if foreign:
                    target.write_text('user resume notes\n')
                before = f.snapshot()
                findings = skill_install.install(context, agents, f.runner, skill='iterm2-launch')
                if foreign:
                    self.assertTrue(any(x.state == 'conflict' for x in findings), findings)
                    self.assertEqual(f.snapshot(), before)
                    self.assertEqual(target.read_text(), 'user resume notes\n')
                else:
                    self.assertFalse(any(x.state == 'conflict' for x in findings), findings)
                    self.assertTrue(target.is_file(), 'owned update did not copy resume reference')
                    self.assertEqual(target.read_bytes(), reference.read_bytes())
                    receipt = context.paths.data/'bootstrap-skill-iterm2-launch/receipt.json'
                    resources = json.loads(receipt.read_text())['resources']
                    self.assertTrue(any(r['target'] == str(target.resolve()) for r in resources))
                    stamp = target.stat().st_mtime_ns
                    skill_install.install(context, agents, f.runner, skill='iterm2-launch')
                    self.assertEqual(target.stat().st_mtime_ns, stamp)

    def test_both_skill_receipts_coexist(self):
        for order in (('iterm2-setup', 'iterm2-launch'), ('iterm2-launch', 'iterm2-setup')):
            with self.subTest(order=order), Fixture() as f:
                with patch('iterm2_utils.cli.Runner', return_value=f.runner), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['install', '--agent', 'codex', '--features', 'shell', '--json']), 0)
                feature_receipt = resolve_paths().data/'receipt.json'
                feature_before = feature_receipt.read_bytes()
                for skill in order:
                    before = f.snapshot()
                    agent = 'both' if skill == 'iterm2-setup' else 'codex'
                    code, output = self.invoke('--skill', skill, '--agent', agent)
                    self.assertEqual(code, 0, output)
                    after = f.snapshot()
                    for path, content in before.items():
                        self.assertEqual(after[path], content, path)
                for receipt in ('bootstrap-skill/receipt.json', 'bootstrap-skill-iterm2-launch/receipt.json'):
                    self.assertTrue((resolve_paths().data/receipt).is_file())
                self.assertEqual(feature_receipt.read_bytes(), feature_before)
                skill_path = f.home/'.codex/skills/iterm2-launch/SKILL.md'
                stamp = skill_path.stat().st_mtime_ns
                before = f.snapshot()
                self.assertEqual(self.invoke('--skill', 'iterm2-launch', '--agent', 'codex')[0], 0)
                self.assertEqual(skill_path.stat().st_mtime_ns, stamp)
                self.assertEqual(f.snapshot(), before)

    def test_launch_dry_run_has_no_probes_or_writes(self):
        with Fixture() as f:
            before = f.snapshot()
            with patch('iterm2_utils.cli.Runner', return_value=f.runner), \
                    patch('iterm2_utils.cli.discover', side_effect=AssertionError('agent inspection')):
                code, output = self.invoke('--skill', 'iterm2-launch', '--agent', 'codex', '--dry-run')
            self.assertEqual(code, 0, output)
            self.assertEqual(output['mode'], 'bootstrap_preview')
            self.assertEqual(output['selection']['features'], [])
            self.assertEqual(f.snapshot(), before)
            self.assertEqual(f.runner.calls, [])

    def test_launch_foreign_modified_symlink_preserved(self):
        for case in ('foreign', 'modified', 'destination_symlink', 'reference_symlink', 'reference_directory_symlink', 'foreign_reference'):
            with self.subTest(case=case), Fixture() as f:
                target = f.home/'.codex/skills/iterm2-launch'
                foreign = f.home/'foreign'
                foreign.mkdir()
                (foreign/'handoff.md').write_text('foreign')
                if case == 'foreign':
                    target.mkdir(parents=True)
                    (target/'SKILL.md').write_text('foreign skill')
                elif case == 'destination_symlink':
                    target.parent.mkdir(parents=True)
                    target.symlink_to(foreign, target_is_directory=True)
                else:
                    self.assertEqual(self.invoke('--skill', 'iterm2-launch', '--agent', 'codex')[0], 0)
                    reference = target/'references/handoff.md'
                    if case == 'modified':
                        (target/'SKILL.md').write_text('user edit')
                    else:
                        reference.unlink()
                        if case == 'reference_symlink':
                            reference.symlink_to(foreign/'handoff.md')
                        elif case == 'reference_directory_symlink':
                            (reference.parent/'resume.md').unlink()
                            reference.parent.rmdir()
                            reference.parent.symlink_to(foreign, target_is_directory=True)
                        else:
                            reference.write_text('foreign reference')
                before = f.snapshot()
                for extra in ((), ('--dry-run',)):
                    code, output = self.invoke('--skill', 'iterm2-launch', '--agent', 'codex', *extra)
                    self.assertEqual(code, 2, output)
                    self.assertTrue(any(x['state'] == 'conflict' for x in output['findings']))
                    self.assertEqual(f.snapshot(), before)
                link = {'destination_symlink': target,
                        'reference_directory_symlink': target/'references',
                        'reference_symlink': target/'references/handoff.md'}.get(case)
                if link is not None:
                    self.assertTrue(link.is_symlink())

    def test_unknown_skill_is_rejected_before_inspection(self):
        with Fixture() as f:
            context = self.context()
            before = f.snapshot()
            with patch('iterm2_utils.skill_install.state.load', side_effect=AssertionError('receipt inspection')), \
                    patch.object(Path, 'is_symlink', side_effect=AssertionError('file inspection')):
                changes = skill_install.build(context, frozenset({'codex'}), skill='../foreign')
                self.assertEqual(changes.edits, [])
                self.assertEqual(changes.findings[0].state, 'conflict')
                findings = skill_install.install(context, frozenset({'codex'}), f.runner, skill='../foreign')
                self.assertEqual(findings[0].state, 'conflict')
                self.assertEqual(self.invoke('--skill', '../foreign', '--agent', 'codex')[0], 2)
            self.assertEqual(f.snapshot(), before)

    def test_skill_install_does_not_replace_foreign_directory(self):
        with Fixture() as f:
            dest = f.home/'.codex/skills/iterm2-setup'
            dest.mkdir(parents=True)
            (dest/'mine').write_text('foreign')
            before = f.snapshot()
            changes = skill_install.build(self.context(), frozenset({'codex'}))
            self.assertEqual(changes.edits, [])
            self.assertTrue(any(x.state == 'conflict' for x in changes.findings))
            self.assertEqual(before, f.snapshot())

    def test_bootstrap_uses_actual_home_and_codex_home(self):
        with Fixture() as f, patch.dict('os.environ', {'CODEX_HOME': str(f.home/'custom-codex')}):
            code, output = self.invoke('--agent', 'codex')
            self.assertEqual(code, 0, output)
            self.assertTrue((f.home/'custom-codex/skills/iterm2-setup/SKILL.md').is_file())
            self.assertFalse((f.home/'.codex').exists())
            self.assertFalse((f.home/'.claude').exists())
            self.assertEqual(output['selection']['features'], [])

    def test_dry_run_has_no_writes_or_agent_probes(self):
        with Fixture() as f:
            before = f.snapshot()
            with patch('iterm2_utils.cli.Runner', return_value=f.runner):
                code, output = self.invoke('--agent', 'both', '--dry-run')
            self.assertEqual(code, 0, output)
            self.assertEqual(before, f.snapshot())
            self.assertEqual(f.runner.calls, [])

    def test_owned_update_idempotence_and_user_changes_preserved(self):
        with Fixture() as f:
            self.assertEqual(self.invoke('--agent', 'codex')[0], 0)
            path = f.home/'.codex/skills/iterm2-setup/SKILL.md'
            stamp = path.stat().st_mtime_ns
            self.assertEqual(self.invoke('--agent', 'codex')[0], 0)
            self.assertEqual(stamp, path.stat().st_mtime_ns)
            path.write_text('user edit')
            self.assertEqual(self.invoke('--agent', 'codex', '--dry-run')[0], 2)
            self.assertEqual(self.invoke('--agent', 'codex')[0], 2)
            self.assertEqual(path.read_text(), 'user edit')

    def test_second_agent_is_only_installed_when_selected(self):
        with Fixture() as f:
            self.assertEqual(self.invoke('--agent', 'claude')[0], 0)
            self.assertFalse((f.home/'.codex').exists())
            first = (f.home/'.claude/skills/iterm2-setup/SKILL.md').read_bytes()
            self.assertEqual(self.invoke('--agent', 'codex')[0], 0)
            self.assertEqual((f.home/'.claude/skills/iterm2-setup/SKILL.md').read_bytes(), first)
            self.assertTrue((f.home/'.codex/skills/iterm2-setup/SKILL.md').is_file())

    def test_symlink_target_is_foreign(self):
        with Fixture() as f:
            dest = f.home/'.codex/skills/iterm2-setup'
            dest.parent.mkdir(parents=True)
            target = f.home/'foreign'; target.mkdir()
            dest.symlink_to(target, target_is_directory=True)
            code, _ = self.invoke('--agent', 'codex')
            self.assertEqual(code, 2)
            self.assertEqual(list(target.iterdir()), [])

    def test_bootstrap_does_not_change_feature_receipt(self):
        with Fixture() as f:
            with patch('iterm2_utils.cli.Runner', return_value=f.runner), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['install','--agent','codex','--features','shell','--json']), 0)
            path = resolve_paths().data/'receipt.json'
            before = path.read_bytes()
            self.assertEqual(self.invoke('--agent', 'codex')[0], 0)
            self.assertEqual(path.read_bytes(), before)

    def test_owned_source_update_copies_all_references(self):
        for skill, files, reference in (
                ('iterm2-setup', skill_install.FILES, 'references/features.md'),
                ('iterm2-launch', ('SKILL.md', 'references/handoff.md', 'references/resume.md'), 'references/handoff.md')):
            with self.subTest(skill=skill), Fixture() as f:
                context = self.context()
                bundle = f.home/'source/skills'/skill
                for name in files:
                    source = context.paths.repo/'skills'/skill/name
                    target = bundle/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
                context.paths = replace(context.paths, repo=f.home/'source')
                self.assertEqual(skill_install.install(context, frozenset({'codex'}), f.runner, skill=skill)[0].state, 'ready')
                (bundle/reference).write_text('updated reference\n')
                findings = skill_install.install(context, frozenset({'codex'}), f.runner, skill=skill)
                self.assertFalse(any(x.state == 'conflict' for x in findings), findings)
                target = context.paths.codex_home/'skills'/skill
                self.assertEqual((target/reference).read_text(), 'updated reference\n')
                self.assertEqual(sorted(str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()), sorted(files))

    def test_launch_structural_examples_reject_bare_codex_as_resume(self):
        with Fixture() as f:
            root = f.home/'iterm2-launch'
            shutil.copytree(resolve_paths().repo/'skills/iterm2-launch', root)
            self.assertEqual(check_skill.check(root), [])
            reference = root/'references/resume.md'
            reference.write_text(reference.read_text().replace('"matches": false', '"matches": true'))
            self.assertIn('Invalid launch command examples', check_skill.check(root))

    def test_corrupt_bootstrap_receipt_blocks_copy(self):
        for skill, receipt in (('iterm2-setup', 'bootstrap-skill'),
                               ('iterm2-launch', 'bootstrap-skill-iterm2-launch')):
            with self.subTest(skill=skill), Fixture() as f:
                path = resolve_paths().data/receipt/'receipt.json'
                path.parent.mkdir(parents=True)
                path.write_text('{BROKEN')
                before = f.snapshot()
                args = () if skill == 'iterm2-setup' else ('--skill', skill)
                code, output = self.invoke('--agent', 'codex', *args)
                self.assertEqual(code, 2)
                self.assertEqual(before, f.snapshot())
                self.assertNotIn('BROKEN', str(output))

    def test_foreign_reference_symlink_and_file_are_not_adopted(self):
        with Fixture() as f:
            self.assertEqual(self.invoke('--agent', 'codex')[0], 0)
            target = f.home/'.codex/skills/iterm2-setup/references/features.md'
            target.unlink()
            foreign = f.home/'foreign.md'; foreign.write_text('foreign')
            target.symlink_to(foreign)
            code, _ = self.invoke('--agent', 'codex')
            self.assertEqual(code, 2)
            self.assertEqual(foreign.read_text(), 'foreign')
