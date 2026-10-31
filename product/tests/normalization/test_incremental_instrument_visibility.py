"""Incremental instrument visibility agrees with complete current-knowledge replay."""
from dataclasses import replace
from decimal import Decimal

import pytest

from viva.ingest import instrument_contracts as c
from viva.ledger.events import Event
from viva.ledger.instruments import decode_change, observation_event
from viva.ledger.projection import LedgerProjection
from test_instrument_projector_b import setup, bank, mortgage
from test_mortgage_context_maintenance import ingest


def _known(tmp_path):
    raw, ledger = setup(tmp_path)
    bank(raw, ledger)
    data = mortgage()
    data['payments'][0]['fees'] = None
    result = ingest(raw, ledger, 'incremental-known-original', data, 'mortgage_statement')
    assert len(ledger.projection().instrument_allocations()) == 1
    reading = next(event for event in reversed(tuple(ledger.events()))
                   if event.event_type == 'ReadRecorded' and event.body['doc_id'] == result.doc_id)
    return raw, ledger, data, reading


def _same_as_replay(ledger):
    current = ledger.projection()
    replay = LedgerProjection(ledger.events())
    assert current.instrument_allocations() == replay.instrument_allocations()
    assert current.instrument_component_states() == replay.instrument_component_states()
    assert current.movements() == replay.movements()
    assert current.core._instrument_effect_keys == replay.core._instrument_effect_keys
    assert current.core._instrument_effect_records == replay.core._instrument_effect_records
    for account in current.accounts():
        assert current.balance(account) == replay.balance(account)


@pytest.mark.parametrize('phase,related,rebuild', [
    ('extract', False, False), ('classify', True, False), ('extract', True, True)])
def test_only_dependency_readings_rebuild_known_allocation(tmp_path, monkeypatch, phase, related, rebuild):
    _, ledger, _, reading = _known(tmp_path)
    constructions = []
    original = LedgerProjection.__init__
    def counted(self, *args, **kwargs):
        constructions.append(1)
        original(self, *args, **kwargs)
    monkeypatch.setattr(LedgerProjection, '__init__', counted)
    body = {**reading.body, 'phase': phase}
    if not related:
        body['doc_id'] = 'unrelated-source'
    ledger.append(Event('ReadRecorded', reading.occurred_at, body, reading.provenance))
    assert bool(constructions) is rebuild
    assert bool(ledger.projection().instrument_allocations()) is not rebuild
    _same_as_replay(ledger)


def test_new_independent_mortgage_observation_can_retire_prior_allocation(tmp_path):
    _, ledger, _, _ = _known(tmp_path)
    source = next(event for event in ledger.events()
                  if event.event_type == 'InstrumentObservationRecorded'
                  and event.body['record']['kind'] == 'mortgage_components')
    change = decode_change(source.body['record'])
    payment = change.payload.payments[0]
    conflicting = replace(payment,
                          principal=c.Money(Decimal('101'), 'USD', payment.principal.source),
                          interest=c.Money(Decimal('199'), 'USD', payment.interest.source))
    independent = replace(change, observation_id='independent-conflicting-payment',
                          payload=replace(change.payload, payments=(conflicting,)))
    assert independent.prior_id is None
    ledger.append(observation_event(independent))
    assert not ledger.projection().instrument_allocations()
    _same_as_replay(ledger)


def test_other_mortgage_source_reading_remains_a_visibility_dependency(tmp_path):
    raw, ledger, data, reading = _known(tmp_path)
    second = ingest(raw, ledger, 'incremental-independent-witness', data, 'mortgage_statement')
    assert len(ledger.projection().instrument_allocations()) == 1
    sibling = next(event for event in reversed(tuple(ledger.events()))
                   if event.event_type == 'ReadRecorded' and event.body['doc_id'] == second.doc_id)
    import json
    conflicting = json.loads(sibling.body['response_text'])
    conflicting['payments'][0]['fees'] = {'raw': '1', 'page': 1}
    ledger.append(Event('ReadRecorded', sibling.occurred_at,
                        {**sibling.body, 'response_text': json.dumps(conflicting)}, sibling.provenance))
    assert not ledger.projection().instrument_allocations()
    _same_as_replay(ledger)
