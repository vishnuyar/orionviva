"""Holding, spending, income, and net-worth ledger reads."""

from __future__ import annotations

from .ledger_common import *

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
    # A holding is a member of what this read ranged over rather than a slice
    # of it, so no figure here names a slice; each records what narrowed the
    # read it was taken over.
    #
    # One instrument's value is never the whole of what a balance measures —
    # the rest is the other instruments beside it and the cash this read cannot
    # see — so a per-holding figure declares itself not whole on every vault,
    # however few rows came back. That places no sentence, and is not the
    # silence of a read that declared nothing.
    narrowed = _narrowed_to(proj, filters)
    figures = [figure(r["market_value"], f"{r['instrument']} — measured value",
                      quantity=quantity.BALANCE,
                      grade=r["grade"], dated=r["as_of"], currency=r["currency"],
                      record_ids=[r["record_id"]]
                      + ([r["provenance"]["doc_id"]]
                         if r["provenance"].get("doc_id") else []),
                      boundary=bounded(whole=False, selected=narrowed))
               for r in rows]
    # A different quantity from the values above it: how many holdings this
    # read measured, which over an unnarrowed read is every one there is.
    figures.append(figure(len(rows), "measured holdings",
                          quantity=quantity.COUNT,
                          grade=weakest(r["grade"] for r in rows),
                          record_ids=sorted({r["record_id"] for r in rows}),
                          boundary=bounded(whole=not narrowed,
                                           selected=narrowed,
                                           cut=cut_set(narrowed))))
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
    spellings: dict = {}
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
            # Missing or empty: a ruling can carry an empty category name, and
            # a nameless group is money a person can neither read nor filter
            # on. The same default the projection and the subcategory grouping
            # take, so all three agree about how much is unnamed — including
            # the caveat below, which states that figure to a person verbatim.
            key = (proj.derived_category(m) or {}).get("category") or "Uncategorized"
        elif group_by == "subcategory":
            # Named under its parent, because a subcategory alone is not a
            # vocabulary: "streaming" says nothing about which category it
            # slices, and a subcategory sharing a name with a category would
            # otherwise have its total summed into it. Money the category holds
            # that no subcategory names is its own group rather than a silent
            # part of the parent.
            ruling = proj.derived_category(m) or {}
            key = subcategory_group_key(
                ruling.get("category") or "Uncategorized",
                ruling.get("subcategory") or "")
            # Which spellings this read counted, per group and per punctuation
            # class, so a caveat afterwards speaks about these figures and not
            # about spellings the filters left out.
            spelled, identity = proj.subcategory_spelling(m)
            if spelled:
                spellings.setdefault((key, identity), set()).add(spelled)
        elif group_by == "merchant":
            # Stripped rather than merely truthy: a description of nothing but
            # spaces names no counterparty either, and both land on the same
            # named group.
            key = _merchant_key(proj, m) or UNNAMED_MERCHANT
        elif group_by == "account":
            key = m.account
        else:
            key = m.currency or "?"
        out[key] = out.get(key, Decimal("0")) + amount
    extras = {"total": total, "count": count, "untagged": untagged,
              "grades": used_grades, "record_ids": sorted(record_ids),
              "currencies": {c for c in currencies if c},
              "spellings": spellings}
    return out, extras


# How each filter narrows a set, so an answer can state what it ranged over.
# Every filter a read honours has an entry here. `window` is the one absence:
# one filter yields three different narrowings depending on which of its edges
# are given, so it is named where the narrowing is assembled rather than by a
# single entry here.
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
    # What the total counted and what it did not, said where there is a total
    # of something: a read that counted no movement has nothing for this
    # sentence to be about. It names no word the person has been shown as a
    # label, so the category called `transfers` and the settlements this leaves
    # out are not one word doing two jobs.
    caveats = ([COUNTS_WHAT_LEFT] if extras["count"] else []) + span_caveats
    if group_by == "tag":
        data["untagged"] = str(extras["untagged"])
        data["overlaps"] = True
        # Said of the tags the read found rather than of the grouping it was
        # asked for: on a vault carrying no tag there are no per-tag figures
        # for them to fail to sum to.
        if grouped:
            caveats.append("Tags overlap: the per-tag figures do not sum to "
                           "the total, and untagged money appears in no line.")
    # An amount inside a caveat is an amount, and is written by the one
    # renderer that writes every other one. A caveat is passed on verbatim, so
    # a figure it spelled for itself would be the sentence under the answer
    # disagreeing with the answer about how this person's money is written.
    def amount(value) -> str:
        return str(render.money(value, currency, locale=locale))

    # Two subcategory spellings differing only in punctuation are counted as
    # one label, which moves a figure and appends no event, so the merge is
    # stated beside the numbers it changed.
    #
    # Only spellings this read counted, and only spellings that met by
    # punctuation: a group whose figure came from one spelling had nothing
    # merged into it, and a fold a person ruled has an event behind it. Lines
    # are named as the read names them, since a subcategory alone does not say
    # which line it means.
    if group_by == "subcategory":
        folds = sorted(((key, sorted(spelled)) for (key, _), spelled
                        in extras["spellings"].items() if len(spelled) > 1),
                       key=lambda fold: (-grouped.get(fold[0], Decimal("0")),
                                         fold[0]))
        if folds:
            named_folds = folds[:MAX_FOLDS]
            unnamed = len(folds) - len(named_folds)
            caveats.append(
                "More than one spelling counts as one label on "
                f"{len(folds)} line(s) here — "
                + "; ".join(f"{key} ({', '.join(spelled)})"
                            for key, spelled in named_folds)
                + (f", and {unnamed} more line(s)" if unnamed else "")
                + ". Spellings differing only in punctuation are one label; "
                "anything else stays separate until you say otherwise.")

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
    # What each of these figures was taken over. The total and the count were
    # taken over whatever the filters left — so they name exactly what the
    # filters named, and a sentence asking what was spent at one counterparty,
    # or at one counterparty inside one span, has a figure that is the whole of
    # what it asks about. A group was taken over one slice of what the filters
    # left, so it names the filters AND its own slice, which is what makes it a
    # different claim from the total beside it.
    #
    # A group is the whole of the spending its quantity ranges over only where
    # the grouping puts every counted movement in exactly one group AND there
    # is only that one group AND nothing narrowed the read. How many groups
    # there are decides nothing on its own: under a grouping that does not
    # partition, the one group is still a slice, and money in no group at all
    # is money the figure does not carry.
    narrowed = _narrowed_to(proj, filters)
    filtered = bool(set(filters) & _SUPPORTED_FILTERS["aggregate:spending"])
    covers_all = (not filtered and group_by in _PARTITIONING
                  and len(grouped) == 1)
    figures = []
    for k, v in sorted(named.items()):
        # Which group this is, said whether or not this group is all of the
        # spending: a breakdown of one group is still a breakdown, and its one
        # row still has a name. What `covers_all` decides is whether there is a
        # boundary to state, not whether the figure knows what it is of.
        cut = cut_set(narrowed, {"kind": _GROUP_NAMES[group_by], "value": k})
        figures.append(figure(v, f"spending — {group_by} '{k}'",
                              quantity=quantity.SPENDING, grade=grade,
                              currency=currency, record_ids=record_ids,
                              boundary=bounded(whole=covers_all,
                                               selected=narrowed, cut=cut)))
    over = cut_set(narrowed)
    figures.append(figure(extras["total"], f"total spending by {group_by}",
                          quantity=quantity.SPENDING,
                          grade=grade, currency=currency,
                          record_ids=record_ids,
                          boundary=bounded(whole=not filtered,
                                           selected=narrowed, cut=over)))
    figures.append(figure(extras["count"], "spending movements counted",
                          quantity=quantity.COUNT,
                          grade=grade, record_ids=record_ids,
                          boundary=bounded(whole=not filtered,
                                           selected=narrowed, cut=over)))
    # What a spending read groups by is sometimes a thing it spoke about — a
    # category, a counterparty — and an answer refers to that rather than
    # spelling it. A subcategory group is not one: its key names a pair, the
    # vault holds no such category, and `_check_filters` refuses the same
    # string on the follow-up. Naming the parent instead would be worse, since
    # the figure beside it measures one slice of that parent rather than all of
    # it. So the pair stays a group key, and what the answer can say about it is
    # what its figure's boundary says it was cut by — the scope of that number,
    # which makes no promise to be a name anything accepts back.
    #
    # The residual group is the same case by another route: its name belongs to
    # no counterparty, so it is minted as no entity either.
    grouped_entities = (_categories(named) if group_by == "category"
                        else _merchants(k for k in named
                                        if k != UNNAMED_MERCHANT)
                        if group_by == "merchant"
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
    # This read cuts by currency, so each figure names the currency its income
    # is in, and declares itself whole only where nothing narrowed the read and
    # there is one currency to be in.
    #
    # A slice is named in the vault's own vocabulary, so the key must be one of
    # the currencies the vault holds — the set a `currency` filter is validated
    # against. Income can be attributed under a key no account declares; such a
    # figure carries no slice, and a block of rows over the read then refuses
    # rather than listing a currency nobody holds.
    known = _currencies(proj)
    narrowed = _narrowed_to(proj, filters)
    whole = not narrowed and len(by_currency) == 1
    figures = [figure(v, f"attributed income in {k}, over everything ingested",
                      quantity=quantity.INCOME,
                      grade=weakest(line_grades), currency=k,
                      record_ids=sources,
                      boundary=bounded(whole=whole, selected=narrowed,
                                       cut=cut_set(
                                           narrowed,
                                           {"kind": BY_CURRENCY, "value": k}
                                           if k in known else None)))
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


PARTS = ("net", "assets", "liabilities")

# What each part of a net-worth point measures. The two sides are not the same
# kind of thing as each other: one totals what is held and the other what is
# owed, so neither can be spoken as the other and neither adds to the other.
_PART_MEASURES = {"net": quantity.NET_WORTH, "assets": quantity.BALANCE,
                  "liabilities": quantity.OWED}


def _side_of(account: str, kind: str = "") -> str:
    """Which part of a net-worth point an account belongs to, or "" when
    nothing says. A ledger kind decides where one is defined; otherwise the
    root of the path does."""
    if kind:
        return "liabilities" if kind == LIABILITY else "assets"
    if account.startswith(networth.LIABILITY_ROOT):
        return "liabilities"
    if account.startswith(networth.ASSET_ROOT):
        return "assets"
    return ""


def _not_counted(point: dict) -> tuple[dict, bool]:
    """What a net-worth point claims to measure and does not include, per part
    of it, as ``({part: [{account, settled_by}]}, placed)``.

    Two things a point holds are two ways of not being in it: an account whose
    figure the point refused, and an account held that no measurement in this
    point covers. Both are money the person has and the total does not carry,
    so both are the total's boundary.

    An account whose only statement is dated after this point is among them.
    Whether the person held it before that statement is not something the
    ledger knows — an account's opening date is read off the first document
    that arrived, so it says when the evidence starts and not when the account
    did — and a total that called itself complete over a don't-know would be
    the claim this field exists to stop.

    One account is one gap however many of the point's own lists hold it. An
    account a ruling brought into being and that was also opened is in both, so
    a gap per list would put two reasons on one account — and the two disagree
    about whether anything can close it. The reason that names a remedy is the
    one kept, because it is the one an answer could act on.

    ``placed`` is False when any of them could not be put on a side, so a side
    that might be short of something never says it is whole."""
    out: dict = {part: [] for part in PARTS}
    placed = True
    noted: set = set()

    def note(account: str, side: str, **fields) -> None:
        nonlocal placed
        if account in noted:
            return
        noted.add(account)
        item = {"account": account, **fields}
        out["net"].append(item)
        if side:
            out[side].append(item)
        else:
            placed = False

    # Refused first, so an account in both lists keeps the reason that carries
    # what would settle it.
    for row in point.get("missing") or []:
        account = str(row.get("account", ""))
        note(account, _side_of(account), reason=GAP_REFUSED,
             settled_by=str(row.get("would_fix", "")))
    for row in point.get("skipped") or []:
        account = str(row.get("account", ""))
        note(account, _side_of(account, str(row.get("kind", ""))),
             reason=GAP_UNOBSERVED)
    return out, placed


def _emitted_line(line: dict) -> str:
    """One net-worth line as a figure states it: a liability in the owed
    convention, anything else as the point holds it."""
    amount = Decimal(str(line.get("amount", "0")))
    return str(-amount if line.get("kind", "") == LIABILITY else amount)


def _line_word(line: dict) -> str:
    """How one net-worth line is written for the model to read: what is owed
    says so, and what is held says which point it is a part of."""
    if line.get("kind", "") == LIABILITY:
        return f"{line['account']} — {quantity.OWED}"
    return f"{line['account']} — its part of net worth"


def _aggregate_net_worth(proj, as_of: str | None, today: str = "") -> ToolResult:
    # With no day asked for, the day it is asked on. A balance carries forward,
    # so the total is good now; `net_worth` on its own would date the point by
    # its newest input, which is when the evidence was taken rather than when
    # the answer is good for.
    point = networth.net_worth(proj, as_of or today or None)
    data = point.to_dict()
    record_ids = sorted({line.get("account", "") for line in
                         (data.get("lines") or []) if line.get("account")})
    lines = [line for line in (data.get("lines") or []) if line.get("account")]
    # A balance carries: absent a newer statement, the last one observed is
    # still what the account holds, so the total is good as of the day it was
    # asked for. How stale the evidence under it is rides in the caveat and on
    # each line's own `as_of`, which the per-account figures carry.
    as_of = data.get("as_of", "")
    # What the point already knows it does not include: the accounts it refused
    # a figure for, the accounts held whose balance has never been observed,
    # and the documents read but not posted. A side's own total leaves out what
    # is missing from that side; the net figure leaves out all of it, and a
    # side that might be short of something nothing could place says so too.
    left_out, placed = _not_counted(data)
    # A document read and not posted is a gap no account can name: it may be
    # about an account that does not exist yet, which is why the point keeps it
    # apart from what it lists per account. It is counted, and said as a count.
    unposted = len(data.get("held") or [])
    figures = []
    # One currency's part of a point held in several is one slice of it, and it
    # names which. It is the whole of what its quantity ranges over only where
    # that currency is the only one the vault holds, the same as one account's
    # balance is a total only on a vault of one account. There is no total
    # across currencies, so on a vault of several nothing here is whole.
    by_currency = data.get("by_currency", {})
    for currency, row in sorted(by_currency.items()):
        for part in PARTS:
            # What is held less what is owed is net worth; each side of it on
            # its own is a total of balances, and saying so keeps a hole that
            # asked for one from being filled with the other.
            missing = left_out[part]
            figures.append(figure(row[part], f"{part} in {currency}",
                                  quantity=_PART_MEASURES[part],
                                  grade=weakest(_grades_in(data)),
                                  dated=as_of, currency=currency,
                                  record_ids=record_ids,
                                  boundary=bounded(
                                      whole=(not missing and not unposted
                                             and placed
                                             and len(by_currency) == 1),
                                      unmeasured=missing,
                                      unposted=unposted,
                                      cut=[{"kind": BY_CURRENCY,
                                            "value": currency}])))
    # A line of the point is emitted under what it measures, not under the sign
    # the point holds it in: an account someone is owed on comes out as the
    # debt the bill prints, the same figure the balances read gives for it, and
    # what is held comes out as its contribution. The line inside the point
    # keeps its signed contribution, which is what every subtotal is built from.
    #
    # A line is one account's part of a point built from several, so it is
    # never the whole of what its quantity ranges over, and it names the
    # account it is the part of.
    figures += [figure(_emitted_line(line), _line_word(line),
                       quantity=_measure_of(line.get("kind", "")),
                       grade=line.get("grade", ""), dated=line.get("as_of", ""),
                       currency=line.get("currency", ""),
                       record_ids=[line["account"]],
                       boundary=bounded(whole=False,
                                        cut=[{"kind": BY_ACCOUNT,
                                              "value": line["account"]}]))
                for line in lines]
    return ToolResult(
        tool=TOOL, ok=True, figures=figures,
        identifiers=_identifiers(proj, record_ids),
        data={"metric": "net_worth", "point": data},
        grade=weakest(_grades_in(data)),
        dated=as_of,
        record_ids=record_ids,
        # A point rests on records of more than one date two ways: its lines
        # were measured on different days, or one line composes days of its
        # own. The sentence is as true of the second as of the first, and a
        # point of one line is the case where only the second can happen.
        caveats=([MIXED_VINTAGE]
                 if _mixed_vintage(line.get("as_of", "") for line in lines)
                 or any(line.get("mixed_vintage") for line in lines)
                 else []),
        text=f"Net worth as of {as_of or 'unknown'}.")




__all__ = ['_query_holdings', '_spending_rows', '_largest_groups', '_aggregate_spending', '_aggregate_income', '_grades_in', 'PARTS', '_PART_MEASURES', '_side_of', '_not_counted', '_emitted_line', '_line_word', '_aggregate_net_worth']
