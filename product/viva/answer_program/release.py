"""Mechanical release gates for the single semantic-to-AnswerProgram path."""

from __future__ import annotations

from dataclasses import dataclass
import json
import pathlib

from vivacore import promptstore, versions

from ..tools.registry import PACKAGE, PROMPTS
from .admission import (_report_from_measured_run, admission_report_digest,
                        current_contract_digests, validate_admission_report)
from .schema import ANSWER_PROGRAM_VERSION, AnswerResourcePolicy

_BANNED_PRODUCTION_NAMES = (
    "NativePlanner", "TextPlanner", "DEFAULT_MAX_CALLS",
    "SPEAK_CLOSING_VERSION", "queued_calls", "SHAPE_TOOL", "FINAL_TOOL",
    "_committable(", "_noted(", "_shape_taken(",
    "compile_answer_program", "COMPILE_TOOL")


@dataclass(frozen=True)
class ReleaseCheck:
    passed: bool
    failures: tuple[str, ...]


def check_single_path(package_root=None):
    if package_root is None:
        project = pathlib.Path(__file__).resolve().parents[3]
        roots = (project / "product" / "viva", project / "desktop" / "src")
    else:
        roots = (pathlib.Path(package_root),)
    failures = []
    for root in roots:
        if (root / "planners.py").exists():
            failures.append("procedural_planner_packaged")
        for path in root.rglob("*"):
            if (not path.is_file()
                    or path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}
                    or path.resolve() == pathlib.Path(__file__).resolve()):
                continue
            text = path.read_text(encoding="utf-8")
            for name in _BANNED_PRODUCTION_NAMES:
                if name in text:
                    failures.append(
                        f"banned_runtime_symbol:{name}:{path.relative_to(root)}")
    manifest = versions.manifest(PACKAGE)
    for family in ("answer_program", "answer_program_retry"):
        if family in manifest.get("in_force", {}):
            failures.append(f"superseded_prompt_family_in_force:{family}")
    return ReleaseCheck(not failures, tuple(sorted(set(failures))))


def check_profile(profile, manifest, report=None, policy=None):
    failures = []
    if profile.capability_manifest_digest != manifest.digest:
        failures.append("capability_manifest_digest_mismatch")
    if promptstore.digest(PROMPTS, profile.prompt_version) != profile.prompt_digest:
        failures.append("compiler_prompt_digest_mismatch")
    if profile.capability_manifest_version != manifest.manifest_version:
        failures.append("capability_manifest_version_mismatch")
    if profile.program_schema_version != ANSWER_PROGRAM_VERSION:
        failures.append("program_schema_version_mismatch")
    schema_digest = versions.fingerprint(
        versions.path_of(PACKAGE, ANSWER_PROGRAM_VERSION))
    if profile.program_schema_digest != schema_digest:
        failures.append("program_schema_digest_mismatch")
    current = current_contract_digests(
        manifest, policy or AnswerResourcePolicy())
    profile_contracts = {
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
    }
    for name, expected in current.items():
        if profile_contracts.get(name) != expected:
            failures.append(f"{name}_digest_mismatch")
    if report is None:
        failures.append("admission_report_missing")
    elif profile.admission_report_digest != admission_report_digest(report):
        failures.append("admission_report_digest_mismatch")
    else:
        failures.extend(validate_admission_report(report, profile))
    return ReleaseCheck(not failures, tuple(failures))


def write_release_bundle(path, *, profile, manifest, measured_run):
    report = _report_from_measured_run(measured_run)
    if not report.admitted:
        raise ValueError("release bundle needs an admitted measured report")
    checked = check_profile(profile, manifest, report)
    if not checked.passed:
        raise ValueError("release profile does not match this build: "
                         + ", ".join(checked.failures))
    from dataclasses import asdict
    payload = {"profile": profile.to_dict(),
               "admission_report": asdict(report),
               "capability_manifest": manifest.to_dict()}
    target = pathlib.Path(path)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    return target


__all__ = ["ReleaseCheck", "check_profile", "check_single_path",
           "write_release_bundle"]
