"""Tool scope contracts."""

from _tool_test_support import *

# --------------------------------------------- where a figure's claim ends

def _spending_events(*movements):
    """A vault with one account and whatever spending is named, so a grouping
    can be given exactly as many groups as a property needs."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan"))]
    spent = Decimal("0")
    for date, descriptor, amount, category, tags in movements:
        evs.append(simple_transaction("chk", amount, descriptor, date,
                                      provenance=_p("doc-jan")))
        spent += abs(Decimal(amount))
        if category:
            evs.append(merchant_enriched(descriptor.lower(), category,
                                         subcategory="", occurred_at="2026-02-02"))
        if tags:
            evs.append(movement_tagged(
                movement_key("doc-jan", "chk", date, Decimal(amount),
                             descriptor, 0), list(tags), "2026-02-05"))
    evs.append(closing_balance_observed("chk", str(Decimal("1000.00") - spent),
                                        "2026-01-31", _p("doc-jan", 6)))
    return evs


def test_a_per_account_balance_says_it_is_one_of_the_accounts_held(proj):
    """A grade says how well a number is stood behind. It does not say how much
    of the question the number answers, and one account's balance offered where
    a total was asked for is a true, well-graded figure over the wrong set.

    It says which account it is as well as how many it is one of. How many
    there are is what stops it being read as a total; which one it is, is what
    a sentence naming an account can be checked against."""
    held = len([i for i in proj.account_infos()
                if i.kind in ledger_tools.REAL_KINDS])
    assert held > 1
    result = ledger_tools.query_ledger(proj, {"entity": "balances"})
    # One figure per row, in the rows' own order, before the count of them.
    for f, row in zip(result.figures, result.data["balances"]):
        assert f["boundary"] == {
            "whole": False, "accounts": {"counted": 1, "held": held},
            "cut": [{"kind": "account", "value": row["record_id"]}]}
    # And the count of them covers every one this read ranged over.
    counted = next(f for f in result.figures if f["quantity"] == quantity.COUNT)
    assert counted["boundary"] == {"whole": True,
                                   "accounts": {"counted": held, "held": held}}


def test_a_balance_read_narrowed_to_one_account_still_counts_what_is_held(proj):
    """The set a figure is one of is what the person holds, not what the read
    was asked for — narrowing the question does not narrow how many accounts
    there are. Beside the count it says which account was asked for, which is
    the other half of where the claim ends and a different sentence.

    One filter leaves one slice, and the count is the whole of that slice, so
    it names it: a sentence about how many accounts one narrowing left has a
    figure that is the whole of what it asks about."""
    held = len([i for i in proj.account_infos()
                if i.kind in ledger_tools.REAL_KINDS])
    result = ledger_tools.query_ledger(
        proj, {"entity": "balances", "filters": {"account": "chk"}})
    counted = next(f for f in result.figures if f["quantity"] == quantity.COUNT)
    assert counted["boundary"] == {
        "whole": False, "accounts": {"counted": 1, "held": held},
        "selected": [{"kind": "account", "value": "chk"}],
        "cut": [{"kind": "account", "value": "chk"}]}


def test_spending_narrowed_to_a_category_says_which_category(proj):
    """The read cannot know what word the question used, and it can say what it
    counted. A category filter comes back in the vault's own word for it, which
    is the whole point: the answer names what it actually counted."""
    result = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "filters": {"category": "groceries"}})
    total = next(f for f in result.figures if "total spending" in f["what"])
    assert total["boundary"] == {
        "whole": False,
        "selected": [{"kind": "category",
                      "value": proj.canonical_category("groceries")}],
        "cut": [{"kind": "category",
                "value": proj.canonical_category("groceries")}]}


def test_spending_narrowed_to_a_window_says_which_days(proj):
    """A window narrows a total exactly as a category does, and a total over
    one quarter stated as a total is the same shape of false sentence. Both
    edges make a span; one edge makes a day it runs from or to."""
    def narrowed(window):
        result = ledger_tools.query_ledger(
            proj, {"entity": "aggregate", "metric": "spending",
                   "filters": {"window": window}})
        return next(f for f in result.figures
                    if "total spending" in f["what"])["boundary"]

    assert narrowed({"from": "2026-01-01", "to": "2026-01-31"}) == {
        "whole": False,
        "selected": [{"kind": "period", "value": "2026-01-01",
                      "to": "2026-01-31"}],
        "cut": [{"kind": "period", "value": "2026-01-01", "to": "2026-01-31"}]}
    assert narrowed({"from": "2026-01-01"}) == {
        "whole": False,
        "selected": [{"kind": "since", "value": "2026-01-01"}],
        "cut": [{"kind": "since", "value": "2026-01-01"}]}
    assert narrowed({"to": "2026-01-31"}) == {
        "whole": False,
        "selected": [{"kind": "until", "value": "2026-01-31"}],
        "cut": [{"kind": "until", "value": "2026-01-31"}]}


def test_an_ungrouped_unfiltered_spending_total_is_the_whole_of_it(proj):
    """The statement fires only where there is a set worth stating. A total
    nothing narrowed covers everything its quantity ranges over, and says so
    rather than saying nothing."""
    result = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending"})
    total = next(f for f in result.figures if "total spending" in f["what"])
    assert total["boundary"] == {"whole": True}


def test_a_group_among_several_is_a_slice_and_says_which(proj):
    """Where a grouping has more than one group, every group is a part of the
    spending its quantity names, and each says which part it is."""
    evs = _spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries", ()),
        ("2026-01-06", "CITY TRANSIT", "-60.00", "transport", ()))
    result = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "spending",
                                "group_by": "category"})
    groups = [f for f in result.figures
              if f["what"].startswith("spending — category")]
    assert len(groups) == 2
    for f in groups:
        assert f["boundary"]["whole"] is False
        # Which part it is is the figure's own cut, told apart from how the
        # read was narrowed: this read was narrowed by nothing, and each of its
        # two figures is still a part.
        assert "selected" not in f["boundary"]
        assert [c["kind"] for c in f["boundary"]["cut"]] == ["category"]


def test_the_only_group_of_a_partitioning_grouping_is_the_whole(proj):
    """And where a grouping puts every counted movement in exactly one group
    and there is only that group, the group IS all of it — so nothing is
    stated, because there is no set worth stating.

    It still says which group it is. Being the whole and being the groceries
    group are two different facts, and a breakdown of one group is still a
    breakdown whose one row has a name."""
    evs = _spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries", ()),
        ("2026-01-06", "GREENFIELD MARKET", "-60.00", "groceries", ()))
    result = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "spending",
                                "group_by": "category"})
    group = next(f for f in result.figures
                 if f["what"].startswith("spending — category"))
    total = next(f for f in result.figures if "total spending" in f["what"])
    assert group["value"] == total["value"]
    assert group["boundary"] == {"whole": True,
                                 "cut": [{"kind": "category",
                                         "value": "groceries"}]}
    # And nothing is said about it, which is the point: a whole figure states
    # no boundary, cut or otherwise.
    from viva.tools.runner import _boundary

    assert _boundary(group) == ([], [])


def test_a_tag_group_is_never_the_whole_however_few_tags_there_are():
    """How many groups a grouping has decides nothing about what one of them
    covers. Tags overlap and money carrying none lands in no group at all, so
    the single tag group of a vault with one tag is still a slice — and a
    figure that called itself the whole of the spending would be the same false
    sentence this field exists to stop."""
    evs = _spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-60.00", "groceries", ("pantry",)),
        ("2026-01-06", "CITY TRANSIT", "-40.00", "transport", ()))
    result = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "spending",
                                "group_by": "tag"})
    tagged = next(f for f in result.figures
                  if f["what"].startswith("spending — tag"))
    total = next(f for f in result.figures if "total spending" in f["what"])
    assert Decimal(tagged["value"]) < Decimal(total["value"])
    assert tagged["boundary"] == {"whole": False,
                                  "cut": [{"kind": "tag", "value": "pantry"}]}


def test_what_a_spending_total_counts_is_said_only_where_it_counted_something():
    """A caveat is a sentence about a number, so a read that produced no
    number to talk about says nothing.

    The sentence names what is left out by what it is — money settling between
    two accounts the person holds — rather than by a label they may have been
    shown beside a figure, so it is true of a total that contains a category
    the vault happens to call `transfers`."""
    evs = _spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries", ()))
    counted = ledger_tools.query_ledger(
        LedgerProjection(evs),
        {"entity": "aggregate", "metric": "spending"})
    assert ledger_tools.COUNTS_WHAT_LEFT in counted.caveats

    empty = ledger_tools.query_ledger(
        LedgerProjection(evs),
        {"entity": "aggregate", "metric": "spending",
         "filters": {"window": {"from": "2027-01-01"}}})
    assert empty.ok, empty.text
    assert not any("left your life" in c for c in empty.caveats)


def test_overlapping_tags_are_disclosed_where_the_read_found_a_tag():
    """The condition belongs to the vault and not to the call.

    Grouping by tag is a fact about how the read was asked; carrying tags is a
    fact about the person's records. A vault with no tag has no per-tag figures
    that could fail to sum to anything, so there is nothing to disclose."""
    untagged = _spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries", ()))
    silent = ledger_tools.query_ledger(
        LedgerProjection(untagged),
        {"entity": "aggregate", "metric": "spending", "group_by": "tag"})
    assert silent.ok, silent.text
    assert not any("Tags overlap" in c for c in silent.caveats)

    tagged = _spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries",
         ("pantry",)))
    spoken = ledger_tools.query_ledger(
        LedgerProjection(tagged),
        {"entity": "aggregate", "metric": "spending", "group_by": "tag"})
    assert spoken.ok, spoken.text
    assert any("Tags overlap" in c for c in spoken.caveats)


def _measured_on(*days):
    """A vault of one account per day named, each last measured on its own
    day, so a point over them rests on as many dates as there are days."""
    evs = [document_captured("doc-one", "one.pdf", 100, "bank_statement", 0.9,
                             "2026-06-01")]
    for n, day in enumerate(days):
        evs += [account_opened(f"acct-{n}", "depository", f"Account {n}",
                               "USD", "2026-01-01"),
                closing_balance_observed(f"acct-{n}", "100.00", day,
                                         _p("doc-one"))]
    return LedgerProjection(evs)


def test_a_point_says_it_rests_on_several_dates_only_where_it_does():
    """The staleness sentence gains the condition its own words imply, and
    loses the pointer at fields nobody reading an answer can see.

    A point every line of which was measured on one day is as current as that
    day, and saying it is only as current as its stalest input tells a person
    nothing they can act on. Where the lines really were measured on different
    days, that is a fact about the value and it is said."""
    one_day = ledger_tools.query_ledger(
        _measured_on("2026-01-31"),
        {"entity": "aggregate", "metric": "net_worth"})
    assert one_day.ok, one_day.text
    assert one_day.caveats == []

    several = ledger_tools.query_ledger(
        _measured_on("2026-01-31", "2026-05-31"),
        {"entity": "aggregate", "metric": "net_worth"})
    assert several.ok, several.text
    assert several.caveats == [ledger_tools.MIXED_VINTAGE]
    assert "staleness fields" not in ledger_tools.MIXED_VINTAGE


def test_when_a_value_rests_on_several_dates_is_one_rule_with_one_sentence():
    """Both halves of the disclosure have one home, so a second reader
    composing a value from measurements of several days places the same
    sentence on the same condition rather than writing a rival one."""
    assert ledger_tools._mixed_vintage(["2026-01-31", "2026-05-31"])
    assert not ledger_tools._mixed_vintage(["2026-01-31", "2026-01-31"])
    # A day nothing recorded is a gap rather than a second vintage.
    assert not ledger_tools._mixed_vintage(["2026-01-31", ""])
    assert not ledger_tools._mixed_vintage([])


def test_a_grouping_the_vault_names_nothing_for_still_names_its_slice():
    """A subcategory pair is a group key and not a thing the vault holds. What
    it can still be is the scope of the number beside it — which slice of the
    read that figure was taken over — and that is what its boundary says.

    The two are different promises and the difference is the whole of why this
    is safe. An entity is a handle: an answer refers to one, and a person may
    hand it back. A cut is a statement about one figure, and hands back
    nothing — the read refuses this same string as a filter, and it is not
    offered as one."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan")),
           simple_transaction("chk", "-40.00", "GREENFIELD MARKET",
                              "2026-01-05", provenance=_p("doc-jan")),
           simple_transaction("chk", "-60.00", "CITY TRANSIT",
                              "2026-01-06", provenance=_p("doc-jan")),
           closing_balance_observed("chk", "900.00", "2026-01-31",
                                    _p("doc-jan", 6)),
           merchant_enriched("greenfield market", "groceries",
                             subcategory="supermarket",
                             occurred_at="2026-02-02"),
           merchant_enriched("city transit", "transport", subcategory="fares",
                             occurred_at="2026-02-02")]
    result = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "spending",
                                "group_by": "subcategory"})
    grouped = [f for f in result.figures
               if f["what"].startswith("spending — subcategory")]
    assert len(grouped) > 1
    for f in grouped:
        assert f["boundary"] == {
            "whole": False,
            "cut": [{"kind": "subcategory",
                    "value": f["what"].split("'")[1]}]}
    # And the name in that cut is still not a filter, which is why it is a
    # scope and not an entity.
    for f in grouped:
        follow_up = ledger_tools.query_ledger(
            LedgerProjection(evs),
            {"entity": "aggregate", "metric": "spending",
             "filters": {"category": f["boundary"]["cut"][0]["value"]}})
        assert not follow_up.ok and follow_up.refusal == "unknown_category"
    assert not [i for i in result.identifiers if i["kind"] == "category"]


def test_a_subcategory_read_says_which_spellings_it_counted_as_one():
    """A spending read grouped by subcategory carries a caveat naming the
    spellings it counted as one label, and a read grouped by category, which
    the fold does not touch, carries none."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan")),
           simple_transaction("chk", "-40.00", "ALPHA STORE",
                              "2026-01-05", provenance=_p("doc-jan")),
           simple_transaction("chk", "-60.00", "BETA STORE",
                              "2026-01-06", provenance=_p("doc-jan")),
           closing_balance_observed("chk", "900.00", "2026-01-31",
                                    _p("doc-jan", 6)),
           merchant_enriched("alpha store", "shopping", subcategory="book shop",
                             occurred_at="2026-02-02"),
           merchant_enriched("beta store", "shopping", subcategory="book_shop",
                             occurred_at="2026-02-02")]
    proj = LedgerProjection(evs)
    result = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "subcategory"})
    (said,) = [c for c in result.caveats if "spelling" in c]
    assert "book shop" in said and "book_shop" in said
    assert result.data["by_group"]["shopping / book shop"] == "100.00", \
        "the caveat is about a figure the same read states"

    # And a grouping the fold does not touch says nothing about spellings.
    by_category = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "category"})
    assert not [c for c in by_category.caveats if "spelling" in c]


def _spellings_vault(rows):
    """A vault whose merchants carry the subcategory spellings given, as
    ``(merchant, subcategory, date, amount)`` — the shape a run leaves behind
    when one idea comes back spelled more than one way."""
    spent = sum(Decimal(amount) for _, _, _, amount in rows)
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-q1", "q1.pdf", 100, "bank_statement", 0.9,
                             "2026-03-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-q1"))]
    for merchant, subcategory, when, amount in rows:
        evs.append(simple_transaction("chk", amount, merchant.upper(), when,
                                      provenance=_p("doc-q1")))
        evs.append(merchant_enriched(merchant, "shopping",
                                     subcategory=subcategory,
                                     occurred_at="2026-03-02"))
    evs.append(closing_balance_observed(
        "chk", str(Decimal("1000.00") + spent), "2026-02-28", _p("doc-q1", 6)))
    return LedgerProjection(evs)


def _by_subcategory(proj, **filters):
    return ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "subcategory",
               **({"filters": filters} if filters else {})})


def _spelling_caveat(result) -> str:
    said = [c for c in result.caveats if "spelling" in c]
    return said[0] if said else ""


def test_a_filtered_read_speaks_only_of_the_spellings_it_counted():
    """The caveat names only the spellings this read counted: a window that
    leaves one spelling out carries no caveat, and the unfiltered read of the
    same vault carries one."""
    proj = _spellings_vault([("alpha store", "book shop", "2026-01-05", "-40.00"),
                             ("beta store", "book_shop", "2026-02-06", "-60.00")])
    january = _by_subcategory(proj, window={"from": "2026-01-01",
                                            "to": "2026-01-31"})
    assert january.data["by_group"]["shopping / book shop"] == "40.00", \
        "one spelling counted"
    assert not _spelling_caveat(january), \
        "nothing met inside this read, so nothing is said about spellings"

    whole = _by_subcategory(proj)
    assert whole.data["by_group"]["shopping / book shop"] == "100.00"
    said = _spelling_caveat(whole)
    assert "book shop" in said and "book_shop" in said, \
        "the read that did count both says so"


def test_a_fold_is_named_the_way_the_read_names_its_own_lines():
    """A fold is named as `category / subcategory`, the way the read names its
    own lines, since one subcategory can sit under two categories."""
    proj = _spellings_vault([("alpha store", "book shop", "2026-01-05", "-40.00"),
                             ("beta store", "book_shop", "2026-01-06", "-60.00")])
    said = _spelling_caveat(_by_subcategory(proj))
    assert "shopping / book shop (book shop, book_shop)" in said


def test_a_caveat_says_only_what_is_true_of_the_lines_it_names():
    """Where a punctuation fold and a ruling land on one label, the caveat
    lists only the spellings that met by punctuation."""
    from viva.ledger.events import ruling_recorded
    proj = _spellings_vault([("alpha store", "book shop", "2026-01-05", "-40.00"),
                             ("beta store", "book_shop", "2026-01-06", "-60.00"),
                             ("gamma store", "book shops", "2026-01-07", "-30.00")])
    proj.apply(ruling_recorded(scope="category", subject="book shops",
                               same_as="book shop", occurred_at="2026-03-03"))
    result = _by_subcategory(proj)
    assert result.data["by_group"]["shopping / book shop"] == "130.00", \
        "the ruling and the fold both land on one line"
    said = _spelling_caveat(result)
    assert "(book shop, book_shop)" in said
    assert "book shops" not in said, \
        "a merge a person ruled is not handed back as a warning about spelling"


def test_a_long_list_of_folds_is_capped_and_says_how_many_it_did_not_name():
    """The caveat names the folded lines that moved the most money, up to
    MAX_FOLDS, and states the rest as a count."""
    rows = []
    for n in range(9):
        amount = str(Decimal("-100.00") - n * Decimal("10.00"))
        rows.append((f"alpha {n} store", f"topic {n}", "2026-01-05", amount))
        rows.append((f"beta {n} store", f"topic_{n}", "2026-01-06", amount))
    said = _spelling_caveat(_by_subcategory(_spellings_vault(rows)))
    assert said.startswith(
        "More than one spelling counts as one label on 9 line(s) here")
    assert "and 6 more line(s)" in said
    for n in (8, 7, 6):
        assert f"shopping / topic {n} (topic {n}, topic_{n})" in said, \
            "the lines named are the ones that moved the most money"
    for n in range(6):
        assert f"(topic {n}, topic_{n})" not in said, \
            "and the smaller ones are counted rather than recited"


def _owing_a_never_measured_loan():
    """A vault where a ruling brought a liability into being and no statement
    has ever measured it — the shape net worth reports as incomplete."""
    from viva.ledger.events import ruling_recorded
    return [
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01"),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", "10000.00", "2026-01-01", _p("doc-jan")),
        simple_transaction("chk", "-2000.00", "MERIDIAN LOAN SERVICING",
                           "2026-01-10", provenance=_p("doc-jan")),
        closing_balance_observed("chk", "8000.00", "2026-01-31",
                                 _p("doc-jan", 6)),
        ruling_recorded(
            scope="merchant", subject="meridian loan servicing",
            legs=[{"major": "liability",
                   "account": "Liabilities:HomeLoan:Meridian"}],
            occurred_at="2026-02-01", by="human"),
    ]


def test_an_incomplete_net_worth_names_what_it_leaves_out():
    """The point already knows it is incomplete, why, and what would settle it.
    The figures carry it, so a total can no longer be stated as though the set
    it was taken over were everything it claims to be."""
    proj = LedgerProjection(_owing_a_never_measured_loan())
    result = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "net_worth"},
        today="2026-03-01")
    net = next(f for f in result.figures if f["what"].startswith("net in"))
    assert net["boundary"]["whole"] is False
    assert net["boundary"]["unmeasured"] == [
        {"account": "Liabilities:HomeLoan:Meridian", "reason": "refused",
         "settled_by": "the loan or mortgage statement"}]
    # What is owed is short of it; what is held is not.
    owed = next(f for f in result.figures
                if f["what"].startswith("liabilities in"))
    holds = next(f for f in result.figures if f["what"].startswith("assets in"))
    assert owed["boundary"] == net["boundary"]
    assert holds["boundary"] == {"whole": True,
                                 "cut": [{"kind": "currency", "value": "USD"}]}


def test_an_account_whose_balance_was_never_observed_is_a_gap_too():
    """An account the person holds and no statement has ever measured is money
    the total does not carry, whatever the point's own completeness flag says
    about it. A figure that called itself whole beside one would be this
    cycle's own failure reproduced inside the mechanism built to stop it."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           account_opened("loan", "liability", "Home Loan", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan")),
           closing_balance_observed("chk", "1000.00", "2026-01-31",
                                    _p("doc-jan", 6))]
    proj = LedgerProjection(evs)
    point = ledger_tools.networth.net_worth(proj, "2026-03-01")
    assert point.complete, "the point's own flag does not see this one"
    result = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "net_worth"},
        today="2026-03-01")
    for f in result.figures:
        if f["what"].startswith(("net in", "liabilities in")):
            assert f["boundary"]["whole"] is False, f["what"]
            assert f["boundary"]["unmeasured"] == [
                {"account": "loan", "reason": "unobserved",
                 "settled_by": ""}]
    # And the side it cannot be short of still says it is whole.
    holds = next(f for f in result.figures if f["what"].startswith("assets in"))
    assert holds["boundary"] == {"whole": True,
                                 "cut": [{"kind": "currency", "value": "USD"}]}


def test_an_account_measured_only_later_is_a_gap_in_an_earlier_point():
    """An account whose only statement is dated after the point is still a gap
    in it, and a total over that date is not whole.

    Whether the person held it before that statement is not something the
    ledger knows: an account's opening date is read off the first document that
    arrived, so it says when the evidence starts and not when the account did.
    Treating "no evidence yet" as "nothing was held" would let a loan a person
    owed money on read as a complete zero for every date before its first
    statement — the exact claim this field exists to stop, and the one place
    such a carve-out could ever fire."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           account_opened("loan", "liability", "Home Loan", "USD",
                          "2026-03-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan")),
           closing_balance_observed("chk", "1000.00", "2026-01-31",
                                    _p("doc-jan", 6)),
           closing_balance_observed("loan", "9000.00", "2026-03-31",
                                    _p("doc-mar", 6))]
    result = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "net_worth",
                                "as_of": "2026-02-15"}, today="2026-07-01")
    owed = next(f for f in result.figures
                if f["what"].startswith("liabilities in"))
    assert owed["value"] == "0"
    assert owed["boundary"] == {
        "whole": False,
        "cut": [{"kind": "currency", "value": "USD"}],
        "unmeasured": [{"account": "loan", "reason": "unobserved",
                        "settled_by": ""}]}


def test_a_complete_net_worth_says_it_is_complete():
    """The same field, the other way round: a point short of nothing — nothing
    refused, nothing held unmeasured, no document read and unposted — says the
    set is everything, which is what makes the incomplete case readable."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan")),
           closing_balance_observed("chk", "1000.00", "2026-01-31",
                                    _p("doc-jan", 6))]
    result = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "net_worth"},
        today="2026-03-01")
    for f in result.figures:
        if f["what"].startswith(("net in", "assets in", "liabilities in")):
            assert f["boundary"] == {
                "whole": True,
                "cut": [{"kind": "currency", "value": "USD"}]}, f["what"]


def test_a_figure_nobody_declared_a_boundary_for_claims_none():
    """No default of "whole". A figure whose emitter said nothing about the set
    it was taken over must not pick up a claim nobody made — silence and "this
    is everything" are different sentences.

    Every read states one, so the silence this holds open is the one an
    emitter written later would leave."""
    said = figure("1", "a number nobody said the set of",
                  quantity=quantity.COUNT)
    assert said["boundary"] == {}


def test_a_whole_set_cannot_also_name_what_it_leaves_out():
    """The contradiction is refused where the emitter is written, not read as a
    disclosure by whoever places it."""
    from viva.tools.envelope import bounded
    assert bounded(whole=True) == {"whole": True}
    contradiction = "cannot also name what it leaves out"
    with pytest.raises(ValueError, match=contradiction):
        bounded(whole=True, counted=1, held=6)
    with pytest.raises(ValueError, match=contradiction):
        bounded(whole=True, selected=[{"kind": "category", "value": "x"}])
    with pytest.raises(ValueError, match=contradiction):
        bounded(whole=True,
                unmeasured=[{"account": "a", "reason": "refused",
                             "settled_by": "a statement"}])
    # Including the gap that names no account: a document read and not posted
    # is money the figure does not carry like any other.
    with pytest.raises(ValueError, match=contradiction):
        bounded(whole=True, unposted=1)
    with pytest.raises(ValueError, match="negative number of documents"):
        bounded(whole=False, unposted=-1)


def test_a_set_is_narrowed_only_in_a_way_the_vocabulary_names():
    """A way of narrowing nothing can say is a build failure here rather than a
    figure that reaches a person with a boundary nobody can read."""
    from viva.tools.envelope import bounded
    with pytest.raises(ValueError, match="is not narrowed by"):
        bounded(whole=False, selected=[{"kind": "colour", "value": "green"}])
    # And the same vocabulary, and the same checks, for the slices one figure
    # was taken over rather than the narrowing of the read it came from.
    with pytest.raises(ValueError, match="is not narrowed by"):
        bounded(whole=False, cut=[{"kind": "colour", "value": "green"}])
    with pytest.raises(ValueError,
                       match="says nothing about what it was narrowed to"):
        bounded(whole=False, cut=[{"kind": "tag", "value": ""}])
    # A cut is the one entry a whole figure may still carry, because naming
    # which slice a figure is is not a way of falling short of anything.
    assert bounded(whole=True, cut=[{"kind": "tag", "value": "pantry"}]) == {
        "whole": True, "cut": [{"kind": "tag", "value": "pantry"}]}
    with pytest.raises(ValueError, match="cannot also name what it leaves out"):
        bounded(whole=True, selected=[{"kind": "tag", "value": "pantry"}])
    with pytest.raises(ValueError,
                       match="says nothing about what it was narrowed to"):
        bounded(whole=False, selected=[{"kind": "category", "value": ""}])
    with pytest.raises(ValueError, match="covers more than there is"):
        bounded(whole=False, counted=7, held=6)
    with pytest.raises(ValueError,
                       match="an unnamed gap is one nobody can close"):
        bounded(whole=False, unmeasured=[{"account": "", "reason": "refused",
                                          "settled_by": "x"}])
    # A span is written from two days and everything else from one, so an entry
    # carrying the other number of them is refused rather than written short.
    with pytest.raises(ValueError,
                       match="carries the other number of them"):
        bounded(whole=False, selected=[{"kind": "period", "value": "2026-01-01"}])
    with pytest.raises(ValueError,
                       match="carries the other number of them"):
        bounded(whole=False, selected=[{"kind": "since", "value": "2026-01-01",
                                        "to": "2026-01-31"}])


def test_a_figure_names_each_axis_it_was_cut_by_once():
    """A cut is a set of axes, and one axis named twice is two narrowings of
    one thing offered as one set — no single set is what they describe, and
    which of the two the figure was taken over would be a guess. Refused where
    the emitter is written.

    Two axes at once is the ordinary case and is how a group of a narrowed read
    says it is the narrowing AND the group. Because the axes are unique, they
    have one written form — ordered by axis — so a set assembled in either
    order is the same declaration and compares equal to itself."""
    from viva.tools.envelope import bounded
    one_way = bounded(whole=False, cut=[{"kind": "merchant", "value": "one"},
                                        {"kind": "category", "value": "two"}])
    other_way = bounded(whole=False, cut=[{"kind": "category", "value": "two"},
                                          {"kind": "merchant", "value": "one"}])
    assert one_way["cut"] == [{"kind": "category", "value": "two"},
                              {"kind": "merchant", "value": "one"}]
    assert one_way == other_way
    with pytest.raises(ValueError, match="names each axis it was cut by once"):
        bounded(whole=False, cut=[{"kind": "tag", "value": "one"},
                                  {"kind": "tag", "value": "two"}])


def test_a_boundary_is_only_what_its_own_constructor_made():
    """Every check that makes a boundary true lives in one constructor, so a
    mapping assembled beside it has passed none of them. A figure takes what
    that constructor returned and nothing else."""
    from viva.tools.envelope import bounded
    unchecked = "passed none of the checks"
    with pytest.raises(TypeError, match=unchecked):
        figure("1", "a number", quantity=quantity.COUNT,
               boundary={"whole": True})
    with pytest.raises(TypeError, match=unchecked):
        figure("1", "a number", quantity=quantity.COUNT,
               boundary={"nonsense": 1})
    made = figure("1", "a number", quantity=quantity.COUNT,
                  boundary=bounded(whole=True))
    assert made["boundary"] == {"whole": True}


def test_a_boundary_is_never_shown_to_the_model():
    """A boundary is placed by the run beside the figure it belongs to, which
    is what makes it a property of the machine. Sending it instead would put
    the saying of it back inside a planner's choice — the arrangement this
    cycle exists to replace — and would pay for it on every remaining call of
    the turn."""
    from viva.tools.envelope import MODEL_FACING_FIGURE
    assert "boundary" not in MODEL_FACING_FIGURE
    result = ledger_tools.query_ledger(
        LedgerProjection(_owing_a_never_measured_loan()),
        {"entity": "balances"})
    assert any(f["boundary"] for f in result.figures), "there is one to hide"
    for shown in result.to_dict()["figures"]:
        assert "boundary" not in shown


def test_a_gap_nothing_can_place_leaves_no_side_claiming_it_is_whole():
    """Which side of a point an account belongs to is read from its ledger kind
    or from the root of its path. An entry with neither is still money the
    total does not carry, so it is named on the net figure and both sides stop
    claiming to be everything — rather than each of them claiming it because
    neither could be shown to be short."""
    placeable = {"missing": [{"account": "Liabilities:HomeLoan:X",
                              "would_fix": "a statement"}]}
    left_out, placed = ledger_tools._not_counted(placeable)
    assert placed and left_out["assets"] == []

    unplaceable = {"missing": [{"account": "somewhere", "would_fix": "a statement"}]}
    left_out, placed = ledger_tools._not_counted(unplaceable)
    assert not placed
    assert [item["account"] for item in left_out["net"]] == ["somewhere"]
    assert left_out["assets"] == [] and left_out["liabilities"] == []


def test_a_gap_nothing_can_place_stops_both_sides_of_the_figure(proj):
    """The wiring, not just the helper. Which side an account belongs to is
    read from its ledger kind or the root of its path, and a ruling leg carries
    neither check — the account it names reaches the point verbatim. A side
    that cannot be shown to be short of it must not say it is whole.

    Asserted on the figure, because a helper that returns the right answer into
    a total that ignores it is a guard nothing holds."""
    from viva.ledger.events import ruling_recorded
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "10000.00", "2026-01-01",
                                    _p("doc-jan")),
           simple_transaction("chk", "-2000.00", "HOMEPLACE FINANCE",
                              "2026-01-10", provenance=_p("doc-jan")),
           closing_balance_observed("chk", "8000.00", "2026-01-31",
                                    _p("doc-jan", 6)),
           # Two majors make the payment MIXED, so the point refuses a figure
           # for it; the asset leg names an account under no root at all.
           ruling_recorded(scope="merchant", subject="homeplace finance",
                           legs=[{"major": "asset", "account": "homeplace"},
                                 {"major": "expense",
                                  "account": "Expenses:Interest"}],
                           occurred_at="2026-02-01", by="human")]
    point = ledger_tools.networth.net_worth(LedgerProjection(evs), "2026-03-01")
    assert [row["account"] for row in point.missing] == ["homeplace"]
    result = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "net_worth"},
        today="2026-03-01")
    for f in result.figures:
        if f["what"].startswith(("net in", "assets in", "liabilities in")):
            assert f["boundary"]["whole"] is False, f["what"]
    # Named on the total that is certainly short of it, and on neither side,
    # because naming it on one would say which side it is and nothing does.
    net = next(f for f in result.figures if f["what"].startswith("net in"))
    holds = next(f for f in result.figures if f["what"].startswith("assets in"))
    assert [item["account"] for item in net["boundary"]["unmeasured"]] == ["homeplace"]
    assert "unmeasured" not in holds["boundary"]


def test_a_document_read_and_not_posted_stops_a_total_being_whole():
    """A statement held for review names money no figure here includes, and it
    may be about an account that does not exist yet — so it appears in nothing
    the point lists per account, and only the point's own held list carries it.
    A total stated beside one is not the whole of what it claims to be, and it
    is counted rather than left as a gap the field knows of and no sentence can
    reach."""
    from viva.ledger.events import statement_held
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan")),
           closing_balance_observed("chk", "1000.00", "2026-01-31",
                                    _p("doc-jan", 6))]
    settled = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "net_worth"},
        today="2026-03-01")
    assert all(f["boundary"] == {"whole": True,
                                 "cut": [{"kind": "currency", "value": "USD"}]}
               for f in settled.figures
               if f["what"].startswith("net in"))

    evs += [document_captured("doc-x", "x.pdf", 90, "bank_statement", 0.5,
                              "2026-02-01"),
            statement_held("doc-x", {"account_ref": "elsewhere"}, None, "gap",
                           "2026-02-01")]
    result = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "net_worth"},
        today="2026-03-01")
    for f in result.figures:
        if f["what"].startswith(("net in", "assets in", "liabilities in")):
            assert f["boundary"] == {
                "whole": False, "unposted": 1,
                "cut": [{"kind": "currency", "value": "USD"}]}, f["what"]


def test_every_grouping_called_partitioning_actually_partitions():
    """The list that decides whether one group can be the whole of a total is
    held to the property it names, by measurement rather than by reading it: a
    grouping partitions when its groups sum to the total.

    The fixture carries money in no tag and money in two, so a grouping that
    overlaps or drops cannot come out equal by accident. A name added to the
    list before the grouping exists would fall through to grouping by currency,
    which does partition — so the emitted group keys are checked to be the
    grouping that was asked for."""
    evs = _spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries",
         ("pantry", "weekly")),
        ("2026-01-06", "CITY TRANSIT", "-60.00", "transport", ()))
    proj = LedgerProjection(evs)
    by_currency = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "currency"}).data["by_group"]
    for group_by in ledger_tools._PARTITIONING:
        data = ledger_tools.query_ledger(
            proj, {"entity": "aggregate", "metric": "spending",
                   "group_by": group_by}).data
        assert data["group_by"] == group_by
        if group_by != "currency":
            assert set(data["by_group"]) != set(by_currency), (
                f"{group_by} produced the currency grouping's own keys — it is "
                "named in _PARTITIONING and nothing implements it")
        assert sum(Decimal(v) for v in data["by_group"].values()) \
            == Decimal(data["total"]), group_by

    # And the counter-case the list exists to exclude.
    tagged = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "tag"}).data
    assert "tag" not in ledger_tools._PARTITIONING
    assert sum(Decimal(v) for v in tagged["by_group"].values()) \
        != Decimal(tagged["total"])


def test_a_gap_names_a_remedy_exactly_where_one_exists():
    """Why something is out of a figure decides whether a remedy can be named,
    and the two are held to each other.

    A figure that was refused a number knows what it was refused for, so a gap
    of that reason without one is a disclosure with the useful half missing. An
    account nothing has measured has nothing to point at, so a remedy there
    would be invented — and permitting it generally is how a gap with no
    remedy at all becomes an ordinary shape."""
    from viva.tools.envelope import (GAP_REFUSED, GAP_UNOBSERVED, bounded)
    refused = bounded(whole=False, unmeasured=[
        {"account": "a", "reason": GAP_REFUSED, "settled_by": "a statement"}])
    assert refused["unmeasured"][0]["settled_by"] == "a statement"
    unobserved = bounded(whole=False, unmeasured=[
        {"account": "a", "reason": GAP_UNOBSERVED}])
    assert unobserved["unmeasured"][0]["settled_by"] == ""

    with pytest.raises(ValueError,
                       match="names what would close it, and this one does not"):
        bounded(whole=False,
                unmeasured=[{"account": "a", "reason": GAP_REFUSED}])
    with pytest.raises(ValueError,
                       match="has nothing to name, and this one names something"):
        bounded(whole=False, unmeasured=[{"account": "a",
                                          "reason": GAP_UNOBSERVED,
                                          "settled_by": "a statement"}])
    # No remedy alongside it, so only the vocabulary check can fire: a reason
    # nothing recognises paired with nothing to name would otherwise be caught
    # by the pairing rule and read as though the vocabulary were guarded.
    with pytest.raises(ValueError,
                       match="is not why something is out of a figure"):
        bounded(whole=False, unmeasured=[{"account": "a", "reason": "because"}])


def test_an_account_in_two_of_the_points_lists_is_one_gap_with_one_reason():
    """A liability a ruling brought into being and that was also opened as an
    account is in the point's refused list AND its unobserved list. Folding
    both in put two entries on one account whose reasons contradict each other
    — one naming a remedy, one saying none exists — so the field held both
    halves of a rule it enforces on every entry.

    The spoken sentence never showed it, because the run names an account once.
    The structured record is what a counterparty would be shown, and a claim
    carrying two reasons for one account is not one anybody can act on."""
    from viva.ledger.events import ASSERTED, ruling_recorded
    loan = "Liabilities:HomeLoan:Meridian"
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           account_opened(loan, "liability", "Home Loan", "USD", "2026-01-01",
                          origin=ASSERTED),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "10000.00", "2026-01-01",
                                    _p("doc-jan")),
           simple_transaction("chk", "-2000.00", "MERIDIAN LOAN SERVICING",
                              "2026-01-10", provenance=_p("doc-jan")),
           closing_balance_observed("chk", "8000.00", "2026-01-31",
                                    _p("doc-jan", 6)),
           ruling_recorded(scope="merchant", subject="meridian loan servicing",
                           legs=[{"major": "liability", "account": loan}],
                           occurred_at="2026-02-01", by="human")]
    proj = LedgerProjection(evs)
    point = ledger_tools.networth.net_worth(proj, "2026-03-01")
    assert loan in {row["account"] for row in point.missing}
    assert loan in {row["account"] for row in point.skipped}, (
        "the fixture no longer produces an account in both lists")

    result = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "net_worth"},
        today="2026-03-01")
    for f in result.figures:
        if not f["what"].startswith(("net in", "liabilities in")):
            continue
        gaps = f["boundary"]["unmeasured"]
        assert [item["account"] for item in gaps] == [loan], f["what"]
        # And the reason kept is the one that carries what would close it.
        assert gaps[0] == {"account": loan, "reason": "refused",
                           "settled_by": "the loan or mortgage statement"}


def test_a_boundary_says_how_many_documents_are_read_and_not_posted():
    """A gap the field counts and no sentence can mention is a gap a person is
    not told about. A held document has no account to name — it may be about
    one that does not exist yet — so it is said as a number of documents."""
    from viva.ledger.events import statement_held
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan")),
           closing_balance_observed("chk", "1000.00", "2026-01-31",
                                    _p("doc-jan", 6))]
    for did in ("doc-x", "doc-y"):
        evs += [document_captured(did, f"{did}.pdf", 90, "bank_statement", 0.5,
                                  "2026-02-01"),
                statement_held(did, {"account_ref": "elsewhere"}, None, "gap",
                               "2026-02-01")]
    result = ledger_tools.query_ledger(
        LedgerProjection(evs), {"entity": "aggregate", "metric": "net_worth"},
        today="2026-03-01")
    net = next(f for f in result.figures if f["what"].startswith("net in"))
    # Counted in the record, so the sentence has something to say.
    assert net["boundary"] == {"whole": False, "unposted": 2,
                               "cut": [{"kind": "currency", "value": "USD"}]}
