import asyncio
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch, AsyncMock
from runtime.terminal_identity import observe_own_terminal

TID='AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'
class OwnTTY(TestCase):
    def test_stale_inherited_terminal_cannot_authorize_different_tty(self):
        session = SimpleNamespace(session_id=TID, async_get_variable=AsyncMock(return_value='/dev/ttys002'))
        connection = SimpleNamespace(websocket=SimpleNamespace(close=AsyncMock()))
        app = SimpleNamespace(terminal_windows=[SimpleNamespace(window_id='window',tabs=[
            SimpleNamespace(tab_id='tab',sessions=[session])])])
        sdk = SimpleNamespace(Connection=SimpleNamespace(async_create=AsyncMock(return_value=connection)),
                              async_get_app=AsyncMock(return_value=app))
        with patch('runtime.terminal_identity.tty_device',side_effect=lambda path: {'/dev/ttys001':1,'/dev/ttys002':2}.get(path)), patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='ttys001\n')):
            self.assertIsNone(asyncio.run(observe_own_terminal(123,'/dev/ttys001',{'ITERM_SESSION_ID':TID},sdk)))
            session.async_get_variable = AsyncMock(side_effect=['/dev/ttys001',None])
            actual=asyncio.run(observe_own_terminal(123,'/dev/ttys001',{'ITERM_SESSION_ID':TID},sdk))
            self.assertEqual(actual['terminal_id'],TID)
            self.assertEqual(actual['tab_id'],'tab')
            self.assertEqual(actual['window_id'],'window')
        with patch('runtime.terminal_identity.tty_device',return_value=None):
            self.assertIsNone(asyncio.run(observe_own_terminal(123,'/missing',{'ITERM_SESSION_ID':TID},sdk)))

    def test_process_controlling_tty_mismatch_rejects_before_api(self):
        sdk=SimpleNamespace(Connection=SimpleNamespace(async_create=AsyncMock()))
        with patch('runtime.terminal_identity.tty_device',side_effect=lambda path: {'/dev/ttys001':1,'/dev/ttys002':2}.get(path)), patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='ttys002\n')):
            self.assertIsNone(asyncio.run(observe_own_terminal(123,'/dev/ttys001',{'ITERM_SESSION_ID':TID},sdk)))
        sdk.Connection.async_create.assert_not_awaited()
