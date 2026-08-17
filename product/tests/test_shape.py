"""A sentence is a structure before it is a sentence.

The properties here are the ones the answer direction now rests on, and they
are properties of a *structure the machine built* rather than of a sentence
anybody read. Nothing below inspects prose. Between them they say: the words
carry no digits, the shape is fixed before any data exists, a second shape can
only take claims away, every hole is filled by a reference into what the run
established, a hole nothing can fill costs its clause and not the turn, and a
caveat a result wrote about its own number cannot be quietly dropped.
"""

import string
from decimal import Decimal

import pytest
from vivacore.verify.normalize import parse_amount, parse_date

from viva import quantity, render
from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)
from viva.ledger.events import document_captured
from viva.persona import (INTENT_FIELDS, ROWS_STOOD_BEHIND_MOMENT,
                          STOOD_BEHIND_MOMENT, moment)
from viva.tools import default_registry, run
from viva.tools import shape as shape_module
from viva.tools.shape import (CHOOSE_THE_QUANTITY, DROP_THE_QUANTITY,
                              FEWER_CLAUSES, HOLE_THE_CLAUSE, HOLE_THE_NUMBER,
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

# A turn that answers having read nothing. Every clause rests on something the
# run established, and a run that made no read has established one thing only:
# the value the person put into their own question.
_ASKED = "was it 40?"
_ASKED_SHAPE = (("You asked about {yours}.",
                 [("yours", "supposed", "spending")]),)
_ASKED_BINDING = {"yours": {"supposed": "40"}}


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
    with pytest.raises(BadShape) as raised:
        Clause(text=text)
    assert raised.value.problem.repair == HOLE_THE_NUMBER, (
        "a clause writing a digit is told to hole the number, whatever else "
        "is also wrong with it")


def test_a_clause_with_no_digits_is_fine_however_it_is_worded():
    """And the other half: prose is not being policed. Any words at all are
    acceptable around a hole, so long as every magnitude among them is that
    hole."""
    clause = Clause(text="You spent a great deal more than usual, frankly: "
                         "{total}.",
                    slots=(Slot(name="total", type=render.MONEY,
                                quantity=quantity.SPENDING),))
    assert clause.written({"total": "USD 40.00"}) == (
        "You spent a great deal more than usual, frankly: USD 40.00.")


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


def test_a_clause_with_no_hole_does_not_come_into_being():
    """Words alone are not a clause. A clause with no hole rests on nothing the
    run established, which is also why it can never be dropped: no binding can
    go missing from it, so it is spoken whatever the reads found."""
    with pytest.raises(BadShape) as raised:
        Clause(text="All settled.")
    assert raised.value.problem.repair == HOLE_THE_CLAUSE
    with pytest.raises(BadShape):
        Clause(text="All settled.", slots=())


def test_the_reader_inherits_the_rule_rather_than_repeating_it():
    """One check, not two. What the reader says about a clause a model sent
    with no hole is the constructor's own problem, word for word, so there is
    no second statement of the rule that could come to disagree with it."""
    raised = None
    try:
        Clause(text="All settled.")
    except BadShape as bad:
        raised = bad.problem
    shape, problem = read_shape({"clauses": [{"text": "All settled.",
                                              "slots": []}]})
    assert shape is None
    assert str(problem) == str(raised)
    assert problem.repair == raised.repair == HOLE_THE_CLAUSE


def test_a_denial_written_beside_a_figure_cannot_be_authored():
    """The shape this rule is bought for: one clause carrying a figure, and one
    clause saying in the model's own words that the figure could not be
    established. The second rests on nothing, so nothing could ever drop it,
    and it is spoken beside the very number it denies. It does not come into
    being — the machine's own gap sentence is what says this, and it is placed
    only where a hole went unfilled."""
    with pytest.raises(BadShape) as raised:
        _shape(("You spent {total}.", [("total", "money", "spending")]),
               ("I could not establish that figure from the records "
                "available to me here.", []))
    assert raised.value.problem.repair == HOLE_THE_CLAUSE


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
    with pytest.raises(BadShape) as raised:
        _shape(*[(f"A clause about {{{name}}}.", [(name, "account")])
                 for name in string.ascii_lowercase[:MAX_CLAUSES + 1]])
    assert raised.value.problem.repair == FEWER_CLAUSES, (
        "a shape past the ceiling is told to say it in fewer clauses, and the "
        "clauses it is counting are ordinary ones")


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
            return {"shape": _shape(*_ASKED_SHAPE)}
        return {"bindings": _ASKED_BINDING}

    assert run(_ASKED, planner, registry).answered
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

    fine = _shape(("Fine, as of {when}.", [("when", "date")]))
    empty = _Ground()
    assert _committable(None, fine, empty) == ""

    holding = _Ground()
    holding.book["f1"] = {"id": "f1"}
    assert _committable(None, fine, holding)


def test_a_second_shape_may_only_take_claims_away():
    """Re-shaping, monotone. Results can contradict what a shape assumed, and a
    clause may then be dropped — but a clause written after its data is exactly
    what the order exists to prevent, so nothing may be added or reworded."""
    first = _shape(("You hold {a}.", [("a", "money", "balance")]),
                   ("It covers {g}.", [("g", "period")]),
                   ("As of {d}.", [("d", "date")]))
    assert weakens(first, first)
    assert weakens(first, _shape(("You hold {a}.", [("a", "money", "balance")])))
    assert weakens(first, _shape(("It covers {g}.", [("g", "period")]),
                                 ("As of {d}.", [("d", "date")])))
    # Added, reworded, and re-ordered: none of the three.
    held = ("You hold {a}.", [("a", "money", "balance")])
    assert not weakens(first, _shape(held, ("And {b} more.",
                                            [("b", "money", "balance")])))
    assert not weakens(first, _shape(("You hold plenty of {a}.",
                                      [("a", "money", "balance")])))
    assert not weakens(first, _shape(("It covers {g}.", [("g", "period")]), held))


def test_a_reshape_that_adds_a_claim_is_refused_and_the_turn_goes_on(registry):
    """And end to end: the widening is refused, the shape in force stands, and
    the model is told why rather than the turn dying."""
    first = _shape(("Your balance is {total}.", [("total", "money", "balance")]))
    wider = _shape(("Your balance is {total}.", [("total", "money", "balance")]),
                   ("That is unusually high, as of {when}.",
                    [("when", "date")]))
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
    assert result.text == ("Your balance is USD 600.00. That counts only what "
                           "is on Everyday Checking. "
                           + moment(STOOD_BEHIND_MOMENT + result.grade))
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

    result = run(_ASKED,
                 _script(_shape(*_ASKED_SHAPE),
                         bind=lambda r: _ASKED_BINDING), registry)
    assert result.answered, result.detail
    (taken,) = [r for r in result.transcript if r["tool"] == "commit_shape"]
    assert taken["text"] == promptstore.load(PROMPTS, COMMITTED_VERSION)
    assert COMMITTED_VERSION == versions.active(PACKAGE, "shape_committed")


# ------------------------------------------------------------- the checks


def test_a_binding_naming_no_hole_is_refused(registry):
    """Totality, one way: a binding that names nothing in the shape is the
    model asserting something the sentence never had room for."""
    result = run("balance?",
                 _script(_shape(("All settled, as of {when}.",
                                 [("when", "date")])), BALANCES,
                         bind=lambda r: {"total": {"figure": "f1"}}),
                 registry)
    assert not result.answered and result.refusal == "unshaped_binding"


def test_a_turn_that_established_nothing_can_say_so_whatever_the_shape(registry):
    """One leg of a conjunction, and the only leg this test pins: once every
    clause has been dropped, `spoken` is empty and the turn refuses with
    `nothing_established` instead of speaking.

    That leg holds on its own and does not depend on every clause carrying a
    hole, so this test does not discriminate — it is here so the refusal at
    the end of the path stays reachable. The other two legs are pinned
    elsewhere. Every clause carries a hole is the discriminating one, and it is
    pinned where a clause comes into being. An unfilled hole costs its
    clause is pre-existing, and it is pinned where the gate drops one.
    Only all three together make a turn that established nothing able to say
    so whatever shape the model authored."""
    shape = _shape(("All settled, as of {when}.", [("when", "date")]),
                   ("Nothing to report on {which}.", [("which", "account")]))
    result = run("?", _script(shape, bind=lambda results: {}), registry)
    assert not result.answered
    assert result.refusal == "nothing_established", result.detail


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


def test_the_form_admits_no_clause_without_a_hole():
    """The form a model is shown asks each clause for at least one hole, and
    the reader refuses one that arrives without any. The form is not the guard:
    nothing at a provider holds a model to it, so both are here."""
    from viva.speak import SHAPE_PARAMS

    clause = SHAPE_PARAMS["properties"]["clauses"]["items"]
    assert clause["properties"]["slots"]["minItems"] == 1
    assert "slots" in clause["required"]
    assert read_shape({"clauses": [{"text": "All settled.",
                                    "slots": []}]})[0] is None


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
                {"clauses": [{"text": "a clause.", "slots": []}]},
                {"clauses": [{"text": "a clause about {x}.",
                              "slots": [{"name": "x", "type": "grade"}]}]
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
    holds one account and the read was asked for all of them, so its balance is
    every balance there is, and the answer is the sentence the shape declared
    and nothing else."""
    result = run("balance?",
                 _script(_shape(("Your balance is {total}.",
                                 [("total", "money", "balance")])),
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
                                 [("total", "money", "balance")])),
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
                                 [("total", "money", "balance")])),
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
                                 [("many", "count", "count")])),
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
                                 [("total", "money", "balance")])),
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
    shape = _shape(("You spent {slice_}.", [("slice_", "money", "spending")]))
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


# ------------------------------------------------- more than one of a thing


def _wide(groups: int):
    """A vault whose spending falls into `groups` sub categories, each worth a
    different amount, so a breakdown of it is a list of known length."""
    from viva.ledger.events import merchant_enriched
    p = Provenance("doc-jan", 1, "r")
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "10000.00", "2026-01-01", p)]
    for n in range(groups):
        who = f"COUNTERPARTY {n:02d}"
        evs.append(simple_transaction("chk", f"-{10 + n}.00", who,
                                      f"2026-01-{5 + n:02d}", provenance=p))
        evs.append(merchant_enriched(who.lower(), "everything",
                                     subcategory=f"slice {n:02d}",
                                     occurred_at="2026-02-02"))
    evs.append(closing_balance_observed(
        "chk", "9000.00", "2026-01-31", Provenance("doc-jan", 6, "r")))
    return default_registry(LedgerProjection(evs))


BY_SUBCATEGORY = ("query_ledger", {"entity": "aggregate", "metric": "spending",
                                   "group_by": "subcategory"})

# One clause whose words introduce the list and whose hole holds it, which is
# the whole of what a shape says about a breakdown however long the breakdown
# turns out to be. The two are one clause, so a list nothing can fill takes its
# own introduction away with it.
_LIST = (("Here is what you spent, by sub category:{breakdown}",
          [("breakdown", render.ROWS)]),)


def _rows_of(text: str) -> list:
    """The lines of the block in an answer: everything between the clause that
    introduced it and the sentences that follow."""
    return [line for line in text.splitlines()
            if line.startswith("everything / slice ")]


def _bind_the_read(results):
    return {"breakdown": {"read": results[-1]["id"]}}


def test_a_shape_that_names_no_row_count_answers_whatever_the_count_turns_out_to_be():
    """The wall this exists to remove, stated as the property that removes it.

    A shape is authored before anything is read, so how many sub categories
    this person has is not knowable when the sentence is written. One shape,
    unchanged, is run against two vaults whose breakdowns are different lengths
    and answers both — because the model never authored a row and never had to
    know."""
    shape = _shape(*_LIST)
    for count in (3, 9):
        result = run("list my expenditures by sub category",
                     _script(shape, BY_SUBCATEGORY, bind=_bind_the_read),
                     _wide(count))
        assert result.answered, (count, result.detail)
        assert len(_rows_of(result.text)) == count, result.text
    # And the same shape said nothing about how many there would be: its words
    # are the words, and every line came from the machine.
    assert shape.to_dict() == _shape(*_LIST).to_dict()


def test_the_block_begins_on_its_own_line_under_the_words_that_introduce_it():
    """The introducing words and the hole holding the list are one clause, so
    the block is written where the hole is — at the end of those words. It
    opens on a line of its own, so a person reads the introduction and then the
    lines under it, rather than the first line beside the colon."""
    result = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY, bind=_bind_the_read),
                 _wide(4))
    assert result.answered, result.detail
    lines = result.text.splitlines()
    assert lines[0] == "Here is what you spent, by sub category:"
    assert len(_rows_of(result.text)) == 4


# The same answer in two clauses rather than one: an introducer carrying a
# hole of its own, and a clause that is nothing but the list.
_SPLIT_LIST = (("Here is what you spent, by sub category, against the {yours} "
                "you named:", [("yours", "supposed", "spending")]),
               ("{breakdown}", [("breakdown", render.ROWS)]))


def test_a_split_introducer_leaves_a_blank_line_above_the_block():
    """What the split form renders, pinned rather than fixed.

    `speak-shape-v8` teaches the merged form, where the introducing words and
    the hole holding the list are one clause. The split form is still legal —
    the introducer carries a hole of its own, so it is a clause, and a clause
    may be nothing but a hole. What it renders is this: the break the block
    opens with travels with the block itself, and the runner already puts a
    break between two clauses, so the two meet and the list sits under a blank
    line.

    That blank line is the accepted cost of writing the break where the block
    is written rather than where clauses are joined. It is recorded here so it
    is not rediscovered as a surprise."""
    result = run("was it 40, by sub category?",
                 _script(_shape(*_SPLIT_LIST), BY_SUBCATEGORY,
                         bind=lambda r: {"yours": {"supposed": "40"},
                                         "breakdown": {"read": r[-1]["id"]}}),
                 _wide(3))
    assert result.answered, result.detail
    lines = result.text.splitlines()
    assert lines[0].endswith("you named:")
    assert lines[1] == ""
    assert len(_rows_of(result.text)) == 3


def test_a_list_of_one_is_still_a_list():
    """A breakdown whose grouping yields one group is the case where that group
    IS all of the spending — and it is still a list, with one named row.

    The two facts are separate and both survive: the figure says which group it
    is, so the block has a name to write, and the figure is the whole, so no
    scope sentence is placed under it."""
    result = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY, bind=_bind_the_read),
                 _wide(1))
    assert result.answered, result.detail
    assert len(_rows_of(result.text)) == 1
    stated = result.figures[0]
    assert stated["boundary"]["whole"] is True
    # Whole, so nothing is said about where its claim ends — the row's name is
    # not a scope clause and the answer carries neither.
    from viva.tools.runner import SELECTED_TERMS
    from viva.tools.envelope import BY_SUBCATEGORY as CUT

    key, slot, _writes = SELECTED_TERMS[CUT]
    assert moment(key, **{slot: render.label(
        stated["boundary"]["cut"]["value"])}) not in result.text


def test_a_person_sees_every_row_the_read_named():
    """No second cap. The read names the largest ten groups and says in its own
    words what it folded away; the block shows all ten of them rather than
    trimming the read's own answer a second time."""
    from viva.tools.ledger_tools import MAX_GROUPS

    result = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY, bind=_bind_the_read),
                 _wide(MAX_GROUPS + 4))
    assert result.answered, result.detail
    assert len(_rows_of(result.text)) == MAX_GROUPS


def test_the_reads_own_tail_sentence_lands_under_the_rows():
    """A capped list already says it was capped, in the read's own words, and
    the run already places what a stated figure owes. So the sentence a person
    needs under ten rows is one nothing here had to write — it only has to land
    under them rather than beside the last one."""
    from viva.tools.ledger_tools import MAX_GROUPS

    result = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY, bind=_bind_the_read),
                 _wide(MAX_GROUPS + 4))
    assert result.answered, result.detail
    lines = result.text.splitlines()
    tail = next(i for i, line in enumerate(lines)
                if "smaller group(s) worth" in line)
    assert tail == len(lines) - 1, result.text
    assert all(line.startswith("everything / slice ")
               for line in lines[-1 - MAX_GROUPS:-1])


def test_the_set_is_graded_once_above_the_block_and_never_per_row():
    """One grade is computed over a whole read and stamped on every figure it
    emits, so a word beside each row would read as a claim about that row when
    it is a claim about the read. It is stated once, above, in the reviewed
    sentence that says that word of a list.

    Once, and not twice: where every money figure the answer stated is a line
    of this block, the block has said the whole of it and nothing repeats it
    underneath."""
    from viva.tools.envelope import STRENGTH

    result = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY, bind=_bind_the_read),
                 _wide(4))
    assert result.answered, result.detail
    said = moment(ROWS_STOOD_BEHIND_MOMENT + result.grade)
    assert result.text.count(said) == 1
    assert result.text.index(said) < min(result.text.index(row)
                                         for row in _rows_of(result.text))
    for row in _rows_of(result.text):
        assert result.grade not in row, row
    assert all(moment(STOOD_BEHIND_MOMENT + grade) not in result.text
               for grade in STRENGTH), result.text


def _mixed_strength():
    """A vault where a breakdown of the spending and the balance it sits under
    are stood behind differently: the movements are recorded with nothing
    checking them, while the closing balance a statement printed agrees with
    what they add up to."""
    from viva.ledger.events import merchant_enriched
    p = Provenance("doc-jan", 1, "r")
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "10000.00", "2026-01-01", p)]
    spent = 0
    for n in range(3):
        who = f"COUNTERPARTY {n:02d}"
        spent += 10 + n
        evs.append(simple_transaction("chk", f"-{10 + n}.00", who,
                                      f"2026-01-{5 + n:02d}", provenance=p,
                                      account_grade="unverified"))
        evs.append(merchant_enriched(who.lower(), "everything",
                                     subcategory=f"slice {n:02d}",
                                     occurred_at="2026-02-02"))
    evs.append(closing_balance_observed(
        "chk", f"{10000 - spent}.00", "2026-01-31",
        Provenance("doc-jan", 6, "r")))
    return default_registry(LedgerProjection(evs))


_BLOCK_AND_A_NUMBER = (("Here is what you spent, by sub category:{breakdown}",
                        [("breakdown", render.ROWS)]),
                       ("Your balance is {total}.",
                        [("total", "money", "balance")]))


def _bind_the_read_and_the_balance(results):
    reads = [r for r in results if r["tool"] != "commit_shape"]
    return {"breakdown": {"read": reads[0]["id"]},
            "total": {"figure": _figure_id(reads[1:], "— balance")}}


def test_an_answer_stating_a_number_beside_a_block_grades_both_together():
    """A block says how well its own read is stood behind; the answer says how
    well everything it stated is, the block's lines counted in. So the set the
    trailing sentence speaks for contains the set the line above the block
    speaks for, and a person reading down the answer reads one set inside
    another rather than two they must tell apart."""
    from viva.tools.envelope import STRENGTH

    result = run("what did I spend, by sub category, and what is my balance?",
                 _script(_shape(*_BLOCK_AND_A_NUMBER), BY_SUBCATEGORY, BALANCES,
                         bind=_bind_the_read_and_the_balance),
                 _mixed_strength())
    assert result.answered, result.detail
    rows = _rows_of(result.text)
    assert rows
    of_the_block = {f["grade"] for f in result.figures
                    if any(f["what"].endswith(row.split(" — ")[0] + "'")
                           for row in rows)}
    assert len(of_the_block) == 1
    block = moment(ROWS_STOOD_BEHIND_MOMENT + of_the_block.pop())
    answer = moment(STOOD_BEHIND_MOMENT + result.grade)
    assert result.text.count(block) == 1 and result.text.count(answer) == 1
    assert result.text.index(block) < result.text.index(answer), result.text
    # The balance is stood behind better than the movements are, and it is the
    # weaker of the two that the answer as a whole is spoken as.
    stated = {f["what"]: f["grade"] for f in result.figures}
    assert len(set(stated.values())) > 1, stated
    assert result.grade == max(stated.values(), key=STRENGTH.index)


def test_an_answer_is_never_stood_behind_more_strongly_than_a_block_it_carries():
    """Every figure a block wrote a line for is among the figures the answer's
    own word is computed over, and that word is the weakest of them. The
    weakest of a set that contains another set can never be stronger than the
    weakest of what it contains — so the sentence beneath a block cannot claim
    more than the line above it, whatever the two reads turned out to hold."""
    from viva.tools.envelope import MONEY_KINDS, STRENGTH, weakest

    result = run("what did I spend, by sub category, and what is my balance?",
                 _script(_shape(*_BLOCK_AND_A_NUMBER), BY_SUBCATEGORY, BALANCES,
                         bind=_bind_the_read_and_the_balance),
                 _mixed_strength())
    assert result.answered, result.detail
    rows = _rows_of(result.text)
    of_the_block = [f for f in result.figures
                    if any(f["what"].endswith(row.split(" — ")[0] + "'")
                           for row in rows)]
    assert len(of_the_block) == len(rows)
    # Every line the block wrote is a figure the answer's word was computed
    # over: the answer states the weakest of what it cites, and it cites these.
    assert result.grade == weakest(f["grade"] for f in result.figures
                                   if f["kind"] in MONEY_KINDS)
    assert STRENGTH.index(result.grade) >= max(
        STRENGTH.index(f["grade"]) for f in of_the_block), result.text
    # The lemma the assertions above rest on, over every pair of words the two
    # sets could carry: the ladder runs strongest first, so a larger place on
    # it is a weaker claim. It is a property of `weakest` and says nothing on
    # its own about what the runner computes the answer's word over; the
    # assertions above are what carry that half.
    for block in STRENGTH:
        for other in STRENGTH:
            assert (STRENGTH.index(weakest([block, other]))
                    >= STRENGTH.index(block)), (block, other)


def test_a_row_names_its_own_slice_and_no_scope_clause_repeats_it():
    """Every row is a figure taken over one slice of the read, and the slice is
    written beside the number as the row's own name. A boundary sentence saying
    the same thing again would be the same claim made twice — ten times over,
    under a block of ten."""
    from viva.tools.runner import SELECTED_TERMS
    from viva.tools.envelope import BY_SUBCATEGORY as CUT

    result = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY, bind=_bind_the_read),
                 _wide(4))
    assert result.answered, result.detail
    key, slot, _writes = SELECTED_TERMS[CUT]
    for figure in result.figures:
        cut = figure["boundary"]["cut"]
        assert cut["kind"] == CUT
        # Named in the block, once, as the line it is.
        assert result.text.count(f"{cut['value']} — ") == 1
        # And not a second time as a sentence about where that claim ends.
        assert moment(key, **{slot: render.label(cut["value"])}) \
            not in result.text


def test_the_slice_a_figure_covers_is_still_said_where_the_figure_is_a_number():
    """The other half of the same rule, so it is not read as "a cut is never
    said". A group figure stated as a number in a sentence of its own has said
    nothing about which slice it is, and the run places it."""
    from viva.tools.runner import SELECTED_TERMS
    from viva.tools.envelope import BY_SUBCATEGORY as CUT

    shape = _shape(("You spent {slice_}.", [("slice_", "money", "spending")]))
    registry = _wide(4)
    result = run("what did I spend on that?",
                 _script(shape, BY_SUBCATEGORY,
                         bind=lambda r: {"slice_": {"figure": _figure_id(
                             r, "subcategory 'everything / slice 00'")}}),
                 registry)
    assert result.answered, result.detail
    key, slot, _writes = SELECTED_TERMS[CUT]
    assert moment(key, **{slot: render.label("everything / slice 00")}) \
        in result.text


def test_every_row_shown_is_cited_and_answers_for_its_records():
    """A block states its rows, so the rows are answerable exactly as a number
    named in a sentence is: they are the answer's cited figures, they set its
    grade, and a money figure standing on no record refuses the turn rather
    than appearing as a line."""
    registry = _wide(4)
    result = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY, bind=_bind_the_read),
                 registry)
    assert result.answered, result.detail
    assert len(result.figures) == 4
    for figure in result.figures:
        assert figure["record_ids"], figure["what"]
    # The read's own total and count were not written as lines, so they are not
    # things this answer stated.
    assert not [f for f in result.figures if "total spending" in f["what"]]


def test_a_read_that_named_no_slice_has_no_rows_in_it():
    """A block is one line per figure taken over a named slice. A read that
    took none has nothing to write a line per, and binding it is a delivery
    naming the wrong sort of read rather than a hole nothing could fill."""
    result = run("list my accounts",
                 _script(_shape(*_LIST), BALANCES, bind=_bind_the_read),
                 _wide(4))
    assert not result.answered
    assert result.refusal == "wrong_kind", result.detail


def test_a_read_that_cuts_two_ways_at_once_has_no_list_in_it():
    """A block is one line per slice a read named, so a read naming slices of
    two kinds at once — a figure per account and a figure per month over the
    same movements — fills no block: a line per slice would state the same
    money once for each way the read cuts. The refusal is on the declared
    kinds, not on which read or tool produced them."""
    result = run("list what moved",
                 _script(_shape(*_LIST),
                         ("query_ledger", {"entity": "transactions"}),
                         bind=_bind_the_read),
                 _wide(4))
    assert not result.answered
    assert result.refusal == "wrong_kind", result.detail


def test_a_read_this_turn_never_made_cannot_be_shown():
    result = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY,
                         bind=lambda r: {"breakdown": {"read": "r9"}}),
                 _wide(4))
    assert not result.answered
    assert result.refusal == "unknown_reading", result.detail


def test_a_block_holds_a_whole_read_and_nothing_else_does():
    """The type check in both directions: a read fills a rows hole and no
    other, and a rows hole is filled by a read and by nothing else."""
    for hole, reference in ((("x", render.ROWS), {"figure": "f1"}),
                            (("x", render.ROWS), {"entity": "a1"}),
                            (("x", render.MONEY, "spending"), {"read": "r1"}),
                            (("x", render.COUNT, "count"), {"read": "r1"}),
                            (("x", render.CATEGORY), {"read": "r1"})):
        result = run("?", _script(_shape(("It is {x}.", [hole])),
                                  BY_SUBCATEGORY,
                                  bind=lambda r, b=reference: {"x": b}),
                     _wide(4))
        assert not result.answered, (hole, reference)
        assert result.refusal == "wrong_kind", (hole, reference, result.detail)


def test_a_block_is_named_by_the_read_rather_than_by_its_rows():
    """A rows hole admits one kind of reference, so a delivery naming the read
    without naming it AS a read has still said which read it means — the same
    economy a date hole already allows. What it can never be is a list of
    figures: every hole holds one thing."""
    result = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY,
                         bind=lambda r: {"breakdown": r[-1]["id"]}),
                 _wide(4))
    assert result.answered, result.detail
    assert list(result.bindings["breakdown"]) == ["read"]

    plural = run("what did I spend, by sub category?",
                 _script(_shape(*_LIST), BY_SUBCATEGORY,
                         bind=lambda r: {"breakdown": ["f1", "f2"]}),
                 _wide(4))
    assert not plural.answered and plural.refusal == "bad_binding"


def test_a_block_nothing_can_fill_costs_its_clause_and_not_the_turn():
    """A list degrades the way every other hole does."""
    shape = _shape(("You spent {total}.", [("total", "money", "spending")]),
                   *_LIST)
    result = run("what did I spend, by sub category?",
                 _script(shape, BY_SUBCATEGORY,
                         bind=lambda r: {"total": {"figure": _figure_id(
                             r, "total spending")}}),
                 _wide(4))
    assert result.answered, result.detail
    assert result.text.startswith("You spent ")
    assert not _rows_of(result.text)
    assert moment("answer_gap", what=moment("gap_rows")) in result.text


def test_what_a_number_means_decides_what_shape_it_takes():
    """A row has no hole above it saying whether to write an amount, a count or
    a proportion, so the figure's own declaration decides — and that is only
    safe while one quantity belongs to one shape. Read off the same pairing
    table the shape check reads, so the two cannot describe different rules."""
    seen: dict = {}
    for kind, measures in render.MAGNITUDE_OF_TYPE.items():
        for measure in measures:
            assert measure not in seen, (
                f"{measure!r} is a quantity both a {kind} hole and a "
                f"{seen.get(measure)} hole may ask for, so nothing can say "
                "what shape a figure declaring it takes")
            seen[measure] = kind
    assert seen == render.TYPE_OF_QUANTITY
    from viva.tools.runner import _MAGNITUDE_WRITERS

    assert set(_MAGNITUDE_WRITERS) == set(render.MAGNITUDE_OF_TYPE)


def test_the_delivery_instructions_teach_every_kind_of_reference():
    """A way of referring to something that the code takes and the instructions
    never mention is one a model will never use; one the instructions offer and
    the code refuses is a delivery that always fails."""
    from vivacore import promptstore

    from viva.speak import FINAL_VERSION
    from viva.tools.registry import PROMPTS
    from viva.tools.runner import BINDING_KEYS

    taught = promptstore.load(PROMPTS, FINAL_VERSION)
    for key in BINDING_KEYS:
        assert f'"{key}"' in taught, (
            f"the delivery instructions never mention {key}")
