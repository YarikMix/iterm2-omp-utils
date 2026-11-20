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

    def test_job_pid_decodes_integer_without_changing_string_variables(self):
        calls=[]
        def run(argv,**kwargs):
            calls.append((argv,kwargs))
            value=123 if argv[3]=='session.jobPid' else '/dev/ttys007'
            return SimpleNamespace(returncode=0,stdout=json.dumps(value))
        terminal=Terminal(Path('/selected/it2'),SimpleNamespace(run=run))
        self.assertEqual(terminal.job_pid('S'),123)
        self.assertEqual(terminal.variable('S','tty'),'/dev/ttys007')
        self.assertEqual(calls[0],(['/selected/it2','session','get-var','session.jobPid','--session','S'],{'timeout':10}))
        with self.assertRaises(ValueError):terminal.variable('S','session.jobPid')

    def test_job_pid_rejects_missing_bool_nonpositive_and_string_values(self):
        for value in (None,True,False,0,-1,'123',1.5,{},[]):
            with self.subTest(value=value):
                runner=SimpleNamespace(run=lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(value)))
                with self.assertRaises(ValueError):Terminal(Path('/it2'),runner).job_pid('S')
