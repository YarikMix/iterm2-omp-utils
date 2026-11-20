import contextlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from iterm2_utils.models import OmpProfile
from iterm2_utils.omp_profile import resolve_omp_profile


class OmpProfileTests(unittest.TestCase):
    def test_profile_precedence_and_default_normalization(self):
        home = Path('/fixture/home')
        for env, explicit, expected in (
                ({'OMP_PROFILE': 'work', 'PI_PROFILE': 'other'}, None, 'work'),
                ({'PI_PROFILE': 'other'}, None, 'other'),
                ({'OMP_PROFILE': '', 'PI_PROFILE': 'other'}, None, None),
                ({'OMP_PROFILE': ' default '}, None, None),
                ({'OMP_PROFILE': 'work'}, '', None),
                ({'OMP_PROFILE': 'work'}, ' chosen ', 'chosen')):
            with self.subTest(env=env, explicit=explicit):
                result = resolve_omp_profile(home, env, explicit)
                destination = home/'.omp/agent' if expected is None else home/'.omp/profiles'/expected/'agent'
                self.assertEqual(result, OmpProfile(expected, destination))

    def test_named_profile_ignores_default_agent_dir_override(self):
        home = Path('/fixture/home')
        self.assertEqual(resolve_omp_profile(home, {'OMP_PROFILE':'work', 'PI_CODING_AGENT_DIR':'/foreign'}).agent_dir,
                         home/'.omp/profiles/work/agent')

    def test_directory_overrides_match_node_path_rules(self):
        with TemporaryDirectory() as root, contextlib.chdir(root):
            home = Path(root).resolve()
            for env, expected in (
                    ({'PI_CONFIG_DIR':'/custom/config'}, home/'custom/config/agent'),
                    ({'PI_CONFIG_DIR':'./custom/../config'}, home/'config/agent'),
                    ({'PI_CONFIG_DIR':''}, home/'.omp/agent'),
                    ({'PI_CODING_AGENT_DIR':'relative/agent'}, home/'relative/agent'),
                    ({'PI_CODING_AGENT_DIR':'~/agent'}, home/'~/agent'),
                    ({'PI_CODING_AGENT_DIR':'/absolute/agent'}, Path('/absolute/agent'))):
                with self.subTest(env=env):
                    self.assertEqual(resolve_omp_profile(home, env).agent_dir, expected)

    def test_invalid_profiles_fail_without_writes(self):
        with TemporaryDirectory() as root:
            home = Path(root)
            for name in ('.', '..', '../escape', 'a/b', 'a\\b', 'Work', 'a'*65, 'work.',
                         'con', 'prn.txt', 'aux', 'nul', 'com0', 'com9.txt', 'lpt0', 'lpt9'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    resolve_omp_profile(home, {'OMP_PROFILE':name})
            self.assertEqual(list(home.iterdir()), [])
