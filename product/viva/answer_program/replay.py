"""Replay a captured compiled program without another model call."""

from __future__ import annotations

import json
import hashlib

from .bind import DeterministicBinder
from .capability import CapabilityManifest
from .execute import ProgramExecutor
from .intents import SemanticFamilyRegistry
from .schema import AnswerProgram, AnswerResourcePolicy
from .validate import ProgramValidator


def replay_capture(captured, registry, *, locale="", policy=None):
    payload = json.loads(captured) if isinstance(captured, str) else dict(captured)
    policy = policy or AnswerResourcePolicy()
    manifest = CapabilityManifest.from_registry(registry)
    raw_program = dict(payload.get("program") or {})
    raw_semantic = dict(payload.get("semantic_request") or {})
    if raw_semantic:
        expected_semantic = str(payload.get("semantic_request_digest") or "")
        actual_semantic = hashlib.sha256(json.dumps(
            raw_semantic, sort_keys=True, separators=(",", ":")).encode()
                                         ).hexdigest()[:16]
        if expected_semantic and expected_semantic != actual_semantic:
            return {"replayed": False, "defects": [{
                "tag": "semantic_request_digest_mismatch"}]}
        families = SemanticFamilyRegistry(
            entity_catalog_digest=str(
                raw_semantic.get("entity_catalog_digest") or ""))
        semantic = families.parse(raw_semantic, require_grounding=False)
        if semantic.kind == "unsupported":
            return {"replayed": False, "defects": [{
                "tag": "unsupported_family",
                "requested_family": (semantic.detail or {}).get(
                    "requested_family", "")}]}
        lowered = families.lower(semantic, manifest).to_dict()
        if raw_program and raw_program != lowered:
            return {"replayed": False, "defects": [{
                "tag": "lowered_program_digest_mismatch"}]}
        raw_program = lowered
    program = AnswerProgram.from_dict(raw_program)
    expected = str(payload.get("lowered_program_digest") or "")
    actual = hashlib.sha256(json.dumps(
        raw_program, sort_keys=True, separators=(",", ":")).encode()
                            ).hexdigest()[:16]
    if expected and expected != actual:
        return {"replayed": False,
                "defects": [{"tag": "lowered_program_digest_mismatch"}]}
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
