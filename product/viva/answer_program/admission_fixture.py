"""Canonical synthetic ledger used only by AnswerProgram admission.

Frozen questions, deterministic oracles, and provider evaluation share this
versioned fixture. Each use builds fresh events with no customer identifiers or
values. Runtime financial reads do not branch on fixture labels.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json

from ..ledger import (VERIFIED, LedgerProjection, Provenance,
                      account_opened, closing_balance_observed,
                      document_captured, movement_key,
                      opening_balance_observed, read_recorded,
                      simple_transaction, statement_held, transfer_linked)
from ..ledger.events import merchant_enriched
from ..tools import default_registry


ADMISSION_FIXTURE_VERSION = "answer-admission-fixture-v2"
ADMISSION_TODAY = "2026-03-01"


def _provenance(doc_id: str, page: int = 1) -> Provenance:
    return Provenance(doc_id, page, "synthetic-admission")


def _statement_reply(opening: str, opening_date: str, closing: str,
                     closing_date: str) -> str:
    return json.dumps({
        "opening": {"amount_raw": opening, "date_raw": opening_date},
        "closing": {"amount_raw": closing, "date_raw": closing_date},
        "transactions": [],
    }, sort_keys=True, separators=(",", ":"))


def admission_fixture_events() -> tuple:
    """Return a fresh event sequence covering every frozen admission oracle."""
    checking = "Assets:Admission:Checking"
    card = "Liabilities:Cards:Admission"
    investment = "Assets:Admission:Investment"
    checking_doc = "admission-checking-2024-10"
    card_doc = "admission-card-2024-10"
    investment_doc = "admission-investment-2026-01"
    held_doc = "admission-held-review"

    events = [
        account_opened(checking, "depository", "Synthetic Checking", "USD",
                       "2024-10-01", institution="Example Community Bank"),
        account_opened(card, "liability", "Synthetic Rewards Card", "USD",
                       "2024-10-01", institution="Example Card Issuer",
                       jurisdiction="us"),
        account_opened(investment, "investment", "Vantage Invest", "USD",
                       "2026-01-01", institution="Fidelity"),
        document_captured(checking_doc, "synthetic-checking.pdf", 100,
                          "bank_account_statement", 1.0, "2024-11-01"),
        document_captured(card_doc, "synthetic-card.pdf", 100,
                          "credit_card_account_statement", 1.0, "2024-11-01"),
        document_captured(investment_doc, "synthetic-investment.pdf", 100,
                          "brokerage_statement", 1.0, "2026-02-01"),
        document_captured(held_doc, "synthetic-review.pdf", 100,
                          "bank_account_statement", 1.0, "2026-02-02"),
        read_recorded(
            checking_doc, "synthetic-fixture", "fixture-v1", "text",
            _statement_reply("1000.00", "2024-10-01", "625.00", "2024-10-31"),
            0.0, 0, 0, True, None, "2024-11-01", usage_reported=True),
        read_recorded(
            card_doc, "synthetic-fixture", "fixture-v1", "text",
            _statement_reply("200.00", "2024-10-01", "450.00", "2024-10-31"),
            0.0, 0, 0, True, None, "2024-11-01", usage_reported=True),
        opening_balance_observed(checking, "1000.00", "2024-10-01",
                                 _provenance(checking_doc)),
        simple_transaction(checking, "-125.00", "SYNTHETIC GROCER",
                           "2024-10-08", provenance=_provenance(checking_doc, 2)),
        simple_transaction(checking, "-250.00", "COSTCO TEST TRANSFER",
                           "2024-10-16", provenance=_provenance(checking_doc, 3)),
        closing_balance_observed(checking, "625.00", "2024-10-31",
                                 _provenance(checking_doc, 4)),
        opening_balance_observed(card, "200.00", "2024-10-01",
                                 _provenance(card_doc)),
        simple_transaction(card, "-250.00", "COSTCO TEST TRANSFER RECEIVED",
                           "2024-10-16", provenance=_provenance(card_doc, 2)),
        closing_balance_observed(card, "450.00", "2024-10-31",
                                 _provenance(card_doc, 4)),
        closing_balance_observed(investment, "2400.00", "2026-01-31",
                                 _provenance(investment_doc, 2)),
        merchant_enriched("synthetic grocer", "groceries",
                          subcategory="supermarket", occurred_at="2024-11-02"),
        merchant_enriched(
            "costco", "transfers", canonical_name="Costco",
            aliases=["costco test transfer",
                     "costco test transfer received"],
            occurred_at="2024-11-02", by="synthetic-fixture"),
        statement_held(held_doc, {}, None, "gap", "2026-02-03"),
    ]
    # Exercise the largest normal counterparty catalog during live admission,
    # without adding movements, amounts, balances, or answer evidence. Together
    # with the four held keys above, these fill the 256-entry catalog bound.
    events.extend(
        merchant_enriched(
            f"synthetic counterparty {index:03d}", "other",
            canonical_name=f"Synthetic Counterparty {index:03d}",
            occurred_at="2024-11-02", by="synthetic-fixture")
        for index in range(1, 253))
    left = movement_key(checking_doc, checking, "2024-10-16",
                        Decimal("-250.00"), "COSTCO TEST TRANSFER", 0)
    right = movement_key(card_doc, card, "2024-10-16", Decimal("-250.00"),
                         "COSTCO TEST TRANSFER RECEIVED", 0)
    events.append(transfer_linked(
        left, right, VERIFIED, {"decided_by": "synthetic-fixture-rule"},
        "2024-11-03", by="fixture"))
    return tuple(events)


def admission_fixture_digest() -> str:
    """Digest fixture meaning while excluding constructor-generated event ids."""
    payload = {
        "version": ADMISSION_FIXTURE_VERSION,
        "events": [{"event_type": event.event_type,
                    "occurred_at": event.occurred_at,
                    "provenance": event.provenance.to_dict(),
                    "body": event.body}
                   for event in admission_fixture_events()],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def admission_registry():
    """Return a fresh registry over the canonical admission-only ledger."""
    return default_registry(
        LedgerProjection(admission_fixture_events()), today=ADMISSION_TODAY)


__all__ = ["ADMISSION_FIXTURE_VERSION", "ADMISSION_TODAY",
           "admission_fixture_digest", "admission_fixture_events",
           "admission_registry"]
