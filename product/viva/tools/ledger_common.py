"""The read tools: deterministic functions over the projection, wrapped in the
envelope. Every filter value is validated against the vault's own learned
vocabulary — its accounts, categories, tags, merchants and currencies — and an
unknown value is refused with the known values named, never silently ignored.

Each read emits every number it asserts as a figure, because a number that
lives only inside a payload is machinery the answer may not speak. A read also
names the accounts it spoke about, so an answer can say which account it means
without the digits in that name being read as an amount. The two shapes of read
are separated: an aggregate answers "how much" without returning rows, and
``list_movements`` returns rows only for a question narrow enough to name one.

A figure holding an amount states the currency it is in, and a figure counting
things states none — that is how anything downstream tells an amount from a
plain number. A summary whose movements are not all in one currency refuses:
nothing here converts, so their sum would be a number in no currency at all.

Every figure also states what it measures, and the read that produced it is
what decides: a balance is not spending, a gross sum of postings is not
spending either, and a count of documents is not a proportion of anything. A
read that measures something the vocabulary cannot name fails here rather than
reaching a person inside a sentence about something else.

No tool here writes, calls a model, or touches the network; each reads the one
live projection it was built over.
"""

from __future__ import annotations

import calendar
import datetime
from decimal import Decimal
from functools import lru_cache

from .. import quantity, render
from ..ledger import networth
from ..ledger.identity import masked
from ..ledger.merchants import normalize_merchant
from ..ledger.projection import UnknownAccountError
from ..ledger.projection.categories import subcategory_group_key
from ..ledger.projection import movements as movements_view
from .envelope import (ACTIVITY, BY_ACCOUNT, BY_CATEGORY, BY_CURRENCY,
                       BY_KIND, BY_MERCHANT, BY_PERIOD, BY_SINCE, BY_SUBCATEGORY,
                       BY_TAG, BY_UNTIL, ENTITY_ACCOUNT, ENTITY_CATEGORY,
                       ENTITY_MERCHANT, GAP_REFUSED, GAP_UNOBSERVED,
                       ToolResult, bounded, cut_set, entity, figure, refusal,
                       weakest)
from .registry import Registry, ToolSpec

LIABILITY = "liability"
REAL_KINDS = ("depository", LIABILITY, "investment")

# How many journal entries one read returns: the most recent, and fewer than a
# movement read returns rows.
MAX_JOURNAL = 20

# How many rows a detailed read returns. Past it the read says how many it did
# not show and which filters would narrow it.
MAX_ROWS = 50

# How many groups an aggregate names. A grouping is as wide as the vault's own
# vocabulary — group spending by counterparty and the group count is the
# counterparty count — so the largest are named and the rest rides a caveat
# carrying its size and its value, which an answer states or refuses.
MAX_GROUPS = 10

# How many folded subcategory lines a caveat names before it counts the rest.
# The named ones are the lines that moved the most money; the remainder is
# stated as a count, never dropped.
MAX_FOLDS = 3

# How many labels a read of a vocabulary names. The same reason every other cap
# here exists: a result is resent in full on every remaining call of the turn,
# and a vocabulary is as wide as the person's own ledger. The count is the whole
# count either way — what the cap hides is which labels, never how many there
# are — and what it hid rides a caveat, like everything else a read leaves out.
MAX_LABELS = 40

# What a spending group is called when the movements in it name no
# counterparty — a description that is blank, or blank once its spaces come
# off. Every descriptor reaches a merchant key in lower case, so no real
# counterparty normalises onto this label.
UNNAMED_MERCHANT = "Unnamed"

# What a spending total counts and what it leaves out, said beside a total of
# something. It names the thing left out by what it is — money settling between
# two accounts the person holds — rather than by a label they have been shown
# beside a figure, so a category the vault happens to call `transfers` and the
# settlements this excludes are two different things and read as two.
COUNTS_WHAT_LEFT = (
    "This counts money that left your life. A movement recognised as settling "
    "between two of your own accounts is not counted, whatever category it "
    "carries; card purchases are counted.")

# What a value standing on measurements of several days owes a person. It
# points at nothing only a payload carries: how current the value is is said as
# a fact about what it rests on, in words that are as true of one account's
# composed value as of a point built from many.
MIXED_VINTAGE = ("This rests on records of more than one date: each part is "
                 "only as current as the record behind it.")


def _mixed_vintage(dates) -> bool:
    """Whether these measurements were taken on more than one day.

    The condition `MIXED_VINTAGE` is said on, so every caller placing that
    sentence places it on one rule. Days nothing recorded are not days, and a
    value resting on one day and one unknown says nothing here: the unknown is
    a gap and not a second vintage."""
    return len({str(day) for day in dates if str(day)}) > 1


# The filters each read honors. Both the model-facing schema and dispatcher
# derive their accepted combinations from this table.
_SUPPORTED_FILTERS = {
    "balances": {"account", "currency", "kind"},
    "transactions": {"account", "category", "tag", "merchant", "currency",
                     "window"},
    "list_movements": {"account", "category", "tag", "merchant", "currency",
                       "window"},
    "holdings": {"account", "currency"},
    "aggregate:spending": {"account", "category", "tag", "merchant",
                           "currency", "window"},
    "aggregate:income": {"currency", "window"},
    "aggregate:recurring_spending": {"currency"},
    "aggregate:surplus": {"currency", "window"},
    "aggregate:stalest_balance": set(),
    "aggregate:weakest_evidence": {"currency"},
    "aggregate:net_worth": set(),
    "vocabulary": set(),
}

_FILTER_PROPERTIES = {
    "account": {"type": "string"},
    "category": {"type": "string"},
    "tag": {"type": "string"},
    "merchant": {"type": "string"},
    "currency": {"type": "string"},
    "kind": {"type": "string", "enum": list(REAL_KINDS)},
    "window": {"type": "object",
               "properties": {"from": {"type": "string"},
                              "to": {"type": "string"},
                              "preset": {"type": "string",
                                         "enum": ["latest_complete_calendar_month"]}},
               "additionalProperties": False},
}

_ENTITY_VALUES = ["balances", "transactions", "holdings", "aggregate",
                  "vocabulary"]
_METRIC_VALUES = ["spending", "income", "recurring_spending", "surplus",
                  "stalest_balance", "weakest_evidence", "net_worth"]
_GROUP_VALUES = ["category", "subcategory", "tag", "merchant", "account",
                 "currency"]


def _filters_schema(kind: str) -> dict:
    """Return the closed native filter object for one read family."""
    return {
        "type": "object",
        "properties": {name: _FILTER_PROPERTIES[name]
                       for name in sorted(_SUPPORTED_FILTERS[kind])},
        "additionalProperties": False,
    }


def _query_branch(entity: str, *, metric: str = "") -> dict:
    kind = f"aggregate:{metric}" if metric else entity
    properties = {"entity": {"type": "string", "enum": [entity]}}
    required = ["entity"]
    if metric:
        properties["metric"] = {"type": "string", "enum": [metric]}
        required.append("metric")
    if entity == "vocabulary":
        properties["group_by"] = {"type": "string", "enum": _GROUP_VALUES}
        properties["matching"] = {"type": "string"}
        required.append("group_by")
    if metric == "spending":
        properties["group_by"] = {"type": "string", "enum": _GROUP_VALUES}
    if metric == "net_worth":
        properties["as_of"] = {"type": "string"}
    supported = _SUPPORTED_FILTERS[kind]
    if supported:
        properties["filters"] = _filters_schema(kind)
    return {"type": "object", "properties": properties,
            "required": required, "additionalProperties": False}


# Top-level properties expose the public vocabulary to deterministic and
# non-native callers. ``oneOf`` closes native calls by entity and metric.
QUERY_LEDGER_PARAMS = {
    "type": "object",
    "properties": {
        "entity": {"type": "string", "enum": _ENTITY_VALUES},
        "metric": {"type": "string",
                   "enum": _METRIC_VALUES},
        "group_by": {"type": "string",
                     "enum": _GROUP_VALUES},
        "as_of": {"type": "string"},
        "matching": {"type": "string"},
        "filters": {
            "type": "object",
            "properties": _FILTER_PROPERTIES,
        },
    },
    "required": ["entity"],
    "oneOf": [
        _query_branch("balances"),
        _query_branch("transactions"),
        _query_branch("holdings"),
        _query_branch("vocabulary"),
        *[_query_branch("aggregate", metric=metric)
          for metric in _METRIC_VALUES],
    ],
}

TOOL = "query_ledger"


def _real_accounts(proj) -> list:
    return [i for i in proj.account_infos() if i.kind in REAL_KINDS]


def _measure_of(kind: str) -> str:
    """What an account's magnitude measures: a liability's is what is owed, and
    anything else's is what is held. There is no third case."""
    return quantity.OWED if kind == LIABILITY else quantity.BALANCE


def _currencies(proj) -> set:
    return {i.currency for i in _real_accounts(proj) if i.currency}


def _identifiers(proj, accounts) -> list:
    """The accounts this read spoke about, each as an entity.

    An account answers to several names — the ledger path every read and filter
    uses, the name someone gave it, the masked form of its number — and one
    entity carries all of them. Which one a person reads is the renderer's
    decision, made once, so there is no form of a name that has to be allowed
    for separately. An account the projection does not hold contributes
    nothing."""
    out: list = []
    for account in sorted(set(accounts)):
        try:
            info = proj.account_info(account)
        except UnknownAccountError:
            continue
        out.append(entity(ENTITY_ACCOUNT, account=account, name=info.name,
                          number_masked=masked(info.number),
                          account_kind=info.kind, currency=info.currency))
    return out


def _merchant_key(proj, m) -> str:
    """The one string a counterparty is known by across every read.

    A movement's own description is the fallback and never the first answer:
    two statements spell one counterparty two ways, and a figure narrowed or
    grouped by counterparty is narrowed by the key. Every surface that names a
    counterparty — a group, a vocabulary, an entity a sentence may refer to —
    reads it from here, so the name beside a number and the value that number's
    scope declares are the same string."""
    return str(proj.merchant_key_of(m) or m.description or "").strip()


@lru_cache(maxsize=512)
def _merchant_filter_key(value: str) -> str:
    """The counterparty key a caller's value names, under the vault's own key
    function.

    Every key this vault holds was minted by that function, so asking it what
    the caller's string keys to is asking which held key was named rather than
    matching one string against another. What the read compares, refuses
    against and declares as its narrowing is that key, so the narrowing stays
    an exact comparison with a value the vault holds.

    Memoized: a read asks this once per movement, and the function is a run of
    regular expressions."""
    return normalize_merchant(value)


# The ways a candidate label can answer a lookup, strongest first. Each is a
# comparison between two strings the vault's own key function produced, so what
# is found is generous about how a person wrote a name and exact about which
# held label it names.
MATCH_EXACT, MATCH_PREFIX, MATCH_TOKEN = 1, 2, 3


def _match_tier(wanted: str, label: str) -> int:
    """Which tier `label` answers `wanted` at, or 0 where it does not.

    Both sides are keyed before they are compared, and the token tier splits on
    the key function's own separator, so a token is a whole word of the key
    rather than any run of characters inside it. A candidate matching at no
    tier is not one the caller named."""
    key = _merchant_filter_key(label)
    if not wanted or not key:
        return 0
    if key == wanted:
        return MATCH_EXACT
    if key.startswith(wanted):
        return MATCH_PREFIX
    if wanted in key.split():
        return MATCH_TOKEN
    return 0


def _merchants(keys) -> list:
    """The counterparties this read spoke about, each as an entity.

    A counterparty key is one of them: it names who the money went to, which is
    a thing rather than a magnitude, however many digits a statement happens to
    have written into the description it was read from. The key is what carries
    here because it is what a follow-up filter takes and what a figure's scope
    names; the description each movement was written with travels on the row it
    belongs to."""
    out, seen = [], set()
    for key in keys:
        text = str(key or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(entity(ENTITY_MERCHANT, example=text))
    return out


def _categories(labels) -> list:
    """The categories this read grouped by, each as an entity."""
    out, seen = [], set()
    for label in labels:
        text = str(label or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(entity(ENTITY_CATEGORY, label=text))
    return out


def _today() -> str:
    """Today, as the one place this module reads a clock."""
    import datetime

    return datetime.date.today().isoformat()


def _is_iso_date(value: str) -> bool:
    """A structural YYYY-MM-DD check — lexical, like every date comparison in
    the projection."""
    return (isinstance(value, str) and len(value) >= 10 and value[4] == "-"
            and value[7] == "-"
            and value[:4].isdigit() and value[5:7].isdigit()
            and value[8:10].isdigit())


def _known(values, cap: int = 40) -> list:
    """A refusal's 'here is what I do have' list, capped so a large vocabulary
    stays readable; the count says what the cap hid.

    Where it fits, the list is the whole answer and says nothing else. Where it
    does not, the useful thing is not more names in some order but how to find
    the one that was meant, so the last entry names the lookup. It carries no
    value the caller supplied: what was asked for is what was just refused."""
    out = sorted(v for v in values if v)
    if len(out) <= cap:
        return out
    return out[:cap] + [
        f"... and {len(out) - cap} more; query_ledger with entity 'vocabulary', "
        "the group_by for this kind and a 'matching' argument returns the ones "
        "a name reaches"]


# The machine tag a refusal carries when more than one filter is wrong. Each
# fault's own tag travels in the payload, under `filter_problems`.
MANY_BAD_FILTERS = "invalid_filters"


def _check_filters(proj, filters: dict) -> ToolResult | None:
    """Refuse any filter value the vault does not hold; None when all pass.

    Names every fault the call carries, not the first one found. One fault
    comes back under its own machine tag; several come back under
    MANY_BAD_FILTERS, with every fault's tag listed in `filter_problems`, the
    texts joined, and each fault's known-values payload merged in."""
    faults: list[tuple[str, str, dict]] = []
    if "account" in filters:
        held = set(proj.accounts())
        if filters["account"] not in held:
            faults.append((
                "unknown_account",
                f"I don't have an account '{filters['account']}' on file.",
                {"known_accounts": _known(i.account
                                          for i in _real_accounts(proj))}))
    if "category" in filters:
        known = set(proj.known_categories()) | {"Uncategorized"}
        if proj.canonical_category(filters["category"]) not in known:
            faults.append((
                "unknown_category",
                f"No category '{filters['category']}' exists in this vault.",
                {"known_categories": _known(known)}))
    if "tag" in filters:
        known = set(proj.known_tags())
        if proj.canonical_tag(filters["tag"]) not in known:
            faults.append((
                "unknown_tag",
                f"No tag '{filters['tag']}' exists in this vault.",
                {"known_tags": _known(known)}))
    if "merchant" in filters:
        # A key that is blank, or blank once stripped, is not a counterparty
        # this vault holds, so narrowing to it refuses like any other value the
        # vault does not hold.
        known = {key for key
                 in ({proj.merchant_key_of(m) for m in proj.movements()}
                     | set(proj.merchant_categories()))
                 if str(key or "").strip()}
        if _merchant_filter_key(filters["merchant"]) not in known:
            faults.append((
                "unknown_merchant",
                f"No counterparty '{filters['merchant']}' is on file under "
                "that key.",
                {"known_merchants": _known(known)}))
    if "currency" in filters:
        held = _currencies(proj)
        if filters["currency"] not in held:
            faults.append((
                "unknown_currency",
                f"No account holds '{filters['currency']}'.",
                {"known_currencies": _known(held)}))
    if "kind" in filters and filters["kind"] not in REAL_KINDS:
        faults.append((
            "unknown_account_kind",
            f"No balance account kind '{filters['kind']}' exists.",
            {"known_account_kinds": list(REAL_KINDS)}))
    window = filters.get("window", {})
    for edge in ("from", "to"):
        if edge in window and not _is_iso_date(window[edge]):
            faults.append((
                "bad_date",
                f"window.{edge} must be an ISO date (YYYY-MM-DD), got "
                f"'{window[edge]}'.",
                {}))
    if not faults:
        return None
    if len(faults) == 1:
        reason, text, extra = faults[0]
        return refusal(TOOL, reason, text, **extra)
    data: dict = {"filter_problems": [reason for reason, _, _ in faults]}
    for _, _, extra in faults:
        data.update(extra)
    return refusal(TOOL, MANY_BAD_FILTERS,
                   "; ".join(text for _, text, _ in faults), **data)


def _resolve_window_preset(proj, filters: dict,
                           today: str = "") -> tuple[dict, ToolResult | None]:
    """Resolve a named period to explicit inclusive edges before a read.

    The latest complete month is the newest ended calendar month wholly
    attested by every balance-holding account that has posted coverage.
    Accounts with no posted run stay visible through normal coverage caveats;
    they do not make every historical month unanswerable.
    """
    out = dict(filters)
    window = dict(out.get("window") or {})
    preset = window.get("preset", "")
    if not preset:
        return out, None
    if set(window) - {"preset"}:
        return out, refusal(
            TOOL, "window_conflict",
            "A window preset cannot be combined with explicit from/to edges.")
    if preset != "latest_complete_calendar_month":
        return out, refusal(TOOL, "unknown_window_preset",
                            f"No window preset '{preset}' exists.")

    bound = today or _today()
    try:
        today_date = datetime.date.fromisoformat(bound[:10])
    except ValueError:
        return out, refusal(TOOL, "bad_date",
                            f"today must be an ISO date, got '{bound}'.")

    common: set[str] | None = None
    covered_accounts = 0
    for info in _real_accounts(proj):
        months: set[str] = set()
        runs = proj.attested_runs(info.account)
        if not runs:
            continue
        covered_accounts += 1
        for start, end in runs:
            try:
                start_date = datetime.date.fromisoformat(start[:10])
                end_date = datetime.date.fromisoformat(end[:10])
            except ValueError:
                continue
            cursor = start_date.replace(day=1)
            while cursor <= end_date:
                month_end = cursor.replace(
                    day=calendar.monthrange(cursor.year, cursor.month)[1])
                if cursor >= start_date and month_end <= end_date \
                        and month_end < today_date:
                    months.add(cursor.strftime("%Y-%m"))
                cursor = (month_end + datetime.timedelta(days=1)).replace(day=1)
        common = months if common is None else common & months

    if not covered_accounts or not common:
        return out, refusal(
            TOOL, "no_complete_calendar_month",
            "The posted statement coverage does not establish one complete "
            "calendar month shared by the accounts it covers.")
    month = max(common)
    year, index = int(month[:4]), int(month[5:])
    out["window"] = {
        "from": f"{month}-01",
        "to": f"{month}-{calendar.monthrange(year, index)[1]:02d}",
    }
    return out, None


def _in_window(date: str, window: dict) -> bool:
    lo, hi = window.get("from", ""), window.get("to", "")
    return (not lo or date[:10] >= lo[:10]) and (not hi or date[:10] <= hi[:10])


def _movement_passes(proj, m, filters: dict) -> bool:
    if "account" in filters and m.account != filters["account"]:
        return False
    if "currency" in filters and m.currency != filters["currency"]:
        return False
    if ("merchant" in filters
            and proj.merchant_key_of(m) != _merchant_filter_key(
                filters["merchant"])):
        return False
    if "window" in filters and not _in_window(m.date, filters["window"]):
        return False
    if "category" in filters:
        want = proj.canonical_category(filters["category"])
        got = (proj.derived_category(m) or {}).get("category", "Uncategorized")
        if got != want:
            return False
    if "tag" in filters and proj.canonical_tag(filters["tag"]) not in proj.tags_of(m):
        return False
    return True


def _attested_coverage(proj, filters: dict,
                       accounts: set[str] | None = None) -> tuple[list, list]:
    """What this read is attested for, per account, and what to say about the
    accounts that fall short of the window asked for.

    Coverage is what a document proved, never what the movements happen to
    show. A statement enters the ledger only by reconciling — the issuer's own
    opening plus the period's transactions equal its closing — so inside a
    posted period every movement is present and a zero is a zero. Deriving the
    span from movement dates instead would report a quiet fortnight as a hole
    in the evidence, which is a different sentence and a false one.

    An account may attest more than one period: statements join only where the
    balances continue AND the dates meet, so a missing statement leaves two
    runs rather than one span across the gap it cannot support.

    Returns `(covers, caveats)`: one entry per account holding an attested
    period that meets the window, and a caveat for every account in scope that
    does not."""
    want = filters.get("window") or {}
    asked_from, asked_to = (want.get("from") or "")[:10], (want.get("to") or "")[:10]
    named = filters.get("account")
    scope = ([named] if named else sorted(accounts if accounts is not None else
             (i.account for i in proj.account_infos() if i.kind)))

    covers, caveats = [], []
    for account in scope:
        runs = proj.attested_runs(account)
        if not runs:
            caveats.append(f"No statement has posted for {account}, so nothing "
                           "here is attested for it.")
            continue
        first, last = runs[0][0], runs[-1][1]
        held = ", ".join(f"{a} to {b}" for a, b in runs)
        met = []
        for start, end in runs:
            lo = max(asked_from, start) if asked_from else start
            hi = min(asked_to, end) if asked_to else end
            if lo <= hi:
                met.append({"account": account, "from": lo, "to": hi})
        if not met:
            caveats.append(f"{account} is attested for {held}, none of which "
                           "falls inside the window asked for.")
            continue
        covers.extend(met)
        if len(met) > 1:
            caveats.append(f"{account} is attested for {len(met)} separate "
                           "periods inside the window asked for; a statement "
                           "between them is missing, and the days between are "
                           "not answered for.")
        if (asked_from and asked_from < first) or (asked_to and asked_to > last):
            caveats.append(f"For {account} the window asked for reaches past "
                           f"what its statements attest; this answers for "
                           f"{met[0]['from']} to {met[-1]['to']}.")
    return covers, caveats


def _shared_currency(currencies) -> str | None:
    """The one currency a set of amounts is in, "" when none of them says, and
    None when they disagree — which is a read that cannot be summed."""
    held = {c for c in currencies if c}
    if len(held) > 1:
        return None
    return held.pop() if held else ""


def _scope(proj, filters: dict) -> list:
    """The balance-holding accounts a read ranges over: the one it names, or
    every one of them."""
    named = filters.get("account")
    return [i for i in _real_accounts(proj)
            if not named or i.account == named]


def _of_an_empty_read(proj, filters: dict) -> tuple[str, list]:
    """What a total of nothing is an amount of, and what it rests on, as
    `(currency, record ids)`.

    A window in which nothing moved still has a total, and that total is zero
    of a currency rather than a bare number. The accounts the read ranged over
    say which currency, and their statements are what answer for the zero being
    real rather than merely unobserved. Saying neither leaves the same zero
    reading as a count, which no balance adds to."""
    scope = _scope(proj, filters)
    return (str(filters.get("currency") or "")
            or _shared_currency(i.currency for i in scope) or "",
            sorted(i.account for i in scope))


def _mixed_currencies(tool: str, held) -> ToolResult:
    """A total across currencies would be a number in none of them, and nothing
    here converts between them."""
    return refusal(tool, "mixed_currencies",
                   "These amounts are in " + ", ".join(sorted(held))
                   + ", and nothing here converts between currencies. A total "
                   "across them would be a number in no currency. Ask for one "
                   "currency at a time.",
                   currencies=sorted(held))


def _movement_row(proj, m, grades: dict) -> dict:
    ruling = proj.derived_category(m) or {}
    return {"record_id": m.key, "account": m.account, "date": m.date,
            "description": m.description,
            # Which counterparty this row is one of, under the one key every
            # read names a counterparty by. It is not a field of the row a
            # person is shown — the description above is — and it is here so a
            # read can say which counterparties it spoke about without
            # recomputing what the grouping already knows.
            "merchant_key": _merchant_key(proj, m),
            # How much, and which way it went. The posting's own sign does not
            # say the direction — the kind of account it sits on does — so the
            # raw signed amount is not a field of a row at all. A reader that
            # needs it has the movement.
            "effect": str(movements_view.money_effect(m)),
            "currency": m.currency, "nature": m.nature,
            "nature_reason": m.nature_reason, "provisional": m.provisional,
            "category": ruling.get("category", ""),
            "subcategory": ruling.get("subcategory", ""),
            "tags": proj.tags_of(m), "grade": grades.get(m.key, ""),
            "doc_id": m.provenance.doc_id}




_FILTER_NAMES = {"account": BY_ACCOUNT, "category": BY_CATEGORY,
                 "merchant": BY_MERCHANT, "tag": BY_TAG,
                 "currency": BY_CURRENCY, "kind": BY_KIND}

# And how each grouping cuts a set. Every grouping the schema offers names the
# slice each of its figures covers, including the three the vault holds no
# entity for: a subcategory key names a pair, a tag overlaps its neighbours and
# a currency is not a thing anyone holds. Saying which slice a figure is a
# figure of is a statement of that figure's scope, and a scope promises nothing
# about being askable — none of the three becomes a name a follow-up accepts,
# and the refusal a person meets if they try still names what is filterable.
_GROUP_NAMES = {"category": BY_CATEGORY, "merchant": BY_MERCHANT,
                "account": BY_ACCOUNT, "subcategory": BY_SUBCATEGORY,
                "tag": BY_TAG, "currency": BY_CURRENCY}

# The groupings under which every counted movement lands in exactly one group.
# Tags do not: one movement carries several of them and money carrying none
# lands in no group at all, so a tag group is a slice of the population however
# few tags there are.
_PARTITIONING = ("category", "subcategory", "merchant", "account", "currency")


def _narrowed_to(proj, filters: dict) -> list:
    """How the filters narrowed this read, as the things they named.

    A category and a counterparty are each named in the vault's own word for it
    rather than in the word the filter arrived as: what is stated is what was
    counted. A window is named by which of its edges were given, so a half-open
    one is still said rather than dropped."""
    out = []
    for name in sorted(set(filters) & set(_FILTER_NAMES)):
        if name == "category":
            value = proj.canonical_category(filters[name])
        elif name == "merchant":
            value = _merchant_filter_key(filters[name])
        else:
            value = filters[name]
        out.append({"kind": _FILTER_NAMES[name], "value": value})
    window = filters.get("window") or {}
    start, end = (window.get("from") or "")[:10], (window.get("to") or "")[:10]
    if start and end:
        out.append({"kind": BY_PERIOD, "value": start, "to": end})
    elif start:
        out.append({"kind": BY_SINCE, "value": start})
    elif end:
        out.append({"kind": BY_UNTIL, "value": end})
    return out


def _month_slice(month: str, narrowed) -> dict | None:
    """The slice a month-shaped group covers: the calendar month it names, held
    inside whatever window the read was narrowed to.

    Two declarations the read already wrote down, met where both of them are
    known. The month's own first and last day say which month the group is —
    not the days something moved in it — and a read asked for part of a month
    holds none of that month's other days, so the month's own edges would
    declare a span the figure was never taken over and claim the days before
    the window opened as its own. Where the two disagree the narrower edge
    stands, on each edge separately, so a window given one edge narrows that
    edge and leaves the other where the month put it.

    `narrowed` is how the read was narrowed, and it has no default: a caller
    that left it out would get the month's own edges back, which is the claim
    this exists to stop.

    `month` is a group name taken from a stored date, which nothing upstream
    promises is a date. Returns None where it is not shaped `YYYY-MM`, names a
    month no calendar has, or lies outside the window altogether; the figure
    then carries no slice. Never raises."""
    try:
        if not (len(month) == 7 and month[4] == "-"):
            return None
        year, index = int(month[:4]), int(month[5:7])
        last = calendar.monthrange(year, index)[1]
    except (TypeError, ValueError):
        return None
    start, end = f"{month}-01", f"{month}-{last:02d}"
    for item in narrowed:
        if item["kind"] == BY_PERIOD:
            start, end = max(start, item["value"]), min(end, item["to"])
        elif item["kind"] == BY_SINCE:
            start = max(start, item["value"])
        elif item["kind"] == BY_UNTIL:
            end = min(end, item["value"])
    if start > end:
        return None
    return {"kind": BY_PERIOD, "value": start, "to": end}



__all__ = ['calendar', 'Decimal', 'lru_cache', 'quantity', 'render', 'networth', 'masked', 'normalize_merchant', 'UnknownAccountError', 'subcategory_group_key', 'movements_view', 'ACTIVITY', 'BY_ACCOUNT', 'BY_CATEGORY', 'BY_CURRENCY', 'BY_KIND', 'BY_MERCHANT', 'BY_PERIOD', 'BY_SINCE', 'BY_SUBCATEGORY', 'BY_TAG', 'BY_UNTIL', 'ENTITY_ACCOUNT', 'ENTITY_CATEGORY', 'ENTITY_MERCHANT', 'GAP_REFUSED', 'GAP_UNOBSERVED', 'ToolResult', 'bounded', 'cut_set', 'entity', 'figure', 'refusal', 'weakest', 'LIABILITY', 'REAL_KINDS', 'MAX_JOURNAL', 'MAX_ROWS', 'MAX_GROUPS', 'MAX_FOLDS', 'MAX_LABELS', 'UNNAMED_MERCHANT', 'COUNTS_WHAT_LEFT', 'MIXED_VINTAGE', '_mixed_vintage', 'QUERY_LEDGER_PARAMS', 'TOOL', '_real_accounts', '_measure_of', '_currencies', '_identifiers', '_merchant_key', '_merchant_filter_key', '_match_tier', '_merchants', '_categories', '_today', '_is_iso_date', '_known', 'MANY_BAD_FILTERS', '_check_filters', '_resolve_window_preset', '_in_window', '_movement_passes', '_attested_coverage', '_shared_currency', '_scope', '_of_an_empty_read', '_mixed_currencies', '_movement_row', '_FILTER_NAMES', '_GROUP_NAMES', '_PARTITIONING', '_narrowed_to', '_month_slice', '_SUPPORTED_FILTERS']
