"""Financial Query IR is finite, exact, bounded, and evidence-carrying."""

import copy

import pytest

from viva.query import (FinancialQuery, FinancialQueryExecutor, QuerySource,
                        QuerySourceRegistry)
from viva.query.schema import (OPERATORS, OPERATOR_RULES,
                               financial_query_json_schema, operator_manifest,
                               packaged_financial_query_json_schema)
from viva.tools.envelope import ToolResult, bounded, figure


def _sources(rows):
    registry = QuerySourceRegistry()
    registry.register(QuerySource(
        "supported_spending",
        {"amount": "Money", "currency": "Enum", "category": "EntityRef(category)",
         "date": "Date", "record_id": "RecordRef", "grade": "EvidenceGrade"},
        lambda: list(rows), 20, evidence_fields=("record_id", "grade"),
        quantities=(("amount", "spending"),),
        currency_fields=(("amount", "currency"),), whole=True))
    return registry


def _query():
    return {
        "query_version": "financial-query-v1",
        "steps": [
            {"id": "source", "op": "scan", "inputs": [],
             "args": {"source": "supported_spending"}},
            {"id": "month", "op": "calendar_window", "inputs": ["source"],
             "args": {"field": "date", "from": "2026-01-01", "to": "2026-01-31"}},
            {"id": "totals", "op": "aggregate", "inputs": ["month"],
             "args": {"function": "sum", "field": "amount", "output": "total",
                      "group_by": ["category", "currency"],
                      "currency_field": "currency"}},
            {"id": "largest", "op": "sort", "inputs": ["totals"],
             "args": {"keys": ["total"], "direction": "desc"}},
            {"id": "top", "op": "limit", "inputs": ["largest"],
             "args": {"count": 3}}
        ],
        "output": "top",
        "emit": {"value_field": "total", "what_field": "category",
                 "quantity": "spending", "currency_field": "currency"}
    }


def test_grouped_exact_aggregation_propagates_records_and_weakest_grade():
    rows = [
        {"amount": "20.00", "currency": "USD", "category": "food",
         "date": "2026-01-03", "record_id": "synthetic-a", "grade": "verified"},
        {"amount": "30.00", "currency": "USD", "category": "food",
         "date": "2026-01-08", "record_id": "synthetic-b", "grade": "unverified"},
        {"amount": "75.00", "currency": "USD", "category": "housing",
         "date": "2026-01-09", "record_id": "synthetic-c", "grade": "verified"},
        {"amount": "999.00", "currency": "USD", "category": "outside",
         "date": "2026-02-01", "record_id": "synthetic-d", "grade": "verified"},
    ]
    result = FinancialQueryExecutor(_sources(rows)).execute(_query())
    assert result.ok
    assert [(fig["what"], fig["value"]) for fig in result.figures] == [
        ("housing", "75.00"), ("food", "50.00")]
    food = result.figures[1]
    assert food["grade"] == "unverified"
    assert food["record_ids"] == ["synthetic-a", "synthetic-b"]


def test_money_aggregation_refuses_mixed_currencies():
    rows = [
        {"amount": "20", "currency": "USD", "category": "food",
         "date": "2026-01-03", "record_id": "synthetic-a", "grade": "verified"},
        {"amount": "20", "currency": "EUR", "category": "food",
         "date": "2026-01-04", "record_id": "synthetic-b", "grade": "verified"},
    ]
    query = _query()
    query["steps"][2]["args"]["group_by"] = ["category"]
    result = FinancialQueryExecutor(_sources(rows)).execute(query)
    assert not result.ok and result.refusal == "invalid_financial_query"
    assert "currencies" in result.text


def test_money_aggregation_cannot_omit_its_trusted_currency_field():
    rows = [
        {"amount": "20", "currency": "USD", "category": "food",
         "date": "2026-01-03", "record_id": "synthetic-a", "grade": "verified"},
        {"amount": "20", "currency": "EUR", "category": "food",
         "date": "2026-01-04", "record_id": "synthetic-b", "grade": "verified"},
    ]
    query = _query()
    query["steps"][2]["args"].pop("currency_field")
    query["steps"][2]["args"]["group_by"] = ["category"]
    result = FinancialQueryExecutor(_sources(rows)).execute(query)
    assert not result.ok
    assert "trusted currency" in result.text


def test_emit_cannot_relabel_quantity_or_manufacture_whole_scope():
    relabelled = _query()
    relabelled["emit"]["quantity"] = "balance"
    result = FinancialQueryExecutor(_sources([])).execute(relabelled)
    assert result.ok and result.figures == []
    result = FinancialQueryExecutor(_sources([{
        "amount": "1", "currency": "USD", "category": "food",
        "date": "2026-01-03", "record_id": "synthetic-a",
        "grade": "verified"}])).execute(relabelled)
    assert not result.ok and "quantity" in result.text

    forged = _query()
    forged["emit"]["whole"] = True
    with pytest.raises(ValueError, match="schema"):
        FinancialQuery.from_dict(forged)


def test_query_contract_refuses_floats_unknown_operators_and_forward_inputs():
    floated = _query()
    floated["steps"][-1]["args"]["count"] = 3.0
    try:
        FinancialQuery.from_dict(floated)
    except ValueError as error:
        assert "float" in str(error)
    else:
        raise AssertionError("a float entered Financial Query IR")

    unknown = _query()
    unknown["steps"][1]["op"] = "python"
    try:
        FinancialQuery.from_dict(unknown)
    except ValueError as error:
        assert "unknown" in str(error)
    else:
        raise AssertionError("arbitrary code became a financial query operator")

    forward = _query()
    forward["steps"][0]["inputs"] = ["top"]
    try:
        FinancialQuery.from_dict(forward)
    except ValueError as error:
        assert "earlier" in str(error) or "scan" in str(error)
    else:
        raise AssertionError("a forward dependency entered the query DAG")


def test_source_row_bounds_are_enforced_before_results_are_emitted():
    registry = QuerySourceRegistry()
    registry.register(QuerySource("tiny", {"value": "Decimal"},
                                        lambda: [{"value": "1"}, {"value": "2"}], 1))
    query = {"query_version": "financial-query-v1",
             "steps": [{"id": "source", "op": "scan", "inputs": [],
                        "args": {"source": "tiny"}}],
             "output": "source",
             "emit": {"value_field": "value", "quantity": "count"}}
    result = FinancialQueryExecutor(registry).execute(query)
    assert not result.ok and "row bound" in result.text


def _execute_steps(rows, steps, output, emit=None, *, fields=None):
    registry = QuerySourceRegistry()
    registry.register(QuerySource(
        "rows", fields or {"id": "RecordRef", "group": "String",
                            "date": "Date", "left": "Decimal",
                            "right": "Decimal", "grade": "EvidenceGrade"},
        lambda: list(rows), 100, stable_key="id", date_fields=("date",),
        evidence_fields=("id", "grade"),
        quantities=(("left", "count"), ("right", "count")), whole=True))
    query = {"query_version": "financial-query-v1",
             "steps": [{"id": "source", "op": "scan", "inputs": [],
                        "args": {"source": "rows"}}, *steps],
             "output": output,
             "emit": emit or {"value_field": "left", "what_field": "group",
                               "quantity": "count"}}
    return FinancialQueryExecutor(registry).execute(query)


def test_group_rank_top_bottom_and_stable_ties_are_deterministic():
    rows = [
        {"id": "c", "group": "b", "date": "2026-01-03", "left": "4",
         "right": "1", "grade": "verified"},
        {"id": "a", "group": "a", "date": "2026-01-01", "left": "2",
         "right": "1", "grade": "verified"},
        {"id": "b", "group": "a", "date": "2026-01-02", "left": "2",
         "right": "1", "grade": "corroborated"},
    ]
    steps = [
        {"id": "grouped", "op": "group", "inputs": ["source"],
         "args": {"keys": ["group"]}},
        {"id": "summed", "op": "aggregate", "inputs": ["grouped"],
         "args": {"function": "sum", "field": "left", "output": "total"}},
        {"id": "ranked", "op": "rank", "inputs": ["summed"],
         "args": {"keys": ["total"], "direction": "desc", "field": "place"}},
        {"id": "top", "op": "top", "inputs": ["ranked"],
         "args": {"keys": ["total"], "count": 2}},
    ]
    emit = {"value_field": "total", "what_field": "group",
            "quantity": "count"}
    forward = _execute_steps(rows, steps, "top", emit)
    reverse = _execute_steps(list(reversed(rows)), steps, "top", emit)
    assert forward.ok and reverse.ok
    assert forward.figures == reverse.figures
    assert [(item["what"], item["value"]) for item in forward.figures] == [
        ("b", "4"), ("a", "4")]

    bottom = copy.deepcopy(steps)
    bottom[-1]["op"] = "bottom"
    result = _execute_steps(rows, bottom, "top", emit)
    assert result.ok and len(result.figures) == 2


def test_calendar_and_true_calendar_month_rolling_windows_retain_evidence():
    coverage = (("2026-03-01", "2026-03-31"),)
    rows = [
        {"id": "feb", "group": "x", "date": "2026-02-28", "left": "1",
         "right": "1", "grade": "verified", "coverage": coverage},
        {"id": "mar", "group": "x", "date": "2026-03-31", "left": "2",
         "right": "1", "grade": "verified", "coverage": coverage},
    ]
    steps = [{"id": "rolling", "op": "rolling_window", "inputs": ["source"],
              "args": {"field": "date", "width": 1, "unit": "month",
                       "edge_policy": "require_full_coverage",
                       "anchor": "2026-03-31"}}]
    result = _execute_steps(rows, steps, "rolling")
    assert result.ok
    assert [item["record_ids"] for item in result.figures] == [["mar"]]


def test_join_sets_and_exact_arithmetic_propagate_hypothetical_and_weakest_grade():
    registry = QuerySourceRegistry()
    fields = {"id": "RecordRef", "key": "String", "left": "Decimal",
              "right": "Decimal", "grade": "EvidenceGrade"}
    registry.register(QuerySource(
        "left", fields, lambda: [
            {"id": "a", "key": "one", "left": "9", "right": "3",
             "grade": "verified", "hypothetical": True},
            {"id": "b", "key": "two", "left": "8", "right": "2",
             "grade": "verified"}], 10, stable_key="id",
        evidence_fields=("id", "grade"),
        quantities=(("left", "count"), ("right", "count")), whole=True))
    registry.register(QuerySource(
        "right", fields, lambda: [
            {"id": "c", "key": "one", "left": "2", "right": "1",
             "grade": "unverified"}], 10, stable_key="id",
        evidence_fields=("id", "grade"),
        quantities=(("left", "count"), ("right", "count")), whole=True))
    query = {"query_version": "financial-query-v1", "steps": [
        {"id": "l", "op": "scan", "inputs": [], "args": {"source": "left"}},
        {"id": "r", "op": "scan", "inputs": [], "args": {"source": "right"}},
        {"id": "joined", "op": "join", "inputs": ["l", "r"],
         "args": {"left_key": "key", "right_key": "key",
                  "join_kind": "inner", "right_prefix": "other_"}},
        {"id": "computed", "op": "compute", "inputs": ["joined"],
         "args": {"operation": "subtract", "left": "left",
                  "right": "other_left", "output": "difference"}},
        {"id": "ratio", "op": "ratio", "inputs": ["computed"],
         "args": {"left": "difference", "right": "right", "output": "rate"}}
    ], "output": "ratio",
                 "emit": {"value_field": "rate", "what_field": "key",
                          "quantity": "ratio_of_count"}}
    result = FinancialQueryExecutor(registry).execute(query)
    assert result.ok
    assert result.figures[0]["value"] == "2.333333333333333333333333333"
    assert result.figures[0]["kind"] == "hypothetical"
    assert result.figures[0]["grade"] == ""
    assert result.figures[0]["record_ids"] == ["a", "c"]

    for op, expected in (("union_compatible", 2), ("difference", 1),
                         ("intersection", 1)):
        set_query = copy.deepcopy(query)
        set_query["steps"] = set_query["steps"][:2] + [
            {"id": "set", "op": op, "inputs": ["l", "r"],
             "args": {"keys": ["key"]}}]
        set_query["output"] = "set"
        set_query["emit"] = {"value_field": "left", "what_field": "key",
                             "quantity": "count"}
        assert len(FinancialQueryExecutor(registry).execute(set_query).figures) == expected


def test_joined_money_arithmetic_refuses_cross_currency_rows():
    registry = QuerySourceRegistry()
    fields = {"id": "RecordRef", "key": "String", "amount": "Money",
              "currency": "Enum"}
    declarations = dict(
        evidence_fields=("id",), quantities=(("amount", "spending"),),
        currency_fields=(("amount", "currency"),), whole=True)
    registry.register(QuerySource(
        "usd", fields, lambda: [{"id": "usd-record", "key": "same",
                                  "amount": "10", "currency": "USD"}],
        10, **declarations))
    registry.register(QuerySource(
        "eur", fields, lambda: [{"id": "eur-record", "key": "same",
                                  "amount": "20", "currency": "EUR"}],
        10, **declarations))
    query = {"query_version": "financial-query-v1", "steps": [
        {"id": "usd", "op": "scan", "inputs": [], "args": {"source": "usd"}},
        {"id": "eur", "op": "scan", "inputs": [], "args": {"source": "eur"}},
        {"id": "joined", "op": "join", "inputs": ["usd", "eur"],
         "args": {"left_key": "key", "right_key": "key",
                  "join_kind": "inner", "right_prefix": "other_"}},
        {"id": "sum", "op": "compute", "inputs": ["joined"],
         "args": {"operation": "add", "left": "amount",
                  "right": "other_amount", "output": "total"}},
    ], "output": "sum", "emit": {
        "value_field": "total", "quantity": "spending",
        "currency_field": "currency"}}
    result = FinancialQueryExecutor(registry).execute(query)
    assert not result.ok and "currencies" in result.text


def test_stable_row_keys_never_substitute_for_evidence_records():
    registry = QuerySourceRegistry()
    registry.register(QuerySource(
        "derived", {"key": "RecordRef", "provenance": "RecordRef",
                    "value": "Decimal"},
        lambda: [{"key": "account|USD|2026-01-31",
                  "provenance": "document-record", "value": "1"}], 10,
        stable_key="key", evidence_fields=("provenance",),
        quantities=(("value", "count"),), whole=True))
    query = {"query_version": "financial-query-v1", "steps": [
        {"id": "source", "op": "scan", "inputs": [],
         "args": {"source": "derived"}}], "output": "source",
        "emit": {"value_field": "value", "quantity": "count"}}
    result = FinancialQueryExecutor(registry).execute(query)
    assert result.ok
    assert result.figures[0]["record_ids"] == ["document-record"]


def test_stable_row_key_without_declared_evidence_never_becomes_provenance():
    registry = QuerySourceRegistry()
    registry.register(QuerySource(
        "derived", {"key": "String", "value": "Decimal"},
        lambda: [{"key": "synthetic-stable-key", "value": "1"}], 10,
        stable_key="key", evidence_fields=(),
        quantities=(("value", "count"),), whole=True))
    query = {"query_version": "financial-query-v1", "steps": [
        {"id": "source", "op": "scan", "inputs": [],
         "args": {"source": "derived"}}], "output": "source",
        "emit": {"value_field": "value", "quantity": "count"}}
    result = FinancialQueryExecutor(registry).execute(query)
    assert result.ok
    assert result.figures[0]["record_ids"] == []


def test_filter_cannot_preserve_a_whole_population_boundary():
    rows = [
        {"amount": "10", "currency": "USD", "category": "food",
         "date": "2026-01-03", "record_id": "food-doc", "grade": "verified"},
        {"amount": "90", "currency": "USD", "category": "rent",
         "date": "2026-01-04", "record_id": "rent-doc", "grade": "verified"},
    ]
    query = {"query_version": "financial-query-v1", "steps": [
        {"id": "source", "op": "scan", "inputs": [],
         "args": {"source": "supported_spending"}},
        {"id": "food", "op": "filter", "inputs": ["source"],
         "args": {"predicate": {"field": "category", "op": "eq",
                                  "value": "food"}}},
        {"id": "total", "op": "aggregate", "inputs": ["food"],
         "args": {"function": "sum", "field": "amount", "output": "total",
                  "currency_field": "currency"}}],
        "output": "total", "emit": {"value_field": "total",
            "quantity": "spending", "currency_field": "currency"}}
    result = FinancialQueryExecutor(_sources(rows)).execute(query)
    assert result.ok
    assert result.figures[0]["boundary"]["whole"] is False
    assert {item["kind"] for item in result.figures[0]["boundary"]["selected"]} == {
        "category"}


def test_join_refuses_incompatible_financial_boundaries():
    registry = QuerySourceRegistry()
    fields = {"id": "RecordRef", "key": "String", "amount": "Money",
              "currency": "Enum"}
    declarations = dict(
        evidence_fields=("id",), quantities=(("amount", "balance"),),
        currency_fields=(("amount", "currency"),), whole=True)
    registry.register(QuerySource(
        "whole", fields, lambda: [{
            "id": "whole-doc", "key": "same", "amount": "10",
            "currency": "USD", "boundary": {"whole": True}}],
        10, **declarations))
    registry.register(QuerySource(
        "account", fields, lambda: [{
            "id": "account-doc", "key": "same", "amount": "3",
            "currency": "USD", "boundary": {
                "whole": False,
                "selected": [{"kind": "account", "value": "checking"}],
                "cut": [{"kind": "account", "value": "checking"}]}}],
        10, **declarations))
    query = {"query_version": "financial-query-v1", "steps": [
        {"id": "whole", "op": "scan", "inputs": [],
         "args": {"source": "whole"}},
        {"id": "account", "op": "scan", "inputs": [],
         "args": {"source": "account"}},
        {"id": "joined", "op": "join", "inputs": ["whole", "account"],
         "args": {"left_key": "key", "right_key": "key",
                  "join_kind": "inner", "right_prefix": "account_"}},
        {"id": "difference", "op": "compute", "inputs": ["joined"],
         "args": {"operation": "subtract", "left": "amount",
                  "right": "account_amount", "output": "difference"}}],
        "output": "difference", "emit": {"value_field": "difference",
            "quantity": "balance", "currency_field": "currency"}}
    result = FinancialQueryExecutor(registry).execute(query)
    assert not result.ok
    assert "different financial boundaries" in result.text


def test_category_spending_can_be_joined_to_period_income_for_a_share():
    registry = QuerySourceRegistry()
    period = {"kind": "period", "value": "2026-01-01", "to": "2026-01-31"}
    registry.register(QuerySource(
        "category_spending",
        {"record": "RecordRef", "period": "String",
         "category": "EntityRef(category)", "amount": "Money",
         "currency": "Enum", "boundary": "Boundary"},
        lambda: [{"record": "spending-doc", "period": "2026-01",
                  "category": "groceries", "amount": "25", "currency": "USD",
                  "boundary": {"whole": False, "selected": [period],
                               "cut": [period, {"kind": "category",
                                                "value": "groceries"}]}}],
        10, evidence_fields=("record",), quantities=(("amount", "spending"),),
        currency_fields=(("amount", "currency"),)))
    registry.register(QuerySource(
        "period_income",
        {"record": "RecordRef", "period": "String", "amount": "Money",
         "currency": "Enum", "boundary": "Boundary"},
        lambda: [{"record": "income-doc", "period": "2026-01",
                  "amount": "100", "currency": "USD",
                  "boundary": {"whole": False, "selected": [period],
                               "cut": [period], "unposted": 2,
                               "unmeasured": [{"account": "missing",
                                   "reason": "unobserved", "settled_by": ""}]}}],
        10, evidence_fields=("record",), quantities=(("amount", "income"),),
        currency_fields=(("amount", "currency"),)))
    query = {"query_version": "financial-query-v1", "steps": [
        {"id": "spending", "op": "scan", "inputs": [],
         "args": {"source": "category_spending"}},
        {"id": "income", "op": "scan", "inputs": [],
         "args": {"source": "period_income"}},
        {"id": "joined", "op": "join", "inputs": ["spending", "income"],
         "args": {"left_key": "period", "right_key": "period",
                  "join_kind": "inner", "right_prefix": "income_"}},
        {"id": "share", "op": "ratio", "inputs": ["joined"],
         "args": {"left": "amount", "right": "income_amount",
                  "output": "share"}}],
        "output": "share", "emit": {"value_field": "share",
            "what_field": "category", "quantity": "ratio"}}
    result = FinancialQueryExecutor(registry).execute(query)
    assert result.ok
    assert result.figures[0]["value"] == "0.25"
    assert result.figures[0]["record_ids"] == ["income-doc", "spending-doc"]
    assert {item["kind"] for item in result.figures[0]["boundary"]["cut"]} == {
        "category", "period"}
    assert result.figures[0]["boundary"]["unposted"] == 2
    assert result.figures[0]["boundary"]["unmeasured"][0]["account"] == "missing"


def test_domain_operator_uses_installed_authority_and_inherits_its_boundary():
    registry = QuerySourceRegistry()
    registry.register_domain("spending", lambda filters: ToolResult(
        tool="query_ledger", ok=True,
        figures=[figure("12.50", "supported spending", quantity="spending",
                        currency="USD", grade="verified", record_ids=["doc-a"],
                        boundary=bounded(whole=True, selected=[], cut=[]))]))
    query = {"query_version": "financial-query-v1",
             "steps": [{"id": "spending", "op": "spending", "inputs": [],
                        "args": {"filters": {}}}], "output": "spending",
             "emit": {"value_field": "value", "what_field": "what",
                      "currency_field": "currency", "dated_field": "dated",
                      "quantity": "spending"}}
    result = FinancialQueryExecutor(registry).execute(query)
    assert result.ok and result.figures[0]["boundary"]["whole"] is True
    assert result.figures[0]["record_ids"] == ["doc-a"]


def test_domain_magnitudes_cannot_bypass_typed_cross_currency_arithmetic():
    registry = QuerySourceRegistry()

    def net_worth(filters):
        currency = "USD" if filters.get("side") == "left" else "EUR"
        value = "10" if currency == "USD" else "20"
        return ToolResult(tool="query_ledger", ok=True, figures=[figure(
            value, "net worth", quantity="net_worth", currency=currency,
            grade="verified", record_ids=[f"doc-{currency}"],
            boundary=bounded(whole=True, selected=[], cut=[]))])

    registry.register_domain("net_worth", net_worth)
    query = {"query_version": "financial-query-v1", "steps": [
        {"id": "left", "op": "net_worth", "inputs": [],
         "args": {"filters": {"side": "left"}}},
        {"id": "right", "op": "net_worth", "inputs": [],
         "args": {"filters": {"side": "right"}}},
        {"id": "joined", "op": "join", "inputs": ["left", "right"],
         "args": {"left_key": "quantity", "right_key": "quantity",
                  "join_kind": "inner", "right_prefix": "right_"}},
        {"id": "total", "op": "compute", "inputs": ["joined"],
         "args": {"operation": "add", "left": "value",
                  "right": "right_value", "output": "total"}}],
        "output": "total", "emit": {"value_field": "total",
            "quantity": "net_worth", "currency_field": "currency"}}
    result = FinancialQueryExecutor(registry).execute(query)
    assert not result.ok
    assert "statically typed numeric operands" in result.text


def test_every_operator_has_both_laws_and_only_finite_vocabulary_is_manifested():
    assert set(OPERATOR_RULES) == set(OPERATORS)
    assert {item["name"] for item in operator_manifest()} == set(OPERATORS)
    assert all(item["value_rule"] and item["evidence_rule"]
               for item in operator_manifest())


def test_packaged_financial_query_schema_is_the_executable_operator_grammar():
    assert packaged_financial_query_json_schema() == financial_query_json_schema()
    step_alternatives = packaged_financial_query_json_schema()["properties"][
        "steps"]["items"]["oneOf"]
    assert {item["properties"]["op"]["enum"][0]
            for item in step_alternatives} == set(OPERATORS)


def test_empty_aggregate_never_invents_zero_without_a_covered_population():
    result = _execute_steps([], [
        {"id": "total", "op": "aggregate", "inputs": ["source"],
         "args": {"function": "sum", "field": "left", "output": "total"}}],
        "total", {"value_field": "total", "quantity": "count"})
    assert result.ok and result.figures == []
