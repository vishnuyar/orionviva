"""Shape claims contracts."""

from _shape_test_support import *

# ------------------------------------------- where a stated figure's claim ends


def _two_accounts():
    """A person with more than one account and a loan nothing has measured."""
    from viva.ledger.events import merchant_enriched, ruling_recorded
    p = Provenance("doc-jan", 1, "r")
    return [
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01", institution="Northgate Bank",
                       account_number="XX4417", account_names=["R VANCE"]),
        account_opened("card", "liability", "Signature Card", "USD",
                       "2026-01-01", institution="Meridian Cards",
                       account_number="XX2291", account_names=["R VANCE"]),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", "10000.00", "2026-01-01", p),
        simple_transaction("chk", "-2000.00", "MERIDIAN LOAN SERVICING",
                           "2026-01-10", provenance=p),
        simple_transaction("chk", "-100.00", "CITY TRANSIT",
                           "2026-01-11", provenance=p),
        simple_transaction("chk", "-300.00", "GREENFIELD MARKET",
                           "2026-01-12", provenance=p),
        closing_balance_observed("chk", "7600.00", "2026-01-31",
                                 Provenance("doc-jan", 6, "r")),
        merchant_enriched("city transit", "transport", subcategory="fares",
                          occurred_at="2026-02-02"),
        merchant_enriched("greenfield market", "groceries",
                          subcategory="supermarket", occurred_at="2026-02-02"),
        ruling_recorded(
            scope="merchant", subject="meridian loan servicing",
            legs=[{"major": "liability",
                   "account": "Liabilities:HomeLoan:Meridian"}],
            occurred_at="2026-02-01", by="human"),
    ]


@pytest.fixture()
def several():
    return default_registry(LedgerProjection(_two_accounts()))


def _figure_id(results, what):
    for result in results:
        for f in result.get("figures") or []:
            if what in f["what"]:
                return f["id"]
    raise AssertionError(f"no figure described as {what!r} was emitted")


def test_a_figure_over_part_of_a_set_says_so_whatever_the_shape_said(several):
    """One account's balance, correctly graded and correctly cited, stated
    under a sentence that reads like a total, says which set it came from.

    The shape says nothing about sets — it was authored before anything was
    read — and the run places the boundary anyway, out of what the read
    declared. Nothing here asks a planner to remember."""
    shape = _shape(("You currently owe {total}.",
                    [("total", "money", "owed", "account")]))
    result = run("what do I owe?",
                 _script(shape, ("query_ledger", {"entity": "balances"}),
                         bind=lambda r: {
                             "total": {"figure": _figure_id(r, "Signature Card")}}),
                 several)
    assert result.answered, result.detail
    assert result.text.startswith("You currently owe ")
    assert moment("boundary_accounts", counted=render.count(1),
                  held=render.count(2)) in result.text


def test_a_balance_over_one_of_several_accounts_says_which_one(several):
    """One account's balance says which account it is, not only that it is one
    of several. Nothing narrowed this read, so which one it is comes from the
    figure's own slice rather than from what the read was asked for."""
    shape = _shape(("You hold {total}.",
                   [("total", "money", "balance", "account")]))
    result = run("how much have I got?",
                 _script(shape, ("query_ledger", {"entity": "balances"}),
                         bind=lambda r: {
                             "total": {"figure": _figure_id(r, "Everyday "
                                                            "Checking")}}),
                 several)
    assert result.answered, result.detail
    assert moment("boundary_selected_account",
                  account=render.account({"account": "chk",
                                          "name": "Everyday Checking"},
                                         among=[])) in result.text


def test_a_figure_whose_set_is_everything_it_measures_places_nothing(registry):
    """The statement fires only where there is a set worth stating. This vault
    holds one account and the read was asked for all of them, so its balance is
    every balance there is, and the answer is the sentence the shape declared
    and nothing else."""
    result = run("balance?",
                 _script(_shape(("Your balance is {total}.",
                                 [("total", "money", "balance", "whole")])),
                         ("query_ledger", {"entity": "balances"}),
                         bind=lambda r: {"total": {"figure": "f1"}}),
                 registry)
    assert result.answered, result.detail
    assert result.text == ("Your balance is USD 600.00. "
                           + moment(STOOD_BEHIND_MOMENT + result.grade))


def test_a_balance_read_narrowed_to_one_account_says_which_account(registry):
    """The same vault and question, narrowed to one account. One account of one
    is still a set somebody chose, so the answer names it.

    A vault of one account is also where the boundary constructor refuses a
    read whose whole and whose narrowing are computed from different filters:
    a figure covering everything cannot also name what narrowed it."""
    result = run("balance?",
                 _script(_shape(("Your balance is {total}.",
                                 [("total", "money", "balance", "account")])),
                         BALANCES,
                         bind=lambda r: {"total": {"figure": "f1"}}),
                 registry)
    assert result.answered, result.detail
    assert result.text == ("Your balance is USD 600.00. That counts only what "
                           "is on Everyday Checking. "
                           + moment(STOOD_BEHIND_MOMENT + result.grade))


def test_an_incomplete_total_cannot_be_stated_without_its_gap(several):
    """A total resting on a set that is not everything it claims to measure
    names every account it leaves out — whether or not the sentence around it
    mentioned any of them, and whichever of the two ways an account came to be
    left out.

    This vault holds both: a loan a ruling brought into being and no statement
    has ever measured, and a card held with no statement at all."""
    shape = _shape(("Your net worth is {n}.",
                   [("n", "money", "net_worth", "currency")]))
    result = run("what am I worth?",
                 _script(shape,
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "net_worth"}),
                         bind=lambda r: {"n": {"figure": _figure_id(r, "net in")}}),
                 several)
    assert result.answered, result.detail
    # Both accounts are named in one sentence, not one sentence each.
    said = moment("boundary_unmeasured", account=render.accounts(
        [{"account": "Liabilities:HomeLoan:Meridian"}, {"account": "card"}]))
    assert said in result.text
    # The frame around the accounts is said once, not once per account. Read
    # from the pack rather than spelled here, so the count follows the wording.
    _, _, frame = moment("boundary_unmeasured", account="\x00").partition("\x00")
    assert result.text.count(frame) == 1
    # What would settle a gap is carried on the figure and never spoken.
    stated = next(f for f in result.figures if f["what"].startswith("net in"))
    assert stated["boundary"]["unmeasured"] == [
        {"account": "Liabilities:HomeLoan:Meridian", "reason": "refused",
         "settled_by": "the loan or mortgage statement"},
        {"account": "card", "reason": "unobserved", "settled_by": ""}]



def test_a_boundary_is_said_once_inside_the_clause_that_made_it(several):
    """The same discipline a caveat is held to, inside one sentence. Two
    figures a clause states over the same set are one boundary between them,
    not two sentences a person reads twice."""
    shape = _shape(("You hold {a} across {n} account(s).",
                    [("a", "money", "balance", "account"),
                     ("n", "count", "count", "account")]))
    result = run("what is on my checking account?",
                 _script(shape, ("query_ledger",
                                 {"entity": "balances",
                                  "filters": {"account": "chk"}}),
                         bind=lambda r: {
                             "a": {"figure": _figure_id(r, "Everyday Checking")},
                             "n": {"figure": _figure_id(r,
                                                        "accounts holding")}}),
                 several)
    assert result.answered, result.detail
    said = moment("boundary_selected_account",
                  account=render.account({"account": "chk",
                                          "name": "Everyday Checking"},
                                         among=[]))
    assert result.text.count(said) == 1


def test_a_boundary_two_clauses_make_is_said_under_each_of_them(several):
    """And it stops at the clause. Two clauses each narrowed to the same
    account make that claim twice, once each, because the word each of these
    sentences begins with points at the sentence just read — a statement said
    once for two clauses is a statement about whichever of them the person
    takes it for."""
    shape = _shape(("You hold {a}.",
                    [("a", "money", "balance", "account")]),
                   ("That is spread over {n} account(s).",
                    [("n", "count", "count", "account")]))
    result = run("what is on my checking account?",
                 _script(shape, ("query_ledger",
                                 {"entity": "balances",
                                  "filters": {"account": "chk"}}),
                         bind=lambda r: {
                             "a": {"figure": _figure_id(r, "Everyday Checking")},
                             "n": {"figure": _figure_id(r,
                                                        "accounts holding")}}),
                 several)
    assert result.answered, result.detail
    said = moment("boundary_selected_account",
                  account=render.account({"account": "chk",
                                          "name": "Everyday Checking"},
                                         among=[]))
    assert result.text.count(said) == 2
    # And each of them sits under its own clause rather than in a pool at the
    # end: the second sentence begins before the second statement does.
    assert result.text.find(said) < result.text.find("That is spread over")


def test_an_answer_covering_two_accounts_never_says_it_covers_one(several):
    """The reach sentence counts the accounts the answer covers, not the
    accounts one of its figures covers.

    Two per-account figures each cover one of the accounts the person holds,
    and each says so identically. Over the answer that is two accounts covered
    of two held, so there is no shortfall and the sentence is not placed."""
    shape = _shape(("You hold {a} and owe {b}.",
                    [("a", "money", "balance", "account"),
                     ("b", "money", "owed", "account")]))
    result = run("where do I stand?",
                 _script(shape, ("query_ledger", {"entity": "balances"}),
                         bind=lambda r: {
                             "a": {"figure": _figure_id(r, "Everyday Checking")},
                             "b": {"figure": _figure_id(r, "Signature Card")}}),
                 several)
    assert result.answered, result.detail
    for counted in (1, 2):
        assert moment("boundary_accounts", counted=render.count(counted),
                      held=render.count(2)) not in result.text


def test_an_answer_over_some_of_the_accounts_says_so_once_about_itself(
        several):
    """And where the answer really does fall short of the accounts a person
    holds, it says so — once, and as a claim about the answer rather than
    about whichever figure happened to be first."""
    shape = _shape(("You hold {a}.",
                    [("a", "money", "balance", "account")]),
                   ("That is what one of them holds: {b}.",
                    [("b", "money", "balance", "account")]))
    result = run("what is on my checking account?",
                 _script(shape, ("query_ledger", {"entity": "balances"}),
                         bind=lambda r: {
                             "a": {"figure": _figure_id(r, "Everyday Checking")},
                             "b": {"figure": _figure_id(r,
                                                        "Everyday Checking")}}),
                 several)
    assert result.answered, result.detail
    said = moment("boundary_accounts", counted=render.count(1),
                  held=render.count(2))
    assert result.text.count(said) == 1
    # Last of what the answer says about its own reach, after both clauses have
    # had their say.
    assert result.text.find(said) > result.text.find("one of them holds")


def test_an_answer_naming_no_account_makes_no_claim_about_how_many_it_covers(
        several):
    """What the count is computed from, said as what happens when there is
    nothing to compute it from.

    A figure that covers several accounts and names none says how many it
    covers and nothing about which. That is a true thing about the figure and
    no basis for a claim about the answer, so the answer makes none — while
    what narrowed the read is still said under the clause that used it. The
    cost is named rather than hidden: an answer made only of such a figure
    states nothing about how many accounts the person holds."""
    shape = _shape(("This many of your accounts in that currency hold "
                    "something: {n}.",
                    [("n", "count", "count", "currency")]))
    result = run("how many of my accounts hold anything?",
                 _script(shape, ("query_ledger",
                                 {"entity": "balances",
                                  "filters": {"currency": "USD"}}),
                         bind=lambda r: {
                             "n": {"figure": _figure_id(r,
                                                        "accounts holding")}}),
                 several)
    assert result.answered, result.detail
    for counted in (1, 2):
        assert moment("boundary_accounts", counted=render.count(counted),
                      held=render.count(2)) not in result.text
    assert moment("boundary_selected_currency",
                  currency=render.label("USD")) in result.text


def test_an_answer_reaching_more_accounts_than_it_names_states_no_reach(
        several):
    """The other half of the same rule, and the one that keeps a false count
    out of the answer.

    One clause states a figure over a single account; the next states a figure
    counted over every account the read ranged over and naming none of them.
    The accounts the answer can list are fewer than the accounts it reached, so
    a shortfall counted from the names would be a shortfall the answer does not
    have — and there is nothing else to count it from. So the answer makes no
    claim about its own reach at all, and each clause still says what narrowed
    the figure it stated."""
    shape = _shape(("You hold {a}.", [("a", "money", "balance", "account")]),
                   ("That is spread over {n} account(s).",
                    [("n", "count", "count", "whole")]))
    result = run("where do I stand?",
                 _script(shape, ("query_ledger", {"entity": "balances"}),
                         bind=lambda r: {
                             "a": {"figure": _figure_id(r, "Everyday Checking")},
                             "n": {"figure": _figure_id(r,
                                                        "accounts holding")}}),
                 several)
    assert result.answered, result.detail
    for counted in (1, 2):
        assert moment("boundary_accounts", counted=render.count(counted),
                      held=render.count(2)) not in result.text
    assert moment("boundary_selected_account",
                  account=render.account({"account": "chk",
                                          "name": "Everyday Checking"},
                                         among=[])) in result.text


def test_an_answer_stating_a_total_over_the_whole_ledger_states_no_reach(
        several):
    """A figure declaring nothing about accounts is one the answer cannot
    account for either.

    One clause states a balance on a single account; the next states a spending
    total taken over everything, which reached both accounts and declared
    nothing about which. Counting the answer's reach from the accounts its
    figures name would count one of two over an answer that reached both, so
    the answer makes no claim about its own reach at all, and each clause still
    says what narrowed the figure it stated."""
    shape = _shape(("You hold {a}.", [("a", "money", "balance", "account")]),
                   ("You spent {b} in all.",
                    [("b", "money", "spending", "whole")]))
    result = run("where do I stand?",
                 _script(shape,
                         ("query_ledger", {"entity": "balances"}),
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "spending",
                                           "group_by": "category"}),
                         bind=lambda r: {
                             "a": {"figure": _figure_id(r,
                                                        "Everyday Checking")},
                             "b": {"figure": _figure_id(
                                 r, "total spending by category")}}),
                 several)
    assert result.answered, result.detail
    for counted in (1, 2):
        assert moment("boundary_accounts", counted=render.count(counted),
                      held=render.count(2)) not in result.text
    assert moment("boundary_selected_account",
                  account=render.account({"account": "chk",
                                          "name": "Everyday Checking"},
                                         among=[])) in result.text


def test_an_answer_stating_a_total_cut_to_a_category_states_no_reach(several):
    """The same, where the figure that names no account declares it is not the
    whole of what it measures.

    A spending total cut to one category names the category and no account,
    over movements on every account. What a figure declares about being the
    whole of its quantity decides nothing here: a figure that does not declare
    which accounts it covers is one the answer cannot enumerate, however
    narrow it is."""
    shape = _shape(("You hold {a}.", [("a", "money", "balance", "account")]),
                   ("You spent {b} on that.",
                    [("b", "money", "spending", "category")]))
    result = run("what is on my checking, and what did I spend on groceries?",
                 _script(shape,
                         ("query_ledger", {"entity": "balances"}),
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "spending",
                                           "group_by": "category"}),
                         bind=lambda r: {
                             "a": {"figure": _figure_id(r,
                                                        "Everyday Checking")},
                             "b": {"figure": _figure_id(
                                 r, "spending \u2014 category 'groceries'")}}),
                 several)
    assert result.answered, result.detail
    for counted in (1, 2):
        assert moment("boundary_accounts", counted=render.count(counted),
                      held=render.count(2)) not in result.text
    assert moment("boundary_selected_category",
                  category=render.category("groceries")) in result.text


def test_a_figures_boundary_comes_before_what_it_does_not_cover(several):
    """A boundary says what the claim is a claim about; a limit says what that
    claim does not reach. Read the other way round, the limit is about a set
    the person has not been told the shape of yet."""
    shape = _shape(("You spent {total}.",
                   [("total", "money", "spending", "category")]))
    result = run("what did I spend on transport?",
                 _script(shape,
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "spending",
                                           "group_by": "category"}),
                         bind=lambda r: {
                             "total": {"figure": _figure_id(
                                 r, "spending — category 'transport'")}}),
                 several)
    assert result.answered, result.detail
    boundary = result.text.find(moment("boundary_selected_category",
                                       category=render.category("transport")))
    limits = result.text.find(moment("answer_limits", limits="").split("{")[0])
    assert 0 < boundary < limits


# ------------------------------------------- how well what was said is stood
#                                                                      behind


def test_an_answer_states_how_well_the_figures_it_stated_are_stood_behind(
        registry):
    """An answer that stated a graded money figure carries the pack's sentence
    for that grade in its text, once.

    Asserted on the text a person is handed rather than on the grade the result
    carries: the grade travelling out on the result is bookkeeping, and a run
    in which only that were true would be a run in which nobody was told."""
    result = run("balance?",
                 _script(_shape(("Your balance is {total}.",
                                 [("total", "money", "balance", "account")])),
                         BALANCES,
                         bind=lambda r: {"total": {"figure": "f1"}}),
                 registry)
    assert result.answered, result.detail
    assert result.grade
    said = moment(STOOD_BEHIND_MOMENT + result.grade)
    assert said in result.text, result.text
    assert result.text.count(said) == 1


def test_the_grade_is_one_whole_reviewed_line_per_word_on_the_ladder(registry):
    """No frame with a machine's word dropped into it, anywhere. The ladder's
    word itself is not what a person reads: the sentence for that word is, and
    it exists in the pack before the turn begins."""
    from viva.tools.envelope import STRENGTH

    said = {grade: moment(STOOD_BEHIND_MOMENT + grade) for grade in STRENGTH}
    assert len(set(said.values())) == len(STRENGTH), (
        "two grades sharing one sentence would map two strengths to one word")
    for grade, sentence in said.items():
        assert sentence.strip() and "{" not in sentence, grade


def test_a_grade_is_said_after_the_extent_of_a_claim_and_before_its_limits(
        several):
    """Scope, then strength, then what it does not cover. A word about how well
    a figure is stood behind, heard before the extent of the claim has been
    stated, invites reading it as covering more than it does."""
    shape = _shape(("You spent {total}.",
                   [("total", "money", "spending", "category")]))
    result = run("what did I spend on transport?",
                 _script(shape,
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "spending",
                                           "group_by": "category"}),
                         bind=lambda r: {
                             "total": {"figure": _figure_id(
                                 r, "spending — category 'transport'")}}),
                 several)
    assert result.answered, result.detail
    boundary = result.text.find(moment("boundary_selected_category",
                                       category=render.category("transport")))
    stood = result.text.find(moment(STOOD_BEHIND_MOMENT + result.grade))
    limits = result.text.find(moment("answer_limits", limits="").split("{")[0])
    assert 0 < boundary < stood < limits, result.text


def test_an_answer_stating_nothing_graded_says_nothing_about_being_stood_behind(
        registry):
    """A count of the agent's own paperwork carries no grade, so there is no
    strength to state and none is claimed. The same rule a block already
    follows: where nothing carries a grade, nothing is said."""
    from viva.tools.envelope import STRENGTH

    result = run("how much have you got on file?",
                 _script(_shape(("I am holding {many} document(s).",
                                 [("many", "count", "count", "whole")])),
                         ("check_completeness", {}),
                         bind=lambda r: {"many": {"figure": "f1"}}),
                 registry)
    assert result.answered, result.detail
    assert result.grade == ""
    assert all(moment(STOOD_BEHIND_MOMENT + grade) not in result.text
               for grade in STRENGTH), result.text


def test_a_refusal_says_nothing_about_how_well_anything_is_stood_behind(
        registry):
    """A turn with nothing to say states no strength. There is no set of stated
    figures for a grade to be about."""
    from viva.tools.envelope import STRENGTH

    result = run("balance?",
                 _script(_shape(("Your balance is {total}.",
                                 [("total", "money", "balance", "account")])),
                         BALANCES,
                         bind=lambda r: {"total": {"figure": "f99"}}),
                 registry)
    assert not result.answered
    assert all(moment(STOOD_BEHIND_MOMENT + grade) not in result.text
               for grade in STRENGTH), result.text


def test_a_figure_stated_as_a_number_is_graded_though_a_block_also_holds_it():
    """The other half of the same rule. A figure named in a sentence of its own
    has said nothing about how well it is stood behind, so the answer says it —
    however many blocks that figure also appears in."""
    shape = _shape(("You spent {slice_}.",
                   [("slice_", "money", "spending", "subcategory")]))
    result = run("what did I spend on that?",
                 _script(shape, BY_SUBCATEGORY,
                         bind=lambda r: {"slice_": {"figure": _figure_id(
                             r, "subcategory 'everything / slice 00'")}}),
                 _wide(4))
    assert result.answered, result.detail
    assert moment(STOOD_BEHIND_MOMENT + result.grade) in result.text


def test_no_hole_can_ask_how_well_a_figure_is_stood_behind():
    """The hole is retired, not merely unused. A grade is a property of a
    figure that the machine holds, so it is placed by the machine and there is
    nothing for a shape to reserve a place for — nor any renderer that would
    write the ladder's word into a sentence."""
    from viva.tools.shape import CHOOSE_A_KIND

    assert "grade" not in SLOT_TYPES
    assert "grade" not in render.TYPES and "grade" not in render.RENDERED
    assert not hasattr(render, "grade")
    _shape_, problem = read_shape(
        {"clauses": [{"text": "That figure is {trust}.",
                      "slots": [{"name": "trust", "type": "grade"}]}]})
    assert _shape_ is None and problem.repair == CHOOSE_A_KIND


def test_a_boundary_is_not_said_three_times_for_one_set_of_gaps():
    """A net worth and each of its two sides carry three overlapping lists of
    the same gaps by design. An answer stating all three used to say three
    near-identical sentences, two of them naming subsets of the first — the
    degradation a placed channel is most prone to, deterministic and with no
    model in it. What the answer leaves out is one set across every figure it
    stated, said once.

    The vault holds one unmeasured account on each side, so the three lists are
    genuinely three different sets and a run that merged them by rendered text
    could not have collapsed them."""
    p = Provenance("doc-jan", 1, "r")
    registry = default_registry(LedgerProjection([
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01"),
        account_opened("brk", "investment", "Brokerage", "USD", "2026-01-01"),
        account_opened("loan", "liability", "Home Loan", "USD", "2026-01-01"),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", "9900.00", "2026-01-01", p),
        closing_balance_observed("chk", "9900.00", "2026-01-31",
                                 Provenance("doc-jan", 6, "r")),
    ]))
    shape = _shape(("Net {n}, held {a}, owed {l}.",
                    [("n", "money", "net_worth", "currency"),
                     ("a", "money", "balance", "currency"),
                     ("l", "money", "owed", "currency")]))
    result = run("where do I stand?",
                 _script(shape,
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "net_worth"}),
                         bind=lambda r: {
                             "n": {"figure": _figure_id(r, "net in")},
                             "a": {"figure": _figure_id(r, "assets in")},
                             "l": {"figure": _figure_id(r, "liabilities in")}}),
                 registry)
    assert result.answered, result.detail
    # Every gap any of the three figures carries, named once, in one sentence.
    _, _, frame = moment("boundary_unmeasured", account="\x00").partition("\x00")
    assert result.text.count(frame) == 1
    assert moment("boundary_unmeasured", account=render.accounts(
        [{"account": "brk"}, {"account": "loan"}])) in result.text
    # The three figures really do disagree about their own gaps, or this test
    # would pass on a vault that could never have produced the failure.
    gaps = {tuple(item["account"]
                  for item in (f["boundary"].get("unmeasured") or []))
            for f in result.figures}
    assert len(gaps) == 3, gaps


def test_a_gap_no_account_can_name_is_still_said():
    """A document read and not posted is money no figure here carries, and it
    has no account to name — it may be about one that does not exist yet, which
    is why the point keeps it apart from everything it lists per account.

    A figure that declared itself short of it and said nothing would leave a
    person told a total is incomplete with no way to learn of what. It is said
    as a number of documents."""
    from viva.ledger.events import statement_held
    p = Provenance("doc-jan", 1, "r")
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", p),
           closing_balance_observed("chk", "1000.00", "2026-01-31",
                                    Provenance("doc-jan", 6, "r")),
           document_captured("doc-x", "x.pdf", 90, "bank_statement", 0.5,
                             "2026-02-01"),
           statement_held("doc-x", {"account_ref": "elsewhere"}, None, "gap",
                          "2026-02-01")]
    registry = default_registry(LedgerProjection(evs))
    result = run("what am I worth?",
                 _script(_shape(("Your net worth is {n}.",
                                 [("n", "money", "net_worth", "currency")])),
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "net_worth"}),
                         bind=lambda r: {"n": {"figure": _figure_id(r, "net in")}}),
                 registry)
    assert result.answered, result.detail
    stated = next(f for f in result.figures if f["what"].startswith("net in"))
    assert stated["boundary"] == {"whole": False, "unposted": 1,
                                  "cut": [{"kind": "currency",
                                          "value": "USD"}]}
    assert moment("boundary_unposted", count=render.count(1)) in result.text
