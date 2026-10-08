"""Everyday financial meaning uses sourced reads and fixed arithmetic."""

import copy
from types import SimpleNamespace

import pytest

from _tool_test_support import (_events, _p, _statement_reply,
                                account_opened, closing_balance_observed, document_captured,
                                opening_balance_observed, read_recorded)
from viva.answer_program import (AnswerResourcePolicy, CapabilityManifest,
                                 ProgramValidator)
from viva.answer_program.bind import DeterministicBinder
from viva.answer_program.execute import ProgramExecutor
from viva.answer_program.intents import (SemanticFamilyRegistry,
                                         SemanticOutcome, SemanticRequest,
                                         SEMANTIC_REQUEST_VERSION)
from viva.answer_program.schema import ContractError
from viva.ledger import LedgerProjection
from viva.ledger import Posting, Provenance, transaction_recorded, simple_transaction
from viva.tools import default_registry


ANALYSIS_FAMILIES = {
    "spending_by_category", "spending_by_merchant", "spending_by_account",
    "spending_comparison", "movement_search", "period_income",
    "period_surplus", "recurring_spending",
}


def _registry(*, quiet_period=False):
    events = _events()
    if quiet_period:
        events.extend([
            document_captured("quiet-period", "quiet.pdf", 100,
                              "bank_statement", 1.0, "2026-03-01"),
            read_recorded("quiet-period", "synthetic", "fixture", "text",
                          _statement_reply("600", "2026-02-01", "600",
                                           "2026-02-28"),
                          0, 0, 0, True, None, "2026-03-01"),
            opening_balance_observed("chk", "600", "2026-02-01",
                                     _p("quiet-period")),
            closing_balance_observed("chk", "600", "2026-02-28",
                                     _p("quiet-period")),
        ])
    return default_registry(LedgerProjection(events), today="2026-03-01")


def _answer(family, parameters, *, claims=None, registry=None):
    registry = registry or _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    families = SemanticFamilyRegistry(registry.semantic_entities())
    definition = families.get(family)
    assert definition is not None, "financial meaning is not executable"
    request = SemanticRequest(family, parameters,
                              tuple(claims or definition.claims),
                              families.catalog_digest)
    program = families.lower(SemanticOutcome("request", request), manifest)
    checked = ProgramValidator(manifest, policy).validate(program)
    assert checked.ok, checked.defects
    execution = ProgramExecutor(registry, policy).execute(program, "synthetic question")
    return DeterministicBinder(registry, "en-US").bind(program, execution), execution


def _comparison(**overrides):
    return {"view": "spending_comparison", "from": "2026-01-01",
            "to": "2026-01-31", "baseline_from": "2026-02-01",
            "baseline_to": "2026-02-28", "include_percentage": False,
            "filters": {"account": "chk"}, **overrides}


def test_everyday_analysis_is_an_executable_reviewed_catalog():
    families = SemanticFamilyRegistry()
    assert ANALYSIS_FAMILIES <= set(families.supported_ids)
    assert families.get("account_inventory").runtime_selectable is False


@pytest.mark.parametrize("family,group", [
    ("spending_by_category", "category"),
    ("spending_by_merchant", "merchant"),
    ("spending_by_account", "account"),
])
def test_breakdown_excludes_transfer_and_carries_total_and_group(family, group):
    answer, execution = _answer(family, {"from": "2026-01-01", "to": "2026-01-31"})
    assert answer.result.answered
    result = execution.transcript[0]
    assert result.data["group_by"] == group
    assert result.data["total"] == "100.00"
    assert any(fig["value"] == "100.00" and "total spending" in fig["what"]
               for fig in answer.result.figures)
    assert "between two of your own accounts is not counted" in answer.result.text


def test_comparison_keeps_covered_zero_and_current_minus_baseline():
    result = _registry(quiet_period=True).call("read_financial_analysis", _comparison())
    assert result.ok, result.text
    assert [fig["value"] for fig in result.figures] == ["100.00", "0", "100.00"]
    assert result.figures[-1]["boundary"]["whole"] is False
    assert {"doc-jan", "quiet-period"} <= set(result.figures[-1]["record_ids"])
    assert result.figures[-1]["dated"] == ""


def test_zero_baseline_percentage_is_disclosed_without_losing_totals():
    result = _registry(quiet_period=True).call(
        "read_financial_analysis", _comparison(include_percentage=True))
    assert result.ok
    assert len(result.figures) == 3
    assert any("zero" in str(caveat).lower() and "percentage" in str(caveat).lower()
               for caveat in result.caveats)


def test_uncovered_baseline_is_unavailable_rather_than_zero():
    result = _registry().call("read_financial_analysis", _comparison())
    assert not result.ok
    assert not result.figures
    assert result.refusal in {"unsupported_empty_scope", "partial_empty_scope"}


@pytest.mark.parametrize("change", [
    {"include_percentage": "false"}, {"include_percentage": 1},
    {"baseline_from": "2026-02-29"}, {"baseline_to": "2026-01-01"},
    {"from": "2026-01-32"}, {"filters": {"tag": "pantry"}},
    {"unexpected": "ignored"}, {"filters": {"account": "absent"}},
])
def test_direct_comparison_rejects_unreviewed_or_invalid_arguments(change):
    result = _registry(quiet_period=True).call("read_financial_analysis", _comparison(**change))
    assert not result.ok
    assert not result.figures


def test_comparison_percentage_claim_controls_the_fixed_read_flag():
    parameters = {"from": "2026-01-01", "to": "2026-01-31",
                  "baseline_from": "2026-02-01", "baseline_to": "2026-02-28",
                  "account_phrase": "chk"}
    for claims, expected in [(('comparison',), False),
                             (('comparison', 'percentage_change'), True)]:
        answer, execution = _answer("spending_comparison", parameters,
                                    claims=claims, registry=_registry(quiet_period=True))
        assert answer.result.answered
        assert execution.transcript[0].data["include_percentage"] is expected


def test_comparison_baseline_calendar_month_is_grounded_and_dates_validated():
    families = SemanticFamilyRegistry()
    parameters = {"from": "2026-01-01", "to": "2026-01-31",
                  "baseline_from": "2025-12-01", "baseline_to": "2025-12-31"}
    sources = {
        key: {"source": "question", "quote": ("January 2026" if key in {"from", "to"}
                                                   else "December 2025"),
              "derivation": "calendar_month_start" if key.endswith("from") else "calendar_month_end"}
        for key in parameters}
    raw = {"request_version": SEMANTIC_REQUEST_VERSION,
           "catalog_digest": families.catalog_digest,
           "entity_catalog_digest": families.entity_catalog_digest,
           "outcome": "request", "family": "spending_comparison",
           "parameters": parameters, "parameter_sources": sources,
           "requested_claims": ["comparison"]}
    context = SimpleNamespace(question="Compare January 2026 with December 2025", prior_turns=())
    assert families.parse(raw, context).kind == "request"
    wrong = copy.deepcopy(raw)
    wrong["parameters"]["baseline_to"] = "2025-12-32"
    with pytest.raises(ContractError, match="ISO date"):
        families.parse(wrong, context)


def test_movement_search_retains_signed_effect_and_transfer_treatment():
    answer, execution = _answer("movement_search", {
        "from": "2026-01-01", "to": "2026-01-31", "account_phrase": "chk"})
    assert answer.result.answered
    figures = [fig for fig in answer.result.figures if fig["quantity"] == "movement"]
    assert sorted(fig["value"] for fig in figures) == ["-300.00", "-40.00", "-60.00"]
    assert execution.transcript[0].data["total"] == 3
    assert all(fig["record_ids"] for fig in figures)


def test_empty_search_is_zero_only_when_the_whole_population_is_covered():
    registry = _registry(quiet_period=True)
    parameters = {"view": "movement_search", "from": "2026-02-01", "to": "2026-02-28"}
    unsupported = registry.call("read_financial_analysis", parameters)
    assert not unsupported.ok and not unsupported.figures
    covered = registry.call("read_financial_analysis", {
        **parameters, "filters": {"account": "chk"}})
    assert covered.ok, covered.text
    assert len(covered.figures) == 1
    assert covered.figures[0]["value"] == "0"
    assert covered.figures[0]["record_ids"] == ["quiet-period"]
    assert covered.covers == [{"account": "chk", "from": "2026-02-01", "to": "2026-02-28"}]
    assert covered.figures[0]["grade"] == ""


@pytest.mark.parametrize("extra", [
    {"include_percentage": False}, {"baseline_from": "2026-01-01"},
    {"baseline_to": "2026-01-31"},
])
def test_direct_search_rejects_comparison_arguments(extra):
    result = _registry().call("read_financial_analysis", {
        "view": "movement_search", "from": "2026-01-01", "to": "2026-01-31", **extra})
    assert not result.ok and not result.figures


def test_percentage_is_a_signed_baseline_relative_ratio():
    result = _registry(quiet_period=True).call("read_financial_analysis", _comparison(
        **{"from": "2026-02-01", "to": "2026-02-28",
           "baseline_from": "2026-01-01", "baseline_to": "2026-01-31",
           "include_percentage": True}))
    assert result.ok
    assert result.figures[-1]["quantity"] == "ratio_of_spending"
    assert result.figures[-1]["value"] == "-1"


def test_comparison_partial_period_keeps_both_limits_and_recorded_meaning():
    result = _registry().call("read_financial_analysis", _comparison(
        **{"from": "2025-12-01", "baseline_from": "2026-01-01",
           "baseline_to": "2026-01-31"}))
    assert result.ok, result.text
    assert any("reaches past" in str(caveat) for caveat in result.caveats)
    assert result.figures[-1]["value"] == "0.00"
    assert "recorded spending" in result.figures[-1]["what"]


def test_comparison_never_chooses_the_largest_or_first_same_quantity(monkeypatch):
    from viva.answer_program import capabilities
    original = capabilities.ledger_tools.query_ledger
    def duplicated(*args, **kwargs):
        result = original(*args, **kwargs)
        if result.ok:
            total = next(fig for fig in result.figures if fig["what"] == "total spending by category")
            result.figures.append(copy.deepcopy(total))
        return result
    monkeypatch.setattr(capabilities.ledger_tools, "query_ledger", duplicated)
    result = _registry(quiet_period=True).call("read_financial_analysis", _comparison())
    assert not result.ok
    assert result.refusal == "inconsistent_spending_authority"


def test_empty_search_currency_scope_keeps_silent_eligible_accounts():
    events = [account_opened("cash", "depository", "Example Cash", "USD", "2026-01-01"),
              account_opened("silent", "depository", "Example Other", "EUR", "2026-01-01"),
              document_captured("covered", "covered.pdf", 100, "bank_statement", 1.0, "2026-02-01"),
              read_recorded("covered", "synthetic", "fixture", "text",
                            _statement_reply("100", "2026-01-01", "100", "2026-01-31"),
                            0, 0, 0, True, None, "2026-02-01"),
              opening_balance_observed("cash", "100", "2026-01-01", _p("covered")),
              closing_balance_observed("cash", "100", "2026-01-31", _p("covered"))]
    registry = default_registry(LedgerProjection(events), today="2026-03-01")
    args = {"view": "movement_search", "from": "2026-01-01", "to": "2026-01-31"}
    assert not registry.call("read_financial_analysis", args).ok
    usd = registry.call("read_financial_analysis", {**args, "filters": {"currency": "USD"}})
    assert usd.ok and usd.figures[0]["record_ids"] == ["covered"]
    eur = registry.call("read_financial_analysis", {**args, "filters": {"currency": "EUR"}})
    assert not eur.ok and not eur.figures


def _income_registry():
    events = [*_events(), transaction_recorded([
        Posting("chk", "800", "verified"),
        Posting("Income:ExamplePay", "-800", "verified")],
        "Example Pay", "2026-01-25", provenance=Provenance("income-source", 1, "fixture")),
        simple_transaction("chk", "150", "Example Unexplained Inflow", "2026-01-26",
                           provenance=Provenance("unexplained-source", 1, "fixture"))]
    return default_registry(LedgerProjection(events), today="2026-03-01")


def test_period_income_delivers_attributed_total_and_keeps_unexplained_separate():
    answer, execution = _answer("period_income", {
        "from": "2026-01-01", "to": "2026-01-31"}, registry=_income_registry())
    assert answer.result.answered, answer.result.text
    assert execution.transcript[0].data["basis"] == "attributed"
    assert execution.transcript[0].data["by_currency"] == {"USD": "800"}
    assert execution.transcript[0].data["unexplained_inflows"] == "150"
    assert {(fig["quantity"], fig["value"]) for fig in answer.result.figures} == {
        ("income", "800"), ("gross_flow", "150")}
    assert "unexplained inflows" in answer.result.text.lower()
    assert "not attributed" in answer.result.text.lower() or "nothing has attributed" in answer.result.text.lower()


@pytest.mark.parametrize("extra", [
    {"filters": {"account": "chk"}}, {"filters": {"category": "groceries"}},
    {"filters": {"merchant": "greenfield market"}},
    {"baseline_from": "2026-01-01"}, {"include_percentage": False},
    {"filters": {"currency": "absent"}},
])
def test_direct_attributed_income_rejects_irrelevant_arguments(extra):
    result = _income_registry().call("read_financial_analysis", {
        "view": "period_income", "from": "2026-01-01", "to": "2026-01-31", **extra})
    assert not result.ok and not result.figures


def test_income_missing_period_is_not_zero():
    result = _income_registry().call("read_financial_analysis", {
        "view": "period_income", "from": "2025-12-01", "to": "2025-12-31"})
    assert not result.ok and not result.figures
    assert result.refusal == "unsupported_empty_scope"


def test_surplus_delivers_attributed_income_less_spending_with_limits():
    answer, execution = _answer("period_surplus", {
        "from": "2026-01-01", "to": "2026-01-31"}, registry=_income_registry())
    assert answer.result.answered
    assert {(fig["quantity"], fig["value"]) for fig in answer.result.figures} == {
        ("income", "800"), ("spending", "100.00"),
        ("net_movement", "700.00"), ("gross_flow", "150")}
    assert "Unexplained inflows are not counted as income" in answer.result.text
    assert "settlements are not counted as spending" in answer.result.text


def test_recurring_spending_delivers_observation_without_future_bill_claim():
    from viva.ledger.events import merchant_enriched
    events = [account_opened("cash", "depository", "Example Cash", "USD", "2025-11-01")]
    for when in ("2025-11-15", "2025-12-15", "2026-01-15"):
        source = "pattern-" + when
        events.extend([
            document_captured(source, "synthetic-pattern.pdf", 100,
                              "bank_statement", 1.0, when),
            read_recorded(source, "synthetic", "fixture", "text",
                          _statement_reply("100", when[:7] + "-01", "75", when),
                          0, 0, 0, True, None, when),
            opening_balance_observed("cash", "100", when[:7] + "-01", _p(source)),
            simple_transaction("cash", "-25", "Example Membership", when,
                               provenance=Provenance(source, 1, "fixture")),
            closing_balance_observed("cash", "75", when, _p(source)),
        ])
    events.append(merchant_enriched("example membership", "other",
                  attributes={"counterparty_kind": "business", "billing": "standing", "billing_period": "monthly"},
                  occurred_at="2026-01-16"))
    registry = default_registry(LedgerProjection(events), today="2026-03-01")
    answer, execution = _answer("recurring_spending", {}, registry=registry)
    assert answer.result.answered, answer.result.text
    assert execution.transcript[0].data["patterns"][0]["count"] == 3
    assert execution.transcript[0].data["patterns"][0]["measured"] is True
    assert any(fig["value"] == "75" and fig["quantity"] == "spending"
               for fig in answer.result.figures)
    assert "not a forecast" in answer.result.text.lower()


def test_recurring_spending_without_qualified_history_refuses():
    answer, execution = _answer("recurring_spending", {})
    assert not answer.result.answered
    assert execution.transcript[0].refusal == "insufficient_history"
    assert not answer.result.figures


def test_empty_attributed_income_is_statement_backed_zero_in_one_currency():
    events = [account_opened("cash", "depository", "Example Cash", "USD", "2026-01-01"),
              document_captured("quiet-income", "quiet-income.pdf", 100,
                                "bank_statement", 1.0, "2026-02-01"),
              read_recorded("quiet-income", "synthetic", "fixture", "text",
                            _statement_reply("100", "2026-01-01", "100", "2026-01-31"),
                            0, 0, 0, True, None, "2026-02-01"),
              opening_balance_observed("cash", "100", "2026-01-01", _p("quiet-income")),
              closing_balance_observed("cash", "100", "2026-01-31", _p("quiet-income"))]
    registry = default_registry(LedgerProjection(events), today="2026-03-01")
    result = registry.call("read_financial_analysis", {
        "view": "period_income", "from": "2026-01-01", "to": "2026-01-31",
        "filters": {"currency": "USD"}})
    assert result.ok, result.text
    assert result.data["basis"] == "attributed"
    assert result.figures[0]["value"] == "0"
    assert result.figures[0]["currency"] == "USD"
    assert result.figures[0]["record_ids"] == ["quiet-income"]


def test_capability_dispatch_sources_are_authenticated_and_counterfactual_changes_bind(monkeypatch):
    import inspect
    from viva.answer_program import capabilities
    families = SemanticFamilyRegistry()
    before = families._admitted_implementation_digests()
    assert {"capabilities", "tool_registrations", "tool_registry", "ledger_tools",
            "ledger_aggregates", "ledger_common", "ledger_movements", "ledger_vocabulary",
            "rhythm_projection", "financial_streams", "statement_register"} <= set(before)
    from pathlib import Path
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path:
                        original(path) + b"\n# changed arithmetic authority\n"
                        if str(path)==inspect.getsourcefile(capabilities) else original(path))
    after = families._admitted_implementation_digests()
    assert after["capabilities"] != before["capabilities"]
    assert {key: value for key, value in before.items() if key != "capabilities"} == {
        key: value for key, value in after.items() if key != "capabilities"}


def _runtime_answer(family, parameters, *, registry=None, execution_flags=None,
                    integrity_refusal=None):
    from viva.answer_program.runtime import AnswerProgramRuntime
    registry = registry or _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    families = SemanticFamilyRegistry(registry.semantic_entities())
    definition = families.get(family)
    request = SemanticRequest(family, parameters, tuple(definition.claims),
                              families.catalog_digest)
    semantic = SemanticOutcome("request", request)
    program = families.lower(semantic, manifest)
    checked = ProgramValidator(manifest, policy).validate(program)
    assert checked.ok, checked.defects
    compilation = SimpleNamespace(ok=True, program=program, exchanges=(),
                                  semantic_outcome=semantic)
    compiler = SimpleNamespace(compile=lambda context: compilation)
    executor = ProgramExecutor(registry, policy)
    binder = DeterministicBinder(registry, "en-US")
    if execution_flags:
        execute = executor.execute
        def flagged(program, question):
            execution = execute(program, question)
            for key, value in execution_flags.items():
                setattr(execution, key, value)
            return execution
        executor.execute = flagged
    if integrity_refusal:
        bind = binder.bind
        def rejected(program, execution):
            binding = bind(program, execution)
            binding.result.refusal = integrity_refusal
            return binding
        binder.bind = rejected
    return AnswerProgramRuntime(compiler, executor, binder).answer(
        SimpleNamespace(question="synthetic question"))


@pytest.mark.parametrize("tag,fragment", [
    ("unsupported_empty_scope", "do not cover"),
    ("partial_empty_scope", "only part"),
    ("insufficient_history", "not enough recorded history"),
    ("mixed_currencies", "one currency at a time"),
])
def test_analysis_limits_are_delivered_with_actual_tag_and_missing_bindings(monkeypatch, tag, fragment):
    from viva.answer_program import capabilities
    from viva.tools.envelope import refusal
    monkeypatch.setattr(capabilities.ledger_tools, "query_ledger",
                        lambda *args: refusal("query_ledger", tag, "unreviewed tool prose"))
    result = _runtime_answer("recurring_spending", {})
    assert not result.result.answered
    assert result.result.status == result.outcome.status == "missing_data"
    assert result.result.refusal == result.result.outcome_tag == result.outcome.tag == tag
    assert fragment in result.result.text == result.outcome.text
    assert "unreviewed tool prose" not in result.result.text
    assert result.result.missing and tuple(result.result.missing) == result.outcome.missing
    assert all(item["label"] == result.result.text for item in result.result.missing)
    assert [{key: item[key] for key in ("hole", "source", "reason")}
            for item in result.result.missing] == [
                item.to_dict() for item in result.binding.unbound]
    assert all("question" not in item for item in result.result.missing)


@pytest.mark.parametrize("flag,expected", [
    ("deadline_exceeded", "execution_deadline"),
    ("evidence_limit_exceeded", "evidence_limit"),
    ("figure_limit_exceeded", "figure_limit"),
])
def test_analysis_delivery_does_not_mask_infrastructure(monkeypatch, flag, expected):
    from viva.answer_program import capabilities
    from viva.tools.envelope import refusal
    monkeypatch.setattr(capabilities.ledger_tools, "query_ledger",
                        lambda *args: refusal("query_ledger", "insufficient_history", "raw"))
    result = _runtime_answer("recurring_spending", {}, execution_flags={flag: True})
    assert result.outcome.status == "failed" and result.outcome.tag == expected
    assert "not enough recorded history" not in result.result.text
    assert all("label" not in item for item in result.result.missing)


@pytest.mark.parametrize("tag", ["unknown_figure", "wrong_subject", "uncited_figure"])
def test_analysis_delivery_does_not_mask_binding_integrity(monkeypatch, tag):
    from viva.answer_program import capabilities
    from viva.tools.envelope import refusal
    monkeypatch.setattr(capabilities.ledger_tools, "query_ledger",
                        lambda *args: refusal("query_ledger", "insufficient_history", "raw"))
    result = _runtime_answer("recurring_spending", {}, integrity_refusal=tag)
    assert result.result.refusal == tag
    assert "not enough recorded history" not in result.result.text
    assert all("label" not in item for item in result.result.missing)


def test_original_family_and_unknown_limits_keep_existing_delivery(monkeypatch):
    from viva.answer_program import capabilities
    from viva.tools.envelope import refusal
    monkeypatch.setattr(capabilities.ledger_tools, "query_ledger",
                        lambda *args: refusal("query_ledger", "insufficient_history", "raw"))
    original = _runtime_answer("category_spending_period", {
        "from": "2026-01-01", "to": "2026-01-31", "category": "groceries"})
    assert original.result.refusal == "nothing_established"
    assert all("label" not in item for item in original.result.missing)
    assert "not enough recorded history" not in original.result.text
    monkeypatch.setattr(capabilities.ledger_tools, "query_ledger",
                        lambda *args: refusal("query_ledger", "unexpected_limit", "raw"))
    unknown = _runtime_answer("recurring_spending", {})
    assert unknown.result.refusal == "nothing_established"
    assert all("label" not in item for item in unknown.result.missing)
    assert "raw" not in unknown.result.text


def test_analysis_limit_uses_program_order_ignoring_blocked_dependents():
    from viva.answer_program.capabilities import actionable_limit
    from viva.answer_program.execute import NodeExecution
    nodes = [SimpleNamespace(id="dependent", importance="required"),
             SimpleNamespace(id="first", importance="required"),
             SimpleNamespace(id="second", importance="required")]
    program = SimpleNamespace(question_kind="movement_search", nodes=nodes)
    execution = SimpleNamespace(nodes={
        "second": NodeExecution("second", "refused", refusal="mixed_currencies"),
        "dependent": NodeExecution("dependent", "dependency_blocked", refusal="dependency_failed"),
        "first": NodeExecution("first", "refused", refusal="partial_empty_scope")},
        deadline_exceeded=False, evidence_limit_exceeded=False, figure_limit_exceeded=False)
    binding = SimpleNamespace(result=SimpleNamespace(answered=False, refusal="nothing_established"))
    assert actionable_limit(program, execution, binding)[0] == "partial_empty_scope"
    execution.nodes["second"].refusal = "invalid_reference"
    assert actionable_limit(program, execution, binding) is None


def test_account_presentation_only_changes_labels_on_copied_numerical_envelopes():
    from viva.answer_program.capabilities import read_financial_analysis
    from viva.tools import ledger_tools
    proj = LedgerProjection(_events())
    raw = ledger_tools.query_ledger(proj, {
        "entity": "aggregate", "metric": "spending", "group_by": "account",
        "filters": {"window": {"from": "2026-01-01", "to": "2026-01-31"}}})
    before = copy.deepcopy(raw)
    presented = read_financial_analysis(proj, {
        "view": "spending_by_account", "from": "2026-01-01", "to": "2026-01-31"})
    assert presented.ok and presented.data == raw.data
    assert any("Everyday Checking" in item["what"] for item in presented.figures)
    for old, new in zip(raw.figures, presented.figures):
        assert {k: v for k, v in old.items() if k != "what"} == {
            k: v for k, v in new.items() if k != "what"}
        if "total" in old["what"] or "residual" in old["what"]:
            assert old["what"] == new["what"]
    assert raw == before
    answer = _runtime_answer("spending_by_account", {
        "from": "2026-01-01", "to": "2026-01-31"})
    assert answer.result.answered and "Everyday Checking" in answer.result.text


def test_duplicate_account_names_use_institution_then_canonical_fallback():
    from viva.answer_program.capabilities import _account_labels
    def labels(rows):
        proj = SimpleNamespace(account_infos=lambda: [SimpleNamespace(
            account=account, name=name, institution=institution)
            for account, name, institution in rows])
        return _account_labels(proj)
    assert labels([("a", "Shared", "Example A"), ("b", "Shared", "Example B")]) == {
        "a": "Shared — Example A", "b": "Shared — Example B"}
    assert labels([("a", "Shared", "Example"), ("b", "Shared", "Example")]) == {
        "a": "a", "b": "b"}
    assert labels([("a", "", "Example"), ("b", "", "")]) == {"a": "Example", "b": "b"}


@pytest.mark.parametrize("extra", [
    {"filters": {"account": "chk"}}, {"filters": {"merchant": "example"}},
    {"filters": {"category": "groceries"}}, {"include_percentage": False},
    {"baseline_from": "2025-12-01"}, {"unknown": "x"},
    {"from": "2026-02-31"}, {"to": "2025-01-01"},
])
def test_account_presentation_rejects_inapplicable_or_bad_arguments(extra):
    result = _registry().call("read_financial_analysis", {
        "view": "spending_by_account", "from": "2026-01-01", "to": "2026-01-31", **extra})
    assert not result.ok and not result.figures


def test_search_and_available_family_copy_use_reviewed_plain_labels():
    answer = _runtime_answer("movement_search", {
        "from": "2026-01-01", "to": "2026-01-31", "account_phrase": "chk"})
    assert answer.result.answered
    assert answer.result.text.startswith("Matching transactions and the number found in the held records")
    families = SemanticFamilyRegistry()
    assert families.get("period_surplus").user_label == "Income minus spending"
    assert families.get("recurring_spending").user_label == "Costs that repeat in the records"
    assert families.get("movement_search").user_example.startswith("Show transactions from")
