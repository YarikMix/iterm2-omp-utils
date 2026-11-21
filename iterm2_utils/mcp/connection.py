"""Lazy, serialized observe generations. Never replay a failed operation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any

from .errors import Disconnected, MCPIterm2Error


@dataclass(frozen=True)
class ObserveSession:
    """The app and connection leased from exactly one generation."""
    app: Any
    connection: Any

    def require_app(self):
        return self.app

    def require_connection(self):
        return self.connection


class ObserveConnection:
    """One process owner; lease covers the whole SDK call/transaction."""

    def __init__(self, *, transport_factory=None, timeout=35.0):
        self._factory = transport_factory or _SDKTransport
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._transport = None
        self._app = None
        self._holder = None
        self._closed = False
        self._poisoned = False
        self._cleanup_task = None

    async def _cleanup(self):
        transport = self._transport
        self._app = None
        if transport is None:
            return
        cleanup = asyncio.create_task(transport.close())
        done, _ = await asyncio.wait({cleanup}, timeout=self._timeout)
        if not done:
            cleanup.cancel()
            self._poisoned = True
            # Consume late failures, but never consider cancellation proof of close.
            cleanup.add_done_callback(_consume)
        else:
            try:
                self._poisoned |= cleanup.result() is not True
            except BaseException:
                self._poisoned = True
        if self._transport is transport:
            self._transport = None

    async def _finish_cleanup(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup())
        cleanup = self._cleanup_task
        cancelled = False
        # Keep the lease lock through every cancellation until bounded cleanup
        # proves close or poisons the owner. Concurrent shutdown joins this task.
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        try:
            cleanup.result()
        except BaseException:
            self._poisoned = True
        if self._cleanup_task is cleanup:
            self._cleanup_task = None
        if cancelled:
            raise asyncio.CancelledError()

    @asynccontextmanager
    async def lease(self):
        async with self._lock:
            if self._closed or self._poisoned:
                raise Disconnected()
            self._holder = asyncio.current_task()
            watcher = None
            lost = False

            async def watch():
                nonlocal lost
                await asyncio.wait({self._transport.reader})
                lost = True
                self._holder.cancel()

            try:
                if self._transport is not None and not self._transport.connected:
                    await self._finish_cleanup()
                if self._poisoned:
                    raise Disconnected()
                if self._transport is None:
                    # Retain the owner BEFORE open or app construction can fail.
                    self._transport = self._factory()
                    await asyncio.wait_for(self._transport.open(), self._timeout)
                if self._transport.reader is not None:
                    watcher = asyncio.create_task(watch())
                if self._app is None:
                    self._app = await asyncio.wait_for(self._transport.build_app(), self._timeout)
                yield ObserveSession(self._app, self._transport.connection)
            except BaseException as exc:
                if watcher is not None:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)
                    watcher = None
                await self._finish_cleanup()
                if isinstance(exc, asyncio.CancelledError) and not lost:
                    raise
                if isinstance(exc, MCPIterm2Error):
                    raise
                if not isinstance(exc, Exception) and not lost:
                    raise
                raise Disconnected() from None
            finally:
                if watcher is not None:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)
                self._holder = None

    async def aclose(self):
        """EOF/shutdown: cancel the active lease, close, and forbid new calls."""
        self._closed = True
        holder = self._holder
        if holder is not None and holder is not asyncio.current_task():
            holder.cancel()
        try:
            await asyncio.wait_for(self._lock.acquire(), self._timeout)
        except TimeoutError:
            self._poisoned = True
            await self._finish_cleanup()
            return
        try:
            await self._finish_cleanup()
        finally:
            self._lock.release()


def _consume(task):
    with suppress(BaseException):
        task.result()


class _SDKTransport:
    """Capability-gated adapter for the SDK's legacy WebSocket protocol.

    We own the socket and reader instead of async_create (which hides ownership
    until after connecting). App.async_construct avoids the SDK app singleton.
    """

    def __init__(self):
        import iterm2
        import iterm2.notifications
        import iterm2.tmux
        from websockets.legacy.client import WebSocketClientProtocol
        from websockets.legacy import client

        self.sdk = iterm2
        self.ws_client = client
        self.connection = iterm2.Connection()
        self.reader = None
        self._tasks = set()
        self._socket = None
        self._app = None
        # Private fields are deliberately gated: no fallback to unowned SDK I/O.
        if not isinstance(getattr(self.connection, '_Connection__receivers', None), list):
            raise Disconnected()
        for name in ('_get_receiver_future', '_async_dispatch_to_helper',
                     'set_message_in_future', '_unix_domain_socket_path'):
            if not callable(getattr(self.connection, name, None)):
                raise Disconnected()
        if (not callable(getattr(iterm2.App, 'async_construct', None)) or
                not isinstance(iterm2.notifications._handlers, dict) or
                not all(callable(getattr(WebSocketClientProtocol, name, None))
                        for name in ('close', 'wait_closed')) or
                not hasattr(WebSocketClientProtocol, 'closed')):
            raise Disconnected()

    @property
    def connected(self):
        return self._socket is not None and not self._socket.closed and self.reader is not None and not self.reader.done()

    async def open(self):
        import os
        from iterm2._version import __version__
        from .cookie import request_cookie_async

        cookie = await request_cookie_async()
        headers = {'origin': 'ws://localhost/',
                   'x-iterm2-library-version': f'python {__version__}',
                   'x-iterm2-disable-auth-ui': 'true', 'x-iterm2-cookie': cookie,
                   'x-iterm2-advisory-name': 'iterm2-omp-utils'}
        options = dict(extra_headers=headers, subprotocols=['api.iterm2.com'],
                       ping_interval=None, close_timeout=1, open_timeout=5)
        path = self.connection._unix_domain_socket_path()
        if os.path.exists(path):
            connect = self.ws_client.unix_connect(path, 'ws://localhost/', max_size=None, **options)
        else:
            connect = self.ws_client.connect('ws://localhost:1912', **options)
        self._socket = await connect
        self.connection.websocket = self._socket
        # No await between taking socket ownership and retaining the reader.
        self.reader = asyncio.create_task(self._read())
        self.reader.add_done_callback(_consume)

    async def _read(self):
        from iterm2.api_pb2 import ServerOriginatedMessage
        loop = asyncio.get_running_loop()
        while True:
            data = await self._socket.recv()
            message = ServerOriginatedMessage()
            message.ParseFromString(data)
            future = self.connection._get_receiver_future(message)
            if future is None:
                task = asyncio.create_task(self.connection._async_dispatch_to_helper(message))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                task.add_done_callback(_consume)
            else:
                self.connection.set_message_in_future(loop, message, future)

    async def build_app(self):
        self._app = await self.sdk.App.async_construct(self.connection)
        return self._app

    async def close(self):
        # Stop all SDK code before clearing global notification/delegate state.
        tasks = set(self._tasks)
        if self.reader is not None:
            tasks.add(self.reader)
        for task in tasks:
            task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=1)
            for task in done:
                _consume(task)
        for _, future in self.connection._Connection__receivers:
            future.cancel()
        self.connection._Connection__receivers.clear()
        self.sdk.notifications._handlers.clear()
        self.sdk.App.instance = None
        self.sdk.Session.delegate = None
        self.sdk.Tab.delegate = None
        self.sdk.Window.delegate = None
        self.sdk.tmux.gDELEGATE = None
        if self._app is not None:
            self._app.tokens.clear()
        self._app = None
        socket = self._socket
        if socket is None:
            return True
        closer = asyncio.create_task(socket.close())
        done, pending = await asyncio.wait({closer}, timeout=2)
        if pending:
            closer.cancel()
            closer.add_done_callback(_consume)
            transport = getattr(socket, 'transport', None)
            if transport is None or not callable(getattr(transport, 'abort', None)):
                return False
            transport.abort()
        else:
            _consume(closer)
        waiter = asyncio.create_task(socket.wait_closed())
        done, pending = await asyncio.wait({waiter}, timeout=1)
        if pending:
            waiter.cancel()
            waiter.add_done_callback(_consume)
            return False
        _consume(waiter)
        # A close request/transport.is_closing alone is not proof of closure.
        # wait_closed proves connection_lost; also join the protocol's I/O tasks.
        socket_tasks = {task for name in ('transfer_data_task', 'close_connection_task',
                                         'keepalive_ping_task')
                        if (task := getattr(socket, name, None)) is not None}
        if socket_tasks:
            done, pending = await asyncio.wait(socket_tasks, timeout=1)
            for task in done:
                _consume(task)
            if pending:
                return False
        proof = socket.closed and all(task.done() for task in tasks) and closer.done()
        if proof:
            self.connection.websocket = None
            self._socket = None
        return proof
