"""Injected vault-backed conversation: one question, one turn, one answer.

This module knows neither the vault implementation nor the desktop transport. A
sidecar entry point injects one already-open vault and gets back the handler for
asking a question.

**The session is the sidecar's.** It lives for as long as the vault is open, so
turns share context the way the engine intends, and nothing on the far side of
the bridge holds one — a caller that could hand a session back could hand back
one nobody had. VOICE-34 requires that text and voice share one session and one
runtime, and this is that session: a voice surface asks the same operation and
reads the same turn.

**A turn is a blocking request rather than a job.** This is one of the five
reserved interface unknowns, and it is answered the narrow way: the reply is the
turn. A job would let a person leave the screen while their question was being
asked, and there is nowhere for the answer to arrive that they could then check
it against — which is the same reason a spoken answer is not given without its
text mirror.

**Nothing is asked of a model this machine has not been told to reach.** With no
model named there is no branch here that calls one: the planner factory answers
with nothing, and what comes back is a reviewed sentence saying so and naming
where a person would say yes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError
from .jobs import JobCancelled, JobRegistry

# Why a question was refused, in the machine's own words.
UNCONFIGURED = "no_model_named"
CANCELLED = "job_cancelled"

# The steps one turn declares. Asking is one step because the engine runs a turn
# as one gated run and reports at its end; splitting it would claim granularity
# this handler does not have.
ASKED = "asked"
SAID = "said"
TURN_STEPS = (ASKED, SAID)


class ConversationActions:
    """Adapt one already-open vault into the allowlisted conversation handler."""

    def __init__(self, vault: Any, jobs: JobRegistry | None = None) -> None:
        self._vault = vault
        self._jobs = jobs if jobs is not None else JobRegistry()
        self._session = None

    def ask(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One question, and the turn it produced.

        The turn is answered as a `proposal` outcome when it refused and a
        `completed` one when it answered, because those are the vocabulary's
        own words for a reply that settled and one that did not — and a refusal
        here is Viva declining to state something she cannot stand behind,
        which is an ordinary reply rather than a failure."""
        from viva.persona import moment
        from viva.speak import _shown
        from viva.surface.conversation import conversation, unconfigured

        question, mirrored = _ask_request(payload)
        session = self._opened()
        if session is None:
            return ActionOutcome(
                "refused", moment("conversation_unconfigured"),
                reason=UNCONFIGURED, state=unconfigured()).as_dict()
        job = self._jobs.open("viva.conversation.ask", TURN_STEPS)
        try:
            with job:
                job.checkpoint()
                turn = session.ask(question)
                job.reached(ASKED)
                said = conversation(turn, _shown(turn.result), mirrored)
                job.reached(SAID)
                return ActionOutcome(
                    "completed" if said["answered"] else "refused",
                    said["text"] or said["refusal"],
                    reason=None if said["answered"] else "not_answered",
                    state={"job_id": job.job_id, **said}).as_dict()
        except JobCancelled:
            return ActionOutcome("refused", moment("jobs_stopped"),
                                 reason=CANCELLED,
                                 state={"job_id": job.job_id}).as_dict()

    def _opened(self):
        """The one session this sidecar holds, or nothing.

        Built on first use rather than at open, so a vault opened on a machine
        that names no model costs nothing and reaches nothing. It is not rebuilt
        after that: turns share context, and a second session would be a second
        conversation wearing the first one's screen."""
        if self._session is not None:
            return self._session
        from viva import speak

        # Read off the module rather than imported by name, so a test that
        # replaces it replaces the one this handler asks. A machine that names
        # no model answers here and reaches nothing.
        spec = speak.speak_spec()
        if spec is None:
            return None
        self._session = _session_for(self._vault, spec,
                                     speak.planner_factory(spec),
                                     speak.max_calls_from_env())
        return self._session


def _session_for(vault, spec, factory, max_calls):
    """One session over one vault, with the tool registry the engine builds.

    The registry reads the projection, which is what keeps a conversation
    answering about the vault that is open rather than about one it was handed
    at some earlier moment. Separated into its own function so a test can build
    a session without a model and without reaching a planner."""
    from viva.env import locale_from_env
    from viva.speak import Session
    from viva.tools import default_registry

    locale = locale_from_env()
    return Session(default_registry(vault.ledger.projection(), locale), factory,
                   ledger=vault.ledger, model=getattr(spec, "model", ""),
                   max_calls=max_calls, locale=locale)


def _ask_request(payload: Mapping[str, Any]) -> tuple[str, bool]:
    """What a question carries: the question, and whether its text is shown.

    `mirrored` is the caller stating a fact about its own screen — whether what
    Viva says will be in front of the person. It is not a preference and it is
    not a switch for speech: it is the input to the rule that a figure is never
    spoken with nowhere to check it, and a caller that says no gets nothing to
    speak rather than a quieter answer."""
    from viva.reply import MAX_REPLY_TOKENS

    allowed = {"question", "mirrored"}
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
    return question, mirrored
