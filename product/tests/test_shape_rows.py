"""Shape rows contracts."""

from _shape_test_support import *
from test_shape_claims import _figure_id, several

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
    (named,) = stated["boundary"]["cut"]
    assert moment(key, **{slot: render.label(named["value"])}) \
        not in result.text


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
                        [("total", "money", "balance", "account")]))


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
        (cut,) = figure["boundary"]["cut"]
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

    shape = _shape(("You spent {slice_}.",
                   [("slice_", "money", "spending", "subcategory")]))
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
    """A block is one line per figure taken over a named slice. A read whose
    figures are each over the whole of what they count named none, so there is
    nothing to write a line per, and binding it is a delivery naming the wrong
    sort of read rather than a hole nothing could fill."""
    result = run("list what you are holding",
                 _script(_shape(*_LIST), ("check_completeness", {}),
                         bind=_bind_the_read),
                 _wide(4))
    assert not result.answered
    assert result.refusal == "wrong_kind", result.detail


def test_a_narrowed_reads_own_total_is_not_a_line_of_itself(registry):
    """A read narrowed one way and grouped another has two sorts of figure that
    each name a slice, and only one of them is a row.

    The groups are slices of what the read returned. The total is the whole of
    what it returned, and the slice it names is the narrowing itself — which
    the block already states once, above the lines. So the block is the groups,
    the total is not among them, and neither the count of lines nor what the
    answer stands on includes it."""
    result = run("what did I spend there, by category?",
                 _script(_shape(("Here is what you spent, by category:"
                                 "{breakdown}", [("breakdown", render.ROWS)])),
                         _AT_ONE_COUNTERPARTY, bind=_bind_the_read),
                 registry)
    assert result.answered, result.detail
    assert len(_lines_of(result.text)) == 1, result.text
    assert [f["what"] for f in result.figures] == [
        "spending — category 'Uncategorized'"]


def test_a_read_grouped_by_what_it_was_filtered_on_has_no_list_in_it(registry):
    """A read narrowed on the same axis it groups by has one group, and that
    group is the narrowing.

    Written as a block it would be a single line naming the bucket the person
    put in their own filter, under an introduction promising a breakdown, with
    the same narrowing stated again beside it. It is the whole of what came
    back rather than a part of it, so the block has nothing to write a line per
    and the answer refuses instead of listing one thing.

    The precondition is asserted from the read: every figure it emits is cut
    by the read's own narrowing and by nothing further, so the refusal is on
    that ground rather than on a read that named no slice at all."""
    narrowed = ("query_ledger", {"entity": "aggregate", "metric": "spending",
                                 "group_by": "category",
                                 "filters": {"category": "Uncategorized",
                                             "merchant": "greenfield market"}})
    read = registry.call(*narrowed)
    assert read.ok, read.text
    cuts = [f["boundary"]["cut"] for f in read.figures
            if f["boundary"].get("cut")]
    assert cuts, "the read named no slice, so this proves nothing"
    for cut in cuts:
        assert cut == read.figures[0]["boundary"]["selected"], cut

    result = run("what did I spend on that there, by category?",
                 _script(_shape(("Here is what you spent, by category:"
                                 "{breakdown}", [("breakdown", render.ROWS)])),
                         narrowed, bind=_bind_the_read),
                 registry)
    assert not result.answered
    assert result.refusal == "wrong_kind", result.detail


def test_a_read_narrowed_to_one_account_is_still_a_list_of_its_months(registry):
    """And the answer that shape has to keep. A read narrowed to one account
    cuts the movements by month as well, and the months are slices of what came
    back rather than the narrowing itself — so they are the lines.

    What the account's own total would have been is not among them: the read
    was narrowed to that account, so it holds no list of accounts. Every line
    is true of the stated set, and what that set is reaches the person as the
    disclosure the machine places under the block."""
    from viva.tools import runner

    result = run("what moved on that account?",
                 _script(_shape(("Here is how the month went:{breakdown}",
                                 [("breakdown", render.ROWS)])),
                         ("query_ledger", {"entity": "transactions",
                                           "filters": {"account": "chk"}}),
                         bind=_bind_the_read),
                 registry)
    assert result.answered, result.detail
    lines = _lines_of(result.text)
    assert lines, result.text
    for line in lines:
        assert "Everyday Checking" not in line, line
    for fig in result.figures:
        # Cut by what narrowed the read and by the month besides, so the month
        # is the one axis past the narrowing and is what the line is named by.
        assert {c["kind"] for c in fig["boundary"]["cut"]} == {"account",
                                                              "period"}
        assert runner._line_of(fig)["kind"] == "period", fig["what"]
    assert moment("boundary_selected_account",
                  account=render.account({"account": "chk",
                                          "name": "Everyday Checking"},
                                         among=[])) in result.text


def test_a_month_of_a_windowed_read_declares_only_the_days_it_covers(registry):
    """The stated-figure path of the clipped month.

    A read asked for part of a month still groups by month, and the group's own
    calendar days are not what its figure was taken over: money measured from
    the 3rd onward, declared as the month, claims the first two days as well.
    Both statements are the read's own — the month it grouped by and the window
    it was asked for — so the slice is where they meet.

    A two-ended window hides this everywhere else: the month's edges collapse
    onto the read's own period axis, so the figure is no line of a block and
    the falsehood reaches a person only here, as the sentence saying what the
    number covers."""
    asked = ("query_ledger", {"entity": "transactions",
                              "filters": {"window": {"from": "2026-01-03",
                                                     "to": "2026-02-15"}}})
    result = run("what moved in that month?",
                 _script(_shape(("In that month, {moved} went through.",
                                 [("moved", "money", "net_movement",
                                   "period")])),
                         asked,
                         bind=lambda r: {"moved": {
                             "figure": _figure_id(r, "net movement in")}}),
                 registry)
    assert result.answered, result.detail
    # What the figure covers, said as the days it was taken over: the month
    # narrowed to the window, never the month's own first day.
    assert moment("boundary_selected_period",
                  period=render.period("2026-01-03",
                                       "2026-01-31")) in result.text
    assert "2026-01-01" not in result.text, result.text
    # And why this is the only path it reaches a person on here: a two-ended
    # window is the read's own period axis, so the month replaces it in the cut
    # and the figure is no line of a block.
    from viva.tools import runner

    assert runner._line_of(result.figures[0]) is None, result.figures[0]


def test_a_month_row_of_a_one_ended_window_is_named_by_the_days_it_covers(
        registry):
    """The rows path of the same clipped month, which the two-ended window
    hides.

    A `since` is a different axis from a period, so a month group of a read
    given one is cut by the read's narrowing and one axis more — which is what
    makes it a line — and the month reaches a person as that line's own name.
    Named by the calendar month it would tell them a span the figure was not
    taken over; named by where the month and the window meet it tells them what
    was measured."""
    asked = ("query_ledger", {"entity": "transactions",
                              "filters": {"account": "chk",
                                          "window": {"from": "2026-01-03"}}})
    result = run("how did the month go?",
                 _script(_shape(("Here is how the month went:{breakdown}",
                                 [("breakdown", render.ROWS)])),
                         asked, bind=_bind_the_read),
                 registry)
    assert result.answered, result.detail
    lines = _lines_of(result.text)
    assert lines, result.text
    for line in lines:
        assert line.startswith(str(render.period("2026-01-03", "2026-01-31"))), (
            line)
    assert "2026-01-01" not in result.text, result.text


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


# One clause introducing a list of what is held, so a block of balances or of
# holdings is asked for in words that fit it.
_PER_ACCOUNT_LIST = (("Here is what you are holding:{breakdown}",
                      [("breakdown", render.ROWS)]),)


def _lines_of(text: str) -> list:
    """The lines of a block whose rows are named for accounts and instruments,
    which is every line written as a name against a magnitude."""
    return [line for line in text.splitlines() if " — " in line]


def test_a_balance_per_account_is_a_block_that_makes_no_claim_of_its_own(
        several):
    """The balances read names one slice per figure, so it fills a block: one
    line per account, each written as the account it is.

    How much of what is held one of those figures covers is not said under the
    block. Said per line it would be one sentence under every line, all of them
    the same; said once for the block it would read as a claim about the
    answer, and the answer covered every account it listed. What says which
    account a line is is the line's own name."""
    result = run("list what I am holding",
                 _script(_shape(*_PER_ACCOUNT_LIST),
                         ("query_ledger", {"entity": "balances"}),
                         bind=_bind_the_read),
                 several)
    assert result.answered, result.detail
    assert len(_lines_of(result.text)) == 2, result.text
    assert len(result.figures) == 2
    for fig in result.figures:
        assert [c["kind"] for c in fig["boundary"]["cut"]] == ["account"]
    assert moment("boundary_accounts", counted=render.count(1),
                  held=render.count(2)) not in result.text


def _two_holdings_in_one_account():
    """One investment account holding two instruments, so a read of it comes
    back with two figures inside one account. Every value here is
    invented."""
    from viva.ledger.events import position_observed
    p = Provenance("doc-stat", 1, "r")
    return [
        account_opened("brk", "investment", "Brokerage", "USD", "2026-01-01"),
        document_captured("doc-stat", "stat.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        position_observed("brk", "ALPHA FUND", "10", "1500.00", "USD",
                          "2026-01-31", cost_basis="1200.00", provenance=p),
        position_observed("brk", "BETA FUND", "5", "500.00", "USD",
                          "2026-01-31", cost_basis="400.00", provenance=p),
    ]


def test_a_holding_is_in_an_account_rather_than_a_slice_of_one():
    """A balance is *of* its account and names that account as the slice it
    is. A holding is one of several things held *in* an account, and nothing a
    set may be narrowed by names an instrument — so a per-holding figure names
    no slice, and a block asked of that read refuses on the same ground as any
    other read that named none: there is nothing in it to write one line per.

    What follows from that, now that a sentence declares what set its number is
    over: a per-holding figure says it is not the whole of what a balance
    measures and names no slice it is, so there is no set for a sentence to
    declare that it answers. Every scope a hole can name refuses it. That is
    the honest reading of what the figure declares — a number over no nameable
    set — and it is the price of a holding not being a slice of anything the
    vocabulary names."""
    registry = default_registry(
        LedgerProjection(_two_holdings_in_one_account()))
    HOLDINGS = ("query_ledger", {"entity": "holdings"})
    held = registry.call(*HOLDINGS)
    assert held.figures
    # No figure of this read names a slice, so "named no slice" is the only
    # ground the block below can have refused on.
    assert all("cut" not in f["boundary"] for f in held.figures)

    blocked = run("list what I am holding",
                  _script(_shape(*_PER_ACCOUNT_LIST), HOLDINGS,
                          bind=_bind_the_read),
                  registry)
    assert not blocked.answered
    assert blocked.refusal == "wrong_kind", blocked.detail

    for over in shape_module.SCOPES:
        spoken = run("what is that one worth?",
                     _script(_shape(("That is worth {held}.",
                                     [("held", "money", "balance", over)])),
                             HOLDINGS,
                             bind=lambda r: {
                                 "held": {"figure": _figure_id(r,
                                                               "ALPHA "
                                                               "FUND")}}),
                     registry)
        assert not spoken.answered, over
        assert spoken.refusal == "wrong_scope", (over, spoken.detail)


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
                            (("x", render.MONEY, "spending", "whole"),
                             {"read": "r1"}),
                            (("x", render.COUNT, "count", "whole"),
                             {"read": "r1"}),
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
    shape = _shape(("You spent {total}.",
                   [("total", "money", "spending", "whole")]),
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


def test_net_worth_by_currency_is_one_homogeneous_block():
    """The currency-row view emits only net worth and preserves its gaps."""
    events = []
    for number, currency in enumerate(("USD", "EUR"), 1):
        account = f"account-{number}"
        document = f"document-{number}"
        provenance = Provenance(document, 1, "r")
        events.extend([
            account_opened(account, "depository", f"Account {number}",
                           currency, "2026-01-01"),
            document_captured(document, f"statement-{number}.pdf", 10,
                              "bank_statement", 0.9, "2026-02-01"),
            opening_balance_observed(account, "500.00", "2026-01-01",
                                     provenance),
            closing_balance_observed(account, "500.00", "2026-01-31",
                                     provenance),
        ])
    events.append(account_opened("unmeasured-card", "liability",
                                 "Unmeasured Card", "USD", "2026-01-01"))
    registry = default_registry(LedgerProjection(events))
    read = ("query_ledger", {"entity": "aggregate", "metric": "net_worth",
                              "view": "net_by_currency"})
    shape = _shape(("Your net worth by currency:{breakdown}",
                    [("breakdown", render.ROWS)]))

    result = run(
        "net worth by currency?",
        _script(shape, read,
                bind=lambda rows: {"breakdown": {"read": rows[-1]["id"]}}),
        registry)

    assert result.answered, result.detail
    lines = result.text.splitlines()
    assert any(line.startswith("USD — USD 500.00") for line in lines)
    assert any(line.startswith("EUR — EUR 500.00") for line in lines)
    assert {figure["quantity"] for figure in result.figures} == {
        quantity.NET_WORTH}
    assert "Unmeasured Card" in result.text
    assert "unmeasured-card" not in result.text
