"""Keyed end-to-end scoring for AnswerProgram model admission."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
from dataclasses import dataclass

CASES = pathlib.Path(__file__).resolve().parent.parent / "evals" / "semantic-request-cases-v2.json"
LEGACY_CASES = (pathlib.Path(__file__).resolve().parent.parent / "evals"
                / "answer-program-cases-v1.json")
ADVERSARIAL_CASES = (pathlib.Path(__file__).resolve().parent.parent / "evals"
                     / "answer-program-adversarial-v1.json")


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    prior_turns: tuple[tuple[str, str], ...]
    answerability_status: str
    accepted_intents: tuple[str, ...]
    required_semantic_claims: tuple[str, ...]
    required_nodes: tuple[dict, ...]
    permitted_supporting_nodes: tuple[str, ...]
    expected_figures: tuple[dict, ...]
    expected: dict
    expected_outcome_tag: str
    forbidden_claims: tuple[str, ...]
    max_model_attempts: int

    @classmethod
    def from_dict(cls, raw):
        required = {"id", "question", "prior_turns", "answerability_status",
                    "accepted_intents", "required_semantic_claims", "required_nodes",
                    "permitted_supporting_nodes", "expected_figures", "expected",
                    "expected_outcome_tag", "forbidden_claims", "max_model_attempts"}
        if set(raw) != required:
            raise ValueError(f"eval case fields differ: {sorted(set(raw) ^ required)}")
        prior = tuple((str(item["question"]), str(item["answer"]))
                      for item in raw["prior_turns"])
        return cls(str(raw["id"]), str(raw["question"]), prior,
                   str(raw["answerability_status"]),
                   tuple(map(str, raw["accepted_intents"])),
                   tuple(map(str, raw["required_semantic_claims"])),
                   tuple(dict(item) for item in raw["required_nodes"]),
                   tuple(map(str, raw["permitted_supporting_nodes"])),
                   tuple(dict(item) for item in raw["expected_figures"]),
                   dict(raw["expected"]), str(raw["expected_outcome_tag"]),
                   tuple(map(str, raw["forbidden_claims"])),
                   int(raw["max_model_attempts"]))


@dataclass(frozen=True)
class SemanticEvalCase:
    id: str
    exact_group: str
    exact: bool
    question: str
    prior_turns: tuple[tuple[str, str], ...]
    answerability_status: str
    expected_family: str
    expected_parameters: dict
    expected_claims: tuple[str, ...]
    oracle_key: str = ""
    oracle: dict = None
    expected_outcome_tag: str = ""
    forbidden_claims: tuple[str, ...] = ()
    max_model_attempts: int = 1


def load_cases(path=CASES) -> tuple[SemanticEvalCase, ...]:
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if raw.get("version") != "semantic-request-cases-v2":
        raise ValueError("unsupported semantic-request case version")
    repetitions = int(raw.get("exact_repetitions") or 0)
    if repetitions != 5:
        raise ValueError("each exact Witness question must run five times")
    cases = []
    required = {"id", "exact_question", "paraphrases", "family",
                "parameters", "requested_claims", "oracle_key"}
    for definition in raw.get("cases", []):
        if set(definition) != required:
            raise ValueError("semantic admission case fields differ")
        shared = dict(
            exact_group=str(definition["id"]), prior_turns=(),
            answerability_status="answered",
            expected_family=str(definition["family"]),
            expected_parameters=dict(definition["parameters"]),
            expected_claims=tuple(map(str, definition["requested_claims"])),
            oracle_key=str(definition["oracle_key"]), oracle=None)
        for repetition in range(1, repetitions + 1):
            cases.append(SemanticEvalCase(
                id=f"{definition['id']}:exact:{repetition}", exact=True,
                question=str(definition["exact_question"]), **shared))
        for index, question in enumerate(definition["paraphrases"], 1):
            cases.append(SemanticEvalCase(
                id=f"{definition['id']}:paraphrase:{index}", exact=False,
                question=str(question), **shared))
    coverage_required = {
        "id", "question", "prior_turns", "answerability_status", "family",
        "parameters", "requested_claims", "expected_outcome_tag",
        "forbidden_claims", "oracle_key"}
    for definition in raw.get("coverage_cases", []):
        if set(definition) != coverage_required:
            raise ValueError("semantic coverage case fields differ")
        prior = tuple((str(item["question"]), str(item["answer"]))
                      for item in definition["prior_turns"])
        cases.append(SemanticEvalCase(
            id=str(definition["id"]), exact_group=str(definition["id"]),
            exact=False, question=str(definition["question"]), prior_turns=prior,
            answerability_status=str(definition["answerability_status"]),
            expected_family=str(definition["family"]),
            expected_parameters=dict(definition["parameters"]),
            expected_claims=tuple(map(str, definition["requested_claims"])),
            oracle_key=str(definition["oracle_key"]), oracle=None,
            expected_outcome_tag=str(definition["expected_outcome_tag"]),
            forbidden_claims=tuple(map(str, definition["forbidden_claims"]))))
    held = tuple(cases)
    exact = tuple(item for item in held if item.exact)
    if (len(raw.get("cases", [])) != 7 or len(exact) != 35
            or len({item.exact_group for item in exact}) != 7
            or len({item.id for item in held}) != len(held)):
        raise ValueError("semantic admission needs seven questions, five exact runs each")
    return held


def corpus_digest(path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:16]


@dataclass(frozen=True)
class AdversarialCase:
    id: str
    mutation: dict
    expected: str


@dataclass(frozen=True)
class AdversarialScore:
    case_id: str
    passed: bool
    observed: str


def load_adversarial_cases(path=ADVERSARIAL_CASES) -> tuple[AdversarialCase, ...]:
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if raw.get("version") != "answer-program-adversarial-v1":
        raise ValueError("unsupported answer-program adversarial case version")
    cases = tuple(AdversarialCase(str(item["id"]), dict(item["mutation"]),
                                  str(item["expected"]))
                  for item in raw.get("cases", []))
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("the adversarial corpus must contain unique cases")
    return cases


def _adversarial_query(operator, args):
    steps = [{"id": "rows", "op": "scan", "inputs": [],
              "args": {"source": "movements"}}]
    output = "rows"
    if operator:
        steps.append({"id": "attack", "op": operator, "inputs": ["rows"],
                      "args": dict(args)})
        output = "attack"
    return {
        "query_version": "financial-query-v1", "steps": steps,
        "output": output,
        "emit": {"value_field": "amount", "what_field": "description",
                 "currency_field": "currency", "dated_field": "date",
                 "quantity": "movement"},
    }


def _mutate_program(base: dict, mutation: dict) -> dict:
    raw = copy.deepcopy(base)
    if mutation.get("operator"):
        raw["nodes"] = [{
            "id": "attack", "kind": "financial_query", "depends_on": [],
            "importance": "required",
            "query": _adversarial_query(str(mutation["operator"]),
                                        {"query": mutation.get("query", "")}),
        }]
        raw["bindings"][0]["source"] = "attack"
    elif mutation.get("tool"):
        raw["nodes"][0].update(kind="tool_read", tool=str(mutation["tool"]),
                               args={})
    elif mutation.get("shape_text"):
        raw["shape"]["clauses"][0]["text"] = str(mutation["shape_text"])
    elif "query_count" in mutation:
        raw["nodes"] = [{
            "id": "attack", "kind": "financial_query", "depends_on": [],
            "importance": "required",
            "query": _adversarial_query("limit",
                                        {"count": mutation["query_count"]}),
        }]
        raw["bindings"][0]["source"] = "attack"
    elif mutation.get("input"):
        first = raw["nodes"][0]
        first["depends_on"] = [str(mutation["input"])]
        later = copy.deepcopy(first)
        later.update(id=str(mutation["input"]), depends_on=[])
        raw["nodes"].append(later)
    elif mutation.get("capability_manifest_digest"):
        raw["capability_manifest_digest"] = str(
            mutation["capability_manifest_digest"])
    else:
        raise ValueError(f"unknown adversarial mutation: {mutation!r}")
    return raw


def evaluate_adversarial(base_program, validator, *, cases=None):
    """Prove every frozen unsafe mutation is rejected before execution."""
    from .schema import AnswerProgram, ContractError

    base = (base_program.to_dict()
            if isinstance(base_program, AnswerProgram) else dict(base_program))
    scores = []
    for case in cases or load_adversarial_cases():
        try:
            program = AnswerProgram.from_dict(_mutate_program(base, case.mutation))
            validation = validator.validate(program)
            observed = "; ".join(
                f"{item.tag}: {item.message}" for item in validation.defects)
            if validation.ok:
                observed = "accepted"
        except (ContractError, ValueError) as error:
            observed = str(error)
        normalize = lambda value: " ".join(
            str(value).casefold().replace("_", " ").replace("-", " ").split())
        scores.append(AdversarialScore(
            case.id, normalize(case.expected) in normalize(observed), observed))
    return tuple(scores)


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    measured: bool
    passed: bool
    defects: tuple[str, ...]
    unsupported_figures: int
    confidently_wrong: int
    keyed_semantic_errors: int = 0
    missing_data_as_zero: int = 0
    hypothetical_as_measured: int = 0
    resource_exhaustions: int = 0


def derive_semantic_oracle(case: SemanticEvalCase, registry, manifest, policy,
                           *, locale: str = "") -> dict:
    """Build a keyed oracle locally, without consulting the candidate model."""
    if not case.oracle_key:
        raise ValueError(f"admission case {case.id!r} has no oracle key")
    if case.answerability_status != "answered":
        return {"oracle_key": case.oracle_key, "figures": [],
                "exact_figures": True}

    from .bind import DeterministicBinder
    from .execute import ProgramExecutor
    from .intents import (SemanticFamilyRegistry, SemanticOutcome,
                          SemanticRequest)
    from .validate import ProgramValidator

    families = SemanticFamilyRegistry()
    family = families.get(case.expected_family)
    if family is None or not family.runtime_selectable:
        raise ValueError(
            f"oracle {case.oracle_key!r} names an unreviewed semantic family")
    request = SemanticRequest(
        case.expected_family, dict(case.expected_parameters),
        tuple(case.expected_claims), families.catalog_digest)
    program = families.lower(SemanticOutcome("request", request), manifest)
    checked = ProgramValidator(manifest, policy).validate(program)
    if not checked.ok:
        raise ValueError(
            f"oracle {case.oracle_key!r} did not lower to a valid program")
    execution = ProgramExecutor(
        registry, policy,
        query_executor=getattr(registry, "query_executor", None)).execute(
            program, case.question)
    result = DeterministicBinder(registry, locale).bind(program, execution).result
    if not result.answered:
        raise ValueError(
            f"oracle {case.oracle_key!r} is not answered by its fresh fixture")

    figures = []
    for figure in result.figures:
        expected = {
            name: str(figure.get(name, ""))
            for name in ("value", "currency", "quantity", "dated")}
        expected["record_ids_exact"] = sorted(
            str(item) for item in figure.get("record_ids") or ())
        figures.append(expected)
    oracle = {"oracle_key": case.oracle_key, "figures": figures,
              "exact_figures": True}
    if "unclear_completeness_language" in case.forbidden_claims:
        oracle["required_completeness_text"] = str(result.text)
    return oracle


def _score_semantic(case: SemanticEvalCase, runtime_result) -> CaseScore:
    compilation = runtime_result.compilation
    exchanges = tuple(getattr(compilation, "exchanges", ()) or ())
    if (not exchanges or all((getattr(exchange, "defect", {}) or {}).get("tag")
                             == "model_unreachable" for exchange in exchanges)):
        return CaseScore(case.id, False, False, ("model_not_reached",), 0, 0)
    defects = []
    oracle = dict(case.oracle or {})
    if not oracle:
        return CaseScore(case.id, False, False,
                         ("missing_deterministic_oracle",), 0, 0)
    result = runtime_result.result
    program = getattr(compilation, "program", None)
    semantic = getattr(compilation, "semantic_outcome", None)
    request = getattr(semantic, "request", None)
    if result.status != case.answerability_status:
        defects.append("wrong_status")
    if result.outcome_tag != case.expected_outcome_tag:
        defects.append("wrong_outcome_tag")
    if len(exchanges) > case.max_model_attempts:
        defects.append("routine_question_needed_repair")
    expected_non_answer = case.answerability_status != "answered"
    if expected_non_answer:
        expected_kind = {
            "needs_clarification": "clarify",
            "needs_assumption": "needs_assumption",
            "outside_domain": "outside_domain",
            "capability_gap": "unsupported",
        }.get(case.answerability_status, "")
        detail = dict(getattr(semantic, "detail", None) or {})
        if (semantic is None or semantic.kind != expected_kind
                or request is not None):
            defects.append("wrong_non_answer_semantics")
        if case.expected_outcome_tag and detail.get("tag") != case.expected_outcome_tag:
            defects.append("wrong_non_answer_tag")
        if expected_kind == "clarify" and (
                not detail.get("question")
                or not isinstance(detail.get("options"), list)):
            defects.append("wrong_non_answer_shape")
        expected_mode = {
            "clarify": "clarify", "needs_assumption": "needs_assumption",
            "outside_domain": "outside_domain"}.get(expected_kind)
        if expected_mode is not None and (
                program is None or program.mode != expected_mode):
            defects.append("wrong_non_answer_program")
    else:
        if request is None:
            defects.append("no_semantic_request")
        else:
            if request.family != case.expected_family:
                defects.append("wrong_family")
            if request.parameters != case.expected_parameters:
                defects.append("wrong_parameters")
            if set(request.requested_claims) != set(case.expected_claims):
                defects.append("wrong_requested_claims")
        if program is None:
            defects.append("no_lowered_program")
        elif program.question_kind != case.expected_family:
            defects.append("wrong_lowered_family")

    figures = list(getattr(result, "figures", ()) or ())
    unsupported = sum(1 for figure in figures
                      if figure.get("kind") in ("financial", "computed")
                      and not figure.get("record_ids"))
    if unsupported:
        defects.append("unsupported_figure")
    if any(figure.get("kind") == "hypothetical" for figure in figures):
        defects.append("hypothetical_as_measured")
    expected_figures = list(oracle.get("figures") or ())
    unmatched = set(range(len(figures)))
    wrong = 0
    def oracle_matches(figure, expected):
        for key, value in expected.items():
            if key == "subject_record_id":
                if str(value) not in {str(item) for item in
                                      figure.get("record_ids") or ()}:
                    return False
            elif key == "record_ids_exact":
                if sorted(str(item) for item in figure.get("record_ids") or ()) \
                        != sorted(str(item) for item in value):
                    return False
            elif str(figure.get(key, "")) != str(value):
                return False
        return True
    for expected in expected_figures:
        found = next((index for index in unmatched
                      if oracle_matches(figures[index], expected)), None)
        if found is None:
            wrong += 1
        else:
            unmatched.remove(found)
    if oracle.get("exact_figures", True) and unmatched:
        wrong += len(unmatched)
    if wrong:
        defects.append("wrong_keyed_figure")
    family = case.expected_family
    if result.status == "answered":
        quantities = {str(figure.get("quantity") or "") for figure in figures}
        if family == "named_account_balance":
            if (len(figures) != 1 or quantities != {"balance"}
                    or not figures[0].get("dated")):
                defects.append("wrong_named_account_result")
        elif family == "needs_attention" and quantities != {"count"}:
            defects.append("wrong_attention_result")
        elif family == "category_spending_period":
            wanted = {"kind": "period", "value": case.expected_parameters["from"],
                      "to": case.expected_parameters["to"]}
            if (quantities != {"spending"} or any(
                    wanted not in ((figure.get("boundary") or {}).get("selected")
                                   or ()) for figure in figures)):
                defects.append("wrong_period_or_quantity")
        elif family == "net_worth":
            if quantities != {"net_worth"} or any(
                    node.args.get("metric") == "stalest_balance"
                    for node in program.nodes):
                defects.append("wrong_net_worth_claim")
        elif family == "credit_card_debt":
            whole = [figure for figure in figures
                     if (figure.get("boundary") or {}).get("whole")]
            rows = [figure for figure in figures
                    if not (figure.get("boundary") or {}).get("whole")]
            if quantities != {"owed"} or not whole or not rows:
                defects.append("incomplete_card_population")
        elif family == "classification_explanation" and (
                quantities != {"movement"} or any(
                    "treated as" not in str(figure.get("what") or "")
                    for figure in figures)):
            defects.append("wrong_classification_explanation")
    normalized_text = " ".join(str(getattr(result, "text", "") or "").casefold().split())
    for forbidden in case.forbidden_claims:
        phrase = " ".join(forbidden.casefold().replace("_", " ").split())
        if phrase and phrase not in {"missing data as zero",
                                     "unclear completeness language"} \
                and phrase in normalized_text:
            defects.append("forbidden_claim")
    missing_zero = int(
        "missing_data_as_zero" in case.forbidden_claims
        and result.status in ("answered", "partial")
        and any(str(figure.get("value")) in ("0", "0.0", "0.00")
                and not figure.get("record_ids") for figure in figures))
    if missing_zero:
        defects.append("missing_data_as_zero")
    unclear = int(bool(
        "unclear_completeness_language" in case.forbidden_claims
        and oracle.get("required_completeness_text")
        and str(oracle["required_completeness_text"]).casefold()
        not in normalized_text))
    if unclear:
        defects.append("unclear_completeness_language")
    exhausted = int(result.outcome_tag in {
        "execution_deadline", "evidence_limit", "figure_limit",
        "program_too_large"})
    semantic_tags = {
        "wrong_family", "wrong_parameters", "wrong_requested_claims",
        "wrong_lowered_family", "wrong_named_account_result",
        "wrong_attention_result", "wrong_period_or_quantity",
        "wrong_net_worth_claim", "incomplete_card_population",
        "wrong_classification_explanation", "routine_question_needed_repair",
        "wrong_keyed_figure", "missing_data_as_zero",
        "unclear_completeness_language", "forbidden_claim",
        "wrong_non_answer_semantics", "wrong_non_answer_tag",
        "wrong_non_answer_shape", "wrong_non_answer_program"}
    semantic_errors = sum(item in semantic_tags for item in defects)
    return CaseScore(case.id, True, not defects, tuple(defects), unsupported,
                     wrong, semantic_errors, missing_zero, 0, exhausted)


def score(case: EvalCase, runtime_result) -> CaseScore:
    if isinstance(case, SemanticEvalCase):
        return _score_semantic(case, runtime_result)
    compilation = runtime_result.compilation
    if (not compilation.exchanges
            or all((getattr(exchange, "defect", {}) or {}).get("tag")
                   == "model_unreachable"
                   for exchange in compilation.exchanges)):
        return CaseScore(case.id, False, False, ("model_not_reached",), 0, 0)
    defects = []
    result = runtime_result.result
    program = compilation.program
    if result.status != case.answerability_status:
        defects.append("wrong_status")
    if case.expected_outcome_tag and result.outcome_tag != case.expected_outcome_tag:
        defects.append("wrong_outcome_tag")
    if len(compilation.exchanges) > case.max_model_attempts:
        defects.append("model_attempt_limit")
    if program is None:
        defects.append("no_program")
    else:
        if program.question_kind not in case.accepted_intents:
            defects.append("wrong_intent")
        actual_nodes = [{"tool": node.tool or ("compute" if node.kind == "compute"
                                                else node.kind),
                         "args": node.args}
                        for node in program.nodes if node.importance == "required"]
        for expected in case.required_nodes:
            if expected not in actual_nodes:
                defects.append("missing_required_node")
        for actual in actual_nodes:
            if actual not in case.required_nodes:
                defects.append("unexpected_required_node")
        permitted = set(case.permitted_supporting_nodes)
        for node in program.nodes:
            if node.importance not in ("supporting", "optional"):
                continue
            name = node.tool or ("compute" if node.kind == "compute" else node.kind)
            if name not in permitted:
                defects.append("unpermitted_supporting_node")

    figures = list(result.figures)
    unsupported = sum(1 for fig in figures
                      if fig.get("kind") in ("financial", "computed")
                      and not fig.get("record_ids"))
    wrong = missing = 0
    matched = set()
    boundary_rules = list(case.expected.get("figure_boundaries") or ())
    if len(boundary_rules) != len(case.expected_figures):
        defects.append("invalid_expected_boundary_contract")
    def figure_matches(fig, expected, boundary_rule):
        for key, value in expected.items():
            if key == "period":
                wanted = tuple(str(value).split("/", 1))
                spans = {(str(item.get("value") or ""),
                          str(item.get("to") or ""))
                         for item in ((fig.get("boundary") or {}).get(
                             "selected") or ())
                         if item.get("kind") == "period"}
                if wanted not in spans:
                    return False
            elif str(fig.get(key, "")) != str(value):
                return False
        boundary = fig.get("boundary") or {}
        if bool(boundary.get("whole", False)) is not bool(
                boundary_rule.get("whole", False)):
            return False
        actual_cuts = {str(item.get("kind") or ""): str(item.get("value") or "")
                       for item in boundary.get("cut") or ()}
        expected_cuts = {str(kind): str(wanted) for kind, wanted in
                         dict(boundary_rule.get("cut") or {}).items()}
        if "period" in expected:
            expected_cuts["period"] = str(expected["period"]).split("/", 1)[0]
        if actual_cuts != expected_cuts:
            return False
        return True
    for expected_index, expected in enumerate(case.expected_figures):
        boundary_rule = (boundary_rules[expected_index]
                         if expected_index < len(boundary_rules) else {})
        found = next((index for index, fig in enumerate(figures)
                      if index not in matched
                      and figure_matches(fig, expected, boundary_rule)), None)
        if found is not None:
            matched.add(found)
            continue
        comparable = next((index for index, fig in enumerate(figures)
                           if index not in matched
                           and all(str(fig.get(key, ""))
                                   == str(expected.get(key, ""))
                                   for key in ("quantity", "currency")
                                   if key in expected)), None)
        if comparable is not None:
            matched.add(comparable)
            wrong += 1
        else:
            missing += 1
    unexpected = [fig for index, fig in enumerate(figures)
                  if index not in matched]
    if unexpected:
        wrong += len(unexpected)
        defects.append("unexpected_keyed_figure")
    if unsupported:
        defects.append("unsupported_figure")
    if wrong:
        defects.append("wrong_keyed_figure")
    if missing:
        defects.append("missing_keyed_figure")
    expected_period = str(case.expected.get("period") or "")
    grounded_status = result.status in ("answered", "partial")
    if "/" in expected_period and grounded_status:
        start, end = expected_period.split("/", 1)
        spans = {(str(item.get("value") or ""), str(item.get("to") or ""))
                 for fig in figures
                 for item in ((fig.get("boundary") or {}).get("selected") or [])
                 if item.get("kind") == "period"}
        if (start, end) not in spans:
            defects.append("wrong_period")
    if case.expected.get("records_required") and grounded_status:
        if any(fig.get("kind") in ("financial", "computed")
               and not fig.get("record_ids") for fig in figures):
            defects.append("records_missing")
    if case.expected.get("caveats_required") and grounded_status:
        observed_disclosures = {
            str(item).split(":", 1)[0]
            for item in (getattr(result, "disclosures", ()) or ())}
        required_disclosures = set(case.expected.get("disclosures") or ("caveat",))
        if not required_disclosures <= observed_disclosures:
            defects.append("missing_caveat")
    normalized_text = " ".join(str(getattr(result, "text", "") or "").casefold().replace(
        "_", " ").replace("-", " ").split())
    for forbidden in case.forbidden_claims:
        phrase = " ".join(forbidden.casefold().replace("_", " ").split())
        if phrase and phrase in normalized_text:
            defects.append("forbidden_claim")
            break
    hypothetical = sum(1 for fig in figures
                       if fig.get("kind") == "hypothetical"
                       and case.answerability_status in ("answered", "partial"))
    missing_zero = int(
        grounded_status
        and "missing_data_as_zero" in case.forbidden_claims
        and any(str(fig.get("value")) in ("0", "0.0", "0.00")
                and not fig.get("record_ids") for fig in figures))
    exhausted = int(result.outcome_tag in {
        "execution_deadline", "evidence_limit", "figure_limit",
        "program_too_large"})
    semantic_tags = {
        "wrong_intent", "missing_required_node", "unexpected_required_node",
        "unpermitted_supporting_node", "reviewed_intent_mismatch",
        "unreviewed_semantic_contract", "missing_semantic_claim", "wrong_scope",
        "wrong_subject", "wrong_period_semantics", "wrong_period",
        "records_missing", "missing_caveat", "forbidden_claim",
        "unexpected_keyed_figure"}
    semantic_errors = sum(1 for defect in defects if defect in semantic_tags)
    return CaseScore(case.id, True, not defects, tuple(defects), unsupported, wrong,
                     semantic_errors, missing_zero, hypothetical, exhausted)


__all__ = ["CASES", "LEGACY_CASES", "ADVERSARIAL_CASES", "EvalCase",
           "SemanticEvalCase", "CaseScore",
           "AdversarialCase", "AdversarialScore", "load_cases",
           "load_adversarial_cases", "corpus_digest",
           "evaluate_adversarial", "derive_semantic_oracle", "score"]
