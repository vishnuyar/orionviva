"""Private validation owns its basis; mutable public inputs still need checks."""
from copy import deepcopy
from dataclasses import replace

import pytest

from test_payroll_counterpart import setup
from viva.investment import healing, payroll
from viva.investment.contracts import EvidenceError
from viva.investment.events import _validated_statements, source_index
from viva.investment.funding import resolver
from viva.ledger.events import Event, Provenance
from viva.ledger.postings import simple_transaction
from viva.ledger.work_cache import memo_scope


def prepared(tmp_path):
    ledger, _, _ = setup(tmp_path)
    events = tuple(ledger.events())
    resolve = resolver(events)
    statement = next(s for s in _validated_statements(events, resolve)
                     if any(row.funding_witness for row in s.rows))
    row = next(row for row in statement.rows if row.funding_witness)
    return ledger, events, resolve, statement, row


def test_owned_runner_isolated_from_original_events_and_public_context_returns(tmp_path):
    ledger, events, resolve, statement, row = prepared(tmp_path)
    runner = payroll._OwnedFundingRunner(events, resolve)
    context = payroll.FundingValidationContext(events, _validated_statements(events, resolve))
    assert runner.validate_funding(statement, row, resolve) is None
    returned = context.records(events, '9999-12-31')
    returned[0][0].body['net_deposit_event_id'] = 'changed returned event'
    index = context.source_index(events)
    copied_events = index.events
    copied_events[0].body['name'] = 'changed copied event'
    index.statements.clear()
    index.heads.clear()
    events[0].body['name'] = 'changed original body'
    assert runner.validate_funding(statement, row, resolve) is None
    with pytest.raises(EvidenceError, match='prefix changed'):
        context.records(events, '9999-12-31')
    with pytest.raises(EvidenceError):
        runner.validate_funding(statement, replace(row, amount=replace(row.amount, value='999')), resolve)


def test_owned_binding_returns_detached_proposals_and_no_snapshot_handles(tmp_path):
    _, events, resolve, statement, row = prepared(tmp_path)
    runner = payroll._OwnedFundingRunner(events, resolve)
    fields = {'printed_reference': row.funding_reference,
              'counterpart_reference': row.counterpart_reference,
              'date': row.date, 'amount': row.amount,
              'funding_role': row.funding_role_source}
    parameters = {'destination_account': statement.account.value,
                  'destination_reference': replace(statement.account, value=statement.account.raw),
                  'currency': statement.currency.value}
    first = runner.bind_funding(fields, **parameters)
    assert first['funding_witness'] == row.funding_witness
    expected = deepcopy(first)
    first.clear()
    assert runner.bind_funding(fields, **parameters) == expected
    assert not any(hasattr(runner, public) for public in
                   ('events', 'records', 'source_index', 'destinations'))


def test_project_has_no_mutable_input_context_rechecks_and_lends_no_event_bodies(tmp_path, monkeypatch):
    _, events, resolve, _, _ = prepared(tmp_path)
    index = source_index(events, resolve)
    calls = []
    original = payroll.FundingValidationContext.check
    def counted(context, supplied):
        calls.append(len(supplied))
        return original(context, supplied)
    monkeypatch.setattr(payroll.FundingValidationContext, 'check', counted)
    expected = index.project('activity', '9999-12-31', resolve)
    assert expected
    assert calls == []
    index.events[0].body['name'] = 'modified returned snapshot'
    events[0].body['name'] = 'modified constructor input'
    assert index.project('activity', '9999-12-31', resolve) == expected


def test_healing_reuses_discovery_index_when_no_copy_advances(tmp_path, monkeypatch):
    ledger, _, _, _, _ = prepared(tmp_path)
    transaction = simple_transaction('checking', '1', 'unrelated source', '2021-02-01',
                                    provenance=Provenance(doc_id='unrelated-document', page=1))
    ledger.append(replace(transaction, body={**transaction.body, 'source_reference': 'unrelated-reference'}))
    before = tuple(ledger.events())
    calls = []
    original = healing.source_index
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(healing, 'source_index', counted)
    assert healing.heal_after_source(ledger, 'unrelated-document') == 0
    assert tuple(ledger.events()) == before
    assert calls == [1]


def test_owned_historical_memo_hit_does_not_rehash_mutable_prefix_inputs(tmp_path, monkeypatch):
    ledger, events, _, _, _ = prepared(tmp_path)
    with memo_scope(ledger._validation_memo):
        expected = payroll._records(events)
        calls = []
        original = payroll.prefix
        def counted(supplied):
            calls.append(len(supplied))
            return original(supplied)
        monkeypatch.setattr(payroll, 'prefix', counted)
        assert payroll._records(events) == expected
        assert calls == []
        changed = deepcopy(events)
        changed[0].body['name'] = 'changed historical prefix with identical IDs'
        with pytest.raises(EvidenceError, match='prefix differs'):
            payroll._records(changed)


def test_orphan_row_cannot_lend_mutable_owned_statement_identifier():
    from viva.investment.events import ROW
    event = Event(ROW, '2021-01-01', {'statement_id': {'untrusted': ['initial']}},
                  event_id='orphan-row')
    runner = payroll._OwnedFundingRunner((event,), lambda field: None)
    assert runner.source_row_statement_id('orphan-row') is None
    assert runner.source_row_statement_id('missing') is None
