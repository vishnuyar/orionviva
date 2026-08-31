"""Adapt an opened vault to durable conversation and correction handlers.

The adapter owns one lazily built session for the opened vault. Turns are
blocking requests, and no model is called until one is configured.
"""

from __future__ import annotations

from collections.abc import Mapping
import datetime
import json
import secrets
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError
from .jobs import JobCancelled, JobRegistry

# Machine reasons for unconfigured and cancelled requests.
UNCONFIGURED = "no_model_named"
CANCELLED = "job_cancelled"

# Progress states exposed for one blocking ask turn.
ASKED = "asked"
SAID = "said"
TURN_STEPS = (ASKED, SAID)


class UnreadableOutcome(RuntimeError):
    """Raised when the engine answered in a shape no outcome word describes."""


class ConversationActions:
    """Adapt one already-open vault into the allowlisted conversation handler."""

    def __init__(self, vault: Any, jobs: JobRegistry | None = None) -> None:
        self._vault = vault
        self._jobs = jobs if jobs is not None else JobRegistry()
        self._session = None

    def ask(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One question, and the turn it produced.

        The turn is answered as `completed` when it states an answer and
        `refused` when Viva cannot stand behind one. A refusal is an ordinary
        product reply rather than a transport failure."""
        from viva.persona import moment
        from viva.speak import _shown
        from viva.surface.conversation import (conversation, plan_draft_turn,
                                               unconfigured)

        from viva.ledger.events import (conversation_turn_opened,
                                        conversation_turn_settled)

        question, mirrored, plan_request = _ask_request(payload)
        turn_id = secrets.token_urlsafe(18)
        self._vault.ledger.append(conversation_turn_opened(
            turn_id, "ask", question, _today(), mirrored=mirrored))
        if plan_request:
            from viva import speak
            spec = speak.speak_spec()
            if spec is None:
                draft_reply = {
                    "kind": "waiting", "message": moment("plans_empty_body"),
                    "reason": "model_free_form",
                    "state": {"draft_state": "needs_input", "verb": "create",
                              "draft": {}},
                }
            else:
                from viva.goal_binding import bind_goal_request
                binding = bind_goal_request(self._vault, spec, question)
                if binding.intent == "other":
                    draft_reply = None
                elif binding.intent == "refused":
                    draft_reply = {
                        "kind": "refused",
                        "message": moment(
                            "refusal_model_unreachable"
                            if binding.reason == "model_unreachable"
                            else "plans_action_refused"),
                        "reason": binding.reason,
                        "state": {"draft_state": "refused", "verb": "create",
                                  "draft": {}},
                    }
                else:
                    from .plan_actions import PlanActions
                    draft_reply = PlanActions(self._vault).draft(binding.payload)
            if draft_reply is not None:
                state = dict(draft_reply.get("state") or {})
                draft_state = str(state.get("draft_state") or "refused")
                said = plan_draft_turn(
                    question, str(draft_reply.get("message") or ""),
                    draft_state, str(state.get("verb") or "create"),
                    state.get("draft") if isinstance(state.get("draft"), dict)
                    else None,
                    str(draft_reply.get("reason") or ""), mirrored)
                kind = str(draft_reply.get("kind") or "refused")
                outcome = ActionOutcome(
                    kind, str(draft_reply.get("message") or ""),
                    reason=str(draft_reply.get("reason") or "") or None,
                    state=said)
                self._vault.ledger.append(conversation_turn_settled(
                    turn_id, outcome.kind, outcome.message, _today(),
                    reason=outcome.reason or "", answer=said))
                return outcome.as_dict()
        session = self._opened()
        if session is None:
            outcome = ActionOutcome(
                "refused", moment("conversation_unconfigured"),
                reason=UNCONFIGURED, state=unconfigured())
            self._vault.ledger.append(conversation_turn_settled(
                turn_id, outcome.kind, outcome.message, _today(),
                reason=outcome.reason or "", answer=outcome.state))
            return outcome.as_dict()
        job = self._jobs.open("viva.conversation.ask", TURN_STEPS)
        try:
            with job:
                job.checkpoint()
                turn = session.ask(question)
                job.reached(ASKED)
                said = conversation(
                    turn, _shown(turn.result), mirrored,
                    projection=self._vault.ledger.projection(),
                    turn_id=turn_id)
                job.reached(SAID)
                outcome = ActionOutcome(
                    "completed" if said["answered"] else "refused",
                    said["text"] or said["refusal"],
                    reason=None if said["answered"] else "not_answered",
                    state={"job_id": job.job_id, **said})
                self._vault.ledger.append(conversation_turn_settled(
                    turn_id, outcome.kind, outcome.message, _today(),
                    reason=outcome.reason or "", answer=said))
                return outcome.as_dict()
        except JobCancelled:
            outcome = ActionOutcome("refused", moment("jobs_stopped"),
                                    reason=CANCELLED,
                                    state={"job_id": job.job_id})
            self._vault.ledger.append(conversation_turn_settled(
                turn_id, outcome.kind, outcome.message, _today(),
                reason=outcome.reason or "", answer=outcome.state))
            return outcome.as_dict()

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Answer one live question and persist the complete outcome."""
        from viva.engine import answer_question
        from viva.ledger.events import (
            conversation_proposal_recorded, conversation_turn_opened,
            conversation_turn_settled)
        from viva.questions import find_question

        question_id, said = _answer_request(payload)
        question = find_question(self._vault.ledger, question_id)
        if question is None:
            from viva.persona import moment
            return ActionOutcome("refused", moment("reply_question_closed"),
                                 reason="not_open").as_dict()
        turn_id = secrets.token_urlsafe(18)
        self._vault.ledger.append(conversation_turn_opened(
            turn_id, "answer", question.text, _today(), said=said,
            question_id=question.id))
        result = answer_question(self._vault, question.id, said)
        proposal = result.get("proposal")
        proposal_id = ""
        if (result.get("ok") is True and result.get("confirm") is True
                and isinstance(proposal, dict)):
            proposal_id = secrets.token_urlsafe(18)
            result = {**result, "proposal": {
                **proposal, "proposal_id": proposal_id}}
            self._vault.ledger.append(conversation_proposal_recorded(
                proposal_id, turn_id, question.id,
                str(proposal.get("summary") or ""), proposal,
                _question_stake(question), _today()))
        outcome = _outcome_of(result)
        self._vault.ledger.append(conversation_turn_settled(
            turn_id, outcome.kind, outcome.message, _today(),
            reason=outcome.reason or "", answer=outcome.state,
            proposal_id=proposal_id))
        return outcome.as_dict()

    def decline(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Set one live question aside inside the durable timeline."""
        from viva.engine import decline_question
        from viva.ledger.events import (conversation_turn_opened,
                                        conversation_turn_settled)
        from viva.questions import find_question

        question_id, reason = _decline_request(payload)
        question = find_question(self._vault.ledger, question_id)
        if question is None:
            from viva.persona import moment
            return ActionOutcome("refused", moment("reply_question_closed"),
                                 reason="not_open").as_dict()
        turn_id = secrets.token_urlsafe(18)
        self._vault.ledger.append(conversation_turn_opened(
            turn_id, "decline", question.text, _today(),
            question_id=question.id))
        outcome = _outcome_of(decline_question(
            self._vault, question.id, reason))
        self._vault.ledger.append(conversation_turn_settled(
            turn_id, outcome.kind, outcome.message, _today(),
            reason=outcome.reason or ""))
        return outcome.as_dict()

    def confirm(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Confirm the exact persisted proposal only while its basis is live."""
        from viva.engine import confirm_proposal
        from viva.ledger.events import (
            conversation_proposal_resolved, conversation_turn_opened,
            conversation_turn_settled)
        from viva.persona import moment
        from viva.questions import find_question

        proposal_id, said, asked = _confirm_request(payload)
        proposal = self._vault.ledger.projection().conversation_proposal(
            proposal_id)
        if proposal is None or proposal.get("status") != "open":
            return ActionOutcome("refused", moment("reply_question_closed"),
                                 reason="proposal_not_open").as_dict()
            # The proposal basis excludes the audit turn appended by this action.
        question = find_question(
            self._vault.ledger, str(proposal.get("question_id") or ""))
        basis_is_live = (question is not None
                         and _question_stake(question) == proposal.get("stake"))
        turn_id = secrets.token_urlsafe(18)
        summary = str(proposal.get("summary") or asked or "Confirm correction")
        self._vault.ledger.append(conversation_turn_opened(
            turn_id, "confirm", summary, _today(), said=said))
        if not basis_is_live:
            outcome = ActionOutcome(
                "stale", moment("reply_question_closed"),
                reason="proposal_basis_changed")
        else:
            result = confirm_proposal(
                self._vault, dict(proposal.get("proposal") or {}), said,
                asked=asked or summary)
            if result.get("ok") and result.get("confirmed") is False:
                outcome = ActionOutcome(
                    "set_aside", str(result.get("message") or ""))
            else:
                outcome = _outcome_of(result)
        # Refused interpretations leave the proposal open; terminal or stale
        # outcomes resolve it.
        if outcome.kind != "refused":
            self._vault.ledger.append(conversation_proposal_resolved(
                proposal_id, turn_id, outcome.kind, outcome.message, _today(),
                reason=outcome.reason or ""))
        self._vault.ledger.append(conversation_turn_settled(
            turn_id, outcome.kind, outcome.message, _today(),
            reason=outcome.reason or ""))
        return outcome.as_dict()

    def _opened(self):
        """Return the lazily built session for this opened vault, if configured."""
        if self._session is not None:
            return self._session
        from viva import speak

        # Module lookup lets tests replace the same configuration used here.
        spec = speak.speak_spec()
        if spec is None:
            return None
        self._session = _session_for(self._vault, spec,
                                     speak.planner_factory(spec),
                                     speak.max_calls_from_env(),
                                     _prior_context(
                                         self._vault.ledger.projection()))
        return self._session


def _session_for(vault, spec, factory, max_calls, prior_turns=()):
    """Build a session over the opened vault's current projection registry."""
    from viva.env import locale_from_env
    from viva.speak import Session
    from viva.tools import default_registry

    locale = locale_from_env()
    return Session(default_registry(vault.ledger.projection(), locale), factory,
                   ledger=vault.ledger, model=getattr(spec, "model", ""),
                   max_calls=max_calls, locale=locale,
                   prior_turns=prior_turns)


def _prior_context(projection) -> list[tuple[str, str]]:
    """Past visible ask turns as text context, never as current evidence."""
    out = []
    for row in projection.conversation_turns():
        if row.get("kind") != "ask":
            continue
        if row.get("outcome") not in ("completed", "refused"):
            continue
        answer = row.get("answer") or {}
        said = str(answer.get("text") or answer.get("refusal")
                   or row.get("message") or "")
        if said:
            out.append((str(row.get("prompt") or ""), said))
    return out


def _question_stake(question) -> dict[str, Any]:
    """The deterministic question state a persisted proposal depends on."""
    stake = {
        "id": question.id, "kind": question.kind,
        "amount": str(question.amount), "currency": question.currency,
        "count": question.count, "scope": question.scope,
        "slots": [slot.to_dict() for slot in question.slots],
        "refs": dict(question.refs),
    }
        # Compare the JSON-normalized form preserved by the event log.
    return json.loads(json.dumps(stake, sort_keys=True))


def _outcome_of(result: Mapping[str, Any]) -> ActionOutcome:
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
        proposal = result.get("proposal")
        state = proposal if isinstance(proposal, dict) else None
        return ActionOutcome("proposal", message or moment("outcome_held"),
                             state=state)
    if result.get("disposition") == "set_aside":
        return ActionOutcome("set_aside", message or moment(
            "not_now_ack", name_part=""))
    if result.get("recorded") is False:
        return ActionOutcome("waiting", message or moment(
            "reply_document_awaited"))
    return ActionOutcome("completed", message or moment("reply_recorded"))


outcome_of = _outcome_of


def _ask_request(payload: Mapping[str, Any]) -> tuple[str, bool, bool]:
    """Validate a question and whether its answer will be mirrored in text."""
    from viva.reply import MAX_REPLY_TOKENS

    allowed = {"question", "mirrored", "plan_request"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            "viva.conversation.ask does not accept fields: "
            + ", ".join(sorted(unexpected)))
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        raise BridgeRequestError("question must be a non-empty string")
    if len(question) > MAX_REPLY_TOKENS * 8:
        raise BridgeRequestError("question is longer than a question may be")
    mirrored = payload.get("mirrored", True)
    if not isinstance(mirrored, bool):
        raise BridgeRequestError("mirrored must be true or false")
    plan_request = payload.get("plan_request", False)
    if not isinstance(plan_request, bool):
        raise BridgeRequestError("plan_request must be true or false")
    return question, mirrored, plan_request


def _answer_request(payload: Mapping[str, Any]) -> tuple[str, str]:
    from viva.reply import MAX_REPLY_TOKENS
    allowed = {"question_id", "said"}
    _fenced(payload, allowed, "viva.conversation.answer")
    question_id = _nonempty(payload, "question_id")
    said = _nonempty(payload, "said")
    if len(said) > MAX_REPLY_TOKENS * 8:
        raise BridgeRequestError("said is longer than a reply may be")
    return question_id, said


def _decline_request(payload: Mapping[str, Any]) -> tuple[str, str]:
    from viva.ledger.events import DECLINE_REASONS
    allowed = {"question_id", "reason"}
    _fenced(payload, allowed, "viva.conversation.decline")
    question_id = _nonempty(payload, "question_id")
    reason = payload.get("reason", DECLINE_REASONS[0])
    if reason not in DECLINE_REASONS:
        raise BridgeRequestError(
            "reason must be one of: " + ", ".join(sorted(DECLINE_REASONS)))
    return question_id, str(reason)


def _confirm_request(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    from viva.reply import MAX_REPLY_TOKENS
    allowed = {"proposal_id", "said", "asked"}
    _fenced(payload, allowed,
            "viva.conversation.confirm")
    proposal_id = _nonempty(payload, "proposal_id")
    said = _nonempty(payload, "said")
    asked = payload.get("asked", "")
    if not isinstance(asked, str):
        raise BridgeRequestError("asked must be a string")
    if len(said) > MAX_REPLY_TOKENS * 8 or len(asked) > MAX_REPLY_TOKENS * 8:
        raise BridgeRequestError("confirmation text is too long")
    return proposal_id, said, asked


def _fenced(payload: Mapping[str, Any], allowed: set[str], operation: str) -> None:
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            f"{operation} does not accept fields: {', '.join(sorted(unexpected))}")


def _nonempty(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise BridgeRequestError(f"{name} must be a non-empty string")
    return value.strip()


def _today() -> str:
    return datetime.date.today().isoformat()
