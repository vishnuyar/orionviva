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
from viva.tools.shape import (MAX_CLAUSES, SLOT_TYPES, BadShape, Clause, Shape,
                              Slot, read_shape, weakens)


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
                   ("Bear in mind: {c}", [("c", "caveat")]))
    assert weakens(first, first)
    assert weakens(first, _shape(("You hold {a}.", [("a", "money", "balance")])))
    assert weakens(first, _shape(("It is {g}.", [("g", "grade")]),
                                 ("Bear in mind: {c}", [("c", "caveat")])))
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
                            ((render.CAVEAT,), {"date": "2026-01-31"}),
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
    """A caveat is the tool saying what its own figure does not cover. An
    answer that states the figure and not the caveat is a stronger claim than
    the read made, so it refuses.

    One caveat hole holds however many turn up, because the shape is authored
    before anyone knows how many there will be."""
    spending = ("query_ledger", {"entity": "aggregate", "metric": "spending"})
    silent = _shape(("You spent {total}.", [("total", "money", "spending")]))
    result = run("what did I spend?",
                 _script(silent, spending,
                         bind=lambda r: {"total": {"figure": _spending(r)}}),
                 registry)
    assert not result.answered and result.refusal == "caveat_unplaced"

    honest = _shape(("You spent {total}.", [("total", "money", "spending")]),
                    ("Bear in mind: {limits}", [("limits", "caveat")]))
    spoken = run("what did I spend?",
                 _script(honest, spending,
                         bind=lambda r: {
                             "total": {"figure": _spending(r)},
                             "limits": {"caveat": [c["id"] for c
                                                   in r[-1]["caveats"]]}}),
                 registry)
    assert spoken.answered, spoken.detail
    assert "Own-account transfers" in spoken.text


def _spending(results):
    return next(f["id"] for f in results[-1]["figures"]
                if "total spending" in f["what"])


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
    shape = _shape(("You spent {total}.", [("total", "money", "spending")]),
                   ("Bear in mind: {limits}", [("limits", "caveat")]))
    result = run(
        "how much did I spend?",
        _script(shape, summary,
                bind=lambda r: {
                    "total": {"figure": _named(r, "money out over")},
                    "limits": {"caveat": [c["id"] for c in r[-1]["caveats"]]}}),
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
                    [("share", "rate", "ratio")]),
                   ("Bear in mind: {limits}", [("limits", "caveat")]))
    result = run(
        "how much of my spending is that?",
        _script(shape, ("check_completeness", {}),
                bind=lambda r: {
                    "share": {"figure": _named(r, "documents held")},
                    "limits": {"caveat": [c["id"] for c in r[-1]["caveats"]]}}),
        registry)
    assert not result.answered, result.text
    assert result.refusal == "wrong_quantity"


def test_the_figure_the_hole_asked_about_is_spoken(registry):
    """And the other side of it, so the check is not merely refusing
    everything: the figure that measures what the sentence is about goes
    through, and is written as the amount it is."""
    spending = ("query_ledger", {"entity": "aggregate", "metric": "spending"})
    shape = _shape(("You spent {total}.", [("total", "money", "spending")]),
                   ("Bear in mind: {limits}", [("limits", "caveat")]))
    result = run(
        "how much did I spend?",
        _script(shape, spending,
                bind=lambda r: {
                    "total": {"figure": _spending(r)},
                    "limits": {"caveat": [c["id"] for c in r[-1]["caveats"]]}}),
        registry)
    assert result.answered, result.detail
    assert result.text.startswith("You spent USD 400.00.")


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
    written = render.rate("12.5", locale=locale)
    read = parse_amount(written.replace("%", " ").strip(), locale=locale)
    assert read.ok and read.decimal() == Decimal("12.5")


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
