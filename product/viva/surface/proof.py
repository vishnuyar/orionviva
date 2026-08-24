"""Conservative proof presentation over structured evidence facts.

The policy decides reasons before it handles any wording. A caller supplies
the grade, exactness, boundary, records, caveat presence, freshness conclusion
and already-reviewed qualification lines owned by Python. The lines cannot
change which reason is selected: they are attached only after structured facts
have made proof required. Silence is not positive evidence, and a required
reason without honest copy is refused rather than hidden.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import (FigureGrade, ProofEmphasis, ProofPresentation,
                     ProofReason)


def proof_presentation_from_evidence(
    *,
    grade: FigureGrade | str | None,
    exactness: str | None,
    boundary: Mapping | None,
    record_ids: Sequence[str] | None,
    caveats: Sequence | None,
    freshness_confirmed: bool | None,
    mixed_vintage: bool | None,
    grade_qualification: str,
    inexact_qualification: str,
    missing_evidence_qualification: str,
    stale_qualification: str,
    mixed_vintage_qualification: str,
    boundary_qualifications: Sequence[str],
) -> ProofPresentation:
    """Return the compact-proof policy for structured evidence state.

    ``freshness_confirmed`` is deliberately a three-state fact.  ``True`` means
    the caller positively established that the evidence is current at the
    relevant boundary; ``False`` means it positively established staleness;
    ``None`` means the product has no structured staleness ruling.  The policy
    invents no age threshold to turn an evidence date into that ruling.
    ``mixed_vintage`` is the separate boolean already owned by composed ledger
    values and net-worth lines; it is never rediscovered from caveat copy.
    """
    reasons: list[ProofReason] = []

    def require(reason: ProofReason) -> None:
        if reason not in reasons:
            reasons.append(reason)

    try:
        evidence_grade = FigureGrade(grade) if grade is not None else None
    except (TypeError, ValueError):
        evidence_grade = None
    if evidence_grade is None:
        require(ProofReason.MISSING_EVIDENCE)
    elif evidence_grade is FigureGrade.CONFLICTED:
        require(ProofReason.CONFLICT)
    elif evidence_grade is FigureGrade.UNVERIFIED:
        require(ProofReason.UNCERTAIN_BASIS)

    if exactness == "rounded":
        require(ProofReason.INEXACT)
    elif exactness != "exact":
        require(ProofReason.MISSING_EVIDENCE)

    if not isinstance(caveats, Sequence) or isinstance(caveats, (str, bytes)):
        require(ProofReason.MISSING_EVIDENCE)
    elif caveats:
        require(ProofReason.CAVEAT)

    if boundary is None or not isinstance(boundary, Mapping):
        require(ProofReason.MISSING_EVIDENCE)
    elif not isinstance(boundary.get("whole"), bool):
        require(ProofReason.MISSING_EVIDENCE)
    elif (not boundary["whole"] or boundary.get("unmeasured")
          or boundary.get("unposted")):
        require(ProofReason.INCOMPLETE_COVERAGE)

    if not isinstance(record_ids, Sequence) or isinstance(record_ids, (str, bytes)):
        require(ProofReason.MISSING_EVIDENCE)
    elif (not record_ids or any(
        not isinstance(record_id, str) or not record_id.strip()
        for record_id in record_ids
    )):
        require(ProofReason.MISSING_EVIDENCE)

    if freshness_confirmed is False:
        require(ProofReason.STALE_BOUNDARY)
    elif freshness_confirmed is not True and mixed_vintage is not True:
        require(ProofReason.MISSING_EVIDENCE)

    if mixed_vintage is True:
        require(ProofReason.MIXED_VINTAGE)
    elif mixed_vintage is not False:
        require(ProofReason.MISSING_EVIDENCE)

    if reasons:
        copy_for = {
            ProofReason.CONFLICT: (grade_qualification,),
            ProofReason.UNCERTAIN_BASIS: (grade_qualification,),
            ProofReason.INEXACT: (inexact_qualification,),
            ProofReason.CAVEAT: caveats,
            ProofReason.STALE_BOUNDARY: (stale_qualification,),
            ProofReason.MIXED_VINTAGE: (mixed_vintage_qualification,),
            ProofReason.INCOMPLETE_COVERAGE: boundary_qualifications,
            ProofReason.MISSING_EVIDENCE: (missing_evidence_qualification,),
        }
        qualifications: list[str] = []
        for reason in reasons:
            lines = copy_for[reason]
            if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes)):
                raise ValueError(
                    f"required proof reason {reason.value} has no qualification")
            usable = tuple(
                line for line in lines
                if isinstance(line, str) and line.strip()
            )
            if not usable:
                raise ValueError(
                    f"required proof reason {reason.value} has no qualification")
            for line in usable:
                if line not in qualifications:
                    qualifications.append(line)
        return ProofPresentation(
            ProofEmphasis.REQUIRED, tuple(reasons), tuple(qualifications))
    return ProofPresentation(ProofEmphasis.ROUTINE)


def freshness_confirmed_on(evidence_dates: Sequence[str], read_on: str) -> bool | None:
    """Positive freshness only when every structured evidence day is the read day.

    An older day is not called stale: without a product-owned age policy it is
    an unknown freshness state.  This exact-equality case is the current real
    path by which freshness can be positively established without inventing a
    threshold or parsing a sentence.
    """
    dates = tuple(str(day or "").strip() for day in evidence_dates)
    current = str(read_on or "").strip()
    if not current or not dates or any(not day for day in dates):
        return None
    return True if all(day == current for day in dates) else None


__all__ = ["freshness_confirmed_on", "proof_presentation_from_evidence"]
