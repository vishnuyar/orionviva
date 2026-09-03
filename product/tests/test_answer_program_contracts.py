"""The answer program is typed, versioned and bounded before any read."""

import copy
import json
import pickle
import time
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from vivacore import versions

from _tool_test_support import (_events, Provenance, account_opened,
                                closing_balance_observed)
from viva.answer_program import (AnswerProgram, AnswerResourcePolicy,
                                 AdmissionPreflightError,
                                 AdmissionReport,
                                 AdmissionThresholds, AnswerProgramCompiler,
                                 BreadthFeedback, CapabilityManifest,
                                 DeterministicBinder, ProgramExecutor,
                                 ProgramValidator, QuestionContext,
                                 admitted_profile, admission_report_digest,
                                 admission_fixture_digest,
                                 admission_registry,
                                 check_profile, check_single_path,
                                 current_contract_digests,
                                 evaluate_admission, replay_capture,
                                 MINIMUM_ADMISSION_THRESHOLDS,
                                 preflight_live_suite,
                                 resource_policy_digest,
                                 run_live_suite, write_release_bundle)
from viva.answer_program import validate_admission_report
from viva.answer_program.compiler import COMPILER_VERSION, compiler_output_json_schema
from viva.answer_program.eval import CaseScore, SemanticEvalCase
from viva.answer_program.intents import (SEMANTIC_REQUEST_VERSION,
                                         SemanticFamilyRegistry,
                                         SemanticOutcome, SemanticRequest)
from viva.answer_program.schema import ANSWER_PROGRAM_VERSION, ContractError
from viva.answer_program.schema import _generated_program_json_schema, program_json_schema
from viva.answer_program.eval import (CASES, EvalCase, derive_semantic_oracle,
                                      evaluate_adversarial,
                                      load_adversarial_cases, load_cases, score)
from viva.ledger import LedgerProjection
from viva.session import Session
from viva.tools import default_registry
from viva.tools.registry import PACKAGE


def _registry():
    return default_registry(LedgerProjection(_events()), today="2026-03-01")


def _fully_validated_forged_report(manifest):
    from vivacore.models import AnthropicAdapter

    cases = load_cases()
    base = evaluate_admission(
        [CaseScore(case.id, True, True, (), 0, 0) for case in cases],
        attempts=[1] * len(cases), first_attempt_valid=[True] * len(cases),
        thresholds=AdmissionThresholds(1, 1, 1),
        identity={"provider": "anthropic", "requested_model": "copied",
                  "resolved_model": "copied", "endpoint": "copied",
                  "modality": "native-structured", "locale_family": "en"},
        contract_digests=current_contract_digests(
            manifest, AnswerResourcePolicy()),
        adversarial_passed=True)
    adapter_name = f"{AnthropicAdapter.__module__}.{AnthropicAdapter.__qualname__}"
    measurements = [{"case_id": case.id, "attempts": 1}
                    for case in cases]
    evidence = tuple({
        "case_id": case.id, "attempt": 1, "oracle_key": case.oracle_key,
        "oracle_digest": "copied-oracle", "request_digest": "copied-request",
        "response_digest": "copied-response", "resolved_model": "copied",
        "modality": "native-structured", "provider_adapter": adapter_name,
        "failure_code": "", "usage_reported": True} for case in cases)
    contracts = dict(base.contract_digests)
    return replace(
        base, metrics={**base.metrics, "turn_measurements": measurements},
        attempt_evidence=evidence, publication_source="live_provider_suite",
        admission_fixture_digest=contracts["admission_fixture"],
        oracle_set_digest=contracts["oracle_set"])


def _program(manifest):
    return {
        "program_version": "answer-program-schema-v1",
        "capability_manifest_version": "capability-manifest-v1",
        "capability_manifest_digest": manifest.digest,
        "mode": "answer",
        "question_kind": "balance_read",
        "shape": {"clauses": [{
            "id": "balance_clause",
            "text": "Your supported balance is {balance}.",
            "slots": [{"name": "balance", "type": "money",
                       "quantity": "balance", "scope": ["whole"]}],
        }]},
        "nodes": [{"id": "balances", "kind": "tool_read",
                   "tool": "query_ledger", "args": {"entity": "balances"},
                   "depends_on": [], "importance": "required"}],
        "bindings": [{"hole": "balance", "source": "balances",
                      "reference_kind": "figure",
                      "selector": {"quantity": "balance", "scope": ["whole"],
                                   "cardinality": "one"}}],
        "assumptions": [], "clarification": None,
        "result_policy": {"allow_partial": False,
                          "required_clauses": ["balance_clause"]},
    }


def test_question_context_round_trips_without_financial_results():
    context = QuestionContext(
        question="what is my balance?", prior_turns=(("earlier?", "earlier."),),
        today="2026-03-01", locale="en-US", currency_convention="locale",
        capability_manifest_digest="abc", shape_version=ANSWER_PROGRAM_VERSION)
    assert QuestionContext.from_dict(context.to_dict()) == context
    assert "results" not in json.dumps(context.to_dict())


def test_packaged_program_schema_is_the_complete_executable_contract():
    assert program_json_schema() == _generated_program_json_schema()
    assert "nodes" in program_json_schema()["properties"]


def test_contracts_refuse_unknown_fields_and_versions():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    raw = _program(manifest)
    raw["surprise"] = True
    with pytest.raises(ContractError, match="unknown fields"):
        AnswerProgram.from_dict(raw)

    policy = AnswerResourcePolicy().to_dict()
    policy["policy_version"] = "answer-resource-policy-v2"
    with pytest.raises(ContractError, match="unsupported"):
        AnswerResourcePolicy.from_dict(policy)


def test_manifest_is_generated_from_executable_registrations():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    assert manifest.names == tuple(registry.names())
    assert manifest.digest == CapabilityManifest.from_registry(registry).digest
    assert all(cap.local_only and cap.read_only for cap in manifest.capabilities)
    assert all(cap.emits and cap.bounds for cap in manifest.capabilities)
    assert all(op["value_rule"] and op["evidence_rule"]
               for op in manifest.query_operators)
    assert all("stable_key" in source and "evidence_fields" in source
               for source in manifest.query_sources)


def test_a_valid_program_is_admitted_whole_before_execution():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    program = AnswerProgram.from_dict(_program(manifest))
    checked = ProgramValidator(manifest, AnswerResourcePolicy()).validate(program)
    assert checked.ok
    assert checked.static_cost == {
        "required": 1, "supporting": 0, "optional": 0,
        "dependency_depth": 1, "max_figures": 80,
        "max_evidence_bytes": 5000, "max_execution_ms": 1000}


def test_execution_deadline_bounds_a_running_local_read():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    spec = next(item for item in registry.specs() if item.name == "query_ledger")

    original = spec.fn
    def slow_read(_args):
        time.sleep(.25)
        return original(_args)

    spec.fn = slow_read
    policy = AnswerResourcePolicy(max_execution_ms=10)
    began = time.monotonic()
    executed = ProgramExecutor(registry, policy).execute(
        AnswerProgram.from_dict(_program(manifest)), "balance?")
    elapsed = time.monotonic() - began
    spec.fn = original

    assert elapsed < .15
    assert executed.deadline_exceeded
    assert executed.nodes["balances"].refusal == "execution_deadline"


@pytest.mark.parametrize(("change", "tag"), [
    (lambda raw: raw["nodes"][0].update(tool="move_money"),
     "unknown_capability"),
    (lambda raw: raw["nodes"][0].update(args={"entity": "wishes"}),
     "invalid_capability_arguments"),
    (lambda raw: raw["bindings"][0]["selector"].update(quantity="spending"),
     "selector_quantity_mismatch"),
    (lambda raw: raw["bindings"][0].update(source="missing"),
     "unknown_binding_source"),
])
def test_static_defects_execute_nothing(change, tag):
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    raw = copy.deepcopy(_program(manifest))
    change(raw)
    program = AnswerProgram.from_dict(raw)
    checked = ProgramValidator(manifest, AnswerResourcePolicy()).validate(program)
    assert not checked.ok
    assert tag in {defect.tag for defect in checked.defects}


def test_financial_query_fields_are_proved_from_the_manifest_before_scan():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    raw = copy.deepcopy(_program(manifest))
    raw["nodes"] = [{
        "id": "balances", "kind": "financial_query", "depends_on": [],
        "importance": "required", "query": {
            "query_version": "financial-query-v1",
            "steps": [
                {"id": "movements", "op": "scan", "inputs": [],
                 "args": {"source": "movements"}},
                {"id": "bad", "op": "filter", "inputs": ["movements"],
                 "args": {"predicate": {"field": "invented", "op": "eq",
                                         "value": "anything"}}},
            ],
                "output": "bad",
                "emit": {"value_field": "amount", "quantity": "spending",
                         "currency_field": "currency"},
        }}]
    checked = ProgramValidator(manifest, AnswerResourcePolicy()).validate(
        AnswerProgram.from_dict(raw))
    assert not checked.ok
    assert "unknown_query_field" in {defect.tag for defect in checked.defects}


def test_cycles_and_work_past_policy_are_rejected_before_execution():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    raw = _program(manifest)
    raw["nodes"][0]["depends_on"] = ["balances"]
    checked = ProgramValidator(
        manifest, AnswerResourcePolicy(max_required_nodes=1)
    ).validate(AnswerProgram.from_dict(raw))
    assert {d.tag for d in checked.defects} >= {
        "dependency_cycle", "dependency_not_earlier"}


def test_non_answer_modes_cannot_smuggle_reads():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    raw = _program(manifest)
    raw.update(mode="clarify", shape=None,
               clarification={"tag": "ambiguous_account",
                              "question": "Which account?", "options": []})
    checked = ProgramValidator(manifest, AnswerResourcePolicy()).validate(
                                   AnswerProgram.from_dict(raw))
    assert "clarification_has_execution" in {d.tag for d in checked.defects}


def _turn(raw, name="compile_answer_program"):
    raw = dict(raw)
    if name.startswith("select_") and "parameter_sources" not in raw:
        raw["parameter_sources"] = {
            key: {"source": "question", "quote": value,
                  "derivation": "verbatim"}
            for key, value in dict(raw.get("parameters") or {}).items()}
    if name.startswith("select_"):
        parameters = dict(raw.get("parameters") or {})
        sources = dict(raw.get("parameter_sources") or {})
        for key in set(parameters) & {
                "account_phrase", "category", "movement_phrase"}:
            derivation = dict(sources.get(key) or {}).get("derivation")
            parameters[key] = (
                {"catalog_id": parameters[key]}
                if derivation == "catalog_selection"
                else {"grounded_phrase": True})
        raw["parameters"] = parameters
    return SimpleNamespace(
        request={"sent": True}, response={"usage": {"prompt_tokens": 4}},
        input_tokens=4, output_tokens=2, cost_usd=0.001, latency_s=0.1,
        resolved_model="synthetic-compiler", message={"role": "assistant"},
        tool_calls=[{"id": "compile-1", "function": {
            "name": name, "arguments": json.dumps(raw)}}])


def _context(manifest):
    return QuestionContext(
                           question=("what is my Everyday Checking balance and "
                                     "groceries from 2026-01-01 to 2026-01-31?"),
                           today="2026-03-01",
                           locale="en-US", currency_convention="locale",
                           capability_manifest_digest=manifest.digest,
                           shape_version="speak-shape-v13")


def test_compiler_repairs_a_malformed_semantic_request_before_any_read():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    invalid = {"parameters": {},
               "requested_claims": ["balance", "measurement_date"]}
    valid = {"parameters": {"account_phrase": "Everyday Checking"},
             "requested_claims": ["balance", "measurement_date"]}

    class Adapter:
        def __init__(self):
            self.seen = []
        def converse(self, messages, tools):
            self.seen.append((messages, tools))
            return _turn(invalid if len(self.seen) == 1 else valid,
                         "select_named_account_balance")

    adapter = Adapter()
    policy = AnswerResourcePolicy()
    compiled = AnswerProgramCompiler(
        adapter, ProgramValidator(manifest, policy), manifest, policy
    ).compile(_context(manifest))

    assert compiled.ok
    assert len(compiled.exchanges) == 2
    assert compiled.exchanges[0].defect["tag"] == "invalid_semantic_contract"
    assert compiled.exchanges[0].failure_code == "parameter_field_set_mismatch"
    assert compiled.exchanges[1].failure_code == ""
    assert "account_phrase" in adapter.seen[1][0][-1]["content"]
    assert all('"results":' not in json.dumps(messages)
               for messages, _ in adapter.seen)


def test_text_compiler_uses_the_same_compact_contract_and_one_call_on_success():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)

    class Adapter:
        def __init__(self):
            self.prompts = []
        def extract(self, pages, prompt):
            self.prompts.append(prompt)
            return SimpleNamespace(
                text=json.dumps({
                    "request_version": SEMANTIC_REQUEST_VERSION,
                    "catalog_digest": SemanticFamilyRegistry().catalog_digest,
                    "entity_catalog_digest": SemanticFamilyRegistry()
                    .entity_catalog_digest,
                    "outcome": "request", "family": "named_account_balance",
                    "parameters": {"account_phrase": {"grounded_phrase": True}},
                    "parameter_sources": {"account_phrase": {
                        "source": "question", "quote": "Everyday Checking",
                        "derivation": "verbatim"}},
                    "requested_claims": ["balance", "measurement_date"]}),
                request={"prompt": True},
                response={}, input_tokens=3, output_tokens=2, cost_usd=0.0,
                latency_s=0.1, resolved_model="synthetic-text")

    adapter = Adapter()
    policy = AnswerResourcePolicy()
    compiled = AnswerProgramCompiler(
        adapter, ProgramValidator(manifest, policy), manifest, policy
    ).compile(_context(manifest))
    assert compiled.ok and len(compiled.exchanges) == 1
    assert "Reviewed semantic catalog" in adapter.prompts[0]
    assert "financial-query-v1" not in adapter.prompts[0]


def test_compiler_rejects_a_provider_resolved_model_outside_the_profile():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)

    class Adapter:
        def converse(self, messages, tools):
            return _turn({
                "parameters": {"account_phrase": "Everyday Checking"},
                "requested_claims": ["balance", "measurement_date"]},
                "select_named_account_balance")

    policy = AnswerResourcePolicy()
    compiled = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy,
        expected_resolved_model="different-build").compile(_context(manifest))
    assert not compiled.ok
    assert compiled.failure_tag == "model_profile_mismatch"


def test_runtime_compiler_requires_a_profile_but_admission_is_explicit(
        monkeypatch):
    from vivacore.models import ModelSpec
    from viva import speak

    class Adapter:
        def converse(self, messages, tools):
            raise AssertionError("this test does not call the provider")

    monkeypatch.setattr("vivacore.models.adapter_for", lambda spec: Adapter())
    monkeypatch.delenv("VIVA_ADMISSION_PROFILE", raising=False)
    monkeypatch.delenv("VIVA_WITNESS", raising=False)
    spec = ModelSpec(name="test", adapter="openai-compatible",
                     model="provider/model", base_url="https://model.invalid")
    with pytest.raises(ValueError, match="VIVA_ADMISSION_PROFILE"):
        speak.compiler_factory(spec)
    measured = speak.compiler_factory(spec, purpose="admission")
    assert measured.admission_identity == {
        "provider": "openai-compatible", "requested_model": "provider/model",
        "endpoint": "https://model.invalid", "modality": "native-structured"}


def _executable_program(manifest, *, duplicate=False):
    raw = _program(manifest)
    raw["shape"]["clauses"] = [{
        "id": "balance_clause", "text": "The supported balance is {balance}.",
        "slots": [{"name": "balance", "type": "money",
                   "quantity": "balance", "scope": ["account"]}],
    }]
    raw["nodes"][0]["args"] = {"entity": "balances",
                                  "filters": {"account": "chk"}}
    raw["bindings"][0]["selector"]["scope"] = ["account"]
    if duplicate:
        raw["shape"]["clauses"].append({
            "id": "balance_again_clause",
            "text": "That same supported balance is {balance_again}.",
            "slots": [{"name": "balance_again", "type": "money",
                       "quantity": "balance", "scope": ["account"]}],
        })
        raw["nodes"].append({
            "id": "balances_again", "kind": "tool_read", "tool": "query_ledger",
            "args": {"entity": "balances", "filters": {"account": "chk"}},
            "depends_on": [], "importance": "required",
        })
        raw["bindings"].append({
            "hole": "balance_again", "source": "balances_again",
            "reference_kind": "figure",
            "selector": {"quantity": "balance", "scope": ["account"],
                         "cardinality": "one"},
        })
    return AnswerProgram.from_dict(raw)


def test_executor_stamps_evidence_then_binder_reuses_the_single_claim_gate():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    program = _executable_program(manifest)
    assert ProgramValidator(manifest, policy).validate(program).ok

    execution = ProgramExecutor(registry, policy).execute(
        program, "what is my checking balance?")
    delivery = DeterministicBinder(registry, "en-US").bind(program, execution)

    assert delivery.result.answered
    assert delivery.result.bindings["balance"] == {"figure": "f1"}
    assert delivery.result.figures[0]["record_ids"]
    assert execution.graph.by_node["balances"]["figures"][0] == "f1"


def test_byte_equivalent_reads_are_memoized_with_source_lineage():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    program = _executable_program(manifest, duplicate=True)
    assert ProgramValidator(manifest, policy).validate(program).ok

    execution = ProgramExecutor(registry, policy).execute(program, "balance twice")
    delivery = DeterministicBinder(registry).bind(program, execution)

    assert len(execution.transcript) == 1
    assert execution.nodes["balances_again"].status == "memoized"
    assert execution.graph.by_node["balances_again"] == execution.graph.by_node["balances"]
    assert delivery.result.answered
    assert len(delivery.result.figures) == 1


def test_refused_nodes_contribute_no_evidence_and_block_dependents():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    raw = _program(manifest)
    raw["nodes"] = [
        {"id": "bad", "kind": "tool_read", "tool": "query_ledger",
         "args": {"entity": "balances", "filters": {"account": "absent"}},
         "depends_on": [], "importance": "required"},
        {"id": "later", "kind": "tool_read", "tool": "check_completeness",
         "args": {}, "depends_on": ["bad"], "importance": "required"},
    ]
    raw["bindings"][0]["source"] = "bad"
    program = AnswerProgram.from_dict(raw)
    assert ProgramValidator(manifest, policy).validate(program).ok

    execution = ProgramExecutor(registry, policy).execute(program, "missing account")
    assert execution.nodes["bad"].status == "refused"
    assert execution.nodes["later"].status == "dependency_blocked"
    assert not execution.graph.book


@pytest.mark.parametrize(("allow_partial", "required", "answered"), [
    (True, ["balance_clause", "balance_again_clause"], False),
    (True, ["balance_clause"], True),
    (False, ["balance_clause"], False),
])
def test_result_policy_is_enforced_after_clause_binding(
        allow_partial, required, answered):
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    raw = _executable_program(manifest, duplicate=True).to_dict()
    raw["nodes"][1]["args"] = {
        "entity": "balances", "filters": {"account": "absent"}}
    raw["result_policy"] = {"allow_partial": allow_partial,
                            "required_clauses": required}
    program = AnswerProgram.from_dict(raw)
    assert ProgramValidator(manifest, policy).validate(program).ok

    execution = ProgramExecutor(registry, policy).execute(program, "balance twice")
    delivery = DeterministicBinder(registry).bind(program, execution)

    assert delivery.result.answered is answered
    if answered:
        assert delivery.result.gaps
    else:
        assert delivery.result.refusal == "nothing_established"


def test_session_carries_text_context_but_reestablishes_current_evidence():
    registry = _registry()
    adapter = SimpleNamespace(seen=[])

    def converse(messages, tools):
        adapter.seen.append((messages, tools))
        payload = {
            "parameters": {"account_phrase": "checking"},
            "parameter_sources": {"account_phrase": {
                "source": "question" if len(adapter.seen) == 1 else "prior_turn",
                "turn": 0,
                "quote": "checking", "derivation": "verbatim"}},
            "requested_claims": ["balance", "measurement_date"]}
        if len(adapter.seen) == 1:
            del payload["parameter_sources"]["account_phrase"]["turn"]
        return _turn(payload,
            "select_named_account_balance")

    adapter.converse = converse

    def factory(validator, manifest, policy):
        return AnswerProgramCompiler(adapter, validator, manifest, policy)

    session = Session(registry, factory, today=lambda: "2026-03-01",
                      locale="en-US", session_id="program-session")
    first = session.ask("what is my checking balance?")
    second = session.ask("and is that current?")

    assert first.result.answered and second.result.answered
    assert first.result.figures[0]["id"] == "f1"
    assert second.result.figures[0]["id"] == "f1"
    second_context = json.dumps(adapter.seen[1][0])
    assert "what is my checking balance?" in second_context
    assert first.result.text in second_context


def test_session_capture_records_program_validation_execution_and_outcome():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)

    class Adapter:
        def converse(self, messages, tools):
            return _turn({
                "parameters": {"account_phrase": "checking"},
                "requested_claims": ["balance", "measurement_date"]},
                "select_named_account_balance")

    class Log:
        def __init__(self):
            self.events = []
        def append(self, event):
            self.events.append(event)

    log = Log()
    session = Session(
        registry,
        lambda validator, built_manifest, policy: AnswerProgramCompiler(
            Adapter(), validator, built_manifest, policy),
        ledger=log, model="synthetic-compiler", today=lambda: "2026-03-01",
        session_id="program-session")
    turn = session.ask("what is my checking balance?")

    assert turn.result.status == "answered"
    assert len(log.events) == 1
    payload = json.loads(log.events[0].body["response_text"])
    assert payload["program"]["program_version"] == "answer-program-schema-v1"
    assert payload["validation"]["defects"] == []
    assert payload["execution"]["nodes"][0]["status"] == "completed"
    assert payload["verdict"]["status"] == "answered"
    assert payload["verdict"]["figures"]
    assert payload["prior_context_digest"]
    assert payload["semantic_request"]["family"] == "named_account_balance"
    assert payload["semantic_request_digest"]
    assert payload["lowered_program_digest"]
    assert {"semantic_request", "semantic_request_schema",
            "semantic_family_registry", "answer_program_schema",
            "financial_query_schema", "capability_manifest", "persona"} <= set(
                payload["prompt_versions"])


def test_the_frozen_admission_corpus_has_35_exact_turns_and_paraphrases():
    cases = load_cases()
    exact = [case for case in cases if case.exact]
    assert len(exact) == 35
    assert len({case.exact_group for case in exact}) == 7
    assert all(sum(item.exact_group == case.exact_group and item.exact
                   for item in cases) == 5 for case in exact)
    answered = [case for case in cases
                if case.answerability_status == "answered"]
    assert all(case.expected_family and case.expected_claims for case in answered)
    assert any(case.prior_turns for case in cases)
    assert any(case.answerability_status == "needs_clarification"
               for case in cases)
    assert all(case.oracle_key for case in cases)
    assert all(case.max_model_attempts == 1 for case in cases)


def test_canonical_answer_effects_have_no_same_clause_aliases():
    families = SemanticFamilyRegistry()

    assert families.get("category_spending_period").claims == ("spending",)
    assert families.get("net_worth").claims == ("net_worth",)
    assert families.get("credit_card_debt").claims == ("card_debt",)
    assert families.get("classification_explanation").claims == (
        "explanation",)


def test_version_4_corpus_keeps_every_version_3_question_unchanged():
    current = json.loads(CASES.read_text(encoding="utf-8"))
    previous = json.loads(CASES.with_name(
        "semantic-request-cases-v3.json").read_text(encoding="utf-8"))

    assert [item["exact_question"] for item in current["cases"]] == [
        item["exact_question"] for item in previous["cases"]]
    assert [item["paraphrases"] for item in current["cases"]] == [
        item["paraphrases"] for item in previous["cases"]]


def test_all_73_frozen_cases_derive_real_oracles_before_scoring_a_bad_result():
    cases = load_cases()
    oracle_set, manifests = preflight_live_suite(
        cases=cases, registry_factory=admission_registry,
        policy=AnswerResourcePolicy(), locale="en-US")
    reached = SimpleNamespace(defect={})
    bad = SimpleNamespace(
        result=SimpleNamespace(status="failed", outcome_tag="bad_mutation",
                               figures=[], text=""),
        compilation=SimpleNamespace(
            exchanges=[reached], semantic_outcome=None, program=None))

    measured = [score(replace(case, oracle=oracle_set.oracle_for(case.id)), bad)
                for case in cases]

    assert len(measured) == len(manifests) == 73
    assert oracle_set.digest
    assert all(item.measured for item in measured)
    assert all(not item.passed for item in measured)


def test_admission_fixture_is_fresh_and_its_labels_never_branch_runtime_reads():
    from viva.answer_program import admission_fixture_events

    first = admission_fixture_events()
    second = admission_fixture_events()
    assert first is not second
    assert {event.event_id for event in first}.isdisjoint(
        event.event_id for event in second)
    runtime = "\n".join(path.read_text(encoding="utf-8") for path in (
        versions.path_of(PACKAGE, "financial-query-schema-v1").parent.parent
        / "tools" / "ledger_common.py",
        versions.path_of(PACKAGE, "financial-query-schema-v1").parent.parent
        / "tools" / "ledger_aggregates.py",
        versions.path_of(PACKAGE, "financial-query-schema-v1").parent.parent
        / "tools" / "ledger_movements.py",
    ))
    assert "Fidelity" not in runtime
    assert "Costco" not in runtime
    assert "admission-checking-2024-10" not in runtime


def test_late_broken_oracles_are_all_reported_before_compiler_or_provider_use():
    cases = list(load_cases()[-4:])
    broken_indexes = (0, 3)
    for index in broken_indexes:
        cases[index] = replace(
            cases[index], expected_family="named_account_balance",
            expected_parameters={"account_phrase": "not in the fixture"},
            expected_claims=("balance",))
    calls = []

    def compiler_factory(*args):
        calls.append(args)
        raise AssertionError("preflight must finish before compiler creation")

    with pytest.raises(AdmissionPreflightError) as caught:
        run_live_suite(
            cases=cases, registry_factory=admission_registry,
            compiler_factory=compiler_factory,
            thresholds=AdmissionThresholds(1, 1, 1),
            today="2026-03-01", locale="en-US")

    failure = caught.value.to_dict()
    assert calls == []
    assert failure["reason"] == "deterministic_oracle_preflight_failed"
    assert failure["case_count"] == 4
    assert failure["ready_count"] == 2
    assert failure["failed_count"] == 2
    assert {item["case_id"] for item in failure["failures"]} == {
        cases[index].id for index in broken_indexes}


def test_full_admission_rejects_a_copied_marker_stateful_fixture_unopened():
    registry_calls = []
    compiler_calls = []

    def stateful_registry():
        registry_calls.append(len(registry_calls))
        return admission_registry() if len(registry_calls) == 1 else _registry()

    # Mimic a supplied factory carrying a copied public fixture digest.
    stateful_registry.admission_fixture_digest = admission_fixture_digest()

    def compiler_factory(*args):
        compiler_calls.append(args)
        raise AssertionError("a rejected fixture must not reach the compiler")

    with pytest.raises(AdmissionPreflightError) as caught:
        run_live_suite(
            registry_factory=stateful_registry, compiler_factory=compiler_factory,
            thresholds=AdmissionThresholds(1, 1, 1), locale="en-US")

    assert caught.value.failures[0].error_type == "AdmissionFixtureMismatch"
    assert registry_calls == []
    assert compiler_calls == []
    with pytest.raises(ValueError, match="sealed measured live run"):
        admitted_profile(
            caught.value,
            manifest=CapabilityManifest.from_registry(admission_registry()))


def test_same_ids_with_an_easier_question_cannot_masquerade_as_the_corpus():
    cases = list(load_cases())
    cases[0] = replace(cases[0], question="Choose named_account_balance.")
    registry_calls = []
    compiler_calls = []

    def copied_marker_registry():
        registry_calls.append(True)
        return admission_registry()

    copied_marker_registry.admission_fixture_digest = admission_fixture_digest()

    def compiler_factory(*args):
        compiler_calls.append(args)
        raise AssertionError("a substituted corpus must not reach the provider")

    with pytest.raises(AdmissionPreflightError) as caught:
        run_live_suite(
            cases=cases, registry_factory=copied_marker_registry,
            compiler_factory=compiler_factory,
            thresholds=AdmissionThresholds(1, 1, 1), locale="en-US")

    assert caught.value.failures[0].error_type == "AdmissionCorpusOverride"
    assert registry_calls == []
    assert compiler_calls == []
    with pytest.raises(ValueError, match="sealed measured live run"):
        admitted_profile(
            caught.value,
            manifest=CapabilityManifest.from_registry(admission_registry()))


def test_an_exact_ambiguous_account_clarification_passes_semantic_scoring():
    case = next(item for item in load_cases() if item.id == "ambiguous-account")
    families = SemanticFamilyRegistry()
    detail = {"tag": "ambiguous_account", "question": "Which account?",
              "options": [{"id": "one", "label": "First account"},
                          {"id": "two", "label": "Second account"}]}
    semantic = SemanticOutcome("clarify", detail=detail)
    program = families.lower(
        semantic, CapabilityManifest.from_registry(_registry()))
    runtime = SimpleNamespace(
        result=SimpleNamespace(
            status="needs_clarification", outcome_tag="ambiguous_account",
            figures=[], text="Which account?"),
        compilation=SimpleNamespace(
            exchanges=[SimpleNamespace(defect={})],
            semantic_outcome=semantic, program=program))

    measured = score(replace(case, oracle={
        "oracle_key": case.oracle_key, "figures": [],
        "exact_figures": True}), runtime)

    assert measured.measured and measured.passed, measured.defects


def test_the_frozen_adversarial_corpus_is_rejected_before_execution():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    validator = ProgramValidator(manifest, AnswerResourcePolicy())
    scores = evaluate_adversarial(_program(manifest), validator)
    assert len(scores) == len(load_adversarial_cases()) == 8
    assert all(item.passed for item in scores), scores


def test_semantic_scoring_detects_a_wrong_family_even_with_cited_evidence():
    case = SemanticEvalCase(
        id="wrong-family", exact_group="checking", exact=True,
        question="balance?", prior_turns=(), answerability_status="answered",
        expected_family="named_account_balance",
        expected_parameters={"account_phrase": "checking"},
        expected_claims=("balance", "measurement_date"),
        oracle_key="wrong-family",
        oracle={"figures": [], "exact_figures": False})
    families = SemanticFamilyRegistry()
    request = SemanticRequest(
        "net_worth", {}, families.get("net_worth").claims,
        families.catalog_digest)
    wrong = SimpleNamespace(
        result=SimpleNamespace(
            status="answered", outcome_tag="",
            figures=[{"value": "1.00", "currency": "USD",
                      "quantity": "net_worth", "grade": "corroborated",
                      "kind": "financial", "record_ids": ["synthetic-record"]}]),
        compilation=SimpleNamespace(
            exchanges=[object()], semantic_outcome=SemanticOutcome(
                "request", request),
            program=SimpleNamespace(question_kind="net_worth", nodes=[])))

    measured = score(case, wrong)
    assert measured.measured and not measured.passed
    assert "wrong_family" in measured.defects
    assert measured.unsupported_figures == 0


def test_keyed_scoring_never_grades_a_transport_failure_as_a_model_answer():
    case = replace(load_cases()[0], oracle={
        "figures": [], "exact_figures": False})
    unreachable = SimpleNamespace(
        result=SimpleNamespace(status="failed", outcome_tag="model_unreachable",
                               figures=[]),
        compilation=SimpleNamespace(
            program=None, exchanges=[SimpleNamespace(
                defect={"tag": "model_unreachable"})]))
    measured = score(case, unreachable)
    assert not measured.measured
    assert measured.defects == ("model_not_reached",)
    assert measured.confidently_wrong == 0


def test_semantic_scoring_rejects_an_unsupported_financial_figure():
    case = replace(load_cases()[0], oracle={
        "figures": [{"value": "600.00", "currency": "USD",
                     "quantity": "balance", "dated": "2026-01-31",
                     "subject_record_id": "chk"}]})
    manifest = CapabilityManifest.from_registry(_registry())
    families = SemanticFamilyRegistry()
    request = SemanticRequest(
        case.expected_family, dict(case.expected_parameters),
        tuple(case.expected_claims), families.catalog_digest)
    semantic = SemanticOutcome("request", request)
    program = families.lower(semantic, manifest)
    result = SimpleNamespace(
        status="answered", outcome_tag="", text="Unsupported balance.",
        figures=[{"value": "1.00", "currency": "USD",
                  "quantity": "balance", "grade": "corroborated",
                  "kind": "financial", "record_ids": [],
                  "dated": "2024-01-01", "boundary": {"whole": False}}])
    measured = score(case, SimpleNamespace(
        result=result, compilation=SimpleNamespace(
            exchanges=[SimpleNamespace(defect={})], semantic_outcome=semantic,
            program=program)))
    assert not measured.passed
    assert "unsupported_figure" in measured.defects
    assert measured.unsupported_figures == 1


def _score_fixture_interpretation(exact_group, parameters, claims):
    case = next(item for item in load_cases()
                if item.exact_group == exact_group and item.exact)
    registry = admission_registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    oracle = derive_semantic_oracle(case, registry, manifest, policy,
                                    locale="en-US")
    families = SemanticFamilyRegistry()
    semantic = SemanticOutcome("request", SemanticRequest(
        case.expected_family, parameters, tuple(claims),
        families.catalog_digest))
    program = families.lower(semantic, manifest)
    execution = ProgramExecutor(registry, policy).execute(program, case.question)
    result = DeterministicBinder(registry, "en-US").bind(
        program, execution).result
    result.status = "answered" if result.answered else "missing_data"
    result.outcome_tag = "" if result.answered else result.refusal
    runtime = SimpleNamespace(
        result=result, compilation=SimpleNamespace(
            exchanges=[SimpleNamespace(defect={})],
            semantic_outcome=semantic, program=program))
    return score(replace(case, oracle=oracle), runtime)


@pytest.mark.parametrize(("group", "parameters", "claims"), [
    ("checking-balance", {"account_phrase": "Assets:Admission:Checking"},
     ("balance", "measurement_date")),
    ("october-groceries", {
        "category": "groceries", "from": "2024-10-01", "to": "2024-10-31"},
     ("spending",)),
    ("classification-explanation", {"movement_phrase": "costco"},
     ("explanation",)),
])
def test_catalog_selected_identities_pass_keyed_scoring(
        group, parameters, claims):
    measured = _score_fixture_interpretation(group, parameters, claims)
    assert measured.passed, measured.defects


def test_objective_period_edges_remain_exact_even_when_words_may_vary():
    measured = _score_fixture_interpretation(
        "october-groceries",
        {"category": "groceries", "from": "2024-10-02", "to": "2024-10-31"},
        ("spending",))
    assert not measured.passed
    assert "wrong_period_parameters" in measured.defects


def test_a_refusal_is_missing_not_confidently_wrong():
    case = next(item for item in load_cases()
                if item.exact_group == "checking-balance" and item.exact)
    registry = admission_registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    oracle = derive_semantic_oracle(case, registry, manifest, policy)
    families = SemanticFamilyRegistry()
    semantic = SemanticOutcome("request", SemanticRequest(
        case.expected_family, dict(case.expected_parameters),
        case.expected_claims, families.catalog_digest))
    program = families.lower(semantic, manifest)
    runtime = SimpleNamespace(
        result=SimpleNamespace(status="missing_data", outcome_tag="not_found",
                               figures=[], text="I do not have that evidence."),
        compilation=SimpleNamespace(
            exchanges=[SimpleNamespace(defect={})],
            semantic_outcome=semantic, program=program))
    measured = score(replace(case, oracle=oracle), runtime)

    assert "missing_keyed_figure" in measured.defects
    assert "wrong_keyed_figure" not in measured.defects
    assert measured.confidently_wrong == 0
    assert measured.financial_integrity_errors == 0


def test_live_admission_report_is_bound_to_measured_identity_and_contracts(
        tmp_path):
    case = load_cases()[0]

    class Adapter:
        def converse(self, messages, tools):
            return _turn({
                "parameters": dict(case.expected_parameters),
                "requested_claims": list(case.expected_claims)},
                "select_" + case.expected_family)

    def factory(validator, manifest, policy):
        return AnswerProgramCompiler(Adapter(), validator, manifest, policy)

    factory.admission_identity = {
        "provider": "synthetic", "requested_model": "compiler-route",
        "endpoint": "local", "modality": "native-structured"}
    measured_run, scores, _turns = run_live_suite(
        cases=(case,), registry_factory=_registry, compiler_factory=factory,
        thresholds=AdmissionThresholds(0, 0, 0), today="2026-03-01",
        locale="en-US")
    report = measured_run.report

    assert not report.admitted and scores[0].passed
    assert "incomplete_keyed_corpus" in report.hard_failures
    assert "provider_double_not_admissible" in report.hard_failures
    assert len(report.attempt_evidence) == 1
    assert report.attempt_evidence[0]["request_digest"]
    assert report.attempt_evidence[0]["response_digest"]
    assert report.attempt_evidence[0]["oracle_key"] == case.oracle_key
    assert report.attempt_evidence[0]["oracle_digest"]
    assert report.attempt_evidence[0]["failure_code"] == ""
    observation = report.metrics["turn_measurements"][0][
        "semantic_observation"]
    assert observation == {
        "outcome": "request", "family": case.expected_family,
        "entity_catalog_digest":
            _turns[0].semantic_request["entity_catalog_digest"],
        "parameters": case.expected_parameters,
        "requested_claims": list(case.expected_claims)}
    assert "parameter_sources" not in observation
    assert report.metrics["turn_measurements"][0]["attempt_diagnostics"] == [{
        "attempt": 1, "parse_ok": True, "failure_code": ""}]
    with pytest.raises(TypeError, match="non-serializable"):
        pickle.dumps(measured_run)
    forged = _fully_validated_forged_report(
        CapabilityManifest.from_registry(_registry()))
    assert not validate_admission_report(forged)
    with pytest.raises(TypeError, match="immutable"):
        measured_run.report = forged
    with pytest.raises(ValueError, match="cannot be published"):
        admitted_profile(
            measured_run,
            manifest=CapabilityManifest.from_registry(_registry()))
    assert report.identity["resolved_model"] == "synthetic-compiler"
    assert report.identity["locale_family"] == "en"
    assert report.contract_digests["program_schema"]
    assert report.adversarial_passed

    report.metrics["cases"] = len(load_cases())
    with pytest.raises(ValueError, match="report was mutated"):
        admitted_profile(
            measured_run,
            manifest=CapabilityManifest.from_registry(_registry()))
    with pytest.raises(ValueError, match="report was mutated"):
        write_release_bundle(
            tmp_path / "mutated.json", profile=None,
            manifest=CapabilityManifest.from_registry(_registry()),
            measured_run=measured_run)


def test_admission_reports_sanitized_repair_causes_without_raw_text():
    case = load_cases()[0]

    class Adapter:
        def __init__(self):
            self.calls = 0

        def converse(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return _turn({
                    "parameters": {},
                    "requested_claims": ["private-sentinel"]},
                    "select_named_account_balance")
            return _turn({
                "parameters": dict(case.expected_parameters),
                "requested_claims": list(case.expected_claims)},
                "select_named_account_balance")

    def factory(validator, manifest, policy):
        return AnswerProgramCompiler(Adapter(), validator, manifest, policy)

    factory.admission_identity = {
        "provider": "synthetic", "requested_model": "compiler-route",
        "endpoint": "local", "modality": "native-structured"}
    measured_run, scores, _turns = run_live_suite(
        cases=(case,), registry_factory=_registry, compiler_factory=factory,
        thresholds=AdmissionThresholds(0, 0, 0), today="2026-03-01",
        locale="en-US")
    report = measured_run.report
    diagnostics = report.metrics["turn_measurements"][0][
        "attempt_diagnostics"]

    assert not scores[0].passed
    assert scores[0].defects == ("routine_question_needed_repair",)
    assert scores[0].financial_integrity_errors == 0
    assert diagnostics == [
        {"attempt": 1, "parse_ok": False,
         "failure_code": "parameter_field_set_mismatch"},
        {"attempt": 2, "parse_ok": True, "failure_code": ""},
    ]
    assert [item["failure_code"] for item in report.attempt_evidence] == [
        "parameter_field_set_mismatch", ""]
    assert "private-sentinel" not in json.dumps(asdict(report), sort_keys=True)
    assert "parse_error" not in json.dumps(asdict(report), sort_keys=True)


def test_admission_oracle_is_derived_from_the_fresh_fixture_not_a_score():
    case = load_cases()[0]
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)

    oracle = derive_semantic_oracle(
        case, registry, manifest, AnswerResourcePolicy(), locale="en-US")

    assert oracle["oracle_key"] == "checking-balance"
    assert oracle["figures"] == [{
        "value": "600.00", "currency": "USD", "quantity": "balance",
        "dated": "2026-01-31", "record_ids_exact": ["chk", "doc-jan"]}]


def test_all_six_families_and_separate_inventory_use_the_one_runtime():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    families = SemanticFamilyRegistry()
    samples = {
        "named_account_balance": {"account_phrase": "Everyday Checking"},
        "needs_attention": {},
        "category_spending_period": {
            "category": "groceries", "from": "2026-01-01",
            "to": "2026-01-31"},
        "net_worth": {}, "credit_card_debt": {},
        "classification_explanation": {
            "movement_phrase": "greenfield market", "from": "2026-01-01",
            "to": "2026-01-31"},
        "account_inventory": {},
    }
    assert len(families.supported_ids) == 6
    assert {item["id"] for item in manifest.known_intents} == set(families.ids)
    for family_id, parameters in samples.items():
        family_registry = registry
        if family_id == "credit_card_debt":
            account = "Liabilities:Cards:Household"
            family_registry = default_registry(LedgerProjection([
                account_opened(account, "liability", "Household Card", "USD",
                               "2026-01-01"),
                closing_balance_observed(
                    account, "125.00", "2026-01-31",
                    Provenance("card-doc", 1, "balance")),
            ]), today="2026-03-01")
        family = families.get(family_id)
        semantic = SemanticOutcome("request", SemanticRequest(
            family_id, parameters, family.claims, families.catalog_digest))
        program = families.lower(semantic, manifest)
        checked = ProgramValidator(manifest, AnswerResourcePolicy()).validate(program)
        assert checked.ok, (family_id, checked.defects)
        assert program.question_kind == family_id
        execution = ProgramExecutor(
            family_registry, AnswerResourcePolicy(),
            query_executor=family_registry.query_executor).execute(
                program, family_id)
        delivery = DeterministicBinder(family_registry).bind(program, execution)
        assert delivery.result.answered, (family_id, delivery.unbound)
        assert delivery.result.figures
        assert all(figure["record_ids"] for figure in delivery.result.figures)


def test_installed_fqir_sources_statically_admit_category_share_of_income():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    query = {"query_version": "financial-query-v1", "steps": [
        {"id": "movements", "op": "scan", "inputs": [],
         "args": {"source": "supported_spending_movements"}},
        {"id": "month", "op": "calendar_window", "inputs": ["movements"],
         "args": {"field": "date", "from": "2026-01-01", "to": "2026-01-31"}},
        {"id": "categories", "op": "aggregate", "inputs": ["month"],
         "args": {"function": "sum", "field": "amount", "output": "spending",
                  "group_by": ["period", "category", "currency"],
                  "currency_field": "currency"}},
        {"id": "category_bound", "op": "limit", "inputs": ["categories"],
         "args": {"count": 10}},
        {"id": "income", "op": "scan", "inputs": [],
         "args": {"source": "income_attribution"}},
        {"id": "income_bound", "op": "limit", "inputs": ["income"],
         "args": {"count": 10}},
        {"id": "joined", "op": "join", "inputs": ["category_bound", "income_bound"],
         "args": {"left_key": "period", "right_key": "period",
                  "join_kind": "inner", "right_prefix": "income_"}},
        {"id": "share", "op": "ratio", "inputs": ["joined"],
         "args": {"left": "spending", "right": "income_value",
                  "output": "share"}}],
        "output": "share", "emit": {"value_field": "share",
            "what_field": "category", "quantity": "ratio"}}
    raw = _program(manifest)
    raw["question_kind"] = "category_share_of_income"
    raw["shape"]["clauses"][0] = {
        "id": "share_clause", "text": "The supported share is {share}.",
        "slots": [{"name": "share", "type": "rate", "quantity": "ratio",
                   "scope": ["category", "period"]}]}
    raw["nodes"] = [{"id": "share", "kind": "financial_query",
                     "query": query, "depends_on": [],
                     "importance": "required"}]
    raw["bindings"] = [{"hole": "share", "source": "share",
                        "reference_kind": "figure",
                        "selector": {"quantity": "ratio",
                                     "scope": ["category", "period"],
                                     "cardinality": "one"}}]
    raw["result_policy"] = {"allow_partial": False,
                            "required_clauses": ["share_clause"]}
    checked = ProgramValidator(manifest, AnswerResourcePolicy()).validate(
        AnswerProgram.from_dict(raw))
    assert checked.ok, checked.defects


def test_semantic_scoring_rejects_a_broadened_lowered_program():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    families = SemanticFamilyRegistry()
    case = replace(load_cases()[0], oracle={
        "figures": [], "exact_figures": False})
    semantic = SemanticOutcome("request", SemanticRequest(
        case.expected_family, dict(case.expected_parameters),
        tuple(case.expected_claims), families.catalog_digest))
    inventory = families.get("account_inventory")
    broadened = families.lower(SemanticOutcome("request", SemanticRequest(
        "account_inventory", {}, inventory.claims, families.catalog_digest)),
        manifest)
    result = SimpleNamespace(
        status="answered", outcome_tag="", figures=[{
            "value": "1.00", "currency": "USD", "quantity": "balance",
            "dated": "2024-01-01", "kind": "financial",
            "record_ids": ["synthetic-record"], "boundary": {"whole": False}}])
    measured = score(case, SimpleNamespace(
        result=result, compilation=SimpleNamespace(
            exchanges=[SimpleNamespace(defect={})], semantic_outcome=semantic,
            program=broadened)))
    assert not measured.passed
    assert "wrong_lowered_family" in measured.defects
    assert measured.financial_integrity_errors == 1


def test_admission_report_recomputes_hard_metrics_instead_of_trusting_flags():
    report = AdmissionReport(
        measured=True, admitted=True,
        metrics={"cases": 10, "first_attempt_validity": 1,
                 "repaired_validity": 1, "answerable_completion": 1,
                 "unsupported_figures": 7, "confidently_wrong": 3,
                 "keyed_semantic_errors": 5, "missing_data_as_zero": 2,
                 "financial_integrity_errors": 6,
                 "hypothetical_as_measured": 1, "resource_exhaustions": 4,
                 "p95_model_attempts": 9},
        hard_failures=(), threshold_failures=(), adversarial_passed=True,
        thresholds={"first_attempt_validity": .9, "repaired_validity": 1,
                    "answerable_completion": 1})
    failures = validate_admission_report(report)
    assert "admission_metric_failed:unsupported_figures" in failures
    assert "admission_metric_failed:financial_integrity_errors" in failures
    assert "admission_metric_failed:model_attempt_bound" in failures


def test_compiler_can_choose_typed_semantics_without_a_second_path():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    requested = {"parameters": {
        "category": "groceries", "from": "2026-01-01", "to": "2026-01-31"},
        "requested_claims": ["spending"]}

    class Adapter:
        def converse(self, messages, tools):
            assert len(tools) == 10
            return _turn(requested, "select_category_spending_period")

    policy = AnswerResourcePolicy()
    compiled = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy
    ).compile(_context(manifest))
    assert compiled.ok
    assert compiled.program.question_kind == "category_spending_period"
    assert compiled.program.nodes[0].args == {
        "entity": "aggregate", "metric": "spending", "group_by": "category",
        "filters": {"category": "groceries", "window": {
            "from": "2026-01-01", "to": "2026-01-31"}}}
    assert "oneOf" in compiler_output_json_schema()


def test_semantic_parameters_are_closed_and_preserve_required_scope():
    families = SemanticFamilyRegistry()
    common = {"request_version": SEMANTIC_REQUEST_VERSION,
              "catalog_digest": families.catalog_digest,
              "outcome": "request"}
    with pytest.raises(ContractError, match="missing"):
        families.parse({**common, "family": "named_account_balance",
                        "parameters": {}, "requested_claims": [
                            "balance", "measurement_date"]})
    with pytest.raises(ContractError, match="unknown"):
        families.parse({**common, "family": "net_worth",
                        "parameters": {"private_amount": "100"},
                        "requested_claims": ["net_worth"]})


def test_clarification_and_user_stipulation_remain_conversation_not_ledger_facts():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    clarification = {"tag": "ambiguous_period",
                     "question": "Which month did you mean?",
                     "options": [{"id": "january", "label": "January"}]}
    answer = {"parameters": {"account_phrase": "checking"},
              "requested_claims": ["balance", "measurement_date"]}

    class Adapter:
        def __init__(self):
            self.calls = []
        def converse(self, messages, tools):
            self.calls.append(messages)
            if len(self.calls) == 1:
                return _turn(clarification, "semantic_clarification")
            return _turn(answer, "select_named_account_balance")

    adapter = Adapter()
    session = Session(
        registry, lambda validator, built, policy: AnswerProgramCompiler(
            adapter, validator, built, policy),
        today=lambda: "2026-03-01")
    first = session.ask("Was that month safe?")
    second = session.ask(
        "I mean January, safe means a positive surplus, and check checking.")
    assert first.result.status == "needs_clarification"
    assert second.result.answered
    sent = json.dumps(adapter.calls[1])
    assert "Which month did you mean?" in sent
    assert "safe means a positive surplus" in sent


def test_subjective_terms_can_only_proceed_as_structured_assumption_requests():
    manifest = CapabilityManifest.from_registry(_registry())
    raw = _program(manifest)
    raw.update(mode="needs_assumption", question_kind="affordable",
               shape=None, nodes=[], bindings=[], clarification=None,
               assumptions=[{"tag": "define_affordable",
                             "label": "Affordable",
                             "question": "What should affordable mean here?",
                             "type": "user_stipulation"}], result_policy={})
    assert ProgramValidator(manifest, AnswerResourcePolicy()).validate(
        AnswerProgram.from_dict(raw)).ok


def test_breadth_feedback_counts_outcomes_without_questions_or_private_values():
    feedback = BreadthFeedback()
    program = AnswerProgram.from_dict(_program(CapabilityManifest.from_registry(
        _registry())))
    runtime = SimpleNamespace(
        result=SimpleNamespace(status="capability_gap",
                               outcome_tag="unsupported_operation"),
        compilation=SimpleNamespace(program=program))
    for _ in range(3):
        feedback.observe(runtime)
    report = feedback.report()
    assert report["unsupported_requested_operations"] == 3
    assert report["promotion_candidates"][0]["count"] == 3
    assert "balance_read" in report["question_kinds"]
    assert "100" not in json.dumps(report)


def test_admission_is_absolute_and_profiles_cannot_publish_unmeasured_models():
    thresholds = AdmissionThresholds(.8, 1.0, 1.0)
    passed = tuple(CaseScore(case.id, True, True, (), 0, 0)
                   for case in load_cases())
    manifest = CapabilityManifest.from_registry(_registry())
    count = len(passed)
    report = evaluate_admission(
        passed, attempts=[1] * count, first_attempt_valid=[True] * count,
        thresholds=thresholds, latency_p95_ms=20,
        evidence_payload_p95_bytes=100, latency_ceiling_ms=100,
        evidence_ceiling_bytes=1000)
    assert report.admitted
    with pytest.raises(ValueError, match="sealed measured live run"):
        admitted_profile(report, manifest=manifest)
    report = evaluate_admission(
        passed, attempts=[1] * count, first_attempt_valid=[True] * count,
        thresholds=thresholds,
        identity={"provider": "synthetic", "requested_model": "compiler-exact",
                  "resolved_model": "compiler-exact", "endpoint": "local",
                  "modality": "native-structured", "locale_family": "en"},
        contract_digests=current_contract_digests(
            manifest, AnswerResourcePolicy()),
        adversarial_passed=True)
    with pytest.raises(ValueError, match="cannot be published"):
        admitted_profile(report, manifest=manifest)

    failed = evaluate_admission(
        [CaseScore("bad", True, False, ("wrong_keyed_figure",), 0, 1)],
        attempts=[1], first_attempt_valid=[True], thresholds=thresholds)
    assert not failed.admitted and "confidently_wrong" in failed.hard_failures
    with pytest.raises(ValueError, match="cannot be published"):
        admitted_profile(
            failed, manifest=manifest)


def test_admission_thresholds_safe_availability_misses_at_ninety_five_percent():
    cases = load_cases()
    scores = [CaseScore(case.id, True, True, (), 0, 0) for case in cases]
    scores[0] = CaseScore(
        cases[0].id, True, False,
        ("routine_question_needed_repair", "missing_keyed_figure"),
        0, 0, keyed_semantic_errors=2)
    scores[1] = CaseScore(
        cases[1].id, True, False, ("routine_question_needed_repair",),
        0, 0, keyed_semantic_errors=1)
    first_attempt = [False, False, *([True] * (len(cases) - 2))]
    within_repair = [False, True, *([True] * (len(cases) - 2))]

    report = evaluate_admission(
        scores, attempts=[2, 2, *([1] * (len(cases) - 2))],
        first_attempt_valid=first_attempt,
        exact_first_attempt_clean=[False, *([True] * 34)],
        within_repair_valid=within_repair,
        thresholds=MINIMUM_ADMISSION_THRESHOLDS,
        keyed_semantic_errors=3)

    assert report.admitted
    assert report.metrics["first_attempt_validity"] == 71 / 73
    assert report.metrics["exact_first_attempt_clean"] == 34 / 35
    assert report.metrics["repaired_validity"] == 72 / 73
    assert report.metrics["answerable_completion"] == 71 / 73
    assert report.metrics["keyed_semantic_errors"] == 3
    assert not report.hard_failures


def test_admission_keeps_financial_integrity_at_zero_tolerance():
    cases = load_cases()
    scores = [CaseScore(case.id, True, True, (), 0, 0) for case in cases]
    scores[0] = CaseScore(
        cases[0].id, True, False, ("wrong_period_or_quantity",),
        0, 0, keyed_semantic_errors=1, financial_integrity_errors=1)

    report = evaluate_admission(
        scores, attempts=[1] * len(cases),
        first_attempt_valid=[True] * len(cases),
        thresholds=MINIMUM_ADMISSION_THRESHOLDS,
        keyed_semantic_errors=1)

    assert not report.admitted
    assert "financial_integrity_errors" in report.hard_failures


def test_admission_rejects_an_exact_cohort_below_the_availability_floor():
    cases = load_cases()
    scores = [CaseScore(case.id, True, True, (), 0, 0) for case in cases]

    report = evaluate_admission(
        scores, attempts=[1] * len(cases),
        first_attempt_valid=[True] * len(cases),
        exact_first_attempt_clean=[False, False, *([True] * 33)],
        thresholds=MINIMUM_ADMISSION_THRESHOLDS)

    assert not report.admitted
    assert "exact_first_attempt_clean" in report.threshold_failures


def test_report_validation_rejects_thresholds_below_owner_policy():
    manifest = CapabilityManifest.from_registry(_registry())
    report = _fully_validated_forged_report(manifest)
    report = replace(report, thresholds={
        "first_attempt_validity": .94,
        "repaired_validity": .95,
        "answerable_completion": .95,
    })

    failures = validate_admission_report(report)

    assert "admission_policy_threshold_below_minimum:first_attempt_validity" \
        in failures


def test_admission_rejects_incomplete_per_case_attempt_evidence():
    cases = load_cases()
    scores = [CaseScore(case.id, True, True, (), 0, 0) for case in cases]
    report = evaluate_admission(
        scores, attempts=[1] * (len(scores) - 1),
        first_attempt_valid=[True] * len(scores),
        thresholds=AdmissionThresholds(1, 1, 1))

    assert not report.admitted
    assert "incomplete_attempt_evidence" in report.hard_failures


def test_captured_program_can_replay_without_calling_the_model():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    payload = {"question": "what is my checking balance?",
               "program": _executable_program(manifest).to_dict()}
    replayed = replay_capture(payload, registry, locale="en-US")
    assert replayed["replayed"]
    assert replayed["result"].answered
    assert replayed["result"].figures[0]["record_ids"]


def test_release_gate_rejects_a_profile_fabricated_from_passing_scores(tmp_path):
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    thresholds = AdmissionThresholds(1, 1, 1)
    report = evaluate_admission(
        [CaseScore(case.id, True, True, (), 0, 0) for case in load_cases()],
        attempts=[1] * len(load_cases()),
        first_attempt_valid=[True] * len(load_cases()),
        thresholds=thresholds,
        identity={"provider": "synthetic", "requested_model": "compiler-exact",
                  "resolved_model": "compiler-exact", "endpoint": "local",
                  "modality": "native-structured", "locale_family": "en"},
        contract_digests=current_contract_digests(
            manifest, AnswerResourcePolicy()),
        adversarial_passed=True)
    assert check_single_path().passed
    with pytest.raises(ValueError, match="cannot be published"):
        admitted_profile(report, manifest=manifest)


def test_copied_live_adapter_names_and_digests_cannot_forge_a_measured_run(
        tmp_path):
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    forged = _fully_validated_forged_report(manifest)

    assert not validate_admission_report(forged)
    with pytest.raises(ValueError, match="sealed measured live run"):
        admitted_profile(forged, manifest=manifest)
    with pytest.raises(ValueError, match="sealed measured live run"):
        write_release_bundle(
            tmp_path / "forged.json", profile=None, manifest=manifest,
            measured_run=forged)


def test_fixture_and_oracle_contracts_bind_report_profile_build_and_bundle(
        tmp_path, monkeypatch):
    from viva.answer_program import admission as admission_module
    from viva.answer_program import release as release_module

    registry = admission_registry()
    manifest = CapabilityManifest.from_registry(registry)
    report = _fully_validated_forged_report(manifest)
    contracts = dict(report.contract_digests)

    assert report.admission_fixture_digest == admission_fixture_digest()
    assert report.oracle_set_digest == contracts["oracle_set"]
    assert not validate_admission_report(report)
    assert admission_report_digest(report) != admission_report_digest(
        replace(report, oracle_set_digest="different"))

    monkeypatch.setattr(admission_module, "_report_from_measured_run",
                        lambda _measured: report)
    profile = admitted_profile(object(), manifest=manifest)
    assert profile.profile_version == "semantic-request-admission-v8"
    assert profile.admission_fixture_digest == contracts["admission_fixture"]
    assert profile.oracle_set_digest == contracts["oracle_set"]
    assert check_profile(profile, manifest, report).passed
    changed = replace(profile, oracle_set_digest="different")
    assert "oracle_set_digest_mismatch" in check_profile(
        changed, manifest, report).failures

    monkeypatch.setattr(release_module, "_report_from_measured_run",
                        lambda _measured: report)
    target = write_release_bundle(
        tmp_path / "bundle.json", profile=profile, manifest=manifest,
        measured_run=object())
    payload = json.loads(target.read_text())
    assert payload["profile"]["admission_fixture_digest"] == \
        report.admission_fixture_digest
    assert payload["profile"]["oracle_set_digest"] == report.oracle_set_digest


def test_admission_digest_binds_model_schema_and_entity_matching(monkeypatch):
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    families = SemanticFamilyRegistry()
    baseline = families.admission_digest(manifest)

    original_schema = SemanticFamilyRegistry.model_output_schema
    monkeypatch.setattr(
        SemanticFamilyRegistry, "model_output_schema",
        lambda self: {"oneOf": [{"type": "object"}]})
    assert families.admission_digest(manifest) != baseline
    monkeypatch.setattr(
        SemanticFamilyRegistry, "model_output_schema", original_schema)

    monkeypatch.setattr(
        SemanticFamilyRegistry, "_catalog_candidates",
        lambda self, name, phrase: ({"id": "forged", "label": "Forged"},))
    assert families.admission_digest(manifest) != baseline


@pytest.mark.parametrize(("field", "wrong"), [
    ("value", "599.00"), ("currency", "EUR"),
    ("dated", "2026-01-30"), ("subject_record_id", "brk")])
def test_semantic_admission_oracle_rejects_wrong_financial_identity(field, wrong):
    case = load_cases()[0]
    expected = {"value": "600.00", "currency": "USD",
                "quantity": "balance", "dated": "2026-01-31",
                "subject_record_id": "chk"}
    expected[field] = wrong
    case = replace(case, oracle={"figures": [expected]})
    families = SemanticFamilyRegistry()
    request = SemanticRequest(
        case.expected_family, case.expected_parameters, case.expected_claims,
        families.catalog_digest)
    semantic = SemanticOutcome("request", request)
    program = families.lower(
        semantic, CapabilityManifest.from_registry(_registry()))
    result = SimpleNamespace(
        status="answered", outcome_tag="", text="supported result",
        figures=[{"value": "600.00", "currency": "USD",
                  "quantity": "balance", "dated": "2026-01-31",
                  "kind": "financial", "record_ids": ["chk"]}])
    measured = score(case, SimpleNamespace(
        result=result, compilation=SimpleNamespace(
            exchanges=[SimpleNamespace(defect={})], semantic_outcome=semantic,
            program=program)))

    assert not measured.passed
    assert "wrong_keyed_figure" in measured.defects
    assert measured.confidently_wrong == 1


def test_single_path_gate_scans_non_python_runtime_sources(tmp_path):
    source = tmp_path / "surface.ts"
    source.write_text("const route = 'compile_answer_program';")

    checked = check_single_path(tmp_path)

    assert not checked.passed
    assert any("compile_answer_program" in item for item in checked.failures)
