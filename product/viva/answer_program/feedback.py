"""Private-value-free local diagnostics for answer breadth."""

from __future__ import annotations

from collections import Counter
import hashlib
import json


def _program_shape(program):
    if program is None:
        return {}
    return {
        "mode": program.mode,
        "question_kind": program.question_kind,
        "nodes": [{"kind": node.kind, "tool": node.tool,
                   "arg_fields": sorted(node.args),
                   "query_ops": [step.get("op") for step in
                                 node.query.get("steps", [])]}
                  for node in program.nodes],
        "slots": sorted(slot.type for slot in
                        (program.shape.slots.values() if program.shape else ())),
    }


class BreadthFeedback:
    """In-memory/local counters; questions and financial values are excluded."""

    def __init__(self):
        self.statuses = Counter()
        self.outcome_tags = Counter()
        self.question_kinds = Counter()
        self.program_shapes = Counter()

    def observe(self, runtime_result):
        result = runtime_result.result
        self.statuses[result.status or "unknown"] += 1
        if result.outcome_tag:
            self.outcome_tags[result.outcome_tag] += 1
        program = runtime_result.compilation.program
        if program is not None:
            self.question_kinds[program.question_kind or "unknown"] += 1
            shape = _program_shape(program)
            digest = hashlib.sha256(json.dumps(
                shape, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
            self.program_shapes[digest] += 1

    def report(self, *, promotion_threshold=3):
        return {
            "statuses": dict(self.statuses),
            "capability_gaps": {tag: count for tag, count in self.outcome_tags.items()
                                if tag in ("unsupported_operation",
                                           "unknown_query_operator",
                                           "unknown_capability")},
            "missing_data": {tag: count for tag, count in self.outcome_tags.items()
                             if tag in ("no_data", "not_found", "empty_result",
                                        "unbound_evidence")},
            "unsupported_requested_operations":
                int(self.outcome_tags.get("unsupported_operation", 0)),
            "promotion_candidates": sorted(
                ({"program_fingerprint": digest, "count": count}
                 for digest, count in self.program_shapes.items()
                 if count >= promotion_threshold),
                key=lambda item: (-item["count"], item["program_fingerprint"])),
            "question_kinds": dict(self.question_kinds),
        }


__all__ = ["BreadthFeedback"]
