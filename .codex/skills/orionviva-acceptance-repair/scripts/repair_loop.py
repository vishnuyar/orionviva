#!/usr/bin/env python3
"""Deterministic runner and report gate for OrionViva acceptance repair."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCENARIO_ID = re.compile(r"^(?:VAULT|IMPORT|PICTURE|TRUST|GUIDE|ACCESS|RESILIENCE)-\d{3}$")


class GateError(RuntimeError):
    """A deterministic precondition or report invariant failed."""


def git(product: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=product, text=True, capture_output=True, check=False)
    if result.returncode:
        raise GateError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def roots(product_arg: str | None, acceptance_arg: str | None) -> tuple[Path, Path]:
    default_product = Path(__file__).resolve().parents[4]
    product = Path(product_arg or os.environ.get("ORIONVIVA_ROOT", default_product)).resolve()
    acceptance = Path(acceptance_arg or os.environ.get(
        "ORIONVIVA_ACCEPTANCE_ROOT", product.parent / "orionviva-acceptance"
    )).resolve()
    for root, required in (
        (product, (".git", "WORKFLOW.md", "acceptance/scenarios")),
        (acceptance, (".git", "package.json", "bin/evaluator.mjs", "packs/orionviva/product.json")),
    ):
        missing = [name for name in required if not (root / name).exists()]
        if missing:
            raise GateError(f"{root} is missing: {', '.join(missing)}")
    return product, acceptance


def catalog_ids(product: Path) -> list[str]:
    found: set[str] = set()
    for path in (product / "acceptance/scenarios").glob("*.md"):
        for token in re.findall(r"[A-Z]+-\d{3}", path.read_text(encoding="utf-8")):
            if SCENARIO_ID.fullmatch(token):
                found.add(token)
    if not found:
        raise GateError("the maintained acceptance catalog contains no scenario IDs")
    return sorted(found)


def evaluator_case_ids(acceptance: Path) -> list[str]:
    found: set[str] = set()
    for folder in ("scenarios", "artifact-journeys", "workflows"):
        for path in (acceptance / "packs/orionviva" / folder).glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            value = data.get("id")
            if isinstance(value, str) and value.strip():
                found.add(value.strip())
    if not found:
        raise GateError("the OrionViva evaluator pack declares no executable cases")
    return sorted(found)


def preflight(product: Path, acceptance: Path) -> dict[str, Any]:
    catalog = catalog_ids(product)
    evaluator = evaluator_case_ids(acceptance)
    untracked = git(product, "ls-files", "--others", "--exclude-standard").splitlines()
    allowed_untracked = re.compile(r"^product/viva/prompts/[a-z0-9][a-z0-9._-]*\.txt$")
    refused_untracked = sorted(path for path in untracked if not allowed_untracked.fullmatch(path))
    return {
        "status": "ready" if not refused_untracked else "blocked",
        "product_root": str(product),
        "acceptance_root": str(acceptance),
        "product_revision": git(product, "rev-parse", "HEAD"),
        "branch": git(product, "branch", "--show-current"),
        "working_tree_clean": not bool(git(product, "status", "--porcelain")),
        "working_tree_evaluator_eligible": not refused_untracked,
        "working_tree_refused_untracked": refused_untracked,
        "maintained_catalog_scenarios": len(catalog),
        "evaluator_declared_cases": len(evaluator),
        "catalog_mapping_verified": False,
        "notice": (
            "The maintained catalog and evaluator pack use different case declarations; "
            "do not claim all catalog scenarios are automated without a reviewed mapping."
        ),
    }


def report_revisions(report: dict[str, Any]) -> list[str]:
    revisions: set[str] = set()
    top = report.get("product_revision")
    if isinstance(top, str) and top:
        revisions.add(top)
    for lane in report.get("lanes") or []:
        value = lane.get("product_revision") if isinstance(lane, dict) else None
        if isinstance(value, str) and value:
            revisions.add(value)
    return sorted(revisions)


def classify_report(report: dict[str, Any], expected_revision: str) -> dict[str, Any]:
    required = ("product", "status", "decision", "complete", "coverage")
    reasons = [f"missing report fields: {', '.join(field for field in required if field not in report)}"] \
        if any(field not in report for field in required) else []
    if report.get("product") != "orionviva":
        reasons.append("report product is not orionviva")

    revisions = report_revisions(report)
    if not revisions:
        reasons.append("report contains no product revision evidence")
    elif any(not value.startswith(expected_revision) for value in revisions):
        reasons.append("report revision evidence does not match the requested product HEAD")

    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        reasons.append("report has no complete-product coverage object")
        coverage = {}
    cases = coverage.get("cases")
    if not isinstance(cases, list) or not cases:
        reasons.append("coverage contains no cases")
        cases = []

    if reasons:
        classification = "invalid_report"
    else:
        statuses = {str(case.get("status")) for case in cases if isinstance(case, dict)}
        has_gap = bool(
            statuses & {"blocked", "incomplete", "not_verified"}
            or coverage.get("missing_dimensions")
            or coverage.get("missing_capabilities")
            or coverage.get("missing_cases")
            or coverage.get("executed_cases") != coverage.get("required_cases")
        )
        has_failure = "fail" in statuses or bool(report.get("failures"))
        is_pass = (
            report.get("status") == "pass" and report.get("decision") == "ready"
            and report.get("complete") is True and not has_gap and not has_failure
            and statuses == {"pass"}
        )
        if is_pass:
            classification = "pass"
        elif has_failure:
            classification = "product_failure"
        elif has_gap:
            classification = "acceptance_gap"
        else:
            classification = "invalid_report"
            reasons.append("report outcome is internally inconsistent")

    return {
        "classification": classification,
        "status": report.get("status"),
        "decision": report.get("decision"),
        "complete": report.get("complete"),
        "product_revisions": revisions,
        "required_cases": coverage.get("required_cases"),
        "executed_cases": coverage.get("executed_cases"),
        "failed_case_ids": [case.get("id") for case in cases if isinstance(case, dict) and case.get("status") == "fail"],
        "gap_case_ids": [case.get("id") for case in cases if isinstance(case, dict) and case.get("status") in {"blocked", "incomplete", "not_verified"}],
        "reasons": reasons,
    }


def locate_report(output: Path) -> Path:
    direct = output / "trace.report.json"
    if direct.is_file():
        return direct
    candidates = sorted(output.glob("*.report.json"))
    if len(candidates) != 1:
        raise GateError(f"expected one top-level report in {output}; found {len(candidates)}")
    return candidates[0]


def run_evaluator(product: Path, acceptance: Path, mode: str, output_arg: str | None) -> dict[str, Any]:
    head = git(product, "rev-parse", "HEAD")
    if mode == "committed" and git(product, "status", "--porcelain"):
        raise GateError("committed mode requires a clean product working tree")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    output = Path(output_arg).resolve() if output_arg else (
        product / "runs" / "acceptance-repair" / f"{stamp}-{mode}-{head[:12]}"
    )
    output.mkdir(parents=True, exist_ok=False)
    command = [
        "node", "bin/evaluator.mjs", "run", "packs/orionviva",
        "--runner", "packs/orionviva/adapter/complete-runner.mjs", "--output", str(output),
    ]
    if mode == "working-tree":
        command.append("--working-tree")
    environment = os.environ.copy()
    environment["ORIONVIVA_ROOT"] = str(product)
    completed = subprocess.run(command, cwd=acceptance, env=environment, check=False)

    report_path = locate_report(output)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = classify_report(report, head)
    result.update({
        "mode": mode, "evaluator_exit_code": completed.returncode, "product_head": head,
        "output_directory": str(output), "report_path": str(report_path),
    })
    metadata = output / "repair-loop-result.json"
    metadata.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    result["result_path"] = str(metadata)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--product-root")
    result.add_argument("--acceptance-root")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    run = commands.add_parser("run")
    run.add_argument("--mode", choices=("working-tree", "committed"), required=True)
    run.add_argument("--output")
    check = commands.add_parser("check-report")
    check.add_argument("report")
    check.add_argument("--expect-revision", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        product, acceptance = roots(args.product_root, args.acceptance_root)
        if args.command == "preflight":
            result = preflight(product, acceptance)
        elif args.command == "run":
            result = run_evaluator(product, acceptance, args.mode, args.output)
        else:
            report_path = Path(args.report).resolve()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            result = {"report_path": str(report_path), **classify_report(report, args.expect_revision)}
        print(json.dumps(result, indent=2))
        if args.command in {"run", "check-report"} and result["classification"] != "pass":
            return 1
        return 0
    except (GateError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"classification": "invalid_report", "error": str(error)}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
