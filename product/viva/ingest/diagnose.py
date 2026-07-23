"""Deterministic diagnosis of a reconciliation failure — Rung 0 of the ladder.

When a statement's opening + transactions do not equal its closing, this module
localizes *why*, using arithmetic alone — no model calls. It returns a typed
``ReconciliationFinding`` whose ``status`` draws the trust boundary described in
docs/verification-findings-and-correction.md:

  - **forced**      — a correction implied by an *independent* identity (the
                      printed running-balance chain) that ALSO closes the
                      opening→closing reconciliation. Two identities agree, so it
                      is safe to auto-apply (at grade `corroborated`) and report.
  - **suggested**   — a correction a *heuristic* proposes (the gap equals a
                      line, a digit transposition). NEVER auto-applied; shown to
                      the human against the source.
  - **unlocalized** — the gap has no clean explanation; likely not this document
                      type at all → reclassify, don't correct.

The rules are deterministic and versioned, so a verdict can always reproduce and
explain itself — a "forced" fix that were actually a heuristic misfire would post
a wrong number, the one failure a trust product cannot survive.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .statement import StatementFacts

DIAGNOSIS_VERSION = "diag-v1"

# statuses
FORCED = "forced"
SUGGESTED = "suggested"
UNLOCALIZED = "unlocalized"
NONE = "none"


@dataclass(frozen=True)
class ReconciliationFinding:
    reconciles: bool
    kind: str                      # ok | amount_misread | balance_misread | missing_or_extra | transposition | unknown
    status: str                    # forced | suggested | unlocalized | none
    delta: str                     # closing - (opening + sum(txns)), as Decimal string
    message: str
    target: str = ""               # human-readable locus
    target_index: int | None = None
    observed: str | None = None    # the value we read at the target
    implied: str | None = None     # the value that would repair it (forced/suggested)
    confidence: float = 0.0
    version: str = DIAGNOSIS_VERSION

    def to_dict(self) -> dict:
        return {
            "reconciles": self.reconciles, "kind": self.kind,
            "status": self.status, "delta": self.delta, "message": self.message,
            "target": self.target, "target_index": self.target_index,
            "observed": self.observed, "implied": self.implied,
            "confidence": self.confidence, "version": self.version,
        }


def _cents(d: Decimal) -> int:
    return int((d * 100).to_integral_value())


def diagnose(facts: StatementFacts) -> ReconciliationFinding:
    """Localize a reconciliation failure with arithmetic alone."""
    opening = facts.opening_amount
    closing = facts.closing_amount
    txns = facts.transactions
    total = sum((t.amount for t in txns), start=Decimal("0"))
    delta = closing - (opening + total)

    if delta == 0:
        return ReconciliationFinding(
            reconciles=True, kind="ok", status=NONE, delta="0",
            message="Statement reconciles.", confidence=1.0)

    # --- forced: the running-balance chain, an independent identity -----------
    if txns and all(t.running_balance is not None for t in txns):
        forced = _via_running_balance(opening, closing, total, txns, delta)
        if forced is not None:
            return forced

    # --- suggested: heuristics that localize but cannot force ------------------
    # The gap equals one line's amount → a likely missing or duplicated line.
    for i, t in enumerate(txns):
        if abs(t.amount) == abs(delta):
            return ReconciliationFinding(
                reconciles=False, kind="missing_or_extra", status=SUGGESTED,
                delta=str(delta), target=f"transaction {i} ({t.description})",
                target_index=i, observed=str(t.amount), confidence=0.5,
                message=(f"The gap of {delta} equals this line's amount — it may "
                         "be duplicated in my read, or one like it is missing. "
                         "Please check against the statement."))

    # A gap that is a multiple of 9 is the signature of a transposed digit.
    if _cents(abs(delta)) % 9 == 0:
        return ReconciliationFinding(
            reconciles=False, kind="transposition", status=SUGGESTED,
            delta=str(delta), confidence=0.4,
            message=(f"The gap of {delta} is a multiple of 9 — the signature of "
                     "two swapped digits somewhere. I couldn't pin the line; "
                     "please check the figures against the statement."))

    # --- unlocalized: no clean explanation ------------------------------------
    return ReconciliationFinding(
        reconciles=False, kind="unknown", status=UNLOCALIZED, delta=str(delta),
        confidence=0.1,
        message=(f"Off by {delta}, with no clean explanation. This may not be a "
                 "checking statement, or several figures are wrong. Held for review."))


def _via_running_balance(opening: Decimal, closing: Decimal, total: Decimal,
                         txns, delta: Decimal) -> ReconciliationFinding | None:
    """Walk the printed running-balance chain. Return a FORCED finding if it
    localizes to exactly one repair that also closes the reconciliation, else None."""
    breaks: list[int] = []
    prev = opening
    for i, t in enumerate(txns):
        if t.running_balance != prev + t.amount:
            breaks.append(i)
        prev = t.running_balance          # continue from the printed (trusted) figure
    last_printed = prev

    # Chain fully consistent, but the closing figure disagrees → closing misread.
    if not breaks:
        # A consistent chain telescopes to opening+total, so this is forced.
        return ReconciliationFinding(
            reconciles=False, kind="balance_misread", status=FORCED,
            delta=str(delta), target="closing balance",
            observed=str(closing), implied=str(last_printed), confidence=0.95,
            message=(f"The transactions and their running balances are internally "
                     f"consistent and end at {last_printed}, but the closing "
                     f"balance reads {closing}. Closing looks misread; using "
                     f"{last_printed}."))

    # Exactly one broken line, and repairing it closes the whole reconciliation.
    if len(breaks) == 1:
        i = breaks[0]
        prev_before = opening if i == 0 else txns[i - 1].running_balance
        implied = txns[i].running_balance - prev_before
        if opening + (total - txns[i].amount + implied) == closing:
            return ReconciliationFinding(
                reconciles=False, kind="amount_misread", status=FORCED,
                delta=str(delta), target=f"transaction {i} ({txns[i].description})",
                target_index=i, observed=str(txns[i].amount), implied=str(implied),
                confidence=0.95,
                message=(f"Line {i} ({txns[i].description}): I read {txns[i].amount}, "
                         f"but the running balance implies {implied}, which makes "
                         "the statement reconcile. Using the implied value."))

    return None
