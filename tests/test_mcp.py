import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from iterm2_utils import engine
from iterm2_utils.config import mcp
from iterm2_utils.models import ChangeSet, Context, OmpProfile, Paths, Plan, Selection


class NoAgentRunner:
    def run(self, *args, **kwargs):
        raise AssertionError('MCP storage adapters must not execute an agent')


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        environment = patch.dict(os.environ, {'HOME': str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        self.profile = OmpProfile('work', self.home/'.omp/profiles/work/agent')
        self.profile.agent_dir.mkdir(parents=True)
        self.path = self.profile.agent_dir/'mcp.json'
        self.runner = NoAgentRunner()
        paths = Paths(self.home, self.home/'.zshrc', self.home/'config', self.home/'cache', self.home/'data', self.home/'profiles', Path(__file__).resolve().parents[1])
        self.context = Context(paths, {}, {}, frozenset(), {}, {}, omp_profile=self.profile)
        self.selection = Selection(frozenset({'mcp'}), frozenset(), 'Default', self.profile)

    def install(self):
        edit = mcp.server_edit(self.profile, self.runner)
        return engine.apply(Plan(self.selection, ChangeSet([edit], [], []), ''), self.context, self.runner)

    def test_owned_server_is_one_json_pointer_and_preserves_foreign_servers(self):
        original = {'$schema': 'keep', 'mcpServers': {'foreign': {'command': 'private', 'env': {'TOKEN': 'secret'}}}, 'foreignRoot': [1, 2]}
        self.path.write_text(json.dumps(original))
        result = self.install()
        self.assertFalse(result.findings)
        self.assertEqual(len(result.receipt.resources), 1)
        resource = result.receipt.resources[0]
        self.assertEqual(resource['kind'], 'json')
        self.assertEqual(resource['locator']['pointer'], ['mcpServers', mcp.NAME])
        current = json.loads(self.path.read_text())
        self.assertEqual(current['mcpServers'][mcp.NAME], mcp.definition())
        self.assertEqual(current['mcpServers']['foreign'], original['mcpServers']['foreign'])
        self.assertEqual(current['foreignRoot'], original['foreignRoot'])
        reverted = engine.revert(result.receipt, self.context, self.runner, frozenset({'mcp'}))
        self.assertFalse(reverted.findings)
        self.assertEqual(json.loads(self.path.read_text()), original)

    def test_equivalent_foreign_server_reuses_without_ownership(self):
        self.path.write_text(json.dumps({'mcpServers': {mcp.NAME: mcp.definition()}}))
        before = self.path.read_bytes()
        result = self.install()
        self.assertFalse(result.findings)
        self.assertEqual(result.receipt.resources, [])
        self.assertEqual(self.path.read_bytes(), before)

    def test_foreign_name_collision_is_not_overwritten(self):
        for value in ({'command': 'other'}, None, {'command': 'uvx', 'args': mcp.ARGS, 'env': {'TOKEN': 'secret'}}):
            self.path.write_text(json.dumps({'mcpServers': {mcp.NAME: value}}))
            before = self.path.read_bytes()
            with self.assertRaises(ValueError):
                mcp.server_edit(self.profile, self.runner)
            self.assertEqual(self.path.read_bytes(), before)

    def test_malformed_storage_and_disabled_server_block_without_mutation(self):
        for content in ('null', '[]', '{', '{"mcpServers":null}', '{"mcpServers":{},"mcpServers":{}}', json.dumps({'disabledServers': [mcp.NAME]})):
            self.path.write_text(content)
            with self.assertRaises(ValueError):
                mcp.server_edit(self.profile, self.runner)
            self.assertEqual(self.path.read_text(), content)

    def test_changed_server_is_retained_on_uninstall(self):
        result = self.install()
        data = json.loads(self.path.read_text())
        data['mcpServers'][mcp.NAME]['args'].append('--foreign')
        data['mcpServers']['neighbour'] = {'command': 'keep'}
        self.path.write_text(json.dumps(data))
        reverted = engine.revert(result.receipt, self.context, self.runner, frozenset({'mcp'}))
        self.assertTrue(reverted.findings)
        self.assertEqual(json.loads(self.path.read_text()), data)
        self.assertEqual(len(reverted.receipt.resources), 1)

    def test_server_replacement_does_not_remove_user_added_field(self):
        result = self.install()
        data = json.loads(self.path.read_text())
        data['mcpServers'][mcp.NAME]['timeout'] = 1234
        self.path.write_text(json.dumps(data))
        reverted = engine.revert(result.receipt, self.context, self.runner, frozenset({'mcp'}))
        self.assertTrue(reverted.findings)
        self.assertEqual(json.loads(self.path.read_text()), data)

    def test_pinned_definition_is_native_stdio_not_agent_cli_metadata(self):
        definition = mcp.definition()
        self.assertEqual(definition, {'command': 'uvx', 'args': ['--with', 'mcp<2', 'mcp-server-iterm2==0.1.1'], 'env': {}, 'enabled': True})
        self.assertNotIn('scope', definition)
        self.assertNotIn('environment_empty', definition)

    def test_probe_checks_exact_tool_allowlist_and_session_evidence(self):
        self.path.write_text(json.dumps({'mcpServers': {mcp.NAME: mcp.definition()}}))
        class Probe(NoAgentRunner):
            extra = False
            def mcp_probe(inner, argv, *, timeout, env=None):
                self.assertEqual(argv, ['uvx', *mcp.ARGS])
                self.assertEqual(timeout, 5)
                self.assertEqual(env['HOME'], str(self.home))
                return {'tools': sorted(mcp.TOOLS | ({'dangerous'} if inner.extra else set())), 'sessions': True}
        runner = Probe()
        self.assertEqual(mcp.probe(self.context, runner).state, 'ready')
        runner.extra = True
        self.assertNotEqual(mcp.probe(self.context, runner).state, 'ready')

    def test_adapter_rejects_incomplete_duplicate_or_unknown_tool_inventory(self):
        self.path.write_text(json.dumps({'mcpServers': {mcp.NAME: mcp.definition()}}))
        complete = sorted(mcp.TOOLS)
        class Probe(NoAgentRunner):
            tools = []
            def mcp_probe(inner, *args, **kwargs):
                return {'tools': inner.tools, 'sessions': True}
        runner = Probe()
        for inventory in ([complete[0]], complete[:-1], complete + [complete[0]], complete[:-1] + [complete[0]], complete + ['execute']):
            runner.tools = inventory
            self.assertEqual(mcp.probe(self.context, runner).state, 'unavailable')

    def test_protocol_rejects_invalid_inventory_before_sessions_call(self):
        import sys
        from iterm2_utils.commands import Runner
        complete = sorted(mcp.TOOLS)
        script = self.home/'inventory-server.py'
        marker = self.home/'sessions-called'
        for inventory in ([complete[0]], complete[:-1], complete + [complete[0]], complete[:-1] + [complete[0]], complete + ['execute']):
            marker.unlink(missing_ok=True)
            script.write_text('tools=' + repr(inventory) + '\nmarker=' + repr(str(marker)) + '\n' + """import sys,json
from pathlib import Path
for line in sys.stdin:
 request=json.loads(line)
 method=request['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{}}
 elif method=='tools/list':result={'tools':[{'name':name} for name in tools]}
 else:
  Path(marker).write_text('called')
  result={'content':[{'type':'text','text':'{"windows": [], "buried_sessions": []}'}]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
""")
            result = Runner().mcp_probe([sys.executable, str(script)], timeout=2)
            self.assertFalse(result['sessions'])
            self.assertFalse(marker.exists())

    def test_protocol_error_payload_does_not_claim_session_evidence(self):
        import sys
        from iterm2_utils.commands import Runner
        script = self.home/'error-server.py'
        script.write_text('tools=' + repr(sorted(mcp.TOOLS)) + '\n' + """import sys,json
for line in sys.stdin:
 request=json.loads(line)
 if 'id' not in request:continue
 method=request['method']
 if method=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{}}
 elif method=='tools/list':result={'tools':[{'name':name} for name in tools]}
 else:result={'isError':True,'content':[{'type':'text','text':'private denied response'}]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
""")
        result = Runner().mcp_probe([sys.executable, str(script)], timeout=2)
        self.assertFalse(result['sessions'])
        self.assertNotIn('private denied response', repr(result))

    def test_native_reconcile_uses_receipt_profile_and_new_probe_signature(self):
        from dataclasses import replace
        from iterm2_utils import lifecycle, state
        from iterm2_utils.models import Receipt, UiStep
        self.path.write_text(json.dumps({'mcpServers': {mcp.NAME: mcp.definition()}}))
        receipt = Receipt('2', self.selection, [], [UiStep('mcp_authorize', 'mcp', None, 'Authorize the selected server.')])
        state.save(self.context.paths.data/'receipt.json', receipt)
        class Probe(NoAgentRunner):
            calls = 0
            def mcp_probe(inner, argv, *, timeout, env=None):
                inner.calls += 1
                return {'tools': sorted(mcp.TOOLS), 'sessions': True}
        runner = Probe()
        different = replace(self.context, omp_profile=OmpProfile(None, self.home/'foreign/agent'))
        result = lifecycle.reconcile_ui(different, 'mcp_authorize', runner)
        self.assertEqual(runner.calls, 1)
        self.assertFalse(result.receipt.pending_ui)
        self.assertTrue(any(f.code == 'mcp_connection' and f.state == 'ready' for f in result.findings))
        self.assertEqual(state.load(self.context.paths.data/'receipt.json').selection.omp_profile, self.profile)

    def test_cli_current_live_doctor_uses_current_receipt_mcp_scope(self):
        import contextlib
        import io
        from iterm2_utils import cli, state
        from iterm2_utils.models import Receipt
        self.path.write_text(json.dumps({'mcpServers': {mcp.NAME: mcp.definition()}}))
        state.save(self.context.paths.data/'receipt.json', Receipt('2', self.selection, [], []))
        class Probe(NoAgentRunner):
            calls = 0
            def mcp_probe(inner, argv, *, timeout, env=None):
                inner.calls += 1
                return {'tools': sorted(mcp.TOOLS), 'sessions': True}
        runner = Probe()
        output = io.StringIO()
        with patch.object(cli, 'resolve_paths', return_value=self.context.paths), patch.object(cli, 'Runner', return_value=runner), patch.object(cli, 'discover', side_effect=AssertionError('agent discovery')), contextlib.redirect_stdout(output):
            cli.main(['doctor', '--live', '--json'])
        self.assertEqual(runner.calls, 1)
        self.assertTrue(any(f['code'] == 'mcp_connection' and f['state'] == 'ready' for f in json.loads(output.getvalue())['findings']))

    def test_cli_historical_live_doctor_stops_before_native_or_legacy_probe(self):
        import contextlib
        import io
        from iterm2_utils import cli
        from tests.test_legacy_state import legacy_fixture
        path = self.context.paths.data/'receipt.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(legacy_fixture(str(self.path))))
        output = io.StringIO()
        with patch.object(cli, 'resolve_paths', return_value=self.context.paths), patch.object(cli, 'discover', side_effect=AssertionError('agent discovery')), patch.object(mcp, 'probe', side_effect=AssertionError('unscoped probe')), contextlib.redirect_stdout(output):
            status = cli.main(['doctor', '--live', '--json'])
        self.assertEqual(status, 2)
        self.assertTrue(any(f['code'] == 'migration_required' for f in json.loads(output.getvalue())['findings']))
