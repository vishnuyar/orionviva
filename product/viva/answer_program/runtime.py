"""The single compile, validate, execute, bind, deliver answer runtime."""

from __future__ import annotations

from dataclasses import dataclass

from ..persona import moment
from ..tools.runner import RunResult
from .bind import BindingResult, DeterministicBinder
from .compiler import CompilationResult
from .execute import ExecutionResult, ProgramExecutor
from .outcomes import AnswerOutcome


@dataclass(frozen=True)
class RuntimeResult:
    result: RunResult
    outcome: AnswerOutcome
    compilation: CompilationResult
    execution: ExecutionResult | None = None
    binding: BindingResult | None = None


class AnswerProgramRuntime:
    def __init__(self, compiler, executor: ProgramExecutor,
                 binder: DeterministicBinder):
        self.compiler = compiler
        self.executor = executor
        self.binder = binder

    def answer(self, context) -> RuntimeResult:
        compilation = self.compiler.compile(context)
        if not compilation.ok:
            tag = compilation.failure_tag or "invalid_program"
            refusal = ("model_unreachable" if tag == "model_unreachable"
                       else "bad_plan")
            result = RunResult(
                answered=False, text=moment("refusal_" + refusal),
                refusal=refusal, status="failed", outcome_tag=tag)
            outcome = AnswerOutcome("failed", tag=tag, text=result.text,
                                    trace={"model_attempts": len(compilation.exchanges)})
            return RuntimeResult(result, outcome, compilation)

        program = compilation.program
        if program.mode != "answer":
            return self._non_answer(program, compilation)

        execution = self.executor.execute(program, context.question)
        binding = self.binder.bind(program, execution)
        result = binding.result
        status, tag = self._status(program, execution, binding)
        result.status = status
        result.outcome_tag = tag
        result.missing = [item.to_dict() for item in binding.unbound]
        outcome = AnswerOutcome(
            status, tag=tag, text=result.text,
            result=result, missing=tuple(result.missing),
            trace={"model_attempts": len(compilation.exchanges),
                   **execution.to_dict()})
        return RuntimeResult(result, outcome, compilation, execution, binding)

    @staticmethod
    def _non_answer(program, compilation):
        if program.mode == "clarify":
            payload = dict(program.clarification or {})
            tag = str(payload.get("tag") or "needs_clarification")
            question = str(payload.get("question") or "")
            options = tuple(dict(item) for item in payload.get("options", [])
                            if isinstance(item, dict))
            result = RunResult(False, text=question, refusal=tag,
                               status="needs_clarification", outcome_tag=tag,
                               options=list(options))
            outcome = AnswerOutcome("needs_clarification", tag=tag, text=question,
                                    question=question, options=options,
                                    trace={"model_attempts":
                                           len(compilation.exchanges)})
        elif program.mode == "needs_assumption":
            item = next(iter(program.assumptions), {})
            tag = str(item.get("tag") or "needs_assumption")
            question = str(item.get("question") or item.get("label") or "")
            result = RunResult(False, text=question, refusal=tag,
                               status="needs_assumption", outcome_tag=tag,
                               missing=[dict(value) for value in program.assumptions])
            outcome = AnswerOutcome(
                "needs_assumption", tag=tag, text=question,
                question=question, missing=tuple(program.assumptions),
                trace={"model_attempts": len(compilation.exchanges)})
        else:
            tag = "outside_domain"
            text = moment("refusal_nothing_established")
            result = RunResult(False, text=text, refusal=tag,
                               status="outside_domain", outcome_tag=tag)
            outcome = AnswerOutcome(
                "outside_domain", tag=tag, text=text,
                trace={"model_attempts": len(compilation.exchanges)})
        return RuntimeResult(result, outcome, compilation)

    @staticmethod
    def _status(program, execution, binding):
        if execution.deadline_exceeded:
            return "failed", "execution_deadline"
        if execution.evidence_limit_exceeded:
            return "failed", "evidence_limit"
        if execution.figure_limit_exceeded:
            return "failed", "figure_limit"
        if binding.result.answered:
            return ("partial", "clause_gap") if binding.result.gaps else (
                "answered", "")
        refusals = {record.refusal for record in execution.nodes.values()
                    if record.refusal}
        if "unsupported_operation" in refusals:
            return "capability_gap", "unsupported_operation"
        if any(item.reason == "selector_not_unique" for item in binding.unbound):
            return "needs_clarification", "selector_not_unique"
        missing = {"missing_entity", "no_data", "not_found", "empty_result",
                   "insufficient_history"}
        if refusals & missing or binding.unbound:
            return "missing_data", next(iter(sorted(refusals & missing)),
                                        "unbound_evidence")
        return "failed", binding.result.refusal or "delivery_failed"


__all__ = ["AnswerProgramRuntime", "RuntimeResult"]
