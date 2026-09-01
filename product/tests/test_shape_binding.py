"""Shape binding contracts."""

from _shape_test_support import *

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
    shape = _shape(("Your balance is {total}.",
                   [("total", "money", "balance", "account")]),
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


def test_a_bad_reference_costs_its_clause_and_not_a_grounded_clause(registry):
    """An invalid binding drops only the clause that contains it."""
    shape = _shape(("Your balance is {total}.",
                    [("total", "money", "balance", "account")]),
                   ("There were {count} movements.",
                    [("count", "count", "count", "whole")]))
    result = run(
        "balance and movement count?",
        _script(shape, BALANCES,
                bind=lambda r: {"total": {"figure": "f1"},
                                "count": {"figure": "f1"}}),
        registry)

    assert result.answered, result.detail
    assert result.text.startswith("Your balance is USD 600.00.")
    assert "There were" not in result.text
    assert result.gaps == [{"name": "count", "type": "count"}]


def test_a_date_can_travel_with_the_figure_stated_beside_it(registry):
    """The answer refers to a dated figure instead of copying its ISO day."""
    shape = _shape(("As of {when}, your balance was {total}.",
                    [("when", "date"),
                     ("total", "money", "balance", "account")]))
    result = run(
        "balance and date?",
        _script(shape, BALANCES,
                bind=lambda r: {"when": {"date_of": "f1"},
                                "total": {"figure": "f1"}}),
        registry)

    assert result.answered, result.detail
    assert result.text.startswith("As of 2026-01-31, your balance was ")
    assert result.bindings["when"] == {"date_of": "f1"}


def test_a_figure_date_cannot_float_free_of_its_figure(registry):
    shape = _shape(("That evidence is dated {when}.", [("when", "date")]))
    result = run(
        "date?",
        _script(shape, BALANCES,
                bind=lambda r: {"when": {"date_of": "f1"}}),
        registry)

    assert not result.answered
    assert result.refusal == "unfounded_date"


def test_an_answer_whose_every_clause_falls_away_says_so(registry):
    result = run("balance?",
                 _script(_shape(("Your balance is {total}.",
                                 [("total", "money", "balance",
                                   "whole")])), BALANCES),
                 registry)
    assert not result.answered and result.refusal == "nothing_established"


def test_a_thing_of_the_wrong_kind_cannot_fill_a_hole(registry):
    """Type, over every pairing the run can produce. An amount states a
    currency and a plain number states none, which is the distinction the
    emitters already make, so this is a check over a field the code computes
    rather than over anything anybody wrote."""
    for hole, reference in (((render.MONEY, "balance", "account"),
                             {"figure": "f2"}),
                            ((render.COUNT, "count", "whole"),
                             {"figure": "f1"}),
                            ((render.DATE,), {"figure": "f1"}),
                            ((render.ACCOUNT,), {"figure": "f1"}),
                            ((render.MONEY, "balance", "account"),
                             {"entity": "a1"}),
                            ((render.MERCHANT,), {"entity": "a1"}),
                            ((render.PERIOD,), {"date": "2026-01-31"}),
                            ((render.SUPPOSED, "balance"),
                             {"figure": "f1"})):
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
    silent = _shape(("You spent {total}.",
                    [("total", "money", "spending", "whole")]))
    result = run("what did I spend?",
                 _script(silent, spending,
                         bind=lambda r: {"total": {"figure": _spending(r)}}),
                 registry)
    assert result.answered, result.detail
    assert result.text.startswith("You spent USD 400.00.")
    assert "money that left your life" in result.text, (
        "the shape says nothing about limits, and the run places them anyway")
    # Once, however many results wrote it, and introduced in Viva's own words.
    assert result.text.count("money that left your life") == 1
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
    shape = _shape(("As of {when}, it stood at {total}.",
                    [("when", "date"),
                     ("total", "money", "balance", "account")]))
    result = run("when?",
                 _script(shape, BALANCES,
                         # The day, bare: a value where the named form was wanted.
                         bind=lambda r: {"when": "2026-01-31",
                                         "total": {"figure": "f1"}}),
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
                    [("total", "money", "balance", "account")]))
    result = run("balance?",
                 _script(shape, BALANCES, bind=lambda r: {"total": "f1"}),
                 registry)
    assert not result.answered and result.refusal == "bad_binding"


def test_a_caveat_behind_a_figure_no_clause_states_is_not_owed(registry):
    """What survives is what asserts, so what survives is what answers for its
    caveats. A clause that fell away states nothing and owes nothing."""
    shape = _shape(("Your balance is {held}.",
                   [("held", "money", "balance", "account")]),
                   ("You spent {spent} on {when}.",
                    [("spent", "money", "spending", "whole"),
                     ("when", "date")]))
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
    shape = _shape(("You spent {total}.",
                   [("total", "money", "spending", "whole")]))
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
                    [("share", "rate", "ratio", "whole")]))
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
    shape = _shape(("You spent {total}.",
                   [("total", "money", "spending", "whole")]))
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
        [("debt", "money", "owed", "account"), ("which", "account")])
HOLDS = ("Your {holding} balance is {amount}.",
         [("holding", "account"), ("amount", "money", "balance", "account")])


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


def test_a_credit_on_a_card_never_fills_a_hole_that_asserts_a_debt():
    """A card paid past its balance owes the person, and its magnitude is
    negative in the owed convention. A hole asking for what is owed is a
    sentence saying a debt is there, so that figure does not fill it: the turn
    refuses rather than writing a sign in front of a number the words around it
    deny.

    The sign convention is untouched: the figure still carries the negative
    the bill prints. What the rule governs is where such a figure may be
    spoken."""
    result = _spoken_about_the_card(_card_events("-50.00", OVERPAID))
    assert not result.answered and result.refusal == "wrong_quantity"
    assert render.money(Decimal("-50.00"), "USD") not in result.text


def test_a_debt_that_is_a_debt_still_fills_the_hole_that_asserts_one():
    """The direction rule is a rule about the value and not about the kind of
    account: the same card, owing money, fills the same hole it always did."""
    result = _spoken_about_the_card(_card_events("1000.00", OWING))
    assert result.answered, result.detail
    assert render.money(Decimal("1000.00"), "USD") in result.text


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
    shape = _shape(("That comes to {total}.",
                   [("total", "count", "count", "whole")]))
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


# ------------------------------------- what set a number is a number over


def test_a_hole_holding_a_magnitude_must_say_what_set_it_is_over():
    """The second declaration, refused every way the first one is.

    A hole that says what it measures and not what set it measured it over is
    one a subset can be put into and read as a total, which is the sentence
    this exists to stop. An empty set is that same silence written out. A set
    outside the vocabulary is refused as the vocabulary's own list; a set on a
    hole holding nothing to measure is a declaration about a number that is not
    there. Each names its own repair, because the change each asks for is
    different."""
    from viva.tools.shape import (CHOOSE_THE_SCOPE, DROP_THE_SCOPE,
                                  NAME_THE_SCOPE, WORD_THE_SCOPE)

    for hole, repair in (
            ({"name": "t", "type": "money", "quantity": "balance"},
             NAME_THE_SCOPE),
            ({"name": "t", "type": "count", "quantity": "count"},
             NAME_THE_SCOPE),
            ({"name": "t", "type": "rate", "quantity": "ratio"},
             NAME_THE_SCOPE),
            ({"name": "t", "type": "money", "quantity": "balance",
              "scope": []}, NAME_THE_SCOPE),
            ({"name": "t", "type": "money", "quantity": "balance",
              "scope": ["instrument"]}, CHOOSE_THE_SCOPE),
            ({"name": "t", "type": "money", "quantity": "balance",
              "scope": ["merchant", "instrument"]}, CHOOSE_THE_SCOPE),
            # The whole of what a quantity ranges over is not an axis a
            # sentence narrows on, so it is never one of several.
            ({"name": "t", "type": "money", "quantity": "balance",
              "scope": ["whole", "merchant"]}, CHOOSE_THE_SCOPE),
            ({"name": "t", "type": "money", "quantity": "balance",
              "scope": 7}, WORD_THE_SCOPE),
            # A scope is a list of axes, so one word standing alone is not one.
            ({"name": "t", "type": "money", "quantity": "balance",
              "scope": "merchant"}, WORD_THE_SCOPE),
            ({"name": "t", "type": "money", "quantity": "balance",
              "scope": [7]}, WORD_THE_SCOPE),
            ({"name": "t", "type": "account", "scope": ["account"]},
             DROP_THE_SCOPE)):
        shape, problem = read_shape(
            {"clauses": [{"text": "It is {t}.", "slots": [hole]}]})
        assert shape is None, hole
        assert problem.repair == repair, (hole, problem)


def test_a_value_the_person_supposed_declares_no_set_it_was_taken_over():
    """A supposition is not a measurement, so it is refused a scope — every
    one of them, including the whole.

    The person may suppose about anything they can name, so the hole says what
    its number is of and that declaration stands. What it cannot say is what
    set the number was taken over, because nobody took it over one: nothing
    reads such a declaration, nothing could, and a recorded shape carrying it
    would mean nothing forever. Refused at the shape, before a read has run,
    and told to take the field out."""
    from viva.tools.shape import DROP_THE_SCOPE

    for over in shape_module.SCOPES:
        shape, problem = read_shape({"clauses": [
            {"text": "The {trip} you named.",
             "slots": [{"name": "trip", "type": render.SUPPOSED,
                        "quantity": "spending", "scope": [over]}]}]})
        assert shape is None, over
        assert problem.repair == DROP_THE_SCOPE, (over, problem)

    # And the hole itself is untouched: what a supposed value is of is still
    # asked for, and still refused when it is not one of that kind's own.
    assert read_shape(_hole(render.SUPPOSED, "spending"))[0] is not None
    assert read_shape(_hole(render.SUPPOSED))[0] is None


def test_the_sets_a_hole_may_declare_are_the_ones_a_figure_can_be_taken_over():
    """One vocabulary, read from where the boundaries declare into rather than
    listed twice. A way of narrowing a set that a hole could not ask about
    would be a scope no sentence could be written for; one a hole could ask for
    and no figure could declare would be a hole nothing can ever fill."""
    from viva.tools.envelope import SELECTED_KINDS

    assert set(shape_module.SCOPES) == set(SELECTED_KINDS) | {"whole"}
    assert len(shape_module.SCOPES) == len(SELECTED_KINDS) + 1


def test_the_form_says_a_magnitude_hole_must_declare_the_set_it_is_over():
    """A field a model may leave out is a check a model can switch off. The
    form requires the scope on every alternative that holds a magnitude and
    offers it on none of the others, and the enum it offers is the vocabulary
    the check reads back.

    It is offered as a set of axes, never one, and each axis at most once: a
    sentence narrows on as many as it names, and one named twice is one claim
    written twice."""
    offered = _offered_holes()
    for kind, form in offered.items():
        carries = bool(render.magnitudes_of(kind))
        field = form["properties"].get("scope") or {}
        told = field.get("items", {}).get("enum")
        assert bool(told) == carries, kind
        assert ("scope" in form["required"]) == carries, kind
        if carries:
            assert field["type"] == "array", kind
            assert field["minItems"] == 1 and field["uniqueItems"], kind
            assert set(told) == set(shape_module.SCOPES), kind
            # And a hole of that kind with no scope is refused, so the form and
            # the check describe one rule rather than two.
            first = shape_module.quantities_of(kind)[0]
            assert read_shape(_hole(kind, first))[0]
            unsaid = {"clauses": [{"text": "It is {it}.", "slots": [
                {"name": "it", "type": kind, "quantity": first}]}]}
            assert read_shape(unsaid)[0] is None


def test_the_shape_prompt_teaches_every_set_a_hole_can_declare():
    """A set the code takes and the instructions never mention is one no model
    will declare; one the instructions offer and the code refuses is a shape
    that will always be sent back."""
    from vivacore import promptstore

    from viva.speak import SHAPE_VERSION
    from viva.tools.registry import PROMPTS

    taught = promptstore.load(PROMPTS, SHAPE_VERSION)
    for over in shape_module.SCOPES:
        assert f"`{over}`" in taught, over


def test_a_total_of_everything_cannot_be_spoken_as_one_counterpartys(registry):
    """A sentence about what was spent at one counterparty, bound to the whole
    ledger's total, is a real number under a description it does not answer —
    and the turn ends rather than saying it.

    Nothing here reads the clause's words. The hole says the sentence is about
    one counterparty; the figure says it was taken over everything; two
    declarations, both written by code, and they disagree."""
    result = run("what did I spend there?",
                 _script(_shape(("You spent {total} there.",
                                 [("total", "money", "spending",
                                   "merchant")])),
                         ("query_ledger", {"entity": "aggregate",
                                           "metric": "spending"}),
                         bind=lambda r: {"total": {"figure": _named(
                             r, "total spending")}}),
                 registry)
    assert not result.answered
    assert result.refusal == "wrong_scope", result.detail
    assert result.text == moment("refusal_wrong_scope")


def test_a_total_of_one_counterparty_cannot_be_spoken_as_everything(registry):
    """The same check the other way round, which is the half a vocabulary of
    kinds alone would miss. A read narrowed to one counterparty returns that
    counterparty's total; a sentence claiming to be about everything spent is
    refused it."""
    result = run("what did I spend in total?",
                 _script(_shape(("You spent {total} in all.",
                                 [("total", "money", "spending", "whole")])),
                         _AT_ONE_COUNTERPARTY,
                         bind=lambda r: {"total": {"figure": _named(
                             r, "total spending")}}),
                 registry)
    assert not result.answered
    assert result.refusal == "wrong_scope", result.detail


def test_what_was_spent_at_one_counterparty_is_still_spoken(registry):
    """And the answer that must survive the check: the most-asked narrowed
    question there is.

    A read narrowed one way returned one slice, and the total over it is the
    whole of that slice — so it says which slice it is, and a sentence about
    one counterparty has a figure that is the whole of what it asks about."""
    result = run("what did I spend there?",
                 _script(_shape(("You spent {total} there.",
                                 [("total", "money", "spending",
                                   "merchant")])),
                         _AT_ONE_COUNTERPARTY,
                         bind=lambda r: {"total": {"figure": _named(
                             r, "total spending")}}),
                 registry)
    assert result.answered, result.detail
    assert result.text.startswith(
        f"You spent {render.money(Decimal('400.00'), 'USD')} there.")


_AT_ONE_COUNTERPARTY_IN_ONE_SPAN = (
    "query_ledger",
    {"entity": "aggregate", "metric": "spending",
     "filters": {"merchant": "greenfield market",
                 "window": {"from": "2026-01-01", "to": "2026-01-31"}}})


def test_what_was_spent_at_one_counterparty_inside_one_span_is_spoken(registry):
    """The most-asked narrowed money question there is, and it narrows on two
    axes rather than one.

    A read filtered to one counterparty and one window returned the overlap of
    the two, and the total over it is the whole of that overlap — so the figure
    says it is both, and a sentence about what was spent there between those
    two days has a figure that is the whole of what it asks about. A rule that
    let a figure name only one axis would refuse this."""
    result = run("what did I spend there between those days?",
                 _script(_shape(("You spent {total} there in that stretch.",
                                 [("total", "money", "spending",
                                   ("merchant", "period"))])),
                         _AT_ONE_COUNTERPARTY_IN_ONE_SPAN,
                         bind=lambda r: {"total": {"figure": _named(
                             r, "total spending")}}),
                 registry)
    assert result.answered, result.detail
    assert result.text.startswith(
        f"You spent {render.money(Decimal('400.00'), 'USD')} there")


def test_a_counterpartys_total_in_one_span_is_not_that_counterpartys_total(
        registry):
    """And the strictness that answer is bought with, on the same figure.

    The figure above is the whole of one counterparty inside one span. A
    sentence about what was spent at that counterparty — with no stretch in it
    — is a claim about every day there has been, and this number is not that.
    It is refused, though the number is real and the counterparty is right."""
    result = run("what did I spend there?",
                 _script(_shape(("You spent {total} there.",
                                 [("total", "money", "spending",
                                   "merchant")])),
                         _AT_ONE_COUNTERPARTY_IN_ONE_SPAN,
                         bind=lambda r: {"total": {"figure": _named(
                             r, "total spending")}}),
                 registry)
    assert not result.answered
    assert result.refusal == "wrong_scope", result.detail
    assert result.text == moment("refusal_wrong_scope")


def test_a_figure_that_states_no_set_fills_no_hole_asking_for_one():
    """Silence and "this is everything" are different sentences. A figure
    carrying no boundary has had nothing said about what set it was taken
    over, so it fills neither a hole asking for the whole nor one asking for a
    slice — a default either way would put a claim on a figure nobody made one
    about."""
    from viva.tools import runner
    from viva.tools.envelope import figure

    unsaid = figure("1", "a thing", quantity=quantity.COUNT, record_ids=["r"])
    unsaid["id"] = "f1"
    for over in shape_module.SCOPES:
        slot = Slot("many", render.COUNT, quantity.COUNT, over)
        written, tag, detail = runner._figure_bound(slot, unsaid, "en-US")
        assert written is None, over
        assert tag == "wrong_scope", (over, detail)


def _hole(kind, measures="", over=""):
    """One clause holding one hole of `kind`, as a model sends it.

    A hole holding a magnitude carries the set it is over as well as what it
    measures, so a pairing refused for want of the second declaration is not
    read as a pairing the check rejects. A hole of a kind that measures nothing
    over a set carries no scope, for the same reason the other way round."""
    slot = {"name": "it", "type": kind}
    if measures:
        slot["quantity"] = measures
        if render.magnitudes_of(kind):
            slot["scope"] = list(over) if over else [shape_module.WHOLE]
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
