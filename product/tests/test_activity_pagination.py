"""Bounded Activity chains retain held revision scope and every identity."""
from types import SimpleNamespace

import pytest

from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger import EventStore, account_opened, simple_transaction, transfer_suggested, category_assigned
from viva.read_store import ReadStore


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME",str(tmp_path / "home"))
    monkeypatch.setenv("MERCHANTCORE_HOME",str(tmp_path / "merchant"))
    monkeypatch.setenv("VIVA_ENV_FILE",str(tmp_path / "synthetic.env"))
    events = EventStore.open(tmp_path / 'events', 'synthetic')
    events.append_atomically(lambda _: (account_opened('invented', 'depository', 'Invented', 'USD', '2026-01-01'),
        *(simple_transaction('invented', '-1', f'Invented row {i:03d}', f'2026-01-{1+i%20:02d}') for i in range(160))))
    store = ReadStore.create(tmp_path / 'read-store', 'synthetic')
    store.synchronize(events)
    vault = SimpleNamespace(read_store=store, read_store_lifecycle='equal', poll_read_store_worker=lambda:None)
    yield OpenedVaultSurfaceProvider(vault, cursor_secret=b'synthetic activity key for tests!'), store, events
    store.close()


def traverse(provider, **scope):
    rows, cursor, counts = [], '', []
    while True:
        result = provider.read_surface('activity', {'page_version':1, 'limit':50, 'cursor':cursor, **scope})
        rows.extend(result['items'])
        counts.append((result['page']['cumulative_count'], result['page']['remaining_count']))
        assert result['beyond']['count'] == counts[-1][0]+counts[-1][1]-len(result['items'])
        assert result['page']['cumulative_count'] == len(rows)
        cursor = result['page']['next_cursor']
        if cursor is None:
            break
    return rows, counts


@pytest.mark.parametrize('historical', [False, True])
def test_all_activity_is_reachable_in_bounded_pages(provider, historical):
    reader, store, events = provider
    with store.open_reader() as held:
        oracle = held.activity_projection().movements()
    oldest = min(oracle, key=lambda m:(m.date,m.key)).key
    events.append(transfer_suggested(oldest, [], {}, '2026-01-21'))
    store.synchronize(events)
    scope = {'as_of':'2026-01-31'} if historical else {}
    rows, counts = traverse(reader, **scope)
    assert len(rows) == 160 and len({row['id'] for row in rows}) == 160
    assert rows[0]['id'] == oldest
    assert {row['id'] for row in rows} == {m.key for m in oracle}
    assert counts == [(50,110),(100,60),(150,10),(160,0)]


@pytest.mark.parametrize('historical', [False, True])
def test_outside_prefix_focus_never_loses_displaced_row(provider, historical):
    reader, store, _ = provider
    with store.open_reader() as held:
        oracle = sorted(held.activity_projection().movements(), key=lambda m:(m.date,m.key), reverse=True)
    focus = oracle[-1].key
    rows, counts = traverse(reader, focus=focus, **({'as_of':'2026-01-31'} if historical else {}))
    assert focus in {row['id'] for row in rows[:50]}
    assert oracle[49].key in {row['id'] for row in rows[50:100]}
    assert len(rows) == len({row['id'] for row in rows}) == len(oracle)
    assert counts[-1] == (160,0)


def test_legacy_prefix_remains_unchanged_and_cap_stays_100(provider):
    reader, _, _ = provider
    result = reader.read_surface('activity', {'limit':100})
    assert len(result['items']) == 100 and result['beyond']['count'] == 60 and 'page' not in result
    for params in ({'page_version':1,'limit':101}, {'cursor':'invented'}, {'page_version':2}, {'page_version':True}):
        with pytest.raises(BridgeRequestError): reader.read_surface('activity',params)


@pytest.mark.parametrize('historical', [False, True])
def test_cursor_carries_focus_when_continuation_omits_it(provider, historical):
    reader, store, _ = provider
    with store.open_reader() as held:
        oracle = sorted(held.activity_projection().movements(), key=lambda m:(m.date,m.key), reverse=True)
    focus = oracle[-1].key
    scope = {'as_of':'2026-01-31'} if historical else {}
    first = reader.read_surface('activity',{'page_version':1,'limit':50,'focus':focus,**scope})
    rows = list(first['items'])
    cursor = first['page']['next_cursor']
    with pytest.raises(BridgeRequestError):
        reader.read_surface('activity',{'page_version':1,'limit':50,'cursor':cursor,'focus':'',**scope})
    while cursor:
        page = reader.read_surface('activity',{'page_version':1,'limit':50,'cursor':cursor,**scope})
        rows.extend(page['items'])
        cursor = page['page']['next_cursor']
    assert len(rows) == len({row['id'] for row in rows}) == len(oracle)
    assert oracle[49].key in {row['id'] for row in rows[50:100]}


def test_cursor_refuses_tamper_scope_provider_and_new_revision(provider):
    reader, store, events = provider
    first = reader.read_surface('activity', {'page_version':1,'limit':50})
    cursor = first['page']['next_cursor']
    for change in ({'cursor':cursor+'a'}, {'limit':49}, {'as_of':'2026-01-31'}, {'focus':'invented'}, {'cursor':'x'*5000}):
        with pytest.raises(BridgeRequestError):
            reader.read_surface('activity', {'page_version':1,'limit':50,'cursor':cursor, **change})
    other = OpenedVaultSurfaceProvider(reader._vault)
    with pytest.raises(BridgeRequestError): other.read_surface('activity',{'page_version':1,'cursor':cursor})
    events.append(simple_transaction('invented','-2','Invented newer row','2026-02-01'))
    store.synchronize(events)
    with pytest.raises(BridgeRequestError): reader.read_surface('activity',{'page_version':1,'cursor':cursor})


def test_pending_group_crosses_page_boundary_without_duplicates(provider):
    reader, store, events = provider
    with store.open_reader() as held:
        keys = [m.key for m in held.activity_projection().movements()]
    events.append_atomically(lambda _:tuple(transfer_suggested(key,[],{},'2026-01-21') for key in keys[:75]))
    store.synchronize(events)
    rows, _ = traverse(reader)
    assert {row['id'] for row in rows[:75]} == set(keys[:75])
    assert {row['id'] for row in rows[75:]} == set(keys[75:])


def test_historical_pages_fold_overlay_value_time_before_selection(provider):
    reader, store, events = provider
    with store.open_reader() as held:
        target = held.activity_projection().movements()[0]
    events.append(category_assigned(target.key,target.description,'food','verified','2026-02-01'))
    store.synchronize(events)
    current,_ = traverse(reader)
    historical,_ = traverse(reader,as_of='2026-01-31')
    current_row = next(row for row in current if row['id']==target.key)
    historical_row = next(row for row in historical if row['id']==target.key)
    assert current_row['category']['id']=='food'
    assert historical_row['category']['id'] is None


def test_cursor_authentication_binds_each_source_scope_component(provider):
    from viva.read_store.activity_page import _decode, _encode
    reader, _, _ = provider
    scope = {'version':1,'ordering':1,'source':{'count':160,'head':'invented-head','epoch':'invented-epoch','generation':'invented-generation'},'as_of':'','limit':50,'focus':''}
    secret = reader._cursor_secret
    token = _encode(scope,50,'',secret)
    assert _decode(token,scope,secret)==(50,'')
    for field in scope:
        changed = {**scope,field:'changed'}
        with pytest.raises(Exception):_decode(token,changed,secret)
    for field in scope['source']:
        changed = {**scope,'source':{**scope['source'],field:'changed'}}
        with pytest.raises(Exception):_decode(token,changed,secret)
