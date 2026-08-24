"""Injected vault-backed review actions.

This module knows neither the vault implementation nor the desktop transport.
A sidecar entry point injects one already-open vault and gets back the handlers
for the review actions this build serves.

Setting a question aside answers with an outcome rather than a bare ok: what
happened, in Viva's own sentence, and a machine reason whenever she refused. A
refusal is an ordinary reply here — a question that is no longer open is not an
error, and a person is told so in words.

Answering is the single inbound door and it is served here. What crosses is one
question's identity and one sentence, and nothing else: the question is looked
up in the live queue rather than taken from the caller, so a stale screen cannot
answer something that is no longer being asked, or answer it with slots it is no
longer being asked with.

**A sentence is a sentence, whatever this machine has been told to do.** With no
model named, the filler degrades to the identity — each declared scalar slot is
offered the sentence as it was typed, and the same deterministic checks decide.
So a plainly written reply is answered on a machine that sends nothing, and
anything else is refused rather than guessed at. With one named, the same door
reads what a person actually wrote. There are not two answering paths; there is
one, and what it can understand widens.
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
        # This opened-vault bridge retains each unapplied proposal. The caller
        # receives an opaque identity for confirming the retained structure.
        self._proposals: dict[str, dict] = {}

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One reply to one question, in a person's own words.

        The engine reads the sentence into the slots the question declared and
        deterministic code checks every value against its type. A value that
        does not survive is asked again in Viva's voice rather than coerced
        into something nobody stated, which arrives here as a refusal with a
        reason — an ordinary reply, not an error frame."""
        from viva.engine import answer_question

        question_id, said = _answer_request(payload)
        result = answer_question(self._vault, question_id, said)
        proposal = result.get("proposal")
        # Only an accepted answer that requests confirmation opens a proposal.
        # Diagnostic proposal context on a refusal is not retained.
        if (result.get("ok") is True and result.get("confirm") is True
                and isinstance(proposal, dict)):
            import secrets
            proposal_id = secrets.token_urlsafe(18)
            self._proposals[proposal_id] = dict(proposal)
            result = {**result,
                      "proposal": {**proposal, "proposal_id": proposal_id}}
        return outcome_of(result).as_dict()

    def decline(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Set one question aside. It returns when its stake moves."""
        from viva.engine import decline_question

        question_id, reason = _decline_request(payload)
        return outcome_of(decline_question(self._vault, question_id, reason)).as_dict()

    def confirm(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Confirm or reject the exact proposal an answer returned.

        Proposals are transient and unapplied. The caller sends the opaque
        identity of the inspected proposal with the person's yes-or-no
        sentence; the engine applies the server-held structure through the
        same typed confirmation slot as the terminal workflow. A no is an
        explicit decline and writes nothing.
        """
        from viva.engine import confirm_proposal

        proposal_id, said, asked = _confirm_request(payload)
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            from viva.persona import moment
            return ActionOutcome("refused", moment("reply_question_closed"),
                                 reason="proposal_not_open").as_dict()
        result = confirm_proposal(self._vault, proposal, said, asked=asked)
        if result.get("ok"):
            self._proposals.pop(proposal_id, None)
        return outcome_of(result).as_dict()


def outcome_of(result: Mapping[str, Any]) -> ActionOutcome:
    """What the engine did, said in the vocabulary an action answers in.

    Every branch reads a declaration the engine made. Whether it accepted the
    reply is ``ok``; whether accepting it wrote anything is ``recorded``, which
    a reply settled by a document that has not arrived says is false; and the
    machine name for a refusal is ``why``.

    Nothing infers a kind from the shape of a reply. A proposal crosses as an
    explicit unapplied outcome; any other reply this vocabulary has no word
    for raises :class:`UnreadableOutcome` rather than being read as the nearest
    word.
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
        # A proposal is an unapplied state awaiting a separate confirmation.
        proposal = result.get("proposal")
        state = proposal if isinstance(proposal, dict) else None
        return ActionOutcome("proposal", message or moment("outcome_held"),
                             state=state)
    if result.get("disposition") == "set_aside":
        return ActionOutcome("set_aside", message or moment("not_now_ack",
                                                             name_part=""))
    if result.get("recorded") is False:
        return ActionOutcome("waiting", message or moment("reply_document_awaited"))
    return ActionOutcome("completed", message or moment("reply_recorded"))


def _answer_request(payload: Mapping[str, Any]) -> tuple[str, str]:
    """The two things an answer carries, and nothing else.

    No slot values and no parsed structure: a caller that could send those
    would be filling the question's slots itself, and the check that stands
    between a model's structure and the ledger would have a second door with
    nothing behind it."""
    from viva.reply import MAX_REPLY_TOKENS

    allowed = {"question_id", "said"}
    _fenced(payload, allowed, "viva.review.answer")
    said = payload.get("said")
    if not isinstance(said, str) or not said.strip():
        raise BridgeRequestError("said must be a non-empty string")
    # Bounded here as well as inside the engine, so a sentence long enough to
    # be a denial of service is refused before it reaches anything that reads
    # it. The bound is the reply module's own, so one number governs.
    if len(said) > MAX_REPLY_TOKENS * 8:
        raise BridgeRequestError("said is longer than a reply may be")
    return _question_id(payload), said


def _decline_request(payload: Mapping[str, Any]) -> tuple[str, str]:
    from viva.ledger.events import DECLINE_REASONS

    allowed = {"question_id", "reason"}
    _fenced(payload, allowed, "viva.review.decline")
    reason = payload.get("reason", DECLINE_REASONS[0])
    if reason not in DECLINE_REASONS:
        raise BridgeRequestError(
            "reason must be one of: " + ", ".join(sorted(DECLINE_REASONS)))
    return _question_id(payload), reason


def _confirm_request(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    """An inspected proposal's identity, confirmation sentence, and prompt."""
    from viva.reply import MAX_REPLY_TOKENS

    allowed = {"proposal_id", "said", "asked"}
    _fenced(payload, allowed, "viva.review.confirm")
    proposal_id = payload.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        raise BridgeRequestError("proposal_id must be a non-empty string")
    said = payload.get("said")
    if not isinstance(said, str) or not said.strip():
        raise BridgeRequestError("said must be a non-empty string")
    if len(said) > MAX_REPLY_TOKENS * 8:
        raise BridgeRequestError("said is longer than a reply may be")
    asked = payload.get("asked", "")
    if not isinstance(asked, str):
        raise BridgeRequestError("asked must be a string")
    if len(asked) > MAX_REPLY_TOKENS * 8:
        raise BridgeRequestError("asked is longer than a question may be")
    return proposal_id, said, asked


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
