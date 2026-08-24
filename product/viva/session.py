"""Conversation session state and exchange capture."""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import dataclass, field

from vivacore import promptstore

from .planners import SPEAK_VERSION
from .tools.registry import PROMPTS
from .tools.runner import DEFAULT_MAX_CALLS, RunResult, run

@dataclass
class Turn:
    """One question and how it went: the gated result plus the turn's cost."""

    question: str
    result: RunResult
    exchanges: list = field(default_factory=list)

    @property
    def said(self) -> str:
        return self.result.text if self.result.answered else (
            self.result.text or self.result.refusal)

    @property
    def cost_usd(self) -> float:
        return sum(e.cost_usd for e in self.exchanges)

    @property
    def tokens(self) -> tuple[int, int]:
        return (sum(e.input_tokens for e in self.exchanges),
                sum(e.output_tokens for e in self.exchanges))


class Session:
    """A conversation: turns share context, figures never carry over.

    Each turn is a fresh gated run whose planner receives the prior questions
    and answers as context. When a ledger is supplied, every model exchange is
    appended as a ``ReadRecorded`` event, ``phase="speak"``, so the vault holds
    what left the machine and what came back, verbatim."""

    def __init__(self, registry, planner_factory, ledger=None, model: str = "",
                 max_calls: int = DEFAULT_MAX_CALLS,
                 session_id: str = "", today=None, locale: str = ""):
        self._registry = registry
        self._planner_factory = planner_factory
        self._ledger = ledger
        self._model = model
        self._max_calls = max_calls
        # How a figure is written is a property of this person's paperwork, and
        # it reaches the renderer the same way it reaches the question queue.
        self._locale = locale
        self._session_id = session_id or uuid.uuid4().hex[:12]
        self._today = today or (lambda: datetime.date.today().isoformat())
        self.turns: list[Turn] = []

    def ask(self, question: str) -> Turn:
        prior = [(t.question, t.said) for t in self.turns]
        planner = self._planner_factory(prior)
        result = run(question, planner, self._registry,
                     max_calls=self._max_calls, locale=self._locale)
        turn = Turn(question=question, result=result,
                    exchanges=list(getattr(planner, "exchanges", [])))
        self.turns.append(turn)
        if self._ledger is not None:
            self._record(turn, planner)
        return turn

    def _record(self, turn: Turn, planner) -> None:
        from .ledger.events import read_recorded
        stamps = {"speak": f"{SPEAK_VERSION}@"
                           f"{promptstore.digest(PROMPTS, SPEAK_VERSION)}",
                  "tools": f"{self._registry.descriptions_version}@"
                           f"{promptstore.digest(PROMPTS, self._registry.descriptions_version)}"}
        n = len(self.turns)
        for i, ex in enumerate(turn.exchanges, 1):
            payload = {"prompt_versions": stamps,
                       "modality": ex.modality,
                       "resolved_model": ex.resolved_model,
                       "question": turn.question,
                       # Which exchange authored a sentence, and what a reply
                       # that could not be used was asked to change.
                       "authored_shape": ex.authored_shape,
                       "defect": ex.defect,
                       "request": ex.request, "response": ex.response,
                       # What was said, as the structure it was. A sentence can
                       # then be shown standing on what it stood on, and the
                       # shapes a real conversation actually needs accumulate.
                       "shape": turn.result.shape,
                       "bindings": turn.result.bindings,
                       "verdict": {"answered": turn.result.answered,
                                   "refusal": turn.result.refusal,
                                   # The read whose account of stopping was
                                   # spoken; empty means no cause was spoken,
                                   # not that no read refused.
                                   "diagnosis": turn.result.diagnosis,
                                   "calls": turn.result.calls}}
            self._ledger.append(read_recorded(
                doc_id=f"speak:{self._session_id}:{n}:{i}",
                model=self._model, prompt_version=SPEAK_VERSION,
                input_mode=ex.modality,
                response_text=json.dumps(payload),
                cost_usd=ex.cost_usd, input_tokens=ex.input_tokens,
                output_tokens=ex.output_tokens, parse_ok=ex.parse_ok,
                parse_error=ex.parse_error or None,
                occurred_at=self._today(), phase="speak",
                resolved_model=ex.resolved_model,
                usage_reported=ex.usage_reported))




__all__ = ["Turn", "Session"]
