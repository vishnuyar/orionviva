"""The ingest pipeline: capture, route, reconcile, post — or park, never lose.

The model read is stubbed, so the whole trust path is exercised offline."""

import itertools
from decimal import Decimal

import pytest

from viva.answer import answer_balance
from viva.ingest import (CONFLICT, DUPLICATE, GAP, IDENTITY, PARKED, POSTED,
                         IngestResult, ReadResult, RawStore, StatementFacts,
                         TxnFact, account_id_for, apply_identity_ruling,
                         capture_and_ingest, held_items)
from viva.ledger import (EventStore, Ledger, LedgerProjection,
                         UnknownAccountError)
from viva.ledger.networth import net_worth

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
                 ref="Northwind Total Checking 000000000005678")
    mar = _facts("2000.00", [("2026-03-05", "Dep", "50.00")], "2050.00",
                 o_date="2026-03-01", c_date="2026-03-31",
                 ref="Northwind Total Checking 000000000005678")
    _up(raw, store, b"jan", jan)
    _up(raw, store, b"mar", mar)
    items = held_items(store.events())
    assert len(items) == 1
    d = items[0].to_dict()
    assert d["reason"] == "gap"
    assert d["held_balance"] == "1457.58" and d["opening_amount"] == "2000.00"
    assert "····5678" in d["account_label"]     # long number masked
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


# -------------------------------------------------------- any-order / backfill

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


def test_same_number_different_labels_are_one_account(tmp_path):
    # The model labels the two months differently (product name vs holder name)
    # but the account number is the same (full vs masked) — they must resolve to
    # ONE account and stitch, not split into two.
    raw, ledger = _stores(tmp_path)
    jan = _facts("1000.00", [("2026-01-10", "Pay", "500.00")], "1500.00",
                 o_date="2026-01-01", c_date="2026-01-31", ref="Chase Total Checking")
    jan.account_number, jan.institution = "000000000001234", "Northwind"
    jan.account_names = ["Jane Q Public"]
    feb = _facts("1500.00", [("2026-02-10", "Pay", "100.00")], "1600.00",
                 o_date="2026-02-01", c_date="2026-02-28",
                 ref="Jane Q Public Checking")
    feb.account_number, feb.institution = "xxxxxxxxx1234", "Northwind"   # masked, same last-4
    feb.account_names = ["Jane Q Public"]
    _up(raw, ledger, b"jan", jan)
    _up(raw, ledger, b"feb", feb)
    proj = ledger.projection()
    assert len([i for i in proj.account_infos()
                if i.kind == "depository"]) == 1                   # one identity
    assert proj.balance(account_id_for(jan)).amount == Decimal("1600.00")
    assert held_items(proj) == []                                   # stitched, nothing stranded


def test_different_full_numbers_with_matching_last_four_both_post_and_replay(tmp_path):
    raw, ledger = _stores(tmp_path)
    checking = _acct_facts(
        "000000001234", ["Jane Public"], "1000.00", [], "1000.00",
        inst="Northwind", ref="Everyday Checking")
    savings = _acct_facts(
        "999999991234", ["Jane Public"], "2500.00", [], "2500.00",
        inst="Northwind", ref="Everyday Checking")

    first = _up(raw, ledger, b"checking", checking)
    second = _up(raw, ledger, b"savings", savings)

    assert first.action == POSTED and second.action == POSTED
    assert first.account != second.account
    assert len(ledger.projection().account_infos()) == 2
    assert sorted(a.amount for a in (
        ledger.projection().balance(first.account),
        ledger.projection().balance(second.account))) == [
            Decimal("1000.00"), Decimal("2500.00")]

    replayed = ledger.fresh_projection()
    assert len(replayed.account_infos()) == 2
    assert sorted(replayed.balance(a).amount for a in replayed.accounts()) == [
        Decimal("1000.00"), Decimal("2500.00")]

    reopened = Ledger.open(tmp_path / "events.jsonl", PW).projection()
    assert len(reopened.account_infos()) == 2
    point = net_worth(reopened, "2026-01-31")
    assert len(point.lines) == 2
    assert point.by_currency()["USD"]["net"] == Decimal("3500.00")


def test_full_number_collision_ids_are_opaque_in_either_ingest_order(tmp_path):
    def ingest(path, order):
        raw, ledger = _stores(path)
        facts = {
            "checking": _acct_facts(
                "000000001234", ["Jane Public"], "1000.00", [], "1000.00",
                inst="Northwind", ref="Everyday Checking"),
            "savings": _acct_facts(
                "999999991234", ["Jane Public"], "2500.00", [], "2500.00",
                inst="Northwind", ref="High-Yield Savings"),
        }
        for label in order:
            assert _up(raw, ledger, label.encode(), facts[label]).action == POSTED
        return {info.number: info.account for info in ledger.projection().account_infos()}

    forward = ingest(tmp_path / "forward", ("checking", "savings"))
    reverse = ingest(tmp_path / "reverse", ("savings", "checking"))

    assert set(forward) == set(reverse)
    assert len(set(forward.values())) == len(set(reverse.values())) == 2
    assert all(number not in account for number, account in forward.items())
    assert all(number not in account for number, account in reverse.items())


def test_masked_followup_asks_when_two_accounts_share_every_visible_signal(tmp_path):
    raw, ledger = _stores(tmp_path)
    for blob, number, balance in (
            (b"one", "000000001234", "1000.00"),
            (b"two", "999999991234", "2500.00")):
        facts = _acct_facts(
            number, ["Jane Public"], balance, [], balance,
            inst="Northwind", ref="Everyday Account")
        assert _up(raw, ledger, blob, facts).action == POSTED

    masked = _acct_facts(
        "••••1234", ["Jane Public"], "2500.00", [], "2500.00",
        o="2026-02-01", c="2026-02-28", inst="Northwind",
        ref="Everyday Account")
    result = _up(raw, ledger, b"masked", masked)

    assert result.action == IDENTITY
    assert result.account is None
    (held,) = held_items(ledger.projection())
    assert held.reason == "identity" and held.held_balance is None
    assert len(ledger.projection().account_infos()) == 2

    resolved = apply_identity_ruling(ledger, result.doc_id, "new")
    assert resolved.action == POSTED
    assert resolved.account not in {info.account for info in
                                    ledger.fresh_projection().account_infos()
                                    if info.number != "••••1234"}
    assert held_items(ledger.projection()) == []
    assert len(ledger.fresh_projection().account_infos()) == 3


def test_masked_multi_candidate_can_be_assigned_to_a_specific_account(tmp_path):
    raw, ledger = _stores(tmp_path)
    first = _acct_facts(
        "000000001234", ["Jane Public"], "1000.00", [], "1000.00",
        inst="Northwind", ref="Everyday Account")
    second = _acct_facts(
        "999999991234", ["Jane Public"], "2500.00", [], "2500.00",
        inst="Northwind", ref="Everyday Account")
    _up(raw, ledger, b"one", first)
    second_result = _up(raw, ledger, b"two", second)
    masked = _acct_facts(
        "••••1234", ["Jane Public"], "2500.00", [], "2500.00",
        o="2026-02-01", c="2026-02-28", inst="Northwind",
        ref="Everyday Account")
    held = _up(raw, ledger, b"masked-choice", masked)

    resolved = apply_identity_ruling(
        ledger, held.doc_id, second_result.account)

    assert resolved.action == POSTED
    assert resolved.account == second_result.account
    assert held_items(ledger.projection()) == []

    # The exact document is settled, but the shared last-four signal is not
    # globally taught to choose this account for every future statement.
    later = _acct_facts(
        "••••1234", ["Jane Public"], "2500.00", [], "2500.00",
        o="2026-03-01", c="2026-03-31", inst="Northwind",
        ref="Everyday Account")
    assert _up(raw, ledger, b"masked-choice-later", later).action == IDENTITY


def test_masked_value_with_more_than_four_digits_is_not_treated_as_full(tmp_path):
    raw, ledger = _stores(tmp_path)
    masked = _acct_facts(
        "XXXXXX123456", ["Jane Public"], "1000.00", [], "1000.00",
        inst="Northwind", ref="Checking")
    full = _acct_facts(
        "000000123456", ["Jane Public"], "1000.00", [], "1000.00",
        o="2026-02-01", c="2026-02-28", inst="Northwind", ref="Checking")

    assert _up(raw, ledger, b"long-mask", masked).action == POSTED
    assert _up(raw, ledger, b"real-full", full).action == POSTED

    projection = Ledger.open(tmp_path / "events.jsonl", PW).projection()
    assert len(projection.account_infos()) == 1
    assert projection.account_infos()[0].number == "000000123456"


def test_full_number_does_not_upgrade_an_incompatible_masked_account(tmp_path):
    raw, ledger = _stores(tmp_path)
    masked = _acct_facts(
        "••••1234", ["Holder One"], "1000.00", [], "1000.00",
        inst="Northwind", ref="Checking")
    different = _acct_facts(
        "999999991234", ["Holder Two"], "2500.00", [], "2500.00",
        o="2026-02-01", c="2026-02-28", inst="Northwind", ref="Savings")

    assert _up(raw, ledger, b"masked-existing", masked).action == POSTED
    result = _up(raw, ledger, b"different-full", different)

    assert result.action == IDENTITY
    assert ledger.projection().account_infos()[0].number == "••••1234"


def test_conflict_on_second_colliding_account_reports_its_own_balance(tmp_path):
    raw, ledger = _stores(tmp_path)
    first = _acct_facts(
        "000000001234", ["Jane Public"], "1000.00", [], "1000.00",
        inst="Northwind", ref="Checking")
    second = _acct_facts(
        "999999991234", ["Jane Public"], "2500.00", [], "2500.00",
        inst="Northwind", ref="Savings")
    _up(raw, ledger, b"first", first)
    second_result = _up(raw, ledger, b"second", second)
    bad = _acct_facts(
        "999999991234", ["Jane Public"], "2500.00",
        [("2026-02-10", "Deposit", "100.00")], "9999.00",
        o="2026-02-01", c="2026-02-28", inst="Northwind", ref="Savings")

    result = _up(raw, ledger, b"bad-second", bad)

    assert result.action == CONFLICT
    assert result.account == second_result.account
    (held,) = held_items(ledger.projection())
    assert held.held_balance == "2500.00"


def test_unposted_colliding_account_does_not_report_the_existing_account(tmp_path):
    raw, ledger = _stores(tmp_path)
    first = _acct_facts(
        "000000001234", ["Jane Public"], "1000.00", [], "1000.00",
        inst="Northwind", ref="Checking")
    bad_second = _acct_facts(
        "999999991234", ["Jane Public"], "2500.00",
        [("2026-02-10", "Deposit", "100.00")], "9999.00",
        o="2026-02-01", c="2026-02-28", inst="Northwind", ref="Savings")
    _up(raw, ledger, b"first", first)

    result = _up(raw, ledger, b"bad-new-collision", bad_second)

    assert result.action == CONFLICT and result.account is None
    (held,) = held_items(ledger.projection())
    assert held.held_balance is None


def test_masked_account_learns_full_number_before_a_later_collision(tmp_path):
    raw, ledger = _stores(tmp_path)
    masked = _acct_facts(
        "••••1234", ["Jane Public"], "1000.00", [], "1000.00",
        inst="Northwind", ref="Checking")
    full = _acct_facts(
        "000000001234", ["Jane Public"], "1000.00", [], "1000.00",
        o="2026-02-01", c="2026-02-28", inst="Northwind", ref="Checking")
    other = _acct_facts(
        "999999991234", ["Jane Public"], "2500.00", [], "2500.00",
        inst="Northwind", ref="Savings")

    assert _up(raw, ledger, b"masked-first", masked).action == POSTED
    assert _up(raw, ledger, b"full-later", full).action == POSTED
    assert _up(raw, ledger, b"other-full", other).action == POSTED

    projection = Ledger.open(tmp_path / "events.jsonl", PW).projection()
    assert len(projection.account_infos()) == 2
    learned = next(info for info in projection.account_infos()
                   if info.name == "Checking")
    assert learned.number == "000000001234"


def _acct_facts(number, names, opening, txns, closing, o="2026-01-01",
                c="2026-01-31", inst="Acme", ref="Acme Checking"):
    f = _facts(opening, txns, closing, o_date=o, c_date=c, ref=ref)
    f.account_number, f.institution, f.account_names = number, inst, names
    return f


def test_ambiguous_identity_is_held_then_learned_as_new(tmp_path):
    raw, ledger = _stores(tmp_path)
    a = _acct_facts("000000001111", ["Jane Public"], "1000.00",
                    [("2026-01-10", "Pay", "500.00")], "1500.00")
    _up(raw, ledger, b"a", a)
    # No number could be read, and the holder matches an account that HAS one.
    # Now a holder's name really is all there is, which is the case worth asking.
    b = _acct_facts("", ["Jane Public"], "200.00",
                    [("2026-02-10", "Dep", "50.00")], "250.00",
                    o="2026-02-01", c="2026-02-28", ref="Acme Savings")
    res = _up(raw, ledger, b"b", b)
    assert res.action == IDENTITY
    assert held_items(ledger.projection())[0].reason == "identity"
    # Rule "new account" -> learned; posts as its own account; never asks again.
    r2 = apply_identity_ruling(ledger, res.doc_id, "new")
    assert r2.action == POSTED and held_items(ledger.projection()) == []
    depo = [i for i in ledger.projection().account_infos() if i.kind == "depository"]
    assert len(depo) == 2                                   # Jane has two accounts


def test_ambiguous_identity_merge_learns_the_alias(tmp_path):
    raw, ledger = _stores(tmp_path)
    a = _acct_facts("000000001111", ["Jane Public"], "1000.00",
                    [("2026-01-10", "Pay", "500.00")], "1500.00")
    _up(raw, ledger, b"a", a)
    # A continuation of the SAME real account but printed with a different number
    # (opening continues from A's balance). Different number -> ambiguous.
    b = _acct_facts("", ["Jane Public"], "1500.00",
                    [("2026-02-10", "Dep", "100.00")], "1600.00",
                    o="2026-02-01", c="2026-02-28", ref="Acme Savings")
    res = _up(raw, ledger, b"b", b)
    assert res.action == IDENTITY
    # Rule "same" -> merges into A, learns the alias, and it stitches.
    r2 = apply_identity_ruling(ledger, res.doc_id, "same")
    assert r2.action == POSTED
    proj = ledger.projection()
    depo = [i for i in proj.account_infos() if i.kind == "depository"]
    assert len(depo) == 1                                   # one account, merged
    assert proj.balance(account_id_for(a)).amount == Decimal("1600.00")


# ------------------------------------------------- registry + card/savings

def _up_typed(raw, ledger, data, facts):
    """Ingest facts whose doc_type may be any registered balance type — the
    ReadResult classification mirrors the facts' own type."""
    return capture_and_ingest(
        raw, ledger, data,
        _reader({data: ReadResult(facts.doc_type, 0.98, facts)}),
        captured_at="2026-04-01")


def test_credit_card_statement_posts_as_a_liability_owed(tmp_path):
    raw, ledger = _stores(tmp_path)
    # prev owed 200; a 500 charge raises it, a 50 payment lowers it -> owe 650.
    card = _facts("200.00", [("2026-01-05", "Flights", "500.00"),
                             ("2026-01-20", "Payment", "-50.00")], "650.00",
                  ref="Amex Platinum 1234", doc_type="credit_card_statement")
    res = _up_typed(raw, ledger, b"card-jan", card)
    assert res.action == POSTED and res.grade == "corroborated"
    proj = ledger.projection()
    acct = account_id_for(card)
    assert proj.account_info(acct).kind == "liability"      # opened as a liability
    assert proj.balance(acct).amount == Decimal("650.00")   # reconciles on one identity
    # The answer path phrases a liability as money owed.
    ans = answer_balance(proj, acct)
    assert ans.answered and "owe" in ans.text.lower()


def test_savings_interest_line_reconciles(tmp_path):
    raw, ledger = _stores(tmp_path)
    # A savings statement whose only movement is an interest credit (increase).
    sav = _facts("1000.00", [("2026-01-31", "Interest", "1.25")], "1001.25",
                 ref="Ally Savings 9876", doc_type="savings_statement")
    res = _up_typed(raw, ledger, b"sav-jan", sav)
    assert res.action == POSTED
    proj = ledger.projection()
    acct = account_id_for(sav)
    assert proj.account_info(acct).kind == "depository"
    assert proj.balance(acct).amount == Decimal("1001.25")


def test_card_and_checking_same_holder_are_two_accounts(tmp_path):
    raw, ledger = _stores(tmp_path)
    chk = _acct_facts("000000001111", ["Jane Public"], "1000.00",
                      [("2026-01-10", "Pay", "500.00")], "1500.00")
    _up_typed(raw, ledger, b"chk", chk)
    # Same holder, different number, DIFFERENT kind -> not ambiguous: two accounts.
    card = _facts("200.00", [("2026-01-05", "Buy", "300.00")], "500.00",
                  ref="Jane's Card", doc_type="credit_card_statement")
    card.account_number, card.institution, card.account_names = \
        "000000002222", "Acme", ["Jane Public"]
    res = _up_typed(raw, ledger, b"card", card)
    assert res.action == POSTED                              # posted, not held for identity
    kinds = sorted(i.kind for i in ledger.projection().account_infos()
                   if i.kind in ("depository", "liability"))
    assert kinds == ["depository", "liability"]


def test_new_balance_type_via_registry_row_only(tmp_path):
    # The load-bearing claim: a brand-new balance-shaped type posts with NO change
    # to the pipeline or gate — just a registry row (data).
    from viva.ingest import DocProfile, LIABILITY, can_project, register
    raw, ledger = _stores(tmp_path)
    store_card = _facts("0.00", [("2026-01-03", "Purchase", "80.00")], "80.00",
                        ref="Store Card 4321", doc_type="store_card_statement")
    # Before registering, the type has no projector -> parked.
    assert not can_project("store_card_statement")
    res = _up_typed(raw, ledger, b"store-unreg", store_card)
    assert res.action == PARKED

    register(DocProfile("store_card_statement", LIABILITY))
    res2 = _up_typed(raw, ledger, b"store-reg", store_card)
    assert res2.action == POSTED
    acct = account_id_for(store_card)
    assert ledger.projection().account_info(acct).kind == "liability"


def test_transactions_sorted_by_date_after_backfill(tmp_path):
    raw, ledger = _stores(tmp_path)
    f = _run_facts()
    _up(raw, ledger, b"mar", f["mar"])          # newest first
    _up(raw, ledger, b"jan", f["jan"])          # backfilled (appended last)
    _up(raw, ledger, b"feb", f["feb"])
    lines = ledger.projection().transactions(account_id_for(f["jan"]))
    dates = [ln.date for ln in lines]
    assert dates == sorted(dates)               # chronological, not append order


def test_cached_projection_matches_a_fresh_replay(tmp_path):
    raw, ledger = _stores(tmp_path)
    f = _run_facts()
    for name in ["feb", "jan", "mar"]:          # deliberately out of order
        _up(raw, ledger, name.encode(), f[name])
    acct = account_id_for(f["jan"])
    cached = ledger.projection().balance(acct).amount
    fresh = LedgerProjection(ledger.events()).balance(acct).amount
    assert cached == fresh == Decimal("1650.00")


def test_two_readable_numbers_are_two_accounts_and_nobody_is_asked(tmp_path):
    """A checking and a savings account at one bank, one holder, two different
    and perfectly readable numbers. This used to be held for review, because a
    holder name outranked the number that is supposed to be the anchor — and it
    is the most ordinary arrangement in personal finance, so the product asked
    about it on almost every real vault."""
    raw, ledger = _stores(tmp_path)
    a = _acct_facts("000000004417", ["Rowan E Vance"], "1000.00",
                    [("2026-01-10", "Pay", "500.00")], "1500.00",
                    ref="Everyday Checking")
    assert _up(raw, ledger, b"a", a).action == POSTED
    b = _acct_facts("000000008802", ["Rowan E Vance"], "200.00",
                    [("2026-02-10", "Dep", "50.00")], "250.00",
                    o="2026-02-01", c="2026-02-28", ref="High-Yield Savings")
    assert _up(raw, ledger, b"b", b).action == POSTED
    depo = [i for i in ledger.projection().account_infos() if i.kind == "depository"]
    assert len(depo) == 2
    assert held_items(ledger.projection()) == []


# A period whose movements net to zero: a payment in and the same amount out.
# The balance chain cannot see a second copy of one, because its opening, its
# closing and the balance already held are all the same number.
NET_ZERO = _facts("1000.00", [("2026-01-10", "Payroll", "500.00"),
                              ("2026-01-15", "Rent", "-500.00")], "1000.00")


def _ingest(raw, store, data, facts, doc_type="checking_statement"):
    import copy
    return capture_and_ingest(
        raw, store, data,
        _reader({data: ReadResult(doc_type, 0.98, copy.deepcopy(facts))}),
        filename="stmt.pdf", captured_at="2026-02-01")


def test_a_redownloaded_statement_does_not_post_its_transactions_twice(tmp_path):
    """A bank does not re-serve a byte-identical PDF, so the capture-time hash
    misses a re-download entirely. The balance chain catches most of them by
    accident; it cannot catch a period that nets to zero, which is an ordinary
    month — a card paid in full, a transfer in and straight out."""
    raw, store = _stores(tmp_path)
    first = _ingest(raw, store, b"monday-download", NET_ZERO)
    second = _ingest(raw, store, b"tuesday-redownload-same-statement", NET_ZERO)

    assert first.action == POSTED
    assert second.action == DUPLICATE
    assert second.doc_id != first.doc_id          # different bytes, different id
    posted = [e for e in store.store.events()
              if e.event_type == "TransactionRecorded"]
    assert len(posted) == 2, "the period's two movements were counted twice"


def test_a_reissued_statement_for_a_posted_period_is_held_not_posted(tmp_path):
    """A corrected re-issue carries the same period and different numbers. It is
    not a duplicate and it is not a second month; which of the two is true is
    not the product's call, so it is held rather than added."""
    raw, store = _stores(tmp_path)
    _ingest(raw, store, b"as-first-issued", NET_ZERO)
    corrected = _facts("1000.00", [("2026-01-10", "Payroll", "500.00"),
                                   ("2026-01-15", "Rent", "-450.00")], "1050.00")
    res = _ingest(raw, store, b"as-reissued-corrected", corrected)

    assert res.action == CONFLICT
    assert "1050.00" in res.message and "1000.00" in res.message
    posted = [e for e in store.store.events()
              if e.event_type == "TransactionRecorded"]
    assert len(posted) == 2, "the re-issue posted alongside the original"
    assert any(h.get("reason") == "reissue" for h in store.projection().open_holds())

    # And what a person is told about it. The generic held-statement sentence
    # says the statement "didn't add up" and asks them to check the figure —
    # false here, and it would send them hunting an error that is not there.
    from viva.questions import _held_questions
    asked = [q for q in _held_questions(store.projection())]
    assert len(asked) == 1
    assert "counting the period twice" in asked[0].text
    assert "didn't add up" not in asked[0].text


def test_a_different_account_may_share_a_period_end(tmp_path):
    """The guard keys on the account as well as the period, so two accounts
    closing on the same day are two statements, not a collision."""
    raw, store = _stores(tmp_path)
    a = _ingest(raw, store, b"account-a", NET_ZERO)
    other = _facts("2000.00", [("2026-01-11", "Payroll", "300.00"),
                               ("2026-01-16", "Rent", "-300.00")], "2000.00",
                   ref="Chase Savings 9876")
    b = _ingest(raw, store, b"account-b", other)

    assert (a.action, b.action) == (POSTED, POSTED)
