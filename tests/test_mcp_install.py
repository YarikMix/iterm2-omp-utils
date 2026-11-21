"""Isolated ownership/cutover contracts; no native API or user configuration."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from iterm2_utils import lifecycle, state, engine
from iterm2_utils.config import mcp
from iterm2_utils.models import Context, OmpProfile, Paths, Selection, ChangeSet, Plan
from iterm2_utils.mcp.binding import McpBinding

ROOT = Path(__file__).resolve().parents[1]


class FixtureRunner:
    def run(self, *args, **kwargs):
        raise AssertionError('No native process during fixture install')


class InstallTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        env = patch.dict(os.environ, HOME=str(self.home)); env.start(); self.addCleanup(env.stop)
        self.profile = OmpProfile('work', self.home/'agent')
        self.paths = Paths(self.home, self.home/'.zshrc', self.home/'config', self.home/'cache',
                           self.home/'data', self.home/'profiles', ROOT)
        self.context = Context(self.paths, {'python3':Path(sys.executable), 'zsh':Path('/bin/zsh'),
                               'iterm2':self.home/'iTerm.app'}, {'python3':'3.12.0'},
                               frozenset({'macos','python:iterm2','python:mcp'}), {}, {}, omp_profile=self.profile)
        self.selection = Selection(frozenset({'mcp'}), frozenset(), 'Default', self.profile)
        self.runner = FixtureRunner()

    def install(self):
        result = lifecycle.install(self.context, self.selection, self.runner)
        self.assertFalse([f for f in result.findings if f.state in {'conflict','unavailable','missing_dependency'}], result.findings)
        return result

    def binding(self):
        registration = json.loads((self.profile.agent_dir/'mcp.json').read_text())['mcpServers']['iterm2-observe']
        return McpBinding(self.profile, Path(registration['args'][1]).parent.parent,
                          self.paths.data/'receipt.json', Path(registration['command']))

    def test_mcp_only_install_and_rollback_keep_other_features(self):
        panel = self.paths.profiles/'panel.json'; panel.parent.mkdir(); panel.write_text('foreign panel')
        result = self.install()
        binding = self.binding(); mcp.authorize_binding(binding)
        release = binding.install_root
        self.assertTrue(release.is_relative_to(self.paths.data/'mcp/releases'))
        self.assertTrue((release/'runtime/iterm2_mcp_entry.py').is_file())
        self.assertFalse((self.paths.data/'current').exists())
        registration = json.loads((self.profile.agent_dir/'mcp.json').read_text())['mcpServers']
        self.assertEqual(set(registration), {'iterm2-observe'})
        self.assertEqual(registration['iterm2-observe']['timeout'],300000)
        self.assertEqual(registration['iterm2-observe']['args'][0],'-I')
        extension = self.profile.agent_dir/'extensions/iterm2-utils-projects.ts'
        self.assertTrue(extension.is_file())
        before = state.load(self.paths.data/'receipt.json')
        self.install(); self.assertEqual(state.load(self.paths.data/'receipt.json'),before)
        removed = lifecycle.uninstall(self.context, frozenset({'mcp'}), self.runner)
        self.assertFalse(removed.findings,removed.findings)
        self.assertFalse(extension.exists())
        self.assertNotIn('iterm2-observe',json.loads((self.profile.agent_dir/'mcp.json').read_text()).get('mcpServers',{}))
        self.assertTrue((release/'runtime/iterm2_mcp_entry.py').is_file(), 'In-flight runtime must survive rollback')
        self.assertEqual(panel.read_text(),'foreign panel')
        with self.assertRaises(ValueError): mcp.authorize_binding(binding)
        self.assertFalse(lifecycle.uninstall(self.context,frozenset({'mcp'}),self.runner).findings)

    def test_explicit_legacy_replacement_never_adopts_or_auto_updates(self):
        legacy = {'command':'uvx','args':['--with','mcp<2','mcp-server-iterm2==0.1.1'],'env':{},'enabled':True}
        self.profile.agent_dir.mkdir()
        path = self.profile.agent_dir/'mcp.json'
        from iterm2_utils.config import jsonfile
        from iterm2_utils.models import FileEdit
        edit = FileEdit(path,None,jsonfile.patch(b'{}',('mcpServers',mcp.NAME),legacy),0o600,'mcp')
        shell=lifecycle.install(self.context,replace(self.selection,features=frozenset({'shell'})),self.runner)
        self.assertFalse([f for f in shell.findings if f.state in lifecycle.BLOCKING])
        shell_bytes=self.paths.zshrc.read_bytes()
        legacy_selection=replace(self.selection,features=frozenset({'mcp','shell'}))
        result = engine.apply(Plan(legacy_selection,ChangeSet([edit],[],[]),''),self.context,self.runner)
        self.assertFalse(result.findings)
        before = path.read_bytes(); receipt = state.load(self.paths.data/'receipt.json')
        rest=[r for r in receipt.resources if 'mcp' not in r['owners']]
        update = lifecycle.update(self.context,self.runner)
        self.assertTrue(any(f.state=='conflict' for f in update.findings))
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(state.load(self.paths.data/'receipt.json'),receipt)
        lifecycle.uninstall(self.context,frozenset({'mcp'}),self.runner,dry_run=True)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse(lifecycle.uninstall(self.context,frozenset({'mcp'}),self.runner).findings)
        self.install()
        self.assertEqual([r for r in state.load(self.paths.data/'receipt.json').resources if 'mcp' not in r['owners']],rest)
        self.assertEqual(self.paths.zshrc.read_bytes(),shell_bytes)
        for field,value in [('enabled',False),('command','foreign')]:
            original=json.loads(path.read_text()); changed=json.loads(path.read_text())
            changed['mcpServers']['iterm2-observe'][field]=value; path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError): mcp.authorize_binding(self.binding())
            self.assertTrue(any(f.state=='conflict' for f in lifecycle.update(self.context,self.runner).findings))
            path.write_text(json.dumps(original))

    def test_loaded_binding_revoked_after_uninstall(self):
        self.install(); binding=self.binding()
        mcp.authorize_binding(binding)
        lifecycle.uninstall(self.context,frozenset({'mcp'}),self.runner)
        with self.assertRaises(ValueError): mcp.authorize_binding(binding)
        entry=binding.install_root/'runtime/iterm2_mcp_entry.py'
        child=subprocess.run([sys.executable,'-I',str(entry),'--project-worker','--omp-profile',str(self.profile.agent_dir),
                              '--receipt',str(binding.receipt_path)],input='{"type":"prepare","change":{"operation":"remove","project":"x"}}\n',
                              text=True,capture_output=True,cwd=self.home,timeout=10)
        self.assertEqual(child.returncode,0,child.stderr)
        self.assertEqual(json.loads(child.stdout),{'result':{'status':'blocked'}})
        self.assertEqual(child.stderr,'')

    def test_binding_refuses_policy_profile_and_receipt_loss(self):
        self.install(); binding=self.binding(); path=self.profile.agent_dir/'mcp.json'
        original=path.read_bytes()
        for policy in ({'disabledServers':['iterm2-observe']},{'enabledServers':[]}):
            value=json.loads(original); value.update(policy); path.write_text(json.dumps(value))
            with self.assertRaises(ValueError): mcp.authorize_binding(binding)
        path.write_bytes(original)
        with self.assertRaises(ValueError): mcp.authorize_binding(replace(binding,profile=OmpProfile('foreign',self.profile.agent_dir)))
        extension=self.profile.agent_dir/'extensions/iterm2-utils-projects.ts'; extension.write_text('foreign')
        with self.assertRaises(ValueError): mcp.authorize_binding(binding)

    def test_upgrade_keeps_old_release_and_disabled_policy_refuses_removal(self):
        import shutil
        from iterm2_utils.features.mcp import payload_names
        self.install(); old=self.binding()
        repo=self.home/'source'
        for name in payload_names(ROOT):
            path=repo/name; path.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT/name,path)
        entry=repo/'runtime/iterm2_mcp_entry.py'; entry.write_bytes(entry.read_bytes()+b'\n')
        changed=replace(self.context,paths=replace(self.paths,repo=repo))
        outcome=lifecycle.update(changed,self.runner)
        self.assertFalse([f for f in outcome.findings if f.state in lifecycle.BLOCKING],outcome.findings)
        fresh=self.binding(); self.assertNotEqual(old.install_root,fresh.install_root)
        self.assertTrue((old.install_root/'runtime/iterm2_mcp_entry.py').is_file())
        with self.assertRaises(ValueError): mcp.authorize_binding(old)
        mcp.authorize_binding(fresh)
        path=self.profile.agent_dir/'mcp.json'
        value=json.loads(path.read_text()); value['disabledServers']=['iterm2-observe']; path.write_text(json.dumps(value))
        before=path.read_bytes()
        outcome=lifecycle.uninstall(changed,frozenset({'mcp'}),self.runner)
        self.assertTrue(any(f.state=='conflict' for f in outcome.findings),outcome.findings)
        self.assertEqual(path.read_bytes(),before)

    def test_reinstall_checks_retained_bytes_and_foreign_registration(self):
        self.install(); binding=self.binding()
        self.assertFalse(lifecycle.uninstall(self.context,frozenset({'mcp'}),self.runner).findings)
        self.install(); mcp.authorize_binding(self.binding())
        self.assertFalse(lifecycle.uninstall(self.context,frozenset({'mcp'}),self.runner).findings)
        entry=binding.install_root/'runtime/iterm2_mcp_entry.py'
        entry.write_text('foreign changed payload')
        outcome=lifecycle.install(self.context,self.selection,self.runner)
        self.assertTrue(any(f.state=='conflict' for f in outcome.findings))
        self.assertEqual(entry.read_text(),'foreign changed payload')

    def test_pending_project_edit_rechecks_real_binding_under_lock(self):
        from tests.test_project_launcher import ProjectLauncherTests
        from iterm2_utils import project_edits
        fixture=ProjectLauncherTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.context.versions['python3']='3.12.0'
        fixture.context.capabilities |= {'python:mcp'}
        fixture.assertSuccess(fixture.install('mcp','project-launcher'))
        fixture.context.project_launcher_config=None
        fixture.context.omp_profile=fixture.profile
        binding=mcp.installed_binding(fixture.context)
        preview=project_edits.prepare_project_edit(fixture.context,fixture.runner,
            project_edits.ProjectChange('rename',project='project-a',name='Changed'))
        self.assertEqual(preview.status,'ready')
        fixture.native['profiles'].append(dict(guid='unrelated',name='Unrelated',
            bar={'Show Status Bar':False,'Status Bar Layout':{'components':[]}},working_directory=None,references=[]))
        from iterm2_utils.mcp.connection import ObserveConnection
        counts={'opens':0,'closes':0}
        class Transport:
            reader=None; connected=True; connection=object()
            async def open(self): counts['opens']+=1
            async def build_app(self): return object()
            async def close(self): counts['closes']+=1; return True
        async def warm_edit():
            owner=ObserveConnection(transport_factory=Transport)
            try:
                async with owner.lease(): pass
                guids=[row['Guid'] for row in json.loads(fixture.dynamic.read_bytes())['Profiles']]
                applied=project_edits.apply_project_edit(fixture.context,fixture.runner,preview,
                    authorize=lambda:mcp.authorize_binding(binding))
                self.assertEqual(applied.status,'applied')
                self.assertEqual([row['Guid'] for row in json.loads(fixture.dynamic.read_bytes())['Profiles']],guids)
                self.assertEqual(counts,{'opens':1,'closes':0})
            finally:
                await owner.aclose()
        asyncio.run(warm_edit())
        preview=project_edits.prepare_project_edit(fixture.context,fixture.runner,
            project_edits.ProjectChange('rename',project='project-a',name='Next change'))
        self.assertEqual(preview.status,'ready')
        # Removal changes only MCP authority, never the separately owned panel.
        panel=fixture.dynamic.read_bytes()
        fixture.assertSuccess(lifecycle.uninstall(fixture.context,frozenset({'mcp'}),fixture.runner))
        calls=[]
        def authorize():
            with self.assertRaises(BlockingIOError):
                with engine._lock(fixture.context): pass
            calls.append('under-lock')
            mcp.authorize_binding(binding)
        with patch.object(engine,'_set',side_effect=AssertionError('Revoked write')) as write:
            result=project_edits.apply_project_edit(fixture.context,fixture.runner,preview,authorize=authorize)
        self.assertEqual(result.status,'blocked')
        self.assertEqual(calls,['under-lock']); write.assert_not_called()
        self.assertEqual(fixture.dynamic.read_bytes(),panel)
        self.assertEqual(fixture.native['profiles'][-1]['guid'],'unrelated')

    def test_failed_install_inverse_does_not_retain_uncommitted_payload(self):
        original=engine._set
        def fail_registration(resource,*args,**kwargs):
            if resource['kind']=='json' and Path(resource['target']).name=='mcp.json':
                raise ValueError('known registration failure')
            return original(resource,*args,**kwargs)
        with patch.object(engine,'_set',side_effect=fail_registration):
            outcome=lifecycle.install(self.context,self.selection,self.runner)
        self.assertTrue(any(f.state=='conflict' for f in outcome.findings))
        self.assertFalse(list((self.paths.data/'mcp/releases').rglob('iterm2_mcp_entry.py')))

    def test_mcp_receipt_has_separate_bound_and_decodes_same_checked_bytes(self):
        from iterm2_utils.project_edits import read_receipt, _safe_bytes, FILE_LIMIT, RECEIPT_LIMIT
        self.install(); path=self.paths.data/'receipt.json'; binding=self.binding()
        self.assertGreater(path.stat().st_size,FILE_LIMIT)
        self.assertLess(path.stat().st_size,RECEIPT_LIMIT)
        with patch.object(state,'load',side_effect=AssertionError('Unchecked receipt reopen')):
            raw,receipt=read_receipt(path)
            self.assertEqual(raw,path.read_bytes())
            self.assertEqual(receipt.selection.omp_profile,self.profile)
            mcp.authorize_binding(binding)
        config=self.home/'oversized-project-config.json'; config.write_bytes(b' '*(FILE_LIMIT+1))
        with self.assertRaises(ValueError): _safe_bytes(config)
        with open(path,'wb') as stream: stream.truncate(RECEIPT_LIMIT+1)
        with patch('iterm2_utils.config.jsonfile.parse',side_effect=AssertionError('Oversized receipt parsed')), \
             patch.object(engine,'_set',side_effect=AssertionError('Oversized receipt wrote')) as write:
            with self.assertRaises(ValueError): read_receipt(path)
            with self.assertRaises(ValueError): mcp.authorize_binding(binding)
            write.assert_not_called()

    def test_damaged_payload_does_not_prevent_owned_mcp_opt_out(self):
        cases = (
            ('runtime/iterm2_mcp_entry.py', b'user changed payload\n'),
            ('runtime/iterm2_mcp_entry.py', None),
            ('sources.lock.json', b'{'),
            ('sources.lock.json', b'{}'),
        )
        for removal in ('lifecycle', 'revert'):
            for name, damaged in cases:
                with self.subTest(removal=removal, payload=name, damaged=damaged):
                    fixture = InstallTests(); fixture.setUp()
                    try:
                        fixture.paths.zshrc.write_bytes(b'unrelated shell\n')
                        fixture.install(); binding = fixture.binding()
                        target = binding.install_root/name
                        if damaged is None:
                            target.unlink()
                        else:
                            target.write_bytes(damaged)
                        with self.assertRaises((OSError, ValueError, KeyError, TypeError)):
                            mcp.authorize_binding(binding)
                        before = (fixture.profile.agent_dir/'mcp.json').read_bytes()
                        refused = lifecycle.install(fixture.context, fixture.selection, fixture.runner)
                        self.assertTrue(any(f.state == 'conflict' for f in refused.findings), refused.findings)
                        self.assertEqual((fixture.profile.agent_dir/'mcp.json').read_bytes(), before)
                        self.assertEqual(target.read_bytes() if target.exists() else None, damaged)
                        if removal == 'lifecycle':
                            outcome = lifecycle.uninstall(fixture.context, frozenset({'mcp'}), fixture.runner)
                        else:
                            receipt = state.load(binding.receipt_path)
                            outcome = engine.revert(receipt, fixture.context, fixture.runner, frozenset({'mcp'}))
                        registration = json.loads((fixture.profile.agent_dir/'mcp.json').read_text())
                        self.assertNotIn('iterm2-observe', registration.get('mcpServers', {}))
                        self.assertFalse((fixture.profile.agent_dir/'extensions/iterm2-utils-projects.ts').exists())
                        self.assertFalse((binding.install_root/'runtime/terminal_identity.py').exists())
                        self.assertEqual(target.read_bytes() if target.exists() else None, damaged)
                        self.assertEqual(fixture.paths.zshrc.read_bytes(), b'unrelated shell\n')
                        self.assertTrue(any(f.code == 'uninstall_changed' and f.state == 'conflict'
                                            for f in outcome.findings), outcome.findings)
                        self.assertFalse(any(f.code in {'apply_conflict','ownership_unavailable'}
                                             for f in outcome.findings), outcome.findings)
                        self.assertEqual([r['target'] for r in outcome.receipt.resources], [str(target.resolve())])
                        with self.assertRaises(ValueError):
                            mcp.authorize_binding(binding)
                        self.assertFalse((fixture.paths.data/'journal').exists())
                    finally:
                        fixture.doCleanups()
