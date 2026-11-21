"""Actual SDK stdio transport with private binding and no real app access."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import importlib.util


FIXTURE = r'''
import asyncio,json,sys
from pathlib import Path
from iterm2_utils.mcp.binding import McpBinding
from iterm2_utils.mcp.connection import ObserveConnection
from iterm2_utils.mcp.server import create_server, serve_stdio
from iterm2_utils.models import OmpProfile
root=Path(sys.argv[1]); counts=dict(opens=0,authorizations=0,closed=False)
class Transport:
    def __init__(self):
        counts['opens']+=1
        raise AssertionError('No SDK access permitted')
observe=ObserveConnection(transport_factory=Transport)
async def authorize(): counts['authorizations']+=1
binding=McpBinding(OmpProfile(None,root/'agent'),Path.cwd(),root/'data/receipt.json',Path(sys.executable))
import iterm2_utils.mcp.server as server_module
async def launch_fixture(binding,args):
    from iterm2_utils.mcp.launch_tools import make_launch_request, bound_paths, uncertain
    request=make_launch_request(binding,bound_paths(binding),args)
    assert request.cwd==root and request.window_id==('' if args.new_window else 'Explicit')
    assert request.new_window is args.new_window
    assert request.mode==args.mode
    assert request.omp_profile==(binding.profile if args.mode=='handoff' else None)
    assert request.profile==('Ordinary' if args.mode=='shell' else 'iterm2-utils:omp')
    return uncertain(dict(window_id='Explicit',tab_id='T',session_id='S'))
server_module.run_launch=launch_fixture
async def main():
    try: await serve_stdio(create_server(binding,observe,authorize=authorize),observe)
    finally:
        counts['closed']=observe._closed
        (root/'counts.json').write_text(json.dumps(counts))
asyncio.run(main())
'''


@unittest.skipUnless(sys.version_info >= (3,12) and importlib.util.find_spec('mcp') and
                     importlib.util.find_spec('iterm2'), 'Optional SDK suite requires selected Python 3.12+ with mcp and iterm2')
class StdioTests(unittest.TestCase):
    def test_stdio_catalogue_does_not_open_websocket(self):
        # No skip: the controller explicitly supplies the optional-dependency Python.
        import mcp
        with TemporaryDirectory() as temp:
            root=Path(temp)
            frames=[dict(jsonrpc='2.0',id=1,method='initialize',params=dict(protocolVersion='2024-11-05',capabilities={},clientInfo=dict(name='fixture',version='1'))),
                    dict(jsonrpc='2.0',method='notifications/initialized'),
                    dict(jsonrpc='2.0',id=2,method='tools/list'),
                    dict(jsonrpc='2.0',id=3,method='tools/call',params=dict(name='list_projects',arguments={})),
                    dict(jsonrpc='2.0',id=4,method='tools/call',params=dict(name='open_shell',arguments=dict(cwd=temp,window_id='Explicit',shell_profile='Ordinary'))),
                    dict(jsonrpc='2.0',id=5,method='tools/call',params=dict(name='launch_omp_task',arguments=dict(cwd=temp,window_id='Explicit',task='PRIVATE TASK'))),
                    dict(jsonrpc='2.0',id=6,method='tools/call',params=dict(name='open_shell_window',arguments=dict(cwd=temp,shell_profile='Ordinary'))),
                    dict(jsonrpc='2.0',id=7,method='tools/call',params=dict(name='launch_omp_task_window',arguments=dict(cwd=temp,task='PRIVATE TASK'))),
                    dict(jsonrpc='2.0',id=8,method='tools/call',params=dict(name='open_shell_window',arguments=dict(cwd=temp,project='invalid',shell_profile='Ordinary')))]
            env=dict(os.environ,HOME=temp,XDG_CONFIG_HOME=temp+'/config',XDG_DATA_HOME=temp+'/data',XDG_CACHE_HOME=temp+'/cache')
            child=subprocess.Popen([sys.executable,'-c',FIXTURE,temp],cwd=Path(__file__).resolve().parents[1],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            responses=[]
            try:
                import select
                for frame in frames:
                    child.stdin.write(json.dumps(frame)+'\n'); child.stdin.flush()
                    if 'id' in frame:
                        self.assertTrue(select.select([child.stdout],[],[],10)[0], 'Missing protocol response')
                        responses.append(json.loads(child.stdout.readline()))
                child.stdin.close(); child.stdin=None
                stdout,stderr=child.communicate(timeout=10)
                self.assertEqual(child.returncode,0,stderr)
                self.assertEqual(stdout,'','Non-protocol stdout')
            finally:
                if child.poll() is None: child.kill()
                child.communicate()
            by_id={r['id']:r for r in responses if 'id' in r}
            self.assertEqual(set(by_id),{1,2,3,4,5,6,7,8},responses)
            names={t['name'] for t in by_id[2]['result']['tools']}
            self.assertEqual(names,{'list_sessions','get_session_info','get_screen_contents','get_selection','get_scrollback','get_recent_output','get_variable','list_profiles','set_badge','set_title','set_tab_color','set_user_variable','post_notification','list_projects','open_shell','launch_omp_task','open_shell_window','launch_omp_task_window'})
            for tool in by_id[2]['result']['tools']:
                if tool['name'] in {'open_shell_window','launch_omp_task_window'}:
                    self.assertNotIn('window_id',tool['inputSchema']['properties'])
            result=by_id[3]['result']; self.assertFalse(result.get('isError',False),result)
            self.assertEqual(json.loads(result['content'][0]['text']),{'status':'not_configured','projects':[]})
            for tool_id in (4,5,6,7):
                self.assertFalse(by_id[tool_id]['result'].get('isError',False),by_id[tool_id])
                self.assertEqual(json.loads(by_id[tool_id]['result']['content'][0]['text'])['tab_id'],'T')
            self.assertTrue(by_id[8]['result'].get('isError',False),by_id[8])
            self.assertNotIn('PRIVATE TASK',json.dumps(responses))
            self.assertEqual(json.loads((root/'counts.json').read_text()),dict(opens=0,authorizations=6,closed=True))

    def test_authorization_loss_on_catalogue_closes_observe(self):
        import asyncio
        from iterm2_utils.mcp.server import create_server
        from iterm2_utils.mcp.binding import McpBinding
        from iterm2_utils.mcp.connection import ObserveConnection
        from iterm2_utils.models import OmpProfile
        async def check():
            with TemporaryDirectory() as temp:
                root=Path(temp); closed=[]; calls=[]
                class Transport:
                    reader=None; connected=True; connection=object()
                    async def open(self): pass
                    async def build_app(self): return object()
                    async def close(self): closed.append(True); return True
                owner=ObserveConnection(transport_factory=Transport)
                async with owner.lease(): pass
                async def deny(): calls.append(True); raise ValueError('private authorization payload')
                server=create_server(McpBinding(OmpProfile(None,root/'agent'),root,root/'receipt.json',Path(sys.executable)),owner,authorize=deny)
                try: await server.call_tool('list_projects',{})
                except Exception as exc: self.assertNotIn('private authorization payload',str(exc))
                else: self.fail('Unauthorized catalogue call succeeded')
                self.assertEqual((len(calls),len(closed)),(1,1))
        asyncio.run(check())

    def test_extracted_installed_runtime_without_source_checkout(self):
        from tests.test_export import ExportTests
        ExportTests().installed_mcp_smoke()

    def test_loaded_owned_binding_revocation_closes_and_blocks_all_effects(self):
        import asyncio
        from unittest.mock import patch
        from tests.test_mcp_install import InstallTests
        from iterm2_utils.config.mcp import authorize_binding
        from iterm2_utils import lifecycle
        from iterm2_utils.mcp.connection import ObserveConnection
        from iterm2_utils.mcp.server import create_server
        fixture=InstallTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.install(); binding=fixture.binding()
        counts={'opens':0,'closes':0}
        class Transport:
            reader=None; connected=True; connection=object()
            async def open(self): counts['opens']+=1
            async def build_app(self): return object()
            async def close(self): counts['closes']+=1; return True
        async def check():
            owner=ObserveConnection(transport_factory=Transport)
            async def authorize(): authorize_binding(binding)
            server=create_server(binding,owner,authorize=authorize)
            async with owner.lease(): pass  # Independently accepted prior work.
            self.assertEqual(counts,{'opens':1,'closes':0})
            fixture.assertFalse(lifecycle.uninstall(fixture.context,frozenset({'mcp'}),fixture.runner).findings)
            with patch('iterm2_utils.mcp.server.run_launch',side_effect=AssertionError('New launch after revocation')) as launch, \
                 patch('iterm2_utils.mcp.tools.write.post_notification_impl',side_effect=AssertionError('Notification after revocation')) as notify:
                for name,args in [('list_projects',{}),('list_sessions',{}),
                                  ('post_notification',{'title':'fixture','body':'fixture'}),
                                  ('open_shell',{'cwd':str(fixture.home)}),
                                  ('open_shell_window',{'cwd':str(fixture.home)}),
                                  ('launch_omp_task_window',{'cwd':str(fixture.home),'task':'PRIVATE TASK'})]:
                    with self.assertRaises(Exception):
                        await server.call_tool(name,args)
                launch.assert_not_called(); notify.assert_not_called()
            self.assertEqual(counts,{'opens':1,'closes':1})
        asyncio.run(check())
