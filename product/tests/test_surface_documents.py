"""The composer that turns one projection into the paperwork a person is shown.

A pure function of a projection, the set of originals the vault still holds and
whether this machine names a reader — so every case below is built from events
and needs no vault, no blob store and no environment.

Every name and value here is invented.
"""

from __future__ import annotations

import pytest

from viva.ledger import (LedgerProjection, Provenance, document_captured,
                         read_recorded)
from viva.persona import moment
from viva.surface.documents import (NEVER_READ, READ, READ_YIELDED_NOTHING,
                                    documents)
from viva.surface.models import PanelState

DOC = "0000000000000000000000000000000000000000000000000000000000000001"
OTHER = "0000000000000000000000000000000000000000000000000000000000000002"


def _captured(doc_id: str, filename: str = "statement.pdf",
              doc_type: str = "unknown"):
    return document_captured(doc_id, filename, 128, doc_type, 0.0, "2026-04-01",
                             Provenance(doc_id=doc_id))


def _read(doc_id: str, parse_ok: bool, phase: str = "extract"):
    return read_recorded(doc_id, "some-model", "some-prompt-v1", "text+image",
                         "{}", 0.0, 0, 0, parse_ok, None if parse_ok else "no",
                         "2026-04-01", Provenance(doc_id=doc_id), phase=phase)


def _read_model(events, raw=(DOC,), reading_configured=False):
    return documents(LedgerProjection(list(events)), frozenset(raw),
                     reading_configured)


def test_a_vault_that_has_captured_nothing_has_no_panel():
    """A panel earns its existence from data. An empty list under a state
    saying the read succeeded invites a screen that renders a heading over
    nothing."""
    read = _read_model([], raw=())

    assert read["state"] == PanelState.ABSENT.value
    assert read["documents"] == []
    assert read["reading_sentence"] == ""
    assert read["raw_document_count"] == 0


def test_a_document_nothing_has_looked_at_says_so_once_on_the_panel():
    read = _read_model([_captured(DOC)])

    assert read["state"] == PanelState.READY.value
    assert read["reading_sentence"] == moment("documents_saved_no_reader")
    assert [row["reading"] for row in read["documents"]] == [NEVER_READ]


def test_the_sentence_is_the_one_this_machine_can_honestly_say():
    """Two true things, and which is true is a fact about the machine rather
    than about the document: nobody has chosen a reader, or one is named and
    nothing has used it."""
    unconfigured = _read_model([_captured(DOC)], reading_configured=False)
    configured = _read_model([_captured(DOC)], reading_configured=True)

    assert unconfigured["reading_sentence"] == moment("documents_saved_no_reader")
    assert configured["reading_sentence"] == moment("documents_saved_unread")
    assert unconfigured["documents"] == configured["documents"]


def test_a_document_that_was_read_and_yielded_nothing_is_not_one_nobody_read():
    """The distinction this read exists to carry. Both documents are unresolved
    and both are still in the vault; what separates them is whether anything
    ever looked."""
    read = _read_model([_captured(DOC), _captured(OTHER), _read(DOC, False)],
                       raw=(DOC, OTHER))

    words = {row["id"]: row["reading"] for row in read["documents"]}
    assert words == {DOC: READ_YIELDED_NOTHING, OTHER: NEVER_READ}


def test_a_read_that_never_got_past_naming_the_document_still_counts_as_a_read():
    """A type with no projector parks after the naming pass, and that pass is
    recorded. Something looked at the document, and the person is told the
    thing that is true rather than the thing that is tidy."""
    read = _read_model([_captured(DOC), _read(DOC, True, phase="classify")])

    assert read["documents"][0]["reading"] == READ_YIELDED_NOTHING
    assert read["reading_sentence"] == moment("documents_read_yielded_nothing")


def test_one_sentence_per_panel_and_the_actionable_one_wins():
    """VOICE-137's budget is one absence per panel. Where a vault holds both
    kinds, the panel says the one a person can do something about."""
    read = _read_model([_captured(DOC), _read(DOC, False), _captured(OTHER)],
                       raw=(DOC, OTHER))

    assert read["reading_sentence"] == moment("documents_saved_no_reader")


def test_a_document_whose_reading_landed_says_nothing_about_reading():
    """Nothing is owed where nothing went wrong, and a panel that always has a
    sentence is a panel whose sentence stops being read.

    The word here comes from the reading declaring itself usable; that the
    document also posted is a second fact, carried in its own field."""
    from viva.ledger import closing_balance_observed

    events = [_captured(DOC, doc_type="checking_statement"), _read(DOC, True),
              closing_balance_observed("acct:one", "100.00", "2026-03-31",
                                       Provenance(doc_id=DOC))]
    read = _read_model(events)

    assert read["documents"][0]["reading"] == READ
    assert read["documents"][0]["resolved"] is True
    assert read["reading_sentence"] == ""


def test_a_settled_document_with_no_reading_behind_it_says_nothing_read_it():
    """The word is about reading, and resolution is not reading.

    A document can reach a terminal state with no reading recorded against it —
    events appended directly, or a person's own ruling settling it. Deciding
    the word from resolution would tell that person a model read their file
    when the vault holds no record that anything did."""
    from viva.ledger import closing_balance_observed

    events = [_captured(DOC, doc_type="checking_statement"),
              closing_balance_observed("acct:one", "100.00", "2026-03-31",
                                       Provenance(doc_id=DOC))]
    read = _read_model(events)
    row = read["documents"][0]

    assert row["resolved"] is True
    assert row["reading"] == NEVER_READ
    assert read["reading_sentence"] == moment("documents_saved_no_reader")


def test_a_document_read_cleanly_with_nowhere_to_be_put_still_says_it_was_read():
    """The other direction. A reading that declared itself usable was a
    reading, whatever the ledger then did with it — a type with no projector
    parks a perfectly good read, and telling the person nothing could be made
    of their document would be false about the one thing this word describes."""
    read = _read_model([_captured(DOC), _read(DOC, True)])
    row = read["documents"][0]

    assert row["resolved"] is False
    assert row["reading"] == READ


def test_the_word_moves_with_the_reading_and_not_with_what_followed_it():
    """Stated as the property rather than as two cases: holding the reading
    fixed and moving everything downstream leaves the word alone."""
    from viva.ledger import closing_balance_observed

    reading = [_captured(DOC), _read(DOC, True)]
    settled = reading + [closing_balance_observed(
        "acct:one", "100.00", "2026-03-31", Provenance(doc_id=DOC))]

    assert (_read_model(reading)["documents"][0]["reading"]
            == _read_model(settled)["documents"][0]["reading"] == READ)


def test_a_row_is_labelled_by_the_name_the_file_arrived_under():
    """A person who has just added a file looks for the name they gave it. The
    address the bytes decide is still there and is no longer the only thing to
    recognise a row by."""
    read = _read_model([_captured(DOC, filename="quarterly-summary.pdf")])
    row = read["documents"][0]

    assert row["filename"] == "quarterly-summary.pdf"
    assert row["id"] == DOC


def test_a_document_captured_without_a_name_offers_none():
    """What a document was called is recorded, never invented: a capture with
    no name gets an empty one, and what to show instead is the screen's
    problem rather than a name composed here."""
    read = _read_model([_captured(DOC, filename="")])

    assert read["documents"][0]["filename"] == ""


def test_whether_the_original_is_still_there_is_the_stores_answer_and_not_the_logs():
    """The projection knows a document was captured; only the blob store knows
    whether its bytes are still openable, so that fact is handed in."""
    read = _read_model([_captured(DOC), _captured(OTHER)], raw=(OTHER,))

    available = {row["id"]: row["raw_available"] for row in read["documents"]}
    assert available == {DOC: False, OTHER: True}
    assert read["raw_document_count"] == 1


def test_the_reading_word_is_one_of_a_closed_set():
    """It reaches a person as a claim about what was done with their file, so
    a row can never carry a word nothing reviewed."""
    read = _read_model([_captured(DOC), _captured(OTHER), _read(OTHER, False)],
                       raw=(DOC, OTHER))

    words = [row["reading"] for row in read["documents"]]

    assert len(words) == 2, "a subset check over no rows proves nothing"
    assert set(words) <= {NEVER_READ, READ_YIELDED_NOTHING, READ}


def test_the_composer_opens_nothing_and_asks_the_environment_nothing(monkeypatch):
    """Whether a reader is configured is handed in, not looked up. A composer
    that read the environment would answer differently on two machines holding
    identical vaults."""
    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "some-adapter")
    monkeypatch.setenv("VIVA_MODEL", "some-pinned-model")

    read = _read_model([_captured(DOC)], reading_configured=False)

    assert read["reading_sentence"] == moment("documents_saved_no_reader")


def test_rows_are_ordered_by_the_address_rather_than_by_arrival():
    """One vault, one order, whatever sequence the events were appended in."""
    forwards = _read_model([_captured(DOC), _captured(OTHER)], raw=(DOC, OTHER))
    backwards = _read_model([_captured(OTHER), _captured(DOC)], raw=(DOC, OTHER))

    assert forwards["documents"] == backwards["documents"]
    assert [row["id"] for row in forwards["documents"]] == [DOC, OTHER]


@pytest.mark.parametrize("field", ["id", "filename", "doc_type", "resolved",
                                   "raw_available", "reading"])
def test_every_row_carries_the_whole_contract(field):
    read = _read_model([_captured(DOC)])

    assert field in read["documents"][0]


def test_a_row_says_what_that_document_put_on_the_books(tmp_path):
    """Per row rather than per panel: it is about that document and no other,
    which is the opposite of the reading sentence above it."""
    from viva import render
    from viva.ingest.raw_store import RawStore
    from viva.ledger.events import (account_opened, closing_balance_observed,
                                    document_captured)
    from viva.vault import Vault

    vault = Vault.open(tmp_path / "vault", "pw")
    doc_id = RawStore.fingerprint(b"a statement")
    vault.ledger.append(account_opened("acct:one", "checking", "Everyday",
                                       "USD", "2026-01-01"))
    vault.ledger.append(document_captured(doc_id, "june.pdf", 11, "statement",
                                          0.9, "2026-07-01"))
    vault.ledger.append(closing_balance_observed(
        "acct:one", "1200.00", "2026-06-30",
        provenance=Provenance(doc_id=doc_id)))

    read = documents(vault.ledger.projection(), frozenset({doc_id}), False,
                     "en-US")

    assert read["documents"][0]["contribution"] == moment(
        "documents_contributed",
        amount=render.money("1200.00", "USD", locale="en-US"),
        account=render.label("acct:one"), day=render.date("2026-06-30"))


def test_a_row_that_nothing_rests_on_says_so_rather_than_staying_silent(tmp_path):
    """A silent row reads as a document nobody has looked at, which is a
    different fact and is already said by the reading word beside it."""
    from viva.ingest.raw_store import RawStore
    from viva.ledger.events import document_captured
    from viva.vault import Vault

    vault = Vault.open(tmp_path / "vault", "pw")
    doc_id = RawStore.fingerprint(b"a statement")
    vault.ledger.append(document_captured(doc_id, "june.pdf", 11, "statement",
                                          0.9, "2026-07-01"))

    read = documents(vault.ledger.projection(), frozenset({doc_id}), False)

    assert read["documents"][0]["contribution"] == moment(
        "documents_contributed_nothing")


def test_brokerage_snapshot_and_activity_have_independent_statuses():
    from viva.ledger.events import (brokerage_activity_held,
                                    closing_balance_observed)

    facts = {"doc_id": DOC, "doc_type": "brokerage_statement",
             "account_ref": "Investment account"}
    events = [
        _captured(DOC, doc_type="brokerage_statement"),
        closing_balance_observed("acct:investment", "500.00", "2026-03-31",
                                 Provenance(doc_id=DOC)),
        brokerage_activity_held(
            DOC, facts, {"message": "Activity is incomplete."}, "2026-03-31",
            Provenance(doc_id=DOC)),
    ]

    row = _read_model(events)["documents"][0]

    assert row["snapshot_status"] == "posted"
    assert row["snapshot_sentence"] == moment("documents_snapshot_posted")
    assert row["activity_status"] == "incomplete"
    assert row["activity_sentence"] == moment("documents_activity_incomplete")
