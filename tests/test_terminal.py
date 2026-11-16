import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from iterm2_utils.terminal import Terminal


class TerminalTests(unittest.TestCase):
    def terminal(self, windows=None, tabs=None, sessions=None):
        data={'window': windows if windows is not None else [dict(id='W')], 'tab': tabs if tabs is not None else [dict(id='T',window_id='W',index=0)], 'session': sessions if sessions is not None else [dict(id='S',tab_id='T',window_id='W')]}
        runner=SimpleNamespace(run=lambda argv,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(data[argv[1]])))
        return Terminal(Path('/selected/it2'),runner)

    def test_complete_inventory_selects_sole_window_not_focus(self):
        self.assertEqual(self.terminal().select_window('',{}),'W')
        self.assertEqual(self.terminal().panes(),[dict(terminal_id='S',tab_id='T',window_id='W')])

    def test_duplicate_or_incomplete_inventory_blocks(self):
        for change in (dict(sessions=[]),dict(sessions=[dict(id='S',tab_id='T',window_id='W')]*2),dict(tabs=[dict(id='T',window_id='W',index=2)])):
            with self.subTest(change=change),self.assertRaises(ValueError): self.terminal(**change).panes()

    def test_parent_sources_must_agree_and_no_focus_fallback(self):
        with self.assertRaises(ValueError): self.terminal().select_window('',dict(ITERM_SESSION_ID='w0t0p0:S',TERM_SESSION_ID='OTHER'))
        with self.assertRaises(ValueError): self.terminal(windows=[dict(id='W'),dict(id='W2')],tabs=[dict(id='T',window_id='W',index=0),dict(id='T2',window_id='W2',index=0)],sessions=[dict(id='S',tab_id='T',window_id='W'),dict(id='S2',tab_id='T2',window_id='W2')]).select_window('',{})

    def test_observe_merges_actual_moved_addresses_not_registry(self):
        terminal=self.terminal()
        terminal.sdk_observe=lambda sid: dict(terminal_id=sid,tab_id='moved',window_id='new',identity=json.dumps(dict(terminal_id=sid,tab_id='old',window_id='old',session_id='dialog')))
        observed=terminal.observe('S')
        self.assertEqual((observed['tab_id'],observed['window_id']),('moved','new'))
