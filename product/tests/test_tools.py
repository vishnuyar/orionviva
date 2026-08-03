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
                                statement_held)
from viva.ledger.projection import movement_key
from viva.tools import default_registry, run, weakest
from viva.tools.registry import PROMPTS, Registry, ToolSpec, descriptions
from vivacore import promptstore

# The registry's description file is a released prompt: its text may never
# change. To edit a description, add tools-v2.txt and point the registry at it.
FROZEN_DESCRIPTIONS = {"tools-v1": "484999eebb3697a4"}


def _p(doc, page=1):
    return Provenance(doc, page, "r")


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
    rows = {r["record_id"]: r for r in result.data["balances"]}
    assert rows["chk"]["amount"] == str(proj.balance("chk").amount)
    assert rows["chk"]["grade"] == CORROBORATED
    # The card has no closing statement, so the composite is only as strong
    # as its weakest part.
    assert rows["card"]["grade"] == UNVERIFIED
    assert result.grade == UNVERIFIED
    assert "doc-jan" in result.record_ids


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
    assert tagged.data["transactions"][0]["amount"] == "-60.00"
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

def test_compute_is_exact_and_inherits_the_weakest_grade(registry):
    result = registry.call("compute", {
        "expression": "a + b",
        "inputs": {"a": "0.10", "b": "0.20"},
        "grades": {"a": VERIFIED, "b": UNVERIFIED},
        "record_ids": ["doc-jan"]})
    assert result.ok and result.data["value"] == "0.30"
    assert result.grade == UNVERIFIED
    assert result.record_ids == ["doc-jan"]


def test_compute_refuses_what_it_cannot_do_exactly(registry):
    assert registry.call("compute",
                         {"expression": "0.1 + 0.2"}).refusal == "bad_expression"
    assert registry.call("compute",
                         {"expression": "a + 1",
                          "inputs": {}}).refusal == "bad_expression"
    assert registry.call("compute",
                         {"expression": "__import__('os')"}
                         ).refusal == "bad_expression"
    assert registry.call("compute",
                         {"expression": "1 / 0"}).refusal == "division_by_zero"


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
        row = context["results"][0]["data"]["balances"][0]
        return {"answer": f"Your checking balance is USD {row['amount']}.",
                "figures": [{"value": row["amount"],
                             "record_ids": [row["record_id"], "doc-jan"],
                             "grade": row["grade"]}]}
    result = run("what is my checking balance?", planner, registry)
    assert result.answered and result.calls == 1
    assert result.grade == CORROBORATED
    assert "600.00" in result.text


def test_a_figure_citing_nothing_is_refused(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        return {"answer": "You have 600.00.",
                "figures": [{"value": "600.00", "record_ids": []}]}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "uncited_figure"


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


def test_a_declared_date_lets_the_answer_write_it_in_words(registry):
    """A date is declared as the ISO date a result carried; the answer may then
    write it however reads best."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        row = context["results"][0]["data"]["balances"][0]
        return {"answer": "As of January 31, 2026 your checking balance is "
                          f"USD {row['amount']}.",
                "figures": [{"value": row["amount"],
                             "record_ids": [row["record_id"], "doc-jan"],
                             "grade": row["grade"]}],
                "dates": [{"iso": "2026-01-31"}]}
    result = run("what is my checking balance?", planner, registry)
    assert result.answered, result.text
    assert "January 31, 2026" in result.text


def test_a_date_written_but_not_declared_says_which_date_it_was(registry):
    """The refusal names the date, because forgetting to declare one and
    inventing a number outright are very different news."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        return {"answer": "As of January 31, 2026 you are fine.",
                "figures": [], "dates": []}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "undeclared_date"
    assert "2026-01-31" in result.text


def test_a_date_no_result_carried_is_refused(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        return {"answer": "Nothing to report.", "figures": [],
                "dates": [{"iso": "2019-12-31"}]}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unfounded_date"


def test_a_declared_date_licenses_its_parts_and_no_other_number(registry):
    """The ruled cost of declaring dates by ISO alone: the parts of a real date
    become sayable, so a four-digit amount matching its year passes, while any
    number that is not one of its parts is refused exactly as before."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        return {"answer": "You spent 2026 dollars and 4711 dollars.",
                "figures": [], "dates": [{"iso": "2026-01-31"}]}
    result = run("balance?", planner, registry)
    # '2026' rides through as the declared date's year; '4711' is nobody's part.
    assert not result.answered and result.refusal == "unfounded_figure"
    assert "4711" in result.text and "2026 dollars" not in result.text


def test_a_figure_citing_records_the_run_never_saw_is_refused(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger", "args": {"entity": "balances",
                                                     "filters": {"account": "chk"}}}
        return {"answer": "600.00.",
                "figures": [{"value": "600.00",
                             "record_ids": ["doc-imaginary"]}]}
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "uncited_figure"


def test_the_call_budget_bounds_a_runaway_planner(registry):
    def planner(context):
        return {"tool": "check_completeness", "args": {}}
    result = run("loop forever", planner, registry, max_calls=3)
    assert not result.answered and result.refusal == "call_budget_exhausted"
    assert result.calls == 3


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
        row = context["results"][1]["data"]["balances"][0]
        return {"answer": f"{row['amount']}.",
                "figures": [{"value": row["amount"],
                             "record_ids": [row["record_id"]]}]}
    result = run("balance of mystery?", planner, registry)
    assert seen["refusal"] == "unknown_account"
    assert result.answered and result.calls == 2
