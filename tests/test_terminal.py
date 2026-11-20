import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import os
from unittest.mock import patch
from runtime import terminal_identity
from iterm2_utils.terminal import _visible_inventory
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

    def shell_fixture(self):
        pane=dict(terminal_id='S',tab_id='T',window_id='W')
        sample={**pane,'identity':None,'pid':123,'job_pid':123,'tty':'/dev/ttys007'}
        state=dict(sample=sample,ps=f'123 1 {os.getuid()} S+\n124 123 {os.getuid()} S\n',
                   holders='123\n',alias='',alias_code=1,stderr='',birth='birth',image='/bin/zsh',
                   canonical='124 ttys007\n')
        calls=[]
        def run(argv,**kw):
            calls.append((argv,kw))
            if argv[0]=='/bin/ps':
                text=state['ps'] if '-t' in argv else state['canonical']
                return SimpleNamespace(returncode=0,stdout=text,stderr=state['stderr'])
            if argv[0]=='/usr/sbin/lsof':
                alias=argv[-1]=='/dev/tty'
                return SimpleNamespace(returncode=state['alias_code'] if alias else 0,
                    stdout=state['alias'] if alias else state['holders'],stderr=state['stderr'])
            return SimpleNamespace(returncode=0,stdout=json.dumps(123 if argv[3]=='session.jobPid' else '/dev/ttys007'))
        terminal=Terminal(Path('/it2'),SimpleNamespace(run=run))
        terminal.sdk_observe=lambda sid:dict(state['sample'])
        terminal.process_start=lambda pid:state['birth']
        terminal.process_image=lambda pid:state['image']
        terminal.process_executable_path=lambda pid:state.get('root_image')
        terminal.foreground_process=lambda *a:True
        return terminal,pane,state,calls

    def test_literal_null_is_benign_but_not_identity_proof(self):
        terminal=self.terminal()
        for identity in (None,'null','{bad',False,[],{}):
            with self.subTest(identity=identity):
                terminal.sdk_observe=lambda sid:dict(terminal_id=sid,tab_id='T',window_id='W',identity=identity)
                self.assertIsNone(terminal.observe('S'))

    def test_idle_root_shell_allows_prompt_worker_without_tty_access(self):
        terminal,pane,state,calls=self.shell_fixture()
        self.assertTrue(terminal.ordinary_shell(pane,Path('/bin/zsh')))
        self.assertIn((['/usr/sbin/lsof','-nP','-t','+w','-a','-p','124','--','/dev/tty'],{'timeout':10}),calls)
        self.assertGreaterEqual(sum(argv[0]=='/bin/ps' and '-t' in argv for argv,kw in calls),2)
        state.update(alias='124\n',alias_code=0)
        self.assertTrue(terminal.ordinary_shell(pane,Path('/bin/zsh')))

    def test_shell_exclusion_rejects_ambiguous_and_attached_processes(self):
        uid=os.getuid()
        faults=('stopped','foreign','holder','alias','diagnostic','alias-failed','malformed-ps',
                'wrong-image','missing-birth','pid','job','tty','scope','missing-identity','encoded-null','identity',
                'empty-canonical','wrong-canonical','alias-outside','alias-empty-success','traced')
        for fault in faults:
            with self.subTest(fault=fault):
                terminal,pane,state,calls=self.shell_fixture()
                if fault=='stopped':state['ps']=f'123 1 {uid} S+\n124 123 {uid} T\n'
                if fault=='foreign':state['ps']=f'123 1 {uid} S+\n124 123 {uid+1} S\n'
                if fault=='holder':state['holders']='123\n124\n'
                if fault=='alias':
                    state.update(alias='124\n',alias_code=0)
                    terminal.process_image=lambda pid:'/bin/bun' if pid==124 else '/bin/zsh'
                if fault=='diagnostic':state['stderr']='warning'
                if fault=='alias-failed':state['alias_code']=2
                if fault=='empty-canonical':state['canonical']=''
                if fault=='wrong-canonical':state['canonical']='124 ttys008\n'
                if fault=='alias-outside':state.update(alias='999\n',alias_code=0)
                if fault=='alias-empty-success':state['alias_code']=0
                if fault=='traced':state['ps']=f'123 1 {uid} S+\n124 123 {uid} SX\n'
                if fault=='malformed-ps':state['ps']='incomplete'
                if fault=='wrong-image':state['image']='/bin/bun'
                if fault=='missing-birth':state['birth']=None
                if fault=='pid':state['sample']['pid']=124
                if fault=='job':state['sample']['job_pid']=True
                if fault=='tty':state['sample']['tty']='/dev/tty'
                if fault=='scope':state['sample']['tab_id']='other'
                if fault=='missing-identity':del state['sample']['identity']
                if fault=='encoded-null':state['sample']['identity']='null'
                if fault=='identity':state['sample']['identity']='{}'
                self.assertFalse(terminal.ordinary_shell(pane,Path('/bin/zsh')))

    def test_shell_rechecks_scoped_samples_and_deadline(self):
        for fault in ('scope','birth','foreground','deadline'):
            with self.subTest(fault=fault):
                terminal,pane,state,calls=self.shell_fixture()
                original=terminal.process_image
                def image(pid):
                    if fault=='scope':state['sample']['window_id']='changed'
                    if fault=='birth':state['birth']='changed'
                    if fault=='foreground':terminal.foreground_process=lambda *a:False
                    if fault=='deadline':terminal.deadline=0
                    return original(pid)
                terminal.process_image=image
                self.assertFalse(terminal.ordinary_shell(pane,Path('/bin/zsh')))

    def test_complete_inventory_requires_matching_stable_visible_sets(self):
        pane=dict(terminal_id='S',tab_id='T',window_id='W')
        for fault in ('none','partial','changed','failed'):
            with self.subTest(fault=fault):
                terminal=self.terminal()
                samples=iter([[pane],[{**pane,'terminal_id':'changed'}] if fault=='changed' else [pane]])
                terminal.panes=lambda:next(samples)
                terminal._run=lambda argv: ([pane] if fault=='none' else [] if fault=='partial' else
                    [pane] if fault=='changed' else None)
                if fault=='none':self.assertEqual(terminal.complete_panes(),[pane])
                else:
                    with self.assertRaises(ValueError):terminal.complete_panes()

    def test_raw_sdk_inventory_rejects_hidden_minimized_mux_and_malformed_tree(self):
        def proto(**kw):
            return SimpleNamespace(**kw,HasField=lambda name:name in kw)
        session=proto(unique_identifier='S')
        link=proto(session=session)
        link.WhichOneof=lambda name:'session'
        root=proto(links=[link])
        tab=proto(tab_id='T',root=root,minimized_sessions=[],active_session_id='S')
        window=proto(window_id='W',tabs=[tab])
        snapshot=proto(windows=[window],buried_sessions=[])
        response=proto(list_sessions_response=snapshot)
        self.assertEqual(_visible_inventory(response),[dict(terminal_id='S',tab_id='T',window_id='W')])
        for fault in ('buried','minimized','mux','missing-root','invalid-link','duplicate','cycle','active'):
            with self.subTest(fault=fault):
                snapshot.buried_sessions=[session] if fault=='buried' else []
                tab.minimized_sessions=[session] if fault=='minimized' else []
                tab.HasField=lambda name:(name=='root' and fault!='missing-root' or
                                         name=='tmux_connection_id' and fault=='mux')
                link.WhichOneof=lambda name:None if fault=='invalid-link' else 'node' if fault=='cycle' else 'session'
                link.node=root
                root.links=[link,link] if fault=='duplicate' else [link]
                tab.active_session_id='unknown' if fault=='active' else 'S'
                with self.assertRaises(ValueError):_visible_inventory(response)

    def test_alias_shell_birth_image_and_census_must_remain_stable(self):
        for fault in ('birth','image','census','missing'):
            with self.subTest(fault=fault):
                terminal,pane,state,calls=self.shell_fixture()
                state.update(alias='124\n',alias_code=0)
                reads=[]
                def image(pid):
                    if pid==124:
                        reads.append(True)
                        if fault=='birth':terminal.process_start=lambda p:'changed' if p==124 else 'birth'
                        if fault=='census':state['ps']=f'123 1 {os.getuid()} S+\n'
                        if fault=='missing':return None
                        if fault=='image' and len(reads)>1:return '/bin/bun'
                    return '/bin/zsh'
                terminal.process_image=image
                self.assertFalse(terminal.ordinary_shell(pane,Path('/bin/zsh')))

    def test_sdk_identity_scope_and_missing_values_never_screen_shell(self):
        for field,value in (('terminal_id','other'),('window_id',''),('tab_id',None),
                            ('pid',None),('job_pid',0),('tty',''),('tty','/dev/ttys007/../tty')):
            with self.subTest(field=field,value=value):
                terminal,pane,state,calls=self.shell_fixture()
                state['sample'][field]=value
                self.assertFalse(terminal.ordinary_shell(pane,Path('/bin/zsh')))

    def test_failed_or_expired_process_probe_cannot_screen_shell(self):
        for failure in (TimeoutError('probe timeout'),OSError('probe unavailable')):
            with self.subTest(failure=type(failure).__name__):
                terminal,pane,state,calls=self.shell_fixture()
                def failed(*args,**kwargs):raise failure
                terminal.runner.run=failed
                self.assertFalse(terminal.ordinary_shell(pane,Path('/bin/zsh')))

    def test_sdk_inventory_accepts_nested_visible_splits(self):
        def proto(**kw):return SimpleNamespace(**kw,HasField=lambda name:name in kw)
        def leaf(sid):
            return SimpleNamespace(session=proto(unique_identifier=sid),WhichOneof=lambda name:'session')
        child=SimpleNamespace(node=proto(links=[leaf('B')]),WhichOneof=lambda name:'node')
        tab=proto(tab_id='T',root=proto(links=[leaf('A'),child]),minimized_sessions=[],active_session_id='A')
        response=proto(list_sessions_response=proto(buried_sessions=[],windows=[proto(window_id='W',tabs=[tab])]))
        self.assertEqual(_visible_inventory(response),[
            dict(terminal_id='A',tab_id='T',window_id='W'),dict(terminal_id='B',tab_id='T',window_id='W')])

    def test_sdk_inventory_accepts_only_absent_or_exact_non_mux_sentinel(self):
        def proto(**kw):return SimpleNamespace(**kw,HasField=lambda name:name in kw)
        absent=object()
        for value in (absent,'-1','0','1','-2','',None,-1):
            for connection in (absent,'','connection'):
                with self.subTest(value=value,connection=connection):
                    link=SimpleNamespace(session=proto(unique_identifier='S'),
                                         WhichOneof=lambda name:'session')
                    fields=dict(tab_id='T',root=proto(links=[link]),
                                minimized_sessions=[],active_session_id='S')
                    if value is not absent:fields['tmux_window_id']=value
                    if connection is not absent:fields['tmux_connection_id']=connection
                    response=proto(list_sessions_response=proto(buried_sessions=[],
                        windows=[proto(window_id='W',tabs=[proto(**fields)])]))
                    if connection is absent and (value is absent or value=='-1'):
                        self.assertEqual(_visible_inventory(response),
                            [dict(terminal_id='S',tab_id='T',window_id='W')])
                    else:
                        with self.assertRaises(ValueError):_visible_inventory(response)

    def login_fixture(self):
        terminal,pane,state,calls=self.shell_fixture()
        state['sample']['pid']=122
        state['root_image']='/usr/bin/login'
        state['ps']=f'122 1 0 Ss\n123 122 {os.getuid()} S+\n124 123 {os.getuid()} S\n'
        def birth(pid):
            if pid==122:raise AssertionError('Protected login birth is unavailable')
            return state['birth']
        terminal.process_start=birth
        return terminal,pane,state,calls

    def test_native_login_supervisor_allows_exact_direct_foreground_zsh(self):
        terminal,pane,state,calls=self.login_fixture()
        state.update(alias='124\n',alias_code=0)
        self.assertTrue(terminal.ordinary_shell(pane,Path('/bin/zsh')))
        self.assertGreaterEqual(sum(argv==['/bin/ps','-t','/dev/ttys007','-o','pid=,ppid=,uid=,state=']
                                    for argv,kwargs in calls),2)

    def test_login_supervisor_requires_exact_kernel_image_uid_parent_and_state(self):
        for fault in ('image','basename','missing-image','uid','parent','stopped','foreign',
                      'holder','missing-root','job-image','changed-parent','changed-root-image',
                      'changed-root','changed-job','changed-birth','changed-state','changed-tty'):
            with self.subTest(fault=fault):
                terminal,pane,state,calls=self.login_fixture()
                uid=os.getuid()
                if fault=='image':state['root_image']='/usr/bin/other'
                if fault=='basename':state['root_image']='login'
                if fault=='missing-image':state['root_image']=None
                if fault=='uid':state['ps']=f'122 1 {uid} Ss\n123 122 {uid} S+\n'
                if fault=='parent':state['ps']=f'122 1 0 Ss\n123 999 {uid} S+\n'
                if fault=='stopped':state['ps']=f'122 1 0 T\n123 122 {uid} S+\n'
                if fault=='foreign':state['ps']+=f'125 1 {uid+1} S\n'
                if fault=='holder':state['holders']='122\n123\n'
                if fault=='missing-root':state['ps']=f'123 122 {uid} S+\n'
                if fault=='job-image':state['image']='/bin/bun'
                if fault.startswith('changed-'):
                    original=terminal.process_executable_path
                    reads=[]
                    def root_image(pid):
                        result=original(pid)
                        reads.append(True)
                        if fault=='changed-parent':state['ps']=f'122 1 0 Ss\n123 999 {uid} S+\n'
                        if fault=='changed-root-image' and len(reads)>1:return '/usr/bin/other'
                        if fault=='changed-root':state['sample']['pid']=999
                        if fault=='changed-job':state['sample']['job_pid']=999
                        if fault=='changed-birth':state['birth']='restarted'
                        if fault=='changed-state':state['ps']=f'122 1 0 T\n123 122 {uid} S+\n'
                        if fault=='changed-tty':state['sample']['tty']='/dev/ttys008'
                        return result
                    terminal.process_executable_path=root_image
                self.assertFalse(terminal.ordinary_shell(pane,Path('/bin/zsh')))

    def test_raw_kernel_path_does_not_weaken_birth_qualified_image(self):
        def probe(pid,buffer,size):
            buffer.value=b'/usr/bin/login'
            return len(buffer.value)
        with patch.object(terminal_identity.sys,'platform','darwin'), \
             patch.object(terminal_identity.ctypes,'CDLL',return_value=SimpleNamespace(proc_pidpath=probe)), \
             patch.object(terminal_identity,'process_start',side_effect=AssertionError('No birth available')):
            self.assertEqual(terminal_identity.process_executable_path(122),'/usr/bin/login')
        with patch.object(terminal_identity,'process_executable_path',return_value='/usr/bin/login'), \
             patch.object(terminal_identity,'process_start',return_value=None):
            self.assertIsNone(terminal_identity.process_image(122))
        with patch.object(terminal_identity,'process_executable_path',return_value='/bin/zsh'), \
             patch.object(terminal_identity,'process_start',return_value='birth'):
            self.assertEqual(terminal_identity.process_image(123),'/bin/zsh')
