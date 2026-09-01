"""Exact-profile model admission with absolute financial-safety gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime
import hashlib
import json
import math

from vivacore import promptstore, versions

from ..tools.registry import PACKAGE, PROMPTS
from .capability import CapabilityManifest
from .compiler import COMPILER_VERSION
from .schema import (ANSWER_PROGRAM_VERSION, CAPABILITY_MANIFEST_VERSION,
                     AnswerProgram)

ADMISSION_PROFILE_VERSION = "answer-program-admission-v1"


@dataclass(frozen=True)
class AdmissionThresholds:
    first_attempt_validity: float
    repaired_validity: float
    answerable_completion: float

    def __post_init__(self):
        for value in asdict(self).values():
            if not 0 <= value <= 1:
                raise ValueError("admission thresholds must be between zero and one")


@dataclass(frozen=True)
class AdmissionReport:
    measured: bool
    admitted: bool
    metrics: dict
    hard_failures: tuple[str, ...]
    threshold_failures: tuple[str, ...]
    identity: dict = None
    contract_digests: dict = None
    adversarial_passed: bool = False
    thresholds: dict = None
    case_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdmissionProfile:
    provider: str
    requested_model: str
    resolved_model: str
    model_version: str
    endpoint: str
    modality: str
    locale_family: str
    capability_manifest_digest: str
    thresholds: AdmissionThresholds
    metrics: dict
    admission_report_digest: str
    prompt_version: str = COMPILER_VERSION
    prompt_digest: str = ""
    program_schema_digest: str = ""
    resource_policy_digest: str = ""
    financial_query_schema_digest: str = ""
    keyed_corpus_digest: str = ""
    adversarial_corpus_digest: str = ""
    reviewed_intents_digest: str = ""
    persona_pack_digest: str = ""
    program_schema_version: str = ANSWER_PROGRAM_VERSION
    capability_manifest_version: str = CAPABILITY_MANIFEST_VERSION
    profile_version: str = ADMISSION_PROFILE_VERSION
    admitted_at: str = ""

    def __post_init__(self):
        if not all((self.provider, self.requested_model, self.resolved_model,
                    self.model_version, self.endpoint, self.modality,
                    self.capability_manifest_digest,
                    self.program_schema_digest, self.resource_policy_digest,
                    self.financial_query_schema_digest,
                    self.keyed_corpus_digest, self.adversarial_corpus_digest,
                    self.reviewed_intents_digest, self.persona_pack_digest,
                    self.admission_report_digest)):
            raise ValueError("an admission profile needs exact model and contract ids")
        if not self.prompt_digest:
            object.__setattr__(self, "prompt_digest",
                               promptstore.digest(PROMPTS, self.prompt_version))
        if not self.admitted_at:
            object.__setattr__(self, "admitted_at",
                               datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self):
        out = asdict(self)
        return out


def evaluate(case_scores, *, attempts, first_attempt_valid, thresholds,
             within_repair_valid=None,
             keyed_semantic_errors=0, missing_data_as_zero=0,
             hypothetical_as_measured=0, resource_exhaustions=0,
             latency_p95_ms=0, evidence_payload_p95_bytes=0,
             latency_ceiling_ms=None, evidence_ceiling_bytes=None,
             identity=None, contract_digests=None, adversarial_passed=False):
    scores = tuple(case_scores)
    attempts = tuple(int(value) for value in attempts)
    first = tuple(bool(value) for value in first_attempt_valid)
    repaired = (tuple(bool(value) for value in within_repair_valid)
                if within_repair_valid is not None
                else tuple(item.passed for item in scores))
    measured = bool(scores) and all(item.measured for item in scores)
    total = max(1, len(scores))
    p95_attempts = (sorted(attempts)[max(0, math.ceil(len(attempts) * .95) - 1)]
                    if attempts else 0)
    metrics = {
        "cases": len(scores),
        "first_attempt_validity": sum(first) / max(1, len(first)),
        "repaired_validity": sum(repaired) / max(1, len(repaired)),
        "answerable_completion": sum(item.passed for item in scores) / total,
        "unsupported_figures": sum(item.unsupported_figures for item in scores),
        "confidently_wrong": sum(item.confidently_wrong for item in scores),
        "keyed_semantic_errors": int(keyed_semantic_errors),
        "missing_data_as_zero": int(missing_data_as_zero),
        "hypothetical_as_measured": int(hypothetical_as_measured),
        "resource_exhaustions": int(resource_exhaustions),
        "p95_model_attempts": p95_attempts,
        "latency_p95_ms": int(latency_p95_ms),
        "evidence_payload_p95_bytes": int(evidence_payload_p95_bytes),
    }
    hard = []
    for name in ("unsupported_figures", "confidently_wrong",
                 "keyed_semantic_errors", "missing_data_as_zero",
                 "hypothetical_as_measured", "resource_exhaustions"):
        if metrics[name]:
            hard.append(name)
    if any(not item.passed for item in scores):
        hard.append("keyed_case_failure")
    if p95_attempts > 2:
        hard.append("model_attempt_bound")
    if latency_ceiling_ms is not None and latency_p95_ms > latency_ceiling_ms:
        hard.append("latency_ceiling")
    if (evidence_ceiling_bytes is not None
            and evidence_payload_p95_bytes > evidence_ceiling_bytes):
        hard.append("evidence_payload_ceiling")
    threshold_failures = []
    for name in ("first_attempt_validity", "repaired_validity",
                 "answerable_completion"):
        if metrics[name] < getattr(thresholds, name):
            threshold_failures.append(name)
    if not measured:
        hard.append("unmeasured_model")
    admitted = measured and not hard and not threshold_failures
    return AdmissionReport(measured, admitted, metrics, tuple(hard),
                           tuple(threshold_failures), dict(identity or {}),
                           dict(contract_digests or {}), adversarial_passed,
                           asdict(thresholds),
                           tuple(str(item.case_id) for item in scores))


def admitted_profile(report, *, manifest):
    if not report.admitted:
        raise ValueError("a model profile cannot be published before every gate passes")
    identity = dict(report.identity or {})
    contracts = dict(report.contract_digests or {})
    required_identity = {"provider", "requested_model", "resolved_model",
                         "endpoint", "modality", "locale_family"}
    if not required_identity <= set(identity) or not all(identity.values()):
        raise ValueError("a model profile needs the identity measured by the suite")
    if validate_admission_report(report):
        raise ValueError("a model profile cannot be published before every gate passes")
    if not report.adversarial_passed:
        raise ValueError("a model profile needs the frozen adversarial suite")
    if not report.thresholds:
        raise ValueError("a model profile needs the thresholds used by the suite")
    schema_digest = contracts.get("program_schema")
    if not schema_digest:
        raise ValueError("a model profile needs the measured schema digest")
    if contracts.get("capability_manifest") != manifest.digest:
        raise ValueError("the measured capability manifest differs from this build")
    if contracts.get("compiler_prompt") != promptstore.digest(
            PROMPTS, COMPILER_VERSION):
        raise ValueError("the measured compiler prompt differs from this build")
    if schema_digest != versions.fingerprint(
            versions.path_of(PACKAGE, ANSWER_PROGRAM_VERSION)):
        raise ValueError("the measured schema differs from this build")
    required_contracts = {
        "resource_policy", "financial_query_schema", "keyed_corpus",
        "adversarial_corpus", "reviewed_intents", "persona_pack"}
    if not required_contracts <= set(contracts) or any(
            not contracts[name] for name in required_contracts):
        raise ValueError("a model profile needs every measured build contract")
    return AdmissionProfile(
        provider=identity["provider"], requested_model=identity["requested_model"],
        resolved_model=identity["resolved_model"],
        model_version=identity["resolved_model"], endpoint=identity["endpoint"],
        modality=identity["modality"], locale_family=identity["locale_family"],
        capability_manifest_digest=manifest.digest,
        program_schema_digest=schema_digest,
        resource_policy_digest=contracts["resource_policy"],
        financial_query_schema_digest=contracts["financial_query_schema"],
        keyed_corpus_digest=contracts["keyed_corpus"],
        adversarial_corpus_digest=contracts["adversarial_corpus"],
        reviewed_intents_digest=contracts["reviewed_intents"],
        persona_pack_digest=contracts["persona_pack"],
        thresholds=AdmissionThresholds(**dict(report.thresholds)),
        metrics=dict(report.metrics),
        admission_report_digest=admission_report_digest(report))


def admission_report_digest(report) -> str:
    payload = asdict(report) if isinstance(report, AdmissionReport) else dict(report)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def resource_policy_digest(policy) -> str:
    payload = policy.to_dict() if hasattr(policy, "to_dict") else dict(policy)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def current_contract_digests(manifest, policy) -> dict[str, str]:
    from .eval import ADVERSARIAL_CASES, CASES, corpus_digest
    from .intents import reviewed_intents_digest
    from ..query.schema import FINANCIAL_QUERY_SCHEMA_VERSION

    persona_version = versions.active(PACKAGE, "persona_pack")
    return {
        "program_schema": versions.fingerprint(
            versions.path_of(PACKAGE, ANSWER_PROGRAM_VERSION)),
        "financial_query_schema": versions.fingerprint(
            versions.path_of(PACKAGE, FINANCIAL_QUERY_SCHEMA_VERSION)),
        "compiler_prompt": promptstore.digest(PROMPTS, COMPILER_VERSION),
        "capability_manifest": manifest.digest if manifest is not None else "",
        "resource_policy": resource_policy_digest(policy),
        "keyed_corpus": corpus_digest(CASES),
        "adversarial_corpus": corpus_digest(ADVERSARIAL_CASES),
        "reviewed_intents": (reviewed_intents_digest(manifest)
                             if manifest is not None else ""),
        "persona_pack": versions.fingerprint(
            versions.path_of(PACKAGE, persona_version)),
    }


def validate_admission_report(report, profile=None) -> tuple[str, ...]:
    """Validate the measured gate result and, when supplied, its exact profile."""
    raw = asdict(report) if isinstance(report, AdmissionReport) else dict(report)
    failures = []
    if raw.get("measured") is not True:
        failures.append("admission_report_unmeasured")
    if raw.get("admitted") is not True:
        failures.append("admission_report_not_admitted")
    if list(raw.get("hard_failures") or ()):
        failures.append("admission_report_hard_failures")
    if list(raw.get("threshold_failures") or ()):
        failures.append("admission_report_threshold_failures")
    if raw.get("adversarial_passed") is not True:
        failures.append("adversarial_contract_failure")
    metrics = dict(raw.get("metrics") or {})
    thresholds = dict(raw.get("thresholds") or {})
    from .eval import load_cases
    expected_case_ids = tuple(item.id for item in load_cases())
    observed_case_ids = tuple(map(str, raw.get("case_ids") or ()))
    if observed_case_ids != expected_case_ids:
        failures.append("incomplete_keyed_corpus")
    if int(metrics.get("cases") or 0) != len(expected_case_ids):
        failures.append("admission_case_count_mismatch")
    for name in ("unsupported_figures", "confidently_wrong",
                 "keyed_semantic_errors", "missing_data_as_zero",
                 "hypothetical_as_measured", "resource_exhaustions"):
        if int(metrics.get(name) or 0) != 0:
            failures.append(f"admission_metric_failed:{name}")
    if int(metrics.get("p95_model_attempts") or 0) > 2:
        failures.append("admission_metric_failed:model_attempt_bound")
    if float(metrics.get("answerable_completion") or 0) < 1:
        failures.append("admission_metric_failed:keyed_case_failure")
    for name in ("first_attempt_validity", "repaired_validity",
                 "answerable_completion"):
        if name not in metrics or name not in thresholds:
            failures.append(f"admission_metric_missing:{name}")
        elif float(metrics[name]) < float(thresholds[name]):
            failures.append(f"admission_threshold_failed:{name}")
    if profile is not None:
        identity = dict(raw.get("identity") or {})
        for name in ("provider", "requested_model", "resolved_model", "endpoint",
                     "modality", "locale_family"):
            if str(identity.get(name) or "") != str(getattr(profile, name)):
                failures.append(f"admission_identity_mismatch:{name}")
        contracts = dict(raw.get("contract_digests") or {})
        expected_contracts = {
            "capability_manifest": profile.capability_manifest_digest,
            "compiler_prompt": profile.prompt_digest,
            "program_schema": profile.program_schema_digest,
            "resource_policy": profile.resource_policy_digest,
            "financial_query_schema": profile.financial_query_schema_digest,
            "keyed_corpus": profile.keyed_corpus_digest,
            "adversarial_corpus": profile.adversarial_corpus_digest,
            "reviewed_intents": profile.reviewed_intents_digest,
            "persona_pack": profile.persona_pack_digest,
        }
        for name, expected in expected_contracts.items():
            if str(contracts.get(name) or "") != str(expected):
                failures.append(f"admission_contract_mismatch:{name}")
        if thresholds != asdict(profile.thresholds):
            failures.append("admission_thresholds_mismatch")
        if metrics != dict(profile.metrics):
            failures.append("admission_metrics_mismatch")
    return tuple(failures)


def run_live_suite(*, cases, registry_factory, compiler_factory, thresholds,
                   policy=None, today="", locale="", latency_ceiling_ms=None,
                   evidence_ceiling_bytes=None):
    """Run the frozen suite through a real compiler adapter and fresh fixtures."""
    from .eval import evaluate_adversarial, score
    from .schema import AnswerResourcePolicy
    from .validate import ProgramValidator
    from ..session import Session

    policy = policy or AnswerResourcePolicy()
    scores, attempts, first_valid, repaired_valid = [], [], [], []
    latencies, evidence_sizes = [], []
    turns = []
    manifests = []
    for case in cases:
        registry = registry_factory()
        manifests.append(CapabilityManifest.from_registry(registry))
        session = Session(
            registry, compiler_factory, resource_policy=policy,
            today=(lambda value=today: value), locale=locale,
            prior_turns=case.prior_turns)
        turn = session.ask(case.question)
        turns.append(turn)
        runtime_result = getattr(turn, "_runtime_result", None)
        # Session intentionally exposes serializable turn data, so reconstruct
        # only the scoring facade here rather than retaining a live runtime.
        compilation = type("Compilation", (), {
            "exchanges": turn.exchanges,
            "program": (AnswerProgram.from_dict(turn.program)
                        if turn.program else None)})()
        facade = type("Runtime", (), {"result": turn.result,
                                      "compilation": compilation})()
        scores.append(score(case, facade))
        attempts.append(len(turn.exchanges))
        first_valid.append(bool(turn.exchanges and turn.exchanges[0].parse_ok))
        repaired_valid.append(bool(turn.program))
        latencies.append(sum(exchange.latency_s for exchange in turn.exchanges) * 1000)
        evidence_sizes.append(int((turn.execution or {}).get("evidence_bytes", 0)))

    def p95(values):
        held = sorted(values)
        return held[max(0, math.ceil(len(held) * .95) - 1)] if held else 0

    configured = dict(getattr(compiler_factory, "admission_identity", {}) or {})
    resolved = {exchange.resolved_model for turn in turns
                for exchange in turn.exchanges if exchange.resolved_model}
    modalities = {exchange.modality for turn in turns
                  for exchange in turn.exchanges if exchange.modality}
    manifest_digests = {manifest.digest for manifest in manifests}
    identity = dict(configured)
    if len(resolved) == 1:
        identity["resolved_model"] = next(iter(resolved))
    identity["locale_family"] = (locale.split("-", 1)[0].casefold()
                                 if locale else "und")
    identity_failures = []
    from .eval import load_cases
    if tuple(case.id for case in cases) != tuple(
            case.id for case in load_cases()):
        identity_failures.append("incomplete_keyed_corpus")
    if len(resolved) != 1:
        identity_failures.append("inconsistent_resolved_model")
    if len(modalities) != 1 or (configured.get("modality")
                               and modalities != {configured["modality"]}):
        identity_failures.append("inconsistent_modality")
    if len(manifest_digests) != 1:
        identity_failures.append("inconsistent_capability_manifest")
    required_identity = {"provider", "requested_model", "endpoint", "modality",
                         "resolved_model", "locale_family"}
    if not required_identity <= set(identity) or not all(identity.values()):
        identity_failures.append("unmeasured_model_identity")

    adversarial = ()
    first_program = next((AnswerProgram.from_dict(turn.program) for turn in turns
                          if turn.program), None)
    if first_program is not None and manifests:
        adversarial = evaluate_adversarial(
            first_program, ProgramValidator(manifests[0], policy))
    adversarial_passed = bool(adversarial) and all(item.passed for item in adversarial)
    contracts = current_contract_digests(
        manifests[0] if manifests else None, policy)
    if len(manifest_digests) != 1:
        contracts["capability_manifest"] = ""
    report = evaluate(
        scores, attempts=attempts, first_attempt_valid=first_valid,
        within_repair_valid=repaired_valid,
        thresholds=thresholds,
        keyed_semantic_errors=sum(item.keyed_semantic_errors for item in scores),
        missing_data_as_zero=sum(item.missing_data_as_zero for item in scores),
        hypothetical_as_measured=sum(item.hypothetical_as_measured
                                     for item in scores),
        resource_exhaustions=sum(item.resource_exhaustions for item in scores),
        latency_p95_ms=p95(latencies),
        evidence_payload_p95_bytes=p95(evidence_sizes),
        latency_ceiling_ms=latency_ceiling_ms,
        evidence_ceiling_bytes=evidence_ceiling_bytes,
        identity=identity, contract_digests=contracts,
        adversarial_passed=adversarial_passed)
    hard = list(report.hard_failures)
    hard.extend(identity_failures)
    if not adversarial_passed:
        hard.append("adversarial_contract_failure")
    report = AdmissionReport(
        report.measured, report.admitted and not hard, report.metrics,
        tuple(dict.fromkeys(hard)), report.threshold_failures,
        report.identity, report.contract_digests, report.adversarial_passed,
        report.thresholds, report.case_ids)
    return report, tuple(scores), tuple(turns)


__all__ = ["ADMISSION_PROFILE_VERSION", "AdmissionProfile",
           "AdmissionReport", "AdmissionThresholds", "admitted_profile",
           "admission_report_digest", "resource_policy_digest",
           "current_contract_digests",
           "validate_admission_report", "evaluate", "run_live_suite"]
