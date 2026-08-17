"""A sentence is a structure before it is a sentence.

The properties here are the ones the answer direction now rests on, and they
are properties of a *structure the machine built* rather than of a sentence
anybody read. Nothing below inspects prose. Between them they say: the words
carry no digits, the shape is fixed before any data exists, a second shape can
only take claims away, every hole is filled by a reference into what the run
established, a hole nothing can fill costs its clause and not the turn, and a
caveat a result wrote about its own number cannot be quietly dropped.
"""

from decimal import Decimal

import pytest
from vivacore.verify.normalize import parse_amount, parse_date

from viva import quantity, render
from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)
from viva.ledger.events import document_captured
from viva.persona import INTENT_FIELDS, moment
from viva.tools import default_registry, run
from viva.tools import shape as shape_module
from viva.tools.shape import (CHOOSE_THE_QUANTITY, DROP_THE_QUANTITY,
                              MAGNITUDE_TYPES, MAX_CLAUSES, NAME_THE_QUANTITY,
                              PLAIN_TYPES, REPAIRS, SLOT_TYPES, BadShape,
                              Clause, Shape, Slot, read_shape, weakens)


def _events():
    p = Provenance("doc-jan", 1, "r")
    return [
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01", institution="Northgate Bank",
                       account_number="XX4417", account_names=["R VANCE"]),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", "1000.00", "2026-01-01", p),
        simple_transaction("chk", "-400.00", "GREENFIELD MARKET",
                           "2026-01-05", provenance=p),
        closing_balance_observed("chk", "600.00", "2026-01-31",
                                 Provenance("doc-jan", 6, "r")),
    ]


@pytest.fixture()
def registry():
    return default_registry(LedgerProjection(_events()))


def _shape(*clauses):
    """A shape as a planner commits one. Each hole is `(name, type)`, or
    `(name, type, what its number measures)` where it holds one."""
    return Shape(clauses=tuple(
        Clause(text=text, slots=tuple(Slot(*slot) for slot in slots))
        for text, slots in clauses))


def _script(shape, *calls, bind=None):
    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if len(done) < len(calls):
            tool, args = calls[len(done)]
            return {"tool": tool, "args": args}
        return {"bindings": {} if bind is None else bind(context["results"])}
    return planner


BALANCES = ("query_ledger", {"entity": "balances", "filters": {"account": "chk"}})


# --------------------------------------------------------------- the grammar


@pytest.mark.parametrize("text", [
    "You spent 400 last month.",
    "Your balance is 600.00.",
    "As of 2026-01-31 you were fine.",
    "You made 3 payments.",
    "Nothing changed in Q1.",
])
def test_no_words_in_a_shape_may_carry_a_digit(text):
    """The one rule that makes a magnitude unable to reach a person except
    through a hole. It is a character class over one field: nothing here reads
    the sentence, guesses at meaning, or keeps a list of words — so there is
    nothing to widen and nothing to keep up to date."""
    with pytest.raises(BadShape):
        Clause(text=text)


def test_a_clause_with_no_digits_is_fine_however_it_is_worded():
    """And the other half: prose is not being policed. Any sentence at all is
    acceptable so long as every magnitude in it is a hole."""
    clause = Clause(text="You spent a great deal more than usual, frankly.")
    assert clause.written({}) == "You spent a great deal more than usual, frankly."


def test_a_hole_and_its_declaration_must_agree():
    """A hole nothing declares says nothing about what fills it; a declaration
    with no hole fills nothing. Either way the shape does not come into being,
    so no later check has to allow for one."""
    with pytest.raises(BadShape):
        Clause(text="You have {total}.")
    with pytest.raises(BadShape):
        Clause(text="Nothing to report.",
               slots=(Slot(name="total", type=render.MONEY),))
    with pytest.raises(BadShape):
        Clause(text="You have {total}.",
               slots=(Slot(name="other", type=render.MONEY),))


def test_a_hole_declares_a_kind_of_thing_in_the_world():
    with pytest.raises(BadShape):
        Clause(text="You have {total}.",
               slots=(Slot(name="total", type="number"),))
    with pytest.raises(BadShape):
        Clause(text="You have {total}.",
               slots=(Slot(name="total", type="text"),))


def test_two_holes_in_one_shape_may_not_share_a_name():
    """A binding names one hole. A name used twice would fill two claims at
    once, and the second would be a claim nobody bound."""
    with pytest.raises(BadShape):
        _shape(("You have {x}.", [("x", "money", "balance")]),
               ("And {x} besides.", [("x", "money", "balance")]))


def test_a_shape_of_nothing_is_not_an_answer():
    with pytest.raises(BadShape):
        Shape(clauses=())
    with pytest.raises(BadShape):
        _shape(*[("A clause.", [])] * (MAX_CLAUSES + 1))


def test_a_malformed_shape_is_something_to_say_back_never_an_exception():
    """A shape a model sent is read, never trusted. Every way it can be wrong
    comes back as a sentence the model can act on."""
    for bad in (None, "clauses", {}, {"clauses": []}, {"clauses": [1]},
                {"clauses": [{"slots": []}]},
                {"clauses": [{"text": "hi", "slots": "none"}]},
                {"clauses": [{"text": "hi {x}", "slots": [{"name": "x"}]}]},
                {"clauses": [{"text": "you spent 400", "slots": []}]}):
        shape, problem = read_shape(bad)
        assert shape is None and problem, bad


def test_a_well_formed_shape_reads_back_as_the_structure_it_declares():
    shape, problem = read_shape({"clauses": [
        {"text": "Your {which} holds {total}.",
         "slots": [{"name": "which", "type": "account"},
                   {"name": "total", "type": "money",
                    "quantity": "balance"}]}]})
    assert problem == ""
    assert set(shape.slots) == {"which", "total"}
    assert shape.slots["total"].type == render.MONEY
    assert shape.slots["total"].quantity == quantity.BALANCE
    assert shape.slots["which"].quantity == ""


# ----------------------------------------------------- the order, which is it


def test_the_shape_is_committed_before_anything_is_read(registry):
    """The load-bearing property. A model that has never seen a figure cannot
    tailor a claim to the one it happened to find — it does not know what will
    be found, or whether anything will be.

    Enforced twice over: the reads are not on the table until a shape is
    committed, and a shape offered after the run holds something is refused."""
    seen = []

    def planner(context):
        seen.append((context["shaped"], bool(context["tools"])))
        if not context["shaped"]:
            return {"shape": _shape(("All settled.", []))}
        return {"bindings": {}}

    assert run("?", planner, registry).answered
    assert seen[0] == (False, False), (
        "a read was on the table before the sentence was authored")
    assert seen[1] == (True, True)


def test_a_read_before_a_shape_refuses_the_turn(registry):
    """A planner that reaches for a tool anyway does not get one."""
    result = run("balance?", lambda context: {"tool": "query_ledger",
                                              "args": {"entity": "balances"}},
                 registry)
    assert not result.answered and result.refusal == "unshaped_read"


def test_a_delivery_with_no_shape_refuses_the_turn(registry):
    result = run("balance?", lambda context: {"bindings": {}}, registry)
    assert not result.answered and result.refusal == "unshaped_answer"


def test_a_shape_offered_after_a_read_is_refused():
    """The rule itself, not the table it is enforced through. A first shape
    written with figures already in hand is refused however it got there, so
    the ordering does not rest on a planner being offered the right menu."""
    from viva.tools.runner import _Ground, _committable

    empty = _Ground()
    assert _committable(None, _shape(("Fine.", [])), empty) == ""

    holding = _Ground()
    holding.book["f1"] = {"id": "f1"}
    assert _committable(None, _shape(("Fine.", [])), holding)


def test_a_second_shape_may_only_take_claims_away():
    """Re-shaping, monotone. Results can contradict what a shape assumed, and a
    clause may then be dropped — but a clause written after its data is exactly
    what the order exists to prevent, so nothing may be added or reworded."""
    first = _shape(("You hold {a}.", [("a", "money", "balance")]),
                   ("It is {g}.", [("g", "grade")]),
                   ("As of {d}.", [("d", "date")]))
    assert weakens(first, first)
    assert weakens(first, _shape(("You hold {a}.", [("a", "money", "balance")])))
    assert weakens(first, _shape(("It is {g}.", [("g", "grade")]),
                                 ("As of {d}.", [("d", "date")])))
    # Added, reworded, and re-ordered: none of the three.
    held = ("You hold {a}.", [("a", "money", "balance")])
    assert not weakens(first, _shape(held, ("And more.", [])))
    assert not weakens(first, _shape(("You hold plenty.", [])))
    assert not weakens(first, _shape(("It is {g}.", [("g", "grade")]), held))


def test_a_reshape_that_adds_a_claim_is_refused_and_the_turn_goes_on(registry):
    """And end to end: the widening is refused, the shape in force stands, and
    the model is told why rather than the turn dying."""
    first = _shape(("Your balance is {total}.", [("total", "money", "balance")]))
    wider = _shape(("Your balance is {total}.", [("total", "money", "balance")]),
                   ("That is unusually high.", []))
    tries = []

    def planner(context):
        if not context["shaped"]:
            return {"shape": first}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": BALANCES[1]}
        if not tries:
            tries.append(True)
            return {"shape": wider}
        return {"bindings": {"total": {"figure": "f1"}}}

    result = run("balance?", planner, registry)
    assert result.answered, result.detail
    assert result.text == "Your balance is USD 600.00."
    refused = [r for r in result.transcript if r["tool"] == "commit_shape"]
    assert [r["ok"] for r in refused] == [True, False]
    assert "only drop clauses" in refused[-1]["text"]


def test_what_a_taken_shape_is_answered_with_is_a_file(registry):
    """What the runner says back when it takes a shape is text a model reads,
    and text a model reads is a versioned file. As a literal it would be
    editable in place, unrecorded, and invisible to the freeze."""
    from vivacore import promptstore, versions

    from viva.tools.registry import PACKAGE, PROMPTS
    from viva.tools.runner import COMMITTED_VERSION

    result = run("balance?",
                 _script(_shape(("All settled.", []))), registry)
    assert result.answered
    (taken,) = [r for r in result.transcript if r["tool"] == "commit_shape"]
    assert taken["text"] == promptstore.load(PROMPTS, COMMITTED_VERSION)
    assert COMMITTED_VERSION == versions.active(PACKAGE, "shape_committed")


# ------------------------------------------------------------- the checks


def test_a_binding_naming_no_hole_is_refused(registry):
    """Totality, one way: a binding that names nothing in the shape is the
    model asserting something the sentence never had room for."""
    result = run("balance?",
                 _script(_shape(("All settled.", [])), BALANCES,
                         bind=lambda r: {"total": {"figure": "f1"}}),
                 registry)
    assert not result.answered and result.refusal == "unshaped_binding"


def test_a_hole_nothing_can_fill_costs_its_clause_and_not_the_turn(registry):
    """Totality, the other way: a hole nothing fills does not refuse the turn.

    The clause carrying it is dropped, what could be established still stands,
    and the person is told plainly what was missing."""
    shape = _shape(("Your balance is {total}.", [("total", "money", "balance")]),
                   ("It was last touched on {when}.", [("when", "date")]))
    result = run("balance?",
                 _script(shape, BALANCES,
                         bind=lambda r: {"total": {"figure": "f1"}}),
                 registry)
    assert result.answered, result.detail
    assert result.text.startswith("Your balance is USD 600.00.")
    assert "last touched" not in result.text
    assert "a day" in result.text            # the gap, named by its kind
    assert result.gaps == [{"name": "when", "type": "date"}]


def test_an_answer_whose_every_clause_falls_away_says_so(registry):
    result = run("balance?",
                 _script(_shape(("Your balance is {total}.",
                                 [("total", "money", "balance")])), BALANCES),
                 registry)
    assert not result.answered and result.refusal == "nothing_established"


def test_a_thing_of_the_wrong_kind_cannot_fill_a_hole(registry):
    """Type, over every pairing the run can produce. An amount states a
    currency and a plain number states none, which is the distinction the
    emitters already make, so this is a check over a field the code computes
    rather than over anything anybody wrote."""
    for hole, reference in (((render.MONEY, "balance"), {"figure": "f2"}),
                            ((render.COUNT, "count"), {"figure": "f1"}),
                            ((render.DATE,), {"figure": "f1"}),
                            ((render.ACCOUNT,), {"figure": "f1"}),
                            ((render.MONEY, "balance"), {"entity": "a1"}),
                            ((render.MERCHANT,), {"entity": "a1"}),
                            ((render.PERIOD,), {"date": "2026-01-31"}),
                            ((render.SUPPOSED, "balance"), {"figure": "f1"})):
        result = run("?", _script(_shape(("It is {x}.", [("x", *hole)])),
                                  BALANCES,
                                  bind=lambda r, b=reference: {"x": b}),
                     registry)
        assert not result.answered, (hole, reference)
        assert result.refusal in ("wrong_kind", "wrong_quantity",
                                  "unfounded_date"), (
            (hole, reference, result.refusal))


def test_a_caveat_a_result_wrote_about_its_own_number_cannot_be_dropped(registry):
    """A caveat is the tool saying what its own figure does not cover, and the
    answer says it whether or not the shape ever mentioned one.

    No hole asks for a caveat. A shape is authored before anything is read, so
    whether there will be one to place is not knowable when a hole for it would
    have to be declared — leaving the saying of it to the shape was leaving it
    to a guess. The run places what its stated figures owe."""
    spending = ("query_ledger", {"entity": "aggregate", "metric": "spending"})
    silent = _shape(("You spent {total}.", [("total", "money", "spending")]))
    result = run("what did I spend?",
                 _script(silent, spending,
                         bind=lambda r: {"total": {"figure": _spending(r)}}),
                 registry)
    assert result.answered, result.detail
    assert result.text.startswith("You spent USD 400.00.")
    assert "Own-account transfers" in result.text, (
        "the shape says nothing about limits, and the run places them anyway")
    # Once, however many results wrote it, and introduced in Viva's own words.
    assert result.text.count("Own-account transfers") == 1
    assert moment("answer_limits", limits="").split("{")[0].strip() in result.text


def _spending(results):
    return next(f["id"] for f in results[-1]["figures"]
                if "total spending" in f["what"])


def test_a_shape_cannot_declare_a_hole_for_a_caveat(registry):
    """The bet a shape used to have to make, removed by removing the hole.

    A caveat hole was declared before any read, so a shape that authored one
    and read no caveats lost the clause holding it, and a shape that authored
    none and read one refused. Neither is reachable now: `caveat` is not a kind
    of thing a hole may hold, and the run places what its figures owe."""
    assert render.CAVEAT not in SLOT_TYPES
    with pytest.raises(BadShape):
        Clause(text="Bear in mind: {limits}",
               slots=(Slot(name="limits", type=render.CAVEAT),))
    shape, problem = read_shape({"clauses": [
        {"text": "Bear in mind: {limits}",
         "slots": [{"name": "limits", "type": "caveat"}]}]})
    assert shape is None and "caveat" in problem


def test_a_reference_the_hole_can_only_read_one_way_is_read_that_way(registry):
    """A correct answer is not lost to a reference that said the same thing in
    fewer words.

    A date hole holds a day and nothing else, so a delivery naming the day
    without naming it AS a day has still said which day it means. What changed
    is the shape of the reference, never what it has to answer for."""
    shape = _shape(("As of {when}, that is where it stood.", [("when", "date")]))
    result = run("when?",
                 _script(shape, BALANCES,
                         # The day, bare: a value where the named form was wanted.
                         bind=lambda r: {"when": "2026-01-31"}),
                 registry)
    assert result.answered, result.detail
    assert result.text.startswith("As of ")
    # And it is answerable as a date reference, which is what it was.
    assert list(result.bindings["when"]) == ["date"]


def test_no_hole_may_be_bound_to_several_things(registry):
    """Every hole holds one thing. A list arriving at one names nothing, and
    completing it from the hole's type would put a list of days where a day
    goes."""
    shape = _shape(("As of {when}, that is where it stood.", [("when", "date")]))
    result = run("when?",
                 _script(shape, BALANCES,
                         bind=lambda r: {"when": ["2026-01-31", "2026-01-05"]}),
                 registry)
    assert not result.answered and result.refusal == "bad_binding"


def test_a_magnitude_hole_still_needs_to_say_which_kind_of_thing_fills_it(registry):
    """The other side of the same rule, and the reason it is the hole's type
    that decides. A figure this run read and an amount the person supposed both
    belong in a money hole, so a bare value there names nothing and is refused
    — inferring one would let a number the person never said be spoken as a
    figure, or the reverse."""
    shape = _shape(("Your balance is {total}.",
                    [("total", "money", "balance")]))
    result = run("balance?",
                 _script(shape, BALANCES, bind=lambda r: {"total": "f1"}),
                 registry)
    assert not result.answered and result.refusal == "bad_binding"


def test_a_caveat_behind_a_figure_no_clause_states_is_not_owed(registry):
    """What survives is what asserts, so what survives is what answers for its
    caveats. A clause that fell away states nothing and owes nothing."""
    shape = _shape(("Your balance is {held}.", [("held", "money", "balance")]),
                   ("You spent {spent} on {when}.",
                    [("spent", "money", "spending"), ("when", "date")]))
    result = run(
        "what did I spend?",
        _script(shape, BALANCES,
                ("query_ledger", {"entity": "aggregate",
                                  "metric": "spending"}),
                # The second clause loses its day, so it falls away — and the
                # spending figure it would have stated falls away with it.
                bind=lambda r: {"held": {"figure": "f1"},
                                "spent": {"figure": _spending(r)}}),
        registry)
    assert result.answered, result.detail
    assert result.text.startswith("Your balance is USD 600.00.")
    assert "You spent" not in result.text


# --------------------------------------------- what a number says it is of


def test_a_gross_sum_of_postings_cannot_be_spoken_as_what_was_spent(registry):
    """The mislabelling, in the shape it actually took: a real figure, cited
    correctly, standing under a claim about something it does not measure.

    Money out over a set of movements is postings summed by their sign. It
    includes settlements and money moved between the person's own accounts, so
    it is not what they spent — and a sentence that says spending gets the
    figure that measures spending, or it gets nothing."""
    summary = ("query_ledger", {"entity": "transactions"})
    shape = _shape(("You spent {total}.", [("total", "money", "spending")]))
    result = run(
        "how much did I spend?",
        _script(shape, summary,
                bind=lambda r: {
                    "total": {"figure": _named(r, "money out over")}}),
        registry)
    assert not result.answered, result.text
    assert result.refusal == "wrong_quantity"
    assert result.text == moment("refusal_wrong_quantity")


def test_a_count_of_things_cannot_be_spoken_as_a_proportion(registry):
    """The same mislabelling one size down, and the reason the count-or-
    proportion question is no longer settled by whether the value came out
    whole. Three documents is three of something; it is not three per
    hundred of anything, and no property of the number says so."""
    shape = _shape(("That is {share} of your spending.",
                    [("share", "rate", "ratio")]))
    result = run(
        "how much of my spending is that?",
        _script(shape, ("check_completeness", {}),
                bind=lambda r: {
                    "share": {"figure": _named(r, "documents held")}}),
        registry)
    assert not result.answered, result.text
    assert result.refusal == "wrong_quantity"


def test_the_figure_the_hole_asked_about_is_spoken(registry):
    """And the other side of it, so the check is not merely refusing
    everything: the figure that measures what the sentence is about goes
    through, and is written as the amount it is."""
    spending = ("query_ledger", {"entity": "aggregate", "metric": "spending"})
    shape = _shape(("You spent {total}.", [("total", "money", "spending")]))
    result = run(
        "how much did I spend?",
        _script(shape, spending,
                bind=lambda r: {
                    "total": {"figure": _spending(r)}}),
        registry)
    assert result.answered, result.detail
    assert result.text.startswith("You spent USD 400.00.")


# ------------------------------------- an account someone is owed on

def _card_events(closing, txns):
    """A vault holding money and a card someone owes on, whose figure is what
    is owed as the bill prints it: positive where the person owes, negative
    where the card owes them."""
    p = Provenance("doc-card", 1, "r")
    evs = _events() + [
        account_opened("card", "liability", "Signature Card", "USD",
                       "2026-01-01", institution="Meridian Cards"),
        document_captured("doc-card", "card.pdf", 100, "card_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("card", "0.00", "2026-01-01", p),
    ]
    for date, description, amount in txns:
        evs.append(simple_transaction("card", amount, description, date,
                                      provenance=p))
    evs.append(closing_balance_observed("card", closing, "2026-01-31",
                                        Provenance("doc-card", 6, "r")))
    return default_registry(LedgerProjection(evs))


OWING = [("2026-01-08", "CITY GYM", "1000.00")]
OVERPAID = OWING + [("2026-01-20", "PAYMENT RECEIVED", "-1050.00")]

CARD_BALANCES = ("query_ledger", {"entity": "balances",
                                  "filters": {"account": "card"}})


def _both_ways(first, second, read, bind):
    """A planner that shapes for both of the things the question might turn out
    to be about, reads, and then commits the shorter shape that keeps the one
    that applied."""
    reshaped = []

    def planner(context):
        if not context["shaped"]:
            return {"shape": first}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": read[0], "args": read[1]}
        if not reshaped:
            reshaped.append(True)
            return {"shape": second}
        return {"bindings": bind(context["results"])}
    return planner


OWES = ("You owe {debt} on {which}.",
        [("debt", "money", "owed"), ("which", "account")])
HOLDS = ("Your {holding} balance is {amount}.",
         [("holding", "account"), ("amount", "money", "balance")])


def _the_card(results):
    """The account a read spoke about, by the handle its identifiers use."""
    return next(i["id"] for result in results
                for i in (result.get("identifiers") or [])
                if i["label"] == "card")


def _spoken_about_the_card(events):
    """One turn about an account the person may hold or may owe on, shaped both
    ways before the read and narrowed to the clause that applied."""
    return run("what's my card balance?",
               _both_ways(_shape(OWES, HOLDS), _shape(OWES), CARD_BALANCES,
                          bind=lambda r: {
                              "debt": {"figure": _named(r, "Signature Card")},
                              "which": {"entity": _the_card(r)}}),
               events)


def test_a_card_someone_owes_on_is_spoken_as_what_is_owed():
    """A turn in the order a turn runs. The shape is authored before anything
    is read, so it carries a clause for each of the two things an account can
    turn out to be; the read says which; the second shape drops the clause that
    did not apply, which is a narrowing and needs no rewording.

    The figure is the one the bill prints, and the sentence around it says what
    it is."""
    result = _spoken_about_the_card(_card_events("1000.00", OWING))
    assert result.answered, result.detail
    assert result.text.startswith(
        f"You owe {render.money(Decimal('1000.00'), 'USD')} on ")
    assert "balance is" not in result.text


def test_an_overpaid_cards_sign_survives_into_what_is_spoken():
    """What is checked here is the sign and nothing more.

    A card paid past its balance owes the person, and its magnitude is negative
    in the owed convention. The figure carries that sign the whole way, so the
    amount reaching the person is written as a negative and the debt clause is
    not filled with a positive one.

    The wording is not fixed and this test does not claim it is: the live path
    says "You owe -USD 50.00 on ...", which is a credit spoken as a negative
    debt. That is an open defect, recorded rather than tested away — the shape
    is authored before the read, and which clauses a live model writes is not
    something anything here can establish."""
    result = _spoken_about_the_card(_card_events("-50.00", OVERPAID))
    assert result.answered, result.detail
    written = render.money(Decimal("-50.00"), "USD")
    assert written in result.text and written.startswith("-")
    assert f"owe {render.money(Decimal('50.00'), 'USD')}" not in result.text


def test_what_is_owed_cannot_fill_a_hole_that_asked_for_what_is_held():
    """The clause today's wrong sentence was built out of. The shape asks for a
    balance, the read comes back with a debt, and the check that has run all
    along now has something to catch: no answer rather than a confident one
    under the wrong word."""
    result = run("what's my card balance?",
                 _script(_shape(HOLDS), CARD_BALANCES,
                         bind=lambda r: {
                             "amount": {"figure": _named(r, "Signature Card")},
                             "holding": {"entity": _the_card(r)}}),
                 _card_events("1000.00", OWING))
    assert not result.answered and result.refusal == "wrong_quantity"


def test_a_magnitude_nothing_measured_can_fill_no_hole(registry):
    """Arithmetic over literals alone produces a number nobody has said the
    meaning of. There is no hole it belongs in, because there is no hole that
    can ask for "whatever this is" — which is the entry the vocabulary
    deliberately does not have."""
    shape = _shape(("That comes to {total}.", [("total", "count", "count")]))
    result = run("how many?",
                 _script(shape,
                         ("compute", {"expression": "12 + 30", "inputs": {}}),
                         bind=lambda r: {
                             "total": {"figure": _named(r, "result of")}}),
                 registry)
    assert not result.answered and result.refusal == "wrong_quantity"


def test_a_hole_holding_a_magnitude_must_say_what_the_magnitude_is_of():
    """Half the check is that both sides declare. A hole that says only "a
    number goes here" is one anything at all can be put into, so it is not a
    shape the machine will take — and it is refused before a single read has
    run, which is where a shape's faults belong."""
    for hole in ({"name": "total", "type": "money"},
                 {"name": "total", "type": "count"},
                 {"name": "total", "type": "rate"},
                 {"name": "total", "type": "money", "quantity": "count"},
                 {"name": "total", "type": "rate", "quantity": "spending"}):
        shape, problem = read_shape(
            {"clauses": [{"text": "It is {total}.", "slots": [hole]}]})
        assert shape is None and problem, hole


def test_a_hole_holding_no_magnitude_may_not_claim_one():
    """And the reverse: an account and a day measure nothing, so a quantity on
    one of them is a declaration about a number that is not there."""
    shape, problem = read_shape({"clauses": [
        {"text": "It is {which}.",
         "slots": [{"name": "which", "type": "account",
                    "quantity": "balance"}]}]})
    assert shape is None and problem


def _hole(kind, measures=""):
    """One clause holding one hole of `kind`, as a model sends it."""
    slot = {"name": "it", "type": kind}
    if measures:
        slot["quantity"] = measures
    return {"clauses": [{"text": "It is {it}.", "slots": [slot]}]}


def _offered_holes():
    """Each alternative the form offers for one hole, by the kind it is for."""
    from viva.speak import SHAPE_PARAMS

    holes = (SHAPE_PARAMS["properties"]["clauses"]["items"]
             ["properties"]["slots"]["items"])
    offered = {}
    for alternative in holes["oneOf"]:
        for kind in alternative["properties"]["type"]["enum"]:
            assert kind not in offered, f"{kind} is offered twice"
            offered[kind] = alternative
    return offered


def test_the_form_a_model_fills_in_and_the_check_reading_it_back_agree():
    """The form a model fills in and the check reading it back describe one
    rule, compared here kind by kind and quantity by quantity.

    A hole is offered as a magnitude, which must say what its number is of and
    may say only what that kind of number can be of, or as anything else, which
    has no field to say it in. Asserted over the whole vocabulary, not a
    sample: what the form tells a model of a kind is exactly what the check
    accepts for it."""
    offered = _offered_holes()

    # Every kind a hole may declare, and only those: the two kinds the runner
    # places itself are not a model's to ask for.
    assert set(offered) == set(SLOT_TYPES)
    assert render.CAVEAT not in offered and render.PROSE not in offered
    carrying = {k for k, form in offered.items()
                if "quantity" in form["properties"]}
    assert carrying == set(MAGNITUDE_TYPES)
    assert set(offered) - carrying == set(PLAIN_TYPES)

    for kind, form in offered.items():
        carries = kind in carrying
        # What the form says this kind may declare, and what the check takes,
        # over the whole vocabulary — not a sample of it.
        told = set(form["properties"].get("quantity", {}).get("enum", ()))
        taken = {measures for measures in quantity.KINDS
                 if read_shape(_hole(kind, measures))[0] is not None}
        assert told == taken, kind
        assert told == set(shape_module.quantities_of(kind)), kind

        # And whether the field may be there at all, which is the same claim
        # made by the presence of the field and by `required`.
        assert bool(taken) == carries, kind
        assert ("quantity" in form["required"]) == carries, kind
        assert (read_shape(_hole(kind))[0] is not None) != carries, kind

        # A hole matches one alternative and not two. Without this, a hole
        # carrying a quantity satisfies the plain form as well as its own, and
        # an alternation satisfied twice is satisfied by nothing.
        assert form["additionalProperties"] is False, kind


def test_the_form_offers_no_pairing_the_check_would_refuse():
    """The same agreement, counted rather than compared: every
    kind-and-quantity pair the form allows is one the check accepts, and the
    form offers at least one pair."""
    offered = _offered_holes()
    refused = [(kind, measures)
               for kind, form in offered.items()
               for measures in form["properties"].get("quantity", {})
               .get("enum", ())
               if read_shape(_hole(kind, measures))[0] is None]
    assert refused == []
    # And the form is not empty of them either: a form offering nothing would
    # pass the line above and describe a hole no model could fill.
    pairs = sum(len(form["properties"].get("quantity", {}).get("enum", ()))
                for form in offered.values())
    assert pairs == sum(len(shape_module.quantities_of(kind))
                        for kind in SLOT_TYPES) > 0


def test_the_form_asks_for_the_kinds_of_value_the_reader_insists_on():
    """The other axis of the same agreement: a clause's words, a hole's name
    and a hole's quantity are described to a model as text, and the reader
    refuses each of them written as a number.

    Each pair below is the form's claim and the reader's answer to a value that
    contradicts it, so neither side can drift alone."""
    from viva.speak import SHAPE_PARAMS

    clause = SHAPE_PARAMS["properties"]["clauses"]["items"]
    assert clause["properties"]["text"]["type"] == "string"
    assert "text" in clause["required"]
    assert read_shape({"clauses": [{"text": 7, "slots": []}]})[0] is None

    for kind, form in _offered_holes().items():
        assert form["properties"]["name"]["type"] == "string", kind
        assert "name" in form["required"], kind
        assert form["properties"]["type"]["type"] == "string", kind
        if "quantity" in form["properties"]:
            assert form["properties"]["quantity"]["type"] == "string", kind

    # And the reader refuses each of those values written as a number, so what
    # the form asks for is what it takes.
    measures = shape_module.quantities_of(render.MONEY)[0]
    for slot in ({"name": 7, "type": render.MONEY, "quantity": measures},
                 {"type": render.MONEY, "quantity": measures},
                 {"name": "it", "type": 7, "quantity": measures},
                 {"name": "it", "type": render.MONEY, "quantity": 7}):
        assert read_shape(
            {"clauses": [{"text": "It is {it}.", "slots": [slot]}]})[0] is None


def test_a_hole_that_measures_nothing_is_told_to_take_the_field_out():
    """A hole of a kind that measures nothing, carrying a quantity, is refused
    with the repair `drop_the_quantity` — for every such kind."""
    for kind in PLAIN_TYPES:
        shape, problem = read_shape(_hole(kind, sorted(quantity.KINDS)[0]))
        assert shape is None and problem.repair == DROP_THE_QUANTITY, kind


def test_a_hole_naming_no_quantity_and_one_naming_the_wrong_one_differ():
    """Two defects that read alike carry different repairs. A hole that sent
    no quantity is told to name one; a hole that sent a quantity its kind
    cannot be of is told to change it, and the defect names both what was sent
    and what may be sent instead."""
    for kind in MAGNITUDE_TYPES:
        allowed = shape_module.quantities_of(kind)
        missing = read_shape(_hole(kind))[1]
        assert missing.repair == NAME_THE_QUANTITY, kind

        wrong = next((m for m in quantity.KINDS if m not in allowed), "")
        if not wrong:
            continue                 # a kind that may be of anything at all
        said = read_shape(_hole(kind, wrong))[1]
        assert said.repair == CHOOSE_THE_QUANTITY, kind
        # The defect names what was sent and what may be sent instead, so the
        # repair has something to point at.
        assert wrong in said and allowed[0] in said


def test_every_way_a_shape_can_be_refused_says_what_to_change():
    """Every defect the reader can find names a repair out of the closed
    list — no refusal reaches a model without one."""
    long_clause = "x" * (400 + 1)
    for bad in (None, "clauses", {}, {"clauses": []}, {"clauses": [1]},
                {"clauses": [{"slots": []}]},
                {"clauses": [{"text": "hi", "slots": "none"}]},
                {"clauses": [{"text": "hi {x}", "slots": [1]}]},
                {"clauses": [{"text": "hi {x}", "slots": [{"name": "x"}]}]},
                {"clauses": [{"text": "hi {x}",
                              "slots": [{"name": "x", "type": "grade",
                                         "quantity": 7}]}]},
                {"clauses": [{"text": "you spent 400", "slots": []}]},
                {"clauses": [{"text": "   ", "slots": []}]},
                {"clauses": [{"text": long_clause, "slots": []}]},
                {"clauses": [{"text": "{x} and {x}",
                              "slots": [{"name": "x", "type": "grade"}]}]},
                {"clauses": [{"text": "nothing placed",
                              "slots": [{"name": "x", "type": "grade"}]}]},
                {"clauses": [{"text": "{x}",
                              "slots": [{"name": "x", "type": "nonsense"}]}]},
                {"clauses": [{"text": "{x}",
                              "slots": [{"name": "x", "type": "money"}]}]},
                {"clauses": [{"text": "{x}",
                              "slots": [{"name": "x", "type": "grade",
                                         "quantity": "count"}]}]},
                {"clauses": [{"text": "a clause.", "slots": []}]
                            * (MAX_CLAUSES + 1)}):
        shape, problem = read_shape(bad)
        assert shape is None, bad
        assert problem.repair in REPAIRS, (bad, problem)


def test_a_stretch_of_time_the_person_named_is_not_written_as_an_amount(registry):
    """A year the person typed is a number they genuinely said, so the rule
    about echoing their own figures back accepts it. What it is a number OF is
    the hole's to declare, and a point in time is written as itself.

    The declaration is the whole of it. Nothing in the run can contradict what
    the person's own sentence meant, because their sentence made no
    declaration — so the same token declared as an amount is written as one."""
    def spoken(measures):
        shape = _shape(("Taking {when}, then.",
                        [("when", "supposed", measures)]))
        result = run("what did I spend in 2026?",
                     _script(shape, ("check_completeness", {}),
                             bind=lambda r: {"when": {"supposed": "2026"}}),
                     registry)
        assert result.answered, result.detail
        return result.text

    assert "2026.00" not in spoken(quantity.TIME)
    assert "2026" in spoken(quantity.TIME)
    assert "2026.00" in spoken(quantity.SPENDING)


def test_the_shape_prompt_teaches_every_quantity_a_hole_can_ask_for():
    """A quantity the code knows and the instructions do not is a hole that
    will never be asked for; one the instructions know and the code does not is
    a shape that will always be refused."""
    from vivacore import promptstore

    from viva.speak import SHAPE_VERSION
    from viva.tools.registry import PROMPTS

    taught = promptstore.load(PROMPTS, SHAPE_VERSION)
    for kind in quantity.KINDS:
        assert f"`{kind}`" in taught, f"the shape grammar never mentions {kind}"
    assert quantity.UNMEASURED not in taught, (
        "the instructions offer a way to say a number means whatever it means")


def _named(results, what):
    return next(f["id"] for r in results for f in (r.get("figures") or [])
                if what in f["what"])


# ------------------------------------------------- the vocabulary, both ways


def test_every_kind_of_thing_a_question_places_can_also_be_answered_with():
    """The completeness check: whatever the asking side needs, the answering
    side needs. A kind of thing only one direction can express means one
    direction cannot talk about something the other can, which is a hole in the
    design rather than an accident of what got built first."""
    asked = {kind for slots in INTENT_FIELDS.values() for kind in slots.values()}
    # Reviewed pack prose is not a kind of thing in the world; it nests one
    # reviewed template inside another, and it is deliberately not a hole.
    asked -= {render.PROSE}
    missing = sorted(asked - set(SLOT_TYPES))
    assert not missing, (
        f"{missing} can be placed in a question and not in an answer")
    unrenderable = sorted(k for k in asked if k not in render.RENDERED)
    assert not unrenderable, (
        f"{unrenderable} is declared as a kind of thing with nothing to write it")


def test_every_kind_a_hole_can_declare_has_exactly_one_way_to_be_written():
    """One renderer per kind, and the renderer is the only thing that makes
    one. A place that asks for an amount can therefore ask for it by type, and
    a string that formatted itself elsewhere cannot be passed off as one."""
    for kind in SLOT_TYPES:
        assert kind in render.RENDERED, kind
        produced = render.RENDERED[kind]
        assert not isinstance("just a string", produced), kind
    assert len(set(render.RENDERED.values())) == len(render.RENDERED)


def test_every_kind_of_magnitude_has_a_way_of_saying_it_was_rounded():
    """A kind of number with nowhere to say "about" is a kind of number that
    reaches a person looking exact when it is not. Which kinds hold a magnitude
    is already declared — they are the kinds that say what they measure — so a
    new one arriving without its own term fails here rather than in front of
    somebody."""
    from viva.tools.runner import APPROX_TERMS

    holders = {kind for kind in render.QUANTITY_OF_TYPE
               if kind != render.SUPPOSED}
    assert set(APPROX_TERMS) == holders, (
        f"only-in-terms={sorted(set(APPROX_TERMS) - holders)}, "
        f"only-in-vocabulary={sorted(holders - set(APPROX_TERMS))}")
    for kind, (key, name, produced) in APPROX_TERMS.items():
        assert produced is render.RENDERED[kind], kind
        # The term is a reviewed line in the pack that places the thing it is
        # about, and nothing else.
        assert moment(key, **{name: "x"}).strip(), key


@pytest.mark.parametrize("locale", ["en-US", "de-DE"])
def test_an_amount_written_by_a_hole_reads_back_as_the_same_amount(locale):
    written = render.money("1234.56", "USD", locale=locale)
    read = parse_amount(written, locale=locale, currency="USD")
    assert read.ok and read.decimal() == Decimal("1234.56")


def test_a_day_written_by_a_hole_reads_back_as_the_same_day():
    written = render.date("2026-01-31")
    read = parse_date(written)
    assert read.ok and read.value == "2026-01-31"


@pytest.mark.parametrize("locale", ["en-US", "de-DE"])
def test_a_proportion_written_by_a_hole_reads_back_as_the_same_proportion(locale):
    """A proportion written into a hole reads back as the same proportion. What
    the product carries is the quotient and what a person is shown is per
    hundred, so the round trip crosses that boundary and runs through the reader
    a reply goes through rather than through the number parser underneath it."""
    from viva.reply import Slot as ReplySlot
    from viva.reply import read_reply
    from viva.schemas import ANSWER_RATE

    written = render.rate("0.5", locale=locale)
    read = read_reply((ReplySlot(name="share", type=ANSWER_RATE, required=True),),
                      {"share": str(written)}, locale=locale)
    assert read.ok and Decimal(read.values["share"]) == Decimal("0.5")


def test_a_count_written_by_a_hole_reads_back_as_the_same_count():
    assert int(render.count(1200)) == 1200
    assert "," not in render.count(1200), (
        "a count is not an amount, and is not grouped like one")


def test_a_thing_is_written_by_its_attributes_and_read_back_as_a_reference():
    """The types that name a thing rather than measure one have no value to
    parse: the person names the thing and the parser resolves it to something
    the vault holds. So the round trip is a reference, and the renderer's job
    is only to choose which of the thing's names is shown."""
    account = {"account": "acct:northgate:4417", "name": "Everyday Checking",
               "number_masked": "••••4417"}
    assert render.account(account) == "Everyday Checking"
    assert render.account({"account": "Assets:Vehicles:The Estate"}) == "The Estate"
    assert render.merchant({"example": "GREENFIELD MARKET",
                            "key": "greenfield market"}) == "GREENFIELD MARKET"
    assert render.category("Groceries") == "Groceries"


def test_the_shape_prompt_teaches_every_kind_a_hole_can_declare():
    """A vocabulary the code knows and the instructions do not is a hole a
    model will never use; one the instructions know and the code does not is a
    shape that will always be refused."""
    from vivacore import promptstore

    from viva.speak import SHAPE_VERSION
    from viva.tools.registry import PROMPTS

    taught = promptstore.load(PROMPTS, SHAPE_VERSION)
    for kind in SLOT_TYPES:
        assert f"`{kind}`" in taught, f"the shape grammar never mentions {kind}"


def test_the_shape_and_its_bindings_are_kept(registry):
    """C-iii, and what keeps C-v open: what was said is recorded as the
    structure it was, so a sentence can be shown standing on what it stood on
    and the shapes a real conversation needs can accumulate."""
    shape = _shape(("Your balance is {total}.", [("total", "money", "balance")]))
    result = run("balance?",
                 _script(shape, BALANCES,
                         bind=lambda r: {"total": {"figure": "f1"}}),
                 registry)
    assert result.answered
    assert result.to_dict()["shape"] == shape.to_dict()
    assert result.to_dict()["bindings"] == {"total": {"figure": "f1"}}


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
                    [("total", "money", "owed")]))
    result = run("what do I owe?",
                 _script(shape, ("query_ledger", {"entity": "balances"}),
                         bind=lambda r: {
                             "total": {"figure": _figure_id(r, "Signature Card")}}),
                 several)
    assert result.answered, result.detail
    assert result.text.startswith("You currently owe ")
    assert moment("boundary_accounts", counted=render.count(1),
                  held=render.count(2)) in result.text


def test_a_figure_whose_set_is_everything_it_measures_places_nothing(registry):
    """The statement fires only where there is a set worth stating. This vault
    holds one account, so its balance is every balance there is, and the answer
    is the sentence the shape declared and nothing else."""
    result = run("balance?",
                 _script(_shape(("Your balance is {total}.",
                                 [("total", "money", "balance")])),
                         BALANCES,
                         bind=lambda r: {"total": {"figure": "f1"}}),
                 registry)
    assert result.answered, result.detail
    assert result.text == "Your balance is USD 600.00."


def test_an_incomplete_total_cannot_be_stated_without_its_gap(several):
    """A total resting on a set that is not everything it claims to measure
    names every account it leaves out — whether or not the sentence around it
    mentioned any of them, and whichever of the two ways an account came to be
    left out.

    This vault holds both: a loan a ruling brought into being and no statement
    has ever measured, and a card held with no statement at all."""
    shape = _shape(("Your net worth is {n}.", [("n", "money", "net_worth")]))
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



def test_a_boundary_is_said_once_however_many_figures_say_it(several):
    """The same discipline a caveat is held to. Two figures over the same set
    are one boundary between them, not two sentences a person reads twice."""
    shape = _shape(("You hold {a} and owe {b}.",
                    [("a", "money", "balance"), ("b", "money", "owed")]))
    result = run("where do I stand?",
                 _script(shape, ("query_ledger", {"entity": "balances"}),
                         bind=lambda r: {
                             "a": {"figure": _figure_id(r, "Everyday Checking")},
                             "b": {"figure": _figure_id(r, "Signature Card")}}),
                 several)
    assert result.answered, result.detail
    said = moment("boundary_accounts", counted=render.count(1),
                  held=render.count(2))
    assert result.text.count(said) == 1


def test_a_figures_boundary_comes_before_what_it_does_not_cover(several):
    """A boundary says what the claim is a claim about; a limit says what that
    claim does not reach. Read the other way round, the limit is about a set
    the person has not been told the shape of yet."""
    shape = _shape(("You spent {total}.", [("total", "money", "spending")]))
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
                    [("n", "money", "net_worth"), ("a", "money", "balance"),
                     ("l", "money", "owed")]))
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
                                 [("n", "money", "net_worth")])),
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "net_worth"}),
                         bind=lambda r: {"n": {"figure": _figure_id(r, "net in")}}),
                 registry)
    assert result.answered, result.detail
    stated = next(f for f in result.figures if f["what"].startswith("net in"))
    assert stated["boundary"] == {"whole": False, "unposted": 1}
    assert moment("boundary_unposted", count=render.count(1)) in result.text
