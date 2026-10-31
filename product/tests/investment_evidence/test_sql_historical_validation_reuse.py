"""One authenticated publication owns bounded exact historical validation work."""
from copy import deepcopy
from contextlib import nullcontext
import sqlite3

import pytest

from test_payroll_counterpart import setup
from viva.investment import authenticated, payroll
from viva.investment.contracts import EvidenceError
from viva.ledger.work_cache import ValidationMemo, active_memo, memo_scope
from viva.ledger.events import Event
from viva.read_store import ReadStore


def source(tmp_path):
    ledger, _, _ = setup(tmp_path)
    snapshot = ledger.store.committed_snapshot()
    return ledger, snapshot


def count_net_folds(monkeypatch):
    calls = []
    original = payroll.LedgerProjection
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(payroll, 'LedgerProjection', counted)
    return calls


def test_authenticated_sql_publication_folds_each_exact_historical_net_prefix_once(tmp_path, monkeypatch):
    _, snapshot = source(tmp_path)
    calls = count_net_folds(monkeypatch)
    with sqlite3.connect(':memory:') as connection:
        authenticated.materialize_authenticated_snapshot(connection, snapshot)
        assert connection.execute('SELECT count(*) FROM retirement_payroll_witnesses').fetchone()[0] == 1
        assert connection.execute('SELECT source_count,source_head FROM investment_evidence_authenticated_source').fetchone() == (
            snapshot.identity.count, snapshot.identity.head_hash)
    assert calls == [1]
    assert active_memo() is None


def test_independent_publications_do_not_share_plaintext_memo(tmp_path, monkeypatch):
    _, snapshot = source(tmp_path)
    seen = []
    original = authenticated.materialize
    def observed(*args, **kwargs):
        memo = active_memo()
        assert memo is not None and memo._capacity == 512
        seen.append(memo)
        return original(*args, **kwargs)
    monkeypatch.setattr(authenticated, 'materialize', observed)
    for _ in range(2):
        with sqlite3.connect(':memory:') as connection:
            authenticated.materialize_authenticated_snapshot(connection, snapshot)
        assert active_memo() is None
    assert seen[0] is not seen[1]
    assert not seen[0]._entries and not seen[1]._entries


@pytest.mark.parametrize('inherited', [False, True])
@pytest.mark.parametrize('failure', [False, True])
def test_publication_scope_preserves_outer_memo_and_cleans_owned_scope(tmp_path, monkeypatch, inherited, failure):
    _, snapshot = source(tmp_path)
    outer = ValidationMemo()
    outer.put('public-sentinel', 'key', ('value',))
    seen = []
    original = authenticated.materialize
    def observed(*args, **kwargs):
        memo = active_memo()
        assert memo is not None
        seen.append(memo)
        original(*args, **kwargs)
        if failure:
            raise EvidenceError('public injected publication failure')
    monkeypatch.setattr(authenticated, 'materialize', observed)
    def publish():
        with sqlite3.connect(':memory:') as connection:
            if failure:
                with pytest.raises(EvidenceError, match='injected publication failure'):
                    authenticated.materialize_authenticated_snapshot(connection, snapshot)
            else:
                authenticated.materialize_authenticated_snapshot(connection, snapshot)
    if inherited:
        with memo_scope(outer):
            publish()
            assert active_memo() is outer and seen == [outer]
            assert outer.get('public-sentinel', 'key') == ('value',)
            assert any(namespace == 'payroll_net_deposit' for namespace, _ in outer._entries)
    else:
        publish()
        assert seen[0] is not outer and not seen[0]._entries
    assert active_memo() is None


def test_exact_historical_proof_and_currency_remain_part_of_memo_identity(tmp_path):
    ledger, snapshot = source(tmp_path)
    events = tuple(Event.from_dict(entry.event.to_dict()) for entry in snapshot.events)
    observed = next(event for event in events if event.event_type == payroll.OBSERVED)
    count = observed.body['prefix']['event_count']
    prefix = deepcopy(events[:count])
    key = observed.body['net_movement_key']
    memo = ValidationMemo()
    with memo_scope(memo):
        expected = payroll._net_event(prefix, key, 'USD')
        with pytest.raises(EvidenceError, match='unavailable or ambiguous'):
            payroll._net_event(prefix, key, 'EUR')
        changed = deepcopy(prefix)
        changed[0].body['name'] = 'different body with same identifier'
        payroll._net_event(changed, key, 'USD')
        assert len(memo._entries) == 2
        reversed_order = (prefix[1], prefix[0], *prefix[2:])
        assert payroll.prefix(reversed_order) != payroll.prefix(prefix)
        try:
            payroll._net_event(reversed_order, key, 'USD')
        except (EvidenceError, ValueError):
            assert len(memo._entries) == 2
        else:
            assert len(memo._entries) == 3
        assert payroll._net_event(prefix, key, 'USD') == expected


def test_sql_rows_and_source_marker_equal_fresh_unmemoized_publication(tmp_path, monkeypatch):
    _, snapshot = source(tmp_path)
    def published():
        with sqlite3.connect(':memory:') as connection:
            authenticated.materialize_authenticated_snapshot(connection, snapshot)
            return tuple(connection.iterdump())
    reused = published()
    monkeypatch.setattr(authenticated, 'publication_memo_scope', nullcontext)
    assert published() == reused
    assert active_memo() is None


def test_financial_error_matches_fresh_publication_and_owned_memo_is_cleared(tmp_path, monkeypatch):
    ledger, _ = source(tmp_path)
    ledger.append(Event(payroll.OBSERVED, '2021-02-01', {}, event_id='public-malformed-payroll-envelope'))
    snapshot = ledger.store.committed_snapshot()
    def failure():
        with sqlite3.connect(':memory:') as connection:
            with pytest.raises(EvidenceError) as error:
                authenticated.materialize_authenticated_snapshot(connection, snapshot)
            return type(error.value), str(error.value)
    reused = failure()
    assert active_memo() is None
    monkeypatch.setattr(authenticated, 'publication_memo_scope', nullcontext)
    assert failure() == reused
    assert active_memo() is None


def test_scratch_authenticated_publication_uses_same_bounded_scope(tmp_path, monkeypatch):
    ledger, _ = source(tmp_path)
    seen = []
    original = authenticated.materialize
    def observed(*args, **kwargs):
        memo = active_memo()
        assert memo is not None and memo._capacity == 512
        seen.append(memo)
        return original(*args, **kwargs)
    monkeypatch.setattr(authenticated, 'materialize', observed)
    with ReadStore.create(tmp_path / 'read-store', 'synthetic-only') as store:
        authenticated.synchronize(store, ledger.store)
        with store.open_reader() as revision:
            identity = store.authenticated_source_identity(revision)
            assert revision.connection.execute('SELECT source_count,source_head FROM investment_evidence_authenticated_source').fetchone() == (
                identity['count'], identity['head'])
    assert len(seen) == 1 and not seen[0]._entries
    assert active_memo() is None
