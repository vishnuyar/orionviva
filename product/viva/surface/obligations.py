"""Reviewed presentation contract for obligations and quiet findings."""

from __future__ import annotations

from .. import render
from ..persona import moment
from .models import FindingView, ObligationView, PanelState


_FINDING_COPY = {
    "possible_duplicate": (
        "finding_possible_duplicate_headline",
        "finding_possible_duplicate_explanation"),
    "amount_changed": (
        "finding_amount_changed_headline",
        "finding_amount_changed_explanation"),
    "expected_outflow_missing": (
        "finding_expected_outflow_missing_headline",
        "finding_expected_outflow_missing_explanation"),
    "income_interrupted": (
        "finding_income_interrupted_headline",
        "finding_income_interrupted_explanation"),
    "fee_observed": (
        "finding_fee_observed_headline",
        "finding_fee_observed_explanation"),
    "recurring_obligation": (
        "finding_recurring_obligation_headline",
        "finding_recurring_obligation_explanation"),
}


def _evidence_ids(projection, record_ids) -> tuple[str, ...]:
    documents = set(projection.captured_docs())
    return tuple(record_id for record_id in record_ids if record_id in documents)


def _obligation(projection, row, locale: str) -> ObligationView:
    low = render.money(row.amount_min, row.currency, locale=locale)
    high = render.money(row.amount_max, row.currency, locale=locale)
    headline = moment(
        "obligation_due" if row.status == "due" else "obligation_expected",
        subject=row.subject, date=render.date(row.expected_date))
    explanation = (moment("obligation_amount_exact", amount=low)
                   if row.exact else
                   moment("obligation_amount_range", low=low, high=high))
    coverage = moment("obligation_coverage", count=render.count(row.count),
                      first=render.date(row.dated_from),
                      last=render.date(row.dated_to))
    caveats = tuple(moment("obligation_measured_caveat")
                    if caveat == "measured_not_confirmed" else
                    moment("obligation_observed_caveat")
                    if caveat == "observed_prior_only" else caveat
                    for caveat in row.caveats)
    return ObligationView(
        id=row.id, subject=row.subject, cadence=row.cadence,
        expected_date=row.expected_date, status=row.status, basis=row.basis,
        amount_display=str(low if row.exact else f"{low} – {high}"),
        amount_min=str(row.amount_min), amount_max=str(row.amount_max),
        currency=row.currency, grade=row.grade, headline=headline,
        explanation=explanation, coverage=coverage,
        record_ids=row.record_ids,
        evidence_ids=_evidence_ids(projection, row.record_ids),
        account_ids=row.account_ids, caveats=caveats,
        required_visibility=bool(caveats or row.grade in ("", "unverified", "conflicted")),
        actions=(("inspect", "ask_viva") if row.record_ids else ("ask_viva",)))


def _finding(projection, row, locale: str) -> FindingView:
    headline_key, explanation_key = _FINDING_COPY[row.kind]
    fields = {"subject": row.subject}
    if row.expected_date:
        fields["date"] = render.date(row.expected_date)
    if row.prior_amount is not None:
        fields["prior"] = render.money(row.prior_amount, row.currency, locale=locale)
    if row.current_amount is not None:
        fields["current"] = render.money(row.current_amount, row.currency,
                                          locale=locale)
    headline = moment(headline_key, **fields)
    explanation = moment(explanation_key, **fields)
    coverage = moment("finding_coverage",
                      count=render.count(row.stake.get("count", 0)),
                      last=render.date(row.dated))
    return FindingView(
        id=row.id, kind=row.kind, subject=row.subject,
        importance=row.importance,
        amount_display=str(render.money(row.amount, row.currency, locale=locale)),
        exact_value=str(row.amount), currency=row.currency, dated=row.dated,
        headline=headline, explanation=explanation, coverage=coverage,
        record_ids=row.record_ids,
        evidence_ids=_evidence_ids(projection, row.record_ids),
        account_ids=row.account_ids,
        actions=(("inspect", "ask_viva", "set_aside") if row.record_ids
                 else ("ask_viva", "set_aside")))


def utility(projection, locale: str, today: str, finding_limit: int = 3) -> dict:
    """The whole utility block; absence is explicit and renders nothing."""
    obligation_rows = [_obligation(projection, row, locale)
                       for row in projection.obligations(today)]
    all_findings = projection.findings(today)
    finding_rows = [_finding(projection, row, locale)
                    for row in all_findings[:finding_limit]]
    return {
        "state": (PanelState.READY if obligation_rows or finding_rows
                  else PanelState.ABSENT).value,
        "obligations": [row.as_dict() for row in obligation_rows],
        "findings": [row.as_dict() for row in finding_rows],
        "finding_count": len(all_findings),
    }


__all__ = ["utility"]
