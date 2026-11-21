"""Offline observe contracts: no host API, cookies, ports or permissions."""
import asyncio
import contextlib
import importlib.util
import inspect
import io
import json
import subprocess
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, call, patch

from iterm2_utils.mcp.connection import ObserveConnection
from iterm2_utils.mcp.errors import Disconnected, AuthDenied
from iterm2_utils.mcp.observe import register_observe, OBSERVE_TOOLS
from iterm2_utils.mcp.output_cursor import encode_cursor, decode_cursor


def setUpModule():
    # Import optional SDKs outside unittest's timed async test tasks.
    if importlib.util.find_spec('iterm2') and importlib.util.find_spec('mcp'):
        global iterm2, FastMCP
        import iterm2
        from mcp.server.fastmcp import FastMCP


class Transport:
    def __init__(self, events, *, fail=False, close=True):
        self.events, self.fail, self.proof = events, fail, close
        self.connection = object()
        self.connected = False
        self.closed = False
        self.reader = None

    async def open(self):
        self.events.append('open')
        self.connected = True
        self.reader = asyncio.create_task(asyncio.Event().wait())

    async def build_app(self):
        if self.fail:
            raise RuntimeError('secret terminal payload')
        return NS(connection=self.connection)

    async def close(self):
        self.events.append('close')
        self.connected = False
        self.reader.cancel()
        await asyncio.gather(self.reader, return_exceptions=True)
        self.closed = True
        return self.proof


class Server:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn
        return register


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_init_failure_closes_socket_before_new_generation(self):
        events = []
        old, new = Transport(events, fail=True), Transport(events)
        transports = iter([old, new])
        owner = ObserveConnection(transport_factory=lambda: next(transports))
        with self.assertRaises(Disconnected):
            async with owner.lease():
                self.fail('failed app must not escape')
        async with owner.lease() as session:
            self.assertIs(session.app.connection, new.connection)
            self.assertIs(session.connection, new.connection)
            self.assertEqual(events, ['open', 'close', 'open'])
            self.assertTrue(old.reader.done())
        await owner.aclose()
        await owner.aclose()
        self.assertEqual(events, ['open', 'close', 'open', 'close'])

    async def test_concurrent_first_calls_share_one_generation(self):
        events, seen = [], []
        transport = Transport(events)
        owner = ObserveConnection(transport_factory=lambda: transport)
        async def call():
            async with owner.lease() as session:
                seen.append(session.connection)
                await asyncio.sleep(0)
        await asyncio.gather(call(), call())
        self.assertEqual(events, ['open'])
        self.assertEqual(seen, [transport.connection, transport.connection])
        await owner.aclose()

    async def test_idle_no_connect_cancel_eof_and_unproven_close(self):
        events = []
        transport = Transport(events)
        owner = ObserveConnection(transport_factory=lambda: transport)
        self.assertEqual(events, [])
        entered = asyncio.Event()
        async def call():
            async with owner.lease():
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(call())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(transport.reader.done())
        self.assertTrue(transport.closed)
        await owner.aclose()
        # EOF is process shutdown, not a reason to reconnect.
        with self.assertRaises(Disconnected):
            async with owner.lease():
                pass
        events = []
        transport = Transport(events, close=False)
        owner = ObserveConnection(transport_factory=lambda: transport)
        async with owner.lease():
            pass
        transport.connected = False
        for _ in range(2):
            with self.assertRaises(Disconnected):
                async with owner.lease():
                    pass
        self.assertEqual(events, ['open', 'close'])
        await owner.aclose()

    async def test_midcall_loss_does_not_replay(self):
        events, calls = [], []
        transports = [Transport(events), Transport(events)]
        remaining = iter(transports)
        owner = ObserveConnection(transport_factory=lambda: next(remaining))
        with self.assertRaises(Disconnected):
            async with owner.lease():
                calls.append('side effect')
                raise ConnectionError('secret response')
        self.assertEqual(calls, ['side effect'])
        async with owner.lease() as session:
            self.assertIs(session.connection, transports[1].connection)
            self.assertEqual(events, ['open', 'close', 'open'])
        await owner.aclose()

    async def test_shutdown_cancels_inflight_and_hung_cleanup_is_bounded(self):
        transport = Transport([])
        owner = ObserveConnection(transport_factory=lambda: transport, timeout=0.02)
        entered = asyncio.Event()
        async def call():
            async with owner.lease():
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(call())
        await entered.wait()
        await asyncio.wait_for(owner.aclose(), 0.5)
        self.assertTrue(task.done())
        self.assertTrue(transport.reader.done())
        transport = Transport([])
        owner = ObserveConnection(transport_factory=lambda: transport, timeout=0.02)
        async with owner.lease():
            pass
        async def hang():
            await asyncio.Event().wait()
        transport.close = hang
        transport.connected = False
        with self.assertRaises(Disconnected):
            async with owner.lease():
                pass
        with self.assertRaises(Disconnected):
            async with owner.lease():
                pass
        # The deliberately unproved fake socket is disposed by the test only.
        transport.reader.cancel()
        await asyncio.gather(transport.reader, return_exceptions=True)
        await owner.aclose()

    async def test_repeated_cancellation_cannot_reopen_before_close_proof(self):
        events = []
        old, new = Transport(events), Transport(events)
        closing, prove_close, reopened = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def slow_close():
            events.append('closing')
            closing.set()
            await prove_close.wait()
            return await Transport.close(old)
        old.close = slow_close
        async def new_open():
            reopened.set()
            await Transport.open(new)
        new.open = new_open
        transports = iter([old, new])
        owner = ObserveConnection(transport_factory=lambda: next(transports), timeout=1)
        async def failed_call():
            async with owner.lease():
                raise ConnectionError('lost response')
        async def next_call():
            async with owner.lease():
                pass
        failed = asyncio.create_task(failed_call())
        await closing.wait()
        # Each yield delivers one separate cancellation while close is blocked.
        for _ in range(3):
            failed.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        following = asyncio.create_task(next_call())
        opened = asyncio.create_task(reopened.wait())
        try:
            done, _ = await asyncio.wait({opened}, timeout=0.03)
            self.assertFalse(done, 'second socket opened before old close proof')
            self.assertFalse(old.closed)
            prove_close.set()
            with self.assertRaises(asyncio.CancelledError):
                await failed
            await following
            self.assertEqual(events, ['open', 'closing', 'close', 'open'])
            self.assertTrue(old.reader.done())
        finally:
            prove_close.set()
            opened.cancel()
            await asyncio.gather(failed, following, opened, return_exceptions=True)
            await owner.aclose()

    async def test_cancel_during_app_then_watcher_join_finishes_cleanup(self):
        events = []
        old, new = Transport(events), Transport(events)
        constructing, joining, release_join = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def build_app():
            constructing.set()
            await asyncio.Event().wait()
        old.build_app = build_app
        transports = iter([old, new])
        owner = ObserveConnection(transport_factory=lambda: next(transports))
        gather = asyncio.gather
        first_join = True
        async def join(*tasks, **kwargs):
            nonlocal first_join
            if first_join and len(tasks) == 1 and tasks[0].get_coro().__name__ == 'watch':
                first_join = False
                joining.set()
                await release_join.wait()
            return await gather(*tasks, **kwargs)
        async def call():
            async with owner.lease():
                self.fail('cancelled App must not escape')
        try:
            with patch('iterm2_utils.mcp.connection.asyncio.gather', side_effect=join):
                task = asyncio.create_task(call())
                await constructing.wait()
                task.cancel()
                await joining.wait()
                task.cancel()
                await asyncio.sleep(0)
                release_join.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertTrue(old.closed, 'watcher join cancellation skipped transport cleanup')
            self.assertTrue(old.reader.done())
            async with owner.lease() as session:
                self.assertIs(session.connection, new.connection)
            self.assertEqual(events, ['open', 'close', 'open'])
        finally:
            release_join.set()
            await owner.aclose()


CONTRACTS = {
    'list_sessions': (), 'get_session_info': (('session_id', None),),
    'get_screen_contents': (('session_id', None),), 'get_selection': (('session_id', None),),
    'get_scrollback': (('session_id', None), ('n_lines', 200)),
    'get_recent_output': (('session_id', None), ('cursor', None)),
    'get_variable': (('name', inspect.Parameter.empty), ('session_id', None)),
    'list_profiles': (), 'set_badge': (('text', inspect.Parameter.empty), ('session_id', None)),
    'set_title': (('title', inspect.Parameter.empty), ('session_id', None)),
    'set_tab_color': (('r', inspect.Parameter.empty), ('g', inspect.Parameter.empty), ('b', inspect.Parameter.empty), ('session_id', None)),
    'set_user_variable': (('name', inspect.Parameter.empty), ('value', inspect.Parameter.empty), ('session_id', None)),
    'post_notification': (('title', inspect.Parameter.empty), ('body', inspect.Parameter.empty)),
}

# Upstream v0.1.1 input contracts; descriptive schema titles are not API.
SCHEMA_PROPERTIES = {
    'session_id': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'default': None},
    'cursor': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'default': None},
    'n_lines': {'type': 'integer', 'default': 200},
    'name': {'type': 'string'}, 'value': {'type': 'string'},
    'text': {'type': 'string'}, 'title': {'type': 'string'}, 'body': {'type': 'string'},
    'r': {'type': 'integer'}, 'g': {'type': 'integer'}, 'b': {'type': 'integer'},
}


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_observe_tool_compatibility_and_privacy(self):
        events = []
        transport = Transport(events)
        owner = ObserveConnection(transport_factory=lambda: transport)
        server = Server()
        auth = AsyncMock()
        register_observe(server, owner, auth, 'w1t2p3:session')
        self.assertEqual(set(server.tools), set(CONTRACTS))
        self.assertEqual(OBSERVE_TOOLS, frozenset(CONTRACTS))
        for name, params in CONTRACTS.items():
            self.assertEqual(tuple((p.name, p.default) for p in inspect.signature(server.tools[name]).parameters.values()), params)
        self.assertEqual(events, [])
        from iterm2_utils.mcp.tools import write
        with patch.object(write, 'post_notification_impl', new=AsyncMock(return_value={'ok': True})) as notify:
            self.assertEqual(await server.tools['post_notification']('title', 'body'), {'ok': True})
            self.assertEqual(events, [])
        for name, kwargs in [('set_tab_color', dict(r=-1, g=0, b=0)), ('set_user_variable', dict(name='session.path', value='x'))]:
            with self.assertRaises(RuntimeError):
                await server.tools[name](**kwargs)
        output = io.StringIO()
        with patch('iterm2_utils.mcp.tools.read.list_sessions_impl', side_effect=RuntimeError('secret payload')), contextlib.redirect_stdout(output):
            with self.assertRaises(RuntimeError) as error:
                await server.tools['list_sessions']()
        self.assertNotIn('secret', str(error.exception))
        self.assertEqual(output.getvalue(), '')
        async with owner.lease():
            pass
        auth.side_effect = AuthDenied('private cookie')
        with patch.object(write, 'post_notification_impl', new=AsyncMock()) as notify:
            with self.assertRaisesRegex(RuntimeError, 'denied'):
                await server.tools['post_notification']('title', 'body')
            notify.assert_not_awaited()
        self.assertTrue(transport.closed)
        self.assertTrue(transport.reader.done())
        self.assertEqual(auth.await_count, 5)
        await owner.aclose()

    async def test_session_cursor_and_notification_boundaries(self):
        from iterm2_utils.mcp.session import resolve_session, normalize_iterm_session_id
        from iterm2_utils.mcp.errors import CursorInvalid, InvalidArgument, NoCurrentSession, SessionNotFound
        from iterm2_utils.mcp.tools.write import post_notification_impl
        session = object()
        app = NS(get_session_by_id=lambda sid: session if sid == 'id' else None)
        self.assertEqual(normalize_iterm_session_id('w1t1p1:id'), 'id')
        self.assertIs(resolve_session(app, None, 'id'), session)
        with self.assertRaises(NoCurrentSession):
            resolve_session(app, None, None)
        with self.assertRaises(SessionNotFound):
            resolve_session(app, 'absent', 'id')
        for cursor in ['?', 'x' * 16385, encode_cursor(session_id='other', line_number=1)]:
            with self.assertRaises(CursorInvalid):
                decode_cursor(cursor, expected_session_id='id')
        with patch('iterm2_utils.mcp.tools.write.subprocess.run') as run:
            run.return_value = NS(returncode=0)
            self.assertEqual(await post_notification_impl(title='a"', body='b\\\n"'), {'ok': True})
            self.assertEqual(run.call_args.args[0], ['/usr/bin/osascript', '-e', 'display notification "b\\\\\\n\\"" with title "a\\""'])
            self.assertEqual(run.call_args.kwargs['timeout'], 5.0)
            self.assertNotIn('ITERM2_COOKIE', run.call_args.kwargs['env'])
            with self.assertRaises(InvalidArgument):
                await post_notification_impl(title='t' * 129, body='body')
            with self.assertRaises(InvalidArgument):
                await post_notification_impl(title='t', body='b' * 1025)
            self.assertEqual(run.call_count, 1)

    @unittest.skipUnless(importlib.util.find_spec('iterm2') and importlib.util.find_spec('mcp'), 'optional SDK dependencies unavailable')
    async def test_sdk_schema_and_transaction_results(self):
        from iterm2_utils.mcp.tools import read, write
        server = FastMCP('offline')
        owner = ObserveConnection()
        register_observe(server, owner, AsyncMock(), 'id')
        schemas = {t.name: t.inputSchema for t in await server.list_tools()}
        for name, params in CONTRACTS.items():
            self.assertEqual(set(schemas[name].get('required', [])), {n for n, d in params if d is inspect.Parameter.empty})
            properties = {key: {field: value for field, value in prop.items()
                                if field not in ('title', 'description')}
                          for key, prop in schemas[name]['properties'].items()}
            self.assertEqual(properties, {key: SCHEMA_PROPERTIES[key] for key, _ in params})
        active = []
        class Transaction:
            def __init__(self, conn): self.conn = conn
            async def __aenter__(self): active.append(self.conn)
            async def __aexit__(self, *args): active.pop()
        async def info():
            self.assertEqual(active, ['connection'])
            return NS(overflow=10, scrollback_buffer_height=6000, mutable_area_height=2)
        async def contents(start, count):
            self.assertEqual(active, ['connection'])
            return [NS(string=f'{start}:{count}')]
        session = NS(session_id='id', async_get_line_info=info, async_get_contents=contents,
            name='name', grid_size=NS(width=80, height=24),
            async_get_profile=AsyncMock(return_value=NS(name='profile')),
            async_get_variable=AsyncMock(side_effect=['cwd', 'badge', 'tty']),
            async_get_screen_contents=AsyncMock(return_value=NS(number_of_lines=1, line=lambda _: NS(string='screen'), cursor_coord=NS(x=2, y=3))),
            async_get_selection=AsyncMock(return_value=NS(sub_selections=[])),
            async_set_variable=AsyncMock(), async_set_name=AsyncMock(), async_set_profile_properties=AsyncMock())
        tab = NS(tab_id='t', all_sessions=[session], current_session=session)
        window = NS(window_id='w', tabs=[tab], current_tab=tab)
        app = NS(get_session_by_id=lambda _: session, windows=[window], current_window=window)
        client = NS(require_app=lambda: app, require_connection=lambda: 'connection')
        args = dict(session_id_arg=None, env_session_id='id')
        self.assertEqual(read.list_sessions_impl(client), {'windows': [{'window_id': 'w', 'tabs': [{'tab_id': 't', 'active': True, 'sessions': [{'session_id': 'id', 'name': 'name', 'active': True}]}]}], 'buried_sessions': []})
        self.assertEqual(await read.get_session_info_impl(client, **args), {'session_id':'id', 'name':'name', 'working_directory':'cwd', 'profile_name':'profile', 'badge':'badge', 'tty':'tty', 'dimensions':{'cols':80,'rows':24}})
        self.assertEqual(await read.get_screen_contents_impl(client, **args), {'text':'screen','cursor':{'row':3,'col':2}})
        self.assertEqual(await read.get_selection_impl(client, **args), {'text':''})
        with patch.object(iterm2, 'Transaction', Transaction):
            self.assertEqual(await read.get_scrollback_impl(client, **args, n_lines=9999), {'text': '1012:5000'})
            recent = await read.get_recent_output_impl(client, **args, cursor=None)
            self.assertEqual(recent, {'text': '6010:2', 'cursor': encode_cursor(session_id='id', line_number=6011), 'cursor_expired': False})
            self.assertEqual(await read.get_recent_output_impl(client, **args, cursor=recent['cursor']), {'text':'','cursor':recent['cursor'],'cursor_expired':False})
            expired = await read.get_recent_output_impl(client, **args, cursor=encode_cursor(session_id='id', line_number=1))
            self.assertTrue(expired['cursor_expired'])
        session.async_get_variable.side_effect = None
        session.async_get_variable.return_value = 'value'
        self.assertEqual(await read.get_variable_impl(client, **args, name='user.x'), {'name':'user.x','value':'value'})
        with patch.object(iterm2.PartialProfile, 'async_query', new=AsyncMock(return_value=[NS(name='profile',guid='guid')])):
            self.assertEqual(await read.list_profiles_impl(client), {'profiles':[{'name':'profile','guid':'guid'}]})
        self.assertEqual(await write.set_badge_impl(client, **args, text='badge'), {'ok':True,'badge':'badge'})
        self.assertEqual(await write.set_title_impl(client, **args, title='title'), {'ok':True,'title':'title'})
        self.assertEqual(await write.set_user_variable_impl(client, **args, name='user.x', value='x'), {'ok':True,'name':'user.x','value':'x'})
        self.assertEqual(await write.set_tab_color_impl(client, **args, r=1,g=2,b=3), {'ok':True,'rgb':[1,2,3]})
        session.async_set_variable.assert_has_awaits([
            call('user.badge', 'badge'), call('user.x', 'x')])
        self.assertEqual(session.async_set_variable.await_count, 2)
        session.async_set_name.assert_awaited_once_with('title')
        session.async_set_profile_properties.assert_awaited_once()
        profile_args = session.async_set_profile_properties.await_args
        self.assertEqual(profile_args.kwargs, {})
        self.assertEqual(len(profile_args.args), 1)
        color = {'Red Component': 1 / 255, 'Green Component': 2 / 255,
                 'Blue Component': 3 / 255, 'Alpha Component': 1.0,
                 'Color Space': 'sRGB'}
        self.assertEqual({key: json.loads(value) for key, value in profile_args.args[0].values.items()}, {
            'Tab Color': color, 'Tab Color (Light)': color, 'Tab Color (Dark)': color,
            'Use Tab Color': True, 'Use Tab Color (Light)': True, 'Use Tab Color (Dark)': True})
        await owner.aclose()

    async def test_cancel_during_app_and_reader_loss_cleanup(self):
        events = []
        transport = Transport(events)
        entered = asyncio.Event()
        async def build_app():
            entered.set()
            await asyncio.Event().wait()
        transport.build_app = build_app
        owner = ObserveConnection(transport_factory=lambda: transport)
        async def call():
            async with owner.lease():
                await asyncio.Event().wait()
        task = asyncio.create_task(call())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(events, ['open', 'close'])
        self.assertTrue(transport.reader.done())
        await owner.aclose()
        transport = Transport([])
        owner = ObserveConnection(transport_factory=lambda: transport)
        entered = asyncio.Event()
        async def in_flight():
            async with owner.lease():
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(in_flight())
        await entered.wait()
        transport.reader.cancel()
        with self.assertRaises(Disconnected):
            await asyncio.wait_for(task, 0.5)
        self.assertTrue(transport.closed)
        await owner.aclose()

    async def test_cookie_cancellation_kills_and_reaps_without_environment_mutation(self):
        from iterm2_utils.mcp.cookie import request_cookie_async
        entered = asyncio.Event()
        class Process:
            returncode = None
            killed = False
            reaped = False
            async def communicate(self):
                entered.set()
                await asyncio.Event().wait()
            def kill(self):
                self.killed = True
            async def wait(self):
                self.reaped = True
        process = Process()
        with patch('iterm2_utils.mcp.cookie.asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)) as spawn:
            task = asyncio.create_task(request_cookie_async())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(process.killed)
            self.assertTrue(process.reaped)
            self.assertEqual(spawn.call_args.args, ('/usr/bin/osascript', '-e', 'tell application "iTerm2" to request cookie'))
            self.assertNotIn('ITERM2_COOKIE', spawn.call_args.kwargs['env'])

    @unittest.skipUnless(importlib.util.find_spec('iterm2') and importlib.util.find_spec('mcp'), 'optional SDK dependencies unavailable')
    async def test_sdk_transport_owns_socket_before_app_and_proves_teardown(self):
        import iterm2
        import iterm2.notifications
        from iterm2_utils.mcp.connection import _SDKTransport
        events = []
        class Socket:
            closed = False
            transport = None
            async def recv(self):
                await asyncio.Event().wait()
            async def close(self):
                events.append('close')
                self.closed = True
            async def wait_closed(self):
                self.assert_closed = self.closed
        sockets = [Socket(), Socket()]
        index = iter(sockets)
        async def connect(*args, **kwargs):
            self.assertEqual(args, ('ws://localhost:1912',))
            self.assertEqual(kwargs['extra_headers']['x-iterm2-cookie'], 'test-cookie')
            self.assertEqual(kwargs['open_timeout'], 5)
            events.append('open')
            return next(index)
        constructions = []
        async def build(connection):
            self.assertIs(connection.websocket, sockets[len(constructions)])
            constructions.append(connection)
            # Model SDK mutation before a partially constructed App fails.
            iterm2.notifications._handlers['partial'] = ['callback']
            iterm2.Session.delegate = object()
            if len(constructions) == 1:
                raise RuntimeError('secret app response')
            return NS(connection=connection, tokens=['token'])
        with patch('iterm2_utils.mcp.cookie.request_cookie_async', new=AsyncMock(return_value='test-cookie')), patch('os.path.exists', return_value=False), patch('websockets.legacy.client.connect', side_effect=connect), patch.object(iterm2.App, 'async_construct', side_effect=build):
            owner = ObserveConnection()
            with self.assertRaises(Disconnected):
                async with owner.lease():
                    pass
            self.assertTrue(sockets[0].closed)
            self.assertEqual(iterm2.notifications._handlers, {})
            self.assertIsNone(iterm2.Session.delegate)
            async with owner.lease() as session:
                self.assertIs(session.app.connection, constructions[1])
                self.assertEqual(events, ['open', 'close', 'open'])
            await owner.aclose()
            self.assertTrue(sockets[1].closed)
            self.assertEqual(iterm2.notifications._handlers, {})
        # Capability refusal occurs before any cookie request/socket opening.
        with patch.object(iterm2.Connection, '_get_receiver_future', new=None):
            # Capability must be callable, not merely an attribute.
            with self.assertRaises(Disconnected):
                _SDKTransport()

    async def test_every_tool_checks_authorization_before_connection_or_side_effect(self):
        owner = ObserveConnection(transport_factory=lambda: self.fail('unauthorized socket'))
        server = Server()
        authorize = AsyncMock(side_effect=AuthDenied('private payload'))
        register_observe(server, owner, authorize, None)
        for name, params in CONTRACTS.items():
            kwargs = {key: (0 if key in ('r', 'g', 'b') else 'input')
                      for key, default in params if default is inspect.Parameter.empty}
            with self.assertRaisesRegex(RuntimeError, 'denied'):
                await server.tools[name](**kwargs)
        self.assertEqual(authorize.await_count, 13)
        await owner.aclose()

    async def test_variable_tab_window_scope_and_unavailable_containers(self):
        from iterm2_utils.mcp.errors import ScopeUnavailable
        from iterm2_utils.mcp.tools.read import get_variable_impl
        tab = NS(tab_id='tab', async_get_variable=AsyncMock(return_value='tab title'))
        window = NS(async_get_variable=AsyncMock(return_value='window name'))
        session = NS(tab=tab, async_get_variable=AsyncMock())
        app = NS(get_session_by_id=lambda sid: session if sid == 'id' else None,
                 get_window_for_tab=lambda tid: window if tid == 'tab' else None)
        client = NS(require_app=lambda: app)
        args = dict(session_id_arg='id', env_session_id=None)
        self.assertEqual(await get_variable_impl(client, **args, name='tab.title'),
                         {'name': 'tab.title', 'value': 'tab title'})
        tab.async_get_variable.assert_awaited_once_with('tab.title')
        self.assertEqual(await get_variable_impl(client, **args, name='window.name'),
                         {'name': 'window.name', 'value': 'window name'})
        window.async_get_variable.assert_awaited_once_with('window.name')
        session.async_get_variable.assert_not_awaited()
        session.tab = None
        for name in ('tab.title', 'window.name'):
            with self.assertRaises(ScopeUnavailable) as error:
                await get_variable_impl(client, **args, name=name)
            self.assertEqual(error.exception.scope, 'tab')
        session.tab = tab
        app.get_window_for_tab = lambda tid: None
        with self.assertRaises(ScopeUnavailable) as error:
            await get_variable_impl(client, **args, name='window.name')
        self.assertEqual(error.exception.scope, 'window')

    async def test_notification_subprocess_timeout_is_bounded_and_sanitized(self):
        server = Server()
        owner = ObserveConnection(transport_factory=lambda: self.fail('notification opened socket'))
        register_observe(server, owner, AsyncMock(), None)
        output = io.StringIO()
        timeout = subprocess.TimeoutExpired('private command', 5, stderr='private payload')
        with patch('iterm2_utils.mcp.tools.write.subprocess.run', side_effect=timeout) as run, contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, 'timed out after 5s') as error:
                await server.tools['post_notification']('title', 'body')
            self.assertNotIn('private', str(error.exception))
            self.assertEqual(run.call_args.kwargs['timeout'], 5.0)
            self.assertEqual(run.call_args.args[0], [
                '/usr/bin/osascript', '-e', 'display notification "body" with title "title"'])
            self.assertEqual(run.call_count, 1)
        self.assertEqual(output.getvalue(), '')
        await owner.aclose()
