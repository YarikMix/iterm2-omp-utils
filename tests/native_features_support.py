"""Isolated native integration fixture; parser subprocesses use temporary HOME."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from iterm2_utils.commands import Runner
from iterm2_utils.models import Context, OmpProfile, Paths, Selection

REPO = Path(__file__).resolve().parents[1]


class NativeFixture(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        env = patch.dict(os.environ, {'HOME': str(self.home)}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.profile = OmpProfile('work', self.home/'.omp/profiles/work/agent')
        self.profile.agent_dir.mkdir(parents=True)
        self.runner = Runner()
        paths = Paths(self.home, self.home/'.zshrc', self.home/'config', self.home/'cache',
                      self.home/'data', self.home/'profiles', REPO)
        self.context = Context(paths, {name:self.home/name for name in ('iterm2','zsh','bun','omp','python3','uvx')},
            {'omp':'99.0.0','python3':'3.11.9','iterm2':'99.0.0'},
            frozenset({'macos','python:iterm2','iterm2:osc7501','iterm2:osc9','omp:resume'}),
            {'Default':{'Name':'Default','Guid':'parent','Keyboard Map':{}}}, {},
            omp_profile=self.profile)

    def selection(self, *features, shortcuts=(), resume_key=None, notify_errors=False):
        return Selection(frozenset(features), frozenset(shortcuts), 'Default', self.profile,
                         resume_key=resume_key, notify_errors=notify_errors)

    def assertSuccess(self, result):
        self.assertFalse([f for f in result.findings if f.state in {'conflict','missing_dependency','unavailable'}])
