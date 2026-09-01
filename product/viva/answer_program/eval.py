"""Keyed end-to-end scoring for AnswerProgram model admission."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
from dataclasses import dataclass

CASES = pathlib.Path(__file__).resolve().parent.parent / "evals" / "answer-program-cases-v1.json"
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


def load_cases(path=CASES) -> tuple[EvalCase, ...]:
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if raw.get("version") != "answer-program-cases-v1":
        raise ValueError("unsupported answer-program case version")
    cases = tuple(EvalCase.from_dict(item) for item in raw.get("cases", []))
    if len(cases) != 10 or len({case.id for case in cases}) != len(cases):
        raise ValueError("the frozen admission corpus must contain ten unique cases")
    return cases


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


def score(case: EvalCase, runtime_result) -> CaseScore:
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

        from .intents import KnownIntentRegistry
        contract = KnownIntentRegistry().semantic_contract(program.question_kind)
        if contract is None:
            defects.append("unreviewed_semantic_contract")
        else:
            missing_claims = (set(case.required_semantic_claims)
                              - set(contract["semantic_claims"]))
            if missing_claims:
                defects.append("missing_semantic_claim")
            expected_scopes = set(case.expected.get("scope") or ())
            if not expected_scopes <= set(contract["scopes"]):
                defects.append("wrong_scope")
            expected_subject = str(case.expected.get("subject") or "")
            if expected_subject and contract["subject"] != expected_subject:
                defects.append("wrong_subject")
            expected_period = str(case.expected.get("period") or "")
            contract_period = contract["period"]
            period_kind_matches = (
                not expected_period or contract_period == expected_period
                or (contract_period == "latest_complete_calendar_month"
                    and (expected_period == "latest_complete_calendar_month"
                         or "/" in expected_period))
                or (contract_period == "explicit" and "/" in expected_period))
            if not period_kind_matches:
                defects.append("wrong_period_semantics")
        if hasattr(program, "to_dict") and contract is not None:
            parameters = {}
            if program.question_kind == "largest_spending_movements":
                movement = next((node for node in program.nodes
                                 if node.tool == "list_movements"), None)
                window = ((movement.args.get("filters") or {}).get("window")
                          if movement is not None else {}) or {}
                parameters = {key: window.get(key, "") for key in ("from", "to")}
            manifest = type("Manifest", (), {
                "digest": program.capability_manifest_digest})()
            try:
                reviewed = KnownIntentRegistry().instantiate(
                    program.question_kind, parameters, manifest)
            except ValueError:
                reviewed = None
            if reviewed is None or program.to_dict() != reviewed.to_dict():
                defects.append("reviewed_intent_mismatch")

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


__all__ = ["CASES", "ADVERSARIAL_CASES", "EvalCase", "CaseScore",
           "AdversarialCase", "AdversarialScore", "load_cases",
           "load_adversarial_cases", "corpus_digest",
           "evaluate_adversarial", "score"]
