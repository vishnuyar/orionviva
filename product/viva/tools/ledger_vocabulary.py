"""Ledger vocabulary lookup and public read dispatch."""

from __future__ import annotations

from .ledger_common import *
from .ledger_aggregates import (_aggregate_income, _aggregate_net_worth,
                                _aggregate_recurring_spending,
                                _aggregate_spending, _aggregate_stalest_balance,
                                _aggregate_surplus,
                                _aggregate_weakest_evidence, _query_holdings)
from .ledger_movements import (_query_balances, _query_transactions)

# ------------------------------------------------------------- the vocabulary

# What each vocabulary a read can group by is, as the labels the vault holds.
# One entry per member of the `group_by` enum, so a grouping a person can ask
# for is a vocabulary they can ask the size of, and a grouping added without
# one fails where the tool is written rather than as a mode that answers
# nothing.
#
# Accounts and currencies are read off what the vault holds rather than off a
# learned label set: they are not vocabulary anything mints, and asking how
# many there are is still the same question.
_VOCABULARIES = {
    "category": lambda proj: proj.known_categories(),
    # Under the category each one slices, which is the unit a breakdown counts
    # in. A bare label is a different kind of thing — two categories may each
    # hold a "fees" — so counting those would answer this question with a
    # number about something else.
    "subcategory": lambda proj: proj.known_subcategory_pairs(),
    "tag": lambda proj: proj.known_tags(),
    "merchant": lambda proj: sorted(
        {_merchant_key(proj, m) for m in proj.movements()} - {""}),
    "account": lambda proj: sorted(i.account for i in _real_accounts(proj)),
    "currency": lambda proj: sorted(_currencies(proj)),
}


def _vocabulary(proj, group_by: str, matching: str = "") -> ToolResult:
    """What labels this vault holds under one of its own vocabularies, and how
    many.

    A different question from any breakdown, and told apart from one on
    purpose. Spending grouped by subcategory says how many subcategories the
    person's SPENDING falls into; it leaves out a label used only on income,
    one whose movements are all transfers, and one named in a ruling with
    nothing posted against it yet. Answering "how many do I have" from that
    count is a real number about one thing put in a sentence about another —
    the failure the quantity vocabulary exists to prevent, one level up, at
    which read was called.

    ``matching`` asks which of the vocabulary a name reaches. It narrows which
    labels are named and nothing else: the count is the whole vocabulary's size
    either way, because a count over the labels a name reached would be a
    number about a set nothing can name. What comes back is labels this vault
    holds, so a follow-up narrows on one of them exactly, and the generosity
    stops here."""
    labels = [str(label) for label in _VOCABULARIES[group_by](proj)]
    if matching:
        wanted = _merchant_filter_key(matching)
        # By tier and then alphabetically: closest first, and one ledger read
        # twice orders the same labels the same way.
        reached = [(_match_tier(wanted, label), label) for label in labels]
        found = [label for tier, label in sorted(reached) if tier]
    else:
        # Alphabetical, because a vocabulary has no size to rank by and two
        # reads of one ledger must name the same labels.
        found = sorted(labels)
    named = found[:MAX_LABELS]
    caveats = []
    if len(named) < len(found):
        # The numbers are about what came back, so a capped lookup says how
        # many of the labels it reached are named rather than how many the
        # vault holds; the count figure states the whole either way.
        caveats.append(
            f"The first {len(named)} of {len(found)} {group_by} label(s) "
            + ("a name reached are named here, closest match first"
               if matching else "are named here, in alphabetical order")
            + "; the count is the whole count.")
    return ToolResult(
        tool=TOOL, ok=True,
        data={"vocabulary": group_by, "labels": named, "count": len(labels)},
        # A count of labels, and nothing about money. It stands on the ledger
        # events that carry them rather than on documents, so it is the kind of
        # figure that carries no grade — being wrong about it costs candour and
        # nothing else.
        figures=[figure(len(labels), f"{group_by} labels held",
                        quantity=quantity.COUNT, kind=ACTIVITY,
                        boundary=bounded(whole=True))],
        # The three vocabularies the vault holds a thing for are named as
        # things, so an answer can refer to one. The other three are the ones
        # with no entity, and this read mints none for them either.
        identifiers=(_identifiers(proj, named) if group_by == "account"
                     else _merchants(named) if group_by == "merchant"
                     else _categories(named) if group_by == "category"
                     else []),
        caveats=caveats,
        coverage=f"{len(labels)} {group_by} label(s) this vault holds.",
        text=(f"The {group_by} vocabulary holds {len(labels)} label(s)."
              if not matching else
              f"{len(found)} of {len(labels)} {group_by} label(s) are reached "
              f"by that name."))


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


def query_ledger(proj, args: dict, locale: str = "",
                 today: str = "") -> ToolResult:
    filters, window_problem = _resolve_window_preset(
        proj, args.get("filters", {}), today)
    if window_problem is not None:
        return window_problem
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
        # A balance carries forward, so any day from the newest evidence up to
        # today is a day this can answer for. Past today it is not carrying a
        # balance, it is projecting one, and the date would otherwise found a
        # claim about a day that has not happened.
        bound = today or _today()
        if args["as_of"] > bound:
            return refusal(TOOL, "as_of_in_the_future",
                           f"I cannot answer for {args['as_of']}, which has "
                           f"not happened yet. I can answer up to {bound}.")
        if not (entity == "aggregate" and args.get("metric") == "net_worth"):
            return refusal(TOOL, "as_of_unsupported",
                           "as_of applies to the net_worth metric; other "
                           "reads answer from the latest evidence.")
    if "matching" in args and entity != "vocabulary":
        # Asking which of a vocabulary a name reaches is a question about
        # labels. A read of money answers it by narrowing, on a value the
        # vocabulary read hands back, so the two are refused apart rather than
        # one quietly doing the other's work.
        return refusal(TOOL, "matching_unsupported",
                       "matching applies to entity 'vocabulary', which is "
                       "where a name is looked up; a read of money narrows by "
                       "a filter instead.")
    if entity == "balances":
        return _query_balances(proj, filters)
    if entity == "transactions":
        return _query_transactions(proj, filters)
    if entity == "holdings":
        return _query_holdings(proj, filters)
    if entity == "vocabulary":
        group_by = args.get("group_by")
        if not group_by:
            return refusal(TOOL, "missing_group_by",
                           "entity 'vocabulary' needs a group_by naming which "
                           "vocabulary: " + ", ".join(sorted(_VOCABULARIES))
                           + ".")
        return _vocabulary(proj, group_by, str(args.get("matching") or ""))
    # aggregate
    metric = args.get("metric")
    if not metric:
        return refusal(TOOL, "missing_metric",
                       "entity 'aggregate' needs a metric: spending, income, "
                       "recurring_spending, surplus, stalest_balance, "
                       "weakest_evidence, or net_worth.")
    if metric == "spending":
        return _aggregate_spending(proj, filters,
                                   args.get("group_by", "category"), locale)
    if metric == "income":
        return _aggregate_income(proj, filters)
    if metric == "recurring_spending":
        return _aggregate_recurring_spending(proj, filters)
    if metric == "surplus":
        return _aggregate_surplus(proj, filters)
    if metric == "stalest_balance":
        return _aggregate_stalest_balance(proj, today or _today())
    if metric == "weakest_evidence":
        return _aggregate_weakest_evidence(proj, filters)
    return _aggregate_net_worth(proj, args.get("as_of"), today or _today())




__all__ = ['_VOCABULARIES', '_vocabulary', '_unsupported_filters', 'query_ledger']
