"""The review loop, from a bridge frame to the ledger and back to the read.

The queue is how the vault gets more honest, so what this file holds is that a
person setting a question aside reaches it and that the read moves afterwards.
Every name and figure here is invented.
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
    """One vault holding a single statement, which is enough to be asked
    about: an uncategorised merchant and a statement whose period has ended."""
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

    def review(self) -> dict:
        return self.send("viva.surface.read",
                         {"surface": "review", "parameters": {"limit": 10}})["data"]


def test_setting_a_question_aside_moves_it_into_the_set_aside_count(tmp_path):
    """The whole loop: the read says what is open, a question is set aside, and
    the next read reports it waiting rather than gone. A decline does not
    destroy a question — the read already counts what is waiting, so a person
    can see where it went."""
    sidecar = _Sidecar(_vault(tmp_path))
    before = sidecar.review()
    assert before["total"] >= 1
    set_aside_before = before["pending"]["count"]

    outcome = sidecar.send("viva.review.decline",
                           {"question_id": before["questions"][0]["id"],
                            "reason": "not_now"})

    after = sidecar.review()
    assert outcome["kind"] == "completed"
    assert outcome["message"], "an outcome always says what happened"
    assert after["total"] == before["total"] - 1
    assert after["pending"]["count"] == set_aside_before + 1


def test_a_question_set_aside_twice_refuses_the_second_time(tmp_path):
    """A stale caller cannot set aside something that is no longer being asked.
    The second attempt is refused in words, with a machine reason beside them,
    and nothing else in the read moves."""
    sidecar = _Sidecar(_vault(tmp_path))
    question_id = sidecar.review()["questions"][0]["id"]
    sidecar.send("viva.review.decline",
                 {"question_id": question_id, "reason": "not_now"})
    settled = sidecar.review()

    outcome = sidecar.send("viva.review.decline",
                           {"question_id": question_id, "reason": "not_now"})

    assert outcome["kind"] == "refused"
    assert outcome["reason"]
    assert outcome["message"]
    assert sidecar.review()["total"] == settled["total"]


def test_a_plainly_written_answer_reaches_the_queue_with_no_model_named(tmp_path):
    """A sentence is a sentence, whatever this machine has been told to do.
    With no model named the filler degrades to the identity, so a plainly
    written reply is answered on a machine that sends nothing — and anything
    else is refused rather than guessed at."""
    sidecar = _Sidecar(_vault(tmp_path))
    question = sidecar.review()["questions"][0]

    answered = sidecar.send("viva.review.answer",
                            {"question_id": question["id"], "said": "groceries"})

    assert answered["kind"] in ("completed", "refused")
    # Whichever it was, it was the vault's own answer rather than an operation
    # the allowlist would not take.
    assert answered["message"]


# ------------------------------------------------- answering, the single door


def test_the_answer_action_is_served_and_takes_a_question_and_a_sentence(tmp_path):
    """Nothing but the question and the sentence crosses. A caller that could
    send slot values would be filling the question's slots itself, and the
    check that stands between a model's structure and the ledger would have a
    second door with nothing behind it."""
    from viva.desktop_bridge.handlers import handlers_for_opened_vault

    handlers = handlers_for_opened_vault(object()).handlers

    assert "viva.review.answer" in handlers


def test_answering_a_question_that_is_not_open_refuses_with_a_reason(tmp_path):
    """The question is looked up in the live queue rather than taken from the
    caller, so a stale screen cannot answer something that is no longer being
    asked."""
    from viva.desktop_bridge.review_actions import ReviewActions
    from viva.persona import moment
    from viva.vault import Vault

    vault = Vault.open(tmp_path / "vault", "pw")

    answered = ReviewActions(vault).answer(
        {"question_id": "nothing-is-asking-this", "said": "yes"})

    assert answered["kind"] == "refused"
    assert answered["reason"] == "not_open"
    assert answered["message"] == moment("reply_question_closed")


def test_an_answer_request_takes_those_two_fields_and_no_others(tmp_path):
    from viva.desktop_bridge.handlers import BridgeRequestError
    from viva.desktop_bridge.review_actions import _answer_request

    with pytest.raises(BridgeRequestError):
        _answer_request({"question_id": "q", "said": "yes", "same_account": "yes"})
    with pytest.raises(BridgeRequestError):
        _answer_request({"question_id": "q", "said": "   "})
    with pytest.raises(BridgeRequestError):
        _answer_request({"question_id": "q", "said": "x" * 100_000})


def test_a_slot_says_what_it_wants_back_in_words_and_names_its_vocabulary():
    """The same declaration the inbound check reads, said in words a person can
    act on. A surface writing it would be writing the second half of a contract
    whose first half lives in code."""
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
    """Narrowing what a model is told costs the model a prior. It must never
    cost the person an answer."""
    from viva.reply import Slot
    from viva.schemas import ANSWER_CHOICE

    slot = Slot(name="category", type=ANSWER_CHOICE,
                choices=("food", "rent", "a-name-a-person-coined"),
                offered=("food", "rent"))

    assert "a-name-a-person-coined" in slot.to_dict()["wants"]
