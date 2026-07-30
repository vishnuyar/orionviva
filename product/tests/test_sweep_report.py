"""What `sweep()` reports about the transfer questions it left open.

`suggested` is the number of questions open when the sweep finished — a level,
not a change. A link resolves the suggestions on both of its legs, so a
difference between two counts nets two unrelated movements and can go negative
while the sweep is answering questions rather than raising them.
"""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest, sweep)
from viva.ledger import EventStore, Ledger


def _stores(tmp_path):
    return (RawStore.open(tmp_path / "raw", "pw"),
            Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")))


def _facts(opening, txns, closing, ref, doc_type, number="", inst="Acme"):
    return StatementFacts(
        doc_id="", doc_type=doc_type, doc_type_confidence=0.98,
        account_ref=ref, currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-01-01",
        closing_amount=Decimal(closing), closing_date="2026-01-31",
        transactions=[TxnFact(date=d, description=desc, amount=Decimal(a))
                      for d, desc, a in txns],
        account_number=number, institution=inst)


def _up(raw, ledger, data, facts):
    def _read(_d, doc_id):
        facts.doc_id = doc_id
        return ReadResult(facts.doc_type, 0.98, facts)
    return capture_and_ingest(raw, ledger, data, _read, captured_at="2026-02-01")


def _ambiguous_pair(tmp_path):
    """A vault whose only candidate pairing is undecidable, so the ingest leaves
    an open transfer suggestion for a person."""
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-01-05", "PAYMENT", "-750.00")], "4250.00",
                 ref="Everyday Checking 1111", doc_type="checking_statement",
                 number="000000001111")
    card = _facts("750.00", [("2026-01-08", "PAYMENT", "-750.00")], "0.00",
                  ref="Rewards Card 2222", doc_type="credit_card_statement",
                  number="000000002222")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    return ledger


def test_sweep_reports_questions_open_now_not_the_change_in_them(tmp_path):
    ledger = _ambiguous_pair(tmp_path)
    result = sweep(ledger)
    assert result["suggested"] == len(ledger.projection().transfer_suggestions())
    assert result["suggested"] >= 0


def test_sweep_counts_are_never_negative(tmp_path):
    """Every count a sweep returns is a magnitude. A resolved question must
    never be reported as a negative number of open ones."""
    ledger = _ambiguous_pair(tmp_path)
    sweep(ledger)                       # first sweep: idempotent from here on
    result = sweep(ledger)
    assert all(v >= 0 for k, v in result.items() if isinstance(v, int)), result
    assert result["resolved"] == max(0, result["open_before"] - result["suggested"])
