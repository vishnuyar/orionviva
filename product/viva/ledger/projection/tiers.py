"""How much of a person's attention a movement deserves.

The queue's rule: ask only where the counterparty cannot tell us. A
supermarket tells us everything; a mortgage servicer tells us there is a
loan but not which property; a check tells us nothing.
"""

from __future__ import annotations

from decimal import Decimal

from ..merchants import is_shareable
from . import categories as categories_view
from . import merchants as merchants_view
from . import movements as movements_view
from .core import ProjectionCore

# Which tier a movement falls in, and therefore whether it is worth a person's
# attention. The rule: ask only where the counterparty cannot tell us.
TIER_SETTLED = "settled"      # enriched, implies nothing → silence
TIER_STRUCTURAL = "structural"  # implies a relationship → an informed proposal
TIER_UNKNOWN = "unknown"      # an instrument or a peer → a real question
TIER_UNENRICHED = "unenriched"  # the merchant is unidentified → enrich first


def tier_of(core: ProjectionCore, m) -> str:
    """Which tier this movement falls in — how much of a person's attention
    it deserves. The queue's rule: ask only where the counterparty cannot
    tell us. A supermarket tells us everything (settled); a mortgage servicer
    tells us there is a loan but not which property (structural); a check
    tells us nothing (unknown)."""
    if merchants_view.counterparty_kind(core, m) in ("instrument", "peer"):
        return TIER_UNKNOWN
    # A descriptor that cannot be SHARED never reaches enrichment, so it can
    # never become `settled` and `unenriched` would promise an identification
    # that will not come. It is `unknown`, the tier that asks one transaction
    # at a time.
    if not is_shareable(m.description):
        return TIER_UNKNOWN
    if categories_view.derived_category(core, m) is None:
        return TIER_UNENRICHED
    return (TIER_STRUCTURAL if merchants_view.implication_of(core, m)
            else TIER_SETTLED)


def tier_summary(core: ProjectionCore, currency: str | None = None) -> dict:
    """Per tier, ``{count, amount, merchants}`` — the measurement that sizes
    the queue. ``merchants`` is a count of distinct normalized keys."""
    out: dict[str, dict] = {}
    for m in movements_view.movements(core):
        if currency is not None and m.currency != currency:
            continue
        row = out.setdefault(tier_of(core, m), {"count": 0, "amount": Decimal("0"),
                                                "merchants": set()})
        row["count"] += 1
        row["amount"] += abs(m.amount)
        row["merchants"].add(merchants_view.merchant_key_of(core, m)
                             or m.description)
    return {k: {"count": v["count"], "amount": v["amount"],
                "merchants": len(v["merchants"])} for k, v in out.items()}


def declined_questions(core: ProjectionCore) -> dict[str, dict]:
    """Questions set aside, by the queue's stable question id. Each body
    carries the stake snapshot (amount, count) from the moment of decline.
    Data, not policy: this remembers, the queue decides."""
    return dict(core._declined)
