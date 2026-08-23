"""Tool runner contracts."""

from _tool_test_support import *

# -------------------------------------------------------------------- runner

def test_every_tag_the_runner_can_refuse_with_is_declared():
    """A refusal is spoken from the pack by its tag, so a tag the vocabulary
    does not hold has no words behind it and would fail in front of a person.
    Read from the source rather than from a list someone maintains: every tag
    handed to the refusal, and every tag a hole's own check returns."""
    import ast
    import pathlib

    from viva.tools import runner as runner_module

    tree = ast.parse(pathlib.Path(runner_module.__file__).read_text())
    emitted = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_refused" and node.args
                and isinstance(node.args[0], ast.Constant)):
            emitted.add(node.args[0].value)
        if (isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple)
                and len(node.value.elts) == 3
                and isinstance(node.value.elts[1], ast.Constant)):
            emitted.add(node.value.elts[1].value)
    undeclared = sorted(t for t in emitted
                        if t and t not in runner_module.REFUSAL_TAGS)
    assert not undeclared, (
        f"{undeclared} can end a turn and is not in REFUSAL_TAGS, so nothing "
        "in the pack answers for it")


def test_scripted_planner_produces_a_cited_answer(registry):
    """The whole mechanism, end to end. The sentence is authored while the run
    holds nothing; the read then happens; then one reference per hole. At no
    point does anything but the renderer write a character of the figure."""
    shape = _shape(("Your {which} stands at {balance}.",
                    [("which", "account"),
                     ("balance", "money", "balance", "account")]))
    result = run(
        "what is my checking balance?",
        _script(shape,
                ("query_ledger", {"entity": "balances",
                                  "filters": {"account": "chk"}}),
                bind=lambda results: {
                    "which": {"entity": _entity(results, "chk")},
                    "balance": {"figure": _fig(results, "balance")}}),
        registry)
    assert result.answered and result.calls == 2
    assert result.grade == CORROBORATED
    assert result.text.startswith("Your Everyday Checking stands at "
                                  "USD 600.00.")
    assert result.figures[0]["record_ids"]
    # And what was said is kept as the structure it was.
    assert result.shape == shape.to_dict()
    assert set(result.bindings) == {"which", "balance"}


def test_a_figure_id_the_run_never_produced_is_refused(registry):
    """The replacement for citing a record the run never read: a model can no
    longer name a record at all, only an id, and an id it made up matches
    nothing."""
    result = run(
        "balance?",
        _script(_shape(("You have {total}.",
                       [("total", "money", "balance", "whole")])),
                ("query_ledger", {"entity": "balances"}),
                bind=lambda results: {"total": {"figure": "f99"}}),
        registry)
    assert not result.answered and result.refusal == "unknown_figure"


def test_a_number_in_a_payload_but_in_no_figure_cannot_be_said(registry):
    """Payload laundering, dead — now by construction rather than by scanning.

    A holding's cost basis rides in `data`; the read emits its market value as
    a figure and says nothing about what it cost. A hole is filled by a
    reference into what the run established, and a number sitting in a payload
    has no identity to be referred to by."""
    holdings = registry.call("query_ledger", {"entity": "holdings"})
    buried = holdings.data["holdings"][0]["cost_basis"]
    assert all(buried != f["value"] for f in holdings.figures)
    assert not any(buried == item.get("label")
                   for item in holdings.identifiers)

    result = run(
        "what did it cost?",
        _script(_shape(("You paid {cost} for it.",
                        [("cost", "money", "balance", "whole")])),
                ("query_ledger", {"entity": "holdings"}),
                bind=lambda results: {"cost": {"figure": "f99"}}),
        registry)
    assert not result.answered and result.refusal == "unknown_figure"


def test_a_financial_figure_standing_on_no_record_is_refused(registry):
    """A magnitude added to a counted thing leaves a number resting on no
    document: the term nothing measured injects a quantity rather than
    rescaling one, so the documents behind the count answer for a different
    number. It has an id, so it can be referred to — and it is refused anyway,
    because what a figure about money must stand on has not moved.

    The term nothing measured also takes away the set the number was over, so
    what the sentence claims to be about is what refuses first — a figure over
    no nameable set is not sayable at all, whatever it stands on. That the
    figure cites nothing is held here beside it."""
    result = run(
        "how much?",
        _script(_shape(("That makes {total}.",
                       [("total", "count", "count", "whole")])),
                ("query_ledger", {"entity": "balances"}),
                ("compute", {"expression": "n + 424242",
                             "inputs": {"n": "f4"}}),
                bind=lambda results: {
                    "total": {"figure": _fig(results, "result of")}}),
        registry)
    assert not result.answered and result.refusal == "wrong_scope"
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    fabricated = registry.call("compute", {"expression": "n + 424242",
                                           "inputs": {"n": "f4"}},
                               figures=book)
    assert fabricated.ok, fabricated.text
    assert not fabricated.figures[0]["record_ids"]


def test_a_money_figure_citing_no_record_is_refused_at_the_citation_gate():
    """The gate itself, held at the unit, on a figure assembled to reach it.

    A figure about money whose records are empty is refused, and the answer it
    was bound into is not said. Held here rather than through a turn because
    the checks ahead of this one settle every route a read can take to it: what
    a sentence claims to be about is compared first, and a figure that lost its
    records lost the set it was over in the same step. The rule is what a later
    emitter would meet, so it is asserted where it lives."""
    from viva.tools import runner
    from viva.tools.envelope import MONEY_KINDS, bounded, figure

    uncited = figure("600.00", "an amount standing on nothing",
                     quantity=quantity.BALANCE, grade=VERIFIED, currency="USD",
                     record_ids=[], boundary=bounded(whole=True))
    uncited["id"] = "f1"
    assert uncited["kind"] in MONEY_KINDS, "the gate reads the figure's kind"

    shape = _shape(("You hold {total}.",
                    [("total", "money", "balance", "whole")]))
    ground = runner._Ground(book={"f1": uncited})
    refused = runner._gate({"bindings": {"total": {"figure": "f1"}}}, [],
                           ground, shape, "en-US", tools=())
    assert not refused.answered
    assert refused.refusal == "uncited_figure", refused.detail
    assert refused.text and "600" not in refused.text

    # And the same figure with a record behind it is said, so what the gate
    # refuses on is the records and not the figure.
    cited = dict(uncited, record_ids=["doc-one"])
    said = runner._gate({"bindings": {"total": {"figure": "f1"}}}, [],
                        runner._Ground(book={"f1": cited}), shape, "en-US",
                        tools=())
    assert said.answered, said.detail


def test_a_holdings_count_over_an_empty_vault_refuses_as_uncited():
    """A count of holdings on a vault holding none ends the turn refused, end
    to end: nothing was found, so the count stands on no record, and the gate
    that every figure about money must cite something stops it.

    This pins a defect rather than a rule. The count is emitted as a claim
    about the person's money, and nobody has asked what a wrong number there
    would move — a count of things found stands on the records that establish
    there are none, which is a different account of what it rests on. Until
    that is settled, a person asking how many holdings they have on a vault
    with none is refused rather than told none. The item that removes it is
    *what a count is a count of*.

    The vault holds an account and a document, so what is missing is holdings
    and nothing else; the gate is reached rather than the read refusing
    first."""
    evs = [account_opened("acct-one", "investment", "Account One", "USD",
                          "2026-01-01"),
           document_captured("doc-one", "one.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("acct-one", "1000.00", "2026-01-01",
                                    _p("doc-one"))]
    empty = default_registry(LedgerProjection(evs))
    read = empty.call("query_ledger", {"entity": "holdings"})
    assert read.ok, read.text
    (count,) = [f for f in read.figures if f["quantity"] == quantity.COUNT]
    assert count["value"] == "0" and not count["record_ids"]

    result = run(
        "how many holdings do I have?",
        _script(_shape(("You hold {many} of them.",
                        [("many", "count", "count", "whole")])),
                ("query_ledger", {"entity": "holdings"}),
                bind=lambda results: {"many": {"figure": _fig(
                    results, "measured holdings")}}),
        empty)
    assert not result.answered
    assert result.refusal == "uncited_figure", result.detail


def test_figure_ids_are_unique_across_tools_and_restart_each_turn(registry):
    seen = []
    shape = _shape(("Your balance is {total}.",
                    [("total", "money", "balance", "account")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        if len(done) == 1:
            return {"tool": "check_completeness", "args": {}}
        seen.extend(f["id"] for r in context["results"]
                    for f in r["figures"])
        return {"bindings": {"total": {"figure": "f1"}}}

    first = run("what do you hold?", planner, registry)
    assert first.answered
    assert len(seen) == len(set(seen))
    assert seen[0] == "f1" and seen == [f"f{i}" for i in range(1, len(seen) + 1)]
    seen.clear()
    assert run("what do you hold?", planner, registry).answered
    assert seen[0] == "f1"                    # the id space is the turn's


def test_an_amount_the_person_never_said_cannot_be_echoed_back(registry):
    """A stipulation is the person's own number handed back to them. Its whole
    warrant is that they said it, so the gate checks the question itself."""
    shape = _shape(("The {trip} you mentioned is well within reach.",
                    [("trip", "supposed", "spending")]))
    result = run("could I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": "5000"}}),
                 registry)
    assert not result.answered and result.refusal == "unfounded_stipulation"


def test_an_amount_the_person_did_say_may_be_said_back(registry):
    shape = _shape(("About the {trip} you mentioned — I can look at that.",
                    [("trip", "supposed", "spending")]))
    result = run("could I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": "3000"}}),
                 registry)
    assert result.answered, result.detail
    assert "3000" in result.text
    assert result.grade == ""          # nothing here is an evidence claim


@pytest.mark.parametrize("part", ["300", "000", "00", "3"])
def test_a_piece_of_a_number_the_person_wrote_is_not_a_number_they_said(
        registry, part):
    """Their warrant is that they said it, and said it whole. A number matched
    inside another one lets a figure nobody named be handed back as the
    person's own — a tenth of what they asked about, or a hundredth, reading as
    something they themselves put on the table."""
    shape = _shape(("The {trip} you mentioned is well within reach.",
                    [("trip", "supposed", "spending")]))
    result = run("can I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": part}}),
                 registry)
    assert not result.answered and result.refusal == "unfounded_stipulation"


def test_a_figure_the_person_supplied_is_written_as_theirs(registry):
    """A figure resting on their premise and on no record of theirs reads as
    one of ours unless something says otherwise, and "something in the sentence
    around it" is not a thing any check can hold anyone to. The marker is part
    of writing the value, so it cannot be left off."""
    from viva import persona, render

    shape = _shape(("About the {trip} you mentioned — I can look at that.",
                    [("trip", "supposed", "spending")]))
    result = run("could I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": "3000"}}),
                 registry)
    assert result.answered, result.detail
    marked = persona.moment("supposed_amount",
                            amount=render.money("3000", locale=""))
    assert marked in result.text
    assert marked != "3000.00", "the marker adds nothing to the bare value"


def test_something_that_is_not_a_magnitude_cannot_arrive_as_a_supposition(
        registry):
    """The hole holds a figure the person supplied. Words are not a figure, and
    a hole that took them would be prose nobody reviewed reaching a person
    through the one binding that carries a value at all."""
    shape = _shape(("The {trip} you mentioned is well within reach.",
                    [("trip", "supposed", "spending")]))
    result = run("could I afford a 3000 trip?",
                 _script(shape, ("check_completeness", {}),
                         bind=lambda r: {"trip": {"supposed": "3000 or so, "
                                                  "whatever you think"}}),
                 registry)
    assert not result.answered and result.refusal == "unfounded_stipulation"


def test_a_hypothetical_figure_carries_no_grade_and_sets_none(registry):
    """Arithmetic over a premise is not evidence, and it is not over any set
    the vault measured either.

    A value the person supposed is over no nameable set; a balance is over one
    account. A number built from both is over neither, so there is no set a
    sentence could declare that it answers, and every scope refuses it. The
    figure is still emitted, carries no grade, and is still a thing the run
    established — what it cannot be is a claim about a set."""
    shape = _shape(("Supposing the {trip} trip, {left} would be left — that "
                    "rests on your figure, not on a statement.",
                    [("trip", "supposed", "spending"),
                     ("left", "money", "balance", "account")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        if len(done) == 1:
            return {"tool": "compute",
                    "args": {"expression": "have - trip",
                             "inputs": {"have": _fig(context["results"],
                                                     "balance"),
                                        "trip": {"stipulated": "250"}}}}
        return {"bindings": {"trip": {"supposed": "250"},
                             "left": {"figure": _fig(context["results"],
                                                     "result of")}}}
    result = run("could I afford a 250 trip?", planner, registry)
    assert not result.answered
    assert result.refusal == "wrong_scope", result.detail
    book = _one_figure(registry, "query_ledger",
                       {"entity": "balances", "filters": {"account": "chk"}})
    held = next(f["id"] for f in book.values()
                if f["quantity"] == quantity.BALANCE)
    supposed = registry.call("compute",
                             {"expression": "have - trip",
                              "inputs": {"have": held,
                                         "trip": {"stipulated": "250"}}},
                             figures=book,
                             question="could I afford a 250 trip?")
    assert supposed.ok, supposed.text
    assert supposed.figures[0]["kind"] == "hypothetical"
    assert supposed.figures[0]["grade"] == ""
    assert supposed.figures[0]["boundary"] == {"whole": False}


def test_a_supposition_does_not_wear_off_after_one_hop(registry):
    """The label has to survive being carried. If it only lasts one step, a
    number the person made up passes through arithmetic once and comes out
    inside a figure the product calls verified — which is the laundering
    figure identity was adopted to make impossible, arriving by a longer
    route."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values()
                   if "Everyday Checking" in f["what"])
    # A second figure of the same kind as the first: what is held on one
    # account adds to what is held on another, and this test is about what the
    # supposition does to the result rather than about which kinds combine.
    other = next(f["id"] for f in book.values()
                 if "Brokerage" in f["what"])
    first = registry.call("compute",
                          {"expression": "have - trip",
                           "inputs": {"have": balance,
                                      "trip": {"stipulated": "250"}}},
                          figures=book, question="could I afford a 250 trip?")
    supposed = first.figures[0]
    supposed["id"] = f"f{len(book) + 1}"
    book[supposed["id"]] = supposed
    assert supposed["kind"] == "hypothetical" and supposed["grade"] == ""

    second = registry.call("compute",
                           {"expression": "a + b",
                            "inputs": {"a": supposed["id"], "b": other}},
                           figures=book, question="and altogether?")
    assert second.figures[0]["kind"] == "hypothetical", (
        "a supposition wore off after one hop")
    assert second.figures[0]["grade"] == ""
    assert second.grade == ""


def test_an_answers_grade_ignores_activity_and_hypothetical_figures(registry):
    """A grade is an evidence claim. What the agent did, and what the person
    supposed, are neither — so neither may set or soften an answer's grade."""
    shape = _shape(("I have taken {actions} action(s); your balance is "
                    "{balance}.",
                    [("actions", "count", "count", "whole"),
                     ("balance", "money", "balance", "account")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "get_transparency",
                    "args": {"topic": "agent_activity"}}
        if len(done) == 1:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances", "filters": {"account": "chk"}}}
        return {"bindings": {
            "actions": {"figure": _fig(context["results"],
                                       "unattended actions")},
            "balance": {"figure": _fig(context["results"], "balance")}}}
    result = run("what have you done, and what is my balance?", planner, registry)
    assert result.answered, result.text
    kinds = {f["kind"] for f in result.figures}
    assert kinds == {"activity", "financial"}
    assert next(f for f in result.figures
                if f["kind"] == "activity")["record_ids"]
    # The load-bearing part: the activity figure is in the answer and its grade
    # is not. Give it a grade by hand — as a careless emitting tool would — and
    # the answer's grade must still be the balance's alone.
    activity = next(f for f in result.figures if f["kind"] == "activity")
    assert activity["grade"] == ""
    balance = next(f for f in result.figures if f["kind"] == "financial")
    assert result.grade == balance["grade"] == CORROBORATED

    from viva.tools.runner import _Ground, _gate
    ground = _Ground()
    for i, (kind, grade) in enumerate([("financial", CORROBORATED),
                                       ("activity", "conflicted")], 1):
        fig = figure("1", "a thing", quantity=quantity.COUNT, kind=kind,
                     record_ids=["r"], boundary=bounded(whole=True))
        fig.update(id=f"f{i}", grade=grade)      # a tool that graded carelessly
        ground.book[fig["id"]] = fig
    both = _shape(("{a} and {b}.", [("a", "count", "count", "whole"),
                                    ("b", "count", "count", "whole")]))
    spoken = _gate({"bindings": {"a": {"figure": "f1"}, "b": {"figure": "f2"}}},
                   [], ground, both, "", tools=())
    assert spoken.answered, spoken.detail
    assert spoken.grade == CORROBORATED


def test_a_number_no_tool_returned_is_refused(registry):
    """A number no tool returned is not refused late, after a sentence has been
    written around it — it cannot be written at all. The words of a clause carry
    no digits, so the only route a magnitude has to a person is a hole, and a
    hole is filled from what the run established.

    Both halves are here: a shape that spells one out does not come into being,
    and a run whose planner tries it never reaches a read."""
    with pytest.raises(BadShape) as raised:
        _shape(("Your balance is about 9999.99.", []))
    assert raised.value.problem.repair == HOLE_THE_NUMBER

    def planner(context):
        if not context["shaped"]:
            return {"shape": {"clauses": [{"text": "About 9999.99.",
                                           "slots": []}]}}
        return {"bindings": {}}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "bad_plan"


def test_a_ranging_read_reports_what_it_is_attested_for(registry):
    """A read that ranges over time says which account it is attested for and
    over what period; one that measures a moment carries its value-time
    instead."""
    ranging = registry.call("query_ledger", {"entity": "transactions"})
    assert ranging.ok and ranging.covers
    for entry in ranging.covers:
        assert entry["account"] and entry["from"] <= entry["to"]
    moment = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "net_worth"})
    assert moment.ok and moment.covers == [] and moment.dated

def test_coverage_is_the_period_a_statement_attested_not_the_movement_dates(registry):
    """A statement posts only by reconciling, so its whole period is covered
    even where no movement falls. Reading the span off the movements instead
    would report a quiet fortnight as a hole in the evidence."""
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2026-01-01", "to": "2026-01-31"}}})
    assert result.ok
    assert result.covers == [{"account": "chk", "from": "2026-01-01",
                              "to": "2026-01-31"}]
    assert not any("past the evidence" in c for c in result.caveats)


def test_a_window_reaching_past_what_is_attested_is_clipped_and_says_so(registry):
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2020-01-01", "to": "2030-12-31"}}})
    assert result.ok
    assert result.covers == [{"account": "chk", "from": "2026-01-01",
                              "to": "2026-01-31"}]
    assert any("reaches past what its statements attest" in c
               for c in result.caveats)

def test_a_window_outside_what_is_attested_covers_nothing_and_says_which(registry):
    """Nothing spent and nothing attested must not read alike."""
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2019-01-01", "to": "2019-12-31"}}})
    assert result.ok and result.covers == []
    assert any("none of which falls inside the window asked for" in c
               for c in result.caveats)


def test_a_filter_that_matches_nothing_still_reports_its_coverage(registry):
    """A category, tag or merchant filter selects rows; it does not decide what
    the vault holds. A zero inside an attested period is money not spent, never
    evidence not held, and the two sentences are not interchangeable."""
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk", "merchant": "payment received",
                    "window": {"from": "2026-01-01", "to": "2026-01-31"}}})
    assert result.ok
    assert result.covers == [{"account": "chk", "from": "2026-01-01",
                              "to": "2026-01-31"}]
    assert not any("no evidence" in c.lower() for c in result.caveats)


def test_an_account_with_no_statement_says_so_rather_than_guessing(registry):
    """An account whose period nothing attests borrows nothing from its
    movements: it reports no coverage and names itself."""
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending"})
    assert result.ok
    assert {c["account"] for c in result.covers} == {"chk"}
    assert any("No statement has posted for card" in c for c in result.caveats)

def test_the_window_asked_for_can_be_stated_in_the_answer(registry):
    """A span a read is attested for is a thing the read established, so the
    answer may say which period it is answering for — by referring to that
    span, never by writing its edges. The figure stated beside it was taken
    over that same span, which is what makes the sentence one claim rather than
    two."""
    window = {"from": "2026-01-05", "to": "2026-01-20"}
    shape = _shape(("Over {span} you spent {total}.",
                    [("span", "period"),
                     ("total", "money", "spending", "period")]))
    result = run(
        "what did I spend then?",
        _script(shape,
                ("query_ledger", {"entity": "aggregate", "metric": "spending",
                                  "filters": {"window": window}}),
                bind=lambda results: {
                    "span": {"period": "p1"},
                    "total": {"figure": _fig(results, "total spending")}}),
        registry)
    assert result.answered, result.detail
    assert "2026-01-05 to 2026-01-20" in result.text


def test_a_span_is_the_span_the_figure_beside_it_was_taken_over(registry):
    """A period hole binds a span a figure its own clause states was measured
    over, and not any span this run's documents answer for.

    Two reads, two spans: one asked for a window and is attested for it, one
    was asked for nothing and was taken over everything. A sentence stating the
    second under the first says a number covers a stretch nothing measured it
    across — the span is real, the number is real, and together they are false.
    So the clause is what decides, and where it states no figure taken over the
    span there is nothing for the hole to say."""
    window = {"from": "2026-01-05", "to": "2026-01-20"}
    shape = _shape(("Over {span} you spent {total}.",
                    [("span", "period"),
                     ("total", "money", "spending", "whole")]))
    result = run(
        "what did I spend?",
        _script(shape,
                ("query_ledger", {"entity": "aggregate", "metric": "spending",
                                  "filters": {"window": window}}),
                ("query_ledger", {"entity": "aggregate",
                                  "metric": "spending"}),
                bind=lambda results: {
                    # p1 is the first read's window; the figure is the second
                    # read's total, taken over every day there is.
                    "span": {"period": "p1"},
                    "total": {"figure": [f["id"] for f in results[-1]["figures"]
                                         if "total spending" in f["what"]][0]}}),
        registry)
    assert not result.answered and result.refusal == "unknown_period", (
        result.detail)


def test_a_period_a_read_is_attested_for_can_never_ground_a_figure(registry):
    """A period is scope — what a document answers for — and never a magnitude.
    It has its own kind, so binding one where an amount belongs is a type
    error rather than a matter of how the sentence was worded."""
    shape = _shape(("The figure is {total}.",
                   [("total", "money", "balance", "whole")]))
    result = run(
        "?",
        _script(shape, ("query_ledger", {"entity": "aggregate",
                                         "metric": "spending"}),
                bind=lambda results: {"total": {"period": "p1"}}),
        registry)
    assert not result.answered and result.refusal == "wrong_kind"


def test_a_date_outside_everything_read_is_refused(registry):
    """A day none of this run's results carries cannot be said, and there is no
    longer any way to declare one into being."""
    shape = _shape(("Nothing to report since {when}.", [("when", "date")]))
    result = run(
        "when?",
        _script(shape, ("query_ledger", {"entity": "transactions"}),
                bind=lambda results: {"when": {"date": "2019-12-31"}}),
        registry)
    assert not result.answered and result.refusal == "unfounded_date"


def test_an_answer_has_no_way_to_name_a_record_at_all(registry):
    """This replaces the check that a figure citing an unread record is
    refused. That test guarded a rule the model could break; now it cannot
    reach the field. A cited figure is an id, and the records travel with the
    figure the tool emitted — so naming a record the run never read is not a
    thing an answer can express."""
    from viva.speak import FINAL_PARAMS
    from viva.tools.runner import BINDING_KEYS

    assert set(FINAL_PARAMS["properties"]) == {"bindings"}
    assert "record" not in BINDING_KEYS and "record_ids" not in BINDING_KEYS


def test_the_call_budget_ends_in_one_closing_attempt_then_refuses(registry):
    """Exhaustion spends one more model call with only the terminator on the
    table, because a turn holding a grounded figure should deliver it rather
    than die beside it. If that closing reply reaches for a tool anyway, the
    turn refuses — and the planner is not asked again."""
    closings = []
    shape = _shape(("Noted, as of {when}.", [("when", "date")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        closings.append(bool(context["final_call"]))
        return {"tool": "check_completeness", "args": {}}
    result = run("loop forever", planner, registry, max_calls=3)
    assert not result.answered and result.refusal == "call_budget_exhausted"
    assert result.calls == 3
    assert closings == [False, False, True]


def test_an_answer_delivered_on_the_closing_call_passes_the_gate_normally(registry):
    shape = _shape(("Your checking balance is {balance}.",
                    [("balance", "money", "balance", "account")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        if not context["final_call"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        return {"bindings": {"balance": {"figure": _fig(context["results"],
                                                        "balance")}}}
    result = run("balance?", planner, registry, max_calls=3)
    assert result.answered and result.grade == CORROBORATED


def test_every_planner_context_says_how_many_calls_remain(registry):
    seen = []
    # A turn that reads and then answers on the one thing a run establishes
    # without reading: the value the person put into their own question.
    shape = _shape(("You asked about {yours}.",
                    [("yours", "supposed", "spending")]))

    def planner(context):
        seen.append(context["calls_remaining"])
        if not context["shaped"]:
            return {"shape": shape}
        if len(seen) < 3:
            return {"tool": "check_completeness", "args": {}}
        return {"bindings": {"yours": {"supposed": "40"}}}
    assert run("was it 40?", planner, registry, max_calls=4).answered
    assert seen == [4, 3, 2]


def test_a_refusal_result_flows_back_to_the_planner(registry):
    seen = {}
    shape = _shape(("It stands at {balance}.",
                    [("balance", "money", "balance", "account")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances",
                             "filters": {"account": "mystery"}}}
        seen["refusal"] = done[0]["refusal"]
        known = done[0]["data"]["known_accounts"][0]
        if len(done) == 1:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": known}}}
        return {"bindings": {"balance": {"figure": _figure(context["results"],
                                                           "balance")["id"]}}}
    result = run("balance of mystery?", planner, registry)
    assert seen["refusal"] == "unknown_account"
    assert result.answered and result.calls == 3


# ------------------------------------------------- what the statements attest

def _statement_doc(doc_id, account, opening, opening_date, closing,
                   closing_date, posted=None, read_at=None):
    """A document that declares its own period, the way ingestion records one.

    `posted` differs from `closing` when a person corrected a figure the model
    misread: the reply keeps what was read, the ledger carries what was
    accepted."""
    accepted = posted or closing
    return [document_captured(doc_id, f"{doc_id}.pdf", 2, "bank_statement", 0.9,
                              read_at or closing_date),
            read_recorded(doc_id, "model", "extract-v1", "text",
                          _statement_reply(opening, opening_date,
                                           closing, closing_date),
                          0.0, 1, 1, True, None, read_at or closing_date),
            closing_balance_observed(account, accepted, closing_date,
                                     _p(doc_id, 6))]


def _gapped_projection():
    """January and March held, February never ingested — and February's real
    net change is zero, so the balances continue across the hole."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-jan"))]
    evs += _statement_doc("d-jan", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += _statement_doc("d-mar", "chk", "900.00", "2026-03-01",
                          "800.00", "2026-03-31")
    return LedgerProjection(evs)


def test_statements_join_only_when_the_dates_meet_as_well_as_the_balances():
    """The ingest stitch joins on balances alone, so a missing month whose net
    change is zero passes it. Requiring the dates to meet is what keeps the
    missing statement visible."""
    proj = _gapped_projection()
    assert proj.attested_runs("chk") == [("2026-01-01", "2026-01-31"),
                                         ("2026-03-01", "2026-03-31")]


def test_a_window_inside_a_gap_between_statements_is_not_covered():
    """A window falling in a gap between statements is not reported as covered,
    and its zero is not reported as a fact."""
    registry = default_registry(_gapped_projection())
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2026-02-01", "to": "2026-02-28"}}})
    assert result.ok and result.covers == []
    assert any("none of which falls inside the window" in c
               for c in result.caveats)


def test_a_window_spanning_a_gap_reports_both_periods_and_names_the_hole():
    registry = default_registry(_gapped_projection())
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk",
                    "window": {"from": "2026-01-01", "to": "2026-03-31"}}})
    assert result.covers == [
        {"account": "chk", "from": "2026-01-01", "to": "2026-01-31"},
        {"account": "chk", "from": "2026-03-01", "to": "2026-03-31"}]
    assert any("a statement between them is missing" in c
               for c in result.caveats)


def test_a_ledger_account_is_never_offered_as_one_with_no_statement(registry):
    """Only accounts a document opened are in scope. `Expenses:Uncategorized`
    is bookkeeping, and naming it in a caveat would be nonsense to a person."""
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending"})
    assert not any("Uncategorized" in c and "No statement" in c
                   for c in result.caveats)


def _uncategorized_projection():
    """One account and one spend nothing has categorized, so a spending read
    writes a caveat with an amount in it."""
    return LedgerProjection([
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01"),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", "5000.00", "2026-01-01", _p("doc-jan")),
        simple_transaction("chk", "-2665.44", "COUNTERPARTY ONE", "2026-01-05",
                           provenance=_p("doc-jan")),
        closing_balance_observed("chk", "2334.56", "2026-01-31",
                                 _p("doc-jan", 6)),
    ])


@pytest.mark.parametrize("locale", ["en-US", "de-DE"])
def test_an_amount_inside_a_caveat_is_written_like_every_other_amount(locale):
    """A caveat is a sentence a tool writes and an answer passes on verbatim,
    so an amount it spells for itself is a second convention arriving one line
    under the first. The read composes it through the same renderer, so the
    caveat and the answer above it write this person's money the same way."""
    from viva import render

    registry = default_registry(_uncategorized_projection(), locale)
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending",
                                            "group_by": "category"})
    assert result.ok
    written = render.money("2665.44", "USD", locale=locale)
    said = [c for c in result.caveats if "uncategorized" in c]
    assert said == [f"{written} is still uncategorized."]
    # And the figures the same read emits are written that way too, because
    # they go through the same function on their way to a hole.
    total = next(f for f in result.figures if f["what"].startswith("total"))
    assert render.money(total["value"], total["currency"],
                        locale=locale) == written


def _numbered_account_projection():
    """A vault whose account id carries the last four of its number, the shape
    `account_key` derives when a statement shows a number."""
    return LedgerProjection([
        account_opened("acct:northgate:4417", "depository", "Everyday Checking",
                       "USD", "2026-01-01", institution="Northgate Bank",
                       account_number="XX4417", account_names=["R VANCE"]),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("acct:northgate:4417", "1000.00",
                                 "2026-01-01", _p("doc-jan")),
        closing_balance_observed("acct:northgate:4417", "600.00",
                                 "2026-01-31", _p("doc-jan", 6)),
    ])


def test_an_answer_may_name_the_account_it_is_about(registry):
    """An answer that cannot say which account it means answers nothing, and an
    account has several names — a ledger path, a name someone gave it, a masked
    number. It is one entity carrying all of them, so an answer refers to the
    entity and the renderer chooses the form. There is no second form to allow
    for, because there is no form the model gets to write."""
    numbered = default_registry(_numbered_account_projection())
    result = numbered.call("query_ledger", {"entity": "balances"})
    (account,) = result.identifiers
    assert account["kind"] == "account"
    assert account["account"] == "acct:northgate:4417"
    assert account["number_masked"] == "••••4417"
    assert account["name"] == "Everyday Checking"

    shape = _shape(("{which} holds {balance}.",
                    [("which", "account"),
                     ("balance", "money", "balance", "whole")]))
    spoken = run("what do I have?",
                 _script(shape, ("query_ledger", {"entity": "balances"}),
                         bind=lambda results: {
                             "which": {"entity": _entity(results, "northgate")},
                             "balance": {"figure": _fig(results, "balance")}}),
                 numbered)
    assert spoken.answered, spoken.detail
    assert spoken.text == ("Everyday Checking holds USD 600.00. "
                           + moment(STOOD_BEHIND_MOMENT + spoken.grade))
    # And the run of digits inside that name never reaches the person on its
    # own, because nothing but the renderer ever writes the name.
    assert "4417" not in spoken.text


def _twin_account_projection():
    """Two accounts a person gave the same name, at different institutions —
    the ordinary case of a name that does not tell one from another."""
    evs = []
    for key, inst, number, opening in (
            ("acct:northgate:4417", "Northgate Bank", "XX4417", "1000.00"),
            ("acct:meridian:9082", "Meridian Bank", "XX9082", "2500.00")):
        evs += [
            account_opened(key, "depository", "Everyday Checking", "USD",
                           "2026-01-01", institution=inst,
                           account_number=number),
            opening_balance_observed(key, opening, "2026-01-01", _p("doc-jan")),
        ]
    evs.insert(0, document_captured("doc-jan", "jan.pdf", 100, "bank_statement",
                                    0.9, "2026-02-01"))
    return LedgerProjection(evs)


def test_two_accounts_a_person_named_the_same_are_told_apart(registry):
    """A name that names two things names neither. Where the name a person gave
    an account does not tell it from another the run also spoke about, the
    masked number goes with it — and where nothing collides, the plain name
    stands, because a number shown for no reason is noise.

    The two accounts share a description, so the figure of the one the sentence
    names is picked by the amount this fixture gave it: a sentence naming one
    account and stating the other's balance is refused before it can be read,
    which is the point of the check and not of this test."""
    twins = default_registry(_twin_account_projection())
    shape = _shape(("{which} holds {balance}.",
                    [("which", "account"),
                     ("balance", "money", "balance", "account")]))

    def spoken_for(reg, handle, held):
        def bind(results):
            figures = [f for r in results for f in r.get("figures") or []]
            return {"which": {"entity": _entity(results, handle)},
                    "balance": {"figure": next(f["id"] for f in figures
                                               if f["value"] == held)}}
        return run("what do I have?",
                   _script(shape, ("query_ledger", {"entity": "balances"}),
                           bind=bind),
                   reg)

    ambiguous = spoken_for(twins, "northgate", "1000.00")
    assert ambiguous.answered, ambiguous.detail
    assert ambiguous.text.startswith("Everyday Checking ••••4417 holds")

    alone = spoken_for(default_registry(_numbered_account_projection()),
                       "northgate", "600.00")
    assert alone.answered, alone.detail
    assert alone.text.startswith("Everyday Checking holds")


def test_a_total_is_dated_by_when_it_was_asked_for_not_by_its_oldest_line():
    """A balance carries forward: absent a newer statement, what was last
    observed is still what the account holds. So a total is good as of the day
    it was asked for, and how old the evidence under it is rides in the caveat
    and in each line's own `as_of`.

    The fixture holds three distinct dates — the day asked on, the newest
    evidence and the oldest — because a vault where they coincide cannot tell
    the competing rules apart."""
    events = [
        account_opened("old", "depository", "Dormant Savings", "USD",
                       "2026-01-01"),
        account_opened("new", "depository", "Everyday Checking", "USD",
                       "2026-01-01"),
        document_captured("doc-old", "old.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        document_captured("doc-new", "new.pdf", 100, "bank_statement", 0.9,
                          "2026-07-01"),
        opening_balance_observed("old", "100.00", "2026-01-01", _p("doc-old")),
        closing_balance_observed("old", "100.00", "2026-01-31", _p("doc-old")),
        opening_balance_observed("new", "500.00", "2026-01-01", _p("doc-new")),
        closing_balance_observed("new", "500.00", "2026-06-30", _p("doc-new")),
    ]
    asked_on = "2026-08-09"
    result = default_registry(LedgerProjection(events), today=asked_on).call(
        "query_ledger", {"entity": "aggregate", "metric": "net_worth"})
    assert result.ok, result.text
    point = result.data["point"]

    # Three distinct dates, so no two rules can be confused for each other: the
    # day asked on, the newest evidence, and the oldest.
    assert point["oldest_input"] == "2026-01-31"
    assert asked_on > "2026-06-30" > point["oldest_input"]
    assert result.dated == asked_on, (
        "the total is dated by its evidence rather than by the day it is "
        "good for — the carry-forward ruling is written down, not built")
    for fig in result.figures:
        if fig["what"].endswith(" in USD"):
            assert fig["dated"] == asked_on, fig["what"]
    # And the per-account lines still carry their own evidence dates, which is
    # where the age of any one part of it reaches a reader.
    lines = {ln["account"]: ln.get("as_of", "") for ln in point["lines"]}
    assert set(lines.values()) == {"2026-01-31", "2026-06-30"}
    for fig in result.figures:
        if " — its part of net worth" in fig["what"]:
            assert fig["dated"] == lines[fig["what"].split(" — ")[0]]


def test_a_caveat_travels_to_the_model_as_a_sentence_and_not_as_a_handle():
    """An answer cannot refer to a caveat, so the model is given no way to try.

    The run still identifies caveats internally — that is how it knows which a
    stated figure owes — but an id in the payload is a handle, and a handle a
    released prompt once taught the model to bind costs a whole turn when it
    binds one now."""
    from viva.tools.envelope import ENTITY_ACCOUNT, ToolResult, entity
    from viva.tools.runner import _Ground

    result = ToolResult(tool="query_ledger", ok=True,
                        caveats=["This does not cover everything."],
                        identifiers=[entity(ENTITY_ACCOUNT, account="acct:x")])
    ground = _Ground(question="?")
    ground.stamp(result)

    assert list(ground.caveats) == ["c1"], "the run still identifies it"
    shown = result.to_dict()["caveats"]
    assert shown == [{"text": "This does not cover everything."}]
    assert "id" not in shown[0], "a caveat id is not a handle a model may bind"


def test_an_account_two_reads_spoke_about_is_not_its_own_twin(registry):
    """One account named by two reads is one account.

    Given a second identity it would collide with itself, and the renderer that
    tells two same-named accounts apart would dutifully write the number out
    beside a name nothing was competing with — an account written twice in one
    breath because the run had counted it twice."""
    numbered = default_registry(_numbered_account_projection())
    shape = _shape(("{which} holds {balance}.",
                    [("which", "account"),
                     ("balance", "money", "balance", "whole")]))

    spoken = run("what do I have?",
                 _script(shape,
                         ("query_ledger", {"entity": "balances"}),
                         ("query_ledger", {"entity": "balances"}),
                         bind=lambda results: {
                             "which": {"entity": _entity(results, "northgate")},
                             "balance": {"figure": _fig(results, "balance")}}),
                 numbered)
    assert spoken.answered, spoken.detail
    assert spoken.text == ("Everyday Checking holds USD 600.00. "
                           + moment(STOOD_BEHIND_MOMENT + spoken.grade)), (
        "a second read of one account made it collide with itself")
    assert "4417" not in spoken.text


def test_two_reads_saying_the_same_thing_say_it_once(registry):
    """A caveat is a thing, not an occurrence of one.

    Every read of the same kind writes the same sentence about what its numbers
    do not cover. If each occurrence were its own caveat, an answer standing on
    four of those reads would have to say the identical sentence four times to
    get past the gate — and a sentence repeated four times reads as a machine
    stuttering, not as a limit being disclosed."""
    from viva.tools.envelope import ENTITY_ACCOUNT, ToolResult, entity
    from viva.tools.runner import _Ground

    def read():
        return ToolResult(
            tool="query_ledger", ok=True,
            caveats=["Each line is only as current as its stalest input."],
            identifiers=[entity(ENTITY_ACCOUNT, account="acct:northgate:4417",
                                name="Everyday Checking",
                                number_masked="••••4417")],
            figures=[figure("600.00", "Everyday Checking — balance",
                            quantity=quantity.BALANCE, currency="USD",
                            grade=VERIFIED, record_ids=["doc-jan"])])

    ground = _Ground(question="what do I have?")
    for _ in range(4):
        ground.stamp(read())

    assert list(ground.caveats) == ["c1"], "one sentence, one caveat"
    assert list(ground.entities) == ["a1"], "one account, one identity"
    # Four figures, though: each read established its own number, and every one
    # of them owes the one caveat, so placing it once answers for all four.
    assert len(ground.book) == 4
    assert {ids for ids in ground.owed.values()} == {("c1",)}


def _brokerage_reply():
    import json
    return json.dumps({"as_of_raw": "2026-01-31", "cash_raw": "100.00",
                       "total_raw": "1600.00",
                       "positions": [{"instrument": "ALPHA FUND",
                                      "units_raw": "10",
                                      "market_value_raw": "1500.00"}]})


def _corrected_projection():
    """Three consecutive months. February's closing was misread and a person
    corrected it, so what posted differs from what the reply still says."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-1"))]
    evs += _statement_doc("d-1", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += _statement_doc("d-2", "chk", "900.00", "2026-02-01",
                          "850.00", "2026-02-28", posted="800.00")
    evs += _statement_doc("d-3", "chk", "800.00", "2026-03-01",
                          "700.00", "2026-03-31")
    return LedgerProjection(evs)


def test_a_corrected_closing_does_not_invent_a_missing_statement():
    """The reply says what the model read; the ledger says what was accepted.
    Reading the reply's figure would break the join to the next month and
    announce a missing statement between two months that abut."""
    assert _corrected_projection().attested_runs("chk") == [
        ("2026-01-01", "2026-03-31")]


def test_the_register_is_the_same_live_as_replayed():
    """A projection built event by event and one replayed from the same log
    must describe the same vault. Dropping the cache on chosen events is what
    let the two disagree for the life of a process."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-1"))]
    evs += _statement_doc("d-1", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    live = LedgerProjection(evs)
    assert live.attested_runs("chk")            # build the register, then move on
    # February's reply arrives while the register is cold, and only the posting
    # follows. A policy that watches for a new reading would miss this, which is
    # the shape a corrected or healed statement actually takes.
    early = _statement_doc("d-2", "chk", "900.00", "2026-02-01",
                           "800.00", "2026-02-28")
    read, posting = early[:2], early[2:]
    for event in read:
        live.apply(event)
    live.attested_runs("chk")                   # warm the register again
    for event in posting:
        live.apply(event)
    assert live.attested_runs("chk") == LedgerProjection(
        evs + early).attested_runs("chk") == [("2026-01-01", "2026-02-28")]


def test_an_as_of_read_never_attests_past_its_own_horizon():
    """A read as of a past date holds only the movements up to it. Attesting a
    period that runs past it would claim completeness for days it is
    deliberately not showing."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-q"))]
    # read on 10 February, declaring a period that runs to the end of March —
    # so the reading is inside the horizon and the period it claims is not
    evs += _statement_doc("d-q", "chk", "1000.00", "2026-01-01",
                          "800.00", "2026-03-31", read_at="2026-02-10")
    assert LedgerProjection(evs).attested_runs("chk") == [("2026-01-01",
                                                          "2026-03-31")]
    assert LedgerProjection(evs, as_of="2026-02-15").attested_runs("chk") == []


def test_statements_are_ordered_by_period_not_by_document_id():
    """Document ids arrive in no meaningful order. Without an explicit sort the
    runs fragment and the answer announces missing statements that are held."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("zzz"))]
    evs += _statement_doc("zzz", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += _statement_doc("aaa", "chk", "900.00", "2026-02-01",
                          "800.00", "2026-02-28")
    evs += _statement_doc("mmm", "chk", "800.00", "2026-03-01",
                          "700.00", "2026-03-31")
    assert LedgerProjection(evs).attested_runs("chk") == [("2026-01-01",
                                                          "2026-03-31")]


def test_a_document_that_is_not_a_statement_attests_nothing_even_if_it_parses():
    """The register asks what kind of document declared a period, not whether
    something statement-shaped can be read out of it. A holdings document whose
    reply happens to parse must still attest nothing, because a snapshot says
    nothing about the days around it."""
    evs = [account_opened("brk", "investment", "Brokerage", "USD", "2026-01-01"),
           document_captured("d-x", "x.pdf", 2, "brokerage_statement", 0.9,
                             "2026-01-31"),
           read_recorded("d-x", "model", "extract-v1", "text",
                         _statement_reply("1000.00", "2026-01-01",
                                          "1600.00", "2026-01-31"),
                         0.0, 1, 1, True, None, "2026-01-31"),
           closing_balance_observed("brk", "1600.00", "2026-01-31", _p("d-x", 3))]
    assert LedgerProjection(evs).attested_runs("brk") == []


def test_statements_whose_balances_do_not_continue_are_two_periods():
    """Dates that meet are not enough. A February opening at a figure January
    did not close at means something between them is unaccounted for, and the
    two months are not one attested stretch."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-1"))]
    evs += _statement_doc("d-1", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += _statement_doc("d-2", "chk", "850.00", "2026-02-01",
                          "800.00", "2026-02-28")
    assert LedgerProjection(evs).attested_runs("chk") == [
        ("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28")]


def test_a_defect_among_the_transactions_does_not_remove_the_period():
    """The register reads the two boxes that bound a statement. A statement is
    in the ledger because it reconciled, so announcing it missing on account of
    an unreadable transaction would deny a month the vault fully holds."""
    import json
    broken = json.dumps({
        "opening": {"amount_raw": "900.00", "date_raw": "2026-02-01"},
        "closing": {"amount_raw": "800.00", "date_raw": "2026-02-28"},
        "transactions": [{"date_raw": "not a date", "amount_raw": "??",
                          "description": "unreadable"}]})
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-1"))]
    evs += _statement_doc("d-1", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-01-31")
    evs += [document_captured("d-2", "d-2.pdf", 2, "bank_statement", 0.9,
                              "2026-02-28"),
            read_recorded("d-2", "model", "extract-v1", "text", broken,
                          0.0, 1, 1, True, None, "2026-02-28"),
            closing_balance_observed("chk", "800.00", "2026-02-28", _p("d-2", 6))]
    evs += _statement_doc("d-3", "chk", "800.00", "2026-03-01",
                          "700.00", "2026-03-31")
    assert LedgerProjection(evs).attested_runs("chk") == [("2026-01-01",
                                                          "2026-03-31")]
