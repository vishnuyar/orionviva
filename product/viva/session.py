"""Conversation session state and exchange capture."""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from dataclasses import dataclass, field

from vivacore import promptstore
from vivacore import versions

from .answer_program import (AnswerProgramRuntime, AnswerResourcePolicy,
                             BreadthFeedback, CapabilityManifest, DeterministicBinder,
                             ProgramExecutor, ProgramValidator, QuestionContext)
from .answer_program.compiler import COMPILER_VERSION, REPAIR_VERSION
from .answer_program.intents import SemanticFamilyRegistry
from .answer_program.schema import ANSWER_PROGRAM_VERSION
from .tools.registry import PROMPTS
from .tools.runner import RunResult

@dataclass
class Turn:
    """One question and how it went: the gated result plus the turn's cost."""

    question: str
    result: RunResult
    exchanges: list = field(default_factory=list)
    outcome: object | None = None
    semantic_request: dict = field(default_factory=dict)
    program: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)
    prior_context_digest: str = ""

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

    Each turn selects fresh semantics from prior text and deterministically
    lowers a complete program before reading current evidence. When a ledger is
    supplied, every model exchange is
    appended as a ``ReadRecorded`` event, ``phase="speak"``, so the vault holds
    what left the machine and what came back, verbatim."""

    def __init__(self, registry, compiler_factory, ledger=None, model: str = "",
                 resource_policy: AnswerResourcePolicy | None = None,
                 session_id: str = "", today=None, locale: str = "",
                 prior_turns=(), breadth_feedback=None):
        self._registry = registry
        self._compiler_factory = compiler_factory
        self._ledger = ledger
        self._model = model
        self._policy = resource_policy or AnswerResourcePolicy()
        self._manifest = CapabilityManifest.from_registry(registry)
        self._validator = ProgramValidator(self._manifest, self._policy)
        # How a figure is written is a property of this person's paperwork, and
        # it reaches the renderer the same way it reaches the question queue.
        self._locale = locale
        self._session_id = session_id or uuid.uuid4().hex[:12]
        self._today = today or (lambda: datetime.date.today().isoformat())
        self.feedback = breadth_feedback or BreadthFeedback()
        # Restored turns supply text context; new turns bind current tool evidence.
        self._prior_turns = [(str(question), str(answer))
                             for question, answer in prior_turns]
        self.turns: list[Turn] = []

    def ask(self, question: str) -> Turn:
        prior = self._prior_turns + [(t.question, t.said) for t in self.turns]
        context = QuestionContext(
            question=question, prior_turns=tuple(prior), today=self._today(),
            locale=self._locale, currency_convention=self._locale,
            capability_manifest_version=self._manifest.manifest_version,
            capability_manifest_digest=self._manifest.digest,
            shape_version=ANSWER_PROGRAM_VERSION,
            resource_policy_version=self._policy.policy_version)
        compiler = self._compiler_factory(self._validator, self._manifest,
                                          self._policy)
        if hasattr(compiler, "set_entity_catalog"):
            compiler.set_entity_catalog(self._registry.semantic_entities())
        runtime = AnswerProgramRuntime(
            compiler, ProgramExecutor(
                self._registry, self._policy,
                query_executor=getattr(self._registry, "query_executor", None)),
            DeterministicBinder(self._registry, self._locale))
        answered = runtime.answer(context)
        validation = answered.compilation.validation
        turn = Turn(
            question=question, result=answered.result,
            exchanges=list(answered.compilation.exchanges),
            outcome=answered.outcome,
            semantic_request=(answered.compilation.semantic_outcome.to_dict()
                              if answered.compilation.semantic_outcome else {}),
            program=(answered.compilation.program.to_dict()
                     if answered.compilation.program is not None else {}),
            validation={"defects": [item.to_dict() for item in validation.defects],
                        "static_cost": validation.static_cost}
                       if validation is not None else {},
            execution=(answered.execution.to_dict()
                       if answered.execution is not None else {}),
            prior_context_digest=hashlib.sha256(json.dumps(
                prior, sort_keys=True, separators=(",", ":")).encode()
                                                ).hexdigest()[:16])
        self.turns.append(turn)
        self.feedback.observe(answered)
        if self._ledger is not None:
            self._record(turn)
        return turn

    def _record(self, turn: Turn) -> None:
        from .ledger.events import read_recorded
        from .query.schema import FINANCIAL_QUERY_SCHEMA_VERSION
        from .tools.registry import PACKAGE
        persona_version = versions.active(PACKAGE, "persona_pack")
        families = SemanticFamilyRegistry()
        semantic_schema = versions.active(PACKAGE, "semantic_request_schema")
        stamps = {"semantic_request": f"{COMPILER_VERSION}@"
                           f"{promptstore.digest(PROMPTS, COMPILER_VERSION)}",
                  "semantic_request_retry": f"{REPAIR_VERSION}@"
                           f"{promptstore.digest(PROMPTS, REPAIR_VERSION)}",
                  "semantic_request_schema": f"{semantic_schema}@"
                           f"{versions.fingerprint(versions.path_of(PACKAGE, semantic_schema))}",
                  "semantic_family_registry": families.admission_digest(
                      self._manifest),
                  "tools": f"{self._registry.descriptions_version}@"
                           f"{promptstore.digest(PROMPTS, self._registry.descriptions_version)}",
                  "answer_program_schema": f"{ANSWER_PROGRAM_VERSION}@"
                           f"{versions.fingerprint(versions.path_of(PACKAGE, ANSWER_PROGRAM_VERSION))}",
                  "financial_query_schema": f"{FINANCIAL_QUERY_SCHEMA_VERSION}@"
                           f"{versions.fingerprint(versions.path_of(PACKAGE, FINANCIAL_QUERY_SCHEMA_VERSION))}",
                  "capability_manifest": f"{self._manifest.manifest_version}@{self._manifest.digest}",
                  "persona": f"{persona_version}@"
                           f"{versions.fingerprint(versions.path_of(PACKAGE, persona_version))}"}
        n = len(self.turns)
        semantic_digest = hashlib.sha256(json.dumps(
            turn.semantic_request, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()[:16]
        program_digest = hashlib.sha256(json.dumps(
            turn.program, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()[:16]
        for i, ex in enumerate(turn.exchanges, 1):
            payload = {"prompt_versions": stamps,
                       "modality": ex.modality,
                       "resolved_model": ex.resolved_model,
                       "question": turn.question,
                       "prior_context_digest": turn.prior_context_digest,
                       "defect": dict(ex.defect),
                       "failure_code": ex.failure_code,
                       "request": ex.request, "response": ex.response,
                       "semantic_request": dict(turn.semantic_request),
                       "semantic_request_digest": semantic_digest,
                       "program": dict(turn.program),
                       "lowered_program_digest": program_digest,
                       "validation": dict(turn.validation),
                       "execution": dict(turn.execution),
                       "shape": turn.result.shape,
                       "bindings": turn.result.bindings,
                       "verdict": turn.result.to_dict()}
            self._ledger.append(read_recorded(
                doc_id=f"speak:{self._session_id}:{n}:{i}",
                model=self._model, prompt_version=COMPILER_VERSION,
                input_mode=ex.modality,
                response_text=json.dumps(payload),
                cost_usd=ex.cost_usd, input_tokens=ex.input_tokens,
                output_tokens=ex.output_tokens, parse_ok=ex.parse_ok,
                parse_error=ex.parse_error or None,
                occurred_at=self._today(), phase="speak",
                resolved_model=ex.resolved_model,
                usage_reported=ex.usage_reported))




__all__ = ["Turn", "Session"]
