"""The ingest pipeline: capture, route, reconcile, post — or park, never lose.

The model read is stubbed, so the whole trust path is exercised offline."""

import itertools
from decimal import Decimal

import pytest

from viva.ingest import (CONFLICT, DUPLICATE, GAP, PARKED, POSTED, IngestResult,
                         ReadResult, RawStore, StatementFacts, TxnFact,
                         account_id_for, capture_and_ingest, held_items)
from viva.ledger import (EventStore, Ledger, LedgerProjection,
                         UnknownAccountError)

PW = "pipeline passphrase"


def _stores(tmp_path):
    """Returns (raw, ledger). The ledger wraps the event store with its cached
    projection — the unit ingest now operates on."""
    return (RawStore.open(tmp_path / "raw", PW),
            Ledger(EventStore.open(tmp_path / "events.jsonl", PW)))


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


def test_forced_correction_auto_applies_and_posts(tmp_path):
    raw, store = _stores(tmp_path)
    # Coffee is misread as -42.33, but its running balance (1457.58) is correct,
    # so diagnosis forces -42.42 and the statement posts, reconciled.
    txns = [TxnFact("2026-01-10", "Pay", Decimal("500.00"),
                    running_balance=Decimal("1500.00")),
            TxnFact("2026-01-15", "Coffee", Decimal("-42.33"),
                    running_balance=Decimal("1457.58"))]
    f = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.9,
        account_ref="Chase Checking 1234", currency="USD",
        opening_amount=Decimal("1000.00"), opening_date="2026-01-01",
        closing_amount=Decimal("1457.58"), closing_date="2026-01-31",
        transactions=txns)
    data = b"misread-stmt"
    res = capture_and_ingest(raw, store, data,
                             _reader({data: ReadResult("checking_statement", 0.9, f)}),
                             captured_at="2026-02-01")
    assert res.action == POSTED and res.auto_corrected
    assert res.finding is not None and res.finding.status == "forced"
    ans = LedgerProjection(store.events()).balance(account_id_for(f))
    assert ans.amount == Decimal("1457.58") and ans.grade == "corroborated"


def test_unforced_conflict_carries_a_finding(tmp_path):
    raw, store = _stores(tmp_path)
    # No running balances and the gap equals a line -> suggested, not forced.
    bad = _facts("1000.00", [("2026-01-10", "Pay", "500.00"),
                             ("2026-01-11", "Rent", "-100.00")], "1500.00")
    data = b"suggested-conflict"
    res = capture_and_ingest(raw, store, data,
                             _reader({data: ReadResult("checking_statement", 0.9, bad)}),
                             captured_at="2026-02-01")
    assert res.action == CONFLICT and res.finding is not None
    assert res.finding.status == "suggested"
    assert LedgerProjection(store.events()).accounts() == []


def test_parked_doc_reprocesses_after_a_fix(tmp_path):
    raw, store = _stores(tmp_path)
    data = b"jul-statement"
    # First read fails to parse -> parks.
    r1 = _reader({data: ReadResult("checking_statement", 1.0, None, "parse failed")})
    assert capture_and_ingest(raw, store, data, r1, captured_at="2026-02-01").action == PARKED
    assert LedgerProjection(store.events()).accounts() == []
    # Re-upload the SAME file after the reader/parser improved -> re-reads, posts.
    good = _facts("1000.00", [("2026-01-10", "Pay", "500.00"),
                              ("2026-01-15", "Coffee", "-42.42")], "1457.58")
    r2 = _reader({data: ReadResult("checking_statement", 1.0, good)})
    res = capture_and_ingest(raw, store, data, r2, captured_at="2026-02-02")
    assert res.action == POSTED
    assert LedgerProjection(store.events()).balance(account_id_for(good)).amount == Decimal("1457.58")


def test_posted_doc_is_not_reprocessed(tmp_path):
    raw, store = _stores(tmp_path)
    data = b"jan-statement-pdf"
    reader = _reader({data: ReadResult("checking_statement", 0.98, JAN)})
    capture_and_ingest(raw, store, data, reader, captured_at="2026-02-01")
    assert capture_and_ingest(raw, store, data, reader,
                              captured_at="2026-02-02").action == DUPLICATE


def _events_of_type(store, etype):
    return [e for e in store.events() if e.event_type == etype]


def test_real_read_stores_the_claims_layer(tmp_path):
    raw, store = _stores(tmp_path)
    data = b"real-read"

    def reader(data, doc_id):
        JAN.doc_id = doc_id
        return ReadResult("checking_statement", 0.98, JAN,
                          raw_text='{"doc_type":"checking_statement",...}',
                          model="google/gemini-3.5-flash", prompt_version="stmt-v1",
                          cost_usd=0.051, input_tokens=1200, output_tokens=800)

    capture_and_ingest(raw, store, data, reader, captured_at="2026-02-01")
    reads = _events_of_type(store, "ReadRecorded")
    assert len(reads) == 1
    b = reads[0].body
    assert b["model"] == "google/gemini-3.5-flash" and b["parse_ok"] is True
    assert b["response_text"].startswith('{"doc_type"') and b["cost_usd"] == 0.051


def test_read_that_throws_is_recorded_not_orphaned(tmp_path):
    raw, store = _stores(tmp_path)
    data = b"boom"

    def reader(data, doc_id):
        raise RuntimeError("network exploded")

    res = capture_and_ingest(raw, store, data, reader, captured_at="2026-02-01")
    assert res.action == PARKED
    # Captured, and the failure is auditable — nothing orphaned.
    assert raw.has(RawStore.fingerprint(data))
    assert len(_events_of_type(store, "DocumentCaptured")) == 1
    reads = _events_of_type(store, "ReadRecorded")
    assert len(reads) == 1 and reads[0].body["parse_ok"] is False
    assert "network exploded" in reads[0].body["parse_error"]


def test_stub_read_records_no_claims_layer(tmp_path):
    # A stub with no model set must not pollute the log with a ReadRecorded.
    raw, store = _stores(tmp_path)
    data = b"stub"
    capture_and_ingest(raw, store, data,
                       _reader({data: ReadResult("checking_statement", 0.98, JAN)}),
                       captured_at="2026-02-01")
    assert _events_of_type(store, "ReadRecorded") == []


def _up(raw, store, data, facts):
    return capture_and_ingest(raw, store, data,
                              _reader({data: ReadResult("checking_statement", 0.98, facts)}),
                              captured_at="2026-04-01")


def test_out_of_order_uploads_self_heal(tmp_path):
    raw, store = _stores(tmp_path)
    jan = _facts("1000.00", [("2026-01-10", "Pay", "500.00"),
                             ("2026-01-15", "Coffee", "-42.42")], "1457.58",
                 o_date="2026-01-01", c_date="2026-01-31")
    feb = _facts("1457.58", [("2026-02-05", "Refund", "100.00")], "1557.58",
                 o_date="2026-02-01", c_date="2026-02-28")
    mar = _facts("1557.58", [("2026-03-05", "Dep", "50.00")], "1607.58",
                 o_date="2026-03-01", c_date="2026-03-31")

    assert _up(raw, store, b"jan", jan).action == POSTED
    assert _up(raw, store, b"mar", mar).action == GAP       # can't chain yet
    assert len(held_items(store.events())) == 1
    _up(raw, store, b"feb", feb)                            # posts feb, heals mar
    assert held_items(store.events()) == []                # nothing stranded
    assert LedgerProjection(store.events()).balance(account_id_for(jan)).amount \
        == Decimal("1607.58")


def test_gap_held_item_reports_the_held_balance(tmp_path):
    raw, store = _stores(tmp_path)
    jan = _facts("1000.00", [("2026-01-10", "Pay", "500.00"),
                             ("2026-01-15", "Coffee", "-42.42")], "1457.58",
                 o_date="2026-01-01", c_date="2026-01-31",
                 ref="Chase Total Checking 000000556079591")
    mar = _facts("2000.00", [("2026-03-05", "Dep", "50.00")], "2050.00",
                 o_date="2026-03-01", c_date="2026-03-31",
                 ref="Chase Total Checking 000000556079591")
    _up(raw, store, b"jan", jan)
    _up(raw, store, b"mar", mar)
    items = held_items(store.events())
    assert len(items) == 1
    d = items[0].to_dict()
    assert d["reason"] == "gap"
    assert d["held_balance"] == "1457.58" and d["opening_amount"] == "2000.00"
    assert "····9591" in d["account_label"]     # long number masked
    assert d["period"] == "2026-03-01 – 2026-03-31"


def test_unreadable_document_is_parked(tmp_path):
    raw, store = _stores(tmp_path)
    data = b"garbled"
    res = capture_and_ingest(raw, store, data,
                             _reader({data: ReadResult("unknown", 0.0, None,
                                                       "no JSON found")}),
                             captured_at="2026-02-01")
    assert res.action == PARKED
    assert raw.has(RawStore.fingerprint(data))


# ----------------------------------------------------- Slice 1: any-order / backfill

def _run_facts():
    """A continuous 3-month run: Jan 1000->1500, Feb 1500->1600, Mar 1600->1650."""
    return {
        "jan": _facts("1000.00", [("2026-01-10", "Pay", "500.00")], "1500.00",
                      o_date="2026-01-01", c_date="2026-01-31"),
        "feb": _facts("1500.00", [("2026-02-10", "Pay", "100.00")], "1600.00",
                      o_date="2026-02-01", c_date="2026-02-28"),
        "mar": _facts("1600.00", [("2026-03-10", "Pay", "50.00")], "1650.00",
                      o_date="2026-03-01", c_date="2026-03-31"),
    }


def test_any_upload_order_yields_the_same_chain(tmp_path):
    for i, order in enumerate(itertools.permutations(["jan", "feb", "mar"])):
        raw, ledger = _stores(tmp_path / f"perm{i}")
        f = _run_facts()
        for name in order:
            _up(raw, ledger, name.encode(), f[name])
        proj = ledger.projection()
        acct = account_id_for(f["jan"])
        assert proj.balance(acct).amount == Decimal("1650.00"), order
        assert proj.balance(acct).grade == "corroborated", order
        assert proj.earliest_opening(acct) == Decimal("1000.00"), order
        assert held_items(proj) == [], order


def test_backfill_prepends_older_statements(tmp_path):
    raw, ledger = _stores(tmp_path)
    f = _run_facts()
    _up(raw, ledger, b"mar", f["mar"])          # seeds at Mar's opening
    _up(raw, ledger, b"feb", f["feb"])          # backward prepend
    _up(raw, ledger, b"jan", f["jan"])          # backward prepend again
    proj = ledger.projection()
    acct = account_id_for(f["jan"])
    assert proj.earliest_opening(acct) == Decimal("1000.00")  # OBE re-seated to the oldest
    assert proj.balance(acct).amount == Decimal("1650.00")
    assert held_items(proj) == []


def test_middle_gap_heals_both_sides(tmp_path):
    raw, ledger = _stores(tmp_path)
    f = _run_facts()
    _up(raw, ledger, b"jan", f["jan"])          # posts, seeds
    assert _up(raw, ledger, b"mar", f["mar"]).action == GAP   # connects to neither yet
    assert len(held_items(ledger.projection())) == 1
    _up(raw, ledger, b"feb", f["feb"])          # posts Feb; heal then posts Mar
    assert held_items(ledger.projection()) == []
    assert ledger.projection().balance(account_id_for(f["jan"])).amount == Decimal("1650.00")


def test_cached_projection_matches_a_fresh_replay(tmp_path):
    raw, ledger = _stores(tmp_path)
    f = _run_facts()
    for name in ["feb", "jan", "mar"]:          # deliberately out of order
        _up(raw, ledger, name.encode(), f[name])
    acct = account_id_for(f["jan"])
    cached = ledger.projection().balance(acct).amount
    fresh = LedgerProjection(ledger.events()).balance(acct).amount
    assert cached == fresh == Decimal("1650.00")
