"""The answer program is typed, versioned and bounded before any read."""

import copy
import json
import time
from types import SimpleNamespace

import pytest
from vivacore import versions

from _tool_test_support import _events
from viva.answer_program import (AnswerProgram, AnswerResourcePolicy,
                                 AdmissionReport,
                                 AdmissionThresholds, AnswerProgramCompiler,
                                 BreadthFeedback, CapabilityManifest,
                                 DeterministicBinder, ProgramExecutor,
                                 ProgramValidator, QuestionContext,
                                 KnownIntentRegistry, admitted_profile,
                                 check_profile, check_single_path,
                                 current_contract_digests,
                                 evaluate_admission, replay_capture,
                                 resource_policy_digest,
                                 run_live_suite, write_release_bundle)
from viva.answer_program import validate_admission_report
from viva.answer_program.compiler import COMPILER_VERSION, compiler_output_json_schema
from viva.answer_program.eval import CaseScore
from viva.answer_program.intents import KNOWN_INTENT_REQUEST_VERSION
from viva.answer_program.schema import ANSWER_PROGRAM_VERSION, ContractError
from viva.answer_program.schema import _generated_program_json_schema, program_json_schema
from viva.answer_program.eval import (EvalCase, evaluate_adversarial,
                                      load_adversarial_cases, load_cases, score)
from viva.ledger import LedgerProjection
from viva.session import Session
from viva.tools import default_registry
from viva.tools.registry import PACKAGE


def _registry():
    return default_registry(LedgerProjection(_events()), today="2026-03-01")


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


def _turn(raw):
    return SimpleNamespace(
        request={"sent": True}, response={"usage": {"prompt_tokens": 4}},
        input_tokens=4, output_tokens=2, cost_usd=0.001, latency_s=0.1,
        resolved_model="synthetic-compiler", message={"role": "assistant"},
        tool_calls=[{"id": "compile-1", "function": {
            "name": "compile_answer_program", "arguments": json.dumps(raw)}}])


def _context(manifest):
    return QuestionContext(question="what is my balance?", today="2026-03-01",
                           locale="en-US", currency_convention="locale",
                           capability_manifest_digest=manifest.digest,
                           shape_version="speak-shape-v13")


def test_compiler_gets_one_targeted_repair_before_any_read():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    invalid = copy.deepcopy(_program(manifest))
    invalid["bindings"][0]["selector"]["quantity"] = "spending"
    valid = _program(manifest)

    class Adapter:
        def __init__(self):
            self.seen = []
        def converse(self, messages, tools):
            self.seen.append((messages, tools))
            return _turn(invalid if len(self.seen) == 1 else valid)

    adapter = Adapter()
    policy = AnswerResourcePolicy()
    compiled = AnswerProgramCompiler(
        adapter, ProgramValidator(manifest, policy), manifest, policy
    ).compile(_context(manifest))

    assert compiled.ok
    assert len(compiled.exchanges) == 2
    assert compiled.exchanges[0].defect["tag"] == "selector_quantity_mismatch"
    assert "selector_quantity_mismatch" in adapter.seen[1][0][-1]["content"]
    assert all('"results":' not in json.dumps(messages)
               for messages, _ in adapter.seen)


def test_text_compiler_uses_the_same_contract_and_one_call_on_success():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)

    class Adapter:
        def __init__(self):
            self.prompts = []
        def extract(self, pages, prompt):
            self.prompts.append(prompt)
            return SimpleNamespace(
                text=json.dumps(_program(manifest)), request={"prompt": True},
                response={}, input_tokens=3, output_tokens=2, cost_usd=0.0,
                latency_s=0.1, resolved_model="synthetic-text")

    adapter = Adapter()
    policy = AnswerResourcePolicy()
    compiled = AnswerProgramCompiler(
        adapter, ProgramValidator(manifest, policy), manifest, policy
    ).compile(_context(manifest))
    assert compiled.ok and len(compiled.exchanges) == 1
    assert "CapabilityManifest" in adapter.prompts[0]


def test_compiler_rejects_a_provider_resolved_model_outside_the_profile():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)

    class Adapter:
        def converse(self, messages, tools):
            return _turn(_program(manifest))

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
        manifest = CapabilityManifest.from_registry(registry)
        return _turn(_executable_program(manifest).to_dict())

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
            return _turn(_executable_program(manifest).to_dict())

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
    assert {"answer_program_schema", "financial_query_schema",
            "capability_manifest", "persona"} <= set(payload["prompt_versions"])


def test_the_frozen_admission_corpus_has_ten_fully_keyed_questions():
    cases = load_cases()
    assert len(cases) == 10
    assert all(case.required_nodes and case.required_semantic_claims for case in cases)
    assert all(case.max_model_attempts <= 2 for case in cases)


def test_the_frozen_adversarial_corpus_is_rejected_before_execution():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    validator = ProgramValidator(manifest, AnswerResourcePolicy())
    scores = evaluate_adversarial(_program(manifest), validator)
    assert len(scores) == len(load_adversarial_cases()) == 8
    assert all(item.passed for item in scores), scores


def test_keyed_scoring_detects_a_wrong_but_cited_figure():
    case = EvalCase(
        id="wrong-cited", question="balance?", prior_turns=(),
        answerability_status="answered", accepted_intents=("balance_read",),
        required_semantic_claims=("balance",),
        required_nodes=({"tool": "query_ledger", "args": {"entity": "balances"}},),
        permitted_supporting_nodes=(),
        expected_figures=({"value": "600.00", "currency": "USD",
                           "quantity": "balance", "grade": "corroborated"},),
        expected={}, expected_outcome_tag="", forbidden_claims=(),
        max_model_attempts=2)
    program = SimpleNamespace(
        question_kind="balance_read",
        nodes=[SimpleNamespace(tool="query_ledger", kind="tool_read",
                               args={"entity": "balances"},
                               importance="required")])
    wrong = SimpleNamespace(
        result=SimpleNamespace(
            status="answered", outcome_tag="",
            figures=[{"value": "601.00", "currency": "USD",
                      "quantity": "balance", "grade": "corroborated",
                      "kind": "financial", "record_ids": ["synthetic-record"]}]),
        compilation=SimpleNamespace(exchanges=[object()], program=program))

    measured = score(case, wrong)
    assert measured.measured and not measured.passed
    assert measured.confidently_wrong == 1
    assert measured.unsupported_figures == 0


def test_keyed_scoring_never_grades_a_transport_failure_as_a_model_answer():
    case = load_cases()[0]
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


def test_keyed_scoring_enforces_semantics_caveats_and_forbidden_claims():
    case = load_cases()[0]
    manifest = CapabilityManifest.from_registry(_registry())
    program = KnownIntentRegistry().instantiate("net_worth", {}, manifest)
    result = SimpleNamespace(
        status="answered", outcome_tag="", text="Converted currency total.",
        figures=[{"value": "2100.00", "currency": "USD",
                  "quantity": "net_worth", "grade": "corroborated",
                  "kind": "financial", "record_ids": ["synthetic-record"],
                  "boundary": {"whole": True}}])
    measured = score(case, SimpleNamespace(
        result=result, compilation=SimpleNamespace(
            exchanges=[SimpleNamespace(defect={})], program=program)))
    assert not measured.passed
    assert {"missing_caveat", "forbidden_claim"} <= set(measured.defects)
    assert measured.keyed_semantic_errors >= 2


def test_live_admission_report_is_bound_to_measured_identity_and_contracts():
    case = load_cases()[0]

    class Adapter:
        def converse(self, messages, tools):
            registry = _registry()
            manifest = CapabilityManifest.from_registry(registry)
            program = KnownIntentRegistry().instantiate("net_worth", {}, manifest)
            return _turn(program.to_dict())

    def factory(validator, manifest, policy):
        return AnswerProgramCompiler(Adapter(), validator, manifest, policy)

    factory.admission_identity = {
        "provider": "synthetic", "requested_model": "compiler-route",
        "endpoint": "local", "modality": "native-structured"}
    report, scores, _turns = run_live_suite(
        cases=(case,), registry_factory=_registry, compiler_factory=factory,
        thresholds=AdmissionThresholds(0, 0, 0), today="2026-03-01",
        locale="en-US")

    assert not report.admitted and scores[0].passed
    assert "incomplete_keyed_corpus" in report.hard_failures
    with pytest.raises(ValueError, match="cannot be published"):
        admitted_profile(report, manifest=CapabilityManifest.from_registry(_registry()))
    assert report.identity["resolved_model"] == "synthetic-compiler"
    assert report.identity["locale_family"] == "en"
    assert report.contract_digests["program_schema"]
    assert report.adversarial_passed


def test_all_ten_known_intents_instantiate_reviewed_programs_on_the_one_runtime():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    intents = KnownIntentRegistry()
    cases = {case.accepted_intents[0]: case for case in load_cases()}
    assert len(intents.ids) == 10
    assert {item["id"] for item in manifest.known_intents} == set(intents.ids)
    for intent_id in intents.ids:
        parameters = ({"from": "2026-01-01", "to": "2026-01-31"}
                      if intent_id == "largest_spending_movements" else {})
        program = intents.instantiate(intent_id, parameters, manifest)
        checked = ProgramValidator(manifest, AnswerResourcePolicy()).validate(program)
        assert checked.ok, (intent_id, checked.defects)
        assert program.question_kind == intent_id
        assert all(binding.reference_kind == "read_figures"
                   for binding in program.bindings)
        execution = ProgramExecutor(
            registry, AnswerResourcePolicy(),
            query_executor=registry.query_executor).execute(program, intent_id)
        delivery = DeterministicBinder(registry).bind(program, execution)
        if intent_id == "recurring_spending":
            assert not delivery.result.answered
            assert execution.nodes["recurring"].refusal == "insufficient_history"
            delivery.result.status = "missing_data"
            delivery.result.outcome_tag = "insufficient_history"
        else:
            assert delivery.result.answered, (intent_id, delivery.unbound)
            delivery.result.status = cases[intent_id].answerability_status
            assert delivery.result.figures
            assert all(figure["record_ids"] for figure in delivery.result.figures)
        measured = score(cases[intent_id], SimpleNamespace(
            result=delivery.result,
            compilation=SimpleNamespace(
                exchanges=[SimpleNamespace(defect={})], program=program)))
        assert measured.passed, (intent_id, measured.defects)


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


def test_keyed_scoring_rejects_extra_figures_and_wrong_runtime_boundaries():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    intents = KnownIntentRegistry()
    cases = {case.accepted_intents[0]: case for case in load_cases()}

    spending_program = intents.instantiate(
        "monthly_spending_by_category", {}, manifest)
    spending_execution = ProgramExecutor(
        registry, AnswerResourcePolicy(),
        query_executor=registry.query_executor).execute(spending_program, "case")
    spending = DeterministicBinder(registry).bind(
        spending_program, spending_execution).result
    spending.figures.append({
        "value": "25.00", "currency": "USD", "quantity": "spending",
        "grade": "verified", "what": "transfer counted as spending",
        "kind": "financial", "record_ids": ["transfer-record"],
        "boundary": {"whole": False, "selected": [{
            "kind": "period", "value": "2026-01-01", "to": "2026-01-31"}],
            "cut": [{"kind": "nature", "value": "transfer"}]}})
    measured = score(cases["monthly_spending_by_category"], SimpleNamespace(
        result=spending, compilation=SimpleNamespace(
            exchanges=[SimpleNamespace(defect={})], program=spending_program)))
    assert "unexpected_keyed_figure" in measured.defects

    balances_program = intents.instantiate("account_balances", {}, manifest)
    balances_execution = ProgramExecutor(
        registry, AnswerResourcePolicy(),
        query_executor=registry.query_executor).execute(balances_program, "case")
    balances = DeterministicBinder(registry).bind(
        balances_program, balances_execution).result
    for item in balances.figures:
        item["boundary"] = {"whole": True}
    measured = score(cases["account_balances"], SimpleNamespace(
        result=balances, compilation=SimpleNamespace(
            exchanges=[SimpleNamespace(defect={})], program=balances_program)))
    assert not measured.passed and "wrong_keyed_figure" in measured.defects


def test_admission_report_recomputes_hard_metrics_instead_of_trusting_flags():
    report = AdmissionReport(
        measured=True, admitted=True,
        metrics={"cases": 10, "first_attempt_validity": 1,
                 "repaired_validity": 1, "answerable_completion": 1,
                 "unsupported_figures": 7, "confidently_wrong": 3,
                 "keyed_semantic_errors": 5, "missing_data_as_zero": 2,
                 "hypothetical_as_measured": 1, "resource_exhaustions": 4,
                 "p95_model_attempts": 9},
        hard_failures=(), threshold_failures=(), adversarial_passed=True,
        thresholds={"first_attempt_validity": .9, "repaired_validity": 1,
                    "answerable_completion": 1})
    failures = validate_admission_report(report)
    assert "admission_metric_failed:unsupported_figures" in failures
    assert "admission_metric_failed:model_attempt_bound" in failures


def test_compiler_can_choose_a_typed_known_intent_without_a_second_path():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    requested = {
        "request_version": KNOWN_INTENT_REQUEST_VERSION,
        "capability_manifest_digest": manifest.digest,
        "intent_id": "largest_spending_movements",
        "parameters": {"from": "2026-01-01", "to": "2026-01-31"},
    }

    class Adapter:
        def converse(self, messages, tools):
            assert len(tools) == 11
            turn = _turn(requested)
            turn.tool_calls[0]["function"] = {
                "name": "compile_intent_largest_spending_movements",
                "arguments": json.dumps(requested["parameters"])}
            return turn

    policy = AnswerResourcePolicy()
    compiled = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy
    ).compile(_context(manifest))
    assert compiled.ok and compiled.program.question_kind == requested["intent_id"]
    assert compiled.program.nodes[0].args == {
        "filters": {"window": {"from": "2026-01-01", "to": "2026-01-31"}}}
    assert "oneOf" in compiler_output_json_schema()


def test_known_intent_parameters_are_closed_and_preserve_required_scope():
    manifest = CapabilityManifest.from_registry(_registry())
    intents = KnownIntentRegistry()
    with pytest.raises(ValueError, match="missing"):
        intents.instantiate("largest_spending_movements", {}, manifest)
    with pytest.raises(ValueError, match="unknown"):
        intents.instantiate("net_worth", {"private_amount": "100"}, manifest)


def test_clarification_and_user_stipulation_remain_conversation_not_ledger_facts():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    clarification = _program(manifest)
    clarification.update(
        mode="clarify", question_kind="ambiguous_period", shape=None, nodes=[],
        bindings=[], clarification={"tag": "ambiguous_period",
                                    "question": "Which month did you mean?",
                                    "options": [{"id": "january",
                                                 "label": "January"}]},
        result_policy={})
    answer = _executable_program(manifest).to_dict()

    class Adapter:
        def __init__(self):
            self.calls = []
        def converse(self, messages, tools):
            self.calls.append(messages)
            return _turn(clarification if len(self.calls) == 1 else answer)

    adapter = Adapter()
    session = Session(
        registry, lambda validator, built, policy: AnswerProgramCompiler(
            adapter, validator, built, policy),
        today=lambda: "2026-03-01")
    first = session.ask("Was that month safe?")
    second = session.ask("I mean January, and safe means a positive surplus.")
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
    report = evaluate_admission(
        passed, attempts=[1] * 10, first_attempt_valid=[True] * 10,
        thresholds=thresholds, latency_p95_ms=20,
        evidence_payload_p95_bytes=100, latency_ceiling_ms=100,
        evidence_ceiling_bytes=1000)
    assert report.admitted
    with pytest.raises(ValueError, match="identity measured"):
        admitted_profile(report, manifest=manifest)
    report = evaluate_admission(
        passed, attempts=[1] * 10, first_attempt_valid=[True] * 10,
        thresholds=thresholds,
        identity={"provider": "synthetic", "requested_model": "compiler-exact",
                  "resolved_model": "compiler-exact", "endpoint": "local",
                  "modality": "native-structured", "locale_family": "en"},
        contract_digests=current_contract_digests(
            manifest, AnswerResourcePolicy()),
        adversarial_passed=True)
    profile = admitted_profile(
        report, manifest=manifest)
    assert profile.capability_manifest_digest == manifest.digest
    assert profile.prompt_digest

    failed = evaluate_admission(
        [CaseScore("bad", True, False, ("wrong_keyed_figure",), 0, 1)],
        attempts=[1], first_attempt_valid=[True], thresholds=thresholds)
    assert not failed.admitted and "confidently_wrong" in failed.hard_failures
    with pytest.raises(ValueError, match="cannot be published"):
        admitted_profile(
            failed, manifest=manifest)


def test_captured_program_can_replay_without_calling_the_model():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    payload = {"question": "what is my checking balance?",
               "program": _executable_program(manifest).to_dict()}
    replayed = replay_capture(payload, registry, locale="en-US")
    assert replayed["replayed"]
    assert replayed["result"].answered
    assert replayed["result"].figures[0]["record_ids"]


def test_release_gate_proves_one_path_and_publishes_exact_profile(tmp_path):
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    thresholds = AdmissionThresholds(1, 1, 1)
    report = evaluate_admission(
        [CaseScore(case.id, True, True, (), 0, 0) for case in load_cases()],
        attempts=[1] * 10, first_attempt_valid=[True] * 10,
        thresholds=thresholds,
        identity={"provider": "synthetic", "requested_model": "compiler-exact",
                  "resolved_model": "compiler-exact", "endpoint": "local",
                  "modality": "native-structured", "locale_family": "en"},
        contract_digests=current_contract_digests(
            manifest, AnswerResourcePolicy()),
        adversarial_passed=True)
    profile = admitted_profile(
        report, manifest=manifest)
    assert check_single_path().passed
    assert check_profile(profile, manifest, report).passed
    target = write_release_bundle(tmp_path / "admission.json",
                                  profile=profile, manifest=manifest,
                                  report=report)
    payload = json.loads(target.read_text())
    assert payload["profile"]["resolved_model"] == "compiler-exact"
    assert payload["capability_manifest"]["digest"] == manifest.digest
