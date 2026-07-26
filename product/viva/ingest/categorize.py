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
                             category_assigned, merchant_categorized,
                             merchant_enriched)
from ..ledger.ledger import Ledger
from ..ledger.merchants import is_shareable, normalize_merchant

_GRADE_RANK = {VERIFIED: 3, CORROBORATED: 2, UNVERIFIED: 1}

log = logging.getLogger(__name__)

# The 16 primary categories live in merchantcore (the shareable taxonomy); the
# product offers them plus the fallback. Categories are still open — a user may
# assign anything.
from merchantcore import FALLBACK_CATEGORY, PRIMARY_CATEGORIES  # noqa: E402

SEED_CATEGORIES = PRIMARY_CATEGORIES + (FALLBACK_CATEGORY,)

UNCATEGORIZED = "Uncategorized"


def normalize_category(category: str) -> str:
    """Canonicalize a label (trim + lowercase). Custom categories are allowed —
    the seed is a suggestion set, not a closed taxonomy."""
    return (category or "").strip().lower() or "other"


def _today() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def rule_category_same_as(ledger: Ledger, label: str, same_as: str,
                          by: str = "human") -> None:
    """Record that two labels name one thing (Slice 7.5).

    Nothing is rewritten. The event that recorded "playing poker" keeps saying
    "playing poker" forever — T4 — and every total folds it into "poker" from
    the moment this ruling exists, retroactively, with no re-ingest. A merge
    made in error is reversed by appending the opposite ruling, never by
    editing, which is what makes it safe to offer at all."""
    from ..ledger.events import SCOPE_CATEGORY, ruling_recorded
    label, same_as = normalize_category(label), normalize_category(same_as)
    if not label or not same_as or label == same_as:
        return
    ledger.append(ruling_recorded(
        scope=SCOPE_CATEGORY, subject=label, same_as=same_as,
        occurred_at=_today(), by=by))


def assign_category(ledger: Ledger, movement_key: str, category: str,
                    by: str = "human", nature: str = "") -> bool:
    """Assign a category to a movement. ``by='human'`` records it `verified` (the
    authoritative ruling + the moat); ``by='model'`` records a `unverified`
    suggestion. Captures the movement's descriptor for later merchant learning.

    ``nature`` (Slice 6.5, optional) is the person's ruling on what the movement
    *is* — `spending`, `transfer`, or `settlement`. It rides on this same overlay
    rather than needing a new event type (Move 1 is read-side only), and outranks
    any category hint when the projection derives nature. Returns whether the
    movement was found."""
    proj = ledger.projection()
    m = next((mv for mv in proj.movements() if mv.key == movement_key), None)
    descriptor = m.description if m else ""
    when = m.date if m else date.today().isoformat()
    grade = VERIFIED if by == "human" else UNVERIFIED
    log.info("category: %s %s -> %r (%s)%s", by, movement_key[:24],
             normalize_category(category), grade,
             f" nature={nature}" if nature else "")
    ledger.append(category_assigned(movement_key, descriptor,
                                    normalize_category(category), grade,
                                    when, by=by, nature=nature))
    return m is not None


def assign_merchant_category(ledger: Ledger, merchant: str, category: str,
                             by: str = "human", subcategory: str = "") -> None:
    """Categorize a whole MERCHANT (Slice 5.5) — 'this merchant is X, everywhere'.
    ``by='human'`` is `verified` (fills every transaction from it, past and
    future, unless a per-transaction override says otherwise). ``subcategory`` is
    the finer label (Slice 5.6) — also the sharper *nature* signal (Slice 6.5)."""
    grade = VERIFIED if by == "human" else UNVERIFIED
    log.info("merchant: %s %r -> %r (%s)", by, merchant, normalize_category(category), grade)
    if subcategory:
        ledger.append(merchant_enriched(
            normalize_merchant(merchant), normalize_category(category),
            subcategory=subcategory.strip().lower(), grade=grade,
            occurred_at=date.today().isoformat(), by=by))
        return
    ledger.append(merchant_categorized(normalize_merchant(merchant),
                                       normalize_category(category), grade,
                                       date.today().isoformat(), by=by))


def rule_merchant_nature(ledger: Ledger, merchant: str, nature: str,
                         by: str = "human") -> None:
    """Record what money with this merchant *is* — spending, a transfer between
    the person's own accounts, or a settlement (Slice 6.5 Move 2).

    Rides on the existing `MerchantEnriched` attributes bag rather than adding an
    event type or a field: nature is merchant knowledge like any other attribute,
    and the write side stays untouched (abstract the read side early, the write
    side late). One ruling settles every transaction from that merchant, past and
    future — the Slice 5.5 generalization, applied to nature.

    Only ever called for *commercial* merchants; a peer descriptor's nature varies
    per payment and is ruled per-movement via ``assign_category(nature=…)``."""
    prior = ledger.projection().merchant_categories().get(normalize_merchant(merchant), {})
    attributes = dict(prior.get("attributes") or {})
    attributes["nature"] = nature
    log.info("merchant: %s %r nature -> %r", by, merchant, nature)
    ledger.append(merchant_enriched(
        normalize_merchant(merchant), prior.get("category", ""),
        subcategory=prior.get("subcategory", ""),
        canonical_name=prior.get("canonical_name", ""),
        attributes=attributes, grade=VERIFIED if by == "human" else CORROBORATED,
        occurred_at=date.today().isoformat(), by=by))


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


def enrich_merchants(ledger: Ledger, catalog, extract_fn) -> dict:
    """The product↔merchantcore loop (Slice 5.6). Submit the unknown, shareable
    merchants to the catalog as **impersonal** hints (a normalized key + a linted
    example — nothing about amounts, dates, or accounts crosses, T9); let
    merchantcore enrich the pending set in one batched call; then **sync** the
    catalog records back into the ledger as `MerchantEnriched` events, so
    categorization is retrospective and the ledger stays self-contained (T4).

    ``catalog`` is a ``merchantcore.Catalog``; ``extract_fn`` is the injected
    model call. Returns counts."""
    from merchantcore import Enricher

    proj = ledger.projection()
    hints = [(key, row["example"])
             for key, row in proj.uncategorized_merchants().items()
             if row["shareable"]]
    submitted = catalog.submit(hints)
    enriched = 0
    if catalog.pending():
        # Show the model the labels this vault already uses, so a new one is a
        # deliberate act rather than the path of least resistance (Slice 7.5).
        records = Enricher(
            extract_fn,
            known_subcategories=ledger.projection().known_subcategories()
        ).enrich(catalog.pending())
        catalog.add_all(records)
        enriched = len(records)

    # Sync: import catalog records the ledger doesn't already reflect (idempotent).
    existing = proj.merchant_categories()
    synced = 0
    for key, r in catalog.records().items():
        cur = existing.get(key)
        if cur is None or _GRADE_RANK.get(r.grade, 0) > _GRADE_RANK.get(cur.get("grade"), 0):
            ledger.append(merchant_enriched(
                r.key, r.category, r.subcategory, r.canonical_name,
                r.attributes, r.grade, date.today().isoformat()))
            synced += 1
    if submitted or enriched or synced:
        log.info("merchants: submitted %d, enriched %d, synced %d",
                 submitted, enriched, synced)
    return {"submitted": submitted, "enriched": enriched, "synced": synced}


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
