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

from ..ledger.events import (CORROBORATED, UNVERIFIED, VERIFIED,
                             category_assigned, merchant_categorized)
from ..ledger.ledger import Ledger
from ..ledger.merchants import is_shareable, normalize_merchant

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


def assign_merchant_category(ledger: Ledger, merchant: str, category: str,
                             by: str = "human") -> None:
    """Categorize a whole MERCHANT (Slice 5.5) — 'this merchant is X, everywhere'.
    ``by='human'`` is `verified` (fills every transaction from it, past and
    future, unless a per-transaction override says otherwise)."""
    grade = VERIFIED if by == "human" else UNVERIFIED
    log.info("merchant: %s %r -> %r (%s)", by, merchant, normalize_category(category), grade)
    ledger.append(merchant_categorized(normalize_merchant(merchant),
                                       normalize_category(category), grade,
                                       date.today().isoformat(), by=by))


def categorize_merchants_batch(ledger: Ledger, categorize_fn,
                               threshold: int = 1) -> int:
    """Batched merchant categorization (the cost win, Slice 5.5): gather the
    deduped UNKNOWN merchants, and if there are at least ``threshold`` of them,
    make ONE call — ``categorize_fn({merchant: example}) -> {merchant: category}``
    — recording each as a `corroborated` merchant rule (a model batch agreeing is
    stronger than a lone guess, but not a human `verified`). Every past and future
    transaction from those merchants fills in retrospectively. ``categorize_fn``
    is injected, so this is offline-testable and the live model edge is swappable.
    Returns the number of merchants categorized."""
    pending = ledger.projection().uncategorized_merchants()
    if len(pending) < threshold:
        return 0
    examples = {mkey: row["example"] for mkey, row in pending.items()}
    results = categorize_fn(examples) or {}
    n = 0
    for mkey, category in results.items():
        if not category:
            continue
        ledger.append(merchant_categorized(mkey, normalize_category(category),
                                           CORROBORATED, date.today().isoformat(),
                                           by="model"))
        n += 1
    if n:
        log.info("merchant: batched-categorized %d merchant(s)", n)
    return n


def export_catalog(ledger: Ledger) -> dict:
    """The privacy-linted, shareable merchant catalog (Slice 5.5): commercial
    merchants only (peer-payment / PII filtered), category + grade, and NOTHING
    else — no amounts, dates, or transaction links. This is the content the
    commons contribution is hashed from (T5/T6)."""
    cat = ledger.projection().merchant_categories()
    return {merchant: {"category": r["category"], "grade": r.get("grade", "")}
            for merchant, r in cat.items() if is_shareable(merchant)}


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
