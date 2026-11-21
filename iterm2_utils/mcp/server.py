"""One explicitly bound stdio server; never discover an installation implicitly."""
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
import os
from typing import Any

from .binding import McpBinding
from .connection import ObserveConnection
from .launch_tools import LaunchArgs, bound_paths, run_launch
from .observe import register_observe
from ..project_edits import list_owned_projects


def create_server(binding: McpBinding, observe: ObserveConnection, *,
                  authorize: Callable[[], Awaitable[None]]):
    from mcp.server.fastmcp import FastMCP

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield
        finally:
            await observe.aclose()

    server = FastMCP('iterm2-observe', lifespan=lifespan, log_level='CRITICAL')

    async def authorized():
        try:
            await authorize()
        except BaseException:
            await observe.aclose()
            raise RuntimeError('Installation authorization unavailable.') from None

    register_observe(server, observe, authorized, os.environ.get('ITERM_SESSION_ID'))

    @server.tool()
    async def list_projects() -> dict[str, Any]:
        """List the installed project's ordered id/name/path catalogue (visible to the model provider)."""
        await authorized()
        try:
            catalogue = await asyncio.to_thread(list_owned_projects, bound_paths(binding), binding.profile)
            return dict(status=catalogue.status, projects=[asdict(p) for p in catalogue.projects])
        except Exception:
            raise RuntimeError('Project catalogue unavailable.') from None

    async def launch(mode, **kwargs):
        await authorized()
        try:
            return await run_launch(binding, LaunchArgs(mode, **kwargs))
        except Exception:
            raise RuntimeError('Launch inputs or destination unavailable.') from None

    @server.tool()
    async def open_shell(cwd: str | None = None, project: str | None = None,
                         window_id: str | None = None, shell_profile: str | None = None) -> dict[str, Any]:
        """Open one explicitly requested separate login-zsh tab; choose cwd OR installed project. Never retry an uncertain result."""
        return await launch('shell', cwd=cwd, project=project, window_id=window_id, shell_profile=shell_profile)

    @server.tool()
    async def launch_omp_task(task: str, cwd: str | None = None, project: str | None = None,
                              window_id: str | None = None, omp_profile: str | None = None) -> dict[str, Any]:
        """Open one explicitly requested separate omp task tab via private handoff, not history resume. Ack is receipt, not completion; never retry uncertainty."""
        return await launch('handoff', task=task, cwd=cwd, project=project, window_id=window_id, omp_profile=omp_profile)

    return server


async def serve_stdio(server, observe: ObserveConnection):
    """Shared lifecycle for production's bound entry and fixture subprocesses."""
    try:
        await server.run_stdio_async()
    finally:
        await observe.aclose()
