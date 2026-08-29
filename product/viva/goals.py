"""Draft, persist and confirm exact save-up goal proposals."""

from __future__ import annotations

import datetime
import secrets
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from .ledger.events import (GOAL_PROPOSAL_VERBS, goal_created,
                            goal_funds_released, goal_funds_reserved,
                            goal_proposal_recorded, goal_proposal_resolved,
                            goal_state_changed, goal_terms_changed)
from .ledger.projection.goals import UnknownGoalError, plan_math


@dataclass(frozen=True)
class GoalDraftResult:
    state: str
    reason: str = ""
    verb: str = ""
    draft: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GoalActionResult:
    kind: str
    reason: str = ""
    proposal_id: str = ""
    summary: str = ""
    goal_id: str = ""
    proposal: dict[str, Any] = field(default_factory=dict)


_TERM_FIELDS = {"title", "currency", "target_amount", "target_date",
                "monthly_contribution", "contribution_day"}
_FIELDS = {
    "create": _TERM_FIELDS,
    "change_terms": _TERM_FIELDS | {"goal_id"},
    "reserve": {"goal_id", "account_id", "amount"},
    "release": {"goal_id", "account_id", "amount", "reason"},
    "pause": {"goal_id"},
    "resume": {"goal_id"},
    "set_aside": {"goal_id"},
}


class GoalService:
    """One opened vault's pure drafts and separately persisted proposals."""

    def __init__(self, vault: Any, *, clock: Callable[[], str] | None = None,
                 mint: Callable[[], str] | None = None) -> None:
        self._vault = vault
        self._clock = clock or (lambda: datetime.date.today().isoformat())
        self._mint = mint or (lambda: secrets.token_urlsafe(18))

    def draft(self, payload: dict[str, Any]) -> GoalDraftResult:
        projection = self._vault.ledger.fresh_projection()
        return _draft(projection, payload, self._clock())

    def propose(self, payload: dict[str, Any]) -> GoalActionResult:
        today = self._clock()
        projection = self._vault.ledger.fresh_projection()
        result = _draft(projection, payload, today)
        if result.state != "ready":
            return GoalActionResult(
                "waiting" if result.state == "needs_input" else "refused",
                reason=result.reason, proposal=result.draft)
        proposal = dict(result.draft["payload"])
        if result.verb == "create":
            proposal["goal_id"] = self._mint()
        live_reason = _live_refusal(projection, result.verb, proposal, today)
        if live_reason:
            return GoalActionResult(
                "refused", reason=live_reason, proposal=result.draft)
        stake = _stake(projection, result.verb, proposal, today)
        proposal_id = self._mint()
        summary = f"{result.verb}:{proposal['goal_id']}"
        self._vault.ledger.append(goal_proposal_recorded(
            proposal_id, result.verb, summary, proposal, stake, today))
        return GoalActionResult(
            "proposal", proposal_id=proposal_id, summary=summary,
            goal_id=proposal["goal_id"], proposal=proposal)

    def confirm(self, proposal_id: str) -> GoalActionResult:
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            return GoalActionResult("refused", reason="proposal_id_required")
        today = self._clock()
        decided: list[GoalActionResult] = []

        def decide(projection):
            held = projection.goal_proposal(proposal_id)
            if held is None or held.get("status") != "open":
                decided.append(GoalActionResult(
                    "refused", reason="proposal_not_open"))
                return ()
            verb = str(held.get("verb") or "")
            proposal = dict(held.get("proposal") or {})
            live_reason = _live_refusal(projection, verb, proposal, today)
            live_stake = _stake(projection, verb, proposal, today)
            common = {
                "proposal_id": proposal_id,
                "summary": str(held.get("summary") or ""),
                "goal_id": str(proposal.get("goal_id") or ""),
                "proposal": proposal,
            }
            if live_reason or live_stake != held.get("stake"):
                reason = live_reason or "proposal_basis_changed"
                decided.append(GoalActionResult(
                    "stale", reason=reason, **common))
                return (goal_proposal_resolved(
                    proposal_id, "stale", today, reason=reason),)
            decided.append(GoalActionResult("completed", **common))
            return (self._event(verb, proposal, proposal_id, today),
                    goal_proposal_resolved(proposal_id, "completed", today))

        self._vault.ledger.append_atomically(decide)
        return decided[0]

    def decline(self, proposal_id: str) -> GoalActionResult:
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            return GoalActionResult("refused", reason="proposal_id_required")
        today = self._clock()
        decided: list[GoalActionResult] = []

        def decide(projection):
            held = projection.goal_proposal(proposal_id)
            if held is None or held.get("status") != "open":
                decided.append(GoalActionResult(
                    "refused", reason="proposal_not_open"))
                return ()
            proposal = dict(held.get("proposal") or {})
            decided.append(GoalActionResult(
                "set_aside", reason="declined", proposal_id=proposal_id,
                summary=str(held.get("summary") or ""),
                goal_id=str(proposal.get("goal_id") or ""), proposal=proposal))
            return (goal_proposal_resolved(
                proposal_id, "set_aside", today, reason="declined"),)

        self._vault.ledger.append_atomically(decide)
        return decided[0]

    def _event(self, verb: str, proposal: dict[str, Any], proposal_id: str,
               today: str):
        goal_id = proposal["goal_id"]
        if verb == "create":
            terms = {key: value for key, value in proposal.items()
                     if key in _TERM_FIELDS}
            return goal_created(
                goal_id, terms["title"], terms["currency"],
                terms["target_amount"], today,
                target_date=terms.get("target_date", ""),
                monthly_contribution=terms.get("monthly_contribution") or None,
                contribution_day=terms.get("contribution_day"),
                proposal_id=proposal_id)
        elif verb == "change_terms":
            return goal_terms_changed(
                goal_id, proposal["title"], proposal["currency"],
                proposal["target_amount"], today,
                target_date=proposal.get("target_date", ""),
                monthly_contribution=proposal.get("monthly_contribution") or None,
                contribution_day=proposal.get("contribution_day"),
                proposal_id=proposal_id)
        elif verb == "reserve":
            return goal_funds_reserved(
                goal_id, proposal["account_id"], proposal["amount"], today,
                proposal_id=proposal_id)
        elif verb == "release":
            return goal_funds_released(
                goal_id, proposal["account_id"], proposal["amount"],
                proposal["reason"], today, proposal_id=proposal_id)
        else:
            state = {"pause": "paused", "resume": "active",
                     "set_aside": "set_aside"}[verb]
            return goal_state_changed(
                goal_id, state, today, proposal_id=proposal_id)


def _draft(projection, payload: dict[str, Any], today: str) -> GoalDraftResult:
    if not isinstance(payload, dict):
        return GoalDraftResult("refused", "payload_not_object")
    verb = payload.get("verb")
    if verb not in GOAL_PROPOSAL_VERBS:
        return GoalDraftResult("refused", "unknown_goal_verb")
    supplied = set(payload) - {"verb"}
    unexpected = supplied - _FIELDS[verb]
    if unexpected:
        return GoalDraftResult("refused", "unexpected_fields")
    required = {
        "create": ("title", "currency", "target_amount"),
        "change_terms": ("goal_id", "title", "currency", "target_amount"),
        "reserve": ("goal_id", "account_id", "amount"),
        "release": ("goal_id", "account_id", "amount", "reason"),
        "pause": ("goal_id",), "resume": ("goal_id",),
        "set_aside": ("goal_id",),
    }[verb]
    if any(payload.get(key) in (None, "") for key in required):
        return GoalDraftResult("needs_input", "goal_action_fields_required")
    if verb in ("create", "change_terms"):
        missing = [key for key in ("title", "currency", "target_amount")
                   if payload.get(key) in (None, "")]
        if missing:
            return GoalDraftResult("needs_input", "goal_terms_required")
    try:
        normalized = _normalized(verb, payload)
    except (TypeError, ValueError) as exc:
        return GoalDraftResult("refused", _reason(exc))
    if verb in ("create", "change_terms"):
        if (normalized.get("target_date")
                and not normalized.get("monthly_contribution")
                and normalized.get("contribution_day") is None):
            return GoalDraftResult("needs_input", "contribution_day_required")
        reservations = {}
        state = "active"
        if verb == "change_terms":
            try:
                current = projection.goal(normalized["goal_id"], today)
            except UnknownGoalError:
                return GoalDraftResult("refused", "unknown_goal")
            reservations = dict(current.reservations)
            state = current.state
        math = plan_math({**normalized, "state": state,
                          "reservations": reservations}, today)
        calculated = {
            "reserved": str(math["reserved"]),
            "remaining": str(math["remaining"]),
            "required_monthly": (str(math["required"])
                                 if math["required"] is not None else ""),
            "projected_completion_date": math["projected"],
            "deviation": (str(math["deviation"])
                          if math["deviation"] is not None else ""),
            "status": math["status"],
            "next_contribution_date": math["next"],
        }
    else:
        if not normalized.get("goal_id"):
            return GoalDraftResult("needs_input", "goal_id_required")
        try:
            projection.goal(normalized["goal_id"], today)
        except UnknownGoalError:
            return GoalDraftResult("refused", "unknown_goal")
        calculated = {}
    return GoalDraftResult(
        "ready", verb=verb,
        draft={"verb": verb, "payload": normalized,
               "calculated": calculated})


def _normalized(verb: str, payload: dict[str, Any]) -> dict[str, Any]:
    if verb in ("create", "change_terms"):
        goal_id = str(payload.get("goal_id") or "draft")
        event = goal_created(
            goal_id, str(payload.get("title") or ""),
            str(payload.get("currency") or ""),
            payload.get("target_amount") or "0", "2000-01-01",
            target_date=str(payload.get("target_date") or ""),
            monthly_contribution=payload.get("monthly_contribution") or None,
            contribution_day=payload.get("contribution_day"))
        terms = {key: event.body.get(key) for key in _TERM_FIELDS}
        if verb == "change_terms":
            terms["goal_id"] = str(payload.get("goal_id") or "").strip()
        return terms
    goal_id = str(payload.get("goal_id") or "").strip()
    if verb in ("reserve", "release"):
        account_id = str(payload.get("account_id") or "").strip()
        raw = payload.get("amount")
        if isinstance(raw, (float, bool)):
            raise TypeError("amount_not_exact")
        amount = Decimal(raw)
        if not amount.is_finite() or amount <= 0:
            raise ValueError("amount_not_positive")
        out = {"goal_id": goal_id, "account_id": account_id,
               "amount": str(amount)}
        if verb == "release":
            reason = str(payload.get("reason") or "")
            if reason not in ("reassigned", "used_elsewhere"):
                raise ValueError("release_reason_invalid")
            out["reason"] = reason
        return out
    return {"goal_id": goal_id}


def _reason(exc: Exception) -> str:
    text = str(exc)
    known = ("amount_not_exact", "amount_not_positive",
             "release_reason_invalid")
    return text if text in known else "invalid_goal_terms"


def _goal_stake(row) -> dict[str, Any]:
    return {
        "goal_id": row.goal_id, "title": row.title, "state": row.state,
        "currency": row.currency, "target_amount": str(row.target_amount),
        "target_date": row.target_date,
        "monthly_contribution": (str(row.monthly_contribution)
                                 if row.monthly_contribution is not None else ""),
        "contribution_day": row.contribution_day,
        "reservations": [[account, str(amount)]
                         for account, amount in row.reservations],
        "event_ids": list(row.event_ids),
    }


def _stake(projection, verb: str, proposal: dict[str, Any], today: str) -> dict:
    goal_id = proposal["goal_id"]
    if verb == "create":
        try:
            projection.goal(goal_id, today)
            absent = False
        except UnknownGoalError:
            absent = True
        return {"goal_id": goal_id, "absent": absent}
    row = projection.goal(goal_id, today)
    stake = {"goal": _goal_stake(row)}
    if verb in ("reserve", "release"):
        account_id = proposal["account_id"]
        stake["account"] = projection.goal_account_stake(
            account_id, row.currency)
    return stake


def _live_refusal(projection, verb: str, proposal: dict[str, Any],
                  today: str) -> str:
    goal_id = proposal["goal_id"]
    if verb == "create":
        try:
            projection.goal(goal_id, today)
            return "goal_id_exists"
        except UnknownGoalError:
            return ""
    try:
        row = projection.goal(goal_id, today)
    except UnknownGoalError:
        return "unknown_goal"
    if row.state == "set_aside":
        return "goal_set_aside"
    if verb == "change_terms":
        if row.reserved and proposal["currency"] != row.currency:
            return "reserved_goal_currency_fixed"
    elif verb == "reserve":
        account = next((item for item in row.available_accounts
                        if item.account_id == proposal["account_id"]), None)
        if account is None:
            return "account_not_eligible"
        if Decimal(proposal["amount"]) > account.available:
            return "reservation_exceeds_available"
    elif verb == "release":
        reserved = dict(row.reservations).get(
            proposal["account_id"], Decimal("0"))
        if Decimal(proposal["amount"]) > reserved:
            return "release_exceeds_reserved"
    elif verb == "pause" and row.state != "active":
        return "goal_not_active"
    elif verb == "resume" and row.state != "paused":
        return "goal_not_paused"
    elif verb == "set_aside" and row.reserved:
        return "goal_still_reserved"
    return ""


__all__ = ["GoalActionResult", "GoalDraftResult", "GoalService"]
