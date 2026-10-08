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
                                merchant_enriched, ruling_recorded,
                                statement_held)
from viva.persona import moment
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
    if name.startswith("select_"):
        parameters = dict(arguments.get("parameters") or {})
        sources = dict(arguments.get("parameter_sources") or {})
        for key in set(parameters) & {
                "account_phrase", "category", "movement_phrase"}:
            derivation = dict(sources.get(key) or {}).get("derivation")
            parameters[key] = (
                {"catalog_id": parameters[key]}
                if derivation == "catalog_selection"
                else {"grounded_phrase": True})
        arguments["parameters"] = parameters
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
    assert families.supported_ids[:6] == (
        "named_account_balance", "needs_attention",
        "category_spending_period", "net_worth", "credit_card_debt",
        "classification_explanation")
    assert families.get("account_inventory").runtime_selectable is False


def test_every_reviewed_family_lowers_and_validates_before_a_read():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    validator = ProgramValidator(manifest, AnswerResourcePolicy())
    families = SemanticFamilyRegistry(registry.semantic_entities())
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
    families = SemanticFamilyRegistry(registry.semantic_entities())
    program = families.lower(_request(
        families, "named_account_balance",
        {"account_phrase": "Everyday Checking"}), manifest)
    assert len(program.nodes) == 1
    assert program.nodes[0].args == {
        "entity": "balances", "filters": {"account": "chk"}}
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
    families = SemanticFamilyRegistry(registry.semantic_entities())
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


def test_model_entity_parameters_separate_catalog_ids_from_grounded_phrases():
    families = SemanticFamilyRegistry(admission_registry().semantic_entities())
    schema = next(tool["parameters"] for tool in families.model_tools()
                  if tool["name"] == "select_classification_explanation")
    reference = schema["properties"]["parameters"]["properties"][
        "movement_phrase"]

    branches = reference["oneOf"]
    ids = branches[0]["properties"]["catalog_id"]["enum"]
    assert "costco" in ids
    assert branches[1]["properties"]["grounded_phrase"]["enum"] == [True]
    assert "indirect description" in reference["description"]
    assert "shares no words" in branches[0]["properties"]["catalog_id"][
        "description"]
    assert "only when no catalog entry" in branches[1]["properties"][
        "grounded_phrase"]["description"]


def test_indirect_counterparty_description_can_select_catalog_identity():
    registry = admission_registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    question = (
        "Which rule caused that warehouse-club purchase to be classified as "
        "a transfer?")

    class Adapter:
        def __init__(self):
            self.tool_description = ""

        def converse(self, messages, tools):
            selected = next(tool for tool in tools
                            if tool["name"] ==
                            "select_classification_explanation")
            self.tool_description = selected["description"]
            return _turn("select_classification_explanation", {
                "parameters": {"movement_phrase": "costco"},
                "parameter_sources": {"movement_phrase": {
                    "source": "question",
                    "quote": "that warehouse-club purchase",
                    "derivation": "catalog_selection"}},
                "requested_claims": ["explanation"]})

    adapter = Adapter()
    compiler = AnswerProgramCompiler(
        adapter, ProgramValidator(manifest, policy), manifest, policy)
    compiler.set_entity_catalog(registry.semantic_entities())
    answered = AnswerProgramRuntime(
        compiler, ProgramExecutor(registry, policy,
                                  query_executor=registry.query_executor),
        DeterministicBinder(registry)).answer(QuestionContext(
            question=question, capability_manifest_digest=manifest.digest))

    assert answered.result.status == "answered"
    assert answered.compilation.semantic_outcome.request.parameters == {
        "movement_phrase": "costco"}
    assert answered.result.text.startswith(
        "I interpreted ‘that warehouse-club purchase’ as costco.")
    assert "indirect descriptions" in adapter.tool_description


def test_unique_grounded_entity_match_is_answered_and_disclosed():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()

    class Adapter:
        def converse(self, messages, tools):
            return _turn("select_classification_explanation", {
                "parameters": {"movement_phrase": "Greenfield Market purchase"},
                "parameter_sources": {"movement_phrase": {
                    "source": "question", "quote": "Greenfield Market purchase",
                    "derivation": "verbatim"}},
                "requested_claims": ["explanation"]})

    compiler = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy)
    compiler.set_entity_catalog(registry.semantic_entities())
    answered = AnswerProgramRuntime(
        compiler, ProgramExecutor(registry, policy,
                                  query_executor=registry.query_executor),
        DeterministicBinder(registry)).answer(QuestionContext(
            question="Why was my Greenfield Market purchase treated that way?",
            capability_manifest_digest=manifest.digest))

    assert answered.result.status == "answered"
    assert answered.compilation.semantic_outcome.request.parameters == {
        "movement_phrase": "greenfield market"}
    assert answered.result.text.startswith(
        "I interpreted ‘Greenfield Market purchase’ as greenfield market.")


def test_reordered_catalog_words_are_not_canonicalized_or_answered():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()

    class Adapter:
        def converse(self, messages, tools):
            return _turn("select_classification_explanation", {
                "parameters": {
                    "movement_phrase": "Market near Greenfield purchase"},
                "parameter_sources": {"movement_phrase": {
                    "source": "question",
                    "quote": "Market near Greenfield purchase",
                    "derivation": "verbatim"}},
                "requested_claims": ["explanation"]})

    compiler = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy)
    compiler.set_entity_catalog(registry.semantic_entities())
    answered = AnswerProgramRuntime(
        compiler, ProgramExecutor(registry, policy,
                                  query_executor=registry.query_executor),
        DeterministicBinder(registry)).answer(QuestionContext(
            question="Why was my Market near Greenfield purchase treated that way?",
            capability_manifest_digest=manifest.digest))

    assert answered.compilation.semantic_outcome.request.parameters == {
        "movement_phrase": "Market near Greenfield purchase"}
    assert answered.result.status == "missing_data"
    assert answered.result.outcome_tag == "not_found"
    assert answered.result.figures == []


def test_model_catalog_id_requires_a_string_even_when_digits_match():
    families = SemanticFamilyRegistry({
        "counterparties": [{"id": "123", "label": "Numeric Shop"}]})
    raw = {
        "request_version": "semantic-request-v7",
        "catalog_digest": families.catalog_digest,
        "entity_catalog_digest": families.entity_catalog_digest,
        "outcome": "request",
        "family": "classification_explanation",
        "parameters": {"movement_phrase": {"catalog_id": 123}},
        "parameter_sources": {"movement_phrase": {
            "source": "question", "quote": "Numeric Shop",
            "derivation": "catalog_selection"}},
        "requested_claims": ["explanation"],
    }

    with pytest.raises(ContractError, match="catalog_id must be"):
        families.materialize_model_output(raw)


def test_multiple_grounded_entity_matches_ask_instead_of_guessing():
    events = _events() + [
        merchant_enriched("alpha", "other", occurred_at="2026-02-06"),
        merchant_enriched("beta", "other", occurred_at="2026-02-06"),
    ]
    registry = default_registry(LedgerProjection(events), today="2026-03-01")
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()

    class Adapter:
        def converse(self, messages, tools):
            return _turn("select_classification_explanation", {
                "parameters": {"movement_phrase": "alpha beta purchase"},
                "parameter_sources": {"movement_phrase": {
                    "source": "question", "quote": "alpha beta purchase",
                    "derivation": "verbatim"}},
                "requested_claims": ["explanation"]})

    compiler = AnswerProgramCompiler(
        Adapter(), ProgramValidator(manifest, policy), manifest, policy)
    compiler.set_entity_catalog(registry.semantic_entities())
    answered = AnswerProgramRuntime(
        compiler, ProgramExecutor(registry, policy,
                                  query_executor=registry.query_executor),
        DeterministicBinder(registry)).answer(QuestionContext(
            question="Why was my alpha beta purchase treated that way?",
            capability_manifest_digest=manifest.digest))

    assert answered.result.status == "needs_clarification"
    assert answered.result.outcome_tag == "ambiguous_movement"
    assert answered.result.text == (
        "I could not match that exactly. Which of these did you mean?")
    assert answered.result.options == [
        {"id": "alpha", "label": "alpha"},
        {"id": "beta", "label": "beta"},
    ]


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
    compiler.set_entity_catalog(registry.semantic_entities())
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
    assert attention.ok and attention.figures
    assert len(attention.figures) == attention.data["shown"] + 3
    assert set(attention.data) == {"total", "shown", "pending", "tail"}

    treatment = registry.call("get_provenance", {
        "movement_phrase": "greenfield market", "from": "2026-01-01",
        "to": "2026-01-31"})
    assert treatment.ok and treatment.figures
    assert all(item["record_ids"] for item in treatment.figures)
    assert all("treated as" in item["what"] for item in treatment.figures)


def test_attention_known_intent_delivers_each_reviewed_question(monkeypatch):
    from viva.tools import ledger_audit
    from viva.tools import runner_binding
    from viva import render

    questions = [
        {"id": f"identity:{index}", "kind": "identity",
         "text": f"Reviewed question {index}", "why": "Reviewed reason",
         "amount": str(index), "currency": "USD", "count": 1,
         "scope": "one", "slots": [], "refs": {}}
        for index in range(2, 0, -1)
    ]

    def complete(_projection):
        return {"questions": questions, "total": len(questions),
                "pending": {"count": 0},
                "tail": {"count": 0, "amount": "0"}}

    monkeypatch.setattr("viva.questions.open_questions", complete)
    count_writes = []
    count_writer = runner_binding._MAGNITUDE_WRITERS[render.COUNT]

    def write_count(value, figure, locale):
        count_writes.append(figure["id"])
        return count_writer(value, figure, locale)

    monkeypatch.setitem(
        runner_binding._MAGNITUDE_WRITERS, render.COUNT, write_count)
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    families = SemanticFamilyRegistry()
    program = families.lower(_request(families, "needs_attention", {}), manifest)
    execution = ProgramExecutor(registry, AnswerResourcePolicy()).execute(
        program, "What needs attention?")
    delivered = DeterministicBinder(registry, "en-US").bind(program, execution)

    assert delivered.result.answered
    assert delivered.result.text == (
        "These open questions need your attention: Reviewed question 2\n"
        "Reviewed question 1.\nAbout this list: \nquestions shown — 2\n"
        "more open questions not shown — 0\ndeferred questions — 0.")
    from viva.speak import _shown
    shown = _shown(delivered.result)
    coverage_names = {"questions shown", "more open questions not shown",
                      "deferred questions"}
    coverage = [figure for figure in delivered.result.figures
                if figure.get("what") in coverage_names]
    assert count_writes == [figure["id"] for figure in coverage]
    assert [(figure["what"], shown.get(figure["id"]))
            for figure in coverage] == [
        ("questions shown", "2"),
        ("more open questions not shown", "0"),
        ("deferred questions", "0"),
    ]
    assert set(shown) == {figure["id"] for figure in coverage}


def test_empty_attention_known_intent_keeps_the_existing_non_answer(monkeypatch):
    monkeypatch.setattr("viva.questions.open_questions", lambda _projection: {
        "questions": [], "total": 0, "pending": {"count": 0},
        "tail": {"count": 0, "amount": "0"}})
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    families = SemanticFamilyRegistry()
    program = families.lower(_request(families, "needs_attention", {}), manifest)

    execution = ProgramExecutor(registry, AnswerResourcePolicy()).execute(
        program, "What needs attention?")
    delivered = DeterministicBinder(registry, "en-US").bind(program, execution)

    assert delivered.result.answered
    assert delivered.result.text == (
        "About this list: \nquestions shown — 0\n"
        "more open questions not shown — 0\ndeferred questions — 0.")


@pytest.mark.parametrize("family", ["net_worth", "credit_card_debt"])
def test_identity_blocked_known_answers_preserve_the_source_outcome(family):
    projection = LedgerProjection([
        *_events(),
        statement_held("identity-doc", {}, {"kind": "identity"},
                       "identity", "2026-02-04"),
    ])
    registry = default_registry(projection)
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    families = SemanticFamilyRegistry()

    class Adapter:
        def converse(self, messages, tools):
            return _turn(f"select_{family}", {
                "parameters": {},
                "requested_claims": list(families.get(family).claims)})

    runtime = AnswerProgramRuntime(
        AnswerProgramCompiler(
            Adapter(), ProgramValidator(manifest, policy), manifest, policy),
        ProgramExecutor(registry, policy, query_executor=registry.query_executor),
        DeterministicBinder(registry))
    answered = runtime.answer(QuestionContext(
        question="Give me the supported total", today="2026-03-01",
        capability_manifest_digest=manifest.digest))

    assert not answered.result.answered
    assert answered.result.figures == []
    assert answered.result.status == "missing_data"
    assert answered.result.outcome_tag == "account_identity_unresolved"
    assert answered.outcome.tag == "account_identity_unresolved"
    assert answered.result.text == " ".join([
        moment("refusal_nothing_established"),
        moment("diagnosis_account_identity_unresolved"),
    ])


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


@pytest.mark.parametrize('claims', [('balance',), ('balance', 'measurement_date')])
def test_named_liability_uses_owed_slot_and_same_measurement_date(claims):
    account = 'Liabilities:Cards:Example'
    registry = default_registry(LedgerProjection([
        account_opened(account, 'liability', 'Example Card', 'USD', '2026-01-01'),
        closing_balance_observed(account, '125.00', '2026-01-31',
                                 Provenance('example-card-doc', 1, 'balance')),
    ]), today='2026-03-01')
    families = SemanticFamilyRegistry(registry.semantic_entities())
    manifest = CapabilityManifest.from_registry(registry)
    request = SemanticRequest('named_account_balance', {'account_phrase': account},
                              claims, families.catalog_digest)
    program = families.lower(SemanticOutcome('request', request), manifest)
    assert ProgramValidator(manifest, AnswerResourcePolicy()).validate(program).ok
    execution = ProgramExecutor(registry, AnswerResourcePolicy()).execute(program, 'card balance?')
    delivery = DeterministicBinder(registry, 'en-US').bind(program, execution)
    assert delivery.result.answered
    assert len(delivery.result.figures) == 1
    figure = delivery.result.figures[0]
    assert (figure['value'], figure['currency'], figure['quantity'], figure['dated']) == (
        '125.00', 'USD', 'owed', '2026-01-31')
    assert figure['record_ids'] == [account, 'example-card-doc']
    assert figure['grade'] == execution.transcript[0].figures[0]['grade']
    assert 'owed' in delivery.result.text
    assert program.shape.clauses[0].slots[0].quantity == 'owed'
    assert all(binding.selector.quantity == 'owed' for binding in program.bindings)
    assert ('2026-01-31' in delivery.result.text) == ('measurement_date' in claims)


def _named_runtime(registry, catalog, phrase, *, question=None, prior_turns=(),
                   source='question', claims=('balance',), modality='native-structured'):
    families = SemanticFamilyRegistry(catalog)
    manifest = CapabilityManifest.from_registry(registry)
    parameters = {'account_phrase': phrase}
    sources = {'account_phrase': {'source': source, 'quote': phrase, 'derivation': 'verbatim'}}
    if source == 'prior_turn':
        sources['account_phrase']['turn'] = 0

    class Adapter:
        def converse(self, messages, tools):
            return _turn('select_named_account_balance', {
                'parameters': parameters, 'parameter_sources': sources,
                'requested_claims': list(claims)})

        def extract(self, pages, prompt):
            return SimpleNamespace(text=json.dumps({
                'request_version': families.output_schema()['oneOf'][0]['properties']['request_version']['enum'][0],
                'catalog_digest': families.catalog_digest,
                'entity_catalog_digest': families.entity_catalog_digest,
                'outcome': 'request', 'family': 'named_account_balance',
                'parameters': {'account_phrase': {'grounded_phrase': True}},
                'parameter_sources': sources, 'requested_claims': list(claims)}),
                request={}, response={}, input_tokens=1, output_tokens=1,
                cost_usd=0, latency_s=.01, resolved_model='synthetic')

    policy = AnswerResourcePolicy()
    compiler = AnswerProgramCompiler(Adapter(), ProgramValidator(manifest, policy),
                                     manifest, policy, modality=modality)
    compiler.set_entity_catalog(catalog)
    return AnswerProgramRuntime(compiler, ProgramExecutor(registry, policy),
                                DeterministicBinder(registry)).answer(QuestionContext(
        question=question or f'Show the balance for {phrase}', prior_turns=prior_turns,
        capability_manifest_digest=manifest.digest))


@pytest.mark.parametrize('kind,quantity', [('depository', 'balance'),
                                          ('investment', 'balance'),
                                          ('liability', 'owed')])
@pytest.mark.parametrize('modality', ['native-structured', 'text-json'])
def test_named_major_roles_deliver_one_account_in_both_protocols(kind, quantity, modality):
    account = 'Example:Measured'
    registry = default_registry(LedgerProjection([
        account_opened(account, kind, 'Example Measured Account', 'EUR', '2026-01-01'),
        closing_balance_observed(account, '75.00', '2026-01-31',
                                 Provenance('example-measurement', 1, 'balance')),
    ]), today='2026-03-01')
    catalog = registry.semantic_entities()
    result = _named_runtime(registry, catalog, account,
                            claims=('balance', 'measurement_date'), modality=modality)
    assert result.result.answered
    assert len(result.result.figures) == 1
    assert result.result.figures[0]['quantity'] == quantity
    assert result.result.figures[0]['currency'] == 'EUR'
    assert result.result.figures[0]['record_ids'] == [account, 'example-measurement']
    assert result.result.figures[0]['dated'] == '2026-01-31'


@pytest.mark.parametrize('change,phrase,status', [
    ('absent', 'Unknown Account', 'capability_gap'),
    ('unknown_kind', 'chk', 'capability_gap'),
    ('missing_kind', 'chk', 'capability_gap'),
    ('truncated', 'checking', 'capability_gap'),
    ('truncated', 'Everyday Checking', 'capability_gap'),
    ('truncated', 'Unknown Account', 'capability_gap'),
    ('duplicate', 'checking', 'needs_clarification'),
    ('complete', 'king', 'capability_gap'),
])
def test_unknown_ambiguous_and_incomplete_account_catalogs_never_read(change, phrase, status):
    registry = _registry()
    catalog = registry.semantic_entities()
    if change in ('unknown_kind', 'missing_kind'):
        row = next(row for row in catalog['accounts'] if row['id'] == 'chk')
        if change == 'unknown_kind':
            row['kind'] = 'unreviewed'
        else:
            row.pop('kind')
    elif change == 'truncated':
        catalog['coverage']['accounts']['complete'] = False
    elif change == 'duplicate':
        catalog['accounts'].append({'id': 'second', 'name': 'Other Checking',
                                    'institution': '', 'kind': 'depository'})
    registry.call = lambda *args, **kwargs: pytest.fail('a non-answer must not read finances')
    result = _named_runtime(registry, catalog, phrase)
    assert result.result.status == status
    assert result.execution is None
    assert result.result.figures == []
    if change == 'duplicate':
        assert result.result.outcome_tag == 'ambiguous_account'
        assert {option['id'] for option in result.result.options} == {'chk', 'second'}


def test_visible_canonical_id_retains_role_in_a_truncated_catalog():
    registry = _registry()
    catalog = registry.semantic_entities()
    catalog['coverage']['accounts']['complete'] = False
    result = _named_runtime(registry, catalog, 'chk')
    assert result.result.answered
    assert result.result.figures[0]['quantity'] == 'balance'


def test_named_role_matching_keeps_grounding_and_ledger_containment_direction():
    registry = admission_registry()
    families = SemanticFamilyRegistry(registry.semantic_entities())
    manifest = CapabilityManifest.from_registry(registry)
    assert families._catalog_candidates('account_phrase', 'checking') == []
    assert len(families._account_role_candidates('checking')) == 1
    for row in registry.semantic_entities()['accounts']:
        phrase = row['id']
        assert families._account_role_candidates(phrase)[0]['id'] == phrase
    phrase = 'checking'
    request = SemanticRequest('named_account_balance', {'account_phrase': phrase},
                              ('balance',), families.catalog_digest,
                              parameter_sources={'account_phrase': {'source': 'question',
                                                'quote': phrase, 'derivation': 'verbatim'}})
    before = request.to_dict()
    program = families.lower(SemanticOutcome('request', request), manifest)
    assert request.to_dict() == before
    assert program.nodes[0].args['filters']['account'] == families._account_role_candidates(phrase)[0]['id']


@pytest.mark.parametrize('closing', [None, '-15.00'])
def test_unmeasured_and_negative_named_debt_never_become_zero_or_held(closing):
    account = 'Liabilities:Loan:Example'
    events = [account_opened(account, 'liability', 'Example Loan', 'USD', '2026-01-01', origin='asserted')]
    if closing is not None:
        events.append(closing_balance_observed(account, closing, '2026-01-31',
                                               Provenance('example-loan-doc', 1, 'balance')))
    registry = default_registry(LedgerProjection(events), today='2026-03-01')
    result = _named_runtime(registry, registry.semantic_entities(), account)
    assert not result.result.answered
    assert result.result.figures == []
    assert result.compilation.program.shape.clauses[0].slots[0].quantity == 'owed'


@pytest.mark.parametrize('question', [
    'Show the latest balance for Everyday Checking',
    'Tell me what sits in Everyday Checking',
    'Bring up the amount held in Everyday Checking',
])
def test_broader_named_phrasings_keep_subject_and_amount_effect(question):
    registry = _registry()
    result = _named_runtime(registry, registry.semantic_entities(), 'Everyday Checking',
                            question=question)
    assert result.result.answered
    assert result.compilation.program.nodes[0].args['filters']['account'] == 'chk'
    assert {binding.hole for binding in result.compilation.program.bindings} == {'balance'}


def test_short_date_follow_up_keeps_grounded_named_subject():
    registry = _registry()
    result = _named_runtime(registry, registry.semantic_entities(), 'Everyday Checking',
        question='And when was that measured?',
        prior_turns=(('Show the balance for Everyday Checking', 'Supported amount shown.'),),
        source='prior_turn', claims=('measurement_date',))
    assert result.result.answered
    assert result.compilation.semantic_outcome.request.parameter_sources['account_phrase']['source'] == 'prior_turn'
    assert result.compilation.program.nodes[0].args['filters']['account'] == 'chk'
    assert result.result.figures[0]['dated'] == '2026-01-31'


def test_named_shape_and_selectors_are_authored_before_financial_read():
    registry = _registry()
    families = SemanticFamilyRegistry(registry.semantic_entities())
    program = families.lower(_request(families, 'named_account_balance',
                                      {'account_phrase': 'Signature Card'}),
                              CapabilityManifest.from_registry(registry))
    before = program.to_dict()
    original = registry.call
    reads = []

    def read(*args, **kwargs):
        assert program.to_dict() == before
        assert before['shape']['clauses'][0]['slots'][0]['quantity'] == 'owed'
        assert all(binding['selector']['quantity'] == 'owed' for binding in before['bindings'])
        reads.append(args[0])
        return original(*args, **kwargs)

    registry.call = read
    execution = ProgramExecutor(registry, AnswerResourcePolicy()).execute(program, 'card balance?')
    DeterministicBinder(registry).bind(program, execution)
    assert reads == ['query_ledger']
    assert program.to_dict() == before


def _measurement_registry(kind, origin, measurement, currency='USD'):
    from viva.ledger import opening_balance_observed, simple_transaction
    account = 'Liabilities:Cards:ExampleMeasured' if kind == 'liability' else 'Assets:ExampleMeasured'
    provenance = Provenance('example-measured-doc', 1, 'measurement')
    events = [account_opened(account, kind, 'Example Measured', currency,
                             '2026-01-01', origin=origin)]
    if measurement == 'movement_only':
        events.append(simple_transaction(account, '25.00', 'EXAMPLE MOVEMENT',
                                         '2026-01-15', provenance=provenance))
    elif measurement == 'opening_backed':
        events.extend([
            opening_balance_observed(account, '100.00', '2026-01-01', provenance),
            simple_transaction(account, '25.00', 'EXAMPLE MOVEMENT',
                               '2026-01-15', provenance=provenance),
        ])
    elif measurement != 'opened_only':
        events.append(closing_balance_observed(account, measurement,
                                               '2026-01-31', provenance))
    return account, default_registry(LedgerProjection(events), today='2026-03-01')


@pytest.mark.parametrize('origin', ['issued', 'asserted'])
@pytest.mark.parametrize('measurement,currency', [
    ('opened_only', 'USD'), ('movement_only', 'USD'), ('0.00', 'USD'),
    ('75.00', 'USD'), ('opening_backed', 'USD'), ('-15.00', 'USD'),
    ('75.00', 'EUR'),
])
def test_named_liability_requires_existing_dated_measurement_for_every_origin(origin, measurement, currency):
    account, registry = _measurement_registry('liability', origin, measurement, currency)
    direct = registry.call('query_ledger', {'entity': 'balances', 'filters': {'account': account}})
    result = _named_runtime(registry, registry.semantic_entities(), account)
    if measurement in ('opened_only', 'movement_only'):
        assert not direct.ok
        assert direct.refusal == 'balance_unobserved'
        assert direct.figures == []
        assert result.result.status == 'missing_data'
        assert result.result.figures == []
    else:
        assert direct.ok
        monetary = [figure for figure in direct.figures if figure['quantity'] == 'owed']
        assert len(monetary) == 1
        figure = monetary[0]
        expected = '125.00' if measurement == 'opening_backed' else measurement
        assert figure['value'] == expected
        assert figure['currency'] == currency
        assert figure['dated'] == ('2026-01-01' if measurement == 'opening_backed' else '2026-01-31')
        assert figure['record_ids'] == [account, 'example-measured-doc']
        assert figure['grade'] == ('unverified' if measurement == 'opening_backed' else 'verified')
        assert any(cut.get('value') == account for cut in figure['boundary']['cut'])
        if measurement == '-15.00':
            assert not result.result.answered
            assert result.result.figures == []
        else:
            assert result.result.answered
            assert len(result.result.figures) == 1
            assert result.result.figures[0]['value'] == expected
            assert result.result.figures[0]['currency'] == currency
            assert result.result.figures[0]['dated'] == figure['dated']
            assert result.result.figures[0]['grade'] == figure['grade']
            assert result.result.figures[0]['record_ids'] == figure['record_ids']
    if measurement in ('movement_only', 'opening_backed'):
        movements = registry.call('list_movements', {'filters': {'account': account}})
        assert movements.ok
        assert any(figure['quantity'] == 'movement' and figure['value'] == '-25.00'
                   for figure in movements.figures)


@pytest.mark.parametrize('kind', ['depository', 'investment'])
@pytest.mark.parametrize('origin', ['issued', 'asserted'])
def test_liability_measurement_correction_preserves_existing_held_origin_policy(kind, origin):
    account, registry = _measurement_registry(kind, origin, 'opened_only')
    direct = registry.call('query_ledger', {'entity': 'balances', 'filters': {'account': account}})
    if origin == 'asserted':
        assert not direct.ok and direct.refusal == 'balance_unobserved'
        assert direct.figures == []
    else:
        assert direct.ok
        held = [figure for figure in direct.figures if figure['quantity'] == 'balance']
        assert len(held) == 1 and held[0]['value'] == '0'
        assert not held[0]['dated']
        assert held[0]['grade'] == 'unverified'


def test_mixed_card_population_keeps_unmeasured_boundary_without_zero_debt():
    measured = 'Liabilities:Cards:ExampleMeasured'
    missing = 'Liabilities:Cards:ExampleMissing'
    registry = default_registry(LedgerProjection([
        account_opened(measured, 'liability', 'Example Measured Card', 'USD', '2026-01-01'),
        closing_balance_observed(measured, '75.00', '2026-01-31',
                                 Provenance('example-measured-doc', 1, 'balance')),
        account_opened(missing, 'liability', 'Example Missing Card', 'USD', '2026-01-01'),
    ]), today='2026-03-01')
    direct = registry.call('query_ledger', {'entity': 'balances', 'filters': {'kind': 'card_account'}})
    assert direct.ok
    owed = [figure for figure in direct.figures if figure['quantity'] == 'owed']
    assert len(owed) == 2
    assert all(figure['value'] == '75.00' for figure in owed)
    assert all(figure['record_ids'] == [measured, 'example-measured-doc'] or
               figure['record_ids'] == ['example-measured-doc', measured] for figure in owed)
    total = next(figure for figure in owed if figure['boundary'].get('unmeasured'))
    assert total['boundary']['accounts']['counted'] == 1
    assert total['boundary']['accounts']['held'] == 2
    assert [item['account'] for item in total['boundary']['unmeasured']] == [missing]
    assert any(item.get('account') == missing for item in direct.identifiers)
    assert any('not reported as zero' in caveat for caveat in direct.caveats)
    assert missing not in {row['record_id'] for row in direct.data['balances']}


def test_all_unmeasured_card_population_preserves_no_accounts_refusal():
    account, registry = _measurement_registry('liability', 'issued', 'opened_only')
    direct = registry.call('query_ledger', {'entity': 'balances', 'filters': {'kind': 'card_account'}})
    assert not direct.ok and direct.refusal == 'no_accounts'
    assert direct.figures == []


@pytest.mark.parametrize('institutions', [
    ('Example North', 'Example South'), ('Example Bank', 'Example Bank'), ('', ''),
])
def test_duplicate_named_account_options_have_distinct_metadata_labels_without_reads(institutions):
    registry = _registry()
    catalog = {'accounts': [
        {'id': f'example-{index}', 'name': 'Example Reserve', 'institution': institution,
         'kind': 'depository'} for index, institution in enumerate(institutions)],
        'coverage': {'accounts': {'count': 2, 'complete': True}}}
    registry.call = lambda *args, **kwargs: pytest.fail('clarification must not read finances')
    result = _named_runtime(registry, catalog, 'Reserve')
    assert result.result.status == 'needs_clarification'
    assert result.result.outcome_tag == 'ambiguous_account'
    assert result.execution is None and result.result.figures == []
    options = result.result.options
    assert {option['id'] for option in options} == {'example-0', 'example-1'}
    assert len({option['label'] for option in options}) == 2
    if institutions[0] != institutions[1]:
        assert {option['label'] for option in options} == {
            f'Example Reserve — {institution}' for institution in institutions}
    else:
        assert all(option['label'] == option['id'] for option in options)
    families = SemanticFamilyRegistry(catalog)
    assert families._display_label('account_phrase', catalog['accounts'][0]) == 'Example Reserve'


def test_named_account_option_uniqueness_precedes_existing_limit():
    registry = _registry()
    catalog = {'accounts': [
        {'id': f'example-{index}', 'name': 'Example Reserve', 'institution': institution,
         'kind': 'depository'} for index, institution in enumerate(
             ('Example North', 'Example South', 'Example East', 'Example North'))],
        'coverage': {'accounts': {'count': 4, 'complete': True}}}
    registry.call = lambda *args, **kwargs: pytest.fail('clarification must not read finances')
    result = _named_runtime(registry, catalog, 'Reserve')
    assert result.result.status == 'needs_clarification'
    assert result.execution is None and result.result.figures == []
    assert len(result.result.options) == 3
    assert len({option['label'] for option in result.result.options}) == 3
    assert next(option for option in result.result.options if option['id'] == 'example-0')['label'] == 'example-0'
    catalog['coverage']['accounts']['complete'] = False
    limited = _named_runtime(registry, catalog, 'Reserve')
    assert limited.result.status == 'capability_gap'
    assert limited.execution is None and limited.result.figures == []
    assert limited.result.options == []


def test_compiler_prompt_matches_advertised_measurement_projection_scenarios():
    registry = _registry()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    compiler = AnswerProgramCompiler(
        None, ProgramValidator(manifest, policy), manifest, policy)
    compiler.set_entity_catalog(registry.semantic_entities())
    prompt = compiler._prompt(QuestionContext(question='Show recorded cash.'))
    for family in ('recorded_cash', 'account_value_history', 'statement_period_coverage',
                   'known_remainder', 'upcoming_obligations', 'goal_progress',
                   'savings_scenario', 'loan_payoff_scenario', 'cash_flow_scenario'):
        assert family in prompt
    prose = ' '.join(prompt.split())
    assert 'projections and scenarios are not yet in this active catalog' not in prose
    assert 'Payment terms, minimum payments and contractual due dates remain unsupported.' in prose
