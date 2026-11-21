"""Bound stdio entry. Installation/revocation code must supply authorization."""
import asyncio
import sys

from .connection import ObserveConnection
from .server import create_server, serve_stdio


def main(binding=None, *, authorize=None, observe=None):
    if binding is None or authorize is None:
        print('An explicitly authorized installation binding is required.', file=sys.stderr)
        return 2
    try:
        if sys.version_info < (3,12):
            raise ValueError('Unsupported interpreter')
        from importlib.metadata import version
        import iterm2
        installed = tuple(map(int, version('mcp').split('.')[:2]))
        if not (1,12) <= installed < (2,0):
            raise ValueError('Unsupported MCP SDK')
    except (ImportError, ValueError):
        print('Select existing Python 3.12+ with mcp>=1.12,<2 and iterm2.', file=sys.stderr)
        return 2
    owner = observe if observe is not None else ObserveConnection()
    asyncio.run(serve_stdio(create_server(binding, owner, authorize=authorize), owner))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
