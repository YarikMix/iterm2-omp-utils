"""Historical MCP storage addresses, never agent discovery or executable calls.

A CLI-normalized registration does not identify CODEX_HOME/CLAUDE_CONFIG_DIR.
Only a separately receipted, exact server address proves the storage location.
"""
import copy
from pathlib import Path
from .. import state
from .iterm import same

NAME = 'iterm2-observe'
ARGS = ['--with', 'mcp<2', 'mcp-server-iterm2==0.1.1']
DEFINITION = {'command':'uvx','args':ARGS,'scope':'user','enabled':True,'environment_empty':True}


def is_address(resource):
    kind = resource['kind']
    pointer = resource['locator'].get('pointer', [])
    return (kind in {'json','toml'} and len(pointer) == 2 and
            pointer == ['mcpServers' if kind == 'json' else 'mcp_servers', NAME])


def validate_address(resource):
    state.validate_resources([resource])
    if not is_address(resource) or Path(resource['target']).resolve() != Path(resource['target']):
        raise ValueError('Historical MCP storage provenance is unavailable')
    return resource


def storage_resource(registration, resources):
    """Resolve only companion ownership evidence, not a conventional filename."""
    state.validate_resources([registration])
    if (registration['kind'] != 'registration' or registration['target'] not in {'codex','claude'} or
            registration['locator'] != {'name':NAME}):
        raise ValueError('Unknown historical MCP registration')
    for value in (registration['before'], registration['installed']):
        if value['exists'] and not same(value['value'], DEFINITION):
            raise ValueError('Unknown historical MCP definition')
    matches = []
    for resource in resources:
        if (not is_address(resource) or
                resource['kind'] != ('toml' if registration['target'] == 'codex' else 'json')):
            continue
        validate_address(resource)
        expected = {'command':'uvx','args':ARGS}
        if resource['kind'] == 'json':
            expected = dict(expected, type='stdio')
        if (same(resource['installed'], {'exists':True,'value':expected}) and
                same(resource['before'], {'exists':False,'value':None}) and
                registration['installed']['exists'] and not registration['before']['exists'] and
                any(owner.removeprefix(registration['target']+':') == 'mcp'
                    for owner in resource['owners'])):
            matches.append(resource)
    if len(matches) != 1:
        raise ValueError('Historical MCP storage provenance is unavailable')
    return copy.deepcopy(matches[0])


def patch_storage(resource, raw, value):
    """Patch one whole server, including a TOML table, retaining foreign lines."""
    from . import jsonfile, tomlfile
    validate_address(resource)
    pointer = tuple(resource['locator']['pointer'])
    if resource['kind'] == 'json':
        return jsonfile.patch(raw or b'{}', pointer, value['value'], remove=not value['exists'])
    content = raw or b''
    lines, spans = tomlfile._spans(content)
    removed = set()
    for kind, address, start, end in spans:
        if kind == 'array' and (address[:len(pointer)] == pointer or pointer[:len(address)] == address):
            raise ValueError('Ambiguous historical MCP array table')
        if address[:len(pointer)] == pointer:
            if kind not in {'table','value'}:
                raise ValueError('Ambiguous historical MCP storage')
            removed.update(range(start, end))
    cleaned = ''.join(line for index, line in enumerate(lines) if index not in removed).encode()
    tomlfile.parse(cleaned)
    if not value['exists']:
        return cleaned
    # Represent the one owned object as an inline value, never serialize the
    # surrounding document. This also works for rollback of a removed table.
    return tomlfile.patch(cleaned, pointer, value['value'])
