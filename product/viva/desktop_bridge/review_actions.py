"""Injected vault-backed review actions.

This module knows neither the vault implementation nor the desktop transport.
A sidecar entry point injects one already-open vault and gets back the handlers
for the review actions this build serves.

Setting a question aside answers with an outcome rather than a bare ok: what
happened, in Viva's own sentence, and a machine reason whenever she refused. A
refusal is an ordinary reply here — a question that is no longer open is not an
error, and a person is told so in words.

The review capability also declares an ``answer`` action, and no handler for it
is registered. The operation is therefore declared and unserved: a frame naming
it is refused by the allowlist rather than by silence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError


class UnreadableOutcome(RuntimeError):
    """Raised when the engine answered in a shape no outcome word describes."""


class ReviewActions:
    """Adapt one already-open vault into the allowlisted review handlers."""

    def __init__(self, vault: Any) -> None:
        self._vault = vault

    def decline(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Set one question aside. It returns when its stake moves."""
        from viva.engine import decline_question

        question_id, reason = _decline_request(payload)
        return outcome_of(decline_question(self._vault, question_id, reason)).as_dict()


def outcome_of(result: Mapping[str, Any]) -> ActionOutcome:
    """What the engine did, said in the vocabulary an action answers in.

    Every branch reads a declaration the engine made. Whether it accepted the
    reply is ``ok``; whether accepting it wrote anything is ``recorded``, which
    a reply settled by a document that has not arrived says is false; and the
    machine name for a refusal is ``why``.

    Nothing infers a kind from the shape of a reply. A reply this vocabulary
    has no word for — one held for a confirmation, which is transient and does
    not cross this bridge — raises :class:`UnreadableOutcome` rather than being
    read as the nearest word.
    """
    from viva.persona import moment

    if "ok" not in result:
        raise UnreadableOutcome(moment("outcome_unstated"))
    message = str(result.get("message") or "")
    if not result["ok"]:
        why = str(result.get("why") or "")
        if not why:
            raise UnreadableOutcome(moment("outcome_unexplained"))
        return ActionOutcome("refused", message or moment("reply_ask_again"),
                             reason=why)
    if "proposal" in result:
        raise UnreadableOutcome(moment("outcome_held"))
    if result.get("recorded") is False:
        return ActionOutcome("waiting", message or moment("reply_document_awaited"))
    return ActionOutcome("completed", message or moment("reply_recorded"))


def _decline_request(payload: Mapping[str, Any]) -> tuple[str, str]:
    from viva.ledger.events import DECLINE_REASONS

    allowed = {"question_id", "reason"}
    _fenced(payload, allowed, "viva.review.decline")
    reason = payload.get("reason", DECLINE_REASONS[0])
    if reason not in DECLINE_REASONS:
        raise BridgeRequestError(
            "reason must be one of: " + ", ".join(sorted(DECLINE_REASONS)))
    return _question_id(payload), reason


def _fenced(payload: Mapping[str, Any], allowed: set[str], operation: str) -> None:
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            f"{operation} does not accept fields: {', '.join(sorted(unexpected))}")


def _question_id(payload: Mapping[str, Any]) -> str:
    question_id = payload.get("question_id")
    if not isinstance(question_id, str) or not question_id.strip():
        raise BridgeRequestError("question_id must be a non-empty string")
    return question_id
