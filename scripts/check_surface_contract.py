#!/usr/bin/env python3
"""Generate and check the reviewed ``viva.surface`` contract artifact."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "product" / "viva" / "surface" / "fixtures" / "surface-v1.json"


def _surface_import_path(root: Path) -> None:
    product = root / "product"
    if str(product) not in sys.path:
        sys.path.insert(0, str(product))


def _goals_fixture_payload(state: str) -> dict[str, Any]:
    """A renderable read/action pair, built through the real contract."""
    from viva.ledger import (LedgerProjection, Provenance, account_opened,
                             closing_balance_observed, document_captured,
                             goal_created, goal_funds_released,
                             goal_funds_reserved, goal_proposal_recorded)
    from viva.persona import moment
    from viva.surface.plans import plans

    today = "2026-08-29"
    base = [
        account_opened("checking", "depository", "Checking", "USD",
                       "2026-01-01"),
        document_captured(
            "fixture-statement", "checking.pdf", 128, "bank_statement", 1.0,
            today, Provenance("fixture-statement")),
        closing_balance_observed(
            "checking", "1000", today,
            Provenance("fixture-statement", 1, "closing")),
        goal_created(
            "fixture-goal", "Journey", "USD", "600", "2026-08-01",
            target_date="2026-11-15", monthly_contribution="150",
            contribution_day=15),
        goal_funds_reserved(
            "fixture-goal", "checking", "200", "2026-08-02"),
    ]
    events = [] if state in ("absent", "needs_input", "refused") else list(base)
    if state == "partial":
        events.append(goal_funds_released(
            "fixture-goal", "checking", "999", "used_elsewhere", today))
    if state == "open":
        events.append(goal_proposal_recorded(
            "fixture-proposal", "reserve", "reserve:fixture-goal",
            {"goal_id": "fixture-goal", "account_id": "checking",
             "amount": "50"},
            {"goal_id": "fixture-goal", "account_id": "checking",
             "balance": "1000", "reserved": "200", "available": "800"},
            today))
    surface = plans(LedgerProjection(events), "en-US", today)
    # Normalize opaque event identities in reusable fixtures.
    for goal in surface["goals"]:
        goal["event_ids"] = []
    action = None
    if state == "needs_input":
        action = {"kind": "waiting", "message": moment("plans_needs_input"),
                  "reason": "contribution_day_required",
                  "state": {"draft_state": "needs_input", "draft": {}}}
    elif state == "refused":
        action = {"kind": "refused", "message": moment("plans_action_refused"),
                  "reason": "reservation_exceeds_available", "state": None}
    elif state == "open":
        action = {"kind": "proposal", "message": moment("plans_proposal_held"),
                  "reason": None,
                  "state": {"proposal_id": "fixture-proposal",
                            "goal_id": "fixture-goal"}}
    elif state == "completed":
        action = {"kind": "completed", "message": moment("plans_action_completed"),
                  "reason": None,
                  "state": {"proposal_id": "fixture-proposal",
                            "goal_id": "fixture-goal"}}
    elif state == "stale":
        action = {"kind": "stale", "message": moment("plans_action_stale"),
                  "reason": "proposal_basis_changed",
                  "state": {"proposal_id": "fixture-proposal",
                            "goal_id": "fixture-goal"}}
    return {"surface": surface, "action": action}


def build_artifact(root: Path = ROOT) -> dict[str, Any]:
    """Build a JSON-safe, stable projection of the Python surface contract."""
    _surface_import_path(root)
    from viva.surface import CURRENT_PROTOCOL, capabilities
    from viva.surface.models import (ActionOutcome,
                                     CurrentPeriodCompletenessView,
                                     CurrentPeriodExclusionView,
                                     CurrentPeriodSliceView,
                                     CurrentPeriodStepView, FindingView,
                                     FigureView, GoalAccountView,
                                     GoalHistoryView, GoalPlanView,
                                     GoalProposalView, ObligationView, PanelState,
                                     ProofEmphasis, ProofPresentation,
                                     ProofReason)

    registry = []
    fixtures = []
    for capability in sorted(capabilities(), key=lambda item: item.id):
        registry.append({
            "id": capability.id,
            "owner": capability.owner,
            "maturity": capability.maturity.value,
            "disposition": capability.disposition.value,
            "destination": capability.destination.value,
            "availability": capability.availability,
            "contract": capability.contract,
            "actions": list(capability.actions),
            "trust_effect": [effect.value for effect in capability.trust_effect],
            "reason": capability.reason,
            "entrypoint": capability.entrypoint,
            "fixture_ids": list(capability.fixture_ids),
        })
        for fixture_id in capability.fixture_ids:
            state = fixture_id.rsplit(".", 1)[-1]
            payload = ({"capability_id": capability.id,
                        "contract": capability.contract,
                        **_goals_fixture_payload(state)}
                       if capability.id == "plans.goals" else
                       {"capability_id": capability.id,
                        "contract": capability.contract})
            fixtures.append({
                "id": fixture_id,
                "capability_id": capability.id,
                "contract": capability.contract,
                "state": state,
                "payload": payload,
            })

    def dataclass_fields(model: type[Any]) -> list[str]:
        return [field.name for field in fields(model)]

    return {
        "artifact": "orionviva.surface-v1",
        "protocol": CURRENT_PROTOCOL.wire(),
        "registry": registry,
        "fixtures": fixtures,
        "models": {
            "FigureView": dataclass_fields(FigureView),
            "ObligationView": dataclass_fields(ObligationView),
            "FindingView": dataclass_fields(FindingView),
            "CurrentPeriodCompletenessView": dataclass_fields(CurrentPeriodCompletenessView),
            "CurrentPeriodExclusionView": dataclass_fields(CurrentPeriodExclusionView),
            "CurrentPeriodSliceView": dataclass_fields(CurrentPeriodSliceView),
            "CurrentPeriodStepView": dataclass_fields(CurrentPeriodStepView),
            "GoalAccountView": dataclass_fields(GoalAccountView),
            "GoalHistoryView": dataclass_fields(GoalHistoryView),
            "GoalPlanView": dataclass_fields(GoalPlanView),
            "GoalProposalView": dataclass_fields(GoalProposalView),
            "ProofPresentation": dataclass_fields(ProofPresentation),
            "ProofEmphasis": [emphasis.value for emphasis in ProofEmphasis],
            "ProofReason": [reason.value for reason in ProofReason],
            "PanelState": [state.value for state in PanelState],
            "ActionOutcome": dataclass_fields(ActionOutcome),
        },
    }


def encoded_artifact(root: Path = ROOT) -> bytes:
    return (json.dumps(build_artifact(root), indent=2, sort_keys=True) + "\n").encode("utf-8")


def check_artifact(path: Path = DEFAULT_ARTIFACT, root: Path = ROOT) -> None:
    expected = encoded_artifact(root)
    if not path.exists():
        raise SystemExit(f"surface contract fixture is missing: {path}")
    actual = path.read_bytes()
    if actual != expected:
        raise SystemExit(
            "surface contract drift detected; run "
            f"{Path(__file__).name} --write to review the generated update"
        )
    parsed = json.loads(actual)
    if parsed != build_artifact(root):
        raise SystemExit("surface contract fixture is not valid JSON for the current registry")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail when the artifact is stale")
    mode.add_argument("--write", action="store_true", help="write the deterministic artifact")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--artifact", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    artifact = (args.artifact or (root / "product/viva/surface/fixtures/surface-v1.json")).resolve()
    if args.write:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(encoded_artifact(root))
        print(f"wrote {artifact}")
    else:
        check_artifact(artifact, root)
        print(f"surface contract is current: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
