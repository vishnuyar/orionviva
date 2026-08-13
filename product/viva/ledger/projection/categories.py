"""Categories partition the money; tags overlay the meaning.

A category label is a bare string rather than a resolved identity, so
`poker` and `playing poker` can both exist and split a total. The fix is
the same primitive accounts, transfers and merchants use: ask when
ambiguous, record the ruling, apply it on the READ side. Not fuzzy string
matching — a recorded alias is auditable and stable between runs, and is
reversed by appending rather than editing.

A category PARTITIONS (one per movement, parts sum to the whole); a tag
OVERLAYS (many per movement, overlapping, and the totals do NOT sum).
Double-entry governs the money; tags govern the meaning.
"""

from __future__ import annotations

from decimal import Decimal

from merchantcore.descriptor import linted_example
from merchantcore.taxonomy import subcategory_identity

from ..merchants import is_shareable
from . import merchants as merchants_view
from . import movements as movements_view
from .core import ProjectionCore


def _record_for(core: ProjectionCore, m) -> dict | None:
    """The record a movement's category is read off: a per-transaction override
    wins, else the strongest catalog record its merchant is filed under."""
    override = core._categories.get(m.key)
    return (override if override is not None
            else merchants_view.merchant_record(core, m))


def derived_category(core: ProjectionCore, m) -> dict | None:
    """A movement's effective category: a per-transaction override wins,
    else the strongest catalog record its merchant is filed under, else
    None. Returns the ruling dict ({category, grade, ...}) with its labels
    canonicalized."""
    found = _record_for(core, m)
    if found is None:
        return None
    # Canonicalized here, at the one funnel every aggregate reads through,
    # so a single alias ruling corrects spending-by-category,
    # spending-by-subcategory, the tiers and net worth at once.
    #
    # The subcategory is folded by separator as well: two spellings differing
    # only in punctuation are one label and one total, with no ruling behind
    # it, and a ruling reaches every spelling that fold declares the same.
    # Everything past punctuation — a plural, a connective, a synonym — stays
    # two labels until a person rules. The primary category is left alone; its
    # controlled names carry underscores of their own.
    if not core._category_alias_map:
        subcategory = (found.get("subcategory") or "").strip()
        folded = subcategory_identity(subcategory)
        return found if folded == subcategory else {**found, "subcategory": folded}
    out = dict(found)
    category = (out.get("category") or "").strip()
    if category:
        out["category"] = canonical_category(core, category)
    subcategory = (out.get("subcategory") or "").strip()
    if subcategory:
        out["subcategory"] = canonical_subcategory(core, subcategory)
    return out


def category_of(core: ProjectionCore, key: str) -> dict | None:
    """The per-transaction override ruling on a movement, or None (the raw
    overlay; ``derived_category`` resolves the merchant prior too)."""
    return core._categories.get(key)


def category_aliases(core: ProjectionCore) -> dict[str, str]:
    """{duplicate label -> the label it is really the same as}."""
    return dict(core._category_alias_map)


def canonical_category(core: ProjectionCore, label: str) -> str:
    """Follow a label to the one every total counts it under.

    Chains are followed (a → b → c) and a cycle terminates rather than
    hanging, returning the last label reached."""
    aliases = core._category_alias_map
    seen: set[str] = set()
    current = label
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def canonical_subcategory(core: ProjectionCore, label: str) -> str:
    """Follow a subcategory label to the one every total counts it under.

    The separator fold applies on both sides of the lookup: the label asked
    about is folded, and so is every label a ruling was recorded against, so a
    ruling recorded against one spelling reaches every spelling the fold
    declares the same.

    Chains are followed and a cycle terminates, as in `canonical_category`."""
    aliases = core._subcategory_alias_map
    seen: set[str] = set()
    current = subcategory_identity(label)
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def subcategory_spelling(core: ProjectionCore, m) -> tuple[str, str]:
    """How this movement's record spells its subcategory, and the label every
    spelling differing only in punctuation is counted under.

    ``(spelling, label)``: the spelling is what the record wrote, the label is
    what the figure is filed under. Asked per movement, so a caller collects
    the spellings its own filters actually counted rather than every spelling
    the vault holds. ``("", "")`` where the record names no subcategory."""
    raw = ((_record_for(core, m) or {}).get("subcategory") or "").strip()
    return (raw, subcategory_identity(raw)) if raw else ("", "")


def known_categories(core: ProjectionCore) -> list[str]:
    """The category vocabulary that already exists, canonical labels only.

    Offered to every path that could MINT a label: the surface picker, the
    free-text ruling, and enrichment's prompt."""
    out = {canonical_category(core, c)
           for row in core._merchant_categories.values()
           for c in [(row.get("category") or "").strip()] if c}
    out |= {canonical_category(core, (row.get("category") or "").strip())
            for row in core._categories.values()
            if (row.get("category") or "").strip()}
    return sorted(out)


def known_subcategories(core: ProjectionCore) -> list[str]:
    """The finer vocabulary, canonicalized — the subcategory labels the
    merchant catalog and the per-movement overlay carry.

    Spelled as the totals count them, so this list and the totals agree."""
    out = {canonical_subcategory(core, s)
           for row in list(core._merchant_categories.values())
           + list(core._categories.values())
           for s in [(row.get("subcategory") or "").strip()] if s}
    return sorted(out - {""})


def subcategory_merges(core: ProjectionCore) -> dict[str, list[str]]:
    """The subcategory spellings this vault holds that now count as one label.

    ``{the label they count under: every spelling behind it}``, and only where
    the separator fold is what brought two of them together. A group whose
    spellings met because a person ruled them the same is left out; an empty
    result means no total moved without an event behind it.

    A ruling landing on one spelling of a folded label does not remove the
    group — it is still reported, under the label the ruling moved it to."""
    groups: dict[str, set[str]] = {}
    for row in (list(core._merchant_categories.values())
                + list(core._categories.values())):
        raw = (row.get("subcategory") or "").strip()
        if not raw:
            continue
        groups.setdefault(canonical_subcategory(core, raw), set()).add(raw)
    return {label: sorted(spellings)
            for label, spellings in sorted(groups.items())
            if len({subcategory_identity(s) for s in spellings}) < len(spellings)}


def spending_by_category(core: ProjectionCore,
                         currency: str | None = None) -> dict[str, Decimal]:
    """Real spending grouped by category: every expense movement, card
    purchases included, bucketed by its *derived* category (override →
    merchant catalog → ``Uncategorized``). Positive magnitudes;
    ``currency`` filters if given.

    Exclusion is by **nature**, not merely by link, so an internal movement
    that never linked — a card payment, a brokerage contribution — is not
    counted, and `transfers` never appears as a line item inside spending."""
    out: dict[str, Decimal] = {}
    for m in movements_view.movements(core):
        if not movements_view.counts_as_spending(m):
            continue
        if currency is not None and m.currency != currency:
            continue
        # An empty category name is not a category: a ruling can carry one,
        # and a `''` bucket in a spending report is a line a person cannot read
        # and cannot filter on. It is the same default the finer view takes, so
        # the two agree about how much is unnamed.
        cat = (derived_category(core, m) or {}).get("category") or "Uncategorized"
        out[cat] = out.get(cat, Decimal("0")) + abs(m.amount)
    return out


def spending_by_subcategory(core: ProjectionCore,
                            currency: str | None = None) -> dict[str, Decimal]:
    """Finer spending view: expense movements grouped by the merchant's
    **subcategory** ("streaming", "warehouse club"), falling back to the
    primary category, then ``Uncategorized``. Positive magnitudes;
    non-spending natures excluded."""
    out: dict[str, Decimal] = {}
    for m in movements_view.movements(core):
        if not movements_view.counts_as_spending(m):
            continue
        if currency is not None and m.currency != currency:
            continue
        ruling = derived_category(core, m) or {}
        label = (ruling.get("subcategory") or ruling.get("category")
                 or "Uncategorized")
        out[label] = out.get(label, Decimal("0")) + abs(m.amount)
    return out


def spending_by_category_then_subcategory(
        core: ProjectionCore,
        currency: str | None = None) -> dict[str, dict[str, Decimal]]:
    """Spending grouped by category, and within each by subcategory.

    ``{category: {subcategory: amount}}``, where the inner key is ``""`` for
    money the category carries that no subcategory names. Positive magnitudes;
    ``currency`` filters if given; non-spending natures excluded, exactly as
    `spending_by_category` excludes them.

    The nesting is what `spending_by_subcategory` cannot express: that view
    falls back to the category label when a movement has no subcategory, so its
    keys are two vocabularies in one namespace and a subcategory sharing a name
    with a category is summed with it. Here the two stay apart, and each
    category's inner values sum to the same total `spending_by_category` gives
    it."""
    out: dict[str, dict[str, Decimal]] = {}
    for m in movements_view.movements(core):
        if not movements_view.counts_as_spending(m):
            continue
        if currency is not None and m.currency != currency:
            continue
        ruling = derived_category(core, m) or {}
        category = ruling.get("category") or "Uncategorized"
        sub = (ruling.get("subcategory") or "").strip()
        within = out.setdefault(category, {})
        within[sub] = within.get(sub, Decimal("0")) + abs(m.amount)
    return out


def uncategorized_expenses(core: ProjectionCore) -> list:
    """Expense movements whose *derived* category is still unknown — no
    override and no merchant-catalog entry. The categorization queue;
    non-spending natures are excluded, so money that did not leave the
    person's life is never asked about."""
    return [m for m in movements_view.movements(core)
            if movements_view.counts_as_spending(m)
            and derived_category(core, m) is None]


def uncategorized_merchants(core: ProjectionCore,
                            expenses_only: bool = False) -> dict[str, dict]:
    """Every counterparty we have not identified yet, deduped by normalized
    key: {merchant -> {count, example, shareable}}. The batched enricher's
    pending set.

    Every counterparty, not just the expense-shaped ones: employers,
    transfers, card payments and inflows are all visible to enrichment.

    `expenses_only=True` gives the narrower, expense-only view for the
    spending queue."""
    out: dict[str, dict] = {}
    source = (uncategorized_expenses(core) if expenses_only
              else [m for m in movements_view.movements(core)
                    if derived_category(core, m) is None])
    for m in source:
        key = merchants_view.merchant_key_of(core, m)
        if not key:
            continue
        # The LINTED example, never the raw line: a raw descriptor carries
        # store numbers, order ids and posting dates, none of which help
        # identify a brand and all of which would cross to a model provider.
        row = out.setdefault(key, {"count": 0,
                                   "example": linted_example(m.description),
                                   "shareable": is_shareable(m.description)})
        row["count"] += 1
    return out


# ------------------------------------------------------------------------ tags

def tags_of(core: ProjectionCore, m) -> list[str]:
    """Every tag on this movement, canonicalized and sorted: its own tags
    unioned with its merchant's.

    A union rather than an override — "everything from this gym is martial
    arts" and "this visit was a birthday present" are both true, and the
    movement is found under either."""
    own = core._movement_tags.get(m.key, [])
    shared = next((core._merchant_tags[k]
                   for k in merchants_view.merchant_keys_of(core, m)
                   if core._merchant_tags.get(k)), [])
    return sorted({canonical_tag(core, t) for t in list(own) + list(shared)})


def tag_aliases(core: ProjectionCore) -> dict[str, str]:
    """Tag-vocabulary aliases, kept apart from category aliases: a tag
    "poker" and a category "poker" are different things, and merging one
    does not merge the other."""
    return dict(core._tag_alias_map)


def canonical_tag(core: ProjectionCore, label: str) -> str:
    aliases = core._tag_alias_map
    seen: set[str] = set()
    current = (label or "").strip().lower()
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def known_tags(core: ProjectionCore) -> list[str]:
    """The tag vocabulary, canonical labels only — offered before a new tag
    can be minted, exactly as the category vocabulary is."""
    out = {canonical_tag(core, t)
           for tags in list(core._movement_tags.values())
           + list(core._merchant_tags.values()) for t in tags}
    return sorted(t for t in out if t)


def spending_by_tag(core: ProjectionCore, currency: str | None = None) -> dict:
    """Spending per tag: ``{by_tag, untagged, total, overlaps}``.

    The per-tag figures DO NOT sum to `total`, and callers must show
    `untagged` and `total` alongside them: one movement carrying three tags
    appears in three lines, and money with no tags appears in none. The
    category report is the one that partitions; this answers a different
    question ("how much on the Japan trip, across every merchant?")."""
    by_tag: dict[str, Decimal] = {}
    untagged = total = Decimal("0")
    for m in movements_view.movements(core):
        if not movements_view.counts_as_spending(m):
            continue
        if currency is not None and m.currency != currency:
            continue
        amount = abs(m.amount)
        total += amount
        tags = tags_of(core, m)
        if not tags:
            untagged += amount
        for tag in tags:
            by_tag[tag] = by_tag.get(tag, Decimal("0")) + amount
    return {"by_tag": by_tag, "untagged": untagged, "total": total,
            "overlaps": True}
