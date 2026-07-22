"""The ingest pipeline: capture, route, reconcile, post — or park, never lose.

The model read is stubbed, so the whole trust path is exercised offline."""

from decimal import Decimal

import pytest

from viva.ingest import (CONFLICT, DUPLICATE, GAP, PARKED, POSTED, IngestResult,
                         ReadResult, RawStore, StatementFacts, TxnFact,
                         account_id_for, capture_and_ingest)
from viva.ledger import EventStore, LedgerProjection, UnknownAccountError

PW = "pipeline passphrase"


def _stores(tmp_path):
    return (RawStore.open(tmp_path / "raw", PW),
            EventStore.open(tmp_path / "events.jsonl", PW))


def _facts(opening, txns, closing, o_date="2026-01-01", c_date="2026-01-31",
           ref="Chase Checking 1234", doc_type="checking_statement"):
    return StatementFacts(
        doc_id="", doc_type=doc_type, doc_type_confidence=0.98,
        account_ref=ref, currency="USD",
        opening_amount=Decimal(opening), opening_date=o_date,
        closing_amount=Decimal(closing), closing_date=c_date,
        transactions=[TxnFact(date=d, description=desc, amount=Decimal(a))
                      for d, desc, a in txns],
        opening_page=1, closing_page=6)


def _reader(mapping):
    """mapping: bytes -> ReadResult. Stamps the real doc_id onto the facts."""
    def rf(data, doc_id):
        rr = mapping[data]
        if rr.facts is not None:
            rr.facts.doc_id = doc_id
        return rr
    return rf


# Jan: open 1000, +500 pay, -42.42 coffee => close 1457.58
JAN = _facts("1000.00", [("2026-01-10", "Payroll", "500.00"),
                         ("2026-01-15", "Coffee", "-42.42")], "1457.58")


def test_checking_statement_posts_and_reconciles(tmp_path):
    raw, store = _stores(tmp_path)
    data = b"jan-statement-pdf"
    res = capture_and_ingest(raw, store, data,
                             _reader({data: ReadResult("checking_statement", 0.98, JAN)}),
                             filename="jan.pdf", captured_at="2026-02-01")
    assert res.action == POSTED and res.grade == "corroborated"
    # The balance is answerable, corroborated, from the ledger.
    ans = LedgerProjection(store.events()).balance(account_id_for(JAN))
    assert ans.amount == Decimal("1457.58") and ans.grade == "corroborated"
    # Raw bytes were captured regardless.
    assert raw.has(RawStore.fingerprint(data))


def test_reupload_is_duplicate_no_double_post(tmp_path):
    raw, store = _stores(tmp_path)
    data = b"jan-statement-pdf"
    reader = _reader({data: ReadResult("checking_statement", 0.98, JAN)})
    capture_and_ingest(raw, store, data, reader, captured_at="2026-02-01")
    res2 = capture_and_ingest(raw, store, data, reader, captured_at="2026-02-02")
    assert res2.action == DUPLICATE
    # Balance unchanged; only one statement's worth of events.
    ans = LedgerProjection(store.events()).balance(account_id_for(JAN))
    assert ans.amount == Decimal("1457.58")


def test_non_checking_is_parked_not_discarded(tmp_path):
    raw, store = _stores(tmp_path)
    data = b"a-pay-stub-pdf"
    res = capture_and_ingest(raw, store, data,
                             _reader({data: ReadResult("pay_stub", 0.9, None,
                                                       "no projector")}),
                             filename="paystub.pdf", captured_at="2026-02-01")
    assert res.action == PARKED and res.doc_type == "pay_stub"
    # Held raw, and recorded as captured, but nothing posted to answer from.
    assert raw.has(RawStore.fingerprint(data))
    assert LedgerProjection(store.events()).accounts() == []


def test_unreconciled_statement_is_conflict_not_posted(tmp_path):
    raw, store = _stores(tmp_path)
    # 1000 + 500 = 1500, but the statement claims a closing of 1600 — it does
    # not reconcile, so nothing should be posted.
    bad = _facts("1000.00", [("2026-01-10", "Payroll", "500.00")], "1600.00")
    data = b"broken-statement-pdf"
    res = capture_and_ingest(raw, store, data,
                             _reader({data: ReadResult("checking_statement", 0.9, bad)}),
                             captured_at="2026-02-01")
    assert res.action == CONFLICT and res.grade == "conflicted"
    assert LedgerProjection(store.events()).accounts() == []   # nothing posted


def test_second_month_stitches(tmp_path):
    raw, store = _stores(tmp_path)
    r1 = _reader({b"jan": ReadResult("checking_statement", 0.98, JAN)})
    capture_and_ingest(raw, store, b"jan", r1, captured_at="2026-02-01")
    feb = _facts("1457.58", [("2026-02-05", "Refund", "100.00")], "1557.58",
                 o_date="2026-02-01", c_date="2026-02-28")
    r2 = _reader({b"feb": ReadResult("checking_statement", 0.98, feb)})
    res = capture_and_ingest(raw, store, b"feb", r2, captured_at="2026-03-01")
    assert res.action == POSTED
    ans = LedgerProjection(store.events()).balance(account_id_for(JAN))
    assert ans.amount == Decimal("1557.58") and ans.grade == "corroborated"


def test_gap_between_months_is_surfaced_not_invented(tmp_path):
    raw, store = _stores(tmp_path)
    r1 = _reader({b"jan": ReadResult("checking_statement", 0.98, JAN)})
    capture_and_ingest(raw, store, b"jan", r1, captured_at="2026-02-01")
    # March opens at 2000, but we only hold up to Jan's 1457.58 — a missing Feb.
    mar = _facts("2000.00", [("2026-03-05", "x", "10.00")], "2010.00",
                 o_date="2026-03-01", c_date="2026-03-31")
    r2 = _reader({b"mar": ReadResult("checking_statement", 0.98, mar)})
    res = capture_and_ingest(raw, store, b"mar", r2, captured_at="2026-04-01")
    assert res.action == GAP
    # Ledger still holds only the trustworthy Jan balance.
    ans = LedgerProjection(store.events()).balance(account_id_for(JAN))
    assert ans.amount == Decimal("1457.58")


def test_unreadable_document_is_parked(tmp_path):
    raw, store = _stores(tmp_path)
    data = b"garbled"
    res = capture_and_ingest(raw, store, data,
                             _reader({data: ReadResult("unknown", 0.0, None,
                                                       "no JSON found")}),
                             captured_at="2026-02-01")
    assert res.action == PARKED
    assert raw.has(RawStore.fingerprint(data))
