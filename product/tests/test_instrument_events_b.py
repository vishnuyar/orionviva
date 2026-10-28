"""Typed instrument history is sourced, fail-closed and replayable."""
from dataclasses import replace
from decimal import Decimal

import pytest

from viva.ingest.instrument_contracts import (
    Availability, ContractError, Family, Restriction, Source, SourcedDate,
    PositionClassification, SourcedText,
)
from viva.ingest.instrument_observations import ObservationChange, ObservationKind, Operation
from viva.ledger.events import Provenance, account_opened, document_captured, opening_balance_observed
from viva.ledger.instruments import (
    account_restrictions, append_change, decode_change, encode_change, family_event,
    observation_event,
)
from viva.ledger import EventStore, Ledger, LedgerProjection

SOURCE = Source("synthetic-doc", 1)
DATE = SourcedDate("2021-01-01", SOURCE)


def restriction_change(identifier="obs-a", **kwargs):
    args = dict(observation_id=identifier, subject_id="CD-A", kind=ObservationKind.AVAILABILITY,
        effective=DATE, operation=Operation.CREATE, source=SOURCE,
        payload=Availability(Family.DEPOSIT, Restriction.TERM, SOURCE))
    args.update(kwargs)
    return ObservationChange(**args)


def test_typed_storage_roundtrip_and_closed_provenance():
    change = restriction_change()
    assert decode_change(encode_change(change)) == change
    encoded = encode_change(change)
    encoded["payload"]["source"]["page"] = True
    with pytest.raises(ContractError):
        decode_change(encoded)
    encoded = encode_change(change)
    encoded["ignored"] = "not allowed"
    with pytest.raises(ContractError):
        decode_change(encoded)


def test_family_without_restriction_still_excludes_cash_and_survives_replay():
    events = [document_captured("synthetic-doc", "synthetic.pdf", 10, "term_deposit_statement", 1, DATE.value),
        account_opened("CD-A", "depository", "Term deposit", "USD", DATE.value),
        family_event("CD-A", "term_deposit", DATE.value, SOURCE)]
    projection = LedgerProjection(events)
    assert projection.account_restrictions()["CD-A"].status == "missing"
    assert projection.account_restrictions()["CD-A"].family == "term_deposit"
    events.append(observation_event(restriction_change()))
    replay = LedgerProjection(events)
    assert replay.account_restrictions()["CD-A"].status == "accepted"
    assert account_restrictions(replay.core) == replay.account_restrictions()
    assert "ordinary" not in replay.account_restrictions()


def test_later_explicit_family_and_conflicting_declarations_fail_closed():
    events = [account_opened("CD-A", "depository", "Ordinary name", "USD", DATE.value)]
    assert not LedgerProjection(events).account_restrictions()
    events.append(family_event("CD-A", "term_deposit", DATE.value, SOURCE))
    assert LedgerProjection(events).account_restrictions()["CD-A"].status == "missing"
    events.append(family_event("CD-A", "escrow", DATE.value, SOURCE))
    assert LedgerProjection(events).account_restrictions()["CD-A"].status == "conflicted"


def test_locked_append_frontier_rejects_stale_correction_and_uncaptured_source(tmp_path):
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "test-passphrase"))
    with pytest.raises(ValueError, match="retained"):
        append_change(ledger, restriction_change())
    ledger.append(document_captured(SOURCE.doc_id, "synthetic.pdf", 10, "term_deposit_statement", 1, DATE.value))
    append_change(ledger, restriction_change())
    corrected = restriction_change("obs-b", operation=Operation.CORRECT, prior_id="obs-a")
    append_change(ledger.fork(), corrected)
    with pytest.raises(ValueError, match="frontier"):
        append_change(ledger, restriction_change("obs-c", operation=Operation.CORRECT, prior_id="obs-a"))
    assert ledger.projection().account_restrictions()["CD-A"].status == "accepted"


def test_superseded_interpretation_effects_leave_canonical_history_but_not_balance():
    classification = PositionClassification(SourcedText("Unclassified holding", SOURCE))
    original = ObservationChange("A", "ACCOUNT-A", ObservationKind.POSITION_CLASSIFICATION, DATE,
        Operation.CREATE, SOURCE, classification)
    corrected = replace(original, observation_id="B", operation=Operation.CORRECT, prior_id="A")
    first = opening_balance_observed("ACCOUNT-A", Decimal("100"), DATE.value, Provenance(SOURCE.doc_id, 1))
    first.body["instrument_observation_id"] = "A"
    replacement = opening_balance_observed("ACCOUNT-A", Decimal("200"), DATE.value, Provenance(SOURCE.doc_id, 1))
    replacement.body["instrument_observation_id"] = "B"
    events = [account_opened("ACCOUNT-A", "depository", "Account A", "USD", DATE.value),
              observation_event(original), first, observation_event(corrected), replacement]
    assert len(events) == 5
    assert LedgerProjection(events).running_balance("ACCOUNT-A") == Decimal("200")
    assert len(events) == 5
