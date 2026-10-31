"""Historical work reuse stays exact, bounded and owned by one ledger."""
from dataclasses import dataclass
from decimal import Decimal

import pytest

from viva.ingest import instrument_contracts as c
from viva.investment import payroll
from viva.ledger import EventStore, Ledger
from viva.ledger.events import account_opened
from viva.ledger.postings import simple_transaction
from viva.ledger.work_cache import ValidationMemo, active_memo, memo_scope


def _source(tmp_path):
    ledger = Ledger(EventStore.open(tmp_path / 'memo-events', 'public-test-passphrase'))
    ledger.append(account_opened('public', 'depository', 'Public', 'USD', '2026-01-01'))
    ledger.append(simple_transaction('public', '100', 'public deposit', '2026-01-02'))
    return ledger, tuple(ledger.events()), ledger.projection().movements()[0].key


def test_historical_net_proof_reuses_exact_prefix_and_detaches_returns(tmp_path, monkeypatch):
    ledger, events, key = _source(tmp_path)
    constructions = []
    original = payroll.LedgerProjection
    def counted(*args, **kwargs):
        constructions.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(payroll, 'LedgerProjection', counted)
    with memo_scope(ledger._validation_memo):
        event, line = payroll._net_event(events, key, 'USD')
        line.amount = Decimal('999')
        other_event, other_line = payroll._net_event(events, key, 'USD')
        assert other_event is event
        assert other_line.amount == Decimal('100')
        assert constructions == [1]
        # An unchanged event ID with a changed body is a different witness.
        events[0].body['name'] = 'Different public account name'
        payroll._net_event(events, key, 'USD')
        assert len(constructions) == 2
    assert active_memo() is None
    with memo_scope(ledger._validation_memo):
        payroll._net_event(events, key, 'USD')
        assert len(constructions) == 2
    ledger._validation_memo.clear()
    with memo_scope(ledger._validation_memo):
        payroll._net_event(events, key, 'USD')
        assert len(constructions) == 3


def test_historical_proofs_do_not_cross_ledger_owners(tmp_path, monkeypatch):
    ledger, events, key = _source(tmp_path)
    other = ledger.fork()
    original = payroll.LedgerProjection
    constructions = []
    def counted(*args, **kwargs):
        constructions.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(payroll, 'LedgerProjection', counted)
    with memo_scope(ledger._validation_memo):
        payroll._net_event(events, key, 'USD')
    with memo_scope(other._validation_memo):
        payroll._net_event(events, key, 'USD')
    assert len(constructions) == 2


def test_canonical_operation_scope_resets_after_settlement_failure(tmp_path):
    ledger, _, _ = _source(tmp_path)
    assert active_memo() is None
    def operation(staged):
        assert active_memo() is ledger._validation_memo
        raise ValueError('public failed settlement')
    with pytest.raises(ValueError, match='public failed settlement'):
        ledger.stage_atomically(operation)
    assert active_memo() is None


def test_memo_capacity_evicts_and_clear_discards_derived_proofs():
    memo = ValidationMemo(capacity=2)
    memo.put('proof', 'first', ('public-first',))
    memo.put('proof', 'second', ('public-second',))
    memo.put('proof', 'third', ('public-third',))
    assert memo.get('proof', 'first') is None
    assert memo.get('proof', 'second') == ('public-second',)
    assert memo.get('proof', 'third') == ('public-third',)
    memo.clear()
    assert memo.get('proof', 'second') is None
    assert memo.get('proof', 'third') is None


def test_closed_fact_type_metadata_is_static_but_every_value_is_checked(monkeypatch):
    @dataclass(frozen=True)
    class PublicFact(c.ClosedFact):
        label: str
    original = c.get_type_hints
    reflected = []
    def counted(target):
        reflected.append(target)
        return original(target)
    monkeypatch.setattr(c, 'get_type_hints', counted)
    assert PublicFact('first').label == 'first'
    assert PublicFact('second').label == 'second'
    with pytest.raises(c.ContractError, match='wrong closed type'):
        PublicFact(1)
    assert reflected == [PublicFact]
