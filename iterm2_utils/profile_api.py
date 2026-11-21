"""Single-request native SDK worker. No terminal text, session writes or retries."""
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import json
import os
import sys

from .config.iterm import (BAR_KEYS, existing, identifier, same, validate_bar,
                           validate_inventory, validate_position)


def _request(request):
    if type(request) is not dict:
        raise ValueError()
    operation = request.get('operation')
    fields = {'operation'}
    if operation == 'inspect' and 'launch_guids' in request:
        fields.add('launch_guids')
        rows = request['launch_guids']
        if type(rows) is not list or not rows or len(rows) > 256:
            raise ValueError()
        if len({identifier(g) for g in rows}) != len(rows):
            raise ValueError()
    if operation == 'inspect' and 'reference_guids' in request:
        fields.add('reference_guids')
        if type(request['reference_guids']) is not list:
            raise ValueError()
        for guid in request['reference_guids']:
            identifier(guid)
    if operation == 'inspect' and 'replaced_bars' in request:
        fields.add('replaced_bars')
        rows = request['replaced_bars']
        if type(rows) is not list or len(rows) > 256:
            raise ValueError()
        guids = set()
        for row in rows:
            if type(row) is not dict or set(row) != {'guid','bar'} or row['guid'] in guids:
                raise ValueError()
            guids.add(identifier(row['guid'])); validate_bar(row['bar'])
    if operation in {'read_bar','write_bar'}:
        fields.add('guid'); identifier(request.get('guid'))
    if operation in {'write_bar','write_position'}:
        fields.update({'value','expected'})
        validator = validate_bar if operation == 'write_bar' else validate_position
        validator(request.get('value')); existing(request.get('expected'), validator)
    if operation not in {'sessions_empty','inspect','read_bar','write_bar','read_position','write_position'} or set(request) != fields:
        raise ValueError()
    return operation


def _refs(properties, guids, names):
    found = set()
    parent = properties.get('Dynamic Profile Parent Name')
    if parent:
        if type(parent) is not str or parent not in names:
            raise ValueError('Unknown dynamic profile parent')
        found.add(names[parent])
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                visit(key); visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str):
            # Include opaque/encoded and hidden fields, even when not visible in the bar.
            found.update(guid for guid in guids if guid in value)
            try:
                decoded = json.loads(value)
            except ValueError:
                return
            if isinstance(decoded, (dict,list,str)) and decoded != value:
                visit(decoded)
    visit({k:v for k,v in properties.items() if k not in {'Guid','Name'}})
    return sorted(found)


def _bar(properties):
    value = {key: properties[key] for key in BAR_KEYS}
    visible = value['Show Status Bar']
    # iTerm2 can expose this boolean as a JSON integer. Keep receipts and CAS boolean.
    if type(visible) is int and visible in (0, 1):
        value['Show Status Bar'] = bool(visible)
    return validate_bar(value)


async def _inventory(sdk, connection, reference_guids=(), replaced_bars=(), launch_guids=()):
    profiles = await sdk.Profile.async_get(connection)
    raw = [p.all_properties for p in profiles]
    persistent_guids = {identifier(p['Guid']) for p in raw}
    guids = persistent_guids | set(reference_guids)
    if not set(launch_guids) <= persistent_guids:
        raise ValueError('Launch evidence unavailable')
    names = {identifier(p['Name']):p['Guid'] for p in raw}
    replacements = {p['guid']:p['bar'] for p in replaced_bars}
    if not set(replacements) <= persistent_guids:
        raise ValueError('Replaced profile unavailable')
    rows = []
    for p in raw:
        properties = p
        if p['Guid'] in replacements:
            if not same(_bar(p),replacements[p['Guid']]):
                raise ValueError('Replaced profile bar changed')
            properties = {k:v for k,v in p.items() if k not in BAR_KEYS}
        rows.append(dict(guid=p['Guid'], name=p['Name'], bar=_bar(p),
            working_directory=p.get('Working Directory'), references=_refs(properties,guids,names)))
        if p['Guid'] in launch_guids:
            rows[-1]['launch'] = dict(parent_guid=p.get('Dynamic Profile Parent GUID'),
                custom_directory=p.get('Custom Directory'), custom_command=p.get('Custom Command'),
                command=p.get('Command'))
    app = await sdk.async_get_app(connection)
    sessions = [s for window in app.terminal_windows for tab in window.tabs for s in tab.all_sessions]
    sessions.extend(app.buried_sessions)
    records = []
    for session in sessions:
        properties = (await session.async_get_profile()).all_properties
        original = properties.get('Original Guid')
        guid = identifier(original if original is not None else properties.get('Guid'))
        reference_properties = properties
        if launch_guids and guid in replacements:
            if not same(_bar(properties), replacements[guid]):
                raise ValueError('Session panel changed')
            reference_properties = {k:v for k,v in properties.items() if k not in BAR_KEYS}
        records.append(dict(id=session.session_id, profile_guid=guid, bar=_bar(properties),
                            references=_refs(reference_properties, guids, names), provenance=guid in persistent_guids))
    default = await sdk.Profile.async_get_default(connection)
    position = await sdk.preferences.async_get_preference(connection, sdk.preferences.PreferenceKey.STATUS_BAR_POSITION)
    return validate_inventory(dict(complete=True, profiles=rows, sessions=records,
                                   default_guid=default.guid, position=position))


def _profile(snapshot, guid):
    matches = [p for p in snapshot['profiles'] if p['guid'] == guid]
    if len(matches) != 1:
        raise ValueError()
    return matches[0]


def _sessions(snapshot, guid, bar):
    for session in snapshot['sessions']:
        if not session['provenance'] or (session['profile_guid'] == guid and not same(session['bar'], bar)):
            raise ValueError()


async def _operate(request):
    connection, sent = None, False
    try:
        operation = _request(request)
        import iterm2
        connection = await iterm2.Connection.async_create()
        if operation == 'sessions_empty':
            response = await iterm2.rpc.async_list_sessions(connection)
            if not response.HasField('list_sessions_response'):
                raise ValueError('Native session coverage unavailable')
            sessions = response.list_sessions_response
            empty = not sessions.buried_sessions and all(
                tab.HasField('root') and not tab.root.links and
                not tab.minimized_sessions and not tab.active_session_id
                for window in sessions.windows for tab in window.tabs)
            return {'status':'ok','value':empty}
        snapshot = await _inventory(iterm2, connection, request.get('reference_guids', ()),
            request.get('replaced_bars', ()), request.get('launch_guids', ()))
        if operation == 'inspect':
            return {'status':'ok','value':snapshot}
        bar = operation.endswith('_bar')
        current = _profile(snapshot, request['guid'])['bar'] if bar else snapshot['position']
        if operation.startswith('write_'):
            if not same({'exists':True,'value':current}, request['expected']):
                raise ValueError()
            if bar:
                guid = request['guid']
                _sessions(snapshot, guid, current)
                # Refresh both parent and session provenance immediately before dispatch.
                fresh = await _inventory(iterm2, connection)
                if not same(_profile(fresh, guid)['bar'], current):
                    raise ValueError()
                _sessions(fresh, guid, current)
                # iTerm2 3.7.7 applies batched assignments to the same original profile.
                for key in sorted(BAR_KEYS):
                    value = request['value'][key]
                    if same(current[key], value):
                        continue
                    # The inventory reads profiles before checking sessions.
                    parent, = await iterm2.Profile.async_get(connection, guids=[guid])
                    properties = parent.all_properties
                    if properties['Guid'] != guid or not same(_bar(properties), current):
                        raise ValueError()
                    sent = True
                    await iterm2.rpc.async_set_profile_properties_json(connection, None,
                        [(key, json.dumps(value, allow_nan=False))], guids=[guid])
                    fresh = await _inventory(iterm2, connection)
                    observed = _profile(fresh, guid)['bar']
                    if not same(observed, dict(current, **{key: value})):
                        raise ValueError()
                    _sessions(fresh, guid, observed)
                    current = observed
            else:
                current = await iterm2.preferences.async_get_preference(connection, iterm2.preferences.PreferenceKey.STATUS_BAR_POSITION)
                if not same({'exists':True,'value':current}, request['expected']):
                    raise ValueError()
                sent = True
                await iterm2.preferences.async_set_preference(connection,
                    iterm2.preferences.PreferenceKey.STATUS_BAR_POSITION, request['value'])
                current = (await _inventory(iterm2, connection))['position']
                if not same(current, request['value']):
                    raise ValueError()
        return {'status':'ok','value':{'exists':True,'value':current}}
    except (Exception, SystemExit, asyncio.CancelledError):
        return {'status':'unknown' if sent else 'conflict'}
    finally:
        if connection is not None:
            try:
                async with asyncio.timeout(.2):
                    await connection.websocket.close()
            except (Exception, SystemExit, asyncio.CancelledError):
                pass


def main():
    result = {'status':'conflict'}
    try:
        raw = sys.stdin.read(1048577)
        if len(raw) > 1048576:
            raise ValueError()
        request = json.loads(raw)
        with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
            result = asyncio.run(_operate(request))
    except (Exception, SystemExit):
        pass
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
