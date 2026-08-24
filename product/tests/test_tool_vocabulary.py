"""Tool vocabulary contracts."""

from _tool_test_support import *
from test_tool_contract import _probe_vault
from test_tool_limits import _every_declared_call, _ledger
from test_tool_scope import _spending_events

# ------------------------------------------------- the vault's own vocabulary


def test_every_grouping_offered_names_the_kind_of_slice_it_cuts_by():
    """A grouping a person can ask for and the read has no way of naming the
    slices of is a breakdown whose rows cannot say what they are about. The
    enum and the naming table are held to each other here, so a grouping added
    without one fails at build time rather than as a nameless row."""
    offered = set(ledger_tools.QUERY_LEDGER_PARAMS["properties"]
                  ["group_by"]["enum"])
    assert set(ledger_tools._GROUP_NAMES) == offered, (
        f"only-in-table={sorted(set(ledger_tools._GROUP_NAMES) - offered)}, "
        f"only-in-schema={sorted(offered - set(ledger_tools._GROUP_NAMES))}")
    from viva.tools.envelope import SELECTED_KINDS

    assert set(ledger_tools._GROUP_NAMES.values()) <= set(SELECTED_KINDS)


def test_a_spending_read_names_the_slice_of_every_group_under_every_grouping():
    """The property that makes the row renderer generic: whichever way a
    breakdown is cut, each of its group figures says which cut it is. So the
    thing that writes rows never has to know what it is looking at."""
    evs = _spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries",
         ("pantry", "weekly")),
        ("2026-01-06", "CITY TRANSIT", "-60.00", "transport", ()))
    proj = LedgerProjection(evs)
    # Read through a window, so no grouping's single group is the whole of the
    # read: a vault holds one currency, and a currency group of an unnarrowed
    # read genuinely IS everything, which is a different fact and has its own
    # test.
    window = {"window": {"from": "2026-01-01", "to": "2026-01-31"}}
    seen = set()
    for group_by, kind in ledger_tools._GROUP_NAMES.items():
        result = ledger_tools.query_ledger(
            proj, {"entity": "aggregate", "metric": "spending",
                   "group_by": group_by, "filters": window})
        assert result.ok, result.text
        grouped = [f for f in result.figures
                   if f["what"].startswith(f"spending — {group_by} ")]
        assert grouped, group_by
        seen.add(group_by)
        for fig in grouped:
            cut = fig["boundary"].get("cut") or []
            # A group of a narrowed read is the narrowing AND the group, so it
            # names both axes and is a different claim from the read's own
            # total.
            assert {item["kind"] for item in cut} == {kind, "period"}, (
                group_by, fig["what"])
            named = next(item for item in cut if item["kind"] == kind)
            assert named["value"] == fig["what"].split("'")[1]
            # And the narrowing of the read is a separate statement, still
            # made, so the two halves of a boundary do not stand in for each
            # other.
            assert [item["kind"] for item in fig["boundary"]["selected"]] \
                == ["period"]
        # The read's own total and count are the whole of what one filter
        # left, so the slices they name are that filter itself and nothing
        # further — which is what tells a total apart from a line of the same
        # read.
        for fig in result.figures:
            if fig not in grouped:
                assert fig["boundary"]["cut"] == fig["boundary"]["selected"], \
                    fig["what"]
    assert seen == set(ledger_tools._GROUP_NAMES)


def test_every_vocabulary_a_read_can_group_by_is_one_it_can_also_size():
    """A grouping is a vocabulary, so every grouping offered can be asked what
    labels it holds. A member with no way of being read is a question with no
    answer; the other way round is a mode nothing reaches."""
    offered = set(ledger_tools.QUERY_LEDGER_PARAMS["properties"]
                  ["group_by"]["enum"])
    assert set(ledger_tools._VOCABULARIES) == offered

    registry, proj = _probe_vault()
    for group_by in sorted(offered):
        result = registry.call("query_ledger", {"entity": "vocabulary",
                                                "group_by": group_by})
        assert result.ok, (group_by, result.text)
        assert result.data["vocabulary"] == group_by
        assert result.data["count"] == len(result.data["labels"])
        stated = [f for f in result.figures if f["quantity"] == quantity.COUNT]
        assert len(stated) == 1 and stated[0]["value"] == str(
            result.data["count"])
        assert not stated[0]["currency"], (
            "a number of labels is not an amount of anything")


def test_a_subcategory_vocabulary_counts_what_a_breakdown_groups_by():
    """The two questions differ for real reasons, and counting different kinds
    of thing is not one of them.

    A subcategory's identity in this vault is the pair, because two categories
    may each hold a "fees". Counting bare spellings would answer "how many do I
    have" with a number about something else — and would do it invisibly, since
    a person only sees the disagreement when they ask for the list too.

    The vault below holds exactly that collision.
    """
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan")),
           simple_transaction("chk", "-40.00", "ALPHA BANK", "2026-01-05",
                              provenance=_p("doc-jan")),
           simple_transaction("chk", "-60.00", "BETA GROCER", "2026-01-06",
                              provenance=_p("doc-jan")),
           simple_transaction("chk", "-20.00", "CITY RAIL", "2026-01-07",
                              provenance=_p("doc-jan")),
           closing_balance_observed("chk", "880.00", "2026-01-31",
                                    _p("doc-jan", 6)),
           merchant_enriched("alpha bank", "banking", subcategory="fees",
                             occurred_at="2026-02-02"),
           merchant_enriched("beta grocer", "groceries", subcategory="fees",
                             occurred_at="2026-02-02"),
           merchant_enriched("city rail", "transport", subcategory="rail",
                             occurred_at="2026-02-02")]
    proj = LedgerProjection(evs)
    held = ledger_tools.query_ledger(
        proj, {"entity": "vocabulary", "group_by": "subcategory"})
    spent = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "subcategory"})
    assert len(set(proj.known_subcategories())) == 2, (
        "this vault does not hold one label under two categories, so it cannot "
        "tell a count of labels from a count of subcategories")
    assert held.data["count"] == 3
    # Spelled by one function, so the two cannot drift into disagreeing about
    # what a subcategory is called.
    assert set(held.data["labels"]) == set(spent.data["by_group"])


def test_a_vocabulary_read_needs_to_be_told_which_vocabulary():
    registry, _proj = _probe_vault()
    result = registry.call("query_ledger", {"entity": "vocabulary"})
    assert not result.ok and result.refusal == "missing_group_by"
    for name in ledger_tools._VOCABULARIES:
        assert name in result.text


# ----------------------------------------- finding the label a name reaches

def _counterparty_vault():
    """One vault whose counterparty keys separate the tiers a lookup has.

    Under the key function the four descriptors below become `havenmart`,
    `cedar haven market`, `sunhaven bakery` and `brightline transit`. Against
    the name `haven` the first begins with it, the second holds it as a whole
    word, the third merely contains it and the fourth has nothing to do with
    it."""
    return LedgerProjection(_spending_events(
        ("2026-01-05", "HAVENMART", "-40.00", "", ()),
        ("2026-01-06", "CEDAR HAVEN MARKET", "-50.00", "", ()),
        ("2026-01-07", "SUNHAVEN BAKERY", "-60.00", "", ()),
        ("2026-01-08", "BRIGHTLINE TRANSIT", "-70.00", "", ())))


def _looked_up(proj, name, group_by="merchant"):
    return ledger_tools.query_ledger(
        proj, {"entity": "vocabulary", "group_by": group_by, "matching": name})


def test_a_name_reaches_the_label_it_is_exactly():
    """The first tier: what the caller wrote keys to a label the vault holds,
    and only that label comes back."""
    result = _looked_up(_counterparty_vault(), "Havenmart")
    assert result.ok
    assert result.data["labels"] == ["havenmart"]


def test_a_name_reaches_the_labels_that_begin_with_it_and_hold_it_as_a_word():
    """The other two tiers, and the order they come back in.

    A label whose key begins with the name is nearer than one merely carrying
    it as a word, so the beginnings come first. Both are labels this vault
    holds, which is what the caller then narrows by."""
    result = _looked_up(_counterparty_vault(), "Haven")
    assert result.ok
    assert result.data["labels"] == ["havenmart", "cedar haven market"]


def test_a_name_buried_inside_a_label_reaches_nothing():
    """The line the tiers draw, and the reason the search may be generous at
    all: a run of characters inside a word is not a thing the caller named, so
    it is not found. Generosity that went this far would be a pattern, and a
    pattern is not something the vault holds."""
    reached = _looked_up(_counterparty_vault(), "Haven").data["labels"]
    assert "sunhaven bakery" not in reached
    assert "brightline transit" not in reached


def test_a_name_that_reaches_nothing_still_answers_with_the_size_held():
    """A lookup that found nothing establishes no thing and still establishes
    the one number it always did — how many labels the vault holds — so it
    cites what it read rather than what it failed to find."""
    result = _looked_up(_counterparty_vault(), "nothing-by-that-name")
    assert result.ok and result.data["labels"] == []
    assert result.data["count"] == 4


def test_a_lookup_counts_the_whole_vocabulary_and_never_its_matches():
    """The count is the same number matched or not, and it declares the whole.

    A number over the labels a name reached would be a number about a set the
    narrowing vocabulary cannot name, so no such figure exists and the one
    that does says what it always said."""
    proj = _counterparty_vault()
    whole = ledger_tools.query_ledger(
        proj, {"entity": "vocabulary", "group_by": "merchant"})
    matched = _looked_up(proj, "Haven")
    for result in (whole, matched):
        stated = [f for f in result.figures if f["quantity"] == quantity.COUNT]
        assert len(stated) == 1
        assert stated[0]["value"] == "4"
        assert stated[0]["boundary"]["whole"] is True
    assert matched.data["count"] == whole.data["count"]


def test_a_capped_lookup_counts_what_it_reached_rather_than_what_is_held(
        monkeypatch):
    """The cap sentence says how many of what came back are named.

    Capping a lookup after it has narrowed makes the whole vocabulary's size
    the wrong number for that sentence: it would say a hundred labels were cut
    to forty when the name reached three."""
    from viva.tools import ledger_vocabulary
    monkeypatch.setattr(ledger_vocabulary, "MAX_LABELS", 1)
    result = _looked_up(_counterparty_vault(), "Haven")
    assert result.data["labels"] == ["havenmart"]
    assert result.caveats == [
        "The first 1 of 2 merchant label(s) a name reached are named here, "
        "closest match first; the count is the whole count."]


def test_a_lookup_answers_for_every_vocabulary_the_read_offers():
    """A mode gains an argument, not a mode of its own: whatever a vocabulary
    read can be asked for, it can be asked for by name."""
    proj = _counterparty_vault()
    for group_by in sorted(ledger_tools._VOCABULARIES):
        held = ledger_tools.query_ledger(
            proj, {"entity": "vocabulary", "group_by": group_by})
        assert held.ok
        by_name = _looked_up(proj, "nothing-by-that-name", group_by)
        assert by_name.ok, group_by
        assert by_name.data["labels"] == []
        assert by_name.data["count"] == held.data["count"]


def test_a_name_reaches_a_label_outside_the_counterparty_vocabulary():
    """The lookup is an argument to the vocabulary read rather than a mode of
    its own, so every vocabulary that read offers answers by name — not only
    the one whose labels are counterparties.

    A name written in the caller's own capitals reaches the label the vault
    holds, and so does one that is the start of a label. What comes back is
    labels this vault holds, which is what a follow-up then narrows on
    exactly."""
    proj = LedgerProjection(_spending_events(
        ("2026-01-05", "HAVENMART", "-40.00", "groceries", ("pantry",)),
        ("2026-01-06", "BRIGHTLINE TRANSIT", "-70.00", "transport",
         ("commute",))))
    for group_by, name, reached in (("category", "Groceries", ["groceries"]),
                                    ("category", "groc", ["groceries"]),
                                    ("tag", "pantry", ["pantry"]),
                                    ("account", "chk", ["chk"]),
                                    ("currency", "usd", ["USD"])):
        result = _looked_up(proj, name, group_by)
        assert result.ok, (group_by, name)
        assert result.data["labels"] == reached, (group_by, name)


def test_looking_a_name_up_is_refused_where_a_read_would_narrow_instead():
    """The lookup belongs to the read of labels. A read of money is not quietly
    made to do it, because what it would have to do is narrow on a pattern."""
    proj = _counterparty_vault()
    result = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "matching": "Haven"})
    assert not result.ok and result.refusal == "matching_unsupported"
    assert "vocabulary" in result.text


def test_a_counterparty_filter_takes_the_key_however_the_name_was_written():
    """The caller's value goes through the vault's own key function, so a name
    written in a person's own capitals and punctuation reaches the key their
    statements were filed under. This is not a search: it resolves to one key,
    and the read then narrows on that key exactly."""
    proj = _counterparty_vault()
    for written in ("havenmart", "Havenmart", "HAVENMART", "Havenmart."):
        result = ledger_tools.query_ledger(
            proj, {"entity": "aggregate", "metric": "spending",
                   "filters": {"merchant": written}})
        assert result.ok, (written, result.text)
        assert result.data["by_group"] == {"Uncategorized": "40.00"}


def test_a_counterparty_filter_refuses_a_name_that_is_not_a_key():
    """The generosity stops at discovery. A name that reaches two labels in a
    lookup narrows nothing: the filter is refused, and what the vault holds is
    named back."""
    result = ledger_tools.query_ledger(
        _counterparty_vault(), {"entity": "aggregate", "metric": "spending",
                                "filters": {"merchant": "Haven"}})
    assert not result.ok and result.refusal == "unknown_merchant"
    assert "havenmart" in result.data["known_merchants"]


def test_a_read_narrowed_by_a_counterparty_states_the_key_it_counted():
    """What is stated is what was counted. The narrowing a figure declares is
    the key the vault holds, never the spelling the filter arrived as, so the
    thing named beside a number and the thing the number was taken over are one
    string."""
    result = ledger_tools.query_ledger(
        _counterparty_vault(), {"entity": "transactions",
                                "filters": {"merchant": "Havenmart."}})
    assert result.ok
    selected = [item for f in result.figures
                for item in (f["boundary"] or {}).get("selected") or []
                if item["kind"] == ledger_tools.BY_MERCHANT]
    assert selected and {item["value"] for item in selected} == {"havenmart"}


def test_a_truncated_remedy_list_says_how_to_find_the_one_that_was_meant():
    """Where the list fits it is the whole answer and says nothing else. Where
    it does not, forty names in any order are not the useful thing — how to
    find the one that was meant is — so the last entry names the lookup and
    carries no value the caller supplied."""
    short = ledger_tools._known(["one", "two"], cap=2)
    assert short == ["one", "two"]

    long = ledger_tools._known([f"label-{n:03d}" for n in range(5)], cap=2)
    assert long[:2] == ["label-000", "label-001"]
    assert len(long) == 3
    assert "matching" in long[-1] and "vocabulary" in long[-1]


def test_how_many_labels_a_vault_holds_is_not_how_many_its_spending_uses():
    """The second question the origin asked, and why it needed a read of its
    own. A breakdown counts the labels this person's SPENDING falls into; the
    vocabulary counts the labels they have. They diverge for real reasons — a
    label carried only by money that is not spending is one of them — and
    answering the first question with the second is a real number about one
    thing put in a sentence about another.

    The vault below holds a sub category used by a transfer, which no spending
    breakdown will ever name."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           account_opened("sav", "depository", "Savings", "USD", "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01",
                                    _p("doc-jan")),
           simple_transaction("chk", "-40.00", "GREENFIELD MARKET",
                              "2026-01-05", provenance=_p("doc-jan")),
           simple_transaction("chk", "-100.00", "OWN SAVINGS SWEEP",
                              "2026-01-07", provenance=_p("doc-jan")),
           closing_balance_observed("chk", "860.00", "2026-01-31",
                                    _p("doc-jan", 6)),
           merchant_enriched("greenfield market", "groceries",
                             subcategory="supermarket",
                             occurred_at="2026-02-02"),
           merchant_enriched("own savings sweep", "transfers",
                             subcategory="internal",
                             occurred_at="2026-02-02"),
           category_assigned(
               movement_key("doc-jan", "chk", "2026-01-07", Decimal("-100.00"),
                            "OWN SAVINGS SWEEP", 0),
               "OWN SAVINGS SWEEP", "transfers", VERIFIED, "2026-02-03",
               nature="transfer")]
    proj = LedgerProjection(evs)
    held = ledger_tools.query_ledger(
        proj, {"entity": "vocabulary", "group_by": "subcategory"})
    spent = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "subcategory"})
    assert held.ok and spent.ok
    assert set(held.data["labels"]) == {"transfers / internal",
                                        "groceries / supermarket"}
    assert held.data["count"] > spent.data["groups"]["total"], (
        "this vault does not separate the two questions, so it proves nothing")
    # And the two numbers are told apart by what each says it is, not by which
    # sentence they happen to land in.
    counted = next(f for f in held.figures)
    assert counted["what"] == "subcategory labels held"
    assert not [f for f in spent.figures if f["what"] == counted["what"]]


# --------------------------------------------- a blank box is not a filter


def test_the_call_that_spent_a_whole_turn_now_reads_the_ledger_once(registry):
    """A call whose every optional box carries an empty string.

    The one field named in the refusal is `nature`, which is not a filter; no
    empty box is a fault. With that field dropped the same call reads the
    ledger and returns the grouping it asked for."""
    blob = {"entity": "aggregate", "metric": "spending",
            "group_by": "subcategory", "as_of": "",
            "filters": {"account": "", "category": "", "tag": "",
                        "merchant": "", "nature": "mixed", "currency": "",
                        "window": {"from": "", "to": ""}}}
    as_sent = registry.call("query_ledger", blob)
    assert not as_sent.ok and "filters.nature" in as_sent.text
    # Every other box in it was empty, and none of them is a problem any more.
    assert "filters.account" not in as_sent.text
    assert "as_of" not in as_sent.text

    blob["filters"].pop("nature")
    result = registry.call("query_ledger", blob)
    assert result.ok, result.text
    assert result.data["group_by"] == "subcategory"
    assert result.data["count"], "the read reached movements, not an empty set"


def test_an_empty_optional_box_narrows_nothing_and_is_said_to_narrow_nothing(
        registry):
    """The rule reaches the whole form, not the filters alone: an empty window
    edge, the empty window that is left, and the empty filters that held only
    it all go, and so does an empty `as_of`, which is neither a filter nor a
    date. What comes back is the read nobody narrowed."""
    whole = registry.call("query_ledger", {"entity": "aggregate",
                                           "metric": "spending"})
    blanks = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending", "as_of": "",
        "filters": {"account": "", "window": {"from": "", "to": ""}}})
    assert blanks.ok, blanks.text
    assert blanks.data == whole.data
    for f in blanks.figures:
        assert f["boundary"].get("selected", []) == []


def test_a_required_box_sent_empty_is_still_a_real_error(registry):
    """A required field is not made absent by being blank: the call is still
    missing the one thing it had to carry, and still refuses."""
    bare = registry.call("query_ledger", {"entity": ""})
    assert not bare.ok and "balances" in bare.text
    empty_expression = registry.call("compute", {"expression": "",
                                                 "inputs": {}})
    assert not empty_expression.ok
    assert empty_expression.refusal != "invalid_arguments", (
        "an empty required field was dropped and read as a missing one")


def test_an_open_map_of_caller_named_keys_is_never_reached_into(registry):
    """Where a schema names no fields, the keys are the caller's own and none
    of them is emptied. An operand bound to nothing refuses in the words of the
    tool that owns the expression."""
    result = registry.call("compute", {"expression": "a", "inputs": {"a": ""}})
    assert not result.ok and result.refusal == "bad_input"
    assert "'a'" in result.text


def test_a_misspelled_filter_still_refuses_however_empty_it_arrived(registry):
    """Only fields the form names are emptied. A field the form does not name
    still refuses by name however it arrived — dropping it silently would be a
    filter accepted and ignored."""
    result = registry.call("query_ledger", {"entity": "transactions",
                                            "filters": {"merchnat": ""}})
    assert not result.ok and "merchnat" in result.text


def test_a_filter_refusal_names_every_problem_it_can_see(registry):
    """A call that got several filter values wrong is told all of them at
    once, each fault tagged, and what the vault holds instead is named for
    each."""
    result = registry.call("query_ledger", {
        "entity": "transactions",
        "filters": {"account": "no-such-account", "category": "unicorns",
                    "tag": "nowhere", "merchant": "nobody",
                    "currency": "XTS",
                    "window": {"from": "soon", "to": "later"}}})
    assert not result.ok and result.refusal == ledger_tools.MANY_BAD_FILTERS
    assert result.data["filter_problems"] == [
        "unknown_account", "unknown_category", "unknown_tag",
        "unknown_merchant", "unknown_currency", "bad_date", "bad_date"]
    for named in ("no-such-account", "unicorns", "nowhere", "nobody", "XTS",
                  "soon", "later"):
        assert named in result.text
    # And what it holds instead is named for each one, as it always was.
    assert {"known_accounts", "known_categories", "known_tags",
            "known_merchants", "known_currencies"} <= set(result.data)


def test_one_bad_filter_still_refuses_by_its_own_name(registry):
    """A single fault keeps its own machine tag rather than the many-fault
    one."""
    result = registry.call("query_ledger", {"entity": "transactions",
                                            "filters": {"tag": "nowhere"}})
    assert not result.ok and result.refusal == "unknown_tag"
    assert "pantry" in result.data["known_tags"]


# --------------------------------------- a counterparty with no name at all


@pytest.mark.parametrize("descriptor", ["", "   "])
def test_a_movement_naming_no_counterparty_is_named_under_every_grouping(
        descriptor):
    """A movement whose description is blank — or blank once its spaces come
    off — names no counterparty, and lands in a named group under every
    spending grouping.

    Both shapes of blank are covered: an empty key, which is refused where a
    figure's scope is written, and a whitespace-only one, which is not empty
    and so is refused nowhere. Neither reaches an answer as a group name, a
    figure's scope or an identifier, and neither is dropped from the
    grouping."""
    proj = LedgerProjection(_spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries", ()),
        ("2026-01-06", descriptor, "-90.00", "", ())))
    for group_by in ledger_tools._GROUP_NAMES:
        result = ledger_tools.query_ledger(
            proj, {"entity": "aggregate", "metric": "spending",
                   "group_by": group_by})
        assert result.ok, (group_by, result.text)
        for key in result.data["by_group"]:
            assert key.strip(), (group_by, repr(key))
        for f in result.figures:
            for cut in f["boundary"].get("cut") or []:
                assert cut["value"].strip(), (group_by, f["what"])
        for item in result.identifiers or []:
            assert str(item.get("example", "x")).strip(), (group_by, item)
    by_merchant = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "merchant"})
    assert by_merchant.data["by_group"] == {
        "greenfield market": "40.00",
        ledger_tools.UNNAMED_MERCHANT: "90.00"}
    assert by_merchant.data["total"] == "130.00"


@pytest.mark.parametrize("descriptor", ["", "   "])
def test_the_groups_of_a_spending_read_add_up_to_the_total_it_states(
        descriptor):
    """The named groups plus the tail are the total, to the cent, with a
    movement naming no counterparty among them.

    The tail is where a group too small to be named goes, so both halves are
    added back before the sum is compared with the headline."""
    movements = [(f"2026-01-{day:02d}", f"MERCHANT {day}", "-10.00", "", ())
                 for day in range(1, 13)]
    movements.append(("2026-01-20", descriptor, "-500.00", "", ()))
    proj = LedgerProjection(_spending_events(*movements))
    result = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "merchant"})
    assert result.ok, result.text
    # The cap is engaged and the unnamed group ranks inside it, which is the
    # only arrangement that reaches the code that writes a group's scope: a
    # small one rides the tail and would pass a weaker test untouched.
    assert result.data["groups"]["named"] == ledger_tools.MAX_GROUPS
    assert result.data["by_group"][ledger_tools.UNNAMED_MERCHANT] == "500.00"

    named = sum(Decimal(v) for v in result.data["by_group"].values())
    tail = next(c for c in result.caveats if "smaller group" in c)
    hidden = Decimal(tail.split("worth ")[1].split()[1].replace(",", ""))
    assert named + hidden == Decimal(result.data["total"])
    assert result.data["groups"]["total"] == len(movements)


def test_no_figure_claims_the_whole_of_a_spending_read_it_only_part_covers():
    """Under a partitioning grouping, a figure whose boundary says `whole` is
    the whole: its value is the read's own total, or its count.

    `whole` says the set the figure was taken over and the quantity it declares
    are the same thing, so a movement naming no counterparty may not be missing
    from the groups any figure claims to cover."""
    proj = LedgerProjection(_spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries", ()),
        ("2026-01-06", "  ", "-90.00", "", ())))
    total = Decimal("130.00")
    for group_by in ledger_tools._PARTITIONING:
        result = ledger_tools.query_ledger(
            proj, {"entity": "aggregate", "metric": "spending",
                   "group_by": group_by})
        assert result.ok, (group_by, result.text)
        assert Decimal(result.data["total"]) == total
        for f in result.figures:
            if not f["boundary"].get("whole"):
                continue
            assert Decimal(f["value"]) in (total, Decimal(result.data["count"]))


def test_the_unnamed_group_is_a_scope_and_never_a_name_to_ask_again_with():
    """The residual label names a group and no entity, so nothing offers it
    back as a counterparty to ask about — and sent as a merchant filter it
    refuses, like any other value the vault does not hold."""
    proj = LedgerProjection(_spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries", ()),
        ("2026-01-06", "", "-90.00", "", ())))
    result = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "group_by": "merchant"})
    assert ledger_tools.UNNAMED_MERCHANT in result.data["by_group"]
    assert ledger_tools.UNNAMED_MERCHANT not in [
        item.get("example") for item in result.identifiers]
    # And the label the read chose is one no descriptor can normalise into, so
    # it can never sit on top of a counterparty someone really paid.
    refused = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "filters": {"merchant": ledger_tools.UNNAMED_MERCHANT}})
    assert not refused.ok and refused.refusal == "unknown_merchant"


@pytest.mark.parametrize("descriptor", ["", "   "])
def test_the_counterparty_vocabulary_never_counts_nobody(descriptor):
    """The counterparty vocabulary — the labels the vault holds, which is a
    different question from any breakdown — lists and counts no blank label,
    whether it is empty or only spaces."""
    proj = LedgerProjection(_spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries", ()),
        ("2026-01-06", descriptor, "-90.00", "", ())))
    held = ledger_tools.query_ledger(proj, {"entity": "vocabulary",
                                            "group_by": "merchant"})
    assert held.ok, held.text
    assert held.data["labels"] == ["greenfield market"]
    assert held.data["count"] == 1
    assert all(label.strip() for label in held.data["labels"])


def test_a_blank_counterparty_is_not_one_this_vault_holds():
    """A blank merchant filter refuses like any other counterparty the vault
    does not hold, rather than selecting the movements whose description says
    nothing.

    Called past the registry, where an empty box never reaches a tool: this is
    the second guard, and the one that answers a key made only of spaces."""
    proj = LedgerProjection(_spending_events(
        ("2026-01-05", "GREENFIELD MARKET", "-40.00", "groceries", ()),
        ("2026-01-06", "", "-90.00", "", ())))
    for blank in ("", "   "):
        result = ledger_tools.query_ledger(
            proj, {"entity": "aggregate", "metric": "spending",
                   "filters": {"merchant": blank}})
        assert not result.ok and result.refusal == "unknown_merchant"
        assert all(key.strip() for key in result.data["known_merchants"])


# ------------------------------ what a narrowing says, and what may narrow


def test_a_read_narrowed_by_tag_says_so_under_the_answer(registry):
    """A read narrowed to a tag places the sentence saying so under the
    answer, not only in a payload a model may skip."""
    from viva import persona

    shape = _shape(("You spent {total}.", [("total", "money", "spending",
                                            "tag")]))
    result = run("what did I spend on pantry things?",
                 _script(shape,
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "spending",
                                           "filters": {"tag": "pantry"}}),
                         bind=lambda r: {
                             "total": {"figure": _fig(r, "total spending")}}),
                 registry)
    assert result.answered, result.detail
    assert persona.moment("boundary_selected_tag",
                          tag=render.label("pantry")) in result.text


def test_a_read_narrowed_by_currency_says_so_under_the_answer(registry):
    """The same claim for the other filter that narrowed and stated nothing."""
    from viva import persona

    shape = _shape(("You spent {total}.", [("total", "money", "spending",
                                            "currency")]))
    result = run("what did I spend in dollars?",
                 _script(shape,
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "spending",
                                           "filters": {"currency": "USD"}}),
                         bind=lambda r: {
                             "total": {"figure": _fig(r, "total spending")}}),
                 registry)
    assert result.answered, result.detail
    assert persona.moment("boundary_selected_currency",
                          currency=render.label("USD")) in result.text


def test_the_summary_read_records_what_narrowed_it(registry):
    """Every figure the summary read emits says what set it was taken over: a
    read narrowed to one counterparty records that counterparty on each of
    them, and an unnarrowed read declares the whole and names no narrowing."""
    narrowed = registry.call("query_ledger",
                             {"entity": "transactions",
                              "filters": {"merchant": "greenfield market"}})
    assert narrowed.ok, narrowed.text
    assert narrowed.figures
    for fig in narrowed.figures:
        assert fig["boundary"], fig["what"]
        assert fig["boundary"]["whole"] is False, fig["what"]
        assert {"kind": "merchant", "value": "greenfield market"} in \
            fig["boundary"]["selected"], fig["what"]

    whole = registry.call("query_ledger", {"entity": "transactions"})
    for fig in whole.figures:
        if fig["boundary"]["whole"]:
            assert "selected" not in fig["boundary"], fig["what"]


def test_a_read_that_covers_everything_never_also_names_a_narrowing(registry):
    """No figure both declares it covers everything and names what narrowed it,
    over every supported combination of filters on these reads.

    That pairing is the contradiction the boundary constructor refuses, and it
    would raise out of a read, through a registry whose module states that a
    call never raises."""
    for filters in ({}, {"account": "chk"}, {"currency": "USD"},
                    {"window": {"from": "2026-01-01", "to": "2026-01-31"}},
                    {"account": "chk", "currency": "USD"}):
        for args in ({"entity": "transactions", "filters": filters},
                     {"entity": "balances",
                      "filters": {k: v for k, v in filters.items()
                                  if k in ("account", "currency")}}):
            result = registry.call("query_ledger", args)
            assert result.ok, (args, result.text)
            for fig in result.figures:
                bound = fig["boundary"]
                assert not (bound["whole"] and bound.get("selected")), (
                    args, fig["what"])


def test_each_group_of_the_summary_read_names_its_own_slice(registry):
    """The read cuts the same movements two ways at once, and each figure says
    which slice it is: a per-account figure names its account, a per-month
    figure names its month. The read-level figures name no slice."""
    result = registry.call("query_ledger", {"entity": "transactions"})
    cuts = {fig["what"]: fig["boundary"].get("cut")
            for fig in result.figures if fig["boundary"].get("cut")}
    assert cuts["net movement on chk"] == [{"kind": "account",
                                            "value": "chk"}]
    assert [c["kind"] for c in cuts["net movement in 2026-01"]] == ["period"]
    # The five read-level figures name no slice: they are the read, not a cut
    # of it.
    assert not result.figures[0]["boundary"].get("cut")


def test_a_months_slice_is_the_calendar_month_not_what_moved_in_it(registry):
    """A month figure's slice is the calendar month's own first and last day,
    not the first and last day something moved in it — so two vaults' January
    is the same period."""
    result = registry.call("query_ledger", {"entity": "transactions"})
    (month,) = [fig for fig in result.figures
                if fig["what"] == "net movement in 2026-01"]
    assert month["boundary"]["cut"] == [{"kind": "period",
                                         "value": "2026-01-01",
                                         "to": "2026-01-31"}]
    # The movements themselves run from the fifth to the twentieth, so a slice
    # read off the data would have said so.
    days = sorted(r["date"] for r in registry.call(
        "list_movements", {"filters": {"account": "chk"}}).data["movements"])
    assert days[0] > "2026-01-01" and days[-1] < "2026-01-31"


def test_a_listed_movement_is_whole_and_names_no_slice(registry):
    """One movement is all of what the quantity `movement` measures, so a row
    figure declares the whole and carries no slice: a row is a member of the
    set rather than a cut of it, and no way of narrowing a set to a single
    movement exists to name it by."""
    result = registry.call("list_movements",
                           {"filters": {"merchant": "greenfield market"}})
    rows = [f for f in result.figures if f["quantity"] == quantity.MOVEMENT]
    assert rows
    for fig in rows:
        assert fig["boundary"] == {"whole": True}, fig["what"]


def test_a_detailed_read_records_its_narrowing_on_its_count(registry):
    """The count over the matching set carries the read's narrowing. It is the
    only figure of that read that can: every other one is a complete
    movement."""
    result = registry.call("list_movements",
                           {"filters": {"merchant": "greenfield market"}})
    (count,) = [f for f in result.figures if f["quantity"] == quantity.COUNT]
    assert count["value"] == str(result.data["total"])
    assert count["boundary"]["selected"] == [{"kind": "merchant",
                                              "value": "greenfield market"}]


def test_a_detailed_read_names_a_counterparty_by_the_key_its_scope_declares(
        registry):
    """A read that returns rows names the counterparty it was narrowed to by
    the same string its own count figure declares that narrowing as.

    A counterparty answers to two names — the key every filter and every
    grouping uses, and whichever spelling one statement wrote — and a read that
    established the thing under one while declaring its scope under the other
    offers a sentence no comparison of the two can pass. So the entity carries
    the key.

    The spelling is not lost by this: it stays on each row, which is what a
    person reading their movements reads."""
    result = registry.call("list_movements",
                           {"filters": {"merchant": "greenfield market"}})
    (count,) = [f for f in result.figures if f["quantity"] == quantity.COUNT]
    (cut,) = [c for c in count["boundary"]["cut"] if c["kind"] == "merchant"]
    named = [i for i in result.identifiers if i["kind"] == "merchant"]
    assert named, "the read established no counterparty to refer to"
    assert [i["example"] for i in named] == [cut["value"]]
    # And the statement's own spelling still travels, on the rows themselves.
    assert result.data["movements"]
    assert all(row["description"] != cut["value"]
               for row in result.data["movements"])


def test_every_read_names_a_counterparty_the_same_way(proj, registry):
    """One counterparty reached through three different reads is one label.

    The rows read, the spending grouping and the counterparty vocabulary each
    establish counterparties; a thing established twice under two labels is two
    things to anything that matches a number against what it is about."""
    rows = registry.call("list_movements",
                         {"filters": {"merchant": "greenfield market"}})
    grouped = registry.call("query_ledger", {"entity": "aggregate",
                                             "metric": "spending",
                                             "group_by": "merchant"})
    held = registry.call("query_ledger", {"entity": "vocabulary",
                                          "group_by": "merchant"})
    named = {}
    for result in (rows, grouped, held):
        named[result.tool, str(result.data.get("vocabulary", ""))] = {
            i["example"] for i in result.identifiers if i["kind"] == "merchant"}
    listed, breakdown, vocabulary = named.values()
    assert listed and listed <= breakdown and listed <= vocabulary


def test_a_capped_list_says_so_to_a_person_and_not_only_to_its_caller():
    """A read that shows fifty of three hundred discloses the cap in a caveat,
    which the run places under the answer. The half naming which filters would
    reach the rest is instruction to whoever called the read and stays in the
    coverage line."""
    registry = _ledger(per_month=30)
    capped = registry.call("list_movements", {"filters": {"account": "acct0"}})
    said = f"Showing {capped.data['shown']} of {capped.data['total']} matching movement(s)."
    assert said in capped.caveats
    assert "Narrow by" not in " ".join(capped.caveats)
    assert "Narrow by" in capped.coverage

    uncapped = registry.call("list_movements",
                             {"filters": {"account": "acct0",
                                          "window": {"from": "2025-01-01",
                                                     "to": "2025-01-02"}}})
    assert uncapped.data["shown"] == uncapped.data["total"]
    assert not [c for c in uncapped.caveats if "Showing" in c]


def _narrowable(*accounts):
    """A vault where every filter the reads honour names something it holds: a
    counterparty with a category and a tag, a measured holding, an attributed
    income, and movements inside one window. Every value in it is synthetic."""
    evs = [account_opened(a, "investment", f"Account {n}", "USD", "2026-01-01")
           for n, a in enumerate(accounts)]
    first = accounts[0]
    evs += [
        document_captured("doc-one", "one.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed(first, "1000.00", "2026-01-01", _p("doc-one")),
        simple_transaction(first, "-40.00", "NORTHWIND SUPPLY", "2026-01-05",
                           provenance=_p("doc-one")),
        transaction_recorded([Posting(first, Decimal("500.00"), VERIFIED),
                              Posting("Income:Salary", Decimal("-500.00"),
                                      VERIFIED)],
                             "PAYROLL", "2026-01-10", provenance=_p("doc-one")),
        closing_balance_observed(first, "1460.00", "2026-01-31",
                                 _p("doc-one", 6)),
        position_observed(first, "ALPHA FUND", "10", "1500.00", "USD",
                          "2026-01-31", provenance=_p("doc-one")),
        merchant_enriched("northwind supply", "supplies",
                          subcategory="hardware", occurred_at="2026-02-02"),
    ]
    key = movement_key("doc-one", first, "2026-01-05", Decimal("-40.00"),
                       "NORTHWIND SUPPLY", 0)
    evs.append(movement_tagged(key, ["pantry"], "2026-02-05"))
    return default_registry(LedgerProjection(evs))


def test_no_holding_is_ever_the_whole_of_what_a_balance_measures():
    """No per-holding figure declares whole, on any vault under any combination
    of filters, including a vault of one holding: a holding is a member of the
    set the read enumerated, and the cash beside it is money this read cannot
    see. A whole figure places no scope sentence, so the claim would delete
    every clause the answer would otherwise carry.

    Not whole is still a declaration, and different from an empty boundary. The
    count beside them is a different quantity — how many holdings were measured
    — and over an unnarrowed read that is all of them."""
    for accounts in (("acct-one",), ("acct-one", "acct-two")):
        registry = _narrowable(*accounts)
        for filters in ({}, {"account": accounts[0]}, {"currency": "USD"},
                        {"account": accounts[0], "currency": "USD"}):
            result = registry.call("query_ledger", {"entity": "holdings",
                                                    "filters": filters})
            where = (accounts, sorted(filters))
            assert result.ok, (where, result.text)
            values = [f for f in result.figures
                      if f["quantity"] == quantity.BALANCE]
            assert values, where
            for fig in values:
                assert fig["boundary"]["whole"] is False, (where, fig["what"])
                # Not whole is a declaration; an empty boundary is a read that
                # said nothing. This read says something either way.
                assert fig["boundary"] != {}, (where, fig["what"])
            (count,) = [f for f in result.figures
                        if f["quantity"] == quantity.COUNT]
            assert count["boundary"]["whole"] is (not filters), where


def _stored_date(date: str):
    """A registry over a vault holding one movement whose stored date is the
    text given, which no write path in front of the read validates."""
    evs = [account_opened("acct-one", "depository", "Account One", "USD",
                          "2026-01-01"),
           document_captured("doc-one", "one.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           simple_transaction("acct-one", "-10.00", "NORTHWIND SUPPLY", date,
                              provenance=_p("doc-one"))]
    return default_registry(LedgerProjection(evs))


def test_a_group_whose_name_is_no_calendar_month_names_no_slice():
    """A group named from a stored date that is no calendar month yields no
    span, so that figure carries no slice and the read comes back as an
    envelope rather than an exception through a registry whose module states
    that a call never raises. A group that is a month names its own first and
    last day."""
    for date in ("2026-13-01", "sometime last winter"):
        registry = _stored_date(date)
        result = registry.call("query_ledger", {"entity": "transactions"})
        assert result.ok, (date, result.text)
        months = [f for f in result.figures
                  if f["what"].startswith("net movement in ")]
        assert months, date
        for fig in months:
            assert "cut" not in fig["boundary"], (date, fig["what"])
    # And a month that is one still names its own first and last day.
    result = _stored_date("2026-02-09").call("query_ledger",
                                             {"entity": "transactions"})
    (month,) = [f for f in result.figures
                if f["what"].startswith("net movement in ")]
    assert month["boundary"]["cut"] == [{"kind": "period",
                                         "value": "2026-02-01",
                                         "to": "2026-02-28"}]


def _income_vault(*currencies):
    """A projection with one account per currency named and one attributed
    income, as `(projection, registry)`. The transaction fold carries the
    real account leg's currency onto its synthetic income counter-leg."""
    evs = [account_opened(f"acct-{n}", "depository", f"Account {n}", currency,
                          "2026-01-01")
           for n, currency in enumerate(currencies)]
    evs += [
        document_captured("doc-one", "one.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        transaction_recorded([Posting("acct-0", Decimal("500.00"), VERIFIED),
                              Posting("Income:Salary", Decimal("-500.00"),
                                      VERIFIED)],
                             "PAYROLL", "2026-01-10", provenance=_p("doc-one")),
    ]
    proj = LedgerProjection(evs)
    return proj, default_registry(proj)


def test_income_cuts_by_a_currency_only_where_the_vault_holds_it():
    """The income read writes a slice only for a key the vault's own currency
    vocabulary knows — the set a `currency` filter is validated against.

    The counter account itself carries no independent currency; its transaction
    line carries the currency of the real account leg. Another account in a
    different currency must not make that known line ambiguous."""
    proj, registry = _income_vault("USD")
    held = {info.currency for info in proj.account_infos() if info.currency}
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "income"})
    assert result.ok, result.text
    (one,) = [f for f in result.figures if f["quantity"] == quantity.INCOME]
    assert one["boundary"]["cut"] == [{"kind": "currency",
                                       "value": next(iter(held))}]

    proj, registry = _income_vault("USD", "EUR")
    held = {info.currency for info in proj.account_infos() if info.currency}
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "income"})
    assert result.ok, result.text
    figures = [f for f in result.figures if f["quantity"] == quantity.INCOME]
    assert figures
    assert set(result.data["by_currency"]) == {"USD"}
    for fig in figures:
        assert fig["boundary"]["cut"] == [{"kind": "currency",
                                             "value": "USD"}]


def _read_call(kind: str, filters: dict) -> tuple:
    """The call that reaches one entry of the read-to-filters table, as
    `(tool, args)`. A read added to that table is reached by this without the
    test being touched."""
    if kind == ledger_tools.LIST_TOOL:
        return kind, {"filters": filters}
    entity, _, metric = kind.partition(":")
    args = {"entity": entity, "filters": filters}
    if metric:
        args["metric"] = metric
    return "query_ledger", args


# What a filter must come back recorded as. Written out rather than read from
# the map the reads narrow by, so a read and the test of it cannot agree by
# construction.
_RECORDED_AS = {"account": "account", "category": "category", "tag": "tag",
                "merchant": "merchant", "currency": "currency",
                "window": "period"}


def test_every_filter_a_read_honours_can_be_said_in_the_answer():
    """A read that narrows a set records what it narrowed it to.

    Every read is called with every filter it honours, singly and all at once,
    on a vault of one account and again on a vault of two. Each call must come
    back as an envelope carrying at least one figure that records the
    narrowing. This asks the reads rather than comparing tables of names, which
    cannot see a read that honours a filter and declares nothing about it.

    Calling is also what catches a read raising: a figure declaring it covers
    everything cannot also name what narrowed it, and a read computing those
    two from different filters raises a ValueError out through a registry whose
    module states that a call never raises — on a vault of one account, or one
    where every account is in the currency asked for, both called here."""
    for accounts in (("acct-one",), ("acct-one", "acct-two")):
        registry = _narrowable(*accounts)
        values = {"account": accounts[0], "category": "supplies",
                  "tag": "pantry", "merchant": "northwind supply",
                  "currency": "USD",
                  "window": {"from": "2026-01-01", "to": "2026-01-31"}}
        for kind, honoured in sorted(ledger_tools._SUPPORTED_FILTERS.items()):
            if not honoured:
                continue
            for name in sorted(honoured):
                filters = {name: values[name]}
                # A detailed read answers only a question narrow enough to name
                # one, so a filter that does not narrow it is paired with one
                # that does; both are still recorded.
                if (kind == ledger_tools.LIST_TOOL
                        and not set(filters) & set(ledger_tools.NARROWING)):
                    filters["account"] = accounts[0]
                tool, args = _read_call(kind, filters)
                result = registry.call(tool, args)
                where = (accounts, kind, name)
                assert result.ok, (where, result.refusal, result.text)
                assert result.figures, where
                said = [f for f in result.figures
                        if any(entry["kind"] == _RECORDED_AS[name]
                               for entry in f["boundary"].get("selected") or ())]
                assert said, (where, [f["boundary"] for f in result.figures])
                for fig in result.figures:
                    assert fig["boundary"], (where, fig["what"])
            # And every filter it honours at once, because a combination is a
            # supported call too, and it is the one that narrows hardest.
            tool, args = _read_call(kind, {name: values[name]
                                           for name in honoured})
            result = registry.call(tool, args)
            where = (accounts, kind, "every filter at once")
            assert result.ok, (where, result.refusal, result.text)
            assert result.figures, where
            for name in honoured:
                assert any(entry["kind"] == _RECORDED_AS[name]
                           for f in result.figures
                           for entry in f["boundary"].get("selected") or ()), (
                    where, name)


def test_the_form_the_reads_and_the_writing_table_offer_the_same_filters():
    """Three sets of names agree: the filters some read honours, the filters
    the form offers, and the filters the writing table can word.

    This compares names and calls no read, so it says nothing about whether a
    read records what it narrowed to. `window` is the one filter absent from
    the writing table on purpose: it yields three different narrowings
    depending on which of its edges are given, and names them where the
    narrowing is assembled."""
    honoured = set().union(*ledger_tools._SUPPORTED_FILTERS.values())
    offered = set(ledger_tools.QUERY_LEDGER_PARAMS["properties"]["filters"]
                  ["properties"])
    sayable = set(ledger_tools._FILTER_NAMES) | {"window"}
    assert honoured <= sayable, sorted(honoured - sayable)
    assert offered == honoured, (sorted(offered - honoured),
                                 sorted(honoured - offered))


def test_native_query_schema_discriminates_filters_by_read_family():
    """Invalid combinations are absent from the form a native model sees.

    The deterministic dispatcher still refuses a bypassed invalid call; this
    test is about preventing the model from being offered one as valid.
    """
    branches = ledger_tools.QUERY_LEDGER_PARAMS["oneOf"]

    def branch(entity, metric=""):
        return next(item for item in branches
                    if item["properties"]["entity"]["enum"] == [entity]
                    and (not metric or
                         item["properties"]["metric"]["enum"] == [metric]))

    assert "filters" not in branch("vocabulary")["properties"]
    assert "filters" not in branch("aggregate", "net_worth")["properties"]
    assert set(branch("balances")["properties"]["filters"]["properties"]) == {
        "account", "currency"}
    assert "window" in branch("transactions")["properties"]["filters"][
        "properties"]


def test_nature_is_not_a_filter_any_read_offers(proj, registry):
    """`nature` is not a filter: the form refuses it as an unknown field, and
    each of the three reads that once honoured it refuses it as unsupported."""
    refused = registry.call("query_ledger", {"entity": "transactions",
                                             "filters": {"nature": "spending"}})
    assert not refused.ok and "filters.nature" in refused.text
    # And past the form, for a caller that never read it: each of the three
    # reads that honoured it says it does not.
    summary = ledger_tools.query_ledger(
        proj, {"entity": "transactions", "filters": {"nature": "spending"}})
    assert summary.refusal == "filter_unsupported"
    spending = ledger_tools.query_ledger(
        proj, {"entity": "aggregate", "metric": "spending",
               "filters": {"nature": "spending"}})
    assert spending.refusal == "filter_unsupported"
    rows = ledger_tools.list_movements(
        proj, {"filters": {"account": "chk", "nature": "spending"}})
    assert rows.refusal == "filter_unsupported"


# ------------------------- the read's own account of why the turn had nothing


def _turn(*steps):
    """A planner that takes the given steps in order, one per call.

    Every step the runner asks for consumes one — a shape, a read, or the
    delivery that ends the turn — so a test says the trajectory it means rather
    than counting what has come back."""
    remaining = iter(steps)

    def planner(context):
        return next(remaining)
    return planner


_SPENT = _shape(("You spent {total}.",
                [("total", "money", "spending", "whole")]))
_ALSO_HELD = _shape(("You spent {total}.",
                    [("total", "money", "spending", "whole")]),
                    ("You hold {balance}.",
                     [("balance", "money", "balance", "whole")]))

# A read refused for a category the vault does not hold, and one that succeeds.
_UNHELD_CATEGORY = {"tool": "query_ledger",
                    "args": {"entity": "aggregate", "metric": "spending",
                             "filters": {"category": "Zzz"}}}
_A_READ_THAT_WORKS = {"tool": "query_ledger", "args": {"entity": "balances"}}
_DELIVER_NOTHING = {"bindings": {}}


def test_a_turn_that_established_nothing_says_why_the_last_read_stopped(registry):
    """The verdict in the pack's words for the turn's tag, then the cause in the
    pack's words for the read's. Both were reviewed before the turn began, and
    the value the read was called with is in neither."""
    from viva.persona import moment

    result = run("what did I spend on that?",
                 _turn({"shape": _SPENT}, _UNHELD_CATEGORY, _DELIVER_NOTHING),
                 registry)
    assert result.refusal == "nothing_established"
    assert result.diagnosis == "unknown_category"
    assert result.text == (moment("refusal_nothing_established") + " "
                           + moment("diagnosis_unknown_category"))
    assert "Zzz" not in result.text
    assert result.to_dict()["diagnosis"] == "unknown_category"


def test_a_turn_that_spent_its_budget_says_why_the_last_read_stopped(registry):
    """The same failure told slower: the calls ran out on reads that refused,
    and which of them refused is the best account of the turn."""
    result = run("what did I spend on that?",
                 _turn({"shape": _SPENT}, _UNHELD_CATEGORY, _UNHELD_CATEGORY),
                 registry, max_calls=2)
    assert result.refusal == "call_budget_exhausted"
    assert result.diagnosis == "unknown_category"


def test_an_identical_refused_call_stops_on_the_first_repeat(registry):
    result = run(
        "what did I spend on that?",
        _turn({"shape": _SPENT}, _UNHELD_CATEGORY, _UNHELD_CATEGORY,
              _UNHELD_CATEGORY),
        registry, max_calls=8)

    assert result.refusal == "call_budget_exhausted"
    assert result.diagnosis == "unknown_category"
    assert result.calls == 3  # shape note, first refusal, repeated refusal
    assert "repeated an identical" in result.detail


def test_a_cause_is_not_spoken_where_a_later_read_succeeded(registry):
    """The turn's trouble lies where the reads cannot explain it, so the
    verdict stands alone rather than quoting a complaint that has stopped being
    the reason."""
    from viva.persona import moment

    result = run("what did I spend on that?",
                 _turn({"shape": _SPENT}, _UNHELD_CATEGORY, _A_READ_THAT_WORKS,
                       _DELIVER_NOTHING),
                 registry)
    assert result.refusal == "nothing_established"
    assert result.diagnosis == ""
    assert result.text == moment("refusal_nothing_established")


def test_a_cause_is_not_spoken_where_the_last_read_refused_the_call_itself(
        registry):
    """A read that refused the arguments it was handed is talking to whoever
    called it. Its tag is not one whose cause may be spoken, and the refusal
    before it is not reached back for."""
    result = run("what did I spend on that?",
                 _turn({"shape": _SPENT}, _UNHELD_CATEGORY,
                       {"tool": "query_ledger",
                        "args": {"entity": "balances", "unknown_field": "x"}},
                       _DELIVER_NOTHING),
                 registry)
    assert result.transcript[-1]["refusal"] == "invalid_arguments"
    assert result.refusal == "nothing_established"
    assert result.diagnosis == ""


def test_a_cause_is_not_spoken_where_one_tag_stands_for_several_faults(
        registry):
    """A read that finds more than one fault in the filters it was handed
    gathers them under a single tag, and that tag says nothing about which
    faults are inside it. Two malformed window edges are entirely about the
    form of the call — nothing was looked for in the records at all — so the
    turn says the verdict and nothing more.

    The field is what is asserted, not any sentence: a tag that is not spoken
    has no sentence to compare against, and this holds whatever words the pack
    happens to carry."""
    from viva.tools.envelope import SPEAKABLE_REFUSALS

    result = run("what did I spend on that?",
                 _turn({"shape": _SPENT},
                       {"tool": "query_ledger",
                        "args": {"entity": "aggregate", "metric": "spending",
                                 "filters": {"window": {"from": "last month",
                                                        "to": "yesterday"}}}},
                       _DELIVER_NOTHING),
                 registry)
    problems = result.transcript[-1]["data"]["filter_problems"]
    assert len(problems) > 1 and not set(problems) & SPEAKABLE_REFUSALS
    assert result.transcript[-1]["refusal"] not in SPEAKABLE_REFUSALS
    assert result.refusal == "nothing_established"
    assert result.diagnosis == ""


def test_a_note_the_runner_wrote_to_the_planner_is_never_a_cause(registry):
    """Eligibility is registry membership: the runner's own note about a shape
    is not a read, so it is passed over rather than spoken and rather than
    hiding the read behind it."""
    result = run("what did I spend on that?",
                 _turn({"shape": _SPENT}, _UNHELD_CATEGORY,
                       {"shape": _ALSO_HELD}, _DELIVER_NOTHING),
                 registry)
    last = result.transcript[-1]
    assert last["tool"] == "commit_shape" and last["refusal"] == "bad_shape"
    assert result.diagnosis == "unknown_category"


def test_a_call_no_registered_tool_answered_is_never_a_cause(registry):
    """The same rule for a step naming a tool that does not exist: the refusal
    is the registry's, not a read's, so it is passed over."""
    result = run("what did I spend on that?",
                 _turn({"shape": _SPENT}, _UNHELD_CATEGORY,
                       {"tool": "no_such_read", "args": {}}, _DELIVER_NOTHING),
                 registry)
    assert result.transcript[-1]["refusal"] == "unknown_tool"
    assert result.diagnosis == "unknown_category"


@pytest.mark.parametrize("step, tag", [
    ({"bindings": {"total": {"figure": "f99"}}}, "unknown_figure"),
    ({"bindings": {"nowhere": {"figure": "f1"}}}, "unshaped_binding"),
    ({"bindings": "not an object"}, "bad_delivery"),
    ({"neither": "shape nor read nor delivery"}, "bad_plan"),
])
def test_a_turn_that_faulted_at_its_own_delivery_borrows_no_reads_account(
        registry, step, tag):
    """A delivery that reached wrongly, and a step that was never a turn, are
    the machine catching itself. Those verdicts stand alone: whatever the reads
    did, none of their accounts is borrowed over the top of one."""
    from viva.persona import moment

    result = run("what did I spend on that?",
                 _turn({"shape": _SPENT}, _UNHELD_CATEGORY, step), registry)
    assert result.refusal == tag
    assert result.diagnosis == ""
    assert result.text == moment("refusal_" + tag)


# ------------------------------------- what set each figure was taken over

# One call per read the registry holds, and per branch of a read that answers
# more than one question. Written out rather than generated, because what is
# being asserted is that nothing a person can ask for comes back with a figure
# whose set nobody stated; the coverage checks below hold this list to the
# schemas rather than the other way round.
_EVERY_READ = (
    ("query_ledger", {"entity": "balances"}),
    ("query_ledger", {"entity": "transactions"}),
    ("query_ledger", {"entity": "holdings"}),
    ("query_ledger", {"entity": "vocabulary", "group_by": "account"}),
    ("query_ledger", {"entity": "aggregate", "metric": "spending"}),
    ("query_ledger", {"entity": "aggregate", "metric": "income"}),
    ("query_ledger", {"entity": "aggregate", "metric": "recurring_spending"}),
    ("query_ledger", {"entity": "aggregate", "metric": "surplus"}),
    ("query_ledger", {"entity": "aggregate", "metric": "stalest_balance"}),
    ("query_ledger", {"entity": "aggregate", "metric": "weakest_evidence"}),
    ("query_ledger", {"entity": "aggregate", "metric": "net_worth"}),
    ("list_movements", {"filters": {"account": "chk"}}),
    ("check_completeness", {}),
    ("get_provenance", {"record_id": "doc-jan"}),
    ("get_provenance", {"record_id": "chk"}),
    ("get_transparency", {"topic": "agent_activity"}),
    ("get_transparency", {"topic": "calls_spent"}),
    ("get_transparency", {"topic": "declined_questions"}),
)


def test_every_read_says_what_set_each_of_its_figures_was_taken_over(registry,
                                                                    proj):
    """No figure any read emits leaves its set for something downstream to
    guess at. Silence and "this is everything" are different sentences, and a
    figure carrying neither is one that can be spoken as any claim at all.

    Every read the registry holds is called, every branch that answers a
    different question with it, and a movement's provenance besides — that last
    one by the key the vault holds rather than by a literal, since a movement's
    identity is derived from what it says."""
    called = set()
    key = movement_key("doc-jan", "chk", "2026-01-20", Decimal("-60.00"),
                       "GREENFIELD MARKET", 0)
    for tool, args in _EVERY_READ + (("get_provenance", {"record_id": key}),):
        result = registry.call(tool, args)
        called.add(tool)
        assert result.ok, (tool, args, result.text)
        for fig in result.figures:
            assert fig["boundary"] != {}, (tool, args, fig["what"])
    # And the calls above reach every read there is, every entity, every
    # metric and every topic — so a read arriving later is either in this list
    # or fails here.
    reads = {name for name, spec in registry._specs.items()
             if not spec.needs_figures}
    assert called == reads, sorted(reads - called)
    for field, key in (("entity", "entity"), ("metric", "metric")):
        offered = set(ledger_tools.QUERY_LEDGER_PARAMS["properties"][field]
                      ["enum"])
        assert offered == {args[key] for tool, args in _EVERY_READ
                           if tool == "query_ledger" and key in args}
    topics = set(ledger_tools.TRANSPARENCY_PARAMS["properties"]["topic"]
                 ["enum"])
    assert topics == {args["topic"] for tool, args in _EVERY_READ
                      if tool == "get_transparency"}


def test_a_read_names_the_things_its_figures_are_slices_of_as_it_named_them(
        registry, proj):
    """One thing, one string, across the two declarations a read makes about
    it.

    A figure says which slice of a set it is; a read says which things it spoke
    about; and the comparison that decides whether a number belongs to the
    thing a sentence names is between those two strings. So where a read
    establishes a thing of some kind and cuts a figure by a value that names a
    thing of that kind, the value has to be the label that read gave it —
    otherwise a true sentence pairing the two is refused, which is a defect
    wearing the fix's clothes and fails no other way.

    Two conditions, and each is a property rather than a list. A read that
    establishes nothing of a kind says nothing about the things of that kind,
    so its cuts of that kind are compared against nothing. And a value naming
    something no read of this vault establishes is a set the run holds no thing
    for: nothing can be bound that names it, so nothing can be bound beside it
    wrongly, and the comparison is silent rather than satisfied.

    Held over every read there is, every branch of every read that answers a
    different question, and over the narrowings that make a read declare an
    axis it did not group by."""
    from viva.tools.envelope import ENTITY_KINDS, SELECTED_KINDS, _named

    key = movement_key("doc-jan", "chk", "2026-01-20", Decimal("-60.00"),
                       "GREENFIELD MARKET", 0)
    calls = list(_EVERY_READ) + _every_declared_call(registry) + [
        ("get_provenance", {"record_id": key}),
        ("list_movements", {"filters": {"account": "chk"}}),
        ("list_movements", {"filters": {"merchant": "greenfield market"}}),
        ("list_movements", {"filters": {"category": "groceries"}}),
        ("query_ledger", {"entity": "aggregate", "metric": "spending",
                          "group_by": "merchant",
                          "filters": {"account": "chk"}}),
    ]
    reads = [(tool, args, registry.call(tool, args)) for tool, args in calls]
    reads = [read for read in reads if read[2].ok]

    def labelled(result):
        out: dict = {}
        for item in result.identifiers or []:
            out.setdefault(item["kind"], set()).add(_named(item)["label"])
        return out

    established: dict = {}
    for _, _, result in reads:
        for kind, labels in labelled(result).items():
            established.setdefault(kind, set()).update(labels)

    compared = set()
    for tool, args, result in reads:
        named = labelled(result)
        for fig in result.figures:
            for item in (fig["boundary"].get("cut") or []):
                kind, value = item["kind"], str(item["value"])
                if not named.get(kind):
                    continue
                if value not in established.get(kind, set()):
                    continue
                compared.add(kind)
                assert value in named[kind], (
                    f"{tool} {args} took {fig['what']!r} over {kind} "
                    f"{value!r} and named that thing "
                    f"{sorted(named[kind])} — one thing under two strings is "
                    "two things to anything comparing them")
    # And the sweep reached every kind of thing a set can be narrowed to and a
    # sentence can name, so a kind nothing exercised cannot pass by absence.
    assert compared == set(ENTITY_KINDS) & set(SELECTED_KINDS), sorted(compared)


def test_a_boundary_that_does_not_say_it_is_whole_is_not_read_as_whole():
    """Where the claim ends is read off what a boundary says, and nothing
    supplies the word where it is missing. A default of "whole" there would put
    a coverage claim on every figure nobody made one about, which is the
    opposite of what an emitter's silence means."""
    from viva.tools import runner

    unsaid = {"selected": [{"kind": "account", "value": "chk"}]}
    said, gaps = runner._boundary({"boundary": unsaid})
    assert said and not gaps
    assert runner._boundary({"boundary": {"whole": True}}) == ([], [])
    assert runner._boundary({}) == ([], [])


def test_a_per_account_figure_names_its_account_on_a_vault_of_one():
    """Which slices a figure is and whether they are everything are two
    statements, and a figure covering everything still has a name. A vault of
    one account in one currency is where the two meet, and no combination of
    filters over it refuses or raises.

    A figure of a narrowed read is the narrowing AND its own account, so what
    it names grows with the filters while what it is stays the same one
    account."""
    registry = _narrowable("acct-one")
    for filters in ({}, {"account": "acct-one"}, {"currency": "USD"},
                    {"account": "acct-one", "currency": "USD"}):
        result = registry.call("query_ledger", {"entity": "balances",
                                                "filters": filters})
        assert result.ok, (sorted(filters), result.text)
        held = [f for f in result.figures if f["quantity"] == quantity.BALANCE]
        assert held, sorted(filters)
        for fig in held:
            cut = fig["boundary"]["cut"]
            assert {"kind": "account", "value": "acct-one"} in cut
            assert {c["kind"] for c in cut} == {"account"} | set(filters)
            assert fig["boundary"]["whole"] is (not filters), fig["what"]


def test_the_net_worth_lines_and_a_looked_up_balance_name_their_account():
    """A figure taken over one account of several says which one. Neither read
    counts what it is one of — one is a part of a point built from parts, and
    the other reaches a single record and knows nothing about the rest — so
    neither claims to cover what a balance measures."""
    registry = default_registry(LedgerProjection(_events()))
    point = registry.call("query_ledger", {"entity": "aggregate",
                                           "metric": "net_worth"})
    # Found by what each figure declares it is a slice of, not by how the read
    # happened to word it: a subject picked out of prose survives the property
    # it was written for being removed.
    lines = [f for f in point.figures
             if [c["kind"] for c in f["boundary"].get("cut") or []]
             == ["account"]]
    assert lines
    for fig in lines:
        assert fig["boundary"] == {
            "whole": False,
            "cut": [{"kind": "account", "value": fig["record_ids"][0]}]}
    looked_up = registry.call("get_provenance", {"record_id": "chk"})
    (balance,) = looked_up.figures
    assert balance["boundary"] == {"whole": False,
                                   "cut": [{"kind": "account", "value": "chk"}]}


def _measured_in(*currencies):
    """A vault holding one account in each currency named, every one of them
    measured by a statement of its own and short of nothing, so what a point
    over it is not whole of is the other currency beside it and nothing else.
    Every value here is invented."""
    evs = []
    for n, currency in enumerate(currencies, 1):
        account, doc = f"acct-{n}", f"doc-{n}"
        evs += [account_opened(account, "depository", f"Account {n}", currency,
                               "2026-01-01"),
                document_captured(doc, f"{doc}.pdf", 10, "bank_statement", 0.9,
                                  "2026-02-01"),
                opening_balance_observed(account, "500.00", "2026-01-01",
                                         _p(doc)),
                closing_balance_observed(account, "500.00", "2026-01-31",
                                         _p(doc, 6))]
    return LedgerProjection(evs)


def test_net_worth_in_one_of_several_currencies_is_not_the_whole_of_it():
    """A per-currency part of a point is the whole of what its quantity ranges
    over only where that currency is the only one the vault holds, exactly as
    one account's balance is a total only on a vault of one account. Either way
    it names the currency it is a part of.

    Nothing adds across currencies, so on a vault of two there is no whole for
    one of them to be the whole of, and a sentence asking for one gets nothing
    to fill it rather than one currency's part standing in for the lot. Neither
    part is short of anything measurable here, so what stops them being whole
    is the currency beside them and nothing else."""
    for currencies in (("USD",), ("USD", "EUR")):
        result = ledger_tools.query_ledger(
            _measured_in(*currencies),
            {"entity": "aggregate", "metric": "net_worth"},
            today="2026-03-01")
        assert result.ok, result.text
        parts = [f for f in result.figures
                 if [c["kind"] for c in f["boundary"].get("cut") or []]
                 == ["currency"]]
        assert {f["currency"] for f in parts} == set(currencies)
        for fig in parts:
            assert fig["boundary"] == {
                "whole": len(currencies) == 1,
                "cut": [{"kind": "currency",
                        "value": fig["currency"]}]}, fig["what"]


def test_a_looked_up_movement_is_the_whole_of_what_a_movement_measures():
    """One movement is all of what the quantity `movement` ranges over, the
    same as a listed one, so it declares the whole and names no slice."""
    registry = default_registry(LedgerProjection(_events()))
    key = movement_key("doc-jan", "chk", "2026-01-20", Decimal("-60.00"),
                       "GREENFIELD MARKET", 0)
    result = registry.call("get_provenance", {"record_id": key})
    (moved,) = result.figures
    assert moved["boundary"] == {"whole": True}


def test_the_counts_of_the_agents_own_records_are_over_all_of_them(registry):
    """The four counts of what the agent holds are taken over every document it
    has and every counterparty it has seen: nothing narrows that read, so each
    covers the whole of what it counts. A day one account's evidence is good as
    of is not every account's, so it says it is not whole and claims no more."""
    result = registry.call("check_completeness", {})
    counted = [f for f in result.figures if f["quantity"] == quantity.COUNT]
    assert len(counted) == 4
    for fig in counted:
        assert fig["boundary"] == {"whole": True}, fig["what"]
    dated = [f for f in result.figures if f["quantity"] == quantity.TIME]
    assert dated
    for fig in dated:
        assert fig["boundary"] == {"whole": False}, fig["what"]


def test_a_journal_read_narrowed_to_a_day_says_so_on_its_count(registry):
    """A day to run from narrows what is counted, so the count records it and
    declares the whole only where nothing was asked for."""
    for topic in ("agent_activity", "calls_spent"):
        whole = registry.call("get_transparency", {"topic": topic})
        (count,) = whole.figures
        assert count["boundary"] == {"whole": True}, topic
        since = registry.call("get_transparency", {"topic": topic,
                                                   "since": "2026-02-01"})
        (count,) = since.figures
        assert count["boundary"] == {
            "whole": False,
            "selected": [{"kind": "since", "value": "2026-02-01"}],
            "cut": [{"kind": "since", "value": "2026-02-01"}]}, topic


def test_how_many_accounts_do_i_have_still_answers(registry):
    """A count of what the vault holds reaches a person. It is the gain a
    figure kind bought, and it stands on this read declaring what set it
    counted over rather than leaving it unsaid.

    Held over both reads that answer a question of that shape, and the second
    is what makes this bite: a sentence asking how many there are is a claim
    about the whole of them, so it is answered only by a figure that says it
    was taken over the whole of them. Take the boundary away from those counts,
    or take the whole out of it, and this fails."""
    for read in (("query_ledger", {"entity": "vocabulary",
                                   "group_by": "account"}),
                 ("check_completeness", {})):
        result = run("how many accounts do I have?",
                     _script(_shape(("You hold {many} account(s).",
                                     [("many", "count", "count", "whole")])),
                             read,
                             bind=lambda r: {"many": {"figure": "f1"}}),
                     registry)
        assert result.answered, (read, result.detail)
        assert result.text.startswith("You hold 3 account(s)."), (read,
                                                                  result.text)
        assert result.figures[0]["boundary"] == {"whole": True}, read


def test_arithmetic_over_one_set_is_over_that_set(registry):
    """Two operands taken over the same set give a result over that same set,
    and the comparison is of the whole declaration rather than of any field in
    it. So a share of one account's balance is still a figure about that
    account, and says which one."""
    book = _one_figure(registry, "query_ledger",
                       {"entity": "balances", "filters": {"account": "chk"}})
    balance = next(f["id"] for f in book.values()
                   if f["quantity"] == quantity.BALANCE)
    result = registry.call("compute", {"expression": "a - a",
                                       "inputs": {"a": balance}},
                           figures=book)
    assert result.ok, result.text
    assert result.figures[0]["boundary"] == book[balance]["boundary"]


def test_a_result_carries_its_own_declaration_and_not_its_operand_s(registry):
    """A result that inherits a declaration inherits its meaning, not the
    object it was written in. Two figures sharing one nested slice would make
    any later change to either a silent change to what the other says it is
    about, and the wrong description would be the one nobody wrote."""
    book = _one_figure(registry, "query_ledger",
                       {"entity": "balances", "filters": {"account": "chk"}})
    balance = next(f["id"] for f in book.values()
                   if f["quantity"] == quantity.BALANCE)
    source = book[balance]["boundary"]
    assert source["cut"]
    result = registry.call("compute", {"expression": "a * 12",
                                       "inputs": {"a": balance}},
                           figures=book)
    assert result.ok, result.text
    carried = result.figures[0]["boundary"]
    assert carried == source
    assert carried is not source
    assert carried["cut"] is not source["cut"]


def test_arithmetic_over_two_different_sets_is_over_neither(registry):
    """Two operands taken over different sets give a number over neither: not
    everything its quantity ranges over, and no slice anybody can name. It
    claims nothing about coverage in either direction."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    ids = [f["id"] for f in book.values()
           if f["quantity"] == quantity.BALANCE]
    assert book[ids[0]]["boundary"] != book[ids[1]]["boundary"]
    result = registry.call("compute", {"expression": "a + b",
                                       "inputs": {"a": ids[0], "b": ids[1]}},
                           figures=book)
    assert result.ok, result.text
    assert result.figures[0]["boundary"] == {"whole": False}


def test_a_value_the_person_supposed_is_over_no_set_the_vault_measured(
        registry):
    """A figure resting on the person's own premise is not a claim about the
    whole of anything: it says it is not everything and names no slice it is.
    What it is computed with makes no difference — a supposition carries that
    declaration through every hop, like the supposition itself."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values()
                   if f["quantity"] == quantity.BALANCE)
    alone = registry.call("compute",
                          {"expression": "trip",
                           "inputs": {"trip": {"stipulated": "250"}}},
                          figures=book, question="could I afford a 250 trip?")
    assert alone.ok and alone.figures[0]["boundary"] == {"whole": False}
    against = registry.call("compute",
                            {"expression": "have - trip",
                             "inputs": {"have": balance,
                                        "trip": {"stipulated": "250"}}},
                            figures=book,
                            question="could I afford a 250 trip?")
    assert against.ok and against.figures[0]["boundary"] == {"whole": False}


def test_arithmetic_over_a_term_whose_set_nobody_stated_states_none(registry):
    """An operand nobody declared a set for gives a result nobody has declared
    a set for, rather than a claim the arithmetic invented.

    One kind of term reaches this and no read emits it, so what is held open
    here is the backstop under a figure some emitter written later would leave
    silent. It is checked by handing the arithmetic exactly such a figure,
    rather than assumed from the fact that nothing produces one."""
    unsaid = figure("2", "a number nobody said the set of",
                    quantity=quantity.COUNT, grade=VERIFIED,
                    record_ids=["doc-jan"])
    unsaid["id"] = "f1"
    for expression in ("a * 2", "a / 2", "a + 2", "a - 2"):
        result = registry.call("compute", {"expression": expression,
                                           "inputs": {"a": "f1"}},
                               figures={"f1": unsaid})
        assert result.ok, (expression, result.text)
        assert result.figures[0]["boundary"] == {}, expression


def test_a_literal_contributes_no_set_and_takes_none_away(registry):
    """A bare number in the expression is not a set, and each operator decides
    for itself what a set met by one comes out as — the same way each already
    decides what records and what grade come out.

    Scaling changes the units and takes nothing away, so a figure multiplied or
    divided by a literal is still over the set its read declared, and can still
    be spoken as a claim about that set. Adding injects a magnitude nothing
    measured, so the total is over neither: not everything its quantity ranges
    over, and no slice anybody can name. Two literals are that same number over
    no set anybody measured, which is a declaration rather than a silence."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    ids = [f["id"] for f in book.values() if f["quantity"] == quantity.BALANCE]
    counted = next(f["id"] for f in book.values()
                   if f["quantity"] == quantity.COUNT)
    over_one_account = book[ids[0]]["boundary"]
    assert over_one_account["cut"], "the operand names the slice it is"
    over_every_account = book[counted]["boundary"]
    assert over_every_account["whole"] is True
    over_no_set = {"whole": False}
    for expression, inputs, expected in (
            # Scaled: what the read declared, unchanged.
            ("a * 12", {"a": ids[0]}, over_one_account),
            ("a / 2", {"a": ids[0]}, over_one_account),
            ("(a + a) / 2", {"a": ids[0]}, over_one_account),
            ("n * 12", {"n": counted}, over_every_account),
            # Added to: over neither, whatever either side declared.
            ("n + 12", {"n": counted}, over_no_set),
            ("n - 12", {"n": counted}, over_no_set),
            # Two literals, and a disagreement that a later scaling does not
            # repair: both are numbers over no set anybody measured.
            ("12 * 5", {}, over_no_set),
            ("a / b * 100", {"a": ids[0], "b": ids[1]}, over_no_set)):
        result = registry.call("compute", {"expression": expression,
                                           "inputs": inputs}, figures=book)
        assert result.ok, (expression, result.text)
        assert result.figures[0]["boundary"] == expected, expression


def test_no_read_names_one_slice_of_what_it_cuts_more_than_once(registry):
    """Two figures over one slice are two measurements of one thing, and a
    block written from them would state that thing's money once per figure
    while reading as one line per slice. No read produces that: where an
    emitter has several figures inside one thing, the thing is what they are
    in rather than the slice they are, and they name no slice at all.

    Held over every read there is, and over a vault holding two instruments in
    one account, which is the shape that would produce it if any did."""
    from viva.tools import runner

    several_inside_one = LedgerProjection([
        account_opened("brk-2", "investment", "Second Brokerage", "USD",
                       "2026-01-01"),
        document_captured("doc-brk-2", "brk.pdf", 10, "bank_statement", 0.9,
                          "2026-02-01"),
        position_observed("brk-2", "ALPHA FUND", "10", "1500.00", "USD",
                          "2026-01-31", provenance=_p("doc-brk-2")),
        position_observed("brk-2", "BETA FUND", "5", "500.00", "USD",
                          "2026-01-31", provenance=_p("doc-brk-2"))])
    calls = [(registry, tool, args) for tool, args in _EVERY_READ]
    calls.append((default_registry(several_inside_one), "query_ledger",
                  {"entity": "holdings"}))
    for called, tool, args in calls:
        result = called.call(tool, args)
        assert result.ok, (tool, args, result.text)
        cuts = [cut for cut in (runner._line_of(f) for f in result.figures)
                if cut]
        if len({cut["kind"] for cut in cuts}) > 1:
            # A read that cuts the same set more than one way at once fills no
            # block on that ground, and that is settled before one slice named
            # twice is looked for. The rule below is not reachable for it.
            continue
        named = [cut["value"] for cut in cuts]
        assert len(set(named)) == len(named), (tool, args, named)


def test_two_figures_over_one_slice_fill_no_block():
    """The rule the test above says nothing reaches, held where it lives.

    A read whose figures name one slice twice fills no block, for the reason a
    read cutting two ways at once fills none: a line per slice would state one
    slice's money once for each figure taken over it. Two figures over two
    slices of the same kind are the ordinary case and write two lines."""
    from viva.tools import runner

    def held(account, value):
        return figure(value, "what one account holds",
                      quantity=quantity.BALANCE, grade=VERIFIED,
                      currency="USD", record_ids=[account],
                      boundary=bounded(whole=False,
                                       cut=[{"kind": "account",
                                             "value": account}]))

    slot = Slot("breakdown", render.ROWS)
    apart = runner._Ground(book={"f1": held("acct-1", "10.00"),
                                 "f2": held("acct-2", "20.00")})
    block, tag, text = runner._rows_bound(slot, ["f1", "f2"], apart, "en-US")
    assert (tag, text) == ("", "")
    assert block is not None

    twice = runner._Ground(book={"f1": held("acct-1", "10.00"),
                                 "f2": held("acct-1", "20.00")})
    block, tag, text = runner._rows_bound(slot, ["f1", "f2"], twice, "en-US")
    assert block is None
    assert tag == "wrong_kind"
    assert slot.name in text


def test_arithmetic_over_one_axis_set_written_two_ways_keeps_that_set(registry):
    """Two figures over the same axes and the same values are one declaration,
    however the emitter that wrote each of them assembled it.

    A cut is a set, and a set has one written form: the axes are unique, so
    ordering by axis is a total order and the constructor puts every cut in it.
    What this pins is the constructor's contract — take the ordering out and
    the first assertion below fails, because one emitter's `narrowing then
    group axis` stops equalling another's `two filters`.

    It is not a verdict the arithmetic reaches. No pair of reads produces that
    pairing today: two operands are inherited from only where their whole
    boundaries are equal, equal boundaries mean the same narrowing, and one
    narrowing is written in one order, so two real operands cannot differ in
    cut ordering alone. The two figures below are built here rather than read
    from a vault for exactly that reason. The contract is worth holding anyway,
    because equality over a whole declaration is not one function's business —
    anything that walks a boundary compares the same way, and being right by
    default beats being right by having read why.

    The other direction is held beside it: axes that genuinely differ still
    give a number over neither operand's set, declaring not-whole and naming
    nothing, which is what tells a slice of a read from the read's own total."""
    def over(*axes):
        return figure("100.00", "spending over a set", quantity=quantity.SPENDING,
                      grade=VERIFIED, currency="USD", record_ids=["r"],
                      boundary=bounded(whole=False, cut=[
                          {"kind": kind, "value": value}
                          for kind, value in axes]))

    merchant = ("merchant", "a counterparty")
    category = ("category", "a category")
    tag = ("tag", "a tag")
    # The two orders one axis set arrives in: a read narrowed to the
    # counterparty and grouped by category names the counterparty first; a read
    # narrowed to both names them in the order its filters were read.
    book = {"f1": over(merchant, category), "f2": over(category, merchant),
            "f3": over(merchant), "f4": over(merchant, tag)}
    for fid, fig in book.items():
        fig["id"] = fid
    assert book["f1"]["boundary"] == book["f2"]["boundary"]

    agreed = registry.call("compute", {"expression": "a + b",
                                       "inputs": {"a": "f1", "b": "f2"}},
                           figures=book, question="how much over both?")
    assert agreed.ok, agreed.text
    assert agreed.figures[0]["boundary"] == {
        "whole": False, "cut": [{"kind": "category", "value": "a category"},
                                {"kind": "merchant", "value": "a counterparty"}]}

    # A subset and a disjoint pair: different sets both ways, and neither is
    # answered with a set either operand was taken over.
    for other in ("f3", "f4"):
        differs = registry.call("compute", {"expression": "a + b",
                                            "inputs": {"a": "f1", "b": other}},
                                figures=book, question="how much over both?")
        assert differs.ok, differs.text
        assert differs.figures[0]["boundary"] == {"whole": False}, other


# --------------------------------------- the thing a number is a number of

_BALANCES = ("query_ledger", {"entity": "balances"})
_POINT = ("query_ledger", {"entity": "aggregate", "metric": "net_worth"})
_BY_MERCHANT = ("query_ledger", {"entity": "aggregate", "metric": "spending",
                                 "group_by": "merchant"})


def test_a_clause_states_the_figure_of_the_account_it_names(registry):
    """The wrong instance of the right sort, caught — and the right one still
    said.

    Both halves of the sentence are real: the account is one this run
    established and the figure is one it emitted, of the same kind of thing,
    measuring what the hole asked for and taken over the axis it declared.
    Every check before this one passes. What fails is that the figure's own
    boundary names a different account from the one the sentence names.

    The two halves come from two different reads, which is the shape this is
    bought for: the run's ledger merges what every read established, so a thing
    one read spoke about sits beside a number another read emitted with nothing
    but this saying whether they belong together."""
    said = ("Your {which} holds {amount}.",
            [("which", "account"), ("amount", "money", "balance", "account")])

    def turn(account):
        return run("what is in it?",
                   _script(_shape(said), _BALANCES, _POINT,
                           bind=lambda results: {
                               "which": {"entity": _entity(results, account)},
                               "amount": {"figure": _fig(results,
                                                         "chk — its part")}}),
                   registry)

    # The account the figure is of is established by the first read; the figure
    # is emitted by the second.
    right = turn("chk")
    assert right.answered, right.refusal

    wrong = turn("brk")
    assert not wrong.answered
    assert wrong.refusal == "wrong_subject", wrong.detail
    # And what the person hears is the reviewed sentence for that tag, whole.
    assert wrong.text == moment("refusal_wrong_subject")


def test_a_clause_states_the_figure_of_the_counterparty_it_names(registry):
    """The same rule where the thing is a counterparty, and the one place the
    two declarations were ever written by different hands.

    A counterparty is established by the read that lists movements and cut by
    the read that groups spending, so the sentence names a thing one read
    spoke about and states a number the other took over it. That the correct
    pairing answers is half of what this holds: the two reads have to write one
    string for one counterparty, or a true sentence refuses."""
    said = ("You spent {amount} at {who}.",
            [("amount", "money", "spending", "merchant"),
             ("who", "merchant")])
    rows = ("list_movements", {"filters": {"account": "chk"}})

    def turn(merchant):
        return run("what did I spend there?",
                   _script(_shape(said), rows, _BY_MERCHANT,
                           bind=lambda results: {
                               "who": {"entity": _entity(results, merchant)},
                               "amount": {"figure": _fig(results,
                                                         "merchant 'green")}}),
                   registry)

    right = turn("greenfield market")
    assert right.answered, right.refusal
    wrong = turn("card payment")
    assert not wrong.answered
    assert wrong.refusal == "wrong_subject", wrong.detail


def test_every_axis_a_figure_is_a_slice_of_is_held_to_what_the_clause_names(
        registry):
    """A cut is a set, so the comparison is over every axis of it.

    A read narrowed to one account and grouped by counterparty emits a figure
    that is both — the intersection — and a sentence naming both things is
    checked on both. Right on one axis and wrong on the other is a number about
    something else, whichever axis it is right about."""
    said = ("At {who}, out of {which}, you spent {amount}.",
            [("who", "merchant"), ("which", "account"),
             ("amount", "money", "spending", ("account", "merchant"))])
    narrowed = ("query_ledger", {"entity": "aggregate", "metric": "spending",
                                 "group_by": "merchant",
                                 "filters": {"account": "chk"}})

    def turn(account, merchant):
        return run("what did I spend there out of that?",
                   _script(_shape(said),
                           ("list_movements", {"filters": {"account": "chk"}}),
                           _BALANCES, narrowed,
                           bind=lambda results: {
                               "who": {"entity": _entity(results, merchant)},
                               "which": {"entity": _entity(results, account)},
                               "amount": {"figure": _fig(results,
                                                         "merchant 'green")}}),
                   registry)

    both = turn("chk", "greenfield market")
    assert both.answered, both.refusal
    for account, merchant in (("brk", "greenfield market"),
                              ("chk", "card payment")):
        result = turn(account, merchant)
        assert not result.answered, (account, merchant)
        assert result.refusal == "wrong_subject", result.detail


def test_a_clause_naming_two_things_of_a_kind_may_state_either_ones_figure(
        registry):
    """A sentence that names two counterparties and states one's number is
    answered, because which of two named things a number sits beside is the
    sentence's own order and reading that would be reading the sentence.

    This is what keeps a comparison sayable — *you spent {x} at ⟨A⟩, more than
    at ⟨B⟩* — and it is why the residual named in the design stands: two things
    and two figures of one kind in one clause can be exchanged and each figure
    still finds a thing of its kind that its boundary names."""
    said = ("You spent {amount} at {who}, rather than at {other}.",
            [("amount", "money", "spending", "merchant"),
             ("who", "merchant"), ("other", "merchant")])
    result = run("where did it go?",
                 _script(_shape(said),
                         ("list_movements", {"filters": {"account": "chk"}}),
                         _BY_MERCHANT,
                         bind=lambda results: {
                             "who": {"entity": _entity(results, "card payment")},
                             "other": {"entity": _entity(results, "greenfield")},
                             "amount": {"figure": _fig(results,
                                                       "merchant 'green")}}),
                 registry)
    assert result.answered, result.refusal


def test_a_thing_named_for_another_purpose_is_still_a_thing_the_clause_names(
        registry):
    """What the sentence is about is the clause, so a thing named anywhere in
    it is a thing it names.

    A clause that names one account and states a figure taken over another is
    refused even where the account was named for its own reason, because
    nothing here can tell one reason from another without reading the words.
    The way to say both is to say them as two sentences — which is what they
    are — and the same two bindings split across two clauses answer."""
    narrowed = ("query_ledger", {"entity": "aggregate", "metric": "spending",
                                 "group_by": "merchant",
                                 "filters": {"account": "chk"}})
    holes = [("which", "account"),
             ("amount", "money", "spending", ("account", "merchant"))]

    def turn(shape):
        return run("what about the other one?",
                   _script(shape, _BALANCES, narrowed,
                           bind=lambda results: {
                               "which": {"entity": _entity(results, "brk")},
                               "amount": {"figure": _fig(results,
                                                         "merchant 'green")}}),
                   registry)

    together = turn(_shape(("Your {which} is one of several, and you spent "
                            "{amount} at the market.", holes)))
    assert not together.answered
    assert together.refusal == "wrong_subject", together.detail

    apart = turn(_shape(("Your {which} is one of several.", holes[:1]),
                        ("You spent {amount} at the market.", holes[1:])))
    assert apart.answered, apart.detail


def test_a_clause_that_names_no_thing_of_a_slices_kind_states_it_freely(
        registry):
    """A sentence that says what it is about only in its own words is checked
    by nothing here, and that residual ships named.

    The comparison is between two references, and prose is neither. A clause
    binding a figure cut by one counterparty and naming no counterparty
    through a hole is answered — refusing it would mean either reading the
    words, or requiring that a figure naming a slice may only be stated beside
    that slice's own thing, which would silence every slice the vault holds no
    thing for."""
    said = ("You spent {amount} at the market.",
            [("amount", "money", "spending", "merchant")])
    result = run("what did I spend there?",
                 _script(_shape(said), _BY_MERCHANT,
                         bind=lambda results: {
                             "amount": {"figure": _fig(results,
                                                       "merchant 'green")}}),
                 registry)
    assert result.answered, result.refusal


def test_every_account_a_point_cuts_by_is_one_a_sentence_can_name(registry):
    """A figure taken over a set no read established a thing for can be bound
    by no sentence, so nothing can check what is said beside it. The point read
    produces no such figure.

    One account is one line, so every slice the point cuts by is a thing the
    same read hands over, and a sentence naming one beside its own figure is
    checked rather than merely tolerated."""
    point = registry.call("query_ledger", {"entity": "aggregate",
                                           "metric": "net_worth"})
    per_account = [f for f in point.figures
                   if [c["kind"] for c in f["boundary"].get("cut") or []]
                   == ["account"]]
    assert per_account, "the point cut by no account, so this proves nothing"
    named = {i["account"] for i in point.identifiers}
    assert all(f["record_ids"][0] in named for f in per_account), (
        "a figure names a slice this run holds no thing for")

    said = ("Your {which} holds {amount}.",
            [("which", "account"), ("amount", "money", "balance", "account")])
    result = run("what is in it?",
                 _script(_shape(said), _BALANCES, _POINT,
                         bind=lambda results: {
                             "which": {"entity": _entity(results, "brk")},
                             "amount": {"figure": _fig(results,
                                                       "its part of net")}}),
                 registry)
    assert result.answered, result.refusal


def test_a_dropped_clause_is_not_held_to_what_it_would_have_named(registry):
    """The comparison runs over what survived the drops.

    A clause with a hole nothing filled asserts nothing: it never reaches the
    person, so a thing and a figure inside it that do not belong together are
    not a false sentence and do not cost the turn. The clause that does reach
    the person is checked, and answers."""
    said = (("You have {count} accounts.", [("count", "count", "count",
                                             "whole")]),
            ("Your {which} holds {amount}, as of {when}.",
             [("which", "account"),
              ("amount", "money", "balance", "account"),
              ("when", "date")]))
    result = run("how many accounts do I have?",
                 _script(_shape(*said), _BALANCES, _POINT,
                         bind=lambda results: {
                             "count": {"figure": _fig(results,
                                                      "accounts holding")},
                             "which": {"entity": _entity(results, "brk")},
                             "amount": {"figure": _fig(results,
                                                       "chk — its part")}}),
                 registry)
    assert result.answered, result.refusal
    assert result.gaps and result.gaps[0]["name"] == "when"
