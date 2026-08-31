"""Balance and movement ledger reads."""

from __future__ import annotations

from .ledger_common import *

def _query_balances(proj, filters: dict) -> ToolResult:
    infos = _real_accounts(proj)
    # How many balance-holding accounts this person has, before any filter
    # narrows the read. It is what a per-account figure is one of, so it is
    # taken while it still means that.
    holds = len(infos)
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
    if "kind" in filters:
        infos = [i for i in infos if i.kind == filters["kind"]]
    selected_infos = list(infos)
    # An asserted loan account exists, but until a balance or dated holding has
    # been observed its replay value of zero is only the additive identity. It
    # is not evidence that nothing is owed. Keep such accounts in the boundary
    # and identifiers, but emit no monetary figure for them.
    infos = [i for i in infos
             if i.origin != "asserted"
             or _has_measured_value(proj, i.account)]
    if "account" in filters and selected_infos and not infos:
        return refusal(
            TOOL, "balance_unobserved",
            f"No balance has been observed for '{filters['account']}'. The "
            "account exists, but zero would mean 'nothing owed or held' and "
            "the ledger has not established that.",
            known_accounts=_known(i.account for i in _real_accounts(proj)))
    # What narrowed this read. Whether a figure is whole is read off this same
    # list, so the two cannot disagree: `bounded` refuses a figure that claims
    # to cover everything while also naming what it leaves out.
    narrowed = _narrowed_to(proj, filters)
    rows, record_ids, values = [], [], []
    # The accounts that came back as more than one value.
    in_parts: set = set()
    for info in infos:
        ba = proj.balance(info.account)
        row = ba.to_dict()
        row.update({"record_id": info.account, "name": info.name,
                    "kind": info.kind,
                    # Requested-field coverage for account-list questions.
                    # These are attributes of the same emitted figure, not a
                    # second monetary claim hidden in the payload.
                    "latest_evidence_date": ba.dated,
                    "evidence_grade": ba.grade,
                    "evidence_limitation": ba.explanation})
        rows.append(row)
        record_ids.append(info.account)
        if ba.provenance.doc_id:
            record_ids.append(ba.provenance.doc_id)
        # What the account is worth as one figure. An investment account's cash
        # and the holdings its latest statement measured are one thing a person
        # owns, so they are one value, dated by the oldest measurement under it
        # and graded by the weakest of them rather than by its cash alone.
        # Holdings in a currency the cash is not in stay a figure of their own,
        # because nothing here converts between currencies.
        composed = proj.composed_values(info.account)
        if len(composed) > 1:
            in_parts.add(info.account)
        values.extend((row, value) for value in composed)
    if not rows:
        return refusal(TOOL, "no_accounts",
                       "I don't have any measured account balances on file yet.")
    # One account's balance is one account's balance, whatever it is asked for:
    # it covers one of the accounts held, and it says so where the whole of
    # them is more than one, and names which one it is either way — beside
    # whatever narrowed the read, because the figure is the overlap of the two.
    # The count covers as many as this read ranged over, which is whatever the
    # filters left, so it names that and nothing further. An
    # account someone is owed on measures what is owed rather than what is
    # held, and both the word it is written under and the kind it declares say
    # so.
    #
    # An account that came back as more than one value is not the whole of what
    # any one of them ranges over: each is a part of the account, so none of
    # them declares itself the whole however few accounts are held.
    figures = [figure(value.amount,
                      f"{r['name'] or r['record_id']} — {_measure_of(r['kind'])}",
                      quantity=_measure_of(r["kind"]),
                      grade=value.grade, dated=value.as_of,
                      currency=value.currency,
                      record_ids=[r["record_id"]]
                      + ([value.proves] if value.proves else []),
                      boundary=bounded(whole=(not narrowed and holds == 1
                                              and r["record_id"]
                                              not in in_parts),
                                       counted=1, held=holds,
                                       selected=narrowed,
                                       cut=cut_set(narrowed,
                                                   {"kind": BY_ACCOUNT,
                                                    "value": r["record_id"]})))
               for r, value in values]
    # Kind-filtered balances include one total per currency beside account rows.
    if "kind" in filters:
        totals: dict[str, Decimal] = {}
        total_records: dict[str, set[str]] = {}
        total_grades: dict[str, list[str]] = {}
        total_dates: dict[str, list[str]] = {}
        for row, value in values:
            totals[value.currency] = totals.get(value.currency, Decimal("0")) + value.amount
            total_records.setdefault(value.currency, set()).add(row["record_id"])
            if value.proves:
                total_records[value.currency].add(value.proves)
            total_grades.setdefault(value.currency, []).append(value.grade)
            if value.as_of:
                total_dates.setdefault(value.currency, []).append(value.as_of)
        missing = [i.account for i in selected_infos if i not in infos]
        for currency, total in sorted(totals.items()):
            figures.append(figure(
                total, f"total {_measure_of(filters['kind'])} across all "
                       f"{filters['kind']} accounts",
                quantity=_measure_of(filters["kind"]),
                grade=weakest(total_grades[currency]),
                dated=min(total_dates.get(currency, []), default=""),
                currency=currency,
                record_ids=sorted(total_records[currency]),
                boundary=bounded(
                    whole=len(totals) == 1,
                    counted=len({r["record_id"] for r, v in values
                                 if v.currency == currency}),
                    held=len(selected_infos),
                    unmeasured=[{"account": account,
                                 "reason": GAP_UNOBSERVED}
                                for account in missing],
                    selected=narrowed,
                    cut=([{"kind": BY_CURRENCY, "value": currency}]
                         if len(totals) > 1 else ()))))
    figures.append(figure(len(rows), "accounts holding a balance",
                          quantity=quantity.COUNT,
                          grade=weakest(value.grade for _r, value in values),
                          record_ids=sorted({r["record_id"] for r in rows}),
                          boundary=bounded(
                              whole=not narrowed and len(rows) == holds,
                              counted=len(rows), held=holds,
                              selected=narrowed,
                              cut=cut_set(narrowed))))
    unmeasured = [i.account for i in selected_infos if i not in infos]
    return ToolResult(
        tool=TOOL, ok=True, figures=figures,
        identifiers=_identifiers(proj, (i.account for i in selected_infos)),
        # The amount, its grade, its currency and its as-of date travel as
        # figures. What stays here is what a figure cannot carry: which account
        # this is, and why its grade is what it is.
        data={"balances": [{k: v for k, v in r.items()
                            if k not in ("amount", "currency", "grade",
                                         "dated", "as_of", "explanation")}
                           for r in rows]},
        grade=weakest(value.grade for _r, value in values),
        dated=min((value.as_of for _r, value in values if value.as_of),
                  default=""),
        record_ids=sorted(set(record_ids)),
        caveats=([MIXED_VINTAGE]
                 if any(_mixed_vintage(value.dates) for _r, value in values)
                 else []) + [
                     f"No balance has been observed for {account}; it is not "
                     "reported as zero and is not included in these figures."
                     for account in unmeasured
                 ],
        coverage=("Included: " + "; ".join(
            f"{r['name'] or r['record_id']} (as of {value.as_of or 'unknown'}, "
            f"{value.grade})" for r, value in values)),
        text=f"{len(rows)} account balance(s), each with its grade and source.")


def _has_measured_value(proj, account: str) -> bool:
    """Whether an account has a dated stock measurement.

    Transactions alone do not establish a current balance without a starting
    point. Dated composed values cover ordinary observed balances and
    investment positions while excluding the synthetic zero of a newly
    asserted liability.
    """
    return any(value.as_of for value in proj.composed_values(account))


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
    money_in = sum((Decimal(r["effect"]) for r in rows
                    if Decimal(r["effect"]) > 0), Decimal("0"))
    money_out = sum((-Decimal(r["effect"]) for r in rows
                     if Decimal(r["effect"]) < 0), Decimal("0"))
    by_account: dict[str, Decimal] = {}
    by_month: dict[str, Decimal] = {}
    month_docs: dict[str, set] = {}
    for r in rows:
        amount = Decimal(r["effect"])
        by_account[r["account"]] = by_account.get(r["account"],
                                                  Decimal("0")) + amount
        month = r["date"][:7]
        by_month[month] = by_month.get(month, Decimal("0")) + amount
        if r["doc_id"]:
            month_docs.setdefault(month, set()).add(r["doc_id"])
    grade = weakest(r["grade"] for r in rows)
    # What these figures were taken over. Whole is read off the same list the
    # narrowing is written from, because `bounded` refuses a figure that
    # declares it covers everything and also names what narrowed it. Each of
    # the five is the whole of what the filters left, so each names exactly
    # what the filters named and nothing beyond it.
    narrowed = _narrowed_to(proj, filters)
    whole = not narrowed
    over = cut_set(narrowed)
    figures = [
        figure(len(rows), "movements matching the filters",
               quantity=quantity.COUNT, grade=grade, record_ids=record_ids,
               boundary=bounded(whole=whole, selected=narrowed, cut=over)),
        # Summed by which way the money went, which is read off the account's
        # kind rather than off the posting's sign.
        figure(money_in, "money in over these movements",
               quantity=quantity.GROSS_FLOW, grade=grade,
               currency=currency, record_ids=record_ids,
               boundary=bounded(whole=whole, selected=narrowed, cut=over)),
        figure(money_out, "money out over these movements",
               quantity=quantity.GROSS_FLOW, grade=grade,
               currency=currency, record_ids=record_ids,
               boundary=bounded(whole=whole, selected=narrowed, cut=over)),
        figure(money_in - money_out, "net movement over this set",
               quantity=quantity.NET_MOVEMENT, grade=grade,
               currency=currency, record_ids=record_ids,
               boundary=bounded(whole=whole, selected=narrowed, cut=over)),
        # The divisor a per-month average over this set is computed with.
        # Arithmetic takes figure ids, so a count that lives only in the
        # payload cannot be divided by.
        figure(len(by_month), "months these movements span",
               quantity=quantity.COUNT, grade=grade, record_ids=record_ids,
               boundary=bounded(whole=whole, selected=narrowed, cut=over)),
    ]
    # Two groupings over the same movements: a figure per account and a figure
    # per month. Each names its own slice, and declares itself whole only where
    # nothing narrowed the read and that grouping produced one group.
    figures += [figure(v, f"net movement on {k}",
                       quantity=quantity.NET_MOVEMENT, grade=grade,
                       currency=currency, record_ids=[k],
                       boundary=bounded(whole=whole and len(by_account) == 1,
                                        selected=narrowed,
                                        cut=cut_set(narrowed,
                                                    {"kind": BY_ACCOUNT,
                                                     "value": k})))
                for k, v in sorted(by_account.items())]
    figures += [figure(v, f"net movement in {k}",
                       quantity=quantity.NET_MOVEMENT, grade=grade,
                       currency=currency,
                       record_ids=sorted(month_docs.get(k, ())),
                       boundary=bounded(whole=whole and len(by_month) == 1,
                                        selected=narrowed,
                                        cut=cut_set(narrowed,
                                                    _month_slice(
                                                        k, narrowed))))
                for k, v in sorted(by_month.items())]
    return ToolResult(
        tool=TOOL, ok=True,
        identifiers=_identifiers(proj, [i.account for i in _scope(proj, filters)]),
        # The breakdown itself is the figures; `data` carries only the counts
        # and the totals, never a second copy of them.
        data={"count": len(rows), "money_in": str(money_in),
              "money_out": str(money_out), "net": str(money_in - money_out),
              "accounts": len(by_account), "months": len(by_month),
              "window": dict(filters.get("window") or {})},
        figures=figures, grade=grade,
        record_ids=record_ids, covers=covers, caveats=caveats,
        coverage=f"{len(rows)} movement(s) matched the filters.",
        text=("A summary of the matching movements; ask list_movements for the "
              "individual rows, narrowed to what you want to see."))


# `filters` is required, so a call that names nothing at all is refused where
# the arguments are validated rather than after the read has been entered.
# Which filters are narrow enough is the read's own rule, in `NARROWING`.
LIST_MOVEMENTS_PARAMS = {
    "type": "object",
    "properties": {
        "filters": QUERY_LEDGER_PARAMS["properties"]["filters"],
    },
    "required": ["filters"],
}

# What one row says: what identifies the movement and what it was ruled to be.
# The reasoning behind the ruling is what `get_provenance` answers for.
#
# The magnitude travels as `effect` and not as the raw posting `amount`,
# because a posting's own sign does not say which way the money went — the kind
# of account it sits on does. A row carrying the raw sign lets a card purchase
# be read as money received, and nothing else in the row contradicts it.
ROW_FIELDS = ("record_id", "account", "date", "description", "effect",
              "currency", "nature", "category", "subcategory", "tags",
              "grade", "doc_id")

LIST_TOOL = "list_movements"

# The filters that narrow a detailed read; at least one is required.
# `currency` is not among them, because it usually matches most of the ledger.
NARROWING = ("account", "category", "merchant", "tag", "window")


def _as_tool(result: ToolResult, tool: str) -> ToolResult:
    """The same refusal, attributed to the verb that was actually called. The
    vocabulary checks are shared between the reads."""
    result.tool = tool
    return result


def list_movements(proj, args: dict, today: str = "") -> ToolResult:
    """The individual rows, for a question narrow enough to name what it is
    about. A call carrying none of `NARROWING` refuses as `too_broad`."""
    filters, window_problem = _resolve_window_preset(
        proj, args.get("filters") or {}, today)
    if window_problem is not None:
        return _as_tool(window_problem, LIST_TOOL)
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
    matched = rows[:MAX_ROWS]
    shown = [{k: r[k] for k in ROW_FIELDS} for r in matched]
    record_ids = sorted({r["doc_id"] for r in shown if r["doc_id"]}
                        | {r["record_id"] for r in shown})
    covers, caveats = _attested_coverage(proj, filters)
    # A row is one movement, which is the whole of what the quantity `movement`
    # ranges over, and a member of the set rather than a slice of it — so it
    # declares whole and names no slice. Declaring whole is not the same as an
    # absent boundary, which means no read has said.
    figures = [figure(r["effect"], f"{r['description']} on {r['date']}",
                      quantity=quantity.MOVEMENT,
                      grade=r["grade"], dated=r["date"], currency=r["currency"],
                      record_ids=[r["record_id"]]
                      + ([r["doc_id"]] if r["doc_id"] else []),
                      boundary=bounded(whole=True))
               for r in shown]
    # How many movements matched, over the whole matching set rather than the
    # part inside the cap, standing on the documents those movements came on
    # and the accounts they sit on. It is the only figure of this read that
    # records what narrowed it.
    narrowed = _narrowed_to(proj, filters)
    counted_on = sorted({r["doc_id"] for r in rows if r["doc_id"]}
                        | {r["account"] for r in rows})
    if not rows:
        # A count of nothing stands on the accounts the read ranged over,
        # which are what make the zero attested rather than unobserved.
        counted_on = sorted(i.account for i in _scope(proj, filters))
    figures.append(figure(total, "movements matching the filters",
                          quantity=quantity.COUNT,
                          grade=weakest(r["grade"] for r in rows),
                          record_ids=counted_on,
                          boundary=bounded(whole=not narrowed,
                                           selected=narrowed,
                                           cut=cut_set(narrowed))))
    # A capped result says so in the sentence the tool itself writes: how many
    # of how many were shown, and which filters would reach the rest.
    coverage = f"Showing {len(shown)} of {total} matching movement(s)."
    if total > len(shown):
        # A capped list discloses the cap to a person as a caveat. The half
        # naming which filters would reach the rest is instruction to the
        # caller and stays in the coverage line.
        caveats = caveats + [coverage]
        coverage += (" Narrow by " + ", ".join(NARROWING)
                     + " to see the rest.")
    return ToolResult(
        tool=LIST_TOOL, ok=True, data={"movements": shown, "shown": len(shown),
                                       "total": total,
                                       "window": dict(filters.get("window") or {})},
        figures=figures,
        # A counterparty is named by its key, which is what a figure of this
        # read declares its scope as and what a follow-up filter takes back. A
        # row's own description stays on the row, where a person reading their
        # movements reads it.
        identifiers=(_identifiers(proj, (r["account"] for r in shown))
                     + _merchants(r["merchant_key"] for r in matched)),
        grade=weakest(r["grade"] for r in shown),
        record_ids=record_ids, covers=covers, caveats=caveats,
        coverage=coverage, text=coverage)





__all__ = ['_query_balances', '_matching_rows', '_query_transactions', 'LIST_MOVEMENTS_PARAMS', 'ROW_FIELDS', 'LIST_TOOL', 'NARROWING', '_as_tool', 'list_movements']
