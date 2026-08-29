"""The durable conversation is the sole product-facing correction history."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

from viva.desktop_bridge.conversation_actions import ConversationActions
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.engine import _record_interpret
from viva.ledger.events import (conversation_proposal_recorded,
                                conversation_turn_opened, read_recorded)
from viva.surface.conversation import timeline
from viva.vault import Vault


def test_an_unconfigured_ask_is_durable_across_a_new_vault_object(
        tmp_path, monkeypatch):
    for name in ("VIVA_SPEAK_MODEL", "VIVA_MODEL"):
        monkeypatch.delenv(name, raising=False)
    directory = tmp_path / "vault"
    vault = Vault.open(directory, "pw")

    result = ConversationActions(vault).ask(
        {"question": "What changed?", "mirrored": True})
    reopened = Vault.open(directory, "pw")
    read = OpenedVaultSurfaceProvider(reopened).read_surface(
        "conversation", {})

    assert result["kind"] == "refused"
    assert [(turn["kind"], turn["prompt"], turn["outcome"])
            for turn in read["turns"]] == [
                ("ask", "What changed?", "refused")]


def test_an_opened_turn_without_a_settlement_is_shown_as_interrupted(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(conversation_turn_opened(
        "turn-interrupted", "ask", "Where did it stop?", "2026-08-29"))

    read = timeline(vault.ledger.projection(), {
        "questions": [], "total": 0, "tail": {"count": 0, "amount": ""},
        "pending": {"count": 0}, "invite": "",
        "answered_by_document": ""})

    assert read["turns"][0]["outcome"] == "stale"
    assert read["turns"][0]["reason"] == "interrupted"


def test_a_proposal_persisted_before_an_interruption_remains_reachable(
        tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(conversation_turn_opened(
        "turn-interrupted", "answer", "What was this?", "2026-08-29",
        said="a loan", question_id="q-1"))
    vault.ledger.append(conversation_proposal_recorded(
        "proposal-1", "turn-interrupted", "q-1",
        "Record this as a loan.",
        {"scope": "movement", "subject": "movement-1", "legs": [],
         "new_accounts": [], "currency": "USD"},
        {"id": "q-1", "kind": "nature", "amount": "10",
         "currency": "USD", "count": 1, "scope": "one", "slots": [],
         "refs": {}}, "2026-08-29"))

    read = timeline(vault.ledger.projection(), {
        "questions": [], "total": 0, "tail": {"count": 0, "amount": ""},
        "pending": {"count": 0}, "invite": "",
        "answered_by_document": ""})

    assert read["turns"][0]["outcome"] == "stale"
    assert read["turns"][0]["proposal"] == {
        "id": "proposal-1", "summary": "Record this as a loan.",
        "status": "open", "outcome": "proposal", "message": "",
        "reason": ""}


def test_old_technical_read_records_are_not_backfilled_into_conversation(
        tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(read_recorded(
        "old-call", "model-route", "old-prompt", "text", "old response",
        0.0, 0, 0, True, None, "2026-08-28", phase="speak"))

    read = OpenedVaultSurfaceProvider(vault).read_surface("conversation", {})

    assert read["turns"] == []


def test_interpretation_exchanges_are_captured_as_outbound_evidence(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    model_result = SimpleNamespace(
        text='{"confirm":"yes"}', resolved_model="provider-model",
        input_tokens=7, output_tokens=3, cost_usd=0.002,
        request={"model": "route-model"},
        response={"usage": {"input_tokens": 7, "output_tokens": 3}})
    extractor = lambda _prompt: model_result.text
    extractor.exchanges = [{"prompt": "Interpret this reply", "result": model_result}]
    extractor.spec = SimpleNamespace(model="route-model")
    parsed = SimpleNamespace(ok=True, version="interpret-v1", why="", detail="")

    _record_interpret(vault, extractor, "Is that right?", "yes", parsed)
    captured = [event for event in vault.events()
                if event.event_type == "ReadRecorded"]

    assert captured[-1].body["phase"] == "interpret"
    assert captured[-1].body["resolved_model"] == "provider-model"
    assert captured[-1].body["usage_reported"] is True
    body = json.loads(captured[-1].body["response_text"])
    assert body["asked"] == "Is that right?"
    assert body["said"] == "yes"


def test_conversation_events_begin_on_the_day_the_product_turn_occurs(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    ConversationActions(vault).ask({"question": "What is here?", "mirrored": True})
    turns = vault.ledger.projection().conversation_turns()
    assert turns[-1]["occurred_at"] == datetime.date.today().isoformat()


def test_a_proposal_whose_deterministic_basis_moved_is_closed_as_stale(
        tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / "vault", "pw")
    stake = {"id": "q-1", "kind": "nature", "amount": "10", "currency": "USD",
             "count": 1, "scope": "one", "slots": [], "refs": {}}
    vault.ledger.append(conversation_turn_opened(
        "answer-turn", "answer", "What was this?", "2026-08-29",
        said="a loan", question_id="q-1"))
    vault.ledger.append(conversation_proposal_recorded(
        "proposal-1", "answer-turn", "q-1", "Record this as a loan.",
        {"scope": "movement", "subject": "movement-1", "legs": [],
         "new_accounts": [], "currency": "USD"},
        stake, "2026-08-29"))
    moved = SimpleNamespace(
        id="q-1", kind="nature", amount=11, currency="USD", count=1,
        scope="one", slots=(), refs={})
    monkeypatch.setattr("viva.questions.find_question",
                        lambda *_args, **_kwargs: moved)

    result = ConversationActions(vault).confirm({
        "proposal_id": "proposal-1", "said": "yes"})

    assert result["kind"] == "stale"
    proposal = vault.ledger.projection().conversation_proposal("proposal-1")
    assert proposal["status"] == "resolved"
    assert proposal["reason"] == "proposal_basis_changed"


def test_an_unreadable_confirmation_turn_leaves_the_exact_proposal_open(
        tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / "vault", "pw")
    stake = {"id": "q-1", "kind": "nature", "amount": "10",
             "currency": "USD", "count": 1, "scope": "one", "slots": [],
             "refs": {}}
    vault.ledger.append(conversation_turn_opened(
        "answer-turn", "answer", "What was this?", "2026-08-29",
        said="a loan", question_id="q-1"))
    vault.ledger.append(conversation_proposal_recorded(
        "proposal-1", "answer-turn", "q-1", "Record this as a loan.",
        {"scope": "movement", "subject": "movement-1", "legs": [],
         "new_accounts": [], "currency": "USD"},
        stake, "2026-08-29"))
    question = SimpleNamespace(
        id="q-1", kind="nature", amount=10, currency="USD", count=1,
        scope="one", slots=(), refs={})
    monkeypatch.setattr("viva.questions.find_question",
                        lambda *_args, **_kwargs: question)
    monkeypatch.setattr("viva.engine.confirm_proposal",
                        lambda *_args, **_kwargs: {
                            "ok": False, "why": "not_in_words",
                            "message": "Please answer yes or no."})

    result = ConversationActions(vault).confirm({
        "proposal_id": "proposal-1", "said": "perhaps"})

    assert result["kind"] == "refused"
    assert vault.ledger.projection().conversation_proposal(
        "proposal-1")["status"] == "open"
    assert vault.ledger.projection().conversation_turns()[-1][
        "outcome"] == "refused"
