"""The tool registry: validated calls, vault-vocabulary refusals, the cited
envelope, and the runner's composition gate."""

import hashlib
from decimal import Decimal

import pytest

from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, merchant_categorized,
                         opening_balance_observed, simple_transaction,
                         transfer_linked)
from viva.ledger.events import (CORROBORATED, UNVERIFIED, VERIFIED,
                                agent_acted, document_captured,
                                merchant_enriched, movement_tagged,
                                position_observed, question_declined,
                                read_recorded, statement_held)
from viva.ledger.projection import movement_key
from viva.tools import default_registry, ledger_tools, run, weakest
from viva.tools.envelope import ToolResult, figure
from viva.tools.registry import PROMPTS, Registry, ToolSpec, descriptions
from vivacore import promptstore

# The registry's description file is a released prompt: its text may never
# change. To edit a description, add tools-v2.txt and point the registry at it.
FROZEN_DESCRIPTIONS = {"tools-v1": "484999eebb3697a4"}


def _p(doc, page=1):
    return Provenance(doc, page, "r")


def _figure(results, what):
    """The figure whose description contains `what`. A planner reads numbers
    from here, not out of a payload — that is the whole contract."""
    for result in results:
        for f in result.get("figures") or []:
            if what in f["what"]:
                return f
    raise AssertionError(f"no figure described as {what!r} was emitted")


def _fig(results, what):
    """Its id — the only handle an answer is given for a number."""
    return _figure(results, what)["id"]


def _statement_reply(opening, opening_date, closing, closing_date):
    """What a model returned for a statement, in the shape the parser reads.
    Coverage is derived from this, so a fixture without it holds no period —
    which is the honest outcome, not a gap in the fixture."""
    import json
    return json.dumps({"opening": {"amount_raw": opening, "date_raw": opening_date},
                       "closing": {"amount_raw": closing, "date_raw": closing_date},
                       "transactions": []})


def _events():
    evs = [
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01", institution="Northgate Bank",
                       account_number="XX4417", account_names=["R VANCE"]),
        account_opened("card", "liability", "Signature Card", "USD",
                       "2026-01-01", institution="Meridian Cards",
                       account_number="XX2291", account_names=["R VANCE"]),
        account_opened("brk", "investment", "Brokerage", "USD",
                       "2026-01-01", institution="Vantage Invest",
                       account_number="XX7734", account_names=["R VANCE"]),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        document_captured("doc-held", "held.pdf", 90, "bank_statement", 0.5,
                          "2026-02-01"),
        statement_held("doc-held", {}, None, "gap", "2026-02-01"),
        document_captured("doc-limbo", "limbo.pdf", 80, "bank_statement", 0.4,
                          "2026-02-01"),
        read_recorded("doc-jan", "model", "extract-v1", "text",
                      _statement_reply("1000.00", "2026-01-01",
                                       "600.00", "2026-01-31"),
                      0.0, 1, 1, True, None, "2026-02-01"),
        opening_balance_observed("chk", "1000.00", "2026-01-01", _p("doc-jan")),
        simple_transaction("chk", "-40.00", "GREENFIELD MARKET",
                           "2026-01-05", provenance=_p("doc-jan")),
        simple_transaction("chk", "-60.00", "GREENFIELD MARKET",
                           "2026-01-20", provenance=_p("doc-jan")),
        simple_transaction("chk", "-300.00", "CARD PAYMENT XX2291",
                           "2026-01-15", provenance=_p("doc-jan")),
        closing_balance_observed("chk", "600.00", "2026-01-31", _p("doc-jan", 6)),
        simple_transaction("card", "-300.00", "PAYMENT RECEIVED",
                           "2026-01-15", provenance=_p("doc-card")),
        position_observed("brk", "ALPHA FUND", "10", "1500.00", "USD",
                          "2026-01-31", cost_basis="1200.00",
                          provenance=_p("doc-brk")),
        merchant_enriched("greenfield market", "groceries",
                          subcategory="supermarket", occurred_at="2026-02-02"),
        agent_acted("enrich_unknown", "enrich", "brands", "done",
                    "2026-02-03", calls=2),
        question_declined("q-1", "nature", "2026-02-03", amount="300.00"),
    ]
    a = movement_key("doc-jan", "chk", "2026-01-15", Decimal("-300.00"),
                     "CARD PAYMENT XX2291", 0)
    b = movement_key("doc-card", "card", "2026-01-15", Decimal("-300.00"),
                     "PAYMENT RECEIVED", 0)
    evs.append(transfer_linked(a, b, VERIFIED, {"decided_by": "test"},
                               "2026-02-04", by="human"))
    key = movement_key("doc-jan", "chk", "2026-01-20", Decimal("-60.00"),
                       "GREENFIELD MARKET", 0)
    evs.append(movement_tagged(key, ["pantry"], "2026-02-05"))
    return evs


@pytest.fixture()
def proj():
    return LedgerProjection(_events())


@pytest.fixture()
def registry(proj):
    return default_registry(proj)


# ------------------------------------------------------------- the contract

def test_descriptions_are_a_frozen_prompt_file():
    """Model-facing tool text lives in a versioned prompt file, never code,
    and a released version's text never changes."""
    for version_id, pinned in FROZEN_DESCRIPTIONS.items():
        text = promptstore.load(PROMPTS, version_id)
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        assert digest == pinned, (
            f"{version_id}.txt changed — a released description file is "
            "immutable; add a new version file instead")
    named, version = descriptions("tools-v1")
    assert version == "tools-v1"
    assert set(named) >= {"query_ledger", "check_completeness",
                          "get_provenance", "get_transparency", "compute"}


def test_every_registered_tool_is_described(registry):
    described = {s["name"] for s in registry.schemas()}
    assert described == set(registry.names())
    assert all(s["description"] for s in registry.schemas())


def test_every_declared_array_says_what_it_holds(registry):
    """A provider validates the tool payload before it reads the question, and
    an array that does not declare its items is rejected there — the whole
    conversation dies on a schema, not on anything the model did. An object
    with no properties is deliberate (an open map of caller-named keys); an
    array with no items never is."""
    from viva.speak import _final_schema

    offenders: list[str] = []

    def walk(tool: str, node, path: str) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "array" and "items" not in node:
            offenders.append(f"{tool}.{path}" if path else tool)
        for name, child in (node.get("properties") or {}).items():
            walk(tool, child, f"{path}.{name}" if path else name)
        walk(tool, node.get("items"), f"{path}[]")

    for schema in registry.schemas() + [_final_schema()]:
        walk(schema["name"], schema["parameters"], "")

    assert not offenders, (
        f"{offenders} declare an array without items; a strict provider "
        "refuses the entire tool payload over it")


def test_a_tool_without_a_description_cannot_register():
    registry = Registry()
    with pytest.raises(ValueError):
        registry.register(ToolSpec(name="mystery_tool",
                                   params={"type": "object", "properties": {}},
                                   fn=lambda args: None))


def test_unknown_tool_is_a_refusal_not_an_exception(registry):
    result = registry.call("move_money", {})
    assert not result.ok and result.refusal == "unknown_tool"
    assert "query_ledger" in result.data["known_tools"]


def test_schema_violations_refuse_and_name_the_problem(registry):
    assert registry.call("query_ledger", {}).refusal == "invalid_arguments"
    bad_enum = registry.call("query_ledger", {"entity": "wishes"})
    assert not bad_enum.ok and "balances" in bad_enum.text
    unknown_field = registry.call("query_ledger",
                                  {"entity": "balances", "speed": "fast"})
    assert not unknown_field.ok and "speed" in unknown_field.text


# ------------------------------------------------------------- query_ledger

def test_balances_match_the_projection_and_carry_grades(proj, registry):
    result = registry.call("query_ledger", {"entity": "balances"})
    assert result.ok
    # The amount and its grade are what the figures assert; the row carries
    # what a figure cannot — which account it is, and why its grade is that.
    figures = {f["what"]: f for f in result.figures}
    chk = figures["Everyday Checking — balance"]
    assert chk["value"] == str(proj.balance("chk").amount)
    assert chk["grade"] == CORROBORATED
    # The card has no closing statement, so the composite is only as strong
    # as its weakest part.
    assert figures["Signature Card — balance"]["grade"] == UNVERIFIED
    assert result.grade == UNVERIFIED
    assert "doc-jan" in result.record_ids
    rows = {r["record_id"]: r for r in result.data["balances"]}
    assert "amount" not in rows["chk"] and "grade" not in rows["chk"]
    assert rows["chk"]["explanation"]


def test_unknown_account_refusal_names_the_known_ones(registry):
    result = registry.call("query_ledger", {"entity": "balances",
                                            "filters": {"account": "mystery"}})
    assert not result.ok and result.refusal == "unknown_account"
    assert "chk" in result.data["known_accounts"]


def test_unknown_category_refusal_names_the_vocabulary(registry):
    result = registry.call("query_ledger",
                           {"entity": "transactions",
                            "filters": {"category": "unicorns"}})
    assert not result.ok and result.refusal == "unknown_category"
    assert "groceries" in result.data["known_categories"]


def test_transactions_filter_by_nature_window_and_tag(proj, registry):
    spending = registry.call("query_ledger",
                             {"entity": "transactions",
                              "filters": {"nature": "spending"}})
    assert spending.ok and spending.data["count"] == 2   # card payment linked out
    tagged = registry.call("query_ledger", {"entity": "transactions",
                                            "filters": {"tag": "pantry"}})
    assert tagged.data["count"] == 1
    assert "transactions" not in tagged.data       # a summary returns no rows
    rows = registry.call("list_movements", {"filters": {"tag": "pantry"}})
    assert rows.data["movements"][0]["amount"] == "-60.00"
    windowed = registry.call("query_ledger",
                             {"entity": "transactions",
                              "filters": {"window": {"to": "2026-01-10"}}})
    assert windowed.data["count"] == 1
    bad = registry.call("query_ledger",
                        {"entity": "transactions",
                         "filters": {"window": {"to": "soon"}}})
    assert not bad.ok and bad.refusal == "bad_date"


def test_aggregate_spending_matches_the_projection(proj, registry):
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending"})
    assert result.ok
    expected = {k: str(v) for k, v in proj.spending_by_category().items()}
    assert result.data["by_group"] == expected
    assert result.data["total"] == "100.00"    # the linked card payment is out
    assert "doc-jan" in result.record_ids


def test_aggregate_needs_a_metric(registry):
    result = registry.call("query_ledger", {"entity": "aggregate"})
    assert not result.ok and result.refusal == "missing_metric"


def test_income_refuses_a_window_rather_than_ignoring_it(registry):
    """A lifetime figure presented as the answer to a dated question is a
    wrong number; income refuses the filter instead."""
    result = registry.call("query_ledger",
                           {"entity": "aggregate", "metric": "income",
                            "filters": {"window": {"from": "2027-01-01"}}})
    assert not result.ok and result.refusal == "filter_unsupported"
    assert "currency" in result.data["supported_filters"]


def test_income_names_its_sources_and_says_it_is_lifetime(proj, registry):
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "income"})
    assert result.ok
    expected = {k: str(v) for k, v in proj.income_by_currency().items()}
    assert result.data["by_currency"] == expected
    assert any("lifetime" in c for c in result.caveats)


def test_filters_an_entity_would_ignore_are_refused(registry):
    """Accepted-and-dropped is the lie this test guards against: rows that
    are individually true still answer the wrong question."""
    by_category = registry.call("query_ledger",
                                {"entity": "balances",
                                 "filters": {"category": "groceries"}})
    assert not by_category.ok and by_category.refusal == "filter_unsupported"
    holdings = registry.call("query_ledger",
                             {"entity": "holdings",
                              "filters": {"tag": "pantry"}})
    assert not holdings.ok and holdings.refusal == "filter_unsupported"
    net_worth = registry.call("query_ledger",
                              {"entity": "aggregate", "metric": "net_worth",
                               "filters": {"account": "chk"}})
    assert not net_worth.ok and net_worth.refusal == "filter_unsupported"


def test_net_worth_point_comes_back_dated(registry):
    result = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "net_worth"})
    assert result.ok and result.data["metric"] == "net_worth"
    assert result.dated == result.data["point"]["as_of"]


def test_as_of_outside_net_worth_is_refused(registry):
    result = registry.call("query_ledger", {"entity": "balances",
                                            "as_of": "2026-01-15"})
    assert not result.ok and result.refusal == "as_of_unsupported"


def test_holdings_are_dated_measurements(registry):
    result = registry.call("query_ledger", {"entity": "holdings"})
    assert result.ok and result.data["count"] == 1
    row = result.data["holdings"][0]
    assert row["market_value"] == "1500.00" and row["as_of"] == "2026-01-31"
    assert any("never" in c and "price" in c for c in result.caveats)


# ------------------------------------------------- completeness and provenance

def test_completeness_counts_the_held_document(registry):
    result = registry.call("check_completeness")
    assert result.ok
    assert result.data["awaiting"] == 2      # one held, one captured in limbo
    assert result.data["holds"][0]["doc_id"] == "doc-held"
    assert any(a["account"] == "chk" and a["grade"] == CORROBORATED
               for a in result.data["accounts"])


def test_provenance_states_say_what_actually_happened(registry):
    """posted: in the ledger. held: read and set aside for review.
    captured: received, not yet processed. Each must report as itself."""
    held = registry.call("get_provenance", {"record_id": "doc-held"})
    assert held.ok and held.data["state"] == "held"
    captured = registry.call("get_provenance", {"record_id": "doc-limbo"})
    assert captured.ok and captured.data["state"] == "captured"


def test_provenance_answers_for_document_account_and_movement(proj, registry):
    doc = registry.call("get_provenance", {"record_id": "doc-jan"})
    assert doc.ok and doc.data["state"] == "posted"
    acct = registry.call("get_provenance", {"record_id": "chk"})
    assert acct.ok and acct.grade == CORROBORATED
    assert acct.provenance[0]["doc_id"] == "doc-jan"
    key = next(m.key for m in proj.movements() if m.amount == Decimal("-300.00")
               and m.account == "chk")
    move = registry.call("get_provenance", {"record_id": key})
    assert move.ok and move.data["movement"]["nature"] == "transfer"
    missing = registry.call("get_provenance", {"record_id": "nothing"})
    assert not missing.ok and missing.refusal == "unknown_record"


def test_transparency_reads_the_agent_journal(registry):
    activity = registry.call("get_transparency", {"topic": "agent_activity"})
    assert activity.ok and activity.data["count"] == 1
    calls = registry.call("get_transparency", {"topic": "calls_spent"})
    assert calls.ok and calls.data["calls"] == 2
    declined = registry.call("get_transparency",
                             {"topic": "declined_questions"})
    assert declined.ok and "q-1" in declined.data["declined"]


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
        f = figure(amount, f"a tenth {i}", grade=VERIFIED, currency="USD",
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
        f = figure("100.00", f"balance {i}", grade=VERIFIED, currency=currency,
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

    Overflow, an inexact division, a very long expression and a deeply nested
    one all come back as refusal envelopes."""
    for args, question in (
            ({"expression": "x * x",
              "inputs": {"x": {"stipulated": "1e999999999"}}}, "1e999999999"),
            ({"expression": "x / 7",
              "inputs": {"x": {"stipulated": "100"}}}, "100"),
            ({"expression": "+".join(["1"] * 1200), "inputs": {}}, ""),
            ({"expression": "1" + "*(1" * 400 + ")" * 400, "inputs": {}}, "")):
        result = registry.call("compute", args, figures={}, question=question)
        assert not result.ok and result.refusal in ("bad_expression",
                                                    "bad_input", "inexact")


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


# ------------------------------------------------------- what a result costs

def _ledger(accounts=6, months=12, per_month=3, docs=12, actions=0):
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
                    f"acct{a}", "-12.34", f"COUNTERPARTY {a}{m}{d} DESCRIPTOR",
                    f"2025-{m:02d}-{(d % 28) + 1:02d}", provenance=p))
    for i in range(actions):
        evs.append(agent_acted("enrich", "enrich", f"target-{i}", "done",
                               "2026-02-03", calls=1))
    return default_registry(LedgerProjection(evs))


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


def test_no_uncapped_read_exceeds_what_a_result_may_cost():
    """Every result is resent in full on every model call for the rest of the
    turn, so one oversized read is paid for as many times as the turn has left
    to run. `list_movements` is the one read allowed past this, and it is
    bounded by its own cap instead."""
    from viva.tools.envelope import PAYLOAD_TARGET

    registry = _ledger(per_month=30, docs=720, actions=1000)
    for tool, args in (
            ("query_ledger", {"entity": "transactions"}),
            ("query_ledger", {"entity": "balances"}),
            ("query_ledger", {"entity": "holdings"}),
            ("query_ledger", {"entity": "aggregate", "metric": "spending"}),
            ("query_ledger", {"entity": "aggregate", "metric": "income"}),
            ("query_ledger", {"entity": "aggregate", "metric": "net_worth"}),
            ("check_completeness", {}),
            ("get_transparency", {"topic": "agent_activity"}),
            ("get_transparency", {"topic": "calls_spent"}),
            ("get_transparency", {"topic": "declined_questions"})):
        size = _payload(registry, tool, args)
        assert size <= PAYLOAD_TARGET, (
            f"{tool} {args} returned {size} characters, over {PAYLOAD_TARGET}")


def test_the_row_cap_is_the_thing_that_bounds_a_detailed_read():
    """Not the announcement — the cap itself. Without it this read returns the
    whole ledger, which is the shape the whole cycle exists to end."""
    registry = _ledger(per_month=30)
    result = registry.call("list_movements", {"filters": {"account": "acct0"}})
    assert result.data["total"] > ledger_tools.MAX_ROWS
    assert result.data["shown"] == ledger_tools.MAX_ROWS
    assert len(result.data["movements"]) == ledger_tools.MAX_ROWS
    assert len(result.figures) == ledger_tools.MAX_ROWS


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

def test_a_date_a_figure_carries_is_still_a_date_and_must_be_declared(registry):
    """`check_completeness` emits each account's as-of date as a figure whose
    value IS a date. Citing that figure must not let the answer write the date
    — otherwise citing a figure becomes a way around declaring one, and the
    date rule stops being the only authority on dates."""
    dated = _one_figure(registry, "check_completeness", {})
    fig = next(f for f in dated.values() if "good as of" in f["what"])
    assert fig["value"] == "2026-01-31"

    def planner(context):
        if not context["results"]:
            return {"tool": "check_completeness", "args": {}}
        return {"answer": "Its evidence runs to 2026-01-31.",
                "figures": [{"id": _fig(context["results"], "good as of")}]}
    result = run("how current is it?", planner, registry)
    assert not result.answered and result.refusal == "undeclared_date"

    def declaring(context):
        if not context["results"]:
            return {"tool": "check_completeness", "args": {}}
        return {"answer": "Its evidence runs to 2026-01-31.",
                "figures": [{"id": _fig(context["results"], "good as of")}],
                "dates": [{"iso": "2026-01-31"}]}
    assert run("how current is it?", declaring, registry).answered


def test_a_date_a_tool_echoed_from_its_own_arguments_is_not_thereby_sayable(registry):
    """A date a tool wrote into its own prose is not thereby sayable.

    A read that reports the `since` it was given writes that date into its own
    sentence, so dates are held out of the prose pool and the date rule alone
    decides whether one may be said."""
    echoed = registry.call("get_transparency",
                           {"topic": "calls_spent", "since": "2019-03-04"})
    assert "2019-03-04" in echoed.text, (
        "the fixture no longer echoes the caller's date into the tool's prose")

    def planner(context):
        if not context["results"]:
            return {"tool": "get_transparency",
                    "args": {"topic": "calls_spent", "since": "2019-03-04"}}
        return {"answer": "Nothing since 2019-03-04.", "figures": []}
    result = run("what have you spent?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_figure"


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


def test_a_capped_read_says_how_many_it_did_not_show(monkeypatch, registry):
    """A capped read says so in its own sentence, not only in a field.

    The sentence carries how many of how many were shown, in that order, and
    which filters reach the rest."""
    monkeypatch.setattr(ledger_tools, "MAX_ROWS", 1)
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


def test_weakest_grade_orders_conflicted_below_unverified():
    assert weakest([VERIFIED, CORROBORATED]) == CORROBORATED
    assert weakest([CORROBORATED, "conflicted", UNVERIFIED]) == "conflicted"
    assert weakest([]) == ""


# -------------------------------------------------------------------- runner

def test_scripted_planner_produces_a_cited_answer(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        fig = _figure(context["results"], "balance")
        return {"answer": f"Your checking balance is USD {fig['value']}.",
                "figures": [{"id": fig["id"]}]}
    result = run("what is my checking balance?", planner, registry)
    assert result.answered and result.calls == 1
    assert result.grade == CORROBORATED
    assert "600.00" in result.text
    assert result.figures[0]["record_ids"]


def test_a_figure_id_the_run_never_produced_is_refused(registry):
    """The replacement for citing a record the run never read: a model can no
    longer name a record at all, only an id, and an id it made up matches
    nothing."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        return {"answer": "You have 600.00.", "figures": [{"id": "f99"}]}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unknown_figure"


def test_a_figure_id_in_the_prose_is_a_name_and_an_amount_is_not(registry):
    """A figure id in an answer's prose is a name; anything else is a quantity.

    Only an id this run stamped is read as a name. Digits attached to any other
    prefix are read as a number and must be answered for."""
    from viva.tools.runner import _tokens

    stamped = {"f1": {}, "f2": {}}
    assert _tokens("Figure f1 shows 600.00", stamped) == {"600.00"}
    assert _tokens("f1 and f2 both", stamped) == set()
    # Not stamped, so not a name: it is read, and will be answered for.
    assert _tokens("see f12", stamped) == {"12"}
    # Ordinary financial prose, with no space and no symbol.
    for written, expected in (("USD4500", "4500"), ("Rs45000", "45000"),
                              ("GBP1,250.00", "1250.00"),
                              ("USD600.00", "600.00")):
        assert _tokens(written, stamped) == {expected}, written
    # And a date-shaped invention still travels whole, never shedding parts.
    assert _tokens("x2026-01-31", stamped) == {"2026-01-31"}

    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        fig = _figure(context["results"], "balance")
        return {"answer": f"Figure {fig['id']} shows {fig['value']}, and your "
                          "card holds USD4500.",
                "figures": [{"id": fig["id"]}]}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_figure"
    assert "4500" in result.detail


def test_an_amount_may_not_be_inflated_around_a_figure_it_cites(registry):
    """The 5× error: citing a figure worth 600.00 and writing 1,600.00. Whole
    tokens, always — a cited value licenses itself and nothing that contains
    it."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        fig = _figure(context["results"], "balance")
        return {"answer": "Your balance is GBP1,600.00.",
                "figures": [{"id": fig["id"]}]}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_figure"


def test_a_number_in_a_payload_but_in_no_figure_cannot_be_said(registry):
    """Payload laundering, dead. A holding's cost basis rides in `data`; the
    read emits its market value as a figure and says nothing about what it
    cost, so the cost is machinery, not a claim, and the answer may not speak
    it however money-shaped it looks."""
    holdings = registry.call("query_ledger", {"entity": "holdings"})
    buried = holdings.data["holdings"][0]["cost_basis"]
    assert buried not in holdings.text and buried not in holdings.coverage
    assert all(buried != f["value"] for f in holdings.figures)

    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "holdings"}}
        return {"answer": f"You paid {buried} for it.", "figures": []}
    result = run("what did it cost?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_figure"


def test_a_number_a_tool_stated_in_words_may_be_said(registry):
    """The safety valve, and the reason ordinary language keeps working: a
    count a tool wrote into its own sentence is a claim it chose to make."""
    completeness = registry.call("check_completeness", {})
    assert "3 document(s) held" in completeness.text

    def planner(context):
        if not context["results"]:
            return {"tool": "check_completeness", "args": {}}
        return {"answer": "I hold 3 documents for you.", "figures": []}
    result = run("how many documents?", planner, registry)
    assert result.answered, result.text


def test_a_financial_figure_standing_on_no_record_is_refused(registry):
    """Arithmetic over nothing but literals produces a number resting on no
    document. It has an id, so it is citable — and it is refused anyway,
    because what a figure about money must stand on has not moved."""
    def planner(context):
        if not context["results"]:
            return {"tool": "compute",
                    "args": {"expression": "424242 + 0", "inputs": {}}}
        return {"answer": "That makes 424242.",
                "figures": [{"id": _fig(context["results"], "result of")}]}
    result = run("how much?", planner, registry)
    assert not result.answered and result.refusal == "uncited_figure"


def test_figure_ids_are_unique_across_tools_and_restart_each_turn(registry):
    seen = []

    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        if len(context["results"]) == 1:
            return {"tool": "check_completeness", "args": {}}
        seen.extend(f["id"] for r in context["results"]
                    for f in r["figures"])
        return {"answer": "Noted.", "figures": []}

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
    def planner(context):
        if not context["results"]:
            return {"tool": "check_completeness", "args": {}}
        return {"answer": "The 5000 you mentioned is well within reach.",
                "figures": [], "stipulated": [{"value": "5000",
                                               "as": "the trip"}]}
    result = run("could I afford a 3000 trip?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_stipulation"


def test_an_amount_the_person_did_say_may_be_said_back(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "check_completeness", "args": {}}
        return {"answer": "About the 3000 you mentioned — I can look at that.",
                "figures": [], "stipulated": [{"value": "3000",
                                               "as": "the trip"}]}
    result = run("could I afford a 3000 trip?", planner, registry)
    assert result.answered, result.text
    assert result.grade == ""          # nothing here is an evidence claim


def test_a_hypothetical_figure_carries_no_grade_and_sets_none(registry):
    """Arithmetic over a premise is answerable and is not evidence. It can be
    spoken; it cannot make an answer look verified."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        if len(context["results"]) == 1:
            return {"tool": "compute",
                    "args": {"expression": "have - trip",
                             "inputs": {"have": _fig(context["results"],
                                                     "balance"),
                                        "trip": {"stipulated": "250"}}}}
        left = _figure(context["results"], "result of")
        return {"answer": f"Supposing the 250 trip, {left['value']} would be "
                          "left — that rests on your figure, not on a "
                          "statement.",
                "figures": [{"id": left["id"]}],
                "stipulated": [{"value": "250", "as": "the trip"}]}
    result = run("could I afford a 250 trip?", planner, registry)
    assert result.answered, result.text
    assert result.figures[0]["kind"] == "hypothetical"
    assert result.figures[0]["grade"] == ""
    assert result.grade == ""


def test_a_supposition_does_not_wear_off_after_one_hop(registry):
    """The label has to survive being carried. If it only lasts one step, a
    number the person made up passes through arithmetic once and comes out
    inside a figure the product calls verified — which is the laundering
    figure identity was adopted to make impossible, arriving by a longer
    route."""
    book = _one_figure(registry, "query_ledger", {"entity": "balances"})
    balance = next(f["id"] for f in book.values()
                   if "Everyday Checking" in f["what"])
    other = next(f["id"] for f in book.values()
                 if "Signature Card" in f["what"])
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
    def planner(context):
        if not context["results"]:
            return {"tool": "get_transparency",
                    "args": {"topic": "agent_activity"}}
        if len(context["results"]) == 1:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances", "filters": {"account": "chk"}}}
        return {"answer": "I have taken 1 action; your balance is 600.00.",
                "figures": [{"id": _fig(context["results"], "unattended actions")},
                            {"id": _fig(context["results"], "balance")}]}
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

    from viva.tools.runner import _Ground, _check
    ground = _Ground()
    for i, (kind, grade) in enumerate([("financial", CORROBORATED),
                                       ("activity", "conflicted")], 1):
        fig = figure("1", "a thing", kind=kind, record_ids=["r"])
        fig.update(id=f"f{i}", grade=grade)      # a tool that graded carelessly
        ground.book[fig["id"]] = fig
    cited, problem = _check({"answer": "1", "figures": [{"id": "f1"},
                                                        {"id": "f2"}]}, ground)
    assert problem is None
    assert weakest(f["grade"] for f in cited
                   if f["kind"] in ("financial", "computed")) == CORROBORATED


def test_a_number_no_tool_returned_is_refused(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        return {"answer": "Your balance is about 9999.99.", "figures": []}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_figure"


def test_a_fabricated_number_cannot_ride_inside_a_seen_one(registry):
    """Numeric tokens match whole, never as substrings: '6' is not grounded
    by a result containing '600.00'."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        return {"answer": "You made 26 payments this month.", "figures": []}
    result = run("how many payments?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_figure"
    # '26' rides inside the dated '2026-01-31' as a substring; the refusal
    # proves tokens are matched whole, not by containment.


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
    """A category, tag, merchant or nature filter selects rows; it does not
    decide what the vault holds. A zero inside an attested period is money not
    spent, never evidence not held, and the two sentences are not
    interchangeable."""
    result = registry.call("query_ledger", {
        "entity": "aggregate", "metric": "spending",
        "filters": {"account": "chk", "nature": "transfer",
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
    """A boundary date the planner supplied is scope the tool reports back, not
    a number the planner invented, so the answer may say which period it read."""
    window = {"from": "2026-01-05", "to": "2026-01-20"}

    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger",
                    "args": {"entity": "aggregate", "metric": "spending",
                             "filters": {"window": window}}}
        total = context["results"][0]["data"]["total"]
        return {"answer": f"Between January 5, 2026 and January 20, 2026 you "
                          f"spent {total}.",
                "figures": [{"id": _fig(context["results"], "total spending")}],
                "dates": [{"iso": "2026-01-05"}, {"iso": "2026-01-20"}]}
    result = run("what did I spend then?", planner, registry)
    assert result.answered, result.text


def test_a_month_written_for_a_day_it_covers_is_accepted(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "transactions"}}
        return {"answer": "Everything I hold was recorded in January 2026.",
                "figures": [], "dates": [{"iso": "2026-01-05"}]}
    result = run("when?", planner, registry)
    assert result.answered, result.text


def test_a_period_a_read_is_attested_for_can_never_ground_a_figure(registry):
    """A period is scope, kept in its own pool, and that pool holds dates only.
    A spending aggregate names no row dates, so its period is the only place
    its boundaries appear — and a figure may not stand on one."""
    covers = registry.call("query_ledger", {"entity": "aggregate",
                                            "metric": "spending"}).covers
    edge = covers[0]["to"]

    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "aggregate",
                                                     "metric": "spending"}}
        return {"answer": f"The figure is {edge}.", "figures": [], "dates": []}
    result = run("?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_figure"

def test_a_date_outside_everything_read_is_refused(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "transactions"}}
        return {"answer": "Nothing to report.", "figures": [],
                "dates": [{"iso": "2019-12-31"}]}
    result = run("when?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_date"


def test_a_date_component_written_but_not_declared_says_which_date_it_was(registry):
    """A date left undeclared and a number invented outright are the same
    refusal to the gate and very different news to the person."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances",
                             "filters": {"account": "chk"}}}
        return {"answer": "You were fine on the 31st.",
                "figures": [], "dates": []}
    result = run("when?", planner, registry)
    assert not result.answered and result.refusal == "undeclared_date"
    assert "2026-01-31" in result.detail

def test_a_declared_date_licenses_its_own_parts_and_nothing_else(registry):
    """The accepted cost of licensing a date by its parts, stated so it is not
    rediscovered as a bug: a number equal to a component of a declared date
    passes. It is bounded by exact equality — an amount that merely begins with
    the year does not pass, and neither does one unrelated to any date. Nothing
    is removed from the text to achieve this; text deleted before the numbers
    are counted takes whatever else it overlaps with it."""
    def answer(sentence):
        def planner(context):
            if not context["results"]:
                return {"tool": "query_ledger",
                        "args": {"entity": "transactions"}}
            return {"answer": sentence, "figures": [],
                    "dates": [{"iso": "2026-01-05"}]}
        return run("how much?", planner, registry)

    assert answer("In January 2026 you spent 2026 dollars.").answered
    for invented in ("In January 2026 you spent 20261 dollars.",
                     "In January 2026 there were 120 charges.",
                     "In January 2026 you spent 4711 dollars."):
        result = answer(invented)
        assert not result.answered and result.refusal == "unfounded_figure"

def test_a_declared_date_that_is_not_a_date_refuses_rather_than_raising(registry):
    for bad in ("600.00", "2026-13-45", "", "2026-01-31 "):
        def planner(context, bad=bad):
            if not context["results"]:
                return {"tool": "query_ledger", "args": {"entity": "transactions"}}
            return {"answer": "Nothing to report.", "figures": [],
                    "dates": [{"iso": bad}]}
        result = run("when?", planner, registry)
        assert not result.answered and result.refusal == "unfounded_date", bad


def test_an_answer_has_no_way_to_name_a_record_at_all(registry):
    """This replaces the check that a figure citing an unread record is
    refused. That test guarded a rule the model could break; now it cannot
    reach the field. A cited figure is an id, and the records travel with the
    figure the tool emitted — so naming a record the run never read is not a
    thing an answer can express."""
    from viva.speak import FINAL_PARAMS

    entry = FINAL_PARAMS["properties"]["figures"]["items"]
    assert set(entry["properties"]) == {"id"}
    assert "record_ids" not in FINAL_PARAMS["properties"]


def test_the_call_budget_ends_in_one_closing_attempt_then_refuses(registry):
    """Exhaustion spends one more model call with only the terminator on the
    table, because a turn holding a grounded figure should deliver it rather
    than die beside it. If that closing reply reaches for a tool anyway, the
    turn refuses — and the planner is not asked again."""
    closings = []

    def planner(context):
        closings.append(bool(context["final_call"]))
        return {"tool": "check_completeness", "args": {}}
    result = run("loop forever", planner, registry, max_calls=3)
    assert not result.answered and result.refusal == "call_budget_exhausted"
    assert result.calls == 3
    assert closings == [False, False, False, True]


def test_an_answer_delivered_on_the_closing_call_passes_the_gate_normally(registry):
    def planner(context):
        if not context["final_call"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        return {"answer": "Your checking balance is 600.00.",
                "figures": [{"id": _fig(context["results"], "balance")}]}
    result = run("balance?", planner, registry, max_calls=2)
    assert result.answered and result.grade == CORROBORATED


def test_every_planner_context_says_how_many_calls_remain(registry):
    seen = []

    def planner(context):
        seen.append(context["calls_remaining"])
        if len(seen) < 3:
            return {"tool": "check_completeness", "args": {}}
        return {"answer": "Noted.", "figures": []}
    assert run("?", planner, registry, max_calls=4).answered
    assert seen == [4, 3, 2]


def test_a_refusal_result_flows_back_to_the_planner(registry):
    seen = {}
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances",
                             "filters": {"account": "mystery"}}}
        seen["refusal"] = context["results"][0]["refusal"]
        known = context["results"][0]["data"]["known_accounts"][0]
        if len(context["results"]) == 1:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": known}}}
        fig = _figure(context["results"], "balance")
        return {"answer": f"{fig['value']}.", "figures": [{"id": fig["id"]}]}
    result = run("balance of mystery?", planner, registry)
    assert seen["refusal"] == "unknown_account"
    assert result.answered and result.calls == 2


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


def test_a_moment_read_licenses_its_own_date_without_a_period(registry):
    """A balance carries a value-time and no period. Without the asserted-date
    path it could not say the date printed on its own statement."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances", "filters": {"account": "chk"}}}
        return {"answer": "As of 2026-01-31 you were fine.", "figures": [],
                "dates": [{"iso": "2026-01-31"}]}
    assert run("?", planner, registry).answered


def test_a_period_missing_an_end_licenses_nothing():
    """`covers` is data a tool sets, not a shape the gate can assume. A
    half-filled entry must not become a period that admits every date up to its
    other end."""
    registry = Registry()
    registry.register(ToolSpec(
        name="query_ledger", params={"type": "object", "properties": {}},
        fn=lambda args: ToolResult(
            tool="query_ledger", ok=True, data={"note": "no start"},
            covers=[{"account": "chk", "from": "", "to": "2026-12-31"}])))

    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {}}
        return {"answer": "Fine.", "figures": [], "dates": [{"iso": "1999-01-01"}]}
    result = run("?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_date"


def _two_year_projection():
    """A vault attested across a year boundary. A one-month fixture cannot tell
    a shape check from containment: every malformed date sorts outside one
    month, so both refuse and the test cannot say which mechanism fired."""
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           opening_balance_observed("chk", "1000.00", "2026-01-01", _p("d-a"))]
    evs += _statement_doc("d-a", "chk", "1000.00", "2026-01-01",
                          "900.00", "2026-12-31")
    evs += _statement_doc("d-b", "chk", "900.00", "2027-01-01",
                          "800.00", "2027-12-31")
    return LedgerProjection(evs)


def test_a_declared_date_the_gate_cannot_take_apart_refuses(registry):
    """The date library accepts forms this gate cannot split. Shape is checked
    first, so a value that would raise on the way to being licensed is refused.
    Driven against a vault wide enough that containment would admit them."""
    wide = default_registry(_two_year_projection())
    def planner_for(iso):
        def planner(context):
            if not context["results"]:
                return {"tool": "query_ledger",
                        "args": {"entity": "transactions"}}
            return {"answer": "Fine.", "figures": [], "dates": [{"iso": iso}]}
        return planner
    for iso in ("20260105", "2026-W01-1", "2026-02-30", "2026-1-5"):
        result = run("?", planner_for(iso), wide)
        assert not result.answered and result.refusal == "unfounded_date", iso
    # and the well-formed date inside the same period is admitted, so the
    # refusals above are the shape check and not the window
    assert run("?", planner_for("2026-06-15"), wide).answered


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
