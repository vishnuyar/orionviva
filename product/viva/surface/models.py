"""Small, JSON-safe models the interface can render without doing product math."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..quantity import MEASURES


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


class ProofEmphasis(StrEnum):
    """Whether compact proof may recede in a presentation."""

    ROUTINE = "routine"
    REQUIRED = "required"


class ProofReason(StrEnum):
    """Structured reasons compact proof must remain visible.

    These are audit data, never sentences and never instructions for an
    interface to translate into financial copy.  The deliberately neutral
    ``INEXACT`` and ``CAVEAT`` names make no materiality claim the current
    structured evidence does not carry.
    """

    CONFLICT = "conflict"
    UNCERTAIN_BASIS = "uncertain_basis"
    INEXACT = "inexact"
    CAVEAT = "caveat"
    STALE_BOUNDARY = "stale_boundary"
    MIXED_VINTAGE = "mixed_vintage"
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    MISSING_EVIDENCE = "missing_evidence"


@dataclass(frozen=True)
class ProofPresentation:
    """Closed presentation policy for one canonical figure."""

    emphasis: ProofEmphasis
    reasons: tuple[ProofReason, ...] = ()
    qualifications: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.emphasis, ProofEmphasis):
            raise TypeError("proof emphasis is a member of ProofEmphasis")
        if not isinstance(self.reasons, tuple) or any(
            not isinstance(reason, ProofReason) for reason in self.reasons
        ):
            raise TypeError("proof reasons are a tuple of ProofReason values")
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("proof reasons are unique")
        if not isinstance(self.qualifications, tuple) or any(
            not isinstance(line, str) or not line.strip()
            for line in self.qualifications
        ):
            raise TypeError("proof qualifications are non-empty backend copy")
        if len(self.qualifications) != len(set(self.qualifications)):
            raise ValueError("proof qualifications are unique")
        if self.emphasis is ProofEmphasis.ROUTINE and (
            self.reasons or self.qualifications
        ):
            raise ValueError("routine proof has no required qualification")
        if self.emphasis is ProofEmphasis.REQUIRED and (
            not self.reasons or not self.qualifications
        ):
            raise ValueError(
                "required proof names why and carries backend qualification copy")

    def as_dict(self) -> dict[str, Any]:
        return {
            "emphasis": self.emphasis.value,
            "reasons": [reason.value for reason in self.reasons],
            "qualifications": list(self.qualifications),
        }


class CitationRelation(StrEnum):
    """How a document stands to the figure that cites it.

    The vocabulary is closed, and it is closed here because a citation is what
    the interface renders: a relation nothing reviewed would reach a person as
    a claim about evidence that nobody wrote down.

    `ATTESTS` is the first witness — the figure was read from this document.
    `CORROBORATES` is a second one, and calling the first the second is a claim
    about independence that the record does not support.
    """

    ATTESTS = "attests"
    CORROBORATES = "corroborates"
    SAME_PERIOD = "same_period"
    SAME_ACCOUNT = "same_account"
    SETTLES_QUESTION = "settles_question"


@dataclass(frozen=True)
class Citation:
    """A route from a figure back to the record it stands on.

    `document_id` is the identity the documents surface holds a document
    under, unchanged, so a person following the citation lands on that row.
    `page` is where on the document the figure was printed, as it was
    recorded, and is empty where the read did not supply one — which the
    interface says rather than guessing at.
    """

    document_id: str
    page: str = ""
    label: str = ""
    relation: CitationRelation = CitationRelation.ATTESTS

    def __post_init__(self) -> None:
        if not self.document_id:
            raise ValueError("a citation without a document routes nowhere")
        if not isinstance(self.page, str):
            raise TypeError("page is recorded as text, never as a number")
        if self.relation not in CitationRelation:
            raise ValueError(f"unknown citation relation: {self.relation!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "page": self.page,
            "label": self.label,
            "relation": CitationRelation(self.relation).value,
        }


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
    proof_presentation: ProofPresentation
    grade_description: str = ""
    record_ids: tuple[str, ...] = ()
    provenance: str = ""
    citations: tuple[Citation, ...] = ()
    caveats: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.measure or not self.as_of or not self.coverage:
            raise ValueError("figures require identity, measure, date, and coverage")
        if not isinstance(self.exact_value, str):
            raise TypeError("exact_value must be a decimal string, never a float")
        if self.currency is not None and not self.currency:
            raise ValueError("currency must be omitted or non-empty")
        # What a figure declares it measures comes from the vocabulary a figure
        # declares from, which holds one name more than the one a hole asks
        # from: a figure may say nothing measured it, and no hole may ask for
        # that.
        if self.measure not in MEASURES:
            raise ValueError(f"a figure measures one of {', '.join(MEASURES)}, "
                             f"never {self.measure!r}")
        if not isinstance(self.provenance, str):
            raise TypeError("provenance is one sentence, never a list of them")
        if any(not isinstance(item, Citation) for item in self.citations):
            raise TypeError("a citation is the model this module owns")
        if not isinstance(self.proof_presentation, ProofPresentation):
            raise TypeError("proof_presentation is the closed surface model")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "exact_value": self.exact_value,
            "display": self.display,
            "currency": self.currency,
            "measure": self.measure,
            "grade": self.grade.value,
            "grade_label": self.grade_label,
            "grade_description": self.grade_description,
            "exactness": self.exactness,
            "as_of": self.as_of,
            "coverage": self.coverage,
            "proof_presentation": self.proof_presentation.as_dict(),
            "record_ids": list(self.record_ids),
            "provenance": self.provenance,
            "citations": [citation.as_dict() for citation in self.citations],
            "caveats": list(self.caveats),
        }


@dataclass(frozen=True)
class ObligationView:
    """One grounded outgoing expectation, already worded for presentation."""

    id: str
    subject: str
    cadence: str
    expected_date: str
    status: str
    basis: str
    amount_display: str
    amount_min: str
    amount_max: str
    currency: str
    grade: str
    headline: str
    explanation: str
    coverage: str
    record_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    account_ids: tuple[str, ...]
    caveats: tuple[str, ...] = ()
    required_visibility: bool = False
    actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.id, self.subject, self.cadence, self.expected_date,
                    self.status, self.basis, self.headline, self.explanation,
                    self.coverage)):
            raise ValueError("an obligation requires identity, basis, date and reviewed copy")
        if self.status not in ("due", "expected"):
            raise ValueError("an obligation is due or expected")
        if self.basis not in ("confirmed", "measured", "observed"):
            raise ValueError("an obligation basis is confirmed, measured or observed")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "subject": self.subject, "cadence": self.cadence,
            "expected_date": self.expected_date, "status": self.status,
            "basis": self.basis, "amount_display": self.amount_display,
            "amount_min": self.amount_min, "amount_max": self.amount_max,
            "currency": self.currency, "grade": self.grade,
            "headline": self.headline, "explanation": self.explanation,
            "coverage": self.coverage, "record_ids": list(self.record_ids),
            "evidence_ids": list(self.evidence_ids),
            "account_ids": list(self.account_ids), "caveats": list(self.caveats),
            "required_visibility": self.required_visibility,
            "actions": list(self.actions),
        }


@dataclass(frozen=True)
class FindingView:
    """One backend-ranked change, with its complete reviewed explanation."""

    id: str
    kind: str
    subject: str
    importance: int
    amount_display: str
    exact_value: str
    currency: str
    dated: str
    headline: str
    explanation: str
    coverage: str
    record_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    account_ids: tuple[str, ...]
    required_visibility: bool = True
    actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.id, self.kind, self.subject, self.headline,
                    self.explanation, self.coverage)):
            raise ValueError("a finding requires identity, kind and reviewed copy")
        if self.importance < 1:
            raise ValueError("finding importance is a positive backend rank")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "subject": self.subject,
            "importance": self.importance, "amount_display": self.amount_display,
            "exact_value": self.exact_value, "currency": self.currency,
            "dated": self.dated, "headline": self.headline,
            "explanation": self.explanation, "coverage": self.coverage,
            "record_ids": list(self.record_ids),
            "evidence_ids": list(self.evidence_ids),
            "account_ids": list(self.account_ids),
            "required_visibility": self.required_visibility,
            "actions": list(self.actions),
        }


@dataclass(frozen=True)
class ActionOutcome:
    """An explicit result; callers never infer meaning from a bare ``ok``."""

    kind: str
    message: str
    state: dict[str, Any] | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        allowed = {"completed", "refused", "proposal", "waiting", "stale",
                   "set_aside"}
        if self.kind not in allowed:
            raise ValueError(f"unknown action outcome: {self.kind!r}")
        if self.kind == "refused" and not self.reason:
            raise ValueError("refused actions require a reason")

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": self.message, "state": self.state, "reason": self.reason}
