"""Closed structured outcomes for answers and precise non-answers."""

from __future__ import annotations

from dataclasses import dataclass, field

OUTCOME_STATUSES = ("answered", "partial", "needs_clarification",
                    "needs_assumption", "missing_data", "capability_gap",
                    "outside_domain", "failed")


@dataclass(frozen=True)
class AnswerOutcome:
    status: str
    tag: str = ""
    text: str = ""
    result: object | None = None
    question: str = ""
    options: tuple[dict, ...] = ()
    missing: tuple[dict, ...] = ()
    trace: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in OUTCOME_STATUSES:
            raise ValueError(f"unknown answer outcome {self.status!r}")
        if self.status == "needs_clarification" and not self.question:
            raise ValueError("a clarification outcome must ask a question")

    def to_dict(self) -> dict:
        out = {"status": self.status, "tag": self.tag, "text": self.text,
               "options": [dict(item) for item in self.options],
               "missing": [dict(item) for item in self.missing],
               "trace": dict(self.trace)}
        if self.result is not None:
            out["result"] = (self.result.to_dict()
                             if hasattr(self.result, "to_dict") else self.result)
        if self.question:
            out["question"] = self.question
        return out
