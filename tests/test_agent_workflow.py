"""Isolated real CLI/lifecycle contracts; not agent-behavior evaluations.

The optional stdio bridge accepts only synthetic setup observations/argv. It
never runs model-supplied shell, agent, UI or real native operations.
"""
import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_lifecycle import LifecycleFixture
from iterm2_utils import cli


class WorkflowFixture(LifecycleFixture):
    def setUp(self):
        super().setUp()
        self.actions = []

    def setup_cli(self, argv):
        self.actions.append({'tool':'setup','argv':argv})
        out, err = io.StringIO(), io.StringIO()
        if '--omp-profile' not in argv:argv = [*argv,'--omp-profile','work']
        with patch.dict(os.environ, {'HOME':str(self.home),'PATH':os.environ.get('PATH',os.defpath),
                                    'OMP_PROFILE':'work','PI_CONFIG_DIR':'.omp'},clear=True), \
             patch.object(cli,'resolve_paths',return_value=self.context.paths), \
             patch.object(cli,'discover',return_value=self.context), \
             patch.object(cli,'Runner',return_value=self.runner), \
             contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code = cli.main([*argv,'--json'])
        report = json.loads(out.getvalue()) if out.getvalue() else {'mode':'invalid_arguments'}
        return {'exit_code':code,'report':report}

    def ui(self,status):
        self.actions.append({'tool':'peekaboo','result':status})
        return {'error':status,'available':status=='available'}

    def generic_command(self,argv):
        self.actions.append({'tool':'generic_command','argv':argv})
        return {'error':'Fixture command recorded; no process was executed.'}


class AgentWorkflowTests(WorkflowFixture):
    def test_native_selection_changes_only_selected_addresses_and_retains_neighbours(self):
        path = self.profile.agent_dir/'config.yml'
        path.write_text('model: keep\ncompletion: {notify: off}\nerror: {notify: off}\n')
        before = self.snapshot()
        planned = self.setup_cli(['plan','--features','status,notifications'])
        self.assertEqual(self.snapshot(),before)
        self.assertIn(planned['exit_code'],(0,3),planned)
        result = self.setup_cli(['install','--features','status,notifications'])
        self.assertEqual(result['report']['selection']['features'],['notifications','status'])
        from iterm2_utils.config import omp
        self.assertEqual(omp.read_setting(self.profile,'terminal.programStatus',self.runner),{'exists':True,'value':True})
        self.assertEqual(omp.read_setting(self.profile,'completion.notify',self.runner)['value'],'on')
        self.assertEqual(omp.read_setting(self.profile,'error.notify',self.runner)['value'],'off')
        self.assertIn('model: keep',path.read_text())
        self.assertFalse(self.context.paths.zshrc.exists())
        self.assertFalse((self.profile.agent_dir/'mcp.json').exists())
        self.assertFalse((self.home/'.codex').exists())
        self.assertFalse((self.home/'.claude').exists())
        before = self.snapshot()
        self.assertIn(self.setup_cli(['doctor'])['exit_code'],(0,3))
        self.assertEqual(self.snapshot(),before)

    def test_cumulative_plan_and_install_preserve_error_optin_and_resume_binding(self):
        self.setup_cli(['install','--features','notifications','--notify-errors'])
        result = self.setup_cli(['install','--features','shortcuts','--shortcuts','resume','--resume-key','F8'])
        self.assertEqual(result['report']['selection']['resume_key'],'F8')
        for command in ('plan','install'):
            result = self.setup_cli([command,'--features','shell'])
            selected = result['report']['selection']
            self.assertEqual(selected['features'],['notifications','shell','shortcuts'])
            self.assertTrue(selected['notify_errors'])
            self.assertEqual(selected['resume_key'],'F8')

    def test_missing_selected_capability_does_not_block_independent_native_feature(self):
        self.context.capabilities -= {'iterm2:osc7501'}
        result = self.setup_cli(['install','--features','status,notifications'])
        self.assertEqual(result['report']['selection']['features'],['notifications'])
        self.assertEqual(result['exit_code'],2)
        self.assertEqual(result['report']['pending'],['notifications'])
        self.assertTrue(any(f['feature']=='status' and f['state']=='unavailable' for f in result['report']['findings']))

    def test_shell_only_preserves_foreign_mcp_and_uninstall_uses_owned_values(self):
        path = self.profile.agent_dir/'mcp.json'
        original = b'{"mcpServers":{"foreign":{"command":"PRIVATE_COMMAND"}}}'
        path.write_bytes(original)
        result = self.setup_cli(['install','--features','shell'])
        self.assertEqual(result['exit_code'],0,result)
        self.assertEqual(path.read_bytes(),original)
        self.assertNotIn('PRIVATE_COMMAND',json.dumps(result))
        self.assertEqual(self.setup_cli(['update'])['exit_code'],0)
        self.assertEqual(self.setup_cli(['uninstall','--features','shell'])['exit_code'],0)
        self.assertEqual(path.read_bytes(),original)

    def test_mcp_reconcile_requires_actual_probe_and_keeps_denied_access_pending(self):
        result = self.setup_cli(['install','--features','mcp'])
        self.assertIn('mcp',result['report']['pending'])
        before = self.snapshot()
        result = self.setup_cli(['reconcile','--step','mcp_authorize'])
        self.assertIn(result['exit_code'],(2,3))
        self.assertIn('mcp',result['report']['pending'])
        self.assertEqual(self.snapshot(),before)
        self.assertFalse(any('osascript' in str(call) for call in self.runner.calls))

    def test_fixture_json_booleans_are_literal_not_string_truthiness(self):
        with self.assertRaises(ValueError):materialize_case(self,{'python_api':'false'})
        materialize_case(self,{'python_api':False,'versions':{'omp':'100.2.3'}})
        self.assertNotIn('python:iterm2',self.context.capabilities)
        self.assertEqual(self.context.versions['omp'],'100.2.3')


class SkillValidatorTests(unittest.TestCase):
    def test_literal_json_booleans_and_complete_argv_are_validated(self):
        import shutil
        from tempfile import TemporaryDirectory
        from tools.check_skill import check
        source=Path(__file__).resolve().parents[1]/'skills/iterm2-launch'
        with TemporaryDirectory() as tmp:
            bundle=Path(tmp)/'iterm2-launch'
            shutil.copytree(source,bundle)
            self.assertEqual(check(bundle),[])
            resume=bundle/'references/resume.md'
            original=resume.read_text()
            for before,after in (('"matches": true','"matches": "true"'),
                                 ('"latest_turn_verified":true','"latest_turn_verified":"true"'),
                                 (' /tmp/session.jsonl --continue"',' /tmp/session.jsonl"')):
                resume.write_text(original.replace(before,after,1))
                self.assertIn('Invalid omp argv/continuation JSON fixtures',check(bundle))


def materialize_case(fixture,observations):
    """Literal JSON semantics only; version strings never imply capabilities."""
    allowed = {'versions','features_initial','peekaboo','foreign_mcp','foreign_command',
               'foreign_marker','python_api','missing_capabilities'}
    if not isinstance(observations,dict) or set(observations)-allowed:
        raise ValueError('Unsupported fixture observations')
    if 'python_api' in observations and type(observations['python_api']) is not bool:
        raise ValueError('python_api must be a JSON boolean')
    if observations.get('peekaboo','absent') not in {'absent','available','denied'}:
        raise ValueError('Invalid synthetic UI status')
    c = fixture.context
    c.versions.update(observations.get('versions',{}))
    c.capabilities -= frozenset(observations.get('missing_capabilities',[]))
    if observations.get('python_api') is False:c.capabilities -= {'python:iterm2'}
    if observations.get('foreign_mcp'):
        path = c.omp_profile.agent_dir/'mcp.json'
        path.write_text(json.dumps({'fixture_marker':observations.get('foreign_marker',''),
            'mcpServers':{observations['foreign_mcp']:{'command':observations.get('foreign_command','fixture-observer'),'args':[]}}}))
    if observations.get('features_initial'):
        result = fixture.setup_cli(['install','--features',','.join(observations['features_initial'])])
        if result['exit_code']==2:raise ValueError('Initial features could not be materialized')


def serve_mcp(case_path,log_path):
    """Synthetic setup-only bridge; launch scenarios use observational actors."""
    case = json.loads(Path(case_path).read_text())
    fixture = WorkflowFixture(); fixture.setUp()
    try:
        materialize_case(fixture,case['fixture'])
        tools = [
            {'name':'setup','description':'Actual isolated omp setup CLI. Supports plan/install --features CSV --omp-profile work, bootstrap-skill, migrate-omp, doctor, reconcile --step CODE, update, uninstall. No live operations.',
             'inputSchema':{'type':'object','properties':{'argv':{'type':'array','items':{'type':'string'}}},'required':['argv']}},
            {'name':'generic_command','description':'Record synthetic argv only; never execute.',
             'inputSchema':{'type':'object','properties':{'argv':{'type':'array','items':{'type':'string'}}},'required':['argv']}}]
        if case['fixture'].get('peekaboo','absent')!='absent':
            tools.append({'name':'peekaboo','description':'Synthetic UI availability only; no live UI.', 'inputSchema':{'type':'object','properties':{}}})
        for line in sys.stdin:
            request = json.loads(line)
            if 'id' not in request:continue
            method = request['method']
            if method=='initialize':
                result = {'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'2'}}
            elif method=='tools/list':result = {'tools':tools}
            elif method=='tools/call':
                params=request['params']; args=params.get('arguments',{})
                if params['name']=='setup':
                    # An actor cannot turn this fake setup transport into a native launch.
                    argv=args['argv']
                    if not argv or argv[0] not in {'plan','install','bootstrap-skill','migrate-omp','doctor','reconcile','update','uninstall'}:
                        value={'error':'Unsupported fixture command'}
                    else:value=fixture.setup_cli(argv)
                elif params['name']=='generic_command':value=fixture.generic_command(args['argv'])
                elif params['name']=='peekaboo':value=fixture.ui(case['fixture'].get('peekaboo','absent'))
                else:value={'error':'Unknown fixture tool'}
                result={'content':[{'type':'text','text':json.dumps(value)}]}
                Path(log_path).write_text(json.dumps({'actions':fixture.actions,'files':{
                    name:__import__('hashlib').sha256(raw).hexdigest() for name,raw in fixture.snapshot().items()}},indent=2))
            else:result={}
            print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
    finally:fixture.doCleanups()


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--serve-mcp':serve_mcp(*sys.argv[2:])
    else:unittest.main()
