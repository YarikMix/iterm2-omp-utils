"""Exact header/lineage and independently observed live identity boundaries."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from iterm2_utils.models import OmpProfile
from iterm2_utils.omp_sessions import ResumeTarget, SessionBinding, resolve_resume, matches_conversation, find_open

TID = 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'

class Sessions(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile = OmpProfile('work', self.root/'custom-agent')
        self.cwd = self.root/'project'
        self.cwd.mkdir()
        self.path = self.save('arbitrary-name.jsonl', 'original')
        self.target = resolve_resume(self.path, 'original', self.profile)

    def save(self, name, sid, **extra):
        path = self.root/name
        path.write_text(json.dumps({'type':'title','v':1,'title':'misleading'})+'\n'+json.dumps(
            {'type':'session','version':3,'id':sid,'cwd':str(self.cwd), 'timestamp':'2026-11-16T00:00:00Z', **extra})+'\n')
        return path

    def binding(self, path=None, sid='original'):
        return SessionBinding(TID, 'tab', 'window', path or self.path, sid, self.cwd,
                              self.profile, 123, 'start-1', 'generation-1')

    def test_exact_header_not_filename_title_or_prefix(self):
        for sid in ('orig', 'arbitrary-name', 'misleading', 'other'):
            with self.assertRaises(ValueError):
                resolve_resume(self.path, sid, self.profile)
        with self.assertRaises(ValueError):
            resolve_resume(self.root/'missing', 'original', self.profile)
        self.assertEqual(self.target.session_id, 'original')
        self.assertEqual(self.target.cwd, self.cwd)

    def test_only_evidenced_continuation_matches_requested_dialog(self):
        child = self.save('child.jsonl', 'child', continuationOf='original', parentSession='original')
        self.assertTrue(matches_conversation(self.target, self.binding(child, 'child')))
        grandchild = self.save('grandchild.jsonl', 'grandchild', continuationOf='child', parentSession='child')
        self.assertTrue(matches_conversation(self.target, self.binding(grandchild, 'grandchild')))
        fork = self.save('fork.jsonl', 'fork', parentSession='original')
        self.assertFalse(matches_conversation(self.target, self.binding(fork, 'fork')))
        self.assertFalse(matches_conversation(self.target, self.binding(child, 'substituted')))
        child.write_text(json.dumps({'type':'session','id':'changed','cwd':str(self.cwd)})+'\n')
        self.assertFalse(matches_conversation(self.target, self.binding(child, 'child')))

    def test_undefined_file_and_foreign_profile_are_not_resume_targets(self):
        self.assertFalse(matches_conversation(self.target, replace(self.binding(), session_file=None)))
        self.assertFalse(matches_conversation(self.target, replace(self.binding(), profile=OmpProfile(None,self.root))))

    def test_pid_reuse_and_wrong_generation_are_not_live_identity(self):
        binding = self.binding()
        class Transport:
            def bindings(self): return [binding]
            def process_start(self, pid): return 'start-1'
            def observe(self, terminal):
                return {'terminal_id':TID,'tab_id':'tab','window_id':'window','pid':123,
                        'process_start':'start-1','generation':'generation-1','session_id':'original',
                        'session_file':str(binding.session_file),'cwd':str(binding.cwd),
                        'profile':{'name':'work','agent_dir':str(binding.profile.agent_dir)}}
        transport = Transport()
        self.assertEqual(find_open(self.target, transport), binding)
        transport.process_start = lambda pid: 'start-2'
        self.assertIsNone(find_open(self.target, transport))
        transport.process_start = lambda pid: 'start-1'
        original = transport.observe
        for patch in ({'generation':'new'}, {'session_id':'switched'}, {'tab_id':'reused'}):
            transport.observe = lambda terminal, patch=patch: {**original(terminal), **patch}
            self.assertIsNone(find_open(self.target, transport))

    def test_continuation_without_parents_newest_turn_is_not_same_dialog(self):
        child = self.save('child.jsonl','child',continuationOf='original',parentSession='original')
        turn = json.dumps({'type':'message','id':'last-turn','timestamp':'2026-11-16T01:00:00Z',
                           'message':{'role':'user','content':'fixture'}})+'\n'
        with self.path.open('a') as source:
            source.write(turn)
        self.assertFalse(matches_conversation(self.target,self.binding(child,'child')))
        with child.open('a') as source:
            source.write(turn)
        self.assertTrue(matches_conversation(self.target,self.binding(child,'child')))

    def test_registry_rejects_public_malformed_and_symlink_records(self):
        from iterm2_utils.omp_sessions import read_bindings, binding_record
        registry = self.root/'registry'
        registry.mkdir(mode=0o700)
        path = registry/'record.json'
        path.write_text(json.dumps({'schema':1,**binding_record(self.binding())}))
        path.chmod(0o600)
        self.assertEqual(read_bindings(registry),[self.binding()])
        path.chmod(0o644)
        self.assertEqual(read_bindings(registry),[])
        path.unlink()
        path.symlink_to(self.path)
        self.assertEqual(read_bindings(registry),[])
        path.unlink()
        for raw in ([], {'schema':1}, {'schema':2,**binding_record(self.binding())}):
            path.write_text(json.dumps(raw))
            path.chmod(0o600)
            self.assertEqual(read_bindings(registry),[])
