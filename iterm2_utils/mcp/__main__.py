"""Bound stdio entry. Installation/revocation code must supply authorization."""
import asyncio
import sys

from .connection import ObserveConnection
from .server import create_server, serve_stdio


def main(binding=None, *, authorize=None, observe=None):
    if binding is None or authorize is None:
        print('An explicitly authorized installation binding is required.', file=sys.stderr)
        return 2
    owner = observe if observe is not None else ObserveConnection()
    asyncio.run(serve_stdio(create_server(binding, owner, authorize=authorize), owner))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
