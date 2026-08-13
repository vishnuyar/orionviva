"""Categorization — assign a movement to a category, as a graded overlay.

Every assignment is an event against a stable movement key: a human
confirmation is `verified`, a model suggestion `unverified` and shown against
the source until confirmed. Each one captures the movement's raw descriptor, so
merchant learning is a projection over these events rather than a re-ingest.

The seed taxonomy is data and open: any string is a valid category, and a new
label is created by assigning it.
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

# The primary categories live in merchantcore (the shareable taxonomy); the
# product offers those plus the fallback, and accepts any other string.
from merchantcore import FALLBACK_CATEGORY, PRIMARY_CATEGORIES  # noqa: E402

SEED_CATEGORIES = PRIMARY_CATEGORIES + (FALLBACK_CATEGORY,)

UNCATEGORIZED = "Uncategorized"


def normalize_category(category: str) -> str:
    """Canonicalize a label: trimmed and lowercased, or "other" when empty."""
    return (category or "").strip().lower() or "other"


def _today() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def tag_movement(ledger: Ledger, movement_key: str, tags: list,
                 by: str = "human") -> None:
    """Tag one movement. ``tags`` is the complete set — last write wins."""
    from ..ledger.events import SCOPE_MOVEMENT, movement_tagged
    ledger.append(movement_tagged(movement_key, list(tags or []), _today(),
                                  scope=SCOPE_MOVEMENT, by=by))


def tag_merchant(ledger: Ledger, merchant: str, tags: list,
                 by: str = "human") -> None:
    """Tag every movement from a merchant. ``tags`` is the complete set.

    The caller is responsible for not generalizing a peer descriptor this way."""
    from ..ledger.events import SCOPE_MERCHANT, movement_tagged
    ledger.append(movement_tagged(merchant, list(tags or []), _today(),
                                  scope=SCOPE_MERCHANT, by=by))


def rule_tag_same_as(ledger: Ledger, label: str, same_as: str,
                     by: str = "human") -> None:
    """Record that two tag labels name one thing.

    A separate alias space from categories: a tag and a category with the same
    text are distinct subjects, and merging one does not merge the other."""
    from ..ledger.events import SCOPE_TAG, ruling_recorded
    label = (label or "").strip().lower()
    same_as = (same_as or "").strip().lower()
    if not label or not same_as or label == same_as:
        return
    ledger.append(ruling_recorded(scope=SCOPE_TAG, subject=label,
                                  same_as=same_as, occurred_at=_today(), by=by))


def rule_category_same_as(ledger: Ledger, label: str, same_as: str,
                          by: str = "human") -> None:
    """Record that two category labels name one thing.

    Nothing is rewritten: past events keep their original label, and every
    total folds ``label`` into ``same_as`` from the moment the ruling exists,
    retroactively and with no re-ingest. Reversed by appending the opposite
    ruling. A no-op when either label is empty or the two are equal."""
    from ..ledger.events import SCOPE_CATEGORY, ruling_recorded
    label, same_as = normalize_category(label), normalize_category(same_as)
    if not label or not same_as or label == same_as:
        return
    ledger.append(ruling_recorded(
        scope=SCOPE_CATEGORY, subject=label, same_as=same_as,
        occurred_at=_today(), by=by))


def assign_category(ledger: Ledger, movement_key: str, category: str,
                    by: str = "human", nature: str = "") -> bool:
    """Assign a category to one movement.

    ``by='human'`` records it `verified`, anything else `unverified`. Captures
    the movement's descriptor for later merchant learning. ``nature`` is the
    optional ruling on what the movement is — `spending`, `transfer` or
    `settlement` — and outranks any category hint when the projection derives
    nature. Returns whether the movement was found."""
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
    """Categorize a whole merchant, everywhere it appears.

    ``by='human'`` records it `verified`, anything else `unverified`. It fills
    every transaction from that merchant, past and future, unless a
    per-transaction assignment overrides it. ``subcategory`` is the finer label
    and the sharper nature signal; supplying it records a `MerchantEnriched`
    rather than a `MerchantCategorized`."""
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
    """Record what money with this merchant is — spending, a transfer between
    the person's own accounts, or a settlement.

    Carried in the `MerchantEnriched` attributes bag, preserving the merchant's
    existing category, subcategory and canonical name. One ruling settles every
    transaction from that merchant, past and future.

    For commercial merchants only: a peer descriptor's nature varies per payment
    and is ruled per movement via ``assign_category(nature=…)``."""
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
    """Categorize the uncategorized merchants in one batched call.

    Gathers the deduped unknown merchants and, if there are at least
    ``threshold`` of them, makes a single call —
    ``categorize_fn({merchant: example}) -> {merchant: category}`` — recording
    each answer as a `corroborated` merchant rule that fills every transaction
    from that merchant, past and future. ``categorize_fn`` is injected, so this
    runs offline. Returns how many merchants were categorized."""
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


def enrich_merchants(ledger: Ledger, catalog, extract_fn, profile_for=None,
                     kind_for=None, chunk_size: int | None = None) -> dict:
    """Enrich the vault's unknown brands through merchantcore.

    Keyed on the brand, not the descriptor. What crosses is a brand and the
    impersonal context every occurrence of it agreed on: no raw descriptor, no
    amount, date or account, and no stream a grammar slot marked as a person.
    merchantcore enriches the pending set in batched calls and the records sync
    back as `MerchantEnriched` events, so categorization is retrospective and
    the ledger stays self-contained.

    ``profile_for(movement)`` supplies the induced grammar for the movement's
    (institution × kind) or None; ``kind_for(movement)`` the account kind. Both
    are optional — without them the resolution falls back through the published
    rules and the normalizer, and no account kind is filtered out.

    ``chunk_size`` bounds how many merchants ride in one model call; None takes
    the package's own default.

    Returns counts of `submitted`, `enriched`, `synced`, `unanswered`, `offered`,
    `minted` and `withheld_people`."""
    from merchantcore import Enricher

    from ..ledger.hints import enrichment_hints
    from ..ledger.streams import build_streams

    from merchantcore.profile import is_inducible

    proj = ledger.projection()
    # Only account kinds whose descriptors name a counterparty — the same
    # allowlist the grammar uses. An investment activity line names a security,
    # and an unmodelled kind is held back until it is added to the allowlist.
    movements = proj.movements()
    if kind_for is not None:
        movements = [m for m in movements if is_inducible(kind_for(m))]
        held_back = len(proj.movements()) - len(movements)
        if held_back:
            log.info("merchants: %d movement(s) held back — their account kind "
                     "names no party", held_back)
    streams = build_streams(movements, profile_for, kind_for)
    offered = enrichment_hints(streams)
    submitted = catalog.submit((h.key, h.example()) for h in offered.values())
    enriched, unanswered, minted = 0, 0, 0
    batch = catalog.pending()
    if batch:
        # The subcategories this vault already uses are shown to the model, so
        # an answer reuses an existing label where one fits — held to what may
        # cross to a model, exactly as the category vocabulary is (T9). A
        # subcategory is a name the person's own rulings coined, so it can
        # carry a person in it.
        from merchantcore.enrich import DEFAULT_CHUNK_SIZE

        from ..listen import shareable_categories
        enricher = Enricher(extract_fn,
                            chunk_size=(DEFAULT_CHUNK_SIZE if chunk_size is None
                                        else chunk_size),
                            known_subcategories=shareable_categories(
                                proj.known_subcategories()))
        records = enricher.enrich(batch)
        catalog.add_all(records)
        enriched = len(records)
        # How far the run went beyond the vocabulary it was shown. Minting is
        # never blocked; it is counted, so a growing label set is visible.
        minted = len(enricher.minted)
        # Marked unanswered: what the model was shown and declined to name, so
        # the queue stops re-asking it. Brands in a chunk whose reply never
        # parsed are excluded — they stay pending and are asked again.
        transport = set(enricher.unparsed)
        unanswered = catalog.mark_unanswered(
            k for k in batch if k not in records and k not in transport)

    # Sync: import catalog records the ledger does not already reflect at an
    # equal or higher grade. Idempotent.
    #
    # Only for merchants this vault actually holds — the ones it offered, plus
    # the ones its ledger already carries a record for. The catalog is shared
    # across every vault on the machine and may be seeded, so a record about a
    # merchant this vault never paid appends no event to this vault's log.
    existing = proj.merchant_categories()
    held = set(offered) | set(existing)
    synced = 0
    for key, r in catalog.records().items():
        if key not in held:
            continue
        cur = existing.get(key)
        if cur is None or _GRADE_RANK.get(r.grade, 0) > _GRADE_RANK.get(cur.get("grade"), 0):
            ledger.append(merchant_enriched(
                r.key, r.category, r.subcategory, r.canonical_name,
                r.attributes, r.grade, date.today().isoformat()))
            synced += 1
    withheld = len([s for s in streams if s.is_person])
    if submitted or enriched or synced:
        log.info("merchants: offered %d brand(s), submitted %d, enriched %d, "
                 "synced %d; %d person stream(s) withheld",
                 len(offered), submitted, enriched, synced, withheld)
    return {"submitted": submitted, "enriched": enriched, "synced": synced,
            "unanswered": unanswered, "minted": minted,
            "offered": len(offered), "withheld_people": withheld}


def export_catalog(ledger: Ledger) -> dict:
    """The shareable merchant catalog: `{merchant: {category, grade}}`.

    Commercial merchants only — anything ``is_shareable`` rejects is dropped —
    and no amounts, dates or transaction links. This is the content a commons
    contribution is hashed from."""
    cat = ledger.projection().merchant_categories()
    return {merchant: {"category": r["category"], "grade": r.get("grade", "")}
            for merchant, r in cat.items() if is_shareable(merchant)}


def suggest_categories(ledger: Ledger, suggest_fn) -> int:
    """Run a suggester over uncategorized expense movements.

    Records each answer as an `unverified` assignment. ``suggest_fn(descriptor)
    -> category | None`` is injected, so this runs offline. Returns how many
    were suggested."""
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
