"""Held statements and human correction-as-event."""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         apply_human_correction, capture_and_ingest, held_items)
from viva.ledger import EventStore, LedgerProjection


def _stores(tmp):
    return (RawStore.open(tmp / "raw", "pw"),
            EventStore.open(tmp / "events.jsonl", "pw"))


def _reader(facts):
    def rf(data, doc_id):
        facts.doc_id = doc_id
        return ReadResult("checking_statement", 0.9, facts)
    return rf


def _held_statement():
    # No running balances, gap equals a line -> suggested, held (not posted).
    return StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.9,
        account_ref="Test Checking 1", currency="USD",
        opening_amount=Decimal("1000.00"), opening_date="2026-01-01",
        closing_amount=Decimal("1500.00"), closing_date="2026-01-31",
        transactions=[TxnFact("2026-01-10", "Pay", Decimal("400.00")),
                      TxnFact("2026-01-20", "Rent", Decimal("-100.00"))])


def test_failed_statement_is_held_and_listed(tmp_path):
    raw, store = _stores(tmp_path)
    facts = _held_statement()
    res = capture_and_ingest(raw, store, b"stmt", _reader(facts),
                             captured_at="2026-02-01")
    assert res.action == "conflict"
    items = held_items(store.events())
    assert len(items) == 1 and items[0].account_ref == "Test Checking 1"


def test_human_correction_posts_at_verified(tmp_path):
    raw, store = _stores(tmp_path)
    facts = _held_statement()
    capture_and_ingest(raw, store, b"stmt", _reader(facts), captured_at="2026-02-01")
    item = held_items(store.events())[0]

    # The person reads the source: Pay was actually 600, not 400.
    # 1000 + 600 - 100 = 1500 -> reconciles.
    res = apply_human_correction(store, item.doc_id, "amount", "600.00", 0)
    assert res.action == "posted" and res.grade == "verified"

    # No longer awaiting review, and the balance is answerable at 1500.
    assert held_items(store.events()) == []
    ans = LedgerProjection(store.events()).balance("acct:test-checking-1")
    assert ans.amount == Decimal("1500.00") and ans.grade == "verified"


def test_correction_that_still_fails_is_re_held(tmp_path):
    raw, store = _stores(tmp_path)
    facts = _held_statement()
    capture_and_ingest(raw, store, b"stmt", _reader(facts), captured_at="2026-02-01")
    item = held_items(store.events())[0]
    # A wrong ruling that still doesn't reconcile -> not posted, held again.
    res = apply_human_correction(store, item.doc_id, "amount", "401.00", 0)
    assert res.action == "conflict"
    assert LedgerProjection(store.events()).accounts() == []
