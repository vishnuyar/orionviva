"""Closed model binding for conversational save-up draft requests.

The model may copy meaning from one person's sentence into the plan draft's
closed fields.  It neither calculates nor writes: the ordinary ``GoalService``
validates the bound payload and owns every amount and date derived from it.
Every call is captured verbatim as a ``ReadRecorded`` event before the result
is returned.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import datetime
import json
import secrets
from typing import Any

from vivacore import promptstore, versions

from .ledger.events import read_recorded
from .tools.registry import PACKAGE, PROMPTS


VERSION = versions.active(PACKAGE, "goal_binding")
_FIELDS = ("title", "target_amount", "currency", "target_date",
           "monthly_contribution", "contribution_day")
_KEYS = frozenset(("intent", *_FIELDS))


@dataclass(frozen=True)
class GoalBinding:
    """One checked binding decision, before deterministic draft calculation."""

    intent: str
    payload: dict[str, Any]
    reason: str = ""


class GoalBindingPlanner:
    """One bounded model call whose only usable output is ``GoalBinding``."""

    def __init__(self, vault, spec, adapter=None, today=None) -> None:
        self._vault = vault
        self._spec = spec
        self._today = today or (lambda: datetime.date.today().isoformat())
        if adapter is None:
            from vivacore.models import adapter_for
            adapter = adapter_for(replace(spec, max_continuations=0))
        self._adapter = adapter

    def bind(self, question: str) -> GoalBinding:
        prompt = promptstore.load(PROMPTS, VERSION).format(
            question=json.dumps(question, ensure_ascii=False))
        from vivacore.models import AdapterError
        try:
            result = self._adapter.extract([], prompt)
        except AdapterError as error:
            self._capture(question, None, False, str(error))
            return GoalBinding("refused", {}, "model_unreachable")
        binding, problem = _read_binding(result.text)
        if result.finish_reason == "length":
            binding, problem = None, "goal_binding_truncated"
        self._capture(question, result, binding is not None, problem)
        return binding or GoalBinding("refused", {}, problem)

    def _capture(self, question: str, result, parse_ok: bool,
                 parse_error: str) -> None:
        request = result.request if result is not None else {}
        response = result.response if result is not None else {}
        raw = result.text if result is not None else ""
        body = {"question": question, "request": request,
                "response": response, "raw": raw}
        usage = response.get("usage") if isinstance(response, dict) else None
        usage_reported = isinstance(usage, dict) and any(
            key in usage for key in ("prompt_tokens", "completion_tokens",
                                     "input_tokens", "output_tokens"))
        self._vault.ledger.append(read_recorded(
            doc_id="goal-binding:" + secrets.token_urlsafe(18),
            model=str(getattr(self._spec, "model", "")),
            prompt_version=VERSION, input_mode="text",
            response_text=json.dumps(body, ensure_ascii=False),
            cost_usd=float(getattr(result, "cost_usd", 0.0) or 0.0),
            input_tokens=int(getattr(result, "input_tokens", 0) or 0),
            output_tokens=int(getattr(result, "output_tokens", 0) or 0),
            parse_ok=parse_ok, parse_error=parse_error or None,
            occurred_at=self._today(), phase="goal_binding",
            resolved_model=str(getattr(result, "resolved_model", "") or ""),
            usage_reported=usage_reported))


def bind_goal_request(vault, spec, question: str, *, adapter=None,
                      today=None) -> GoalBinding:
    return GoalBindingPlanner(vault, spec, adapter=adapter, today=today).bind(
        question)


def _read_binding(text: str) -> tuple[GoalBinding | None, str]:
    try:
        raw = json.loads(text or "")
    except (TypeError, json.JSONDecodeError):
        return None, "goal_binding_unparseable"
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        return None, "goal_binding_shape"
    intent = raw.get("intent")
    if intent not in ("goal", "other"):
        return None, "goal_binding_intent"
    if intent == "other":
        if any(raw.get(field) is not None for field in _FIELDS):
            return None, "goal_binding_other_carried_fields"
        return GoalBinding("other", {}), ""
    payload: dict[str, Any] = {"verb": "create"}
    for field in _FIELDS[:-1]:
        value = raw.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            return None, f"goal_binding_{field}_type"
        if value.strip():
            payload[field] = value.strip()
    day = raw.get("contribution_day")
    if day is not None:
        if isinstance(day, bool) or not isinstance(day, int):
            return None, "goal_binding_contribution_day_type"
        payload["contribution_day"] = day
    return GoalBinding("goal", payload), ""


__all__ = ["GoalBinding", "GoalBindingPlanner", "VERSION",
           "bind_goal_request"]
