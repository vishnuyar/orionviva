"""Categorization — assign a movement to a category, as a graded overlay.

The mechanism is correction-as-event over a stable movement key (Slice 5): a
human confirmation is `verified` and the moat; a model suggestion is `unverified`
and shown against the source until confirmed. Every assignment captures the
movement's raw descriptor, so merchant learning is later a projection over these
events — no re-ingestion, nothing wasted.

The seed taxonomy is minimal, jurisdiction-neutral **data** (I5): a person or a
region extends it by simply assigning a new label; nothing here is a US-shaped
table, and any string is a valid category.
"""

from __future__ import annotations

import logging
from datetime import date

from ..ledger.events import UNVERIFIED, VERIFIED, category_assigned
from ..ledger.ledger import Ledger

log = logging.getLogger(__name__)

# Offered defaults only — categories are open; the user may assign anything.
SEED_CATEGORIES = (
    "groceries", "dining", "transport", "utilities", "housing", "shopping",
    "health", "entertainment", "income", "transfers", "other",
)

UNCATEGORIZED = "Uncategorized"


def normalize_category(category: str) -> str:
    """Canonicalize a label (trim + lowercase). Custom categories are allowed —
    the seed is a suggestion set, not a closed taxonomy."""
    return (category or "").strip().lower() or "other"


def assign_category(ledger: Ledger, movement_key: str, category: str,
                    by: str = "human") -> bool:
    """Assign a category to a movement. ``by='human'`` records it `verified` (the
    authoritative ruling + the moat); ``by='model'`` records a `unverified`
    suggestion. Captures the movement's descriptor for later merchant learning.
    Returns whether the movement was found."""
    proj = ledger.projection()
    m = next((mv for mv in proj.movements() if mv.key == movement_key), None)
    descriptor = m.description if m else ""
    when = m.date if m else date.today().isoformat()
    grade = VERIFIED if by == "human" else UNVERIFIED
    log.info("category: %s %s -> %r (%s)", by, movement_key[:24],
             normalize_category(category), grade)
    ledger.append(category_assigned(movement_key, descriptor,
                                    normalize_category(category), grade,
                                    when, by=by))
    return m is not None


def suggest_categories(ledger: Ledger, suggest_fn) -> int:
    """Run a model/heuristic suggester over uncategorized expense movements,
    recording `unverified` suggestions (shown, never asserted). ``suggest_fn(
    descriptor) -> category | None`` is injected, so this is testable offline and
    the live model edge is swappable. Returns the count suggested."""
    proj = ledger.projection()
    n = 0
    for m in proj.uncategorized_expenses():
        cat = suggest_fn(m.description)
        if not cat:
            continue
        ledger.append(category_assigned(m.key, m.description,
                                        normalize_category(cat), UNVERIFIED,
                                        m.date, by="model"))
        n += 1
    if n:
        log.info("category: suggested %d category(ies)", n)
    return n
