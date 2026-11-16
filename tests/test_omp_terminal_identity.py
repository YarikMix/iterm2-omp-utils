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


class ProcessBirth(TestCase):
    def test_libproc_live_birth_preserves_microseconds_and_rejects_zombie(self):
        import ctypes
        from runtime.terminal_identity import _ProcBSDInfo, process_start
        class NativeProbe:
            status = 2
            microseconds = 123456
            def __call__(self, pid, flavor, arg, buffer, size):
                self.request = (pid,flavor,arg,size)
                info = _ProcBSDInfo()
                info.pbi_pid, info.pbi_status = pid,self.status
                info.pbi_start_tvsec, info.pbi_start_tvusec = 1800000000,self.microseconds
                ctypes.memmove(buffer,ctypes.byref(info),ctypes.sizeof(info))
                return size
        native = NativeProbe()
        with patch('sys.platform','darwin'), patch('ctypes.CDLL',return_value=SimpleNamespace(proc_pidinfo=native)):
            self.assertEqual(process_start(123),'darwin-bsd:1800000000:123456')
            self.assertEqual(native.request,(123,3,0,136))
            self.assertEqual(_ProcBSDInfo.pbi_start_tvsec.offset,120)
            native.microseconds=123457
            self.assertEqual(process_start(123),'darwin-bsd:1800000000:123457')
            for state in (0,1,5,6):
                native.status=state
                self.assertIsNone(process_start(123))

    def test_unavailable_or_partial_kernel_probe_never_falls_back_to_ps(self):
        from runtime.terminal_identity import process_start
        class PartialProbe:
            def __call__(self, *_args): return 12
        with patch('sys.platform','darwin'), patch('subprocess.run') as shell:
            with patch('ctypes.CDLL',side_effect=OSError('unavailable')):
                self.assertIsNone(process_start(123))
            with patch('ctypes.CDLL',return_value=SimpleNamespace(proc_pidinfo=PartialProbe())):
                self.assertIsNone(process_start(123))
            shell.assert_not_called()

    def test_process_start_cli_returns_shared_authority_without_sdk_or_shell(self):
        import io
        from contextlib import redirect_stdout
        from runtime.terminal_identity import _main
        output = io.StringIO()
        with patch('sys.argv',['terminal_identity.py','--process-start','123']), patch(
                'runtime.terminal_identity.process_start',return_value='darwin-bsd:1800000000:123456') as probe, patch(
                'subprocess.run') as shell, redirect_stdout(output):
            _main()
        self.assertEqual(output.getvalue(), '"darwin-bsd:1800000000:123456"' + chr(10))
        probe.assert_called_once_with(123)
        shell.assert_not_called()
