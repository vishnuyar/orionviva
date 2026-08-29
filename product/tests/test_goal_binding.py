"""Conversational save-up requests bind narrowly and remain pure drafts."""

from __future__ import annotations

import json

from vivacore.models import ModelSpec
from vivacore.models.base import ModelResult

from viva.desktop_bridge.conversation_actions import ConversationActions
from viva.goal_binding import GoalBinding, bind_goal_request
from viva.vault import Vault


class _Adapter:
    def __init__(self, text: str, *, finish_reason: str = "stop") -> None:
        self.text = text
        self.finish_reason = finish_reason
        self.prompts: list[str] = []

    def extract(self, pages, prompt):
        assert pages == []
        self.prompts.append(prompt)
        return ModelResult(
            text=self.text, resolved_model="provider-model",
            input_tokens=7, output_tokens=3, cost_usd=0.002,
            latency_s=0.1,
            request={"model": "route-model", "prompt": prompt},
            response={"model": "provider-model",
                      "usage": {"input_tokens": 7, "output_tokens": 3}},
            finish_reason=self.finish_reason)


def _spec() -> ModelSpec:
    return ModelSpec(name="goal-test", adapter="openai-compatible",
                     model="route-model", base_url="http://unused.invalid")


def _model_json(**changes) -> str:
    body = {
        "intent": "goal", "title": "Trip", "target_amount": "600",
        "currency": "USD", "target_date": "2026-11-15",
        "monthly_contribution": None, "contribution_day": 15,
    }
    body.update(changes)
    return json.dumps(body)


def test_binding_copies_closed_fields_and_captures_the_raw_exchange(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    adapter = _Adapter(_model_json())

    result = bind_goal_request(
        vault, _spec(),
        "I want to save USD 600 for a Trip by 2026-11-15 on day 15.",
        adapter=adapter, today=lambda: "2026-08-29")

    assert result == GoalBinding("goal", {
        "verb": "create", "title": "Trip", "target_amount": "600",
        "currency": "USD", "target_date": "2026-11-15",
        "contribution_day": 15,
    })
    assert "Do not calculate required contributions" in adapter.prompts[0]
    captured = [event for event in vault.events()
                if event.event_type == "ReadRecorded"][-1]
    assert captured.body["phase"] == "goal_binding"
    assert captured.body["prompt_version"] == "goal-binding-v1"
    assert captured.body["parse_ok"] is True
    assert captured.body["resolved_model"] == "provider-model"
    assert captured.body["usage_reported"] is True
    exchange = json.loads(captured.body["response_text"])
    assert exchange["request"] == {
        "model": "route-model", "prompt": adapter.prompts[0]}
    assert exchange["response"]["usage"] == {
        "input_tokens": 7, "output_tokens": 3}
    assert exchange["raw"] == _model_json()


def test_binding_refuses_malformed_or_truncated_output_after_capture(tmp_path):
    for name, adapter, reason in (
        ("malformed", _Adapter("not json"), "goal_binding_unparseable"),
        ("truncated", _Adapter(_model_json(), finish_reason="length"),
         "goal_binding_truncated"),
    ):
        vault = Vault.open(tmp_path / name, "pw")
        result = bind_goal_request(vault, _spec(), "Make a savings goal.",
                                   adapter=adapter)
        assert result == GoalBinding("refused", {}, reason)
        captured = [event for event in vault.events()
                    if event.event_type == "ReadRecorded"][-1]
        assert captured.body["parse_ok"] is False
        assert captured.body["parse_error"] == reason


def test_model_free_goal_request_routes_to_a_durable_needs_input_form(
        tmp_path, monkeypatch):
    monkeypatch.setattr("viva.speak.speak_spec", lambda: None)
    vault = Vault.open(tmp_path / "vault", "pw")

    result = ConversationActions(vault).ask({
        "question": "I want to save for a trip", "mirrored": True,
        "plan_request": True})
    turn = vault.ledger.projection().conversation_turns()[-1]

    assert result["kind"] == "waiting"
    assert result["state"]["goal_draft"] == {
        "kind": "needs_input", "message": result["message"],
        "reason": "model_free_form", "verb": "create", "draft": {},
        "review_in_plans": True,
    }
    assert turn["answer"]["goal_draft"] == result["state"]["goal_draft"]
    assert not [event for event in vault.events()
                if event.event_type.startswith("Goal")]


def test_configured_goal_request_carries_the_same_deterministic_draft_to_plans(
        tmp_path, monkeypatch):
    monkeypatch.setattr("viva.speak.speak_spec", lambda: _spec())
    bound = {
        "verb": "create", "title": "Trip", "target_amount": "600",
        "currency": "USD", "target_date": "2026-11-15",
        "contribution_day": 15,
    }
    monkeypatch.setattr(
        "viva.goal_binding.bind_goal_request",
        lambda *_args, **_kwargs: GoalBinding("goal", bound))
    vault = Vault.open(tmp_path / "vault", "pw")

    result = ConversationActions(vault).ask({
        "question": "Create a USD 600 savings goal for a trip by 2026-11-15",
        "mirrored": True, "plan_request": True})
    goal_draft = result["state"]["goal_draft"]

    assert result["kind"] == "completed"
    assert goal_draft["kind"] == "ready"
    assert goal_draft["review_in_plans"] is True
    assert goal_draft["draft"]["payload"] == {
        "title": "Trip", "currency": "USD", "target_amount": "600",
        "target_date": "2026-11-15", "monthly_contribution": "",
        "contribution_day": 15,
    }
    assert goal_draft["draft"]["calculated"]["required_monthly"] == "200.00"
    assert not [event for event in vault.events()
                if event.event_type.startswith("Goal")]
