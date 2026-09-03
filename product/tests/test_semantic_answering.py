"""The runtime model names meaning; code authors every executable detail."""

import json
from types import SimpleNamespace

import pytest

from _tool_test_support import (_events, Provenance, account_opened,
                                closing_balance_observed)
from viva.answer_program import (AnswerProgramCompiler, AnswerResourcePolicy,
                                 CapabilityManifest, ProgramValidator,
                                 QuestionContext, admission_registry)
from viva.answer_program.bind import DeterministicBinder
from viva.answer_program.execute import ProgramExecutor
from viva.answer_program.intents import (SemanticFamilyRegistry,
                                         SemanticOutcome, SemanticRequest)
from viva.answer_program.schema import ContractError
from viva.answer_program.runtime import AnswerProgramRuntime
from viva.ledger import LedgerProjection
from viva.ledger.events import (MAJOR_ASSET, SCOPE_MOVEMENT,
                                ruling_recorded)
from viva.tools import default_registry


def _registry():
    return default_registry(LedgerProjection(_events()), today="2026-03-01")


def _request(families, family, parameters):
    definition = families.get(family)
    return SemanticOutcome("request", SemanticRequest(
        family, parameters, definition.claims, families.catalog_digest))


def _turn(name, arguments):
    arguments = dict(arguments)
    if name.startswith("select_") and "parameter_sources" not in arguments:
        arguments["parameter_sources"] = {
            key: {"source": "question", "quote": value,
                  "derivation": "verbatim"}
            for key, value in dict(arguments.get("parameters") or {}).items()}
    return SimpleNamespace(
        request={"messages": True}, response={"usage": {"input_tokens": 3}},
        input_tokens=3, output_tokens=2, cost_usd=0, latency_s=.01,
        resolved_model="synthetic-semantic",
        tool_calls=[{"function": {"name": name,
                                   "arguments": json.dumps(arguments)}}])


def test_model_contract_cannot_author_executable_program_fields():
    families = SemanticFamilyRegistry()
    forbidden = {"nodes", "query", "bindings", "result_policy", "tool",
                 "importance", "resource_limits"}
    for tool in families.model_tools():
        encoded = json.dumps(tool["parameters"])
        assert not any(f'"{field}"' in encoded for field in forbidden)
    encoded = json.dumps(families.output_schema())
    assert not any(f'"{field}"' in encoded for field in forbidden)
    assert families.supported_ids == (
        "named_account_balance", "needs_attention",
        "category_spending_period", "net_worth", "credit_card_debt",
        "classification_explanation")
    assert families.get("account_inventory").runtime_selectable is False


def test_every_reviewed_family_lowers_and_validates_before_a_read():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    validator = ProgramValidator(manifest, AnswerResourcePolicy())
    families = SemanticFamilyRegistry()
    samples = {
        "named_account_balance": {"account_phrase": "Everyday Checking"},
        "needs_attention": {},
        "category_spending_period": {
            "category": "groceries", "from": "2026-01-01",
            "to": "2026-01-31"},
        "net_worth": {}, "credit_card_debt": {},
        "classification_explanation": {"movement_phrase": "greenfield market"},
    }
    for family, parameters in samples.items():
        program = families.lower(_request(families, family, parameters), manifest)
        checked = validator.validate(program)
        assert checked.ok, (family, checked.defects)
        assert program.question_kind == family
    inventory = families.lower(
        SemanticOutcome("request", SemanticRequest(
            "account_inventory", {}, families.get("account_inventory").claims,
            families.catalog_digest)), manifest)
    assert validator.validate(inventory).ok
    assert inventory.question_kind == "account_inventory"


def test_named_account_scope_and_date_survive_lowering_and_delivery():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    families = SemanticFamilyRegistry()
    program = families.lower(_request(
        families, "named_account_balance",
        {"account_phrase": "Everyday Checking"}), manifest)
    assert len(program.nodes) == 1
    assert program.nodes[0].args == {
        "entity": "balances", "filters": {"account": "Everyday Checking"}}
    assert {binding.hole for binding in program.bindings} == {"balance", "date"}
    assert program.result_policy["required_clauses"] == ["balance_and_date"]
    execution = ProgramExecutor(registry, policy).execute(program, "balance?")
    delivered = DeterministicBinder(registry, "en-US").bind(program, execution)
    assert delivered.result.answered
    assert len(delivered.result.figures) == 1
    assert "2026-01-31" in delivered.result.text
    assert "Brokerage" not in delivered.result.text


def test_requested_claim_subset_controls_required_clauses():
    registry = _registry()
    families = SemanticFamilyRegistry()
    definition = families.get("named_account_balance")
    request = SemanticRequest(
        definition.id, {"account_phrase": "Everyday Checking"},
        ("balance",), families.catalog_digest)
    program = families.lower(SemanticOutcome("request", request),
                             CapabilityManifest.from_registry(registry))

    assert [clause.id for clause in program.shape.clauses] == ["balance"]
    assert program.result_policy["required_clauses"] == ["balance"]
    assert {binding.hole for binding in program.bindings} == {"balance"}


def test_compiler_rejects_a_subject_not_grounded_in_the_question_before_reads():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()

    class Adapter:
        def converse(self, messages, tools):
            return _turn("select_named_account_balance", {
                "parameters": {"account_phrase": "Brokerage"},
                "parameter_sources": {"account_phrase": {
                    "source": "question", "quote": "Brokerage",
                    "derivation": "verbatim"}},
                "requested_claims": ["balance", "measurement_date"]})

    compiled = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy).compile(
            QuestionContext(question="What is my checking balance?",
                            capability_manifest_digest=manifest.digest))

    assert not compiled.ok
    assert compiled.failure_tag == "invalid_semantic_request"
    assert all(exchange.parse_error for exchange in compiled.exchanges)


def test_calendar_month_edges_are_derived_from_the_quoted_question_text():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()

    class Adapter:
        def converse(self, messages, tools):
            return _turn("select_category_spending_period", {
                "parameters": {"category": "groceries", "from": "2026-01-01",
                               "to": "2026-01-31"},
                "parameter_sources": {
                    "category": {"source": "question", "quote": "groceries",
                                 "derivation": "verbatim"},
                    "from": {"source": "question", "quote": "January 2026",
                             "derivation": "calendar_month_start"},
                    "to": {"source": "question", "quote": "January 2026",
                           "derivation": "calendar_month_end"}},
                "requested_claims": ["spending"]})

    compiled = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy).compile(
            QuestionContext(question="groceries in January 2026",
                            capability_manifest_digest=manifest.digest))

    assert compiled.ok
    assert compiled.program.result_policy["required_clauses"] == ["category_total"]


def test_named_account_can_resolve_one_visible_institution_without_word_lists():
    registry = _registry()
    result = registry.call("query_ledger", {
        "entity": "balances", "filters": {"account": "Vantage Invest"}})

    assert result.ok
    assert {figure["record_ids"][0] for figure in result.figures
            if figure["quantity"] == "balance"} == {"brk"}


def test_description_resolution_never_accepts_partial_words_or_ties():
    registry = admission_registry()
    for phrase in ("king", "age", "account"):
        result = registry.call("query_ledger", {
            "entity": "balances", "filters": {"account": phrase}})
        assert not result.ok
        assert result.figures == []


def test_clarification_tags_are_a_closed_interpretation_vocabulary():
    families = SemanticFamilyRegistry()
    schema = next(tool["parameters"] for tool in families.model_tools()
                  if tool["name"] == "semantic_clarification")
    assert schema["properties"]["tag"]["enum"] == [
        "ambiguous_account", "ambiguous_movement", "ambiguous_period"]
    with pytest.raises(ContractError, match="invalid semantic clarification"):
        families.parse({
            "request_version": families.output_schema()["oneOf"][0]
            ["properties"]["request_version"]["enum"][0],
            "outcome": "clarify", "tag": "missing_account",
            "question": "Which account?", "options": []})


def test_user_specific_catalog_selects_identity_without_word_matching():
    registry = admission_registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    catalog = registry.semantic_entities()
    checking_id = next(item["id"] for item in catalog["accounts"]
                       if item["name"] == "Synthetic Checking")
    question = "What is the balance of the place where my salary lands?"

    class Adapter:
        def __init__(self):
            self.system_prompt = ""

        def converse(self, messages, tools):
            self.system_prompt = messages[0]["content"]
            return _turn("select_named_account_balance", {
                "parameters": {"account_phrase": checking_id},
                "parameter_sources": {"account_phrase": {
                    "source": "question",
                    "quote": "the place where my salary lands",
                    "derivation": "catalog_selection"}},
                "requested_claims": ["balance"]})

    adapter = Adapter()
    compiler = AnswerProgramCompiler(
        adapter, ProgramValidator(manifest, policy), manifest, policy)
    compiler.set_entity_catalog(catalog)
    runtime = AnswerProgramRuntime(
        compiler, ProgramExecutor(registry, policy,
                                  query_executor=registry.query_executor),
        DeterministicBinder(registry))
    answered = runtime.answer(QuestionContext(
        question=question, capability_manifest_digest=manifest.digest))

    assert answered.result.answered
    assert checking_id in adapter.system_prompt
    assert any(checking_id in figure["record_ids"]
               for figure in answered.result.figures)


def test_catalog_selection_cannot_invent_an_identity():
    registry = admission_registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()

    class Adapter:
        def converse(self, messages, tools):
            return _turn("select_named_account_balance", {
                "parameters": {"account_phrase": "invented-account"},
                "parameter_sources": {"account_phrase": {
                    "source": "question", "quote": "my main account",
                    "derivation": "catalog_selection"}},
                "requested_claims": ["balance"]})

    compiler = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy)
    compiler.set_entity_catalog(registry.semantic_entities())
    compiled = compiler.compile(QuestionContext(
        question="What is my main account balance?",
        capability_manifest_digest=manifest.digest))

    assert not compiled.ok
    assert compiled.failure_tag == "invalid_semantic_request"
    assert all(exchange.parse_error for exchange in compiled.exchanges)


def test_interpretation_catalog_contains_labels_but_no_financial_results():
    catalog = admission_registry().semantic_entities()

    assert set(catalog) == {
        "version", "accounts", "categories", "counterparties", "coverage"}
    assert all(set(item) == {"id", "name", "institution", "kind"}
               for item in catalog["accounts"])
    assert all(set(item) == {"id", "label"}
               for group in ("categories", "counterparties")
               for item in catalog[group])
    encoded = json.dumps(catalog).casefold()
    assert not any(word in encoded for word in (
        '"amount"', '"balance"', '"currency"', '"document"', '"evidence"'))
    assert catalog["coverage"]["counterparties"] == {
        "count": 256, "complete": True}


def test_users_share_the_semantic_contract_not_each_others_candidates():
    first = SemanticFamilyRegistry(_registry().semantic_entities())
    second = SemanticFamilyRegistry(admission_registry().semantic_entities())

    assert first.catalog_digest == second.catalog_digest
    assert first.entity_catalog_digest != second.entity_catalog_digest
    assert first.entity_catalog != second.entity_catalog


def test_net_worth_has_no_unrequested_staleness_clause():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    families = SemanticFamilyRegistry()
    program = families.lower(_request(families, "net_worth", {}), manifest)
    assert [node.id for node in program.nodes] == ["net_worth"]
    assert program.result_policy == {
        "allow_partial": False, "required_clauses": ["net_worth"]}
    assert not any(node.args.get("metric") == "stalest_balance"
                   for node in program.nodes)


def test_card_debt_uses_one_complete_population_for_totals_and_rows():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    families = SemanticFamilyRegistry()
    program = families.lower(_request(families, "credit_card_debt", {}),
                             manifest)
    assert len(program.nodes) == 1
    assert program.nodes[0].args == {
        "entity": "balances", "filters": {"kind": "card_account"}}
    assert len(program.bindings) == 1
    binding = program.bindings[0]
    assert binding.reference_kind == "read_figures"
    assert binding.selector.quantity == "owed"
    assert binding.selector.currency == ""


def test_card_debt_excludes_a_measured_loan_from_the_card_population():
    card = "Liabilities:Cards:Household"
    loan = "Liabilities:HomeLoan:Residence"
    events = [
        account_opened(card, "liability", "Household Card", "USD",
                       "2026-01-01"),
        account_opened(loan, "liability", "Residence Loan", "USD",
                       "2026-01-01"),
        closing_balance_observed(card, "125.00", "2026-01-31",
                                 Provenance("card-doc", 1, "balance")),
        closing_balance_observed(loan, "900.00", "2026-01-31",
                                 Provenance("loan-doc", 1, "balance")),
    ]
    registry = default_registry(LedgerProjection(events), today="2026-03-01")
    families = SemanticFamilyRegistry()
    manifest = CapabilityManifest.from_registry(registry)
    program = families.lower(_request(
        families, "credit_card_debt", {}), manifest)
    result = ProgramExecutor(registry, AnswerResourcePolicy()).execute(
        program, "card debt")
    figures = [figure for item in result.transcript for figure in item.figures]

    assert any(figure["value"] == "125.00" for figure in figures)
    assert not any(figure["value"] == "900.00" for figure in figures)
    assert not any(loan in figure["record_ids"] for figure in figures)


def test_compiler_accepts_only_semantic_selection_then_lowers_it():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()

    class Adapter:
        def __init__(self):
            self.tools = None

        def converse(self, messages, tools):
            self.tools = tools
            return _turn("select_named_account_balance", {
                "parameters": {"account_phrase": "Everyday Checking"},
                "requested_claims": ["balance", "measurement_date"]})

    adapter = Adapter()
    compiler = AnswerProgramCompiler(
        adapter, ProgramValidator(manifest, policy), manifest, policy)
    result = compiler.compile(QuestionContext(
        question="What is the Everyday Checking balance and date?",
        today="2026-03-01",
        locale="en-US", capability_manifest_digest=manifest.digest))
    assert result.ok
    assert result.semantic_outcome.request.family == "named_account_balance"
    assert result.program.nodes[0].tool == "query_ledger"
    assert all(tool["name"] != "compile_answer_program"
               for tool in adapter.tools)


def test_unsupported_meaning_is_a_structured_capability_gap():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()

    class Adapter:
        def converse(self, messages, tools):
            return _turn("semantic_unsupported", {
                "requested_family": "future_projection"})

    compiler = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy)
    runtime = AnswerProgramRuntime(
        compiler, ProgramExecutor(registry, policy,
                                  query_executor=registry.query_executor),
        DeterministicBinder(registry))
    answered = runtime.answer(QuestionContext(
        question="Project next year", today="2026-03-01",
        capability_manifest_digest=manifest.digest))
    assert answered.result.status == "capability_gap"
    assert answered.result.outcome_tag == "unsupported_family"
    assert answered.result.missing[0]["requested_family"] == "future_projection"
    assert [item["id"] for item in
            answered.result.missing[0]["supported_families"]] == list(
                SemanticFamilyRegistry().supported_ids)
    assert all(item["label"] and item["example"]
               for item in answered.result.missing[0]["supported_families"])
    assert "available financial answers are listed below" in answered.result.text
    assert "future projection" not in answered.result.text
    assert answered.result.missing[0]["tag"] == "unsupported_family"


def test_attention_reads_the_existing_ordered_queue_and_classification_is_proved():
    registry = _registry()
    attention = registry.call("check_completeness", {"view": "attention"})
    assert attention.ok and attention.data["questions"]
    stakes = [float(item["amount"]) for item in attention.data["questions"]]
    assert stakes == sorted(stakes, reverse=True)

    treatment = registry.call("get_provenance", {
        "movement_phrase": "greenfield market", "from": "2026-01-01",
        "to": "2026-01-31"})
    assert treatment.ok and treatment.figures
    assert all(item["record_ids"] for item in treatment.figures)
    assert all("treated as" in item["what"] for item in treatment.figures)


def test_materially_different_classification_matches_request_clarification():
    events = _events()
    first = next(item for item in LedgerProjection(events).movements()
                 if "GREENFIELD" in item.description)
    events.append(ruling_recorded(
        SCOPE_MOVEMENT, first.key, "2026-02-06",
        legs=[{"major": MAJOR_ASSET, "account": "Assets:Example"}],
        said="This became an asset."))
    registry = default_registry(LedgerProjection(events), today="2026-03-01")
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()

    class Adapter:
        def converse(self, messages, tools):
            return _turn("select_classification_explanation", {
                "parameters": {"movement_phrase": "greenfield market"},
                "requested_claims": ["explanation"]})

    runtime = AnswerProgramRuntime(
        AnswerProgramCompiler(
            Adapter(), ProgramValidator(manifest, policy), manifest, policy),
        ProgramExecutor(registry, policy, query_executor=registry.query_executor),
        DeterministicBinder(registry))
    answered = runtime.answer(QuestionContext(
        question="Why was greenfield market treated this way?", today="2026-03-01",
        capability_manifest_digest=manifest.digest))
    assert answered.result.status == "needs_clarification"
    assert answered.result.outcome_tag == "ambiguous_movement_treatment"
