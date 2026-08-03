"""The read tools: deterministic functions over the projection, wrapped in the
envelope. Every filter value is validated against the vault's own learned
vocabulary — its accounts, categories, tags, merchants and currencies — and an
unknown value is refused with the known values named, never silently ignored.

No tool here writes, calls a model, or touches the network; each reads the one
live projection it was built over.
"""

from __future__ import annotations

from decimal import Decimal

from ..ledger import networth
from ..ledger.projection import (MIXED, SETTLEMENT, SPENDING, TRANSFER,
                                 UnknownAccountError)
from ..ledger.projection import movements as movements_view
from .envelope import ToolResult, refusal, weakest
from .registry import Registry, ToolSpec

REAL_KINDS = ("depository", "liability", "investment")

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


def _movement_row(proj, m, grades: dict) -> dict:
    ruling = proj.derived_category(m) or {}
    return {"record_id": m.key, "account": m.account, "date": m.date,
            "description": m.description, "amount": str(m.amount),
            "currency": m.currency, "nature": m.nature,
            "nature_reason": m.nature_reason, "provisional": m.provisional,
            "category": ruling.get("category", ""),
            "subcategory": ruling.get("subcategory", ""),
            "tags": proj.tags_of(m), "grade": grades.get(m.key, ""),
            "provenance": m.provenance.to_dict()}


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
    return ToolResult(
        tool=TOOL, ok=True, data={"balances": rows},
        grade=weakest(r["grade"] for r in rows),
        dated=min((r["dated"] for r in rows if r["dated"]), default=""),
        record_ids=sorted(set(record_ids)),
        coverage=("Included: " + "; ".join(
            f"{r['name'] or r['record_id']} (as of {r['dated'] or 'unknown'}, "
            f"{r['grade']})" for r in rows)),
        text=f"{len(rows)} account balance(s), each with its grade and source.")


def _query_transactions(proj, filters: dict) -> ToolResult:
    grades = movements_view.movement_grades(proj.core)
    rows = [_movement_row(proj, m, grades) for m in proj.movements()
            if _movement_passes(proj, m, filters)]
    record_ids = sorted({r["provenance"]["doc_id"] for r in rows
                         if r["provenance"].get("doc_id")}
                        | {r["record_id"] for r in rows})
    covers, caveats = _attested_coverage(proj, filters)
    return ToolResult(
        tool=TOOL, ok=True,
        data={"transactions": rows, "count": len(rows)},
        grade=weakest(r["grade"] for r in rows),
        record_ids=record_ids, covers=covers, caveats=caveats,
        coverage=f"{len(rows)} movement(s) matched the filters.",
        text=f"{len(rows)} movement(s), each with nature, category and source.")


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
    return ToolResult(
        tool=TOOL, ok=True, data={"holdings": rows, "count": len(rows)},
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
              "grades": used_grades, "record_ids": sorted(record_ids)}
    return out, extras


def _aggregate_spending(proj, filters: dict, group_by: str) -> ToolResult:
    grouped, extras = _spending_rows(proj, filters, group_by)
    covers, span_caveats = _attested_coverage(proj, filters)
    currency = filters.get("currency")
    data = {"metric": "spending", "group_by": group_by,
            "by_group": {k: str(v) for k, v in sorted(grouped.items())},
            "total": str(extras["total"]), "count": extras["count"]}
    caveats = ["Own-account transfers and settlements are excluded by nature; "
               "card purchases are included."] + span_caveats
    if group_by == "tag":
        data["untagged"] = str(extras["untagged"])
        data["overlaps"] = True
        caveats.append("Tags overlap: the per-tag figures do not sum to the "
                       "total, and untagged money appears in no line.")
    uncategorized = grouped.get("Uncategorized")
    if group_by == "category" and uncategorized:
        caveats.append(f"{uncategorized} is still uncategorized.")
    provisional = proj.provisional_spending(currency)
    if provisional:
        caveats.append(f"{provisional} of this rests on provisional evidence "
                       "(a suggested implication, not a ruling).")
    undecided = proj.undecomposed(currency)
    if undecided["count"]:
        caveats.append(f"{undecided['total']} across {undecided['count']} "
                       "compound payment(s) has known components but unknown "
                       "proportions, and is reported apart, not counted here.")
    return ToolResult(
        tool=TOOL, ok=True, data=data,
        grade=weakest(extras["grades"]), covers=covers,
        record_ids=extras["record_ids"], caveats=caveats,
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
    return ToolResult(
        tool=TOOL, ok=True,
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
    return ToolResult(
        tool=TOOL, ok=True,
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


def query_ledger(proj, args: dict) -> ToolResult:
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
        return _aggregate_spending(proj, filters, args.get("group_by",
                                                           "category"))
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
    return ToolResult(
        tool="check_completeness", ok=True,
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
        return ToolResult(
            tool="get_provenance", ok=True, grade=ba.grade, dated=ba.dated,
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
        return ToolResult(
            tool="get_provenance", ok=True,
            grade=grades.get(match.key, ""), dated=match.date,
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


def get_transparency(proj, args: dict) -> ToolResult:
    topic = args["topic"]
    since = args.get("since", "")
    if since and not _is_iso_date(since):
        return refusal("get_transparency", "bad_date",
                       f"since must be an ISO date, got '{since}'.")
    if topic == "agent_activity":
        log = proj.agent_log()
        if since:
            log = [a for a in log
                   if str(a.get("occurred_at", ""))[:10] >= since]
        return ToolResult(
            tool="get_transparency", ok=True,
            data={"topic": topic, "actions": log, "count": len(log)},
            coverage="The complete unattended-action journal; nothing is "
                     "collapsed.",
            text=f"{len(log)} unattended action(s) on record.")
    if topic == "calls_spent":
        calls = proj.agent_calls_spent(since=since)
        return ToolResult(
            tool="get_transparency", ok=True,
            data={"topic": topic, "calls": calls, "since": since},
            caveats=["Counts only the maintenance agent's unattended calls; "
                     "a conversation's own model calls are recorded "
                     "separately."],
            text=(f"{calls} model call(s) spent by the agent"
                  + (f" since {since}." if since else " in total.")))
    declined = proj.declined_questions()
    return ToolResult(
        tool="get_transparency", ok=True,
        data={"topic": topic, "declined": declined, "count": len(declined)},
        text=f"{len(declined)} question(s) set aside.")
