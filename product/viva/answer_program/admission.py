"""Exact-profile model admission with absolute financial-safety gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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

ADMISSION_PROFILE_VERSION = "semantic-request-admission-v4"


def _semantic_observation(raw) -> dict:
    """A bounded diagnostic view of interpretation, without source excerpts."""
    held = dict(raw or {})
    out = {"outcome": str(held.get("outcome") or "")}
    if out["outcome"] == "request":
        out.update(
            family=str(held.get("family") or ""),
            entity_catalog_digest=str(
                held.get("entity_catalog_digest") or "")[:32],
            parameters={str(key): str(value)[:160]
                        for key, value in dict(
                            held.get("parameters") or {}).items()},
            requested_claims=[str(item)[:80] for item in
                              list(held.get("requested_claims") or ())[:12]])
    elif held.get("tag"):
        out["tag"] = str(held["tag"])[:80]
    return out


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
    attempt_evidence: tuple[dict, ...] = ()
    publication_source: str = ""
    admission_fixture_digest: str = ""
    oracle_set_digest: str = ""


@dataclass(frozen=True)
class AdmissionPreflightFailure:
    case_id: str
    oracle_key: str
    error_type: str
    message: str


class AdmissionPreflightError(ValueError):
    """All deterministic oracle failures, safe for a tester to serialize."""

    def __init__(self, failures, *, case_count: int, ready_count: int):
        self.failures = tuple(failures)
        self.case_count = int(case_count)
        self.ready_count = int(ready_count)
        super().__init__(
            f"deterministic oracle preflight failed for {len(self.failures)} "
            f"of {self.case_count} cases")

    def to_dict(self) -> dict:
        return {
            "status": "blocked",
            "reason": "deterministic_oracle_preflight_failed",
            "case_count": self.case_count,
            "ready_count": self.ready_count,
            "failed_count": len(self.failures),
            "failures": [asdict(item) for item in self.failures],
        }


@dataclass(frozen=True)
class AdmissionOracleSet:
    """Immutable canonical JSON snapshots of every prederived oracle."""

    entries: tuple[tuple[str, str], ...]
    digest: str

    def oracle_for(self, case_id: str) -> dict:
        for candidate, snapshot in self.entries:
            if candidate == case_id:
                return json.loads(snapshot)
        raise KeyError(case_id)


_MEASURED_RUN_SEAL = object()


class _MeasuredAdmissionRun:
    """Process-local proof that this report came from the live suite runner."""

    __slots__ = ("_report", "_report_digest", "_report_snapshot", "_seal")

    def __init__(self, report, seal):
        if seal is not _MEASURED_RUN_SEAL:
            raise TypeError("measured admission runs are minted by run_live_suite")
        snapshot = json.dumps(asdict(report), sort_keys=True,
                              separators=(",", ":"))
        object.__setattr__(self, "_report", report)
        object.__setattr__(self, "_report_snapshot", snapshot)
        object.__setattr__(self, "_report_digest", hashlib.sha256(
            snapshot.encode()).hexdigest())
        object.__setattr__(self, "_seal", seal)

    @property
    def report(self):
        return self._report

    def __setattr__(self, name, value):
        raise TypeError("a measured admission run is immutable")

    def __reduce__(self):
        raise TypeError("a measured admission run is deliberately non-serializable")


def _report_from_measured_run(measured_run):
    if (not isinstance(measured_run, _MeasuredAdmissionRun)
            or measured_run._seal is not _MEASURED_RUN_SEAL):
        raise ValueError(
            "a model profile cannot be published without a sealed measured live run")
    snapshot = json.dumps(asdict(measured_run._report), sort_keys=True,
                          separators=(",", ":"))
    digest = hashlib.sha256(snapshot.encode()).hexdigest()
    if (snapshot != measured_run._report_snapshot
            or digest != measured_run._report_digest):
        raise ValueError("the sealed measured live run report was mutated")
    return measured_run._report


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
    semantic_request_schema_digest: str = ""
    semantic_catalog_digest: str = ""
    deterministic_builder_digest: str = ""
    keyed_corpus_digest: str = ""
    adversarial_corpus_digest: str = ""
    persona_pack_digest: str = ""
    admission_fixture_digest: str = ""
    oracle_set_digest: str = ""
    program_schema_version: str = ANSWER_PROGRAM_VERSION
    capability_manifest_version: str = CAPABILITY_MANIFEST_VERSION
    profile_version: str = ADMISSION_PROFILE_VERSION
    admitted_at: str = ""

    def __post_init__(self):
        if self.profile_version != ADMISSION_PROFILE_VERSION:
            raise ValueError(
                f"unsupported admission profile version {self.profile_version!r}")
        if not all((self.provider, self.requested_model, self.resolved_model,
                    self.model_version, self.endpoint, self.modality,
                    self.capability_manifest_digest,
                    self.program_schema_digest, self.resource_policy_digest,
                    self.financial_query_schema_digest,
                    self.semantic_request_schema_digest,
                    self.semantic_catalog_digest,
                    self.deterministic_builder_digest,
                    self.keyed_corpus_digest, self.adversarial_corpus_digest,
                    self.persona_pack_digest, self.admission_fixture_digest,
                    self.oracle_set_digest,
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
    complete_attempts = (len(attempts) == len(scores)
                         and len(first) == len(scores)
                         and len(repaired) == len(scores))
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
    if not complete_attempts:
        hard.append("incomplete_attempt_evidence")
    admitted = measured and complete_attempts and not hard and not threshold_failures
    return AdmissionReport(measured, admitted, metrics, tuple(hard),
                           tuple(threshold_failures), dict(identity or {}),
                           dict(contract_digests or {}), adversarial_passed,
                           asdict(thresholds),
                           tuple(str(item.case_id) for item in scores))


def admitted_profile(measured_run, *, manifest, policy=None):
    report = _report_from_measured_run(measured_run)
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
        "resource_policy", "financial_query_schema", "semantic_request_schema",
        "semantic_catalog", "deterministic_builders", "keyed_corpus",
        "adversarial_corpus", "persona_pack", "admission_fixture",
        "oracle_set"}
    if not required_contracts <= set(contracts) or any(
            not contracts[name] for name in required_contracts):
        raise ValueError("a model profile needs every measured build contract")
    from .schema import AnswerResourcePolicy
    current = current_contract_digests(
        manifest, policy or AnswerResourcePolicy())
    changed = [name for name, digest in current.items()
               if contracts.get(name) != digest]
    if changed:
        raise ValueError("the measured contracts differ from this build: "
                         + ", ".join(changed))
    return AdmissionProfile(
        provider=identity["provider"], requested_model=identity["requested_model"],
        resolved_model=identity["resolved_model"],
        model_version=identity["resolved_model"], endpoint=identity["endpoint"],
        modality=identity["modality"], locale_family=identity["locale_family"],
        capability_manifest_digest=manifest.digest,
        program_schema_digest=schema_digest,
        resource_policy_digest=contracts["resource_policy"],
        financial_query_schema_digest=contracts["financial_query_schema"],
        semantic_request_schema_digest=contracts["semantic_request_schema"],
        semantic_catalog_digest=contracts["semantic_catalog"],
        deterministic_builder_digest=contracts["deterministic_builders"],
        keyed_corpus_digest=contracts["keyed_corpus"],
        adversarial_corpus_digest=contracts["adversarial_corpus"],
        persona_pack_digest=contracts["persona_pack"],
        admission_fixture_digest=contracts["admission_fixture"],
        oracle_set_digest=contracts["oracle_set"],
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


def _digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def oracle_set_digest(oracles) -> str:
    """Digest canonical ``{case_id: oracle_digest}`` admission evidence."""
    mapping = {
        str(case_id): _digest(oracle)
        for case_id, oracle in (oracles.items() if hasattr(oracles, "items")
                                else oracles)
    }
    return _digest(mapping)


def preflight_live_suite(*, cases, registry_factory=None, policy=None,
                         locale="") -> tuple[AdmissionOracleSet, tuple]:
    """Derive every oracle before a compiler or provider can be constructed."""
    from .admission_fixture import admission_registry
    from .eval import derive_semantic_oracle
    from .schema import AnswerResourcePolicy

    factory = registry_factory or admission_registry
    selected = tuple(cases)
    policy = policy or AnswerResourcePolicy()
    snapshots = []
    manifests = []
    failures = []
    for case in selected:
        try:
            registry = factory()
            manifest = CapabilityManifest.from_registry(registry)
            oracle = derive_semantic_oracle(
                case, registry, manifest, policy, locale=locale)
            snapshots.append((str(case.id), json.dumps(
                oracle, sort_keys=True, separators=(",", ":"))))
            manifests.append(manifest)
        except Exception as error:
            failures.append(AdmissionPreflightFailure(
                str(getattr(case, "id", "")),
                str(getattr(case, "oracle_key", "")),
                type(error).__name__, str(error)))
    if failures:
        raise AdmissionPreflightError(
            failures, case_count=len(selected), ready_count=len(snapshots))
    immutable = tuple(sorted(snapshots))
    digest = oracle_set_digest(
        (case_id, json.loads(snapshot)) for case_id, snapshot in immutable)
    return AdmissionOracleSet(immutable, digest), tuple(manifests)


def current_contract_digests(manifest, policy) -> dict[str, str]:
    from .admission_fixture import (admission_fixture_digest,
                                    admission_registry)
    from .eval import (ADVERSARIAL_CASES, CASES, corpus_digest, load_cases)
    from .intents import SemanticFamilyRegistry
    from ..query.schema import FINANCIAL_QUERY_SCHEMA_VERSION

    persona_version = versions.active(PACKAGE, "persona_pack")
    semantic_schema_version = versions.active(PACKAGE,
                                              "semantic_request_schema")
    families = SemanticFamilyRegistry()
    canonical_oracles, _manifests = preflight_live_suite(
        cases=load_cases(), registry_factory=admission_registry,
        policy=policy, locale="en-US")
    return {
        "program_schema": versions.fingerprint(
            versions.path_of(PACKAGE, ANSWER_PROGRAM_VERSION)),
        "financial_query_schema": versions.fingerprint(
            versions.path_of(PACKAGE, FINANCIAL_QUERY_SCHEMA_VERSION)),
        "semantic_request_schema": versions.fingerprint(
            versions.path_of(PACKAGE, semantic_schema_version)),
        "semantic_catalog": families.catalog_digest,
        "deterministic_builders": (families.admission_digest(manifest)
                                   if manifest is not None else ""),
        "compiler_prompt": promptstore.digest(PROMPTS, COMPILER_VERSION),
        "capability_manifest": manifest.digest if manifest is not None else "",
        "resource_policy": resource_policy_digest(policy),
        "keyed_corpus": corpus_digest(CASES),
        "adversarial_corpus": corpus_digest(ADVERSARIAL_CASES),
        "persona_pack": versions.fingerprint(
            versions.path_of(PACKAGE, persona_version)),
        "admission_fixture": admission_fixture_digest(),
        "oracle_set": canonical_oracles.digest,
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
    contracts = dict(raw.get("contract_digests") or {})
    for field, contract in (("admission_fixture_digest", "admission_fixture"),
                            ("oracle_set_digest", "oracle_set")):
        if (not raw.get(field)
                or str(raw.get(field)) != str(contracts.get(contract) or "")):
            failures.append(f"admission_contract_mismatch:{contract}")
    from .eval import load_cases
    expected_cases = load_cases()
    expected_case_ids = tuple(item.id for item in expected_cases)
    expected_oracle_keys = {item.id: item.oracle_key for item in expected_cases}
    observed_case_ids = tuple(map(str, raw.get("case_ids") or ()))
    if observed_case_ids != expected_case_ids:
        failures.append("incomplete_keyed_corpus")
    if int(metrics.get("cases") or 0) != len(expected_case_ids):
        failures.append("admission_case_count_mismatch")
    attempts = tuple(raw.get("attempt_evidence") or ())
    by_case = {case_id: [] for case_id in expected_case_ids}
    from vivacore.models import AnthropicAdapter, OpenAICompatAdapter
    live_adapters = {
        f"{kind.__module__}.{kind.__qualname__}"
        for kind in (AnthropicAdapter, OpenAICompatAdapter)}
    for item in attempts:
        if not isinstance(item, dict) or str(item.get("case_id") or "") not in by_case:
            failures.append("invalid_attempt_evidence")
            continue
        case_id = str(item["case_id"])
        by_case[case_id].append(int(item.get("attempt") or 0))
        required = {"case_id", "attempt", "oracle_key", "oracle_digest",
                    "request_digest", "response_digest", "resolved_model",
                    "modality", "provider_adapter", "usage_reported"}
        if (not required <= set(item) or not item["request_digest"]
                or not item["response_digest"] or not item["resolved_model"]
                or not item["oracle_key"] or not item["oracle_digest"]
                or not item["provider_adapter"]
                or item["usage_reported"] is not True):
            failures.append("invalid_attempt_evidence")
        if str(item.get("oracle_key") or "") != expected_oracle_keys[case_id]:
            failures.append("oracle_key_mismatch")
        if str(item.get("provider_adapter") or "") not in live_adapters:
            failures.append("provider_double_not_admissible")
    if any(not numbers for numbers in by_case.values()):
        failures.append("incomplete_attempt_evidence")
    if any(sorted(numbers) != list(range(1, len(numbers) + 1))
           for numbers in by_case.values() if numbers):
        failures.append("invalid_attempt_sequence")
    measurements = metrics.get("turn_measurements")
    if (not isinstance(measurements, list)
            or {str(item.get("case_id") or "") for item in measurements
                if isinstance(item, dict)} != set(expected_case_ids)
            or any(int(item.get("attempts") or 0)
                   != len(by_case.get(str(item.get("case_id") or ""), ()))
                   for item in measurements if isinstance(item, dict))):
        failures.append("attempt_measurements_mismatch")
    if raw.get("publication_source") != "live_provider_suite":
        failures.append("non_live_publication_source")
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
        expected_contracts = {
            "capability_manifest": profile.capability_manifest_digest,
            "compiler_prompt": profile.prompt_digest,
            "program_schema": profile.program_schema_digest,
            "resource_policy": profile.resource_policy_digest,
            "financial_query_schema": profile.financial_query_schema_digest,
            "semantic_request_schema": profile.semantic_request_schema_digest,
            "semantic_catalog": profile.semantic_catalog_digest,
            "deterministic_builders": profile.deterministic_builder_digest,
            "keyed_corpus": profile.keyed_corpus_digest,
            "adversarial_corpus": profile.adversarial_corpus_digest,
            "persona_pack": profile.persona_pack_digest,
            "admission_fixture": profile.admission_fixture_digest,
            "oracle_set": profile.oracle_set_digest,
        }
        for name, expected in expected_contracts.items():
            if str(contracts.get(name) or "") != str(expected):
                failures.append(f"admission_contract_mismatch:{name}")
        if thresholds != asdict(profile.thresholds):
            failures.append("admission_thresholds_mismatch")
        if metrics != dict(profile.metrics):
            failures.append("admission_metrics_mismatch")
    return tuple(failures)


def run_live_suite(*, cases=None, registry_factory=None, compiler_factory, thresholds,
                   policy=None, today="", locale="", latency_ceiling_ms=None,
                   evidence_ceiling_bytes=None):
    """Run the internally loaded frozen suite, or a non-publishing partial test.

    Omit ``cases`` and ``registry_factory`` for canonical admission. Supplying
    either full-corpus input is rejected before deterministic or provider work.
    """
    from .admission_fixture import (admission_fixture_digest,
                                    admission_registry)
    from .eval import evaluate_adversarial, load_cases, score
    from .schema import AnswerResourcePolicy
    from .validate import ProgramValidator
    from ..session import Session

    policy = policy or AnswerResourcePolicy()
    canonical_cases = load_cases()
    canonical_ids = tuple(case.id for case in canonical_cases)
    expected_fixture = admission_fixture_digest()
    if cases is None:
        cases = canonical_cases
        if registry_factory is not None:
            raise AdmissionPreflightError((AdmissionPreflightFailure(
                "", "", "AdmissionFixtureMismatch",
                "the full provider suite constructs the canonical admission "
                "fixture internally; do not pass registry_factory"),),
                case_count=len(cases), ready_count=0)
        registry_factory = admission_registry
        observed_fixture = expected_fixture
    else:
        cases = tuple(cases)
        if tuple(case.id for case in cases) == canonical_ids:
            raise AdmissionPreflightError((AdmissionPreflightFailure(
                "", "", "AdmissionCorpusOverride",
                "the full provider suite loads the canonical corpus "
                "internally; omit cases instead of supplying a copy"),),
                case_count=len(cases), ready_count=0)
        registry_factory = registry_factory or admission_registry
        observed_fixture = ""
    oracle_set, manifests = preflight_live_suite(
        cases=cases, registry_factory=registry_factory, policy=policy,
        locale=locale)
    scores, attempts, first_valid, repaired_valid = [], [], [], []
    latencies, evidence_sizes, turn_metrics = [], [], []
    turns = []
    oracles = {}
    for case, manifest in zip(cases, manifests):
        registry = registry_factory()
        oracle = oracle_set.oracle_for(case.id)
        oracles[case.id] = oracle
        session = Session(
            registry, compiler_factory, resource_policy=policy,
            today=(lambda value=today: value), locale=locale,
            prior_turns=case.prior_turns)
        turn = session.ask(case.question)
        turns.append(turn)
        # Reconstruct the scoring facade from the serializable turn record.
        from .intents import SemanticFamilyRegistry
        semantic = (SemanticFamilyRegistry(
                    registry.semantic_entities()).parse(
                    turn.semantic_request,
                    type("Context", (), {"question": case.question,
                                         "prior_turns": case.prior_turns})())
                    if turn.semantic_request else None)
        compilation = type("Compilation", (), {
            "exchanges": turn.exchanges,
            "semantic_outcome": semantic,
            "program": (AnswerProgram.from_dict(turn.program)
                        if turn.program else None)})()
        facade = type("Runtime", (), {"result": turn.result,
                                      "compilation": compilation})()
        scored_case = replace(case, oracle=oracle)
        scores.append(score(scored_case, facade))
        attempts.append(len(turn.exchanges))
        first_valid.append(bool(turn.exchanges and turn.exchanges[0].parse_ok))
        repaired_valid.append(bool(turn.program))
        latency_ms = sum(exchange.latency_s for exchange in turn.exchanges) * 1000
        latencies.append(latency_ms)
        evidence_sizes.append(int((turn.execution or {}).get("evidence_bytes", 0)))
        turn_metrics.append({
            "case_id": case.id,
            "family": str(getattr(case, "expected_family", "")),
            "exact_group": str(getattr(case, "exact_group", "")),
            "exact": bool(getattr(case, "exact", False)),
            "attempts": len(turn.exchanges),
            "input_tokens": sum(item.input_tokens for item in turn.exchanges),
            "output_tokens": sum(item.output_tokens for item in turn.exchanges),
            "cost_usd": sum(item.cost_usd for item in turn.exchanges),
            "latency_ms": latency_ms,
            "semantic_observation": _semantic_observation(
                turn.semantic_request),
            "result_status": str(turn.result.status or ""),
            "result_outcome_tag": str(turn.result.outcome_tag or ""),
        })

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
    current_contracts = current_contract_digests(
        manifests[0] if manifests else None, policy)
    contracts = dict(current_contracts)
    contracts["admission_fixture"] = observed_fixture
    contracts["oracle_set"] = oracle_set.digest
    if len(manifest_digests) != 1:
        contracts["capability_manifest"] = ""
    if observed_fixture != current_contracts["admission_fixture"]:
        identity_failures.append("admission_fixture_differs_from_current_build")
    if oracle_set.digest != current_contracts["oracle_set"]:
        identity_failures.append("oracle_set_differs_from_current_build")
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
    by_family = {}
    for item in turn_metrics:
        family = by_family.setdefault(item["family"], {
            "turns": 0, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "latency_ms": 0.0})
        family["turns"] += 1
        for name in ("input_tokens", "output_tokens", "cost_usd", "latency_ms"):
            family[name] += item[name]
    measured_metrics = dict(report.metrics)
    measured_metrics["turn_measurements"] = turn_metrics
    measured_metrics["family_measurements"] = by_family
    report = AdmissionReport(
        report.measured, report.admitted, measured_metrics,
        report.hard_failures, report.threshold_failures, report.identity,
        report.contract_digests, report.adversarial_passed, report.thresholds,
        report.case_ids, report.attempt_evidence, report.publication_source,
        observed_fixture, oracle_set.digest)
    attempt_evidence = []
    live_provider = True
    for case, turn in zip(cases, turns):
        for number, exchange in enumerate(turn.exchanges, 1):
            live_provider = live_provider and bool(exchange.live_provider)
            attempt_evidence.append({
                "case_id": case.id, "attempt": number,
                "oracle_key": case.oracle_key,
                "oracle_digest": _digest(oracles[case.id]),
                "request_digest": _digest(exchange.request),
                "response_digest": _digest(exchange.response),
                "resolved_model": exchange.resolved_model,
                "modality": exchange.modality,
                "provider_adapter": exchange.provider_adapter,
                "usage_reported": exchange.usage_reported})
    hard = list(report.hard_failures)
    hard.extend(identity_failures)
    if not live_provider:
        hard.append("provider_double_not_admissible")
    if any(not item["usage_reported"] for item in attempt_evidence):
        hard.append("provider_usage_unreported")
    if not adversarial_passed:
        hard.append("adversarial_contract_failure")
    report = AdmissionReport(
        report.measured, report.admitted and not hard, report.metrics,
        tuple(dict.fromkeys(hard)), report.threshold_failures,
        report.identity, report.contract_digests, report.adversarial_passed,
        report.thresholds, report.case_ids, tuple(attempt_evidence),
        "live_provider_suite" if live_provider else "",
        report.admission_fixture_digest, report.oracle_set_digest)
    return _MeasuredAdmissionRun(report, _MEASURED_RUN_SEAL), tuple(scores), tuple(turns)


__all__ = ["ADMISSION_PROFILE_VERSION", "AdmissionOracleSet",
           "AdmissionPreflightError", "AdmissionPreflightFailure",
           "AdmissionProfile", "AdmissionReport", "AdmissionThresholds",
           "admitted_profile", "admission_report_digest",
           "oracle_set_digest", "preflight_live_suite",
           "resource_policy_digest",
           "current_contract_digests",
           "validate_admission_report", "evaluate", "run_live_suite"]
