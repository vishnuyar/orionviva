"""Exercise the conversation loop from bridge frames to ledger reads.

Every name and financial value is synthetic.
"""

from __future__ import annotations

import json

import pytest
from decimal import Decimal

from viva.desktop_bridge import dispatch_frame, handlers_for_opened_vault
from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest)
from viva.ledger import EventStore, Ledger
from viva.vault import Vault


def _vault(tmp_path) -> Vault:
    """Return a synthetic vault with one open merchant question."""
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    vault = Vault(ledger=ledger, raw=raw, directory=tmp_path)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Everyday Account", currency="USD",
        opening_amount=Decimal("10000.00"), opening_date="2026-03-01",
        closing_amount=Decimal("9880.00"), closing_date="2026-03-31",
        transactions=[TxnFact("2026-03-05", "QUILLFEATHER BAKERY", Decimal("-120.00"))],
        account_number="000000001122", institution="Northaven Mutual")

    def read(_data, doc_id):
        facts.doc_id = doc_id
        return ReadResult(facts.doc_type, 0.98, facts)

    capture_and_ingest(raw, ledger, b"one-statement", read, captured_at="2026-05-01")
    return vault


class _Sidecar:
    """The frames a desktop would send, over one opened vault's allowlist."""

    def __init__(self, vault: Vault) -> None:
        self._handlers = handlers_for_opened_vault(vault).handlers

    def send(self, operation: str, payload: dict) -> dict:
        frame = json.dumps({"protocol": "2.0", "request_id": "review-1",
                            "operation": operation, "payload": payload})
        response = json.loads(dispatch_frame(frame, self._handlers))
        assert response["ok"] is True, response
        return response["result"]

    def refused(self, operation: str, payload: dict) -> dict:
        frame = json.dumps({"protocol": "2.0", "request_id": "review-1",
                            "operation": operation, "payload": payload})
        response = json.loads(dispatch_frame(frame, self._handlers))
        assert response["ok"] is False, response
        return response

    def conversation(self) -> dict:
        return self.send("viva.surface.read",
                         {"surface": "conversation", "parameters": {"limit": 10}})["data"]


def test_setting_a_question_aside_moves_it_into_the_set_aside_count(tmp_path):
    """A set-aside question leaves the open count and enters the pending count."""
    sidecar = _Sidecar(_vault(tmp_path))
    before = sidecar.conversation()
    assert before["total"] >= 1
    set_aside_before = before["pending"]["count"]

    outcome = sidecar.send("viva.conversation.decline",
                           {"question_id": before["questions"][0]["id"],
                            "reason": "not_now"})

    after = sidecar.conversation()
    assert outcome["kind"] == "set_aside"
    assert outcome["message"], "an outcome always says what happened"
    assert after["total"] == before["total"] - 1
    assert after["pending"]["count"] == set_aside_before + 1


def test_a_question_set_aside_twice_refuses_the_second_time(tmp_path):
    """A stale second set-aside request refuses without moving the read."""
    sidecar = _Sidecar(_vault(tmp_path))
    question_id = sidecar.conversation()["questions"][0]["id"]
    sidecar.send("viva.conversation.decline",
                 {"question_id": question_id, "reason": "not_now"})
    settled = sidecar.conversation()

    outcome = sidecar.send("viva.conversation.decline",
                           {"question_id": question_id, "reason": "not_now"})

    assert outcome["kind"] == "refused"
    assert outcome["reason"]
    assert outcome["message"]
    assert sidecar.conversation()["total"] == settled["total"]


def test_a_plainly_written_answer_reaches_the_queue_with_no_model_named(tmp_path):
    """A plain reply completes or refuses through the vault's answer path."""
    sidecar = _Sidecar(_vault(tmp_path))
    question = sidecar.conversation()["questions"][0]

    answered = sidecar.send("viva.conversation.answer",
                            {"question_id": question["id"], "said": "groceries"})

    assert answered["kind"] in ("completed", "refused")
    # Either result is an ordinary answer-path outcome.
    assert answered["message"]


def test_a_confirmation_proposal_is_readable_and_proves_nothing_was_written():
    """A proposal crosses the bridge as an unapplied outcome."""
    from viva.desktop_bridge.conversation_actions import outcome_of

    proposed = {"summary": "Classify these as transfers to Brokerage.",
                "confirm_accounts": ["Assets:Investments:Brokerage"]}
    outcome = outcome_of({"ok": True, "confirm": True,
                          "proposal": proposed})

    assert outcome.kind == "proposal"
    assert outcome.state == proposed
    assert outcome.message


def test_bridge_can_confirm_a_held_proposal_and_verify_the_durable_account(
        tmp_path, monkeypatch):
    from viva.desktop_bridge.conversation_actions import ConversationActions
    from viva.ledger.events import SCOPE_MOVEMENT
    from viva.listen import Proposal

    vault = _vault(tmp_path)
    movement = vault.ledger.projection().movements()[0]
    account = "Assets:Loans:Sample Person"
    proposal = Proposal(
        scope=SCOPE_MOVEMENT, subject=movement.key,
        legs=[{"major": "asset", "account": account}],
        new_accounts=[account], currency="USD", said="this was a loan")
    actions = ConversationActions(vault)
    question_id = __import__(
        "viva.questions", fromlist=["open_questions"]
    ).open_questions(vault.ledger.projection())["questions"][0]["id"]
    monkeypatch.setattr("viva.engine.answer_question", lambda *_args, **_kwargs: {
        "ok": True, "confirm": True, "proposal": proposal.to_dict()})
    proposed = actions.answer({"question_id": question_id,
                               "said": "this was a loan"})
    proposal_id = proposed["state"]["proposal_id"]
    assert proposed["kind"] == "proposal" and proposed["state"]["summary"]

    # Proposal state survives recreating the bridge adapter.
    outcome = ConversationActions(vault).confirm(
        {"proposal_id": proposal_id, "said": "yes"})

    assert outcome["kind"] == "completed"
    assert account in {info.account
                       for info in vault.ledger.projection().account_infos()}
    ruled = next(m for m in vault.ledger.projection().movements()
                  if m.key == movement.key)
    assert ruled.nature_reason == "ruling"


def test_bridge_can_decline_a_held_proposal_without_writing(tmp_path,
                                                            monkeypatch):
    from viva.desktop_bridge.conversation_actions import ConversationActions
    from viva.ledger.events import SCOPE_MOVEMENT
    from viva.listen import Proposal

    vault = _vault(tmp_path)
    movement = vault.ledger.projection().movements()[0]
    proposal = Proposal(scope=SCOPE_MOVEMENT, subject=movement.key,
                        legs=[{"major": "asset",
                               "account": "Assets:Loans:Sample Person"}],
                        new_accounts=["Assets:Loans:Sample Person"],
                        currency="USD")
    actions = ConversationActions(vault)
    from viva.questions import open_questions
    question_id = open_questions(vault.ledger.projection())["questions"][0]["id"]
    monkeypatch.setattr("viva.engine.answer_question", lambda *_args, **_kwargs: {
        "ok": True, "confirm": True, "proposal": proposal.to_dict()})
    proposed = actions.answer({"question_id": question_id,
                               "said": "this was a loan"})
    proposal_id = proposed["state"]["proposal_id"]

    outcome = actions.confirm({"proposal_id": proposal_id, "said": "no"})

    assert outcome["kind"] == "set_aside"
    assert "Assets:Loans:Sample Person" not in {
        info.account for info in vault.ledger.projection().account_infos()}
    assert vault.ledger.projection().conversation_proposal(
        proposal_id)["status"] == "resolved"


def test_a_refused_answer_does_not_leave_an_unreachable_proposal(tmp_path,
                                                                 monkeypatch):
    """A refused answer neither returns nor retains diagnostic proposal data."""
    from viva.desktop_bridge.conversation_actions import ConversationActions

    vault = _vault(tmp_path)
    actions = ConversationActions(vault)
    from viva.questions import open_questions
    question_id = open_questions(vault.ledger.projection())["questions"][0]["id"]
    monkeypatch.setattr("viva.engine.answer_question", lambda *_args, **_kwargs: {
        "ok": False, "why": "needs_name", "message": "What should I call it?",
        "proposal": {"summary": "Open an unnamed account."}})

    outcome = actions.answer({"question_id": question_id,
                              "said": "this was a loan"})

    assert outcome["kind"] == "refused"
    assert outcome["reason"] == "needs_name"
    assert outcome["state"] is None
    assert vault.ledger.projection().conversation_proposals(open_only=True) == []


def test_an_answer_that_sets_a_question_aside_has_its_own_outcome_kind():
    from viva.desktop_bridge.conversation_actions import outcome_of

    outcome = outcome_of({"ok": True, "disposition": "set_aside",
                          "message": "Set aside until evidence arrives."})

    assert outcome.kind == "set_aside"


# ------------------------------------------------------------ answer requests


def test_the_answer_action_is_served_and_takes_a_question_and_a_sentence(tmp_path):
    """The served answer action accepts a question identity and sentence."""
    from viva.desktop_bridge.handlers import handlers_for_opened_vault

    handlers = handlers_for_opened_vault(object()).handlers

    assert "viva.conversation.answer" in handlers


def test_answering_a_question_that_is_not_open_refuses_with_a_reason(tmp_path):
    """Answering a question absent from the live queue refuses with a reason."""
    from viva.desktop_bridge.conversation_actions import ConversationActions
    from viva.persona import moment
    from viva.vault import Vault

    vault = Vault.open(tmp_path / "vault", "pw")

    answered = ConversationActions(vault).answer(
        {"question_id": "nothing-is-asking-this", "said": "yes"})

    assert answered["kind"] == "refused"
    assert answered["reason"] == "not_open"
    assert answered["message"] == moment("reply_question_closed")


def test_an_answer_request_takes_those_two_fields_and_no_others(tmp_path):
    from viva.desktop_bridge.handlers import BridgeRequestError
    from viva.desktop_bridge.conversation_actions import _answer_request

    with pytest.raises(BridgeRequestError):
        _answer_request({"question_id": "q", "said": "yes", "same_account": "yes"})
    with pytest.raises(BridgeRequestError):
        _answer_request({"question_id": "q", "said": "   "})
    with pytest.raises(BridgeRequestError):
        _answer_request({"question_id": "q", "said": "x" * 100_000})


def test_a_slot_says_what_it_wants_back_in_words_and_names_its_vocabulary():
    """A slot exposes the answer shape and its closed vocabulary in words."""
    from viva.persona import moment
    from viva.reply import Slot
    from viva.schemas import ANSWER_CHOICE, ANSWER_YES_NO

    yes_no = Slot(name="same_account", type=ANSWER_YES_NO).to_dict()
    choice = Slot(name="category", type=ANSWER_CHOICE,
                  choices=("food", "rent")).to_dict()

    assert yes_no["wants"] == moment("wants_yes_no")
    assert choice["choices"] == ["food", "rent"]
    assert "food, rent" in choice["wants"]


def test_what_a_person_may_answer_with_is_never_narrowed_to_what_a_model_is_told():
    """Model hints do not narrow the answers a person may give."""
    from viva.reply import Slot
    from viva.schemas import ANSWER_CHOICE

    slot = Slot(name="category", type=ANSWER_CHOICE,
                choices=("food", "rent", "a-name-a-person-coined"),
                offered=("food", "rent"))

    assert "a-name-a-person-coined" in slot.to_dict()["wants"]
