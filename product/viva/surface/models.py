"""Small, JSON-safe models the interface can render without doing product math."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PanelState(StrEnum):
    ABSENT = "absent"
    READY = "ready"
    PARTIAL = "partial"
    NEEDS_INPUT = "needs_input"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class FigureGrade(StrEnum):
    VERIFIED = "verified"
    CORROBORATED = "corroborated"
    UNVERIFIED = "unverified"
    CONFLICTED = "conflicted"


@dataclass(frozen=True)
class FigureView:
    """A figure already interpreted by the product and ready to render."""

    id: str
    exact_value: str
    display: str
    currency: str | None
    measure: str
    grade: FigureGrade
    grade_label: str
    exactness: str
    as_of: str
    coverage: str
    record_ids: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.measure or not self.as_of or not self.coverage:
            raise ValueError("figures require identity, measure, date, and coverage")
        if not isinstance(self.exact_value, str):
            raise TypeError("exact_value must be a decimal string, never a float")
        if self.currency is not None and not self.currency:
            raise ValueError("currency must be omitted or non-empty")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "exact_value": self.exact_value,
            "display": self.display,
            "currency": self.currency,
            "measure": self.measure,
            "grade": self.grade.value,
            "grade_label": self.grade_label,
            "exactness": self.exactness,
            "as_of": self.as_of,
            "coverage": self.coverage,
            "record_ids": list(self.record_ids),
            "provenance": list(self.provenance),
            "caveats": list(self.caveats),
        }


@dataclass(frozen=True)
class ActionOutcome:
    """An explicit result; callers never infer meaning from a bare ``ok``."""

    kind: str
    message: str
    state: dict[str, Any] | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        allowed = {"completed", "refused", "proposal", "waiting", "stale"}
        if self.kind not in allowed:
            raise ValueError(f"unknown action outcome: {self.kind!r}")
        if self.kind == "refused" and not self.reason:
            raise ValueError("refused actions require a reason")

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": self.message, "state": self.state, "reason": self.reason}
