"""Seed a vault with fabricated sample data so the surface is alive to look at.

Everything here is invented — fake bank names, fake amounts, no real person's
data ever. It exercises the whole surface: a clean posted account, an account
whose statement self-corrected via the running balance, a statement held for
review, and a non-checking document parked. Idempotent (content-addressed
capture dedups), so running it twice is harmless.
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
    return capture_and_ingest(vault.raw, vault.store, data, _reader(rr),
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

    # 2. A second account whose Fee line was misread as -12.33, but its running
    #    balance (1487.58) implies -12.42 and closes the reconciliation — it
    #    self-corrects and posts.
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

    # 4. A non-checking document — parked, acknowledged, not discarded.
    _ingest(vault, b"sample-paystub",
            ReadResult("pay_stub", 0.95, None, "no projector yet"),
            "paystub-jan.pdf", "2026-02-01")
