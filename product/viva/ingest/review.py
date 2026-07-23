"""Human-in-the-loop review: list held statements, and apply a person's ruling.

This is the second half of the findings design (see
docs/verification-findings-and-correction.md): a statement that did not
reconcile was *held* (its read persisted, never posted). Here the person rules
on it, and their ruling is a **correction event** — appended, never an overwrite
(T4) — after which the corrected statement posts at `verified`, the highest
grade, because a human attested it against the source.

Everything here is deterministic and offline: the person supplies the value, the
same reconciliation gate decides whether it now holds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from ..ledger.events import Provenance, correction_applied
from ..ledger.store import EventStore
from .pipeline import IngestResult, account_id_for, post_statement
from .statement import StatementFacts

log = logging.getLogger(__name__)


@dataclass
class HeldItem:
    doc_id: str
    reason: str                 # "conflict" | "gap"
    account_ref: str
    facts: StatementFacts
    finding: dict | None

    def to_dict(self) -> dict:
        f = self.facts
        return {
            "doc_id": self.doc_id, "reason": self.reason,
            "account_ref": self.account_ref, "currency": f.currency,
            "opening_amount": str(f.opening_amount),
            "closing_amount": str(f.closing_amount),
            "closing_date": f.closing_date,
            "transactions": [t.to_dict() for t in f.transactions],
            "finding": self.finding,
        }


def _posted_docs(events) -> set[str]:
    posted: set[str] = set()
    for e in events:
        if e.event_type in ("TransactionRecorded", "ClosingBalanceObserved",
                            "OpeningBalanceObserved") and e.provenance.doc_id:
            posted.add(e.provenance.doc_id)
    return posted


def held_items(events) -> list[HeldItem]:
    """The statements awaiting a human ruling — held and not since resolved."""
    events = list(events)
    posted = _posted_docs(events)
    latest: dict[str, dict] = {}
    for e in events:
        if e.event_type == "StatementHeld":
            latest[e.body["doc_id"]] = e.body
    items: list[HeldItem] = []
    for doc_id, body in latest.items():
        if doc_id in posted:
            continue                     # already resolved and posted
        facts = StatementFacts.from_dict(body["facts"])
        items.append(HeldItem(doc_id=doc_id, reason=body.get("reason", ""),
                              account_ref=facts.account_ref, facts=facts,
                              finding=body.get("finding")))
    return items


def _held_facts(store: EventStore, doc_id: str) -> StatementFacts:
    body = None
    for e in store.events():
        if e.event_type == "StatementHeld" and e.body["doc_id"] == doc_id:
            body = e.body
    if body is None:
        raise ValueError(f"no held statement for {doc_id}")
    return StatementFacts.from_dict(body["facts"])


def apply_human_correction(store: EventStore, doc_id: str, field: str,
                           value: str, target_index: int | None = None
                           ) -> IngestResult:
    """Apply a person's ruling to a held statement, then re-post it.

    ``field`` is 'amount' (with ``target_index``) or 'closing'; ``value`` is the
    corrected figure the person read off the source. The ruling is recorded as a
    correction event; if it now reconciles, the statement posts at `verified`.
    If it still doesn't, it is held again — we don't post what we can't verify."""
    from dataclasses import replace
    facts = _held_facts(store, doc_id)
    to_value = str(Decimal(value))

    if field == "amount":
        if target_index is None:
            raise ValueError("amount correction needs a target_index")
        old = facts.transactions[target_index]
        from_value = str(old.amount)
        txns = list(facts.transactions)
        txns[target_index] = replace(old, amount=Decimal(value))
        corrected = replace(facts, transactions=txns)
        target = f"transaction {target_index} ({old.description})"
    elif field == "closing":
        from_value = str(facts.closing_amount)
        corrected = replace(facts, closing_amount=Decimal(value))
        target = "closing balance"
    else:
        raise ValueError(f"unknown correction field {field!r}")

    log.info("correction: doc_id=%s %s: %s -> %s (by human)",
             doc_id[:12], target, from_value, to_value)
    store.append(correction_applied(
        doc_id, target, from_value, to_value, facts.closing_date, by="human",
        provenance=Provenance(doc_id=doc_id)))
    return post_statement(store, corrected, confirmed_by="human")
