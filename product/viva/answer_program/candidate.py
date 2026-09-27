"""Check deterministic admission or evaluate and publish a candidate model."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from vivacore.errors import ConfigError
from vivacore.models import AdapterError

from .admission import (AdmissionPreflightError, MINIMUM_ADMISSION_THRESHOLDS,
                        admitted_profile, preflight_live_suite, run_live_suite)
from .admission_fixture import ADMISSION_TODAY
from .eval import load_cases
from .release import write_release_bundle
from ..env import locale_from_env
from ..speak import compiler_factory, resource_policy_from_env, speak_spec


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="evaluate the configured provider using synthetic questions")
    parser.add_argument("--output", type=Path,
                        help="write the approved runtime bundle here on success")
    parser.add_argument("--report", type=Path,
                        help="write measured diagnostics here (defaults beside output)")
    args = parser.parse_args(argv)
    if args.live and args.output is None:
        parser.error("--live requires --output")
    if not args.live and (args.output is not None or args.report is not None):
        parser.error("--output and --report require --live")
    report_path = None
    if args.live:
        report_path = args.report or args.output.with_name(
            args.output.name + ".report.json")
        if (report_path.resolve() == args.output.resolve()
                or (report_path.exists() and args.output.exists()
                    and report_path.samefile(args.output))):
            parser.error("--report and --output must be different files")
        for path in (args.output, report_path):
            if not path.parent.is_dir() or (path.exists() and not path.is_file()):
                parser.error("output and report must name files in existing directories")
    try:
        locale = locale_from_env()
        policy = resource_policy_from_env()
        cases = load_cases()
        oracles, manifests = preflight_live_suite(
            cases=cases, policy=policy, locale=locale)
        if not args.live:
            print(json.dumps({"status": "preflight_passed", "cases": len(cases),
                              "oracle_set_digest": oracles.digest,
                              "model_evaluated": False}))
            return 0
        spec = speak_spec()
        if spec is None:
            raise ValueError("candidate model is not configured")
        factory = compiler_factory(spec, purpose="admission", locale=locale)
        measured, _scores, _turns = run_live_suite(
            compiler_factory=factory, thresholds=MINIMUM_ADMISSION_THRESHOLDS,
            policy=policy, today=ADMISSION_TODAY, locale=locale)
        report = measured.report
        report_path.write_text(json.dumps(asdict(report), indent=2, sort_keys=True)
                               + "\n", encoding="utf-8")
        if not report.admitted:
            print(json.dumps({"status": "not_admitted",
                              "hard_failures": report.hard_failures,
                              "threshold_failures": report.threshold_failures,
                              "report": str(report_path)}))
            return 1
        manifest = manifests[0]
        profile = admitted_profile(measured, manifest=manifest, policy=policy)
        write_release_bundle(args.output, profile=profile, manifest=manifest,
                             measured_run=measured, policy=policy)
        print(json.dumps({"status": "admitted", "bundle": str(args.output),
                          "report": str(report_path)}))
        return 0
    except AdmissionPreflightError as error:
        print(json.dumps(error.to_dict()))
        return 1
    except (OSError, ValueError, ConfigError, AdapterError) as error:
        # Provider errors can contain credentials or raw responses.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
