"""Seed a vault with fabricated sample data so the surface has something to show.

Every institution, amount and date here is invented. The four documents cover the
outcomes the surface renders: a statement that posts clean, one that self-corrects
from its running balance and posts, one held for review, and a document type with
no projector, which parks.

Idempotent — capture is content-addressed, so a second run deduplicates.
"""

from __future__ import annotations

from decimal import Decimal

from ..ingest import ReadResult, StatementFacts, TxnFact, capture_and_ingest
from ..vault import Vault


def _reader(rr: ReadResult):
    def rf(data, doc_id):
        if rr.facts is not None:
            rr.facts.doc_id = doc_id
        return rr
    return rf


def _facts(ref, opening, rows, closing, currency="USD",
           o="2026-01-01", c="2026-01-31"):
    txns = [TxnFact(date=d, description=desc, amount=Decimal(a),
                    running_balance=(Decimal(rb) if rb is not None else None))
            for d, desc, a, rb in rows]
    return StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref=ref, currency=currency,
        opening_amount=Decimal(opening), opening_date=o,
        closing_amount=Decimal(closing), closing_date=c, transactions=txns)


def _ingest(vault, data, rr, filename, captured_at):
    return capture_and_ingest(vault.raw, vault.ledger, data, _reader(rr),
                              filename=filename, captured_at=captured_at)


def seed_sample(vault: Vault) -> None:
    # 1. A clean checking statement — posts, corroborated.
    clean = _facts(
        "Northwind Checking 4021", "3200.00",
        [("2026-01-05", "Payroll — Northwind", "2450.00", "5650.00"),
         ("2026-01-09", "Cedar Market", "-84.30", "5565.70"),
         ("2026-01-18", "City Power", "-140.00", "5425.70")],
        "5425.70")
    _ingest(vault, b"sample-northwind-jan",
            ReadResult("checking_statement", 0.98, clean),
            "northwind-jan.pdf", "2026-02-01")

    # 2. A second account whose Fee line reads -12.33 while its running balance
    #    (1487.58) implies -12.42. The running balance closes the
    #    reconciliation, so it self-corrects and posts.
    fixable = _facts(
        "Cedar Savings 7788", "1000.00",
        [("2026-01-07", "Transfer in", "500.00", "1500.00"),
         ("2026-01-15", "Fee", "-12.33", "1487.58")],
        "1487.58")
    _ingest(vault, b"sample-cedar-jan",
            ReadResult("checking_statement", 0.97, fixable),
            "cedar-jan.pdf", "2026-02-01")

    # 3. A statement that does not reconcile and cannot be forced (no running
    #    balances; the gap equals a line) — held for the person's review.
    held = _facts(
        "Northwind Checking 4021", "5425.70",
        [("2026-02-04", "Refund", "60.00", None),
         ("2026-02-11", "Grocer", "-55.00", None)],
        "5485.70", o="2026-02-01", c="2026-02-28")
    _ingest(vault, b"sample-northwind-feb",
            ReadResult("checking_statement", 0.9, held),
            "northwind-feb.pdf", "2026-03-01")

    # 4. A document type with no projector — parked, not discarded.
    _ingest(vault, b"sample-paystub",
            ReadResult("pay_stub", 0.95, None, "no projector yet"),
            "paystub-jan.pdf", "2026-02-01")
