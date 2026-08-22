"""Who a movement's counterparty is, and what knowing them implies.

A merchant is filed under its BRAND: two locations of one retailer are one
key and one record. Naming the brand takes the resolution layers, and the
best of them is a grammar living outside the event log — so the key map is
built by an injected resolver rather than derived from events. What comes
back is the key each line is filed under and the lines a grammar slot
declared a person on, the one thing about a line no read can recover for
itself. Without a resolver a descriptor normalizes to itself and no line is
declared anything, which is what every read did before grammars existed.

Every lookup therefore considers TWO keys. Knowledge recorded before a
grammar could name the brand sits under the descriptor, and a person's
answer is the most trustworthy record in the vault; a lookup that found
only the brand key would lose it. The candidates are ranked by grade, the
brand winning a tie, so the strongest record answers regardless of which
name it happens to be filed under.
"""

from __future__ import annotations

from ..events import SCOPE_MERCHANT
from ..merchant_keys import MerchantKeys
from ..merchants import normalize_merchant
from .core import ProjectionCore, _grade_rank


def merchant_key_map(core: ProjectionCore) -> MerchantKeys:
    """`{(account, descriptor): brand key}` for every line held, carrying the
    lines a grammar slot declared a person on.

    Built once and dropped whenever a transaction or an account arrives,
    because both can change how a descriptor resolves.

    Always a `MerchantKeys`: the empty one a projection with no resolver gets
    declares no persons, and so does a resolver that named none. Raises
    `TypeError` where a resolver returns any other mapping, which carries no
    declaration to tell apart from a declaration of nobody."""
    if core._mkeys is None:
        if core._resolve_keys is None:
            core._mkeys = MerchantKeys()
        else:
            # Only the accounts `movements` reads: the other side of a
            # posting is a category, and a category has no counterparty.
            resolved = core._resolve_keys(
                [(account, st.institution, st.kind, ln.description)
                 for account, st in core._acct.items()
                 if st.kind in ("depository", "liability", "investment")
                 for ln in st.lines])
            if not isinstance(resolved, MerchantKeys):
                raise TypeError(
                    "a resolver must return MerchantKeys, which carries the "
                    "lines a slot declared a person on; got "
                    f"{type(resolved).__name__}")
            core._mkeys = resolved
    return core._mkeys


def merchant_keys_of(core: ProjectionCore, m) -> tuple:
    """Every key this movement's merchant could be filed under, strongest
    identity first: the brand, then the descriptor where they differ.

    Memoized per descriptor: this is read several times for every movement
    in the vault on every aggregate, and normalization is a run of regular
    expressions."""
    cached = core._mkeys_of.get((m.account, m.description))
    if cached is not None:
        return cached
    descriptor_key = normalize_merchant(m.description)
    brand_key = merchant_key_map(core).get((m.account, m.description),
                                           descriptor_key)
    keys = ((descriptor_key,) if brand_key in ("", descriptor_key)
            else (brand_key, descriptor_key))
    core._mkeys_of[(m.account, m.description)] = keys
    return keys


def merchant_key_of(core: ProjectionCore, m) -> str:
    """The single key this movement's merchant is known by now — what a
    surface groups on and what a new ruling about it is written under."""
    return merchant_keys_of(core, m)[0]


def is_person(core: ProjectionCore, m) -> bool:
    """True where a grammar slot declared the other side of this movement a
    person.

    The same declaration the enrichment gate reads, asked of a movement rather
    than of a stream: a slot named a party, never a guess from the text. False
    wherever no grammar has named the line, and false from a resolver that
    declared nobody.
    """
    return (m.account, m.description) in merchant_key_map(core).persons


def merchant_graded(core: ProjectionCore, get, m) -> dict | None:
    """The highest-graded record `get(key)` finds among the candidates, or
    None. Ties go to the first candidate, which is the brand."""
    best = None
    for key in merchant_keys_of(core, m):
        found = get(key)
        if found is None:
            continue
        if best is None or _grade_rank(found.get("grade")) > _grade_rank(best.get("grade")):
            best = found
    return best


def merchant_record(core: ProjectionCore, m) -> dict | None:
    """This movement's catalog record — what enrichment learned about the
    counterparty, or what a person ruled about it."""
    return merchant_graded(core, core._merchant_categories.get, m)


def merchant_ruling(core: ProjectionCore, m) -> dict | None:
    """The merchant-scoped ruling covering this movement, if one was made."""
    return merchant_graded(
        core, lambda key: core._rulings.get((SCOPE_MERCHANT, key)), m)


def merchant_categories(core: ProjectionCore) -> dict[str, dict]:
    """The merchant catalog: normalized merchant -> ruling."""
    return dict(core._merchant_categories)


def implication_for(core: ProjectionCore, merchant: str,
                    inflow: bool = False) -> dict | None:
    """The first implication a MERCHANT KEY carries in the given direction,
    or None. Keyed on the catalog rather than on a movement, so a caller can
    ask about a counterparty it has not seen yet."""
    return implication_in(core._merchant_categories.get(merchant),
                          inflow=inflow)


def implication_in(record: dict | None, inflow: bool = False) -> dict | None:
    """The first implication a catalog record carries in the given
    direction, or None."""
    implies = ((record or {}).get("attributes") or {}).get("implies") or []
    want = "inflow" if inflow else "outflow"
    for item in implies:
        if item.get("on") in (want, "both"):
            return item
    return None


def implication_of(core: ProjectionCore, m) -> dict | None:
    """What this movement's counterparty implies, filtered by DIRECTION.

    Money out to a lender repays borrowing; money in from one is the
    borrowing. Same counterparty, opposite sign, opposite meaning — so `on`
    is data on the implication rather than a branch in the caller.

    **Which way the money went comes from the account's kind.** A posted amount
    is signed by its effect on the balance the document prints, so on a
    liability a purchase posts positive and a sign alone reads it as money
    arriving. This asks the one function that knows, which raises rather than
    guessing when it is handed no kind — so a movement that cannot say what
    kind of account it is on cannot be described in a direction at all.

    The guard is the call, not a comment beside one: there is no branch here
    that reads `m.amount` and no argument that could reintroduce it."""
    from ..streams import money_effect

    return implication_in(merchant_record(core, m),
                          inflow=money_effect(getattr(m, "kind", ""),
                                              m.amount) > 0)


def counterparty_kind(core: ProjectionCore, m) -> str:
    """business | instrument | peer | "" — learned, not pattern-matched."""
    return ((merchant_record(core, m) or {}).get("attributes")
            or {}).get("counterparty_kind", "")


def kind_of_merchant(core: ProjectionCore, merchant: str) -> str:
    record = core._merchant_categories.get(merchant)
    return ((record or {}).get("attributes") or {}).get("counterparty_kind", "")
