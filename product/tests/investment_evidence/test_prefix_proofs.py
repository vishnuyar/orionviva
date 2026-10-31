"""Historical proofs preserve the canonical witness without repeated encoding."""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

import pytest

from viva.investment import prefix_proofs
from viva.investment.contracts import digest, EvidenceError
from viva.investment.events import prefix
from viva.ledger.events import Event, Provenance


@dataclass(frozen=True)
class FallbackValue:
    amount: Decimal


def events():
    return (
        Event('First', '2021-01-01', {'unicode': 'தமிழ் é 😀',
              'nested': [None, True, False, 3, -2, -0.0, {'text': '\\"\n'}]},
              Provenance(doc_id='source', page=1), event_id='first'),
        Event('Fallback', '2021-01-02', {'value': FallbackValue(Decimal('12.340')),
              'tuple': (Decimal('0'), 'second')}, event_id='second'),
    )


def test_every_historical_proof_matches_legacy_canonical_bytes():
    source = events()
    index = prefix_proofs.PrefixProofIndex(source)
    for count in range(len(source) + 1):
        proof = index.proof(count)
        assert proof == prefix(source[:count])
        assert proof.prefix_digest == digest(tuple(event.to_dict() for event in source[:count]))
    for invalid in (-1, 3, True, '1', None):
        with pytest.raises(ValueError):
            index.proof(invalid)


def test_owned_basis_and_proofs_survive_source_and_returned_body_mutation():
    source = deepcopy(events())
    original = deepcopy(source)
    index = prefix_proofs.PrefixProofIndex(source)
    source[0].body['nested'][6]['text'] = 'caller changed'
    returned = index.events
    returned[0].body['nested'][6]['text'] = 'returned changed'
    assert index.events == original
    assert index.proof(2) == prefix(original)
    assert index.proof(2) != prefix(source)


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), float('-inf'), object()])
def test_noncanonical_values_fail_without_a_partial_proof(invalid):
    with pytest.raises((EvidenceError, ValueError)):
        prefix_proofs.PrefixProofIndex([Event('Bad', '2021-01-01', {'value': invalid})])


def test_each_event_is_canonicalized_once_for_all_historical_lookups(monkeypatch):
    source = events() * 20
    original = prefix_proofs._encode_event
    calls = []
    def counted(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(prefix_proofs, '_encode_event', counted)
    index = prefix_proofs.PrefixProofIndex(source)
    assert len(calls) == len(source)
    for _ in range(3):
        for count in range(len(source) + 1):
            assert index.proof(count) == prefix(source[:count])
    assert len(calls) == len(source)


def test_source_validation_uses_owned_proofs_instead_of_reserializing_prefixes(tmp_path, monkeypatch):
    from test_lifecycle import setup
    from viva.investment import events as observations
    ledger, _ = setup(tmp_path)
    source = tuple(ledger.events())
    calls = []
    legacy_prefix = observations.prefix
    def counted(events):
        calls.append(len(events))
        return legacy_prefix(events)
    monkeypatch.setattr(observations, 'prefix', counted)
    assert observations._validated_statements(source)
    assert calls == []
