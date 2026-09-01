"""Test-only scripted driver for binding and delivery-gate fixtures."""

import json

from vivacore import promptstore, versions
from viva.tools.envelope import ToolResult
from viva.tools.registry import PACKAGE, PROMPTS
from viva.tools.runner import (RunResult, _Ground, _diagnosed, _gate, _refused)
from viva.tools.shape import Shape, weakens

LEGACY_TEST_STEPS = 8
SHAPE_TOOL = "commit_shape"
COMMITTED_VERSION = versions.active(PACKAGE, "shape_committed")
REFUSAL_TAGS = (
    "model_unreachable", "unparseable", "bad_plan", "unshaped_answer",
    "unshaped_read", "call_budget_exhausted", "bad_delivery",
    "unshaped_binding", "bad_binding", "unknown_figure", "unknown_entity",
    "unknown_period", "unknown_reading", "unfounded_date",
    "unfounded_stipulation", "wrong_kind", "wrong_quantity", "wrong_scope",
    "wrong_subject", "nothing_established", "uncited_figure")


def _shape_taken() -> str:
    return promptstore.load(PROMPTS, COMMITTED_VERSION)


def _noted(tool: str, ok: bool, text: str) -> ToolResult:
    return ToolResult(tool=tool, ok=ok, text=text,
                      refusal="" if ok else "bad_shape")


def _committable(current, proposed: Shape, ground: _Ground) -> str:
    if current is None:
        if ground.book or ground.entities or ground.periods:
            return ("A shape is committed before anything is read, and this "
                    "run has already read. There is nothing to do with a "
                    "sentence authored around figures already in hand.")
        return ""
    if not weakens(current, proposed):
        return ("A second shape may only drop clauses from the one already "
                "committed, never add or reword one. A claim written after "
                "its data is the thing the order exists to prevent.")
    return ""


def run(question: str, planner, registry, max_calls: int = LEGACY_TEST_STEPS,
        locale: str = "") -> RunResult:
    """Drive scripted gate fixtures; this is not importable by Viva itself."""
    ground = _Ground(question=question)
    transcript: list[ToolResult] = []
    refused_calls: set[str] = set()
    shape: Shape | None = None
    result = None
    while result is None:
        final_call = len(transcript) >= max_calls
        step = planner({
            "question": question,
            "tools": registry.schemas() if shape is not None else [],
            "descriptions_version": registry.descriptions_version,
            "results": [item.to_dict() for item in transcript],
            "calls_remaining": max(0, max_calls - len(transcript)),
            "shaped": shape is not None,
            "shape": shape.to_dict() if shape is not None else {},
            "final_call": final_call,
        })
        if not isinstance(step, dict):
            result = _refused("bad_plan", "The fixture returned a non-step.",
                              [item.to_dict() for item in transcript],
                              len(transcript), shape)
        elif "refusal" in step:
            tag = str(step["refusal"])
            result = _refused(tag if tag in REFUSAL_TAGS else "bad_plan",
                              str(step.get("text", "")),
                              [item.to_dict() for item in transcript],
                              len(transcript), shape)
        elif "shape" in step:
            proposed = step["shape"]
            if not isinstance(proposed, Shape):
                result = _refused("bad_plan", "A shape must be a Shape.",
                                  [item.to_dict() for item in transcript],
                                  len(transcript), shape)
            elif final_call:
                result = _refused(
                    "call_budget_exhausted", "Scripted gate budget exhausted.",
                    [item.to_dict() for item in transcript], len(transcript),
                    shape, diagnosis=_diagnosed(transcript, registry.names()))
            else:
                problem = _committable(shape, proposed, ground)
                transcript.append(_noted(SHAPE_TOOL, not problem,
                                         problem or _shape_taken()))
                if not problem:
                    shape = proposed
        elif "bindings" in step:
            if shape is None:
                result = _refused("unshaped_answer", "No shape was committed.",
                                  [item.to_dict() for item in transcript],
                                  len(transcript))
            else:
                result = _gate(step, transcript, ground, shape, locale,
                               tools=registry.names())
        elif "tool" in step:
            if shape is None:
                result = _refused("unshaped_read", "Read before shape.",
                                  [item.to_dict() for item in transcript],
                                  len(transcript))
            elif final_call:
                result = _refused(
                    "call_budget_exhausted", "Scripted gate budget exhausted.",
                    [item.to_dict() for item in transcript], len(transcript),
                    shape, diagnosis=_diagnosed(transcript, registry.names()))
            else:
                called = registry.call(step["tool"], step.get("args"),
                                       figures=ground.book, question=question)
                transcript.append(called)
                if called.ok:
                    ground.stamp(called)
                else:
                    fingerprint = json.dumps(
                        {"tool": step["tool"], "args": step.get("args") or {}},
                        sort_keys=True, separators=(",", ":"), default=str)
                    if fingerprint in refused_calls:
                        result = _refused(
                            "call_budget_exhausted",
                            "Planner repeated an identical refused call.",
                            [item.to_dict() for item in transcript],
                            len(transcript), shape,
                            diagnosis=_diagnosed(transcript, registry.names()))
                    refused_calls.add(fingerprint)
        else:
            result = _refused("bad_plan", "Step has no operation.",
                              [item.to_dict() for item in transcript],
                              len(transcript), shape)
    return result


__all__ = ["COMMITTED_VERSION", "REFUSAL_TAGS", "run", "_committable"]
