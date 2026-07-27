"""The merchant drill-through keeps direction (found 2026-07-27, on the real vault).

The finding: every EFT to the author's broker showed positive and the header total summed
magnitudes in BOTH directions, so a counterparty the author both sent money to
and received money from displayed a gross figure dressed as one number. Cause:
abs() on every amount in `merchant_transactions` — the same defect family as the
liability abs() in the first net-worth cut (net-worth.md, D1: abs() erases the
one bit that matters).

These tests pin the contract: amounts stay signed, each row carries a kind-aware
direction, and the summary is three figures — out, in, net — never one.
"""

from decimal import Decimal

from viva.ingest import RawStore, ReadResult, StatementFacts, TxnFact, capture_and_ingest
from viva.ledger import EventStore, Ledger
from viva.vault import Vault
from viva.web import service


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.98, f)


def _vault(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    return Vault(ledger=ledger, raw=raw, directory=tmp_path)


def _checking(vault, txns, opening="10000.00"):
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Total Checking", currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-03-01",
        closing_amount=Decimal(opening) + total, closing_date="2026-03-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000001122", institution="Chase")
    return capture_and_ingest(vault.raw, vault.ledger, b"chk",
                              lambda data, did: _stamp(facts, did),
                              captured_at="2026-04-01")


def _card(vault, txns, opening="0"):
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.98,
        account_ref="Chase Freedom Rise", currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-03-01",
        closing_amount=Decimal(opening) + total, closing_date="2026-03-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000007799", institution="Chase")
    return capture_and_ingest(vault.raw, vault.ledger, b"card",
                              lambda data, did: _stamp(facts, did),
                              captured_at="2026-04-01")


def test_two_way_counterparty_keeps_signs_and_reports_out_in_net(tmp_path):
    """The real-vault shape: EFTs out to the broker AND money received back.
    One direction must never be dressed as the other, and the summary must be
    three figures, not their gross sum."""
    vault = _vault(tmp_path)
    _checking(vault, [
        ("2026-03-05", "EFT Broker Moneyline", "-1500.00"),   # sent to them
        ("2026-03-12", "EFT Broker Moneyline", "-2000.00"),   # sent to them
        ("2026-03-20", "EFT Broker Moneyline", "500.00"),     # received back
    ])
    d = service.merchant_transactions(vault, "EFT Broker Moneyline")
    assert d["count"] == 3
    # Signed as the account recorded them — abs() was the bug.
    amounts = {i["amount"]: i["direction"] for i in d["items"]}
    assert amounts == {"-1500.00": "out", "-2000.00": "out", "500.00": "in"}
    # Three figures. The old single "total" would have said 4000.00.
    assert d["money_out"] == "3500.00"
    assert d["money_in"] == "500.00"
    assert d["net"] == "3000.00"
    assert "total" not in d, "the one-figure gross total must not come back"


def test_card_charge_is_out_despite_its_positive_sign(tmp_path):
    """Kind-aware, the Slice 5 distinction: a liability records a charge —
    money out to the merchant — POSITIVE. Reading the raw sign alone would
    call every card purchase incoming money."""
    vault = _vault(tmp_path)
    _card(vault, [("2026-03-07", "GYM MONTHLY", "500.00")])
    d = service.merchant_transactions(vault, "GYM MONTHLY")
    assert d["count"] == 1
    assert d["items"][0]["direction"] == "out"
    assert d["items"][0]["amount"] == "500.00"      # still signed as recorded
    assert d["money_out"] == "500.00" and d["money_in"] == "0"


def test_one_way_merchant_reads_as_before(tmp_path):
    """For the common case — a merchant money only flows toward — the view
    stays simple: everything out, nothing in, net equals out."""
    vault = _vault(tmp_path)
    _checking(vault, [
        ("2026-03-03", "COSTCO WHSE #1234", "-120.00"),
        ("2026-03-17", "COSTCO WHSE #1234", "-80.00"),
    ])
    d = service.merchant_transactions(vault, "COSTCO WHSE #1234")
    assert d["count"] == 2
    assert all(i["direction"] == "out" for i in d["items"])
    assert d["money_out"] == "200.00"
    assert d["money_in"] == "0"
    assert d["net"] == "200.00"
