"""Human-in-the-loop review: list held statements, and apply a person's ruling.

A statement that did not reconcile was held — its read persisted, never posted.
Here a person rules on it. The ruling is appended as a correction event rather
than overwriting anything, and the corrected statement re-enters the same
reconciliation gate, posting at `verified` if it now holds and being held again
if it does not.

Deterministic and offline: the person supplies the value, the gate decides.
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
from .registry import BALANCE_IDENTITY, identity_of_facts
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
        fdict = body.get("facts", {})
        # Route on the registry, not on the shape of the dict: a pay stub or a
        # brokerage statement is held with different facts.
        if identity_of_facts(fdict) != BALANCE_IDENTITY:
            continue                      # reported by other_holds() instead
        facts = StatementFacts.from_dict(fdict)
        held_bal = proj.running_balance(account_id_for(facts))
        items.append(HeldItem(
            doc_id=body["doc_id"], reason=body.get("reason", ""),
            account_ref=facts.account_ref, facts=facts,
            finding=body.get("finding"),
            held_balance=None if held_bal is None else str(held_bal)))
    return items


def other_holds(source) -> list[dict]:
    """Held documents that are not balance-family — a pay stub awaiting its
    deposit, a brokerage statement whose tally did not close.

    The complement of ``held_items`` over the same open holds, so between them
    no held document goes unreported. Returns dicts saying what each is and why
    it is waiting; there is no correction affordance for these."""
    proj = source if isinstance(source, LedgerProjection) else LedgerProjection(source)
    out: list[dict] = []
    for body in proj.open_holds():
        fdict = body.get("facts", {})
        if identity_of_facts(fdict) == BALANCE_IDENTITY:
            continue
        finding = body.get("finding") or {}
        out.append({
            "doc_id": body["doc_id"],
            "doc_type": fdict.get("doc_type", "unknown"),
            "reason": body.get("reason", ""),
            "account_ref": _mask(fdict.get("account_ref", "")
                                 or fdict.get("employer", "")),
            "message": finding.get("message", ""),
        })
    for body in proj.open_activity_holds():
        fdict = body.get("facts", {})
        finding = body.get("finding") or {}
        out.append({
            "doc_id": body["doc_id"],
            "doc_type": fdict.get("doc_type", "brokerage_statement"),
            "reason": "activity",
            "account_ref": _mask(fdict.get("account_ref", "")),
            "message": finding.get("message", ""),
        })
    return out


def apply_identity_ruling(ledger: Ledger, doc_id: str, decision: str) -> IngestResult:
    """Apply a person's ruling on an ambiguous account identity, and learn it.

    ``decision='same'`` merges the statement into the candidate account it
    matched by name; ``decision='new'`` confirms it is its own account. Either
    is recorded as an `AccountAliasConfirmed`, so the same pattern is not asked
    about again, and the statement is then re-posted. Raises ValueError when the
    document is not identity-held or the decision is not one of the two."""
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
    res = post_statement(ledger, facts)     # resolves cleanly now: alias learned
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
    correction event either way. If the statement now reconciles it posts at
    `verified`; if not, it is held again. Raises ValueError for an unknown field
    or an amount correction with no target index."""
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
        heal_gaps(ledger)            # this post may unblock a waiting statement
    return res
