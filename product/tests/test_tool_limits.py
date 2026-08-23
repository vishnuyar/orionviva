"""Tool limits contracts."""

from _tool_test_support import *

# ------------------------------------------------------- what a result costs

# The counterparties this ledger spends at — a pool a person could plausibly
# have over a year, cycled through, so that grouping by counterparty produces
# far more groups than one read may name. Every one is synthetic.
COUNTERPARTIES = [f"COUNTERPARTY {chr(65 + i // 26)}{chr(65 + i % 26)} DESCRIPTOR"
                  for i in range(60)]


def _ledger(accounts=6, months=12, per_month=3, docs=12, actions=0):
    """The read tools over a ledger a person could actually have."""
    return default_registry(LedgerProjection(
        _ledger_events(accounts, months, per_month, docs, actions)))


def _ledger_events(accounts=6, months=12, per_month=3, docs=12, actions=0):
    """A ledger built through the real event constructors, at a shape a person
    could actually have. Every value in it is synthetic."""
    evs, p = [], _p("doc-0000")
    for d in range(docs):
        evs.append(document_captured(f"doc-{d:04d}", f"s{d}.pdf", 10,
                                     "bank_statement", 0.9, "2026-02-01"))
    for a in range(accounts):
        evs.append(account_opened(f"acct{a}", "depository", f"Account {a}",
                                  "USD", "2025-01-01"))
        evs.append(opening_balance_observed(f"acct{a}", "1000.00",
                                            "2025-01-01", p))
        for m in range(1, months + 1):
            for d in range(per_month):
                evs.append(simple_transaction(
                    f"acct{a}", "-12.34",
                    COUNTERPARTIES[(a * 31 + m * 7 + d) % len(COUNTERPARTIES)],
                    f"2025-{m:02d}-{(d % 28) + 1:02d}", provenance=p))
    for i in range(actions):
        evs.append(agent_acted("enrich", "enrich", f"target-{i}", "done",
                               "2026-02-03", calls=1))
    return evs


def _payload(registry, tool, args):
    import json
    result = registry.call(tool, args)
    assert result.ok, result.text
    return len(json.dumps(result.to_dict()))


def test_what_a_read_costs_does_not_grow_with_the_ledger():
    """The defect that failed the first verification: a summary meant to shrink
    the payload carried one composite movement key per matching movement, on
    each of its figures, and grew instead. The guard has to scale its input or
    it measures a constant — this one holds the accounts and months fixed and
    multiplies the movements by ten."""
    from viva.tools.envelope import PAYLOAD_TARGET

    small = _payload(_ledger(per_month=3), "query_ledger",
                     {"entity": "transactions"})
    large = _payload(_ledger(per_month=30), "query_ledger",
                     {"entity": "transactions"})
    assert large < small * 1.2, (
        f"the summary grew from {small} to {large} when only the movement "
        "count changed; it is carrying the movements")
    assert large < PAYLOAD_TARGET


# The tools whose arguments no schema can enumerate, against what bounds each
# one instead. `list_movements` is the one read allowed past the budget and is
# held by its own row cap; the other two take a value only a run can supply — a
# record id another read emitted, or the figures a turn has already established
# — and each answers about exactly one of them. Every entry is measured by
# `test_what_the_sweep_cannot_enumerate_is_bounded_some_other_way`, so leaving
# a tool out of the sweep costs a bound rather than nothing.
UNENUMERABLE = ("list_movements", "get_provenance", "compute")


def _every_declared_call(registry) -> list:
    """Every call the registry's own schemas allow, generated from them.

    A parameter's enum IS the set of values a model may send, so the argument
    space is read off the schema rather than kept as a list beside it: a
    grouping or an entity added to a tool enters this sweep by existing.
    Optional fields are enumerated present and absent, and a field with no enum
    names a value only this vault could supply, so it is left unset."""
    import itertools
    calls = []
    for schema in registry.schemas():
        if schema["name"] in UNENUMERABLE:
            continue
        params = schema["parameters"]
        required = set(params.get("required", ()))
        choices = []
        for name, spec in sorted(params.get("properties", {}).items()):
            if "enum" not in spec:
                continue
            values = [{name: v} for v in spec["enum"]]
            if name not in required:
                values.append({})
            choices.append(values)
        for combination in itertools.product(*choices):
            args: dict = {}
            for part in combination:
                args.update(part)
            if required <= set(args):
                calls.append((schema["name"], args))
    return calls


def test_the_sweep_reaches_every_tool_or_says_which_it_does_not():
    """Every tool is either swept over its whole declared argument space or
    named in `UNENUMERABLE`, so what sits outside the sweep is written down
    rather than implied. A name in `UNENUMERABLE` that no tool answers to is a
    guard pointing at nothing, and fails here too."""
    registry = _ledger()
    named = {schema["name"] for schema in registry.schemas()}
    swept = {tool for tool, _ in _every_declared_call(registry)}

    assert set(UNENUMERABLE) <= named, sorted(set(UNENUMERABLE) - named)
    assert swept | set(UNENUMERABLE) == named, (
        "not swept and not declared unenumerable: "
        + str(sorted(named - swept - set(UNENUMERABLE))))


def test_what_the_sweep_cannot_enumerate_is_bounded_some_other_way():
    """Every name in `UNENUMERABLE` has a bound of its own, measured here
    against the largest input this vault can hand it: the capped read on every
    movement it holds, and the two run-supplied tools on a value a read actually
    emitted. Naming a tool unenumerable is what removes it from the budget
    sweep, so a tool added to the list with nothing measuring it fails here."""
    import json

    from viva.tools.envelope import PAYLOAD_TARGET
    from viva.tools.ledger_tools import MAX_ROWS

    registry = _ledger(per_month=30, docs=720)
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    record = next(iter(book.values()))["record_ids"][0]
    measured = {
        "list_movements": registry.call("list_movements",
                                        {"filters": {"account": "acct0"}}),
        "get_provenance": registry.call("get_provenance", {"record_id": record}),
        "compute": registry.call(
            "compute", {"expression": "a", "inputs": {"a": "f1"}}, figures=book),
    }
    assert set(measured) == set(UNENUMERABLE), (
        "an unenumerable tool with nothing measuring it: "
        + str(sorted(set(UNENUMERABLE) - set(measured))))

    # Two bounds, and the wider one comes first: the whole ledger is not a
    # listing at all, and the widest listing there is stops at the row cap.
    assert not registry.call("list_movements", {}).ok
    rows = measured["list_movements"]
    assert rows.ok, rows.text
    assert len(rows.data["movements"]) <= MAX_ROWS
    assert rows.data["total"] > MAX_ROWS, "the fixture never reaches the cap"
    for tool in ("get_provenance", "compute"):
        result = measured[tool]
        assert result.ok, result.text
        assert len(json.dumps(result.to_dict())) <= PAYLOAD_TARGET, tool


def test_every_declared_call_answers_or_refuses_and_never_raises():
    """The read boundary's own contract, asserted over the argument space
    rather than over a sample: every call the schemas allow comes back as an
    envelope — an answer carrying the sentence a model reads, or a refusal
    carrying the machine tag that says which refusal it was. A tool that raises
    instead ends the turn with no sentence at all."""
    registry = _ledger()
    for tool, args in _every_declared_call(registry):
        result = registry.call(tool, args)
        if result.ok:
            assert result.text, f"{tool} {args} answered with no sentence"
        else:
            assert result.refusal, f"{tool} {args} refused with no machine tag"


def test_every_figure_the_argument_space_emits_matches_its_own_declaration():
    """Every figure the declared argument space emits names something, measures
    a known quantity, and agrees with itself: an amount of money states the
    currency it is in, and a number of things states none. Read over the whole
    space, so a grouping or an entity emitting a figure of a new kind cannot
    arrive disagreeing with its own declaration."""
    from viva import quantity
    from viva.render import COUNT, MONEY, QUANTITY_OF_TYPE

    registry = _ledger()
    seen = 0
    for tool, args in _every_declared_call(registry):
        for fig in registry.call(tool, args).figures:
            seen += 1
            assert fig["what"], f"{tool} {args} emitted a figure naming nothing"
            assert fig["quantity"] in quantity.MEASURES, (tool, args, fig)
            if fig["quantity"] in QUANTITY_OF_TYPE[MONEY]:
                assert fig["currency"], (tool, args, fig["what"])
            if fig["quantity"] in QUANTITY_OF_TYPE[COUNT]:
                assert not fig["currency"], (tool, args, fig["what"])
    assert seen, "the sweep emitted no figures to check"


def test_no_uncapped_read_exceeds_what_a_result_may_cost():
    """Every result is resent in full on every model call for the rest of the
    turn, so one oversized read is paid for as many times as the turn has left
    to run.

    What this proves: every combination of the enumerated arguments — each
    entity, each metric, each grouping, each transparency topic, present and
    absent — is inside the budget, generated from the schemas rather than
    listed here, so a read that fits under one grouping and not under another
    cannot pass by being absent from a list. What it does not reach: the
    parameters no enum bounds (filters, windows, accounts, record ids), and the
    three tools named in `UNENUMERABLE`."""
    import json

    from viva.tools.envelope import PAYLOAD_TARGET

    registry = _ledger(per_month=30, docs=720, actions=1000)
    calls = _every_declared_call(registry)
    assert len(calls) > 10, "the argument space collapsed to a handful of calls"
    for tool, args in calls:
        result = registry.call(tool, args)
        size = len(json.dumps(result.to_dict()))
        assert size <= PAYLOAD_TARGET, (
            f"{tool} {args} returned {size} characters, over {PAYLOAD_TARGET}")


def test_the_groups_a_capped_read_names_are_the_largest_ones():
    """Which groups a cap keeps is the honest half of capping.

    Naming ten groups and caveating away the rest is a true sentence whichever
    ten are named, so nothing about the payload's size can catch a read that
    keeps the smallest. What makes the cap answerable is that the money it
    names is the money there is most of, and that two reads of one ledger name
    the same ten."""
    proj = LedgerProjection(_ledger_events(per_month=30))
    result = default_registry(proj).call("query_ledger",
                                         {"entity": "aggregate",
                                          "metric": "spending",
                                          "group_by": "merchant"})
    everything, _ = ledger_tools._spending_rows(proj, {}, "merchant")
    named = {k: Decimal(v) for k, v in result.data["by_group"].items()}
    dropped = {k: v for k, v in everything.items() if k not in named}
    assert named and dropped
    assert min(named.values()) >= max(dropped.values())


def test_the_groups_a_cap_keeps_are_the_same_ones_on_every_read():
    """Ordered by magnitude, and ties broken by name — so a read repeated
    against an unchanged ledger names the same groups, and a person who asks
    twice is not told about two different sets of counterparties."""
    sized = {f"counterparty {chr(97 + i)}": Decimal(i) for i in range(30)}
    named, tail = ledger_tools._largest_groups(sized)
    assert len(named) == ledger_tools.MAX_GROUPS
    assert set(named) == set(sorted(sized, key=sized.get,
                                    reverse=True)[:ledger_tools.MAX_GROUPS])
    assert tail["count"] == len(sized) - len(named)
    assert tail["total"] == sum(v for k, v in sized.items() if k not in named)

    # All one size: nothing but the name can decide, and the name does — not
    # the order they happen to have been folded in.
    tied = {f"counterparty {chr(97 + i)}": Decimal("10")
            for i in reversed(range(30))}
    kept, _ = ledger_tools._largest_groups(tied)
    assert list(kept) == sorted(tied)[:ledger_tools.MAX_GROUPS]


def test_a_grouped_read_names_the_largest_and_caveats_the_tail_it_dropped():
    """A grouping is as wide as the vault's own vocabulary — by counterparty,
    the group count is the counterparty count — so a read that named every
    group would grow with the ledger. It names the largest, and what it did not
    name rides a caveat: the one thing a result carries that has an identity, can
    be placed in a sentence, and cannot be dropped from an answer that states a
    figure it sits behind. A coverage line would say it where nothing could
    speak it."""
    registry = _ledger(per_month=30)
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending",
                                            "group_by": "merchant"})
    assert result.ok
    groups = result.data["groups"]
    assert groups["total"] > ledger_tools.MAX_GROUPS
    assert groups["named"] == ledger_tools.MAX_GROUPS
    assert len(result.data["by_group"]) == ledger_tools.MAX_GROUPS
    dropped = groups["total"] - groups["named"]
    assert any(f"{dropped} smaller group(s)" in c for c in result.caveats)
    # The total is over everything counted, capped or not: what the cap dropped
    # is missing from the named groups, never from the sum.
    assert (sum(Decimal(v) for v in result.data["by_group"].values())
            < Decimal(result.data["total"]))


def test_the_row_cap_is_the_thing_that_bounds_a_detailed_read():
    """Not the announcement — the cap itself. Without it this read returns the
    whole ledger, which is the shape the whole cycle exists to end."""
    registry = _ledger(per_month=30)
    result = registry.call("list_movements", {"filters": {"account": "acct0"}})
    assert result.data["total"] > ledger_tools.MAX_ROWS
    assert result.data["shown"] == ledger_tools.MAX_ROWS
    assert len(result.data["movements"]) == ledger_tools.MAX_ROWS
    # One figure per row shown, plus the one count over the whole matching set,
    # which is what says how many the cap left out.
    assert len(result.figures) == ledger_tools.MAX_ROWS + 1


def test_a_summary_stands_on_the_documents_not_on_every_movement():
    """What a total rests on is the statements that attest the period. Naming
    every movement key instead is both a weaker claim to make and the shape
    that made this read grow; the individual keys belong to the read that
    returns individual rows."""
    registry = _ledger(per_month=30)
    summary = registry.call("query_ledger", {"entity": "transactions"})
    rows = registry.call("list_movements", {"filters": {"account": "acct0"}})
    keys = {r["record_id"] for r in rows.data["movements"]}
    assert keys and not (keys & set(summary.record_ids))
    assert all(r.startswith("doc-") or r.startswith("acct")
               for r in summary.record_ids)
    assert keys <= set(rows.record_ids)


def test_a_figures_records_do_not_travel_to_the_model():
    """The model cites an id; the runner resolves the records. Sending them
    would repeat a document id once per figure per result, on every model call
    for the rest of the turn — and the model could not use them if it had
    them."""
    registry = _ledger()
    result = registry.call("check_completeness", {})
    assert all(f["record_ids"] for f in result.figures)
    stated = result.to_dict()["figures"]
    assert all("record_ids" not in f for f in stated)
    assert all(f["records"] > 0 for f in stated)
    assert result.to_dict()["records"] == len(result.record_ids)


# -------------------------------------------------------------- the two reads

def test_a_day_is_said_beside_the_figure_it_is_the_day_of(registry):
    """A day is bound from the `dated` of a figure its own clause states, and
    from nothing else.

    A day is written with no declaration still: what fills a date hole is one
    of this run's own days rather than anything the delivery wrote. What it may
    no longer be is a day belonging to some other number of the turn — that day
    is real, and beside a figure it is not the day of it is the opposite of the
    answer.

    So a clause that states a dated figure says its day, and the same day put
    in a clause that states no figure is refused. `check_completeness` emits
    each account's as-of date as a figure whose value IS a date; those figures
    fill no hole, so they are in no clause, so their days can reach nobody. The
    loss is taken on purpose."""
    dated = _one_figure(registry, "check_completeness", {})
    fig = next(f for f in dated.values() if "good as of" in f["what"])
    assert fig["value"] == "2026-01-31"

    alone = _shape(("Its evidence runs to {when}.", [("when", "date")]))
    orphan = run("how current is it?",
                 _script(alone, ("check_completeness", {}),
                         bind=lambda results: {"when": {"date": "2026-01-31"}}),
                 registry)
    assert not orphan.answered and orphan.refusal == "unfounded_date"

    beside = _shape(("It stood at {total} as of {when}.",
                     [("total", "money", "balance", "account"),
                      ("when", "date")]))

    def bind_to(iso):
        return lambda results: {"when": {"date": iso},
                                "total": {"figure": _fig(results, "balance")}}

    said = run("how current is it?",
               _script(beside, ("query_ledger",
                                {"entity": "balances",
                                 "filters": {"account": "chk"}}),
                       bind=bind_to("2026-01-31")), registry)
    assert said.answered, said.detail
    assert "2026-01-31" in said.text

    result = run("how current is it?",
                 _script(beside, ("query_ledger",
                                  {"entity": "balances",
                                   "filters": {"account": "chk"}}),
                         bind=bind_to("2019-03-04")), registry)
    assert not result.answered and result.refusal == "unfounded_date"


def test_todays_date_cannot_be_said_beside_a_figure_months_older(registry):
    """The day a read stamped on its own totals is not the day of every number
    that read emitted.

    The net-worth read holds its currency totals good as of the day they were
    asked for, and dates each account's line by the evidence under it — so one
    result carries today and a day months older, both true, of different
    numbers. A sentence stating the older figure and saying today beside it is
    made of two real things and says something false, and the clause is what
    tells them apart."""
    read = registry.call("query_ledger", {"entity": "aggregate",
                                          "metric": "net_worth"})
    today = next(f["dated"] for f in read.figures if "net in" in f["what"])
    stale = next(f["dated"] for f in read.figures if "part of net worth"
                 in f["what"])
    assert today > stale, "the fixture no longer dates a line before its total"

    shape = _shape(("That account is worth {amount}, as of {when}.",
                    [("amount", "money", "balance", "account"),
                     ("when", "date")]))

    def bind_to(iso):
        return lambda results: {"when": {"date": iso},
                                "amount": {"figure": _fig(results,
                                                          "part of net worth")}}

    asked = ("query_ledger", {"entity": "aggregate", "metric": "net_worth"})
    said = run("how much is in there?",
               _script(shape, asked, bind=bind_to(stale)), registry)
    assert said.answered, said.detail
    assert stale in said.text

    result = run("how much is in there?",
                 _script(shape, asked, bind=bind_to(today)), registry)
    assert not result.answered and result.refusal == "unfounded_date", (
        result.detail)


def test_a_page_of_rows_can_be_written_without_declaring_every_date(registry):
    """A detailed read returns rows, and writing a row means writing its date.
    The read emits a figure per movement carrying that movement's own day, so
    an answer stating those figures writes their days and declares none of
    them.

    Each day is said in the clause that states the movement it belongs to,
    which is what makes two days in one answer two facts rather than a pair
    that could be exchanged.

    Only the dates are written here. A description is a statement's own words
    and may carry digits of its own, which no read licenses; a listing answer
    that writes one is refused."""
    shape = _shape(("One fell on {first}, worth {first_amount}.",
                    [("first", "date"),
                     ("first_amount", "money", "movement", "whole")]),
                   ("Another on {last}, worth {last_amount}.",
                    [("last", "date"),
                     ("last_amount", "money", "movement", "whole")]))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if not done:
            return {"tool": "list_movements",
                    "args": {"filters": {"merchant": "greenfield market"}}}
        rows = done[0]["data"]["movements"]
        assert len(rows) > 1, "the fixture no longer returns several rows"
        moved = [f for f in done[0]["figures"] if f.get("dated")]
        return {"bindings": {"first": {"date": rows[0]["date"]},
                             "first_amount": {"figure": moved[0]["id"]},
                             "last": {"date": rows[-1]["date"]},
                             "last_amount": {"figure": moved[-1]["id"]}}}
    spoken = run("when did I shop there?", planner, registry)
    assert spoken.answered, spoken.detail
    assert "2026-01-05" in spoken.text and "2026-01-20" in spoken.text


def test_a_date_a_tool_echoed_from_its_own_arguments_is_not_thereby_sayable(registry):
    """A date a tool wrote into its own prose is not thereby sayable.

    A read that reports the `since` it was given writes that date into its own
    sentence, so dates are held out of the prose pool and the date rule alone
    decides whether one may be said."""
    echoed = registry.call("get_transparency",
                           {"topic": "calls_spent", "since": "2019-03-04"})
    assert "2019-03-04" in echoed.text, (
        "the fixture no longer echoes the caller's date into the tool's prose")

    shape = _shape(("Nothing since {when}.", [("when", "date")]))
    result = run("what have you spent?",
                 _script(shape,
                         ("get_transparency", {"topic": "calls_spent",
                                               "since": "2019-03-04"}),
                         bind=lambda r: {"when": {"date": "2019-03-04"}}),
                 registry)
    assert not result.answered and result.refusal == "unfounded_date"


def test_a_detailed_read_refuses_to_dump_the_whole_ledger(registry):
    """Whether the person asked to see rows is the model's judgment; that a
    read with no filter at all answers no question is not, so the code makes it
    inexpressible and names what would narrow it."""
    result = registry.call("list_movements", {"filters": {}})
    assert not result.ok and result.refusal == "too_broad"
    assert set(result.data["narrowing_filters"]) >= {"account", "category",
                                                     "merchant", "tag",
                                                     "window"}
    assert registry.call("list_movements",
                         {"filters": {"account": "chk"}}).ok


def test_the_detailed_read_declares_in_its_schema_that_it_takes_filters(registry):
    """A call naming no filters at all is refused where the arguments are
    validated, not after the read has been entered.

    A schema in which every field is optional says an empty call is well
    formed, and the model reads the schema before it calls. So the requirement
    is in the schema the model is shown, and the refusal names the field rather
    than the read's own narrowing rule."""
    result = registry.call("list_movements", {})
    assert not result.ok and result.refusal == "invalid_arguments"
    assert "filters" in result.text
    assert "required" in ledger_tools.LIST_MOVEMENTS_PARAMS
    schemas = {s["name"]: s for s in registry.schemas()}
    assert schemas["list_movements"]["parameters"]["required"] == ["filters"]


def test_a_capped_read_says_how_many_it_did_not_show(monkeypatch, registry):
    """A capped read says so in its own sentence, not only in a field.

    The sentence carries how many of how many were shown, in that order, and
    which filters reach the rest."""
    from viva.tools import ledger_movements
    monkeypatch.setattr(ledger_movements, "MAX_ROWS", 1)
    result = registry.call("list_movements", {"filters": {"account": "chk"}})
    assert result.ok
    shown, total = result.data["shown"], result.data["total"]
    assert (shown, total) == (1, 3)
    said = result.text
    assert said.index(str(shown)) < said.index(str(total)), (
        "the sentence must say how many it showed, then how many there were")
    assert str(total) in said and "Narrow by" in said
    for name in ledger_tools.NARROWING:
        assert name in said, f"the sentence does not say it can narrow by {name}"
    # And the same sentence is what a model actually reads back.
    assert result.coverage == said


def test_the_transactions_read_returns_totals_and_no_rows(registry):
    """The read that returned a hundred and fifty thousand characters now
    answers in totals. Every one of them is a figure; none of the movements
    themselves comes back."""
    import json

    result = registry.call("query_ledger", {"entity": "transactions"})
    assert result.ok
    payload = json.dumps(result.to_dict())
    assert "transactions" not in result.data and "movements" not in result.data
    assert {"count", "money_in", "money_out", "net"} <= set(result.data)
    described = {f["what"] for f in result.figures}
    assert any("money in" in w for w in described)
    assert any("net movement" in w for w in described)
    assert len(payload) < 4000


def test_a_charge_on_a_card_is_money_out_of_the_summary():
    """The transactions summary reads direction off the account's kind, not off
    the posting's sign. A purchase on a liability is recorded positive — what is
    owed grew — and it is money gone, so a summary reading the sign alone gives
    every card purchase the right magnitude, the right records and the right
    grade under a false description of what it measures."""
    events = [
        account_opened("card", "liability", "Signature Card", "USD",
                       "2026-01-01", institution="Meridian Cards"),
        document_captured("doc-card", "card.pdf", 100, "card_statement", 0.9,
                          "2026-02-01"),
        simple_transaction("card", "500.00", "CITY GYM", "2026-01-08",
                           provenance=_p("doc-card")),
    ]
    result = default_registry(LedgerProjection(events)).call(
        "query_ledger", {"entity": "transactions"})
    assert result.ok, result.text
    assert result.data["money_out"] == "500.00"
    assert result.data["money_in"] == "0"
    assert result.data["net"] == "-500.00"
    of = {f["what"]: f["value"] for f in result.figures}
    assert of["money out over these movements"] == "500.00"
    assert of["money in over these movements"] == "0"
    assert of["net movement over this set"] == "-500.00"
    assert of["net movement on card"] == "-500.00"


def test_a_row_and_its_figure_say_which_way_the_money_went():
    """The other half of the same rule, one read down.

    The summary was taught to read direction off the account's kind; a detailed
    read was not, and handed both its rows and its per-row figures the raw
    posting `amount`. On a liability a purchase is recorded positive — what is
    owed grew — so a model reading rows rather than totals could state a card
    charge as money received, with the right magnitude, the right record and
    the right grade under a false sign. Nothing else in the row contradicted
    it."""
    events = [
        account_opened("card", "liability", "Signature Card", "USD",
                       "2026-01-01", institution="Meridian Cards"),
        document_captured("doc-card", "card.pdf", 100, "card_statement", 0.9,
                          "2026-02-01"),
        simple_transaction("card", "500.00", "CITY GYM", "2026-01-08",
                           provenance=_p("doc-card")),
    ]
    result = default_registry(LedgerProjection(events)).call(
        "list_movements", {"filters": {"account": "card"}})
    assert result.ok, result.text

    (row,) = result.data["movements"]
    assert "amount" not in row, "the raw posting sign is not a row field"
    assert row["effect"] == "-500.00", "a charge on a card is money out"

    (fig,) = [f for f in result.figures if "CITY GYM" in f["what"]]
    assert fig["value"] == "-500.00", (
        "the figure an answer would state carries the raw sign")

    # And through the tool that exists to justify a figure. Two tools naming
    # one movement with the same `what` and the same quantity, disagreeing on
    # sign, would put both in the run's book with citable ids — and `compute`
    # would add them to zero.
    registry = default_registry(LedgerProjection(events))
    told = registry.call("list_movements", {"filters": {"account": "card"}})
    stood_on = registry.call("get_provenance",
                             {"record_id": told.data["movements"][0]["record_id"]})
    assert stood_on.ok, stood_on.text
    (justified,) = stood_on.figures
    (stated,) = [f for f in told.figures if f["quantity"] == quantity.MOVEMENT]
    assert justified["what"] == stated["what"]
    assert justified["value"] == stated["value"] == "-500.00"
    assert "amount" not in stood_on.data["movement"]
    assert "500.00" in stood_on.text and "-500.00" in stood_on.text, (
        "the sentence spells a number the figure disagrees with")


def test_a_subcategory_group_is_not_offered_as_a_category(registry):
    """A group key naming a pair is not a thing the vault holds.

    Grouping by subcategory keys each group by its parent and its own name, so
    two vocabularies stay apart. That key is not a category: `known_categories`
    does not hold it and the filter check refuses the same string on a
    follow-up, so minting it as a category entity would hand the answer a name
    to speak that no other read accepts. Naming the parent instead would be
    worse — the figure beside it measures one slice of that parent."""
    grouped = registry.call("query_ledger",
                            {"entity": "aggregate", "metric": "spending",
                             "group_by": "subcategory"})
    assert grouped.ok, grouped.text
    assert grouped.data["by_group"], "this fixture groups nothing"
    assert not [i for i in grouped.identifiers if i["kind"] == "category"], (
        "a pair was offered as a category the answer could name")

    # And the same read grouped by category does still name them, because
    # those keys are categories the vault holds.
    by_category = registry.call("query_ledger",
                                {"entity": "aggregate", "metric": "spending",
                                 "group_by": "category"})
    named = [i for i in by_category.identifiers if i["kind"] == "category"]
    assert named
    for item in named:
        assert registry.call(
            "query_ledger",
            {"entity": "aggregate", "metric": "spending",
             "filters": {"category": item["label"]}}).ok, item["label"]


def test_a_day_that_has_not_happened_is_not_a_day_a_read_answers_for(registry):
    """A balance carries forward, so a read answers for any day from the newest
    evidence up to today. Past today it would be projecting rather than
    carrying, and the date is worse than useless: `as_of` is echoed into the
    result's own date, which is what founds a day an answer may state — so an
    unbounded one lets a figure be spoken as good for a day nothing has
    happened on yet."""
    ahead = registry.call("query_ledger", {"entity": "aggregate",
                                           "metric": "net_worth",
                                           "as_of": "2030-01-01"})
    assert not ahead.ok
    assert ahead.refusal == "as_of_in_the_future"
    assert "2030-01-01" in ahead.text

    # Up to today still answers, which is what carrying forward means.
    behind = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "net_worth",
                                            "as_of": "2026-01-31"})
    assert behind.ok, behind.text
    assert behind.dated == "2026-01-31"


def test_an_average_over_a_summary_has_a_divisor_it_can_cite(registry):
    """A summary states how many months it spans, as a figure with an id. It
    carries no currency, so dividing an amount by it yields an amount: that is
    what makes a per-month average expressible at all, since arithmetic takes
    figure ids and never a number the answer supplies."""
    book = _one_figure(registry, "query_ledger", {"entity": "transactions"})
    months = next(f for f in book.values()
                  if "months these movements span" in f["what"])
    assert months["value"] == "1" and months["currency"] == ""
    spent = next(f["id"] for f in book.values()
                 if "money out over these movements" in f["what"])
    result = registry.call("compute",
                           {"expression": "out / months",
                            "inputs": {"out": spent, "months": months["id"]}},
                           figures=book)
    assert result.ok, result.text
    assert result.figures[0]["currency"] == "USD", (
        "money divided by a count is money")


def test_weakest_grade_orders_conflicted_below_unverified():
    assert weakest([VERIFIED, CORROBORATED]) == CORROBORATED
    assert weakest([CORROBORATED, "conflicted", UNVERIFIED]) == "conflicted"
    assert weakest([]) == ""


def test_a_grade_off_the_ladder_is_refused_where_it_is_written():
    """`weakest` ignores a grade it does not recognise, so an invented one
    would reach the person as a strength claim while counting for nothing in
    composition. The figure is where that is caught, not the answer."""
    plain = dict(quantity=quantity.COUNT)
    assert figure("1", "a thing", grade=CORROBORATED,
                  **plain)["grade"] == CORROBORATED
    assert figure("1", "a thing", **plain)["grade"] == ""
    with pytest.raises(ValueError):
        figure("1", "a thing", grade="pretty solid", **plain)
    # A kind that carries no grade still clears one rather than refusing it.
    assert figure("1", "a thing", kind="activity", grade=VERIFIED,
                  **plain)["grade"] == ""
