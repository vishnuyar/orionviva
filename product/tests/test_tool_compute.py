"""Tool compute contracts."""

from _tool_test_support import *
from test_tool_contract import _every_figure

# ------------------------------------------------------------------- compute

def _one_figure(registry, tool, args):
    """The figure book after one call, as the runner would stamp it."""
    result = registry.call(tool, args)
    assert result.ok, result.text
    for i, fig in enumerate(result.figures, 1):
        fig["id"] = f"f{i}"
    return {f["id"]: f for f in result.figures}


def _shift(book, offset):
    """The same figures, renumbered as if a second call had emitted them."""
    out = {}
    for i, fig in enumerate(book.values(), offset + 1):
        fig["id"] = f"f{i}"
        out[fig["id"]] = fig
    return out


def test_compute_is_exact(registry):
    """The float-drift trap, and the reason arithmetic is a tool at all. If
    this passes while `compute` returns the wrong number, the suite is
    measuring everything about arithmetic except whether it is right."""
    book = {}
    for i, amount in enumerate(("0.10", "0.20"), 1):
        f = figure(amount, f"a tenth {i}", quantity=quantity.BALANCE,
                   grade=VERIFIED, currency="USD",
                   record_ids=["doc-jan"])
        f["id"] = f"f{i}"
        book[f["id"]] = f
    result = registry.call("compute",
                           {"expression": "a + b",
                            "inputs": {"a": "f1", "b": "f2"}}, figures=book)
    assert result.ok and result.figures[0]["value"] == "0.30"
    thirds = registry.call("compute",
                           {"expression": "a * 3",
                            "inputs": {"a": "f1"}}, figures=book)
    assert thirds.figures[0]["value"] == "0.30"


def test_compute_inherits_records_and_the_weakest_grade_from_its_operands(registry):
    """An operand is a figure, so provenance is carried rather than declared:
    the result stands on the same documents and can be no stronger than the
    weakest thing it was built from. Arithmetic is deterministic, so nothing is
    lost in the crossing — the result is a claim about money like its parts."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    ids = [f["id"] for f in book.values() if "balance" in f["what"]]
    result = registry.call("compute",
                           {"expression": "a + b",
                            "inputs": {"a": ids[0], "b": ids[1]}},
                           figures=book)
    assert result.ok
    assert result.figures[0]["kind"] == "computed"
    assert result.grade == weakest(book[i]["grade"] for i in ids[:2])
    assert result.figures[0]["grade"] == result.grade
    assert set(result.record_ids) == {r for i in ids[:2]
                                      for r in book[i]["record_ids"]}


def test_compute_will_not_add_across_currencies(registry):
    """Every read here refuses to convert, for want of a rate with a date, a
    source and a grade of its own. Arithmetic may not do quietly what the reads
    will not do at all."""
    book = {}
    for i, currency in enumerate(("USD", "EUR"), 1):
        f = figure("100.00", f"balance {i}", quantity=quantity.BALANCE,
                   grade=VERIFIED, currency=currency,
                   record_ids=[f"doc-{i}"])
        f["id"] = f"f{i}"
        book[f["id"]] = f
    result = registry.call("compute", {"expression": "a + b",
                                       "inputs": {"a": "f1", "b": "f2"}},
                           figures=book)
    assert not result.ok and result.refusal == "mixed_currencies"


def test_compute_will_not_mix_what_the_agent_did_with_what_you_hold(registry):
    """A figure about the agent's own behaviour and a figure about money make a
    number of neither kind, and the emitting tool is the only thing allowed to
    decide a kind."""
    book = _one_figure(registry, "get_transparency", {"topic": "calls_spent"})
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "balances"}), len(book)))
    activity = next(f["id"] for f in book.values() if f["kind"] == "activity")
    money = next(f["id"] for f in book.values() if "balance" in f["what"])
    result = registry.call("compute", {"expression": "a + b",
                                       "inputs": {"a": activity, "b": money}},
                           figures=book)
    assert not result.ok and result.refusal == "mixed_kinds"


def test_compute_comes_back_as_an_envelope_however_large_the_arithmetic(registry):
    """No arithmetic input makes the call raise across the boundary.

    A magnitude larger than the context can carry, a division by zero, a very
    long expression and a deeply nested one all come back as refusal envelopes.

    The huge case scales an amount by a plain number on purpose. An expression
    the walk turns away on its dimensions never reaches the arithmetic at all,
    so it would pass this test while measuring nothing about it — which is why
    the expected tags here are the arithmetic's own."""
    for args, question, expected in (
            ({"expression": "x * 10",
              "inputs": {"x": {"stipulated": "1e999999999"}}}, "1e999999999",
             ("bad_expression",)),
            ({"expression": "x / 0",
              "inputs": {"x": {"stipulated": "100"}}}, "100",
             ("division_by_zero",)),
            ({"expression": "+".join(["1"] * 1200), "inputs": {}}, "",
             ("bad_expression", "bad_input")),
            ({"expression": "1" + "*(1" * 400 + ")" * 400, "inputs": {}}, "",
             ("bad_expression", "bad_input"))):
        result = registry.call("compute", args, figures={}, question=question)
        assert not result.ok and result.refusal in expected, result.refusal


def test_a_magnitude_the_expression_invented_stands_on_no_document(registry):
    """Naming a figure and depending on it are different things. A magnitude
    typed into an expression carries none of the documents of a figure the call
    merely bound — one subtracted away, one multiplied by zero, one never
    referred to at all — so it stands on nothing and cannot be said."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values() if "balance" in f["what"])
    for expression in ("a - a + 424242", "a * 0 + 999999"):
        refused = registry.call("compute",
                                {"expression": expression,
                                 "inputs": {"a": balance}}, figures=book)
        assert not refused.ok, f"{expression} came back as {refused.figures}"
        assert refused.refusal == "mixed_dimensions"
    # Subtracting a figure from itself is not the fabrication and is not
    # refused: zero really is what those documents say the difference is.
    zero = registry.call("compute", {"expression": "a - a",
                                     "inputs": {"a": balance}}, figures=book)
    assert zero.ok and Decimal(zero.figures[0]["value"]) == 0
    assert zero.record_ids == book[balance]["record_ids"]
    # A magnitude alone inherits nothing from a figure it never touched: no
    # records, no grade, and nothing saying what it is a magnitude of.
    alone = registry.call("compute", {"expression": "987654",
                                      "inputs": {"a": balance}}, figures=book)
    assert alone.ok and alone.figures[0]["record_ids"] == []
    assert alone.figures[0]["grade"] == ""
    assert alone.figures[0]["quantity"] == quantity.UNMEASURED

    shape = _shape(("That comes to {total}.",
                   [("total", "count", "count", "whole")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        if len(done) == 1:
            return {"tool": "compute",
                    "args": {"expression": "987654",
                             "inputs": {"a": _fig(context["results"],
                                                  "balance")}}}
        return {"bindings": {"total": {"figure": _fig(context["results"],
                                                      "result of")}}}
    assert run("how much?", planner, registry).refusal == "wrong_quantity"


# ------------------------------------------ what a computed figure rests on

def _book(*specs):
    """A figure book as the runner would stamp one, built from
    `(value, what, grade, currency, records)`. Every value in it is
    synthetic.

    A spec stating a currency is an amount held, and one stating none counts
    things — which is what the specs below already mean, said once here so
    every one of them does not have to repeat it."""
    out = {}
    for i, (value, what, grade, currency, records) in enumerate(specs, 1):
        fig = figure(value, what, grade=grade, currency=currency,
                     quantity=quantity.BALANCE if currency else quantity.COUNT,
                     record_ids=records)
        fig["id"] = f"f{i}"
        out[fig["id"]] = fig
    return out


def _computed(registry, book, expression, **inputs):
    """One arithmetic call over a book, asserted to have come back."""
    result = registry.call("compute", {"expression": expression,
                                       "inputs": inputs}, figures=book)
    assert result.ok, f"{expression}: {result.refusal} — {result.text}"
    return result.figures[0]


TWO_AMOUNTS_AND_A_COUNT = (
    ("600.00", "an amount", VERIFIED, "USD", ["doc-one"]),
    ("200.00", "another amount", UNVERIFIED, "USD", ["doc-two"]),
    ("7", "a count of things", CONFLICTED, "", ["doc-three"]),
)


def test_a_magnitude_added_to_a_plain_number_takes_the_total_off_its_evidence(
        registry):
    """A count is a plain number, so a magnitude may be added to it with no
    dimension objecting. Adding is where a magnitude enters rather than
    rescales, so a term standing on no record leaves the total standing on
    none, and carrying no grade.

    That the other terms were well evidenced is what the assertion is about:
    their evidence says nothing about the number that came out."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    for expression, inputs in (
            ("n - n + 424242", {"n": "f3"}),
            ("n * 0 + 777", {"n": "f3"}),
            ("(a / b) * 0 + 8888", {"a": "f1", "b": "f2"})):
        result = registry.call("compute", {"expression": expression,
                                           "inputs": inputs}, figures=book)
        assert result.ok, f"{expression} refused: {result.refusal}"
        fig = result.figures[0]
        assert fig["record_ids"] == [], f"{expression} cites {fig['record_ids']}"
        assert fig["grade"] == "", f"{expression} claims {fig['grade']}"
        assert result.record_ids == [] and result.grade == ""


def test_a_fabricated_total_is_refused_before_it_can_be_said(registry):
    """A fabricated total cannot be said, and there are now two reasons it
    cannot.

    A magnitude nothing measured injects: it takes the documents behind the
    count away from the number, and it takes the set away too, leaving a
    figure over neither what it was added to nor anything else. The sentence
    declares what set it is about, so that is the first thing found, and the
    turn ends before the citation gate is reached. Both faults are held here:
    the tag that fires, and the fact that the figure stands on nothing."""
    shape = _shape(("That comes to {total}.",
                   [("total", "count", "count", "whole")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        if len(done) == 1:
            return {"tool": "compute",
                    "args": {"expression": "n - n + 424242",
                             "inputs": {"n": _fig(context["results"],
                                                  "accounts holding")}}}
        return {"bindings": {"total": {"figure": _fig(context["results"],
                                                      "result of")}}}
    run_result = run("how much?", planner, registry)
    assert not run_result.answered
    assert run_result.refusal == "wrong_scope"
    # The count it was built from is a real figure with real documents, which
    # is what made the fabrication look attested in the first place.
    counted = _one_figure(registry, "query_ledger", {"entity": "balances"})
    count = next(f for f in counted.values() if "accounts holding" in f["what"])
    assert count["record_ids"] and count["grade"]


def _earning_and_spending():
    """A vault holding one attributed income and one purchase, in one
    currency: the pair of whole-ledger totals the commonest comparison of two
    unlike kinds is made of."""
    evs = [account_opened("acct-0", "depository", "Account", "USD",
                          "2026-01-01"),
           document_captured("doc-one", "one.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           transaction_recorded([Posting("acct-0", Decimal("500.00"), VERIFIED),
                                 Posting("Income:Salary", Decimal("-500.00"),
                                         VERIFIED)],
                                "PAYROLL", "2026-01-10",
                                provenance=_p("doc-one")),
           transaction_recorded([Posting("acct-0", Decimal("-120.00"),
                                         VERIFIED),
                                 Posting("Expenses:Groceries",
                                         Decimal("120.00"), VERIFIED)],
                                "NORTHWIND MARKET", "2026-01-12",
                                provenance=_p("doc-one"))]
    return default_registry(LedgerProjection(evs))


def _spending_over_income(shape):
    """One turn dividing a whole-ledger spending total by a whole-ledger
    income total and binding the quotient into `shape`'s one hole."""
    registry = _earning_and_spending()

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger",
                    "args": {"entity": "aggregate", "metric": "spending"}}
        if len(done) == 1:
            return {"tool": "query_ledger",
                    "args": {"entity": "aggregate", "metric": "income"}}
        if len(done) == 2:
            return {"tool": "compute",
                    "args": {"expression": "spent / earned",
                             "inputs": {
                                 "spent": _fig(context["results"],
                                               "total spending"),
                                 "earned": _fig(context["results"],
                                                "attributed income")}}}
        return {"bindings": {"share": {"figure": _fig(context["results"],
                                                      "result of")}}}
    return run("how does my spending compare to my income?", planner, registry)


def test_a_comparison_of_two_unlike_kinds_fills_no_hole_and_is_written_nowhere():
    """Spending over income is a real quotient of two real figures, and the
    vocabulary's own name for it says no kind is true of the result.

    A proportion is written in a unit — per hundred — so writing this one picks
    a unit for a number that has none, and the sentence around it then means
    whatever the words happened to say. The binding is refused instead, and
    nothing of the quotient reaches the page.

    The comparison is made over one set: both totals are whole, so the scope
    check has nothing to catch and this is the check that fires."""
    quotient = _spending_over_income(
        _shape(("Your spending comes to {share} of what you earn.",
                [("share", "rate", quantity.RATIO, "whole")])))
    assert not quotient.answered and quotient.refusal == "wrong_kind"
    assert "%" not in quotient.text


def test_a_proportion_of_one_kind_of_thing_still_fills_a_proportion_hole():
    """The other side of the same rule, so it reads as a refusal of numbers
    with no name rather than a refusal of proportions.

    A quotient of two figures measuring one kind is a proportion OF that kind,
    the vocabulary names it, and it is written per hundred as it always was."""
    registry = _earning_and_spending()
    shape = _shape(("That is {share} of what you spend.",
                    [("share", "rate", quantity.ratio_of(quantity.SPENDING),
                      "whole")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger",
                    "args": {"entity": "aggregate", "metric": "spending"}}
        if len(done) == 1:
            total = _fig(context["results"], "total spending")
            return {"tool": "compute",
                    "args": {"expression": "a / a",
                             "inputs": {"a": total}}}
        return {"bindings": {"share": {"figure": _fig(context["results"],
                                                      "result of")}}}
    spoken = run("what share of my spending is that?", planner, registry)
    assert spoken.answered, spoken.detail
    assert "%" in spoken.text


def test_what_refuses_a_comparison_is_the_figures_own_name_for_itself():
    """The refusal reads two declarations and no words.

    The quotient's own quantity is the bare name the vocabulary gives a
    comparison of unlike kinds; the hole's type is the kind of thing written
    per hundred. Neither is a sentence, and the clause's words are the same in
    the case that is refused and the case that is not."""
    quotient = _spending_over_income(
        _shape(("Your spending comes to {share} of what you earn.",
                [("share", "rate", quantity.RATIO, "whole")])))
    assert quotient.refusal == "wrong_kind"
    computed = [r for r in quotient.transcript if r["tool"] == "compute"]
    assert computed and computed[0]["ok"]
    (result,) = [f for r in computed for f in (r.get("figures") or [])]
    assert result["quantity"] == quantity.RATIO


def test_which_quantities_assert_a_direction_is_declared_with_the_vocabulary():
    """The rule has one home, and it is the module that owns the words.

    A quantity asserting which way the money goes is a fact about the word,
    not about a kind of account, so it is declared beside the word and the
    binding check reads that declaration. Adding the next one is an edit to
    this list and to nothing else."""
    assert quantity.OWED in quantity.ASSERTS_DIRECTION
    assert set(quantity.ASSERTS_DIRECTION) <= set(quantity.KINDS)


def test_a_negative_value_of_a_quantity_asserting_no_direction_still_speaks(
        registry):
    """What the direction rule is not: a rule about signs.

    What a set of movements came to nets one way or the other, and its own
    name asserts neither, so a negative one fills the hole asking for it and is
    written with the sign it carries."""
    shape = _shape(("Your accounts moved {net} over that stretch.",
                    [("net", "money", quantity.NET_MOVEMENT, "whole")]))
    spoken = run("what did my accounts do?",
                 _script(shape, ("query_ledger", {"entity": "transactions"}),
                         bind=lambda results: {
                             "net": {"figure": _fig(results,
                                                    "net movement over")}}),
                 registry)
    assert spoken.answered, spoken.detail
    assert str(render.money(Decimal("-100.00"), "USD")) in spoken.text


def test_scaling_a_figure_leaves_it_standing_where_it_stood(registry):
    """Multiplying or dividing by a plain magnitude changes the units, not the
    evidence: the result keeps the records and the grade of what was scaled.
    Annualising, halving, splitting per person and expressing a proportion are
    all this shape."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    for expression, inputs, records, grade in (
            ("a * 3", {"a": "f1"}, ["doc-one"], VERIFIED),
            ("a / 3", {"a": "f1"}, ["doc-one"], VERIFIED),
            ("(a / b) * 100", {"a": "f1", "b": "f2"},
             ["doc-one", "doc-two"], UNVERIFIED)):
        fig = _computed(registry, book, expression, **inputs)
        assert fig["record_ids"] == records, expression
        assert fig["grade"] == grade, expression


def test_a_graded_count_hands_its_evidence_to_what_it_scales(registry):
    """A count is a figure like any other: it has documents behind it and a
    grade of its own. An amount nothing disputes, scaled by a count that
    disagrees with its own evidence, is conflicted and cites both sides — not
    verified, citing half of what it was built from."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    fig = _computed(registry, book, "a * n", a="f1", n="f3")
    assert fig["record_ids"] == ["doc-one", "doc-three"]
    assert fig["grade"] == CONFLICTED
    assert fig["currency"] == "USD"


def test_a_total_of_attested_terms_keeps_them_all(registry):
    """Two figures added stand on both sets of documents at the weaker grade,
    and a figure subtracted from itself is a zero standing on its own
    document."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    total = _computed(registry, book, "a + b", a="f1", b="f2")
    assert total["record_ids"] == ["doc-one", "doc-two"]
    assert total["grade"] == UNVERIFIED and total["currency"] == "USD"
    zero = _computed(registry, book, "a - a", a="f1")
    assert Decimal(zero["value"]) == 0
    assert zero["record_ids"] == ["doc-one"] and zero["grade"] == VERIFIED


def test_a_figure_bound_and_never_named_decides_nothing(registry):
    """What currency a computation is in is a property of the expression. A
    second currency bound to a name the arithmetic never reaches leaves a
    single-currency computation alone; two currencies the expression actually
    reaches refuse."""
    book = _book(("600.00", "an amount", VERIFIED, "USD", ["doc-one"]),
                 ("100.00", "an amount elsewhere", VERIFIED, "EUR",
                  ["doc-two"]))
    fig = _computed(registry, book, "a * 2", a="f1", elsewhere="f2")
    assert fig["currency"] == "USD" and fig["record_ids"] == ["doc-one"]
    crossed = registry.call("compute",
                            {"expression": "a + elsewhere",
                             "inputs": {"a": "f1", "elsewhere": "f2"}},
                            figures=book)
    assert not crossed.ok and crossed.refusal == "mixed_currencies"


def test_negating_a_figure_keeps_everything_true_of_it(registry):
    """A sign is not a provenance event. What the figure measures, what it
    stands on, how strong it is and how its arithmetic came out all survive the
    minus — the last of these because a negated approximation stated as an
    exact number is the same untruth as any other."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    fig = _computed(registry, book, "-a", a="f1")
    assert Decimal(fig["value"]) == Decimal("-600.00")
    assert fig["currency"] == "USD"
    assert fig["record_ids"] == ["doc-one"] and fig["grade"] == VERIFIED
    assert fig["exactness"] == "exact"
    rounded = _computed(registry, book, "-(a / 7)", a="f1")
    assert rounded["exactness"] == "rounded"
    assert Decimal(rounded["value"]) == Decimal("-85.71")
    assert rounded["currency"] == "USD" and rounded["grade"] == VERIFIED
    assert rounded["record_ids"] == ["doc-one"]


def test_a_supposition_survives_being_computed_with_again(registry):
    """A figure derived from something the person supposed is hypothetical, and
    so is anything derived from that in turn, however many rounds of arithmetic
    separate them from the premise."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values() if "balance" in f["what"])
    first = registry.call(
        "compute", {"expression": "have - trip",
                    "inputs": {"have": balance, "trip": {"stipulated": "250"}}},
        figures=book, question="what if a trip cost 250?")
    assert first.ok and first.figures[0]["kind"] == "hypothetical"
    assert first.figures[0]["grade"] == ""
    book.update(_shift({"x": first.figures[0]}, len(book)))
    again = _computed(registry, book, "supposed * 2",
                      supposed=first.figures[0]["id"])
    assert again["kind"] == "hypothetical" and again["grade"] == ""


# --------------------------------------------------- how the arithmetic went

def test_a_division_that_does_not_come_out_is_answered_not_refused(registry):
    """A quotient that does not terminate comes back rather than refusing. The
    value is written at the scale money is counted in, and the figure says of
    itself that it was rounded."""
    book = _book(("2000.00", "an amount", VERIFIED, "USD", ["doc-one"]))
    for expression, value in (("a / 52", "38.46"), ("a / 12", "166.67")):
        fig = _computed(registry, book, expression, a="f1")
        assert fig["value"] == value, expression
        assert fig["exactness"] == "rounded", expression
        assert fig["currency"] == "USD"


def test_how_the_arithmetic_went_never_moves_the_grade(registry):
    """A figure that had to be rounded stands on the same documents at the same
    grade as one that did not; only its account of the arithmetic differs."""
    book = _book(*TWO_AMOUNTS_AND_A_COUNT)
    exact = _computed(registry, book, "a / 3", a="f1")
    rounded = _computed(registry, book, "a / 7", a="f1")
    assert exact["exactness"] == "exact" and rounded["exactness"] == "rounded"
    assert rounded["grade"] == exact["grade"] == VERIFIED
    assert rounded["record_ids"] == exact["record_ids"] == ["doc-one"]
    # And it travels the other way too: an exact operation over a rounded
    # operand cannot pretend the result came out.
    book.update(_shift({"x": rounded}, len(book)))
    onward = _computed(registry, book, "r + b", r=rounded["id"], b="f2")
    assert onward["exactness"] == "rounded"


SMALL_AND_LARGE = (
    ("1.00", "a small amount", VERIFIED, "USD", ["doc-one"]),
    ("300000.00", "a large amount", VERIFIED, "USD", ["doc-two"]),
    ("1234.56", "an amount", VERIFIED, "USD", ["doc-three"]),
    ("98765.43", "another amount", VERIFIED, "USD", ["doc-four"]),
)


def test_a_ratio_is_written_to_significant_figures_and_never_down_to_zero(
        registry):
    """No dimensionless result that is not zero is written as zero, at any
    magnitude.

    Decimal places are money's scale, not a ratio's: a proportion smaller than
    a hundredth written at two decimal places becomes 0.00, which is not an
    approximation of it but a different claim — and one carrying the grade of
    the documents it was derived from. Counting from the leading digit instead
    cannot do that, whatever the magnitude."""
    book = _book(*SMALL_AND_LARGE)
    for expression, inputs in (
            ("a / b", {"a": "f1", "b": "f2"}),
            ("(a / b) * (a / b)", {"a": "f1", "b": "f2"}),
            ("(a / b) * (a / b) * (a / b)", {"a": "f1", "b": "f2"}),
            ("c / d", {"c": "f3", "d": "f4"}),
            ("d / c", {"c": "f3", "d": "f4"}),
            ("(d / c) * (d / c) * 1000000", {"c": "f3", "d": "f4"})):
        fig = _computed(registry, book, expression, **inputs)
        assert fig["exactness"] == "rounded", expression
        assert Decimal(fig["value"]) != 0, (
            f"{expression} came out as {fig['value']}, which is a claim about "
            "the world rather than an approximation of the answer")
        assert fig["currency"] == "" and fig["grade"] == VERIFIED, expression
        digits = len(Decimal(fig["value"]).as_tuple().digits)
        assert digits <= 6, f"{expression} kept {digits} significant figures"


def test_a_proportion_and_the_same_proportion_per_hundred_agree(registry):
    """The same quantity asked two ways gives the same answer. Counting
    significant figures from the leading digit means a power of ten moves the
    point without moving the digits, so scaling before or after the rounding
    cannot disagree."""
    book = _book(*SMALL_AND_LARGE)
    for over, inputs in (("a / b", {"a": "f1", "b": "f2"}),
                         ("c / d", {"c": "f3", "d": "f4"}),
                         ("d / c", {"c": "f3", "d": "f4"})):
        plain = _computed(registry, book, over, **inputs)
        hundred = _computed(registry, book, f"({over}) * 100", **inputs)
        assert (Decimal(hundred["value"]) == Decimal(plain["value"]) * 100), (
            f"{over} is {plain['value']} but per hundred is "
            f"{hundred['value']}")


def test_money_is_written_at_the_scale_money_is_counted_in(registry):
    """An amount of money is written to hundredths whatever the arithmetic did
    to it, because that is the precision money has."""
    book = _book(("2000.00", "a yearly amount", VERIFIED, "USD", ["doc-one"]))
    for expression, value in (("a / 52", "38.46"), ("a / 12", "166.67"),
                              ("a / 7", "285.71")):
        fig = _computed(registry, book, expression, a="f1")
        assert fig["value"] == value, expression
        assert fig["currency"] == "USD" and fig["exactness"] == "rounded"
        assert fig["grade"] == VERIFIED and fig["record_ids"] == ["doc-one"]


def test_a_rounding_is_taken_once_at_the_end(registry):
    """A third of an amount, tripled, comes back to the amount itself. It would
    not if the third had been written at two decimals before the walk carried
    it on."""
    book = _book(("100.00", "an amount", VERIFIED, "USD", ["doc-one"]))
    fig = _computed(registry, book, "a / 3 * 3", a="f1")
    assert Decimal(fig["value"]) == Decimal("100.00")
    assert fig["exactness"] == "rounded"


def test_an_exactness_nothing_recognises_is_refused_where_it_is_written():
    """A value outside the vocabulary raises where the figure is written. It
    would otherwise travel as an account of the arithmetic while meaning
    nothing to anything that reads it."""
    plain = dict(quantity=quantity.COUNT)
    assert figure("1", "a thing", **plain)["exactness"] == "exact"
    assert figure("1", "a thing", exactness="rounded",
                  **plain)["exactness"] == "rounded"
    with pytest.raises(ValueError):
        figure("1", "a thing", exactness="roughly", **plain)


def test_the_model_is_told_only_when_a_figure_has_something_to_say():
    """A figure whose arithmetic came out exactly omits the field; one that had
    to be rounded sends it. Every result is resent on every remaining call of
    the turn, so a field carrying the ordinary case is paid for repeatedly."""
    ordinary = ToolResult(tool="t", ok=True,
                          figures=[figure("1.00", "a thing", currency="USD",
                                          quantity=quantity.BALANCE,
                                          record_ids=["doc-one"])])
    assert "exactness" not in ordinary.to_dict()["figures"][0]
    approximate = ToolResult(tool="t", ok=True,
                             figures=[figure("1.00", "a thing", currency="USD",
                                             quantity=quantity.BALANCE,
                                             record_ids=["doc-one"],
                                             exactness="rounded")])
    assert approximate.to_dict()["figures"][0]["exactness"] == "rounded"


def _approximate_run(registry, shape, bind, expression="a / 7",
                     read=("balances", None), over="Everyday Checking"):
    """One run whose answer states a figure the arithmetic had to round.

    `read` is the entity the run looks at and `over` the figure of it the
    arithmetic is done on, so the same run can be had over an amount, over a
    number of things, or over a proportion of one by another.

    The second call is written by hand rather than scripted because it binds a
    figure id the first call produced."""
    entity, filters = read
    args = {"entity": entity}
    if filters:
        args["filters"] = filters

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": args}
        if len(done) == 1:
            return {"tool": "compute",
                    "args": {"expression": expression,
                             "inputs": {"a": _fig(context["results"], over)}}}
        return {"bindings": bind(context["results"])}
    return run("how much a week?", planner, registry)


def _on_one_account() -> str:
    """What a clause says beside a figure taken over one account: which
    account it is. It is a claim about that figure, so it lands under the
    clause that stated it."""
    return moment("boundary_selected_account",
                  account=render.account({"account": "chk",
                                          "name": "Everyday Checking"},
                                         among=[]))


def _covering_one_of_three() -> str:
    """And what the answer says about itself once it is assembled: how many of
    the three accounts the fixture holds it covers. One claim about the whole
    answer, said once and after the clauses."""
    return moment("boundary_accounts", counted=render.count(1),
                  held=render.count(3))


def test_an_approximate_value_never_reaches_the_person_bare(registry):
    """A figure the arithmetic could not write exactly reaches the person
    carrying the term that says so.

    The shape asks for nothing of the kind and could not: it was written before
    any arithmetic happened, so hedging cannot be something the sentence
    remembered to do. The term travels with the figure, placed where the figure
    is placed.

    Dividing by a bare number changes the units and takes nothing away, so the
    weekly share of one account's balance is still over that one account and
    the answer says so beside it."""
    spoken = _approximate_run(
        registry,
        _shape(("You spend {weekly} a week.",
                [("weekly", "money", "balance", "account")])),
        lambda results: {"weekly": {"figure": _fig(results, "result of")}})
    assert spoken.answered, spoken.detail
    assert spoken.text == ("You spend about USD 85.71 a week. "
                           + _on_one_account() + " "
                           + _covering_one_of_three() + " "
                           + moment(STOOD_BEHIND_MOMENT + spoken.grade))
    # The figure itself is unchanged; only what was written from it is hedged.
    assert spoken.figures[0]["value"] == "85.71"
    assert spoken.figures[0]["exactness"] == "rounded"


def test_an_approximate_number_of_things_never_reaches_the_person_bare(
        registry):
    """And the same of a count, which is a magnitude like any other.

    A number of things the arithmetic could not write exactly is written to the
    nearest whole thing, and the digits shown are the digits of the value: a
    count cut off at the point would be a different number, always smaller, and
    said with no sign that it had been rounded at all."""
    spoken = _approximate_run(
        registry,
        _shape(("You make this many a week: {weekly}.",
                [("weekly", "count", "count", "whole")])),
        lambda results: {"weekly": {"figure": _fig(results, "result of")}},
        expression="a * 5 / 7", read=("transactions", None),
        over="movements matching the filters")
    assert spoken.answered, spoken.detail
    assert spoken.text == ("You make this many a week: about 3. "
                           + moment(STOOD_BEHIND_MOMENT + spoken.grade))
    assert spoken.figures[0]["value"] == "2.85714"
    assert spoken.figures[0]["exactness"] == "rounded"


def test_an_approximate_proportion_never_reaches_the_person_bare(registry):
    """And of a proportion, which is the third and last kind of magnitude a
    hole can hold. A share written to fewer digits than it was carried at is
    still a share that did not come out exactly."""
    spoken = _approximate_run(
        registry,
        _shape(("That is {share} of it.",
                [("share", "rate", quantity.ratio_of(quantity.BALANCE),
                  "account")])),
        lambda results: {"share": {"figure": _fig(results, "result of")}},
        expression="a / a / 7")
    assert spoken.answered, spoken.detail
    # One seventh, carried as the quotient and written per hundred. Both
    # operands of the share were taken over the same one account, and dividing
    # by a bare number leaves it over that account, so the answer says which.
    assert spoken.text == ("That is about 14.2857% of it. "
                           + _on_one_account() + " "
                           + _covering_one_of_three() + " "
                           + moment(STOOD_BEHIND_MOMENT + spoken.grade))
    assert spoken.figures[0]["exactness"] == "rounded"


def test_a_figure_over_everything_is_hedged_the_same_way(registry):
    """The hedge belongs to the figure, not to what its sentence claims about
    sets. A number over the whole of what it counts is written with the same
    term when the arithmetic could not write it exactly, and the sentence
    stating it places no scope clause, because there is no narrowing to state.

    So one assertion about hedging stands where the scope vocabulary cannot
    move it: whatever a hole declares, a rounded figure still reaches a person
    saying it is rounded."""
    spoken = _approximate_run(
        registry,
        _shape(("That is about {each} each.",
                [("each", "count", "count", "whole")])),
        lambda results: {"each": {"figure": _fig(results, "result of")}},
        read=("balances", None), over="accounts holding a balance")
    assert spoken.answered, spoken.detail
    stated = spoken.figures[0]
    assert stated["exactness"] == "rounded"
    assert stated["boundary"] == {"whole": True,
                                  "accounts": {"counted": 3, "held": 3}}
    assert spoken.written["each"] == moment(
        "approx_count", count=render.count(Decimal(stated["value"])))
    # Whole, so nothing about where the claim ends is placed under it.
    assert _on_one_account() not in spoken.text
    assert _covering_one_of_three() not in spoken.text


def test_only_the_value_that_was_rounded_is_hedged(registry):
    """The term reaches what the arithmetic could not write exactly, and
    nothing else.

    One sentence states an exact balance and an approximate weekly share of it,
    deliberately: a rule that hedged every amount would satisfy an assertion
    made with approximate figures alone."""
    spoken = _approximate_run(
        registry,
        _shape(("Of {held} you spend {weekly} a week.",
                [("held", "money", "balance", "account"),
                 ("weekly", "money", "balance", "account")])),
        lambda results: {"held": {"figure": _fig(results, "Everyday Checking")},
                         "weekly": {"figure": _fig(results, "result of")}})
    assert spoken.answered, spoken.detail
    # The sentence itself, then what the run places behind it: one of the
    # figures is a balance over one account of the several this person holds,
    # and the answer says which set it came from.
    assert spoken.text.startswith("Of USD 600.00 you spend about USD 85.71 "
                                  "a week.")


# ------------------------------------ what a money figure is allowed to lack

def test_every_money_figure_a_tool_emits_stands_on_a_record():
    """Every figure stating a currency carries at least one record.

    The attestation rule uses "carries a record" as the proxy for "is
    attested", so an amount emitted with nothing behind it would let a
    magnitude added to it inherit an attestation nothing earned, or would
    strip a legitimate total of the evidence it did have."""
    for what, fig in _every_figure().items():
        if fig["currency"]:
            assert fig["record_ids"], (
                f"{what!r} is an amount of money standing on no record")


def test_a_quiet_window_is_still_an_amount_and_still_stands_on_something(
        registry):
    """A window in which nothing moved has a total, and that total is zero of a
    currency, resting on the accounts whose statements answer for the period.
    Saying neither would make the zero read as a plain number, which no balance
    can be put together with at all."""
    quiet = {"entity": "transactions",
             "filters": {"window": {"from": "2026-06-01", "to": "2026-06-30"}}}
    summary = registry.call("query_ledger", quiet)
    assert summary.ok and summary.data["count"] == 0
    net = next(f for f in summary.figures
               if f["what"] == "net movement over this set")
    assert net["currency"] == "USD" and net["record_ids"]
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    book.update(_shift(_one_figure(registry, "query_ledger", quiet), len(book)))
    balance = next(f["id"] for f in book.values()
                   if "Everyday Checking" in f["what"])
    still = next(f["id"] for f in book.values()
                 if f["what"] == "net movement over this set")
    combined = _computed(registry, book, "a - b", a=balance, b=still)
    assert combined["currency"] == "USD" and combined["grade"]


def test_a_refusal_to_add_says_what_it_actually_saw(registry):
    """The refusal names what was observed — that one side states a currency
    and the other states none — rather than guessing at what the plain side
    counts or measures."""
    book = _book(("600.00", "an amount", VERIFIED, "USD", ["doc-one"]),
                 ("7", "a count of things", VERIFIED, "", ["doc-two"]))
    refused = registry.call("compute", {"expression": "a + n",
                                        "inputs": {"a": "f1", "n": "f2"}},
                            figures=book)
    assert not refused.ok and refused.refusal == "mixed_dimensions"
    assert "count or a ratio" not in refused.text
    assert "states a currency" in refused.text


def test_two_amounts_divide_into_a_ratio_and_never_into_money(registry):
    """Asking how a balance compares with a total is division, and its
    answer is "three times over", not "three dollars". A currency on a ratio is
    a claim about money that no money was ever measured for."""
    book = {}
    for i, (amount, grade) in enumerate((("600.00", VERIFIED),
                                         ("200.00", UNVERIFIED)), 1):
        f = figure(amount, f"an amount {i}", quantity=quantity.BALANCE,
                   grade=grade, currency="USD",
                   record_ids=[f"doc-{i}"])
        f["id"] = f"f{i}"
        book[f["id"]] = f
    ratio = registry.call("compute", {"expression": "a / b",
                                      "inputs": {"a": "f1", "b": "f2"}},
                          figures=book)
    assert ratio.ok and Decimal(ratio.figures[0]["value"]) == 3
    assert ratio.figures[0]["currency"] == ""
    assert set(ratio.record_ids) == {"doc-1", "doc-2"}
    assert ratio.figures[0]["grade"] == UNVERIFIED
    product = registry.call("compute", {"expression": "a * b",
                                        "inputs": {"a": "f1", "b": "f2"}},
                            figures=book)
    assert not product.ok and product.refusal == "mixed_dimensions"
    inverted = registry.call("compute", {"expression": "2 / a",
                                         "inputs": {"a": "f1"}}, figures=book)
    assert not inverted.ok and inverted.refusal == "mixed_dimensions"
    # Splitting an amount by a plain number is still an amount of money.
    split = registry.call("compute", {"expression": "a / 3",
                                      "inputs": {"a": "f1"}}, figures=book)
    assert split.ok and split.figures[0]["currency"] == "USD"
    assert split.figures[0]["grade"] == VERIFIED


def test_a_balance_still_combines_with_what_a_summary_totalled(registry):
    """The two questions a person actually asks across reads — a balance less
    what moved over a set, a balance less a total spent — are money and money,
    and they must go through. A total that failed to state its currency would
    read as a plain number and turn both into refusals."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "transactions"}), len(book)))
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "aggregate",
                                    "metric": "spending"}), len(book)))
    balance = next(f["id"] for f in book.values()
                   if "Everyday Checking" in f["what"])
    net = next(f["id"] for f in book.values()
               if f["what"] == "net movement over this set")
    spent = next(f["id"] for f in book.values()
                 if f["what"].startswith("total spending"))
    counted = next(f["id"] for f in book.values()
                   if f["what"] == "movements matching the filters")
    for expression, inputs in (("a - b", {"a": balance, "b": net}),
                               ("a - b", {"a": balance, "b": spent})):
        result = registry.call("compute", {"expression": expression,
                                           "inputs": inputs}, figures=book)
        assert result.ok, f"{expression}: {result.text}"
        assert result.figures[0]["currency"] == "USD"
        assert result.figures[0]["kind"] == "computed"
        assert result.figures[0]["grade"] and result.record_ids
    # And the two that must not: an amount times an amount, and a count added
    # to an amount.
    for expression, inputs in (("a * b", {"a": balance, "b": spent}),
                               ("a + b", {"a": balance, "b": counted})):
        refused = registry.call("compute", {"expression": expression,
                                            "inputs": inputs}, figures=book)
        assert not refused.ok, f"{expression} came back as {refused.figures}"
        assert refused.refusal == "mixed_dimensions"


def test_what_a_total_measures_follows_from_what_its_terms_measure(registry):
    """What is held taken together with what moved is still what is held, so a
    balance less what was spent is a balance and can be asked about as one.
    Two different flows are two different questions and their sum answers
    neither, so the arithmetic refuses rather than hand back a number whose
    meaning the reader would have to supply."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "transactions"}), len(book)))
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "aggregate",
                                    "metric": "spending"}), len(book)))
    of = {f["what"]: f["id"] for f in book.values()}
    balance = next(i for w, i in of.items() if "Everyday Checking" in w)
    spent = next(i for w, i in of.items() if w.startswith("total spending"))
    gross = of["money out over these movements"]

    left = registry.call("compute", {"expression": "a - b",
                                     "inputs": {"a": balance, "b": spent}},
                         figures=book)
    assert left.ok and left.figures[0]["quantity"] == quantity.BALANCE

    both = registry.call("compute", {"expression": "a + b",
                                     "inputs": {"a": spent, "b": gross}},
                         figures=book)
    assert not both.ok and both.refusal == "mixed_quantities"


def test_only_a_flow_taken_out_of_a_stock_is_still_that_stock(registry):
    """Which way round the two stand, and which way the operator runs, are both
    part of what the total measures.

    What is held, less what was spent, is what is left. Nothing else about that
    pair is a balance: what was spent less what is held is a magnitude with the
    wrong sign and no referent, and what is held plus what was spent is larger
    than anything the person has. Each of those, called a balance, is a true
    number under a false description — every record real, every grade earned,
    and the sentence a lie about what was measured. So they refuse."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    book.update(_shift(_one_figure(registry, "query_ledger",
                                   {"entity": "aggregate",
                                    "metric": "spending"}), len(book)))
    of = {f["what"]: f["id"] for f in book.values()}
    held = next(i for w, i in of.items() if "Everyday Checking" in w)
    spent = next(i for w, i in of.items() if w.startswith("total spending"))
    left_over = Decimal(book[held]["value"]) - Decimal(book[spent]["value"])

    kept = registry.call("compute", {"expression": "held - spent",
                                     "inputs": {"held": held, "spent": spent}},
                         figures=book)
    assert kept.ok, kept.text
    assert kept.figures[0]["quantity"] == quantity.BALANCE
    assert Decimal(kept.figures[0]["value"]) == left_over

    for expression in ("spent - held", "held + spent", "spent + held"):
        refused = registry.call("compute",
                                {"expression": expression,
                                 "inputs": {"held": held, "spent": spent}},
                                figures=book)
        assert not refused.ok, (
            f"{expression} came back as "
            f"{refused.figures[0]['value']} of "
            f"{refused.figures[0]['quantity']}")
        assert refused.refusal == "mixed_quantities", expression


def _held_and_owed():
    """A vault holding one account of each side: money held, and money owed on
    a card, both attested by a statement."""
    evs = [
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01"),
        account_opened("card", "liability", "Signature Card", "USD",
                       "2026-01-01"),
        document_captured("doc-one", "one.pdf", 10, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", "5000.00", "2026-01-01", _p("doc-one")),
        closing_balance_observed("chk", "5000.00", "2026-01-31",
                                 _p("doc-one", 6)),
        opening_balance_observed("card", "0.00", "2026-01-01", _p("doc-one")),
        simple_transaction("card", "1000.00", "COUNTERPARTY ONE", "2026-01-08",
                           provenance=_p("doc-one")),
        closing_balance_observed("card", "1000.00", "2026-01-31",
                                 _p("doc-one", 7)),
    ]
    return default_registry(LedgerProjection(evs))


def test_what_is_owed_does_not_add_to_what_is_held():
    """The arithmetic this vocabulary exists for. Both figures are real, both
    are corroborated, and a sum of them is a number about nothing: what is held
    on one account and what is owed on another are opposite claims, and adding
    them reads as a total the person has while overstating it by every debt in
    it. It refuses, and the refusal names both kinds so the model can see what
    it put together."""
    reg = _held_and_owed()
    book = _one_figure(reg, "query_ledger", {"entity": "balances"})
    held = next(f["id"] for f in book.values() if "Everyday Checking" in f["what"])
    owed = next(f["id"] for f in book.values() if "Signature Card" in f["what"])
    assert book[owed]["quantity"] == quantity.OWED
    for expression in ("held + owed", "owed + held", "held - owed"):
        refused = reg.call("compute", {"expression": expression,
                                       "inputs": {"held": held, "owed": owed}},
                           figures=book)
        assert not refused.ok, (
            f"{expression} came back as {refused.figures[0]['value']} of "
            f"{refused.figures[0]['quantity']}")
        assert refused.refusal == "mixed_quantities", expression
        assert quantity.BALANCE in refused.text and quantity.OWED in refused.text
    both = reg.call("compute", {"expression": "a + b",
                                "inputs": {"a": owed, "b": owed}},
                    figures=book)
    assert both.ok and both.figures[0]["quantity"] == quantity.OWED, (
        "two debts add to a debt")


def test_a_net_worth_cannot_be_assembled_out_of_its_two_sides():
    """The instruction never to build a net worth by hand becomes a property of
    the machine. The two sides of a point measure different things, so
    subtracting one from the other refuses and the model is left with the read
    that is complete on its own and says what it left out."""
    reg = _held_and_owed()
    book = _one_figure(reg, "query_ledger", {"entity": "aggregate",
                                             "metric": "net_worth"})
    of = {f["what"]: f["id"] for f in book.values()}
    assets = next(i for w, i in of.items() if w.startswith("assets in"))
    liabilities = next(i for w, i in of.items() if w.startswith("liabilities in"))
    assert book[assets]["quantity"] == quantity.BALANCE
    assert book[liabilities]["quantity"] == quantity.OWED
    refused = reg.call("compute", {"expression": "a - l",
                                   "inputs": {"a": assets, "l": liabilities}},
                       figures=book)
    assert not refused.ok and refused.refusal == "mixed_quantities"
    stated = next(f for f in book.values() if f["what"].startswith("net in"))
    assert stated["quantity"] == quantity.NET_WORTH
    assert Decimal(stated["value"]) == Decimal("4000.00")


def test_splitting_a_quantity_leaves_it_the_quantity_it_was(registry):
    """A year's spending over its months is spending, so the answer to "on
    average" is bindable where the answer to "in total" is. What it must not
    become is a proportion: dividing by a count is splitting an amount up, not
    comparing two things."""
    book = _one_figure(registry, "query_ledger", {"entity": "transactions"})
    of = {f["what"]: f["id"] for f in book.values()}
    gross = of["money out over these movements"]
    months = of["months these movements span"]
    per_month = registry.call("compute", {"expression": "a / b",
                                          "inputs": {"a": gross, "b": months}},
                              figures=book)
    assert per_month.ok, per_month.text
    assert per_month.figures[0]["quantity"] == quantity.GROSS_FLOW
    assert per_month.figures[0]["currency"] == "USD"


def test_two_measured_things_divide_into_a_proportion(registry):
    """Comparing an amount with an amount, or a count with a count, gives a
    number of times over rather than an amount or a count of anything — which
    is what a proportion is, and it is the only way one is ever produced."""
    book = _one_figure(registry, "query_ledger", {"entity": "transactions"})
    of = {f["what"]: f["id"] for f in book.values()}
    for a, b in ((of["money out over these movements"],
                  of["net movement over this set"]),
                 (of["movements matching the filters"],
                  of["months these movements span"])):
        share = registry.call("compute", {"expression": "a / b",
                                          "inputs": {"a": a, "b": b}},
                              figures=book)
        assert share.ok, share.text
        assert quantity.is_ratio(share.figures[0]["quantity"])
        assert share.figures[0]["currency"] == ""


def test_a_quotient_carries_what_its_operands_measured(registry):
    """A quotient's quantity comes from its operands: two figures of one kind
    give a proportion of that kind, and two of different kinds give a bare
    proportion, since no single kind is true of it."""
    book = _one_figure(registry, "query_ledger", {"entity": "transactions"})
    of = {f["what"]: f["id"] for f in book.values()}

    def divide(a, b):
        got = registry.call("compute", {"expression": "a / b",
                                        "inputs": {"a": of[a], "b": of[b]}},
                            figures=book)
        assert got.ok, got.text
        return got.figures[0]["quantity"]

    assert divide("net movement on card", "net movement on chk") == \
        quantity.ratio_of(quantity.NET_MOVEMENT)
    assert divide("movements matching the filters",
                  "months these movements span") == \
        quantity.ratio_of(quantity.COUNT)
    assert divide("money out over these movements",
                  "net movement over this set") == quantity.RATIO


def test_a_proportion_of_one_thing_is_not_a_proportion_of_another(registry):
    """The quantity check, reached through division: the hole asks about
    spending and the operands are gross flows, so the number is real and the
    description of it is not, and the answer is refused. The check compares two
    declarations, so the division has to carry one of them."""
    shape = _shape(("That is {share} of what you spend.",
                    [("share", "rate", quantity.ratio_of(quantity.SPENDING),
                      "whole")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "transactions"}}
        if len(done) == 1:
            gross = _fig(done, "money out over")
            return {"tool": "compute",
                    "args": {"expression": "a / b",
                             "inputs": {"a": gross, "b": gross}}}
        return {"bindings": {"share": {"figure": _fig(context["results"],
                                                      "result of")}}}

    assert run("what share of my spending goes there?",
               planner, registry).refusal == "wrong_quantity"


def test_compute_refuses_a_number_typed_in_and_names_what_it_has(registry):
    """The dead end this ends: a model retyping values it read and computing
    over them succeeded call after call, and the answer was refused at the very
    end. Now the first call says no and says what the operands could be."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    refused = registry.call("compute",
                            {"expression": "a", "inputs": {"a": "600.00"}},
                            figures=book)
    assert not refused.ok and refused.refusal == "bad_input"
    offered = {f["id"] for f in refused.data["available_figures"]}
    assert offered == set(book)


def test_compute_over_something_only_the_person_said_is_hypothetical(registry):
    """Arithmetic on the person's own premise is answerable and is not an
    evidence claim: it carries no grade, and it says which it is."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values() if "balance" in f["what"])
    result = registry.call("compute",
                           {"expression": "have - trip",
                            "inputs": {"have": balance,
                                       "trip": {"stipulated": "250"}}},
                           figures=book, question="could I afford a 250 trip?")
    assert result.ok
    assert result.figures[0]["kind"] == "hypothetical"
    assert result.figures[0]["grade"] == ""
    # An amount they named is money in the currency of what it is set against,
    # so the subtraction goes through and the answer is an amount.
    assert (Decimal(result.figures[0]["value"])
            == Decimal(book[balance]["value"]) - 250)
    assert result.figures[0]["currency"] == "USD"


def test_compute_refuses_a_stipulation_the_person_never_made(registry):
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    result = registry.call("compute",
                           {"expression": "trip",
                            "inputs": {"trip": {"stipulated": "854203"}}},
                           figures=book, question="could I afford a 250 trip?")
    assert not result.ok and result.refusal == "bad_input"


def test_compute_refuses_what_it_cannot_do_exactly(registry):
    def call(args):
        return registry.call("compute", args, figures={})
    assert call({"expression": "0.1 + 0.2",
                 "inputs": {}}).refusal == "bad_expression"
    assert call({"expression": "a + 1", "inputs": {}}).refusal == "bad_expression"
    assert call({"expression": "__import__('os')",
                 "inputs": {}}).refusal == "bad_expression"
    assert call({"expression": "1 / 0",
                 "inputs": {}}).refusal == "division_by_zero"
