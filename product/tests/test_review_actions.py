"""The review loop, from a bridge frame to the ledger and back to the read.

The queue is how the vault gets more honest, so what this file holds is that a
person setting a question aside reaches it and that the read moves afterwards.
Every name and figure here is invented.
"""

from __future__ import annotations

import json
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


def test_the_declared_answer_action_is_reachable_by_name_and_served_by_nobody(tmp_path):
    """The registry declares an `answer` action, so the operation exists and the
    table stays the complete list of everything that could touch a vault. This
    build registers no handler for it, so a frame naming it is refused rather
    than quietly doing something."""
    sidecar = _Sidecar(_vault(tmp_path))
    question_id = sidecar.review()["questions"][0]["id"]

    response = sidecar.refused("viva.review.answer",
                               {"question_id": question_id, "said": "groceries"})

    assert response["error"]["code"] == "operation_not_allowed"
    assert sidecar.review()["total"] >= 1
