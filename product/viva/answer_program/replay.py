"""Replay a captured compiled program without another model call."""

from __future__ import annotations

import json

from .bind import DeterministicBinder
from .capability import CapabilityManifest
from .execute import ProgramExecutor
from .schema import AnswerProgram, AnswerResourcePolicy
from .validate import ProgramValidator


def replay_capture(captured, registry, *, locale="", policy=None):
    payload = json.loads(captured) if isinstance(captured, str) else dict(captured)
    program = AnswerProgram.from_dict(payload["program"])
    policy = policy or AnswerResourcePolicy()
    manifest = CapabilityManifest.from_registry(registry)
    checked = ProgramValidator(manifest, policy).validate(program)
    if not checked.ok:
        return {"replayed": False,
                "defects": [item.to_dict() for item in checked.defects]}
    execution = ProgramExecutor(
        registry, policy,
        query_executor=getattr(registry, "query_executor", None)).execute(
            program, str(payload.get("question") or ""))
    binding = DeterministicBinder(registry, locale).bind(program, execution)
    return {"replayed": True, "result": binding.result,
            "execution": execution.to_dict(),
            "binding": {"unbound": [item.to_dict() for item in binding.unbound]}}


__all__ = ["replay_capture"]
