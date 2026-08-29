"""Bridge adapter for pure goal drafts and exact persisted proposals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..goals import GoalActionResult, GoalService
from ..persona import moment
from ..surface.models import ActionOutcome
from .handlers import BridgeRequestError


_MESSAGES = {
    "proposal": "plans_proposal_held",
    "completed": "plans_action_completed",
    "stale": "plans_action_stale",
    "set_aside": "plans_action_set_aside",
    "refused": "plans_action_refused",
    "waiting": "plans_needs_input",
}


class PlanActions:
    def __init__(self, vault) -> None:
        self._service = GoalService(vault)

    def draft(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = _goal_request(payload)
        result = self._service.draft(request)
        kind = {"ready": "completed", "needs_input": "waiting",
                "refused": "refused"}[result.state]
        message = moment(
            "plans_draft_ready" if result.state == "ready"
            else "plans_needs_input" if result.state == "needs_input"
            else "plans_action_refused")
        return ActionOutcome(
            kind, message,
            state={"draft_state": result.state, "verb": result.verb,
                   "draft": result.draft},
            reason=result.reason or None).as_dict()

    def propose(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return _outcome(self._service.propose(_goal_request(payload)))

    def confirm(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return _outcome(self._service.confirm(_proposal_id(payload)))

    def decline(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return _outcome(self._service.decline(_proposal_id(payload)))


def _goal_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise BridgeRequestError("a plan action payload must be an object")
    allowed = {"verb", "title", "currency", "target_amount", "target_date",
               "monthly_contribution", "contribution_day", "goal_id",
               "account_id", "amount", "reason"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            "a plan action does not accept fields: "
            + ", ".join(sorted(unexpected)))
    return dict(payload)


def _proposal_id(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise BridgeRequestError("a proposal action payload must be an object")
    request = dict(payload)
    allowed = {"proposal_id"}
    if set(request) != allowed:
        raise BridgeRequestError("a proposal action requires only proposal_id")
    proposal_id = request["proposal_id"]
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        raise BridgeRequestError("proposal_id must be a non-empty string")
    return proposal_id


def _outcome(result: GoalActionResult) -> dict[str, Any]:
    return ActionOutcome(
        result.kind, moment(_MESSAGES[result.kind]),
        state={"proposal_id": result.proposal_id,
               "goal_id": result.goal_id, "summary": result.summary,
               "proposal": result.proposal},
        reason=result.reason or None).as_dict()


__all__ = ["PlanActions"]
