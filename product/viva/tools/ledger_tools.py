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

from decimal import Decimal

from .. import quantity, render
from ..ledger import networth
from ..ledger.identity import masked
from ..ledger.projection import (MIXED, SETTLEMENT, SPENDING, TRANSFER,
                                 UnknownAccountError)
from ..ledger.projection import movements as movements_view
from .envelope import (ACTIVITY, ENTITY_ACCOUNT, ENTITY_CATEGORY,
                       ENTITY_MERCHANT, ToolResult, entity, figure, refusal,
                       weakest)
from .registry import Registry, ToolSpec

REAL_KINDS = ("depository", "liability", "investment")

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

QUERY_LEDGER_PARAMS = {
    "type": "object",
    "properties": {
        "entity": {"type": "string",
                   "enum": ["balances", "transactions", "holdings",
                            "aggregate"]},
        "metric": {"type": "string",
                   "enum": ["spending", "income", "net_worth"]},
        "group_by": {"type": "string",
                     "enum": ["category", "subcategory", "tag", "merchant",
                              "account", "currency"]},
        "as_of": {"type": "string"},
        "filters": {
            "type": "object",
            "properties": {
                "account": {"type": "string"},
                "category": {"type": "string"},
                "tag": {"type": "string"},
                "merchant": {"type": "string"},
                "nature": {"type": "string",
                           "enum": [SPENDING, TRANSFER, SETTLEMENT, MIXED]},
                "currency": {"type": "string"},
                "window": {"type": "object",
                           "properties": {"from": {"type": "string"},
                                          "to": {"type": "string"}}},
            },
        },
    },
    "required": ["entity"],
}

TOOL = "query_ledger"


def _real_accounts(proj) -> list:
    return [i for i in proj.account_infos() if i.kind in REAL_KINDS]


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


def _merchants(descriptors) -> list:
    """The counterparties this read spoke about, each as an entity.

    A movement's description is one of them: it names who the money went to,
    which is a thing rather than a magnitude, however many digits a statement
    happens to have written into it."""
    out, seen = [], set()
    for descriptor in descriptors:
        text = str(descriptor or "").strip()
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


def _is_iso_date(value: str) -> bool:
    """A structural YYYY-MM-DD check — lexical, like every date comparison in
    the projection."""
    return (isinstance(value, str) and len(value) >= 10 and value[4] == "-"
            and value[7] == "-"
            and value[:4].isdigit() and value[5:7].isdigit()
            and value[8:10].isdigit())


def _known(values, cap: int = 40) -> list:
    """A refusal's 'here is what I do have' list, capped so a large vocabulary
    stays readable; the count says what the cap hid."""
    out = sorted(v for v in values if v)
    if len(out) <= cap:
        return out
    return out[:cap] + [f"... and {len(out) - cap} more"]


def _check_filters(proj, filters: dict) -> ToolResult | None:
    """Refuse any filter value the vault does not hold; None when all pass."""
    if "account" in filters:
        held = set(proj.accounts())
        if filters["account"] not in held:
            return refusal(
                TOOL, "unknown_account",
                f"I don't have an account '{filters['account']}' on file.",
                known_accounts=_known(i.account for i in _real_accounts(proj)))
    if "category" in filters:
        known = set(proj.known_categories()) | {"Uncategorized"}
        if proj.canonical_category(filters["category"]) not in known:
            return refusal(
                TOOL, "unknown_category",
                f"No category '{filters['category']}' exists in this vault.",
                known_categories=_known(known))
    if "tag" in filters:
        known = set(proj.known_tags())
        if proj.canonical_tag(filters["tag"]) not in known:
            return refusal(TOOL, "unknown_tag",
                           f"No tag '{filters['tag']}' exists in this vault.",
                           known_tags=_known(known))
    if "merchant" in filters:
        known = ({proj.merchant_key_of(m) for m in proj.movements()}
                 | set(proj.merchant_categories()))
        if filters["merchant"] not in known:
            return refusal(TOOL, "unknown_merchant",
                           f"No counterparty '{filters['merchant']}' is on "
                           "file under that key.",
                           known_merchants=_known(known))
    if "currency" in filters:
        held = _currencies(proj)
        if filters["currency"] not in held:
            return refusal(TOOL, "unknown_currency",
                           f"No account holds '{filters['currency']}'.",
                           known_currencies=_known(held))
    window = filters.get("window", {})
    for edge in ("from", "to"):
        if edge in window and not _is_iso_date(window[edge]):
            return refusal(TOOL, "bad_date",
                           f"window.{edge} must be an ISO date (YYYY-MM-DD), "
                           f"got '{window[edge]}'.")
    return None


def _in_window(date: str, window: dict) -> bool:
    lo, hi = window.get("from", ""), window.get("to", "")
    return (not lo or date[:10] >= lo[:10]) and (not hi or date[:10] <= hi[:10])


def _movement_passes(proj, m, filters: dict) -> bool:
    if "account" in filters and m.account != filters["account"]:
        return False
    if "nature" in filters and m.nature != filters["nature"]:
        return False
    if "currency" in filters and m.currency != filters["currency"]:
        return False
    if "merchant" in filters and proj.merchant_key_of(m) != filters["merchant"]:
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


def _attested_coverage(proj, filters: dict) -> tuple[list, list]:
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
    scope = [named] if named else sorted(
        i.account for i in proj.account_infos() if i.kind)

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
            "description": m.description, "amount": str(m.amount),
            "currency": m.currency, "nature": m.nature,
            "nature_reason": m.nature_reason, "provisional": m.provisional,
            "category": ruling.get("category", ""),
            "subcategory": ruling.get("subcategory", ""),
            "tags": proj.tags_of(m), "grade": grades.get(m.key, ""),
            "doc_id": m.provenance.doc_id}


def _query_balances(proj, filters: dict) -> ToolResult:
    infos = _real_accounts(proj)
    if "account" in filters:
        infos = [i for i in infos if i.account == filters["account"]]
        if not infos:
            # The account exists (the vocabulary check passed) but is not a
            # balance-holding account — a category bucket, for instance.
            return refusal(TOOL, "not_a_balance_account",
                           f"'{filters['account']}' is not an account that "
                           "holds a balance.",
                           known_accounts=_known(
                               i.account for i in _real_accounts(proj)))
    if "currency" in filters:
        infos = [i for i in infos if i.currency == filters["currency"]]
    rows, record_ids = [], []
    for info in infos:
        ba = proj.balance(info.account)
        row = ba.to_dict()
        row.update({"record_id": info.account, "name": info.name,
                    "kind": info.kind, "value": str(proj.account_value(info.account))})
        rows.append(row)
        record_ids.append(info.account)
        if ba.provenance.doc_id:
            record_ids.append(ba.provenance.doc_id)
    if not rows:
        return refusal(TOOL, "no_accounts",
                       "I don't have any balance-holding accounts on file yet.")
    figures = [figure(r["value"], f"{r['name'] or r['record_id']} — balance",
                      quantity=quantity.BALANCE,
                      grade=r["grade"], dated=r["dated"], currency=r["currency"],
                      record_ids=[r["record_id"]]
                      + ([r["provenance"]["doc_id"]]
                         if r["provenance"].get("doc_id") else []))
               for r in rows]
    figures.append(figure(len(rows), "accounts holding a balance",
                          quantity=quantity.COUNT,
                          grade=weakest(r["grade"] for r in rows),
                          record_ids=sorted({r["record_id"] for r in rows})))
    return ToolResult(
        tool=TOOL, ok=True, figures=figures,
        identifiers=_identifiers(proj, (r["record_id"] for r in rows)),
        # The amount, its grade, its currency and its as-of date travel as
        # figures. What stays here is what a figure cannot carry: which account
        # this is, and why its grade is what it is.
        data={"balances": [{k: v for k, v in r.items()
                            if k not in ("amount", "currency", "grade",
                                         "dated", "value", "as_of")}
                           for r in rows]},
        grade=weakest(r["grade"] for r in rows),
        dated=min((r["dated"] for r in rows if r["dated"]), default=""),
        record_ids=sorted(set(record_ids)),
        coverage=("Included: " + "; ".join(
            f"{r['name'] or r['record_id']} (as of {r['dated'] or 'unknown'}, "
            f"{r['grade']})" for r in rows)),
        text=f"{len(rows)} account balance(s), each with its grade and source.")


def _matching_rows(proj, filters: dict) -> tuple[list, dict]:
    grades = movements_view.movement_grades(proj.core)
    return ([_movement_row(proj, m, grades) for m in proj.movements()
             if _movement_passes(proj, m, filters)], grades)


def _query_transactions(proj, filters: dict) -> ToolResult:
    """What the movements add up to, never the movements themselves.

    How much moved, where and when. The rows themselves are `list_movements`,
    which answers only a narrower ask."""
    rows, _ = _matching_rows(proj, filters)
    held = _shared_currency(r["currency"] for r in rows)
    if held is None:
        return _mixed_currencies(TOOL, {r["currency"] for r in rows
                                        if r["currency"]})
    # A summary stands on the documents that attest the period and on the
    # accounts it ranged over, not on every movement inside it. Per-movement
    # keys belong to the read that returns individual rows.
    record_ids = sorted({r["doc_id"] for r in rows if r["doc_id"]}
                        | {r["account"] for r in rows})
    currency = held or str(filters.get("currency") or "")
    if not rows:
        currency, record_ids = _of_an_empty_read(proj, filters)
    covers, caveats = _attested_coverage(proj, filters)
    money_in = sum((Decimal(r["amount"]) for r in rows
                    if Decimal(r["amount"]) > 0), Decimal("0"))
    money_out = sum((-Decimal(r["amount"]) for r in rows
                     if Decimal(r["amount"]) < 0), Decimal("0"))
    by_account: dict[str, Decimal] = {}
    by_month: dict[str, Decimal] = {}
    month_docs: dict[str, set] = {}
    for r in rows:
        amount = Decimal(r["amount"])
        by_account[r["account"]] = by_account.get(r["account"],
                                                  Decimal("0")) + amount
        month = r["date"][:7]
        by_month[month] = by_month.get(month, Decimal("0")) + amount
        if r["doc_id"]:
            month_docs.setdefault(month, set()).add(r["doc_id"])
    grade = weakest(r["grade"] for r in rows)
    figures = [
        figure(len(rows), "movements matching the filters",
               quantity=quantity.COUNT, grade=grade, record_ids=record_ids),
        # Summed by the sign of the posting, which is why neither of these
        # claims a direction: what a positive posting means depends on the
        # account it sits on, and that is not established here.
        figure(money_in, "money in over these movements",
               quantity=quantity.GROSS_FLOW, grade=grade,
               currency=currency, record_ids=record_ids),
        figure(money_out, "money out over these movements",
               quantity=quantity.GROSS_FLOW, grade=grade,
               currency=currency, record_ids=record_ids),
        figure(money_in - money_out, "net movement over this set",
               quantity=quantity.NET_MOVEMENT, grade=grade,
               currency=currency, record_ids=record_ids),
        # The divisor a per-month average over this set is computed with.
        # Arithmetic takes figure ids, so a count that lives only in the
        # payload cannot be divided by.
        figure(len(by_month), "months these movements span",
               quantity=quantity.COUNT, grade=grade, record_ids=record_ids),
    ]
    figures += [figure(v, f"net movement on {k}",
                       quantity=quantity.NET_MOVEMENT, grade=grade,
                       currency=currency, record_ids=[k])
                for k, v in sorted(by_account.items())]
    figures += [figure(v, f"net movement in {k}",
                       quantity=quantity.NET_MOVEMENT, grade=grade,
                       currency=currency,
                       record_ids=sorted(month_docs.get(k, ())))
                for k, v in sorted(by_month.items())]
    return ToolResult(
        tool=TOOL, ok=True,
        identifiers=_identifiers(proj, [i.account for i in _scope(proj, filters)]),
        # The breakdown itself is the figures; `data` carries only the counts
        # and the totals, never a second copy of them.
        data={"count": len(rows), "money_in": str(money_in),
              "money_out": str(money_out), "net": str(money_in - money_out),
              "accounts": len(by_account), "months": len(by_month)},
        figures=figures, grade=grade,
        record_ids=record_ids, covers=covers, caveats=caveats,
        coverage=f"{len(rows)} movement(s) matched the filters.",
        text=("A summary of the matching movements; ask list_movements for the "
              "individual rows, narrowed to what you want to see."))


LIST_MOVEMENTS_PARAMS = {
    "type": "object",
    "properties": {
        "filters": QUERY_LEDGER_PARAMS["properties"]["filters"],
    },
}

# What one row says: what identifies the movement and what it was ruled to be.
# The reasoning behind the ruling is what `get_provenance` answers for.
ROW_FIELDS = ("record_id", "account", "date", "description", "amount",
              "currency", "nature", "category", "subcategory", "tags",
              "grade", "doc_id")

LIST_TOOL = "list_movements"

# The filters that narrow a detailed read; at least one is required. `nature`
# and `currency` are not among them, because either usually matches most of the
# ledger.
NARROWING = ("account", "category", "merchant", "tag", "window")


def _as_tool(result: ToolResult, tool: str) -> ToolResult:
    """The same refusal, attributed to the verb that was actually called. The
    vocabulary checks are shared between the reads."""
    result.tool = tool
    return result


def list_movements(proj, args: dict) -> ToolResult:
    """The individual rows, for a question narrow enough to name what it is
    about. A call carrying none of `NARROWING` refuses as `too_broad`."""
    filters = args.get("filters") or {}
    if not any(f in filters for f in NARROWING):
        return refusal(
            LIST_TOOL, "too_broad",
            "Listing every movement held would answer no question. Narrow it "
            "by " + ", ".join(NARROWING) + ".",
            narrowing_filters=list(NARROWING))
    bad = _check_filters(proj, filters)
    if bad is not None:
        return _as_tool(bad, LIST_TOOL)
    extra = sorted(set(filters) - _SUPPORTED_FILTERS[LIST_TOOL])
    if extra:
        return refusal(LIST_TOOL, "filter_unsupported",
                       f"{LIST_TOOL} does not answer by {', '.join(extra)}.",
                       supported_filters=sorted(_SUPPORTED_FILTERS[LIST_TOOL]))
    rows, _ = _matching_rows(proj, filters)
    total = len(rows)
    shown = [{k: r[k] for k in ROW_FIELDS} for r in rows[:MAX_ROWS]]
    record_ids = sorted({r["doc_id"] for r in shown if r["doc_id"]}
                        | {r["record_id"] for r in shown})
    covers, caveats = _attested_coverage(proj, filters)
    figures = [figure(r["amount"], f"{r['description']} on {r['date']}",
                      quantity=quantity.MOVEMENT,
                      grade=r["grade"], dated=r["date"], currency=r["currency"],
                      record_ids=[r["record_id"]]
                      + ([r["doc_id"]] if r["doc_id"] else []))
               for r in shown]
    # A capped result says so in the sentence the tool itself writes: how many
    # of how many were shown, and which filters would reach the rest.
    coverage = f"Showing {len(shown)} of {total} matching movement(s)."
    if total > len(shown):
        coverage += (" Narrow by " + ", ".join(NARROWING)
                     + " to see the rest.")
    return ToolResult(
        tool=LIST_TOOL, ok=True, data={"movements": shown, "shown": len(shown),
                                       "total": total},
        figures=figures,
        identifiers=(_identifiers(proj, (r["account"] for r in shown))
                     + _merchants(r["description"] for r in shown)),
        grade=weakest(r["grade"] for r in shown),
        record_ids=record_ids, covers=covers, caveats=caveats,
        coverage=coverage, text=coverage)



def _query_holdings(proj, filters: dict) -> ToolResult:
    rows = [p.to_dict() for p in proj.positions(filters.get("account"))]
    for row in rows:
        row["record_id"] = f"{row['account']}|{row['instrument']}"
    if "currency" in filters:
        rows = [r for r in rows if r["currency"] == filters["currency"]]
    record_ids = sorted({r["provenance"]["doc_id"] for r in rows
                         if r["provenance"].get("doc_id")}
                        | {r["record_id"] for r in rows})
    caveats = ["Each holding is a dated measurement from a statement, never "
               "a current price."]
    figures = [figure(r["market_value"], f"{r['instrument']} — measured value",
                      quantity=quantity.BALANCE,
                      grade=r["grade"], dated=r["as_of"], currency=r["currency"],
                      record_ids=[r["record_id"]]
                      + ([r["provenance"]["doc_id"]]
                         if r["provenance"].get("doc_id") else []))
               for r in rows]
    figures.append(figure(len(rows), "measured holdings",
                          quantity=quantity.COUNT,
                          grade=weakest(r["grade"] for r in rows),
                          record_ids=sorted({r["record_id"] for r in rows})))
    return ToolResult(
        tool=TOOL, ok=True, data={"holdings": rows, "count": len(rows)},
        figures=figures, identifiers=_identifiers(
            proj, (r["account"] for r in rows)),
        grade=weakest(r["grade"] for r in rows),
        dated=min((r["as_of"] for r in rows if r["as_of"]), default=""),
        record_ids=record_ids, caveats=caveats,
        coverage=f"{len(rows)} holding(s) from the latest statement snapshots.",
        text=f"{len(rows)} measured holding(s).")


def _spending_rows(proj, filters: dict, group_by: str) -> tuple[dict, dict]:
    """(grouped totals, extras) over movements passing the filters. Tags
    overlap, so that grouping also returns untagged and total."""
    grades = movements_view.movement_grades(proj.core)
    out: dict[str, Decimal] = {}
    used_grades: list = []
    record_ids: set = set()
    currencies: set = set()
    untagged = total = Decimal("0")
    count = 0
    for m in proj.movements():
        if not proj._counts_as_spending(m):
            continue
        if not _movement_passes(proj, m, filters):
            continue
        amount = abs(m.amount)
        total += amount
        count += 1
        currencies.add(m.currency)
        used_grades.append(grades.get(m.key, ""))
        if m.provenance.doc_id:
            record_ids.add(m.provenance.doc_id)
        if group_by == "tag":
            tags = proj.tags_of(m)
            if not tags:
                untagged += amount
            for tag in tags:
                out[tag] = out.get(tag, Decimal("0")) + amount
            continue
        if group_by == "category":
            key = (proj.derived_category(m) or {}).get("category",
                                                       "Uncategorized")
        elif group_by == "subcategory":
            ruling = proj.derived_category(m) or {}
            key = (ruling.get("subcategory") or ruling.get("category")
                   or "Uncategorized")
        elif group_by == "merchant":
            key = proj.merchant_key_of(m) or m.description
        elif group_by == "account":
            key = m.account
        else:
            key = m.currency or "?"
        out[key] = out.get(key, Decimal("0")) + amount
    extras = {"total": total, "count": count, "untagged": untagged,
              "grades": used_grades, "record_ids": sorted(record_ids),
              "currencies": {c for c in currencies if c}}
    return out, extras


def _largest_groups(grouped: dict) -> tuple[dict, dict]:
    """The groups an aggregate names, and the tail it did not.

    Ordered by magnitude, ties broken by name, so two reads of one ledger name
    the same groups. The tail carries how many groups it holds and what they
    are worth together."""
    ranked = sorted(grouped.items(), key=lambda kv: (-kv[1], kv[0]))
    return (dict(ranked[:MAX_GROUPS]),
            {"count": len(ranked[MAX_GROUPS:]),
             "total": sum((v for _, v in ranked[MAX_GROUPS:]), Decimal("0"))})


def _aggregate_spending(proj, filters: dict, group_by: str,
                        locale: str = "") -> ToolResult:
    grouped, extras = _spending_rows(proj, filters, group_by)
    named, tail = _largest_groups(grouped)
    held = _shared_currency(extras["currencies"])
    if held is None:
        return _mixed_currencies(TOOL, extras["currencies"])
    # The currency the counted movements are in, which is what the totals are
    # amounts of. The filter is what narrowed the read, and answers for the
    # caveats' own scope.
    currency = held or str(filters.get("currency") or "")
    record_ids = extras["record_ids"]
    if not extras["count"]:
        currency, record_ids = _of_an_empty_read(proj, filters)
    covers, span_caveats = _attested_coverage(proj, filters)
    data = {"metric": "spending", "group_by": group_by,
            "by_group": {k: str(v) for k, v in sorted(named.items())},
            "groups": {"named": len(named), "total": len(grouped)},
            "total": str(extras["total"]), "count": extras["count"]}
    caveats = ["Own-account transfers and settlements are excluded by nature; "
               "card purchases are included."] + span_caveats
    if group_by == "tag":
        data["untagged"] = str(extras["untagged"])
        data["overlaps"] = True
        caveats.append("Tags overlap: the per-tag figures do not sum to the "
                       "total, and untagged money appears in no line.")
    # An amount inside a caveat is an amount, and is written by the one
    # renderer that writes every other one. A caveat is passed on verbatim, so
    # a figure it spelled for itself would be the sentence under the answer
    # disagreeing with the answer about how this person's money is written.
    def amount(value) -> str:
        return str(render.money(value, currency, locale=locale))

    uncategorized = grouped.get("Uncategorized")
    if group_by == "category" and uncategorized:
        caveats.append(f"{amount(uncategorized)} is still uncategorized.")
    provisional = proj.provisional_spending(filters.get("currency"))
    if provisional:
        caveats.append(f"{amount(provisional)} of this rests on provisional "
                       "evidence (a suggested implication, not a ruling).")
    undecided = proj.undecomposed(filters.get("currency"))
    if undecided["count"]:
        caveats.append(f"{amount(undecided['total'])} across "
                       f"{undecided['count']} compound payment(s) has known "
                       "components but unknown proportions, and is reported "
                       "apart, not counted here.")
    # What the cap dropped is a caveat, like everything else this read says its
    # own numbers do not cover: it carries an identity, it can be placed in a
    # sentence, and a figure it sits behind cannot be stated without it.
    if tail["count"]:
        caveats.append(f"The largest {len(named)} of {len(grouped)} "
                       f"{group_by} group(s) are named here, plus "
                       f"{tail['count']} smaller group(s) worth "
                       f"{amount(tail['total'])} in total.")
    grade = weakest(extras["grades"])
    figures = [figure(v, f"spending — {group_by} '{k}'",
                      quantity=quantity.SPENDING, grade=grade,
                      currency=currency, record_ids=record_ids)
               for k, v in sorted(named.items())]
    figures.append(figure(extras["total"], f"total spending by {group_by}",
                          quantity=quantity.SPENDING,
                          grade=grade, currency=currency,
                          record_ids=record_ids))
    figures.append(figure(extras["count"], "spending movements counted",
                          quantity=quantity.COUNT,
                          grade=grade, record_ids=record_ids))
    # What a spending read groups by is a thing it spoke about — a category, a
    # counterparty, an account — and an answer refers to it rather than
    # spelling it.
    grouped_entities = (_categories(named)
                        if group_by in ("category", "subcategory")
                        else _merchants(named) if group_by == "merchant"
                        else [])
    return ToolResult(
        tool=TOOL, ok=True, data=data, figures=figures,
        identifiers=(_identifiers(proj, [i.account
                                         for i in _scope(proj, filters)])
                     + grouped_entities),
        grade=grade, covers=covers,
        record_ids=record_ids, caveats=caveats,
        coverage=f"{extras['count']} spending movement(s) counted.",
        text=f"Spending by {group_by}: total {extras['total']}.")


def _aggregate_income(proj, filters: dict) -> ToolResult:
    by_currency = proj.income_by_currency()
    if "currency" in filters:
        by_currency = {k: v for k, v in by_currency.items()
                       if k == filters["currency"]}
    sources = sorted(a for a in proj.accounts()
                     if a.startswith("Income:") and a != "Income:Uncategorized")
    line_grades = [ln.grade for a in sources for ln in proj.transactions(a)]
    figures = [figure(v, f"attributed income in {k}, over everything ingested",
                      quantity=quantity.INCOME,
                      grade=weakest(line_grades), currency=k,
                      record_ids=sources)
               for k, v in sorted(by_currency.items())]
    return ToolResult(
        tool=TOOL, ok=True, figures=figures,
        data={"metric": "income",
              "by_currency": {k: str(v) for k, v in sorted(by_currency.items())}},
        grade=weakest(line_grades),
        record_ids=sources,
        caveats=["Attributed income only; inflows nothing has attributed are "
                 "not counted as income.",
                 "A lifetime figure over everything ingested — income does "
                 "not answer by date window yet."],
        coverage=("Summed from: " + "; ".join(sources)) if sources else "",
        text="Attributed income per currency, over everything ingested.")


def _grades_in(value) -> list:
    """Every 'grade' value anywhere in a nested payload."""
    out = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "grade" and isinstance(v, str):
                out.append(v)
            else:
                out.extend(_grades_in(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(_grades_in(v))
    return out


def _aggregate_net_worth(proj, as_of: str | None) -> ToolResult:
    point = networth.net_worth(proj, as_of)
    data = point.to_dict()
    record_ids = sorted({line.get("account", "") for line in
                         (data.get("lines") or []) if line.get("account")})
    as_of = data.get("as_of", "")
    figures = []
    for currency, row in sorted(data.get("by_currency", {}).items()):
        for part in ("net", "assets", "liabilities"):
            # What is held less what is owed is net worth; each side of it on
            # its own is a total of balances, and saying so keeps a hole that
            # asked for one from being filled with the other.
            figures.append(figure(row[part], f"{part} in {currency}",
                                  quantity=(quantity.NET_WORTH if part == "net"
                                            else quantity.BALANCE),
                                  grade=weakest(_grades_in(data)),
                                  dated=as_of, currency=currency,
                                  record_ids=record_ids))
    figures += [figure(line["amount"], f"{line['account']} — its part of net worth",
                       quantity=quantity.BALANCE,
                       grade=line.get("grade", ""), dated=line.get("as_of", ""),
                       currency=line.get("currency", ""),
                       record_ids=[line["account"]])
                for line in (data.get("lines") or []) if line.get("account")]
    return ToolResult(
        tool=TOOL, ok=True, figures=figures,
        identifiers=_identifiers(proj, record_ids),
        data={"metric": "net_worth", "point": data},
        grade=weakest(_grades_in(data)),
        dated=data.get("as_of", ""),
        record_ids=record_ids,
        caveats=["Each line is only as current as its stalest input; see the "
                 "point's own staleness fields."],
        text=f"Net worth as of {data.get('as_of', 'unknown')}.")


# Which filters each read honors. A filter an entity would ignore is refused,
# never accepted-and-dropped: rows that are individually true still answer the
# wrong question when the set was never narrowed.
_SUPPORTED_FILTERS = {
    "balances": {"account", "currency"},
    "transactions": {"account", "category", "tag", "merchant", "nature",
                     "currency", "window"},
    "list_movements": {"account", "category", "tag", "merchant", "nature",
                       "currency", "window"},
    "holdings": {"account", "currency"},
    "aggregate:spending": {"account", "category", "tag", "merchant", "nature",
                           "currency", "window"},
    "aggregate:income": {"currency"},
    "aggregate:net_worth": set(),
}


def _unsupported_filters(kind: str, filters: dict) -> ToolResult | None:
    supported = _SUPPORTED_FILTERS[kind]
    extra = sorted(set(filters) - supported)
    if not extra:
        return None
    return refusal(
        TOOL, "filter_unsupported",
        f"{kind} does not answer by {', '.join(extra)}; "
        + (f"it filters by {', '.join(sorted(supported))} only."
           if supported else "it takes no filters."),
        supported_filters=sorted(supported))


def query_ledger(proj, args: dict, locale: str = "") -> ToolResult:
    filters = args.get("filters", {})
    bad = _check_filters(proj, filters)
    if bad is not None:
        return bad
    entity = args["entity"]
    kind = (f"aggregate:{args['metric']}"
            if entity == "aggregate" and args.get("metric") else entity)
    if kind in _SUPPORTED_FILTERS:
        bad = _unsupported_filters(kind, filters)
        if bad is not None:
            return bad
    if "as_of" in args:
        if not _is_iso_date(args["as_of"]):
            return refusal(TOOL, "bad_date",
                           f"as_of must be an ISO date, got '{args['as_of']}'.")
        if not (entity == "aggregate" and args.get("metric") == "net_worth"):
            return refusal(TOOL, "as_of_unsupported",
                           "as_of applies to the net_worth metric; other "
                           "reads answer from the latest evidence.")
    if entity == "balances":
        return _query_balances(proj, filters)
    if entity == "transactions":
        return _query_transactions(proj, filters)
    if entity == "holdings":
        return _query_holdings(proj, filters)
    # aggregate
    metric = args.get("metric")
    if not metric:
        return refusal(TOOL, "missing_metric",
                       "entity 'aggregate' needs a metric: spending, income, "
                       "or net_worth.")
    if metric == "spending":
        return _aggregate_spending(proj, filters,
                                   args.get("group_by", "category"), locale)
    if metric == "income":
        return _aggregate_income(proj, filters)
    return _aggregate_net_worth(proj, args.get("as_of"))


# ---------------------------------------------------------- check_completeness

def check_completeness(proj, args: dict) -> ToolResult:
    captured = proj.captured_docs()
    posted_ids = proj.posted_doc_ids()
    held = [did for did in captured if did not in posted_ids]
    awaiting_types: dict[str, int] = {}
    for did in held:
        awaiting_types[captured[did]] = awaiting_types.get(captured[did], 0) + 1
    accounts = []
    for info in _real_accounts(proj):
        ba = proj.balance(info.account)
        accounts.append({"account": info.account, "name": info.name,
                         "kind": info.kind, "dated": ba.dated,
                         "grade": ba.grade})
    tiers = {k: {"count": v["count"], "amount": str(v["amount"]),
                 "merchants": v["merchants"]}
             for k, v in sorted(proj.tier_summary().items())}
    unidentified = len(proj.uncategorized_merchants())
    holds = [{"doc_id": b.get("doc_id", ""), "reason": b.get("reason", "")}
             for b in proj.open_holds()]
    caveats = []
    if holds:
        caveats.append(f"{len(holds)} document(s) are held awaiting review "
                       "and are not in any figure.")
    if unidentified:
        caveats.append(f"{unidentified} counterparty(ies) are not yet "
                       "identified, so their categories are unknown.")
    all_docs = sorted(captured)
    figures = [
        figure(len(captured), "documents held", quantity=quantity.COUNT,
               record_ids=all_docs),
        figure(len(captured) - len(held), "documents posted to the ledger",
               quantity=quantity.COUNT, record_ids=all_docs),
        figure(len(held), "documents awaiting review", quantity=quantity.COUNT,
               record_ids=all_docs),
        figure(unidentified, "counterparties not yet identified",
               quantity=quantity.COUNT, record_ids=all_docs),
    ]
    # A day, which is a point in time and not a magnitude: it fills no hole
    # that asks for an amount, a count or a proportion.
    figures += [figure(a["dated"], f"{a['name'] or a['account']} — the date "
                       "its evidence is good as of",
                       quantity=quantity.TIME,
                       grade=a["grade"], dated=a["dated"],
                       record_ids=[a["account"]])
                for a in accounts if a["dated"]]
    return ToolResult(
        tool="check_completeness", ok=True, figures=figures,
        identifiers=_identifiers(proj, (a["account"] for a in accounts)),
        data={"documents_held": len(captured), "posted": len(captured) - len(held),
              "awaiting": len(held), "awaiting_types": awaiting_types,
              "holds": holds, "accounts": accounts, "tiers": tiers,
              "unidentified_counterparties": unidentified},
        record_ids=sorted(captured),
        caveats=caveats,
        coverage="Every captured document and every balance-holding account.",
        text=(f"{len(captured)} document(s) held; {len(captured) - len(held)} "
              f"posted; {len(held)} awaiting review."))


# ------------------------------------------------------------- get_provenance

PROVENANCE_PARAMS = {"type": "object",
                     "properties": {"record_id": {"type": "string"}},
                     "required": ["record_id"]}


def get_provenance(proj, args: dict) -> ToolResult:
    rid = args["record_id"]
    captured = proj.captured_docs()
    if rid in captured:
        # posted: its figures are in the ledger. held: read but set aside,
        # awaiting review. captured: received and not yet processed.
        state = ("posted" if rid in proj.posted_doc_ids()
                 else "held" if proj.is_resolved(rid) else "captured")
        return ToolResult(
            tool="get_provenance", ok=True, record_ids=[rid],
            data={"kind": "document", "doc_id": rid,
                  "doc_type": captured[rid], "state": state},
            text=f"Document {rid}: a {captured[rid]}, {state}.")
    if proj.seen_account(rid):
        ba = proj.balance(rid)
        ids = [rid] + ([ba.provenance.doc_id] if ba.provenance.doc_id else [])
        return ToolResult(
            tool="get_provenance", ok=True, grade=ba.grade, dated=ba.dated,
            figures=[figure(proj.account_value(rid), f"{rid} — balance",
                            quantity=quantity.BALANCE,
                            grade=ba.grade, dated=ba.dated,
                            currency=ba.currency, record_ids=ids)],
            identifiers=_identifiers(proj, [rid]),
            record_ids=[rid] + ([ba.provenance.doc_id]
                                if ba.provenance.doc_id else []),
            provenance=[ba.provenance.to_dict()],
            data={"kind": "account", "account": rid,
                  "explanation": ba.explanation,
                  "reconciliation": (ba.reconciliation.explain()
                                     if ba.reconciliation else None)},
            text=ba.explanation)
    match = next((m for m in proj.movements() if m.key == rid), None)
    if match is not None:
        grades = movements_view.movement_grades(proj.core)
        ids = [match.key] + ([match.provenance.doc_id]
                             if match.provenance.doc_id else [])
        return ToolResult(
            tool="get_provenance", ok=True,
            grade=grades.get(match.key, ""), dated=match.date,
            figures=[figure(match.amount,
                            f"{match.description} on {match.date}",
                            quantity=quantity.MOVEMENT,
                            grade=grades.get(match.key, ""), dated=match.date,
                            currency=match.currency, record_ids=ids)],
            identifiers=_identifiers(proj, [match.account]),
            record_ids=[match.key] + ([match.provenance.doc_id]
                                      if match.provenance.doc_id else []),
            provenance=[match.provenance.to_dict()],
            data={"kind": "movement",
                  "movement": _movement_row(proj, match, grades)},
            text=(f"Movement of {match.amount} on {match.date}: nature "
                  f"'{match.nature}', decided by rung '{match.nature_reason}'."))
    return refusal("get_provenance", "unknown_record",
                   f"'{rid}' names no document, account or movement I hold.",
                   accepted=["a doc_id from check_completeness",
                             "an account id from query_ledger balances",
                             "a movement record_id from query_ledger "
                             "transactions"])


# ----------------------------------------------------------- get_transparency

TRANSPARENCY_PARAMS = {
    "type": "object",
    "properties": {"topic": {"type": "string",
                             "enum": ["agent_activity", "calls_spent",
                                      "declined_questions"]},
                   "since": {"type": "string"}},
    "required": ["topic"]}


# What one journal entry says: when, what fired, on what, how it went, what it
# cost. The evidence behind it and the artifact it produced are not here.
JOURNAL_FIELDS = ("occurred_at", "rule", "target", "outcome", "calls")


def _event_ids(entries) -> list:
    """The ledger events behind a journal read, in order and deduplicated."""
    return sorted({e["event_id"] for e in entries if e.get("event_id")})


def get_transparency(proj, args: dict) -> ToolResult:
    topic = args["topic"]
    since = args.get("since", "")
    if since and not _is_iso_date(since):
        return refusal("get_transparency", "bad_date",
                       f"since must be an ISO date, got '{since}'.")
    # Every number here is a claim about the agent rather than about the
    # person's money, and stands on the ledger events that recorded the
    # behaviour.
    if topic == "agent_activity":
        log = proj.agent_log()
        if since:
            log = [a for a in log
                   if str(a.get("occurred_at", ""))[:10] >= since]
        # The journal is append-only, so this is the one read whose size grows
        # with time. The most recent entries are shown and the count answers for
        # the rest.
        shown = [{k: a[k] for k in JOURNAL_FIELDS if k in a}
                 for a in log[-MAX_JOURNAL:]]
        events = _event_ids(log)
        said = f"{len(shown)} of {len(log)} unattended action(s) on record"
        said += (", the most recent." if len(shown) < len(log)
                 else "; nothing is collapsed.")
        if len(shown) < len(log):
            said += " Narrow with since to see a different period."
        return ToolResult(
            tool="get_transparency", ok=True,
            data={"topic": topic, "actions": shown, "shown": len(shown),
                  "count": len(log)},
            figures=[figure(len(log), "unattended actions on record",
                            quantity=quantity.COUNT,
                            kind=ACTIVITY, record_ids=events)],
            record_ids=events, coverage=said, text=said)
    if topic == "calls_spent":
        log = [a for a in proj.agent_log()
               if not since or str(a.get("occurred_at", ""))[:10] >= since]
        calls = proj.agent_calls_spent(since=since)
        events = _event_ids(log)
        return ToolResult(
            tool="get_transparency", ok=True,
            data={"topic": topic, "calls": calls, "since": since},
            figures=[figure(calls, "model calls the agent spent on its own",
                            quantity=quantity.COUNT,
                            kind=ACTIVITY, record_ids=events)],
            record_ids=events,
            caveats=["Counts only the maintenance agent's unattended calls; "
                     "a conversation's own model calls are recorded "
                     "separately."],
            text=(f"{calls} model call(s) spent by the agent"
                  + (f" since {since}." if since else " in total.")))
    declined = proj.declined_questions()
    events = _event_ids(declined.values())
    return ToolResult(
        tool="get_transparency", ok=True,
        data={"topic": topic, "declined": declined, "count": len(declined)},
        figures=[figure(len(declined), "questions set aside",
                        quantity=quantity.COUNT,
                        kind=ACTIVITY, record_ids=events)],
        record_ids=events,
        text=f"{len(declined)} question(s) set aside.")
