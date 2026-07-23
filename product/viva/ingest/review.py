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
import re
from dataclasses import dataclass
from decimal import Decimal

from ..ledger.events import (Provenance, account_alias_confirmed,
                             correction_applied)
from ..ledger.identity import account_key
from ..ledger.ledger import Ledger
from ..ledger.projection import LedgerProjection
from .pipeline import (IngestResult, account_id_for, heal_gaps, post_statement)
from .statement import StatementFacts

log = logging.getLogger(__name__)


def _mask(account_ref: str) -> str:
    """Mask a long account number in a label: keep the last 4 digits."""
    return re.sub(r"\d{5,}", lambda m: "····" + m.group(0)[-4:], account_ref)


@dataclass
class HeldItem:
    doc_id: str
    reason: str                 # "conflict" | "gap"
    account_ref: str
    facts: StatementFacts
    finding: dict | None
    held_balance: str | None = None    # for a gap: the balance the chain left off at

    def to_dict(self) -> dict:
        f = self.facts
        return {
            "doc_id": self.doc_id, "reason": self.reason,
            "account_ref": self.account_ref,
            "account_label": _mask(self.account_ref),
            "currency": f.currency,
            "opening_amount": str(f.opening_amount),
            "opening_date": f.opening_date,
            "closing_amount": str(f.closing_amount),
            "closing_date": f.closing_date,
            "period": f"{f.opening_date} – {f.closing_date}",
            "held_balance": self.held_balance,
            "transactions": [t.to_dict() for t in f.transactions],
            "finding": self.finding,
        }


def held_items(source) -> list[HeldItem]:
    """The statements awaiting a human ruling — held and not since resolved.

    ``source`` may be a live ``LedgerProjection`` (from the Ledger's cache) or an
    iterable of events (from which a projection is built)."""
    proj = source if isinstance(source, LedgerProjection) else LedgerProjection(source)
    items: list[HeldItem] = []
    for body in proj.open_holds():
        facts = StatementFacts.from_dict(body["facts"])
        held_bal = proj.running_balance(account_id_for(facts))
        items.append(HeldItem(
            doc_id=body["doc_id"], reason=body.get("reason", ""),
            account_ref=facts.account_ref, facts=facts,
            finding=body.get("finding"),
            held_balance=None if held_bal is None else str(held_bal)))
    return items


def apply_identity_ruling(ledger: Ledger, doc_id: str, decision: str) -> IngestResult:
    """The person rules on an ambiguous account identity, and we *learn* it.

    ``decision='same'`` merges the statement into the candidate account it matched
    by name; ``decision='new'`` confirms it is its own account. Either way the
    ruling is an `AccountAliasConfirmed` event, so the same pattern never asks
    again — then the statement is re-posted (it resolves cleanly now)."""
    body = next((b for b in ledger.projection().open_holds()
                 if b["doc_id"] == doc_id and b.get("reason") == "identity"), None)
    if body is None:
        raise ValueError(f"no identity-held statement for {doc_id}")
    facts = StatementFacts.from_dict(body["facts"])
    fnd = body.get("finding") or {}
    key = fnd.get("key") or account_key(facts.institution, facts.account_number,
                                        facts.account_ref)
    if decision == "same":
        target = fnd.get("candidate")
        if not target:
            raise ValueError("no candidate account to merge into")
    elif decision == "new":
        target = key
    else:
        raise ValueError("decision must be 'same' or 'new'")

    log.info("identity ruling: doc_id=%s key=%s -> %s (%s)",
             doc_id[:12], key, target, decision)
    ledger.append(account_alias_confirmed(key, target, doc_id, facts.closing_date,
                                          by="human"))
    res = post_statement(ledger, facts)     # resolves cleanly now (alias learned)
    if res.action == "posted":
        heal_gaps(ledger)
    return res


def _held_facts(ledger: Ledger, doc_id: str) -> StatementFacts:
    for body in ledger.projection().open_holds():
        if body["doc_id"] == doc_id:
            return StatementFacts.from_dict(body["facts"])
    raise ValueError(f"no held statement for {doc_id}")


def apply_human_correction(ledger: Ledger, doc_id: str, field: str,
                           value: str, target_index: int | None = None
                           ) -> IngestResult:
    """Apply a person's ruling to a held statement, then re-post it.

    ``field`` is 'amount' (with ``target_index``) or 'closing'; ``value`` is the
    corrected figure the person read off the source. The ruling is recorded as a
    correction event; if it now reconciles, the statement posts at `verified`.
    If it still doesn't, it is held again — we don't post what we can't verify."""
    from dataclasses import replace
    facts = _held_facts(ledger, doc_id)
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
    ledger.append(correction_applied(
        doc_id, target, from_value, to_value, facts.closing_date, by="human",
        provenance=Provenance(doc_id=doc_id)))
    res = post_statement(ledger, corrected, confirmed_by="human")
    if res.action == "posted":
        heal_gaps(ledger)            # this post may unblock statements waiting on it
    return res
