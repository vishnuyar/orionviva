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
from decimal import Decimal

from ..ledger.events import (CORROBORATED, MAJOR_ASSET, MAJOR_EXPENSE,
                             SCOPE_MOVEMENT, UNVERIFIED, VERIFIED,
                             category_assigned, merchant_categorized,
                             merchant_enriched, ruling_recorded)
from ..ledger.ledger import Ledger
from ..ledger.merchants import is_shareable, normalize_merchant

_GRADE_RANK = {VERIFIED: 3, CORROBORATED: 2, UNVERIFIED: 1}

log = logging.getLogger(__name__)

# The primary categories live in merchantcore (the shareable taxonomy); the
# product offers those plus the fallback, and accepts any other string.
from merchantcore import FALLBACK_CATEGORY, PRIMARY_CATEGORIES  # noqa: E402

SEED_CATEGORIES = PRIMARY_CATEGORIES + (FALLBACK_CATEGORY,)

UNCATEGORIZED = "Uncategorized"

MEANING_SPENDING = "spending"
MEANING_LOAN = "loan"
MEANING_LOAN_REPAYMENT = "loan_repayment"
MOVEMENT_MEANINGS = (MEANING_SPENDING, MEANING_LOAN,
                     MEANING_LOAN_REPAYMENT)


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
    # Preserve a merchant key the projection already holds; normalize only a
    # descriptor that has not resolved to a held identity.
    projection = ledger.projection()
    held = set(projection.merchant_categories())
    held.update(projection.merchant_key_of(m) for m in projection.movements())
    supplied = str(merchant or "").strip()
    merchant_key = supplied if supplied in held else normalize_merchant(supplied)
    log.info("merchant: %s %r -> %r (%s)", by, merchant_key,
             normalize_category(category), grade)
    if subcategory:
        ledger.append(merchant_enriched(
            merchant_key, normalize_category(category),
            subcategory=subcategory.strip().lower(), grade=grade,
            occurred_at=date.today().isoformat(), by=by))
        return
    ledger.append(merchant_categorized(merchant_key,
                                       normalize_category(category), grade,
                                       date.today().isoformat(), by=by))


def assign_default_categories(ledger: Ledger, doc_id: str) -> int:
    """Assign replaceable first categories to one posted statement.

    Person grammar slots receive ``transfers`` and transfer treatment; other
    unidentified movements receive ``other``. Existing categories and
    movements from other documents are unchanged.
    """
    if not (doc_id or "").strip():
        return 0
    projection = ledger.projection()
    assigned = 0
    for movement in projection.movements():
        if movement.provenance.doc_id != doc_id:
            continue
        if projection.derived_category(movement) is not None:
            continue
        person = projection.is_person(movement)
        category = "transfers" if person else "other"
        ledger.append(category_assigned(
            movement.key, movement.description, category, UNVERIFIED,
            movement.date, by="default",
            nature="transfer" if person else ""))
        assigned += 1
    if assigned:
        log.info("category: default-classified %d movement(s) from %s",
                 assigned, doc_id[:12])
    return assigned


def assign_movement_meaning(ledger: Ledger, movement_key: str, meaning: str,
                            counterparty: str = "") -> bool:
    """Record one movement's economic treatment without opening an account.

    Loan treatments bind the movement to a named asserted receivable and must
    agree with the movement's direction and known principal.
    """
    from ..ledger.postings import account_path
    from ..ledger.projection.movements import is_expense, money_effect

    meaning = (meaning or "").strip().lower()
    if meaning not in MOVEMENT_MEANINGS:
        raise ValueError(f"unknown movement meaning {meaning!r}")
    proj = ledger.projection()
    movement = next((item for item in proj.movements()
                     if item.key == movement_key), None)
    if movement is None:
        return False
    effect = money_effect(movement)

    if meaning == MEANING_SPENDING:
        if not is_expense(movement):
            raise ValueError("only an expense-shaped movement can be spending")
        legs = [{"major": MAJOR_EXPENSE,
                 "account": account_path(MAJOR_EXPENSE, "Other")}]
        said = "count this movement as spending"
        current = proj.derived_category(movement)
        if current is None or normalize_category(
                current.get("category", "")) == "transfers":
            # Keep the category aligned with the spending treatment.
            ledger.append(category_assigned(
                movement.key, movement.description, FALLBACK_CATEGORY,
                VERIFIED, movement.date, by="human"))
    else:
        label = " ".join((counterparty or "").strip().split())
        if not label or not any(char.isalnum() for char in label):
            raise ValueError("a loan correction needs the person or arrangement name")
        if len(label) > 80:
            raise ValueError("a loan correction name is too long")
        account = account_path(MAJOR_ASSET, "Loans", label)
        if meaning == MEANING_LOAN and effect >= 0:
            raise ValueError("a loan lent must move money out")
        if meaning == MEANING_LOAN_REPAYMENT:
            if effect <= 0:
                raise ValueError("a loan repayment must move money in")
            outstanding = Decimal("0")
            for other in proj.movements():
                if (other.key == movement.key or other.date > movement.date
                        or other.currency != movement.currency
                        or other.ruling_account != account):
                    continue
                outstanding += -money_effect(other)
            if outstanding <= 0:
                raise ValueError("no matching loan principal is outstanding")
            if effect > outstanding:
                raise ValueError("the repayment exceeds the outstanding principal")
        legs = [{"major": MAJOR_ASSET, "account": account}]
        said = ("this movement lent money to " if meaning == MEANING_LOAN
                else "this movement repaid the loan with ") + label
        # Loan treatments use the transfer category.
        ledger.append(category_assigned(
            movement.key, movement.description, "transfers", VERIFIED,
            movement.date, by="human"))

    ledger.append(ruling_recorded(
        SCOPE_MOVEMENT, movement.key, movement.date, legs=legs,
        by="human", grade=VERIFIED, said=said))
    return True


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
    """Enrich the vault's honestly unknown merchant identities through merchantcore.

    A reviewed exact alias resolves for free and never reaches the model. For an
    unresolved stream, its structural/brand fallback key and the impersonal
    context every occurrence agreed on cross: no raw descriptor, amount, date,
    account, or stream a grammar slot marked as a person. merchantcore enriches
    the pending set in batches and syncs records back as `MerchantEnriched`
    events, so categorization is retrospective and the ledger stays self-contained.

    ``profile_for(movement)`` supplies the induced grammar for the movement's
    (institution × kind) or None, and is optional — without it the resolution
    falls back through the published rules and the normalizer.
    ``kind_for(movement)`` gives the account kind and is required: it decides
    which way a movement's money went and which kinds name a party at all.
    Raises ValueError without it.

    ``chunk_size`` bounds how many merchants ride in one model call; None takes
    the package's own default.

    Returns counts of `submitted`, `enriched`, `synced`, `unanswered`, `offered`,
    `minted` and `withheld_people`."""
    from merchantcore import Enricher

    from ..ledger.hints import enrichment_hints
    from ..ledger.streams import build_streams

    from merchantcore.profile import is_inducible

    if kind_for is None:
        raise ValueError(
            "enrich_merchants needs kind_for: the account kind decides which "
            "movements name a party and which way their money went"
        )
    proj = ledger.projection()
    # Only account kinds whose descriptors name a counterparty — the same
    # allowlist the grammar uses. An investment activity line names a security,
    # and an unmodelled kind is held back until it is added to the allowlist.
    every = proj.movements()
    movements = [m for m in every if is_inducible(kind_for(m))]
    held_back = len(every) - len(movements)
    if held_back:
        log.info("merchants: %d movement(s) held back — their account kind "
                 "names no party", held_back)
    streams = build_streams(movements, profile_for, kind_for)
    offered = enrichment_hints(streams)
    unknown = [hint for hint in offered.values()
               if catalog.resolve(hint.identity_candidates or (hint.key,)) is None]
    submitted = catalog.submit((hint.key, hint.example()) for hint in unknown)
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

    # Apply installed records independently of whether enrichment made a call.
    synced = sync_merchant_records(ledger, catalog, offered)
    withheld = len([s for s in streams if s.is_person])
    if submitted or enriched or synced:
        log.info("merchants: offered %d brand(s), submitted %d, enriched %d, "
                 "synced %d; %d person stream(s) withheld",
                 len(offered), submitted, enriched, synced, withheld)
    return {"submitted": submitted, "enriched": enriched, "synced": synced,
            "unanswered": unanswered, "minted": minted,
            "offered": len(offered), "withheld_people": withheld}


def merchant_records_to_sync(ledger: Ledger, catalog, offered=()) -> dict:
    """Catalog records this vault can apply without a model call.

    ``offered`` contains this vault's eligible counterparty hints. Existing
    ledger records are considered too, so a stronger installed prior can
    replace an older one. Records for merchants the vault never encountered
    are excluded. Pure: returns records and writes nothing.
    """
    existing = ledger.projection().merchant_categories()
    matched: dict = {}
    items = offered.items() if isinstance(offered, dict) else (
        (key, None) for key in offered)
    for key, hint in items:
        candidates = (getattr(hint, "identity_candidates", None)
                      or (getattr(hint, "key", None) or key,))
        record = catalog.resolve(candidates)
        if record is not None:
            matched[record.key] = record
    for key in existing:
        record = catalog.get(key)
        if record is not None:
            matched[record.key] = record
    return {
        key: record for key, record in matched.items()
        if (key not in existing
            or not set(record.aliases).issubset(
                set(existing[key].get("aliases") or ()))
            or _GRADE_RANK.get(record.grade, 0)
            > _GRADE_RANK.get(existing[key].get("grade"), 0))
    }


def sync_merchant_records(ledger: Ledger, catalog, offered=()) -> int:
    """Append matching installed records as idempotent vault events.

    Lower-grade records may add reviewed aliases without replacing stronger
    local facts. No extractor or model call is used.
    """
    records = merchant_records_to_sync(ledger, catalog, offered)
    for record in records.values():
        ledger.append(merchant_enriched(
            record.key, record.category, record.subcategory,
            record.canonical_name, record.attributes, record.grade,
            date.today().isoformat(), aliases=record.aliases))
    return len(records)


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
