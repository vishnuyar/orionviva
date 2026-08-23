"""Shape grammar contracts."""

from _shape_test_support import *

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
                                quantity=quantity.SPENDING,
                                scope=frozenset({shape_module.WHOLE})),))
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
        _shape(("You spent {total}.",
               [("total", "money", "spending", "whole")]),
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
        _shape(("You have {x}.", [("x", "money", "balance", "whole")]),
               ("And {x} besides.", [("x", "money", "balance", "whole")]))


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
                    "quantity": "balance", "scope": ["account"]}]}]})
    assert problem == ""
    assert set(shape.slots) == {"which", "total"}
    assert shape.slots["total"].type == render.MONEY
    assert shape.slots["total"].quantity == quantity.BALANCE
    assert shape.slots["total"].scope == frozenset({"account"})
    assert shape.slots["which"].quantity == ""
    assert shape.slots["which"].scope == frozenset()


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
    first = _shape(("You hold {a}.", [("a", "money", "balance", "whole")]),
                   ("It covers {g}.", [("g", "period")]),
                   ("As of {d}.", [("d", "date")]))
    assert weakens(first, first)
    assert weakens(first, _shape(("You hold {a}.",
                                 [("a", "money", "balance", "whole")])))
    assert weakens(first, _shape(("It covers {g}.", [("g", "period")]),
                                 ("As of {d}.", [("d", "date")])))
    # Added, reworded, and re-ordered: none of the three.
    held = ("You hold {a}.", [("a", "money", "balance", "whole")])
    assert not weakens(first, _shape(held, ("And {b} more.",
                                            [("b", "money", "balance",
                                              "whole")])))
    assert not weakens(first, _shape(("You hold plenty of {a}.",
                                      [("a", "money", "balance", "whole")])))
    assert not weakens(first, _shape(("It covers {g}.", [("g", "period")]), held))


def test_a_reshape_that_adds_a_claim_is_refused_and_the_turn_goes_on(registry):
    """And end to end: the widening is refused, the shape in force stands, and
    the model is told why rather than the turn dying."""
    first = _shape(("Your balance is {total}.",
                   [("total", "money", "balance", "account")]))
    wider = _shape(("Your balance is {total}.",
                   [("total", "money", "balance", "account")]),
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
