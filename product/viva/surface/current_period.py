"""Reviewed current-period control, including backend-authored chart copy."""

from __future__ import annotations

from .. import render
from ..persona import STOOD_BEHIND_MOMENT, moment
from .models import (Citation, CitationRelation, CurrentPeriodCompletenessView,
                     CurrentPeriodExclusionView, CurrentPeriodSliceView,
                     CurrentPeriodStepView, FigureGrade)
from .proof import freshness_confirmed_on, proof_presentation_from_evidence


_ASSUMPTIONS = {
    "rolling_30_day_horizon": "current_period_assumption_horizon",
    "caller_supplied_horizon": "current_period_assumption_horizon",
    "expected_income_not_guaranteed": "current_period_assumption_income",
    "qualified_recurring_money_only": "current_period_assumption_recurring",
}
_CAVEATS = {
    "balance_freshness_unconfirmed": "current_period_old_balance",
    "balance_undated": "current_period_undated_balance",
    "balance_conflicted": "current_period_conflicted_balance",
    "income_interrupted": "current_period_income_interrupted",
}
_EXCLUSIONS = {
    "account_not_depository": "current_period_exclusion_not_depository",
    "account_not_issuer": "current_period_exclusion_not_issuer",
    "account_currency_unstated": "current_period_exclusion_currency_unstated",
    "incoming_not_qualified": "current_period_exclusion_income_unqualified",
    "incoming_interrupted": "current_period_income_interrupted",
    "obligation_not_qualified": "current_period_exclusion_obligation_unqualified",
}


def _evidence_ids(projection, record_ids) -> tuple[str, ...]:
    documents = set(projection.captured_docs())
    return tuple(record_id for record_id in record_ids if record_id in documents)


def _citations(projection, record_ids) -> tuple[Citation, ...]:
    documents = set(projection.captured_docs())
    filenames = projection.captured_filenames()
    return tuple(Citation(
        document_id=record_id, label=filenames.get(record_id, ""),
        relation=CitationRelation.ATTESTS)
        for record_id in record_ids if record_id in documents)


def _exclusion(projection, row) -> CurrentPeriodExclusionView:
    return CurrentPeriodExclusionView(
        kind=row.kind, identity=row.identity, reason=row.reason,
        sentence=moment(_EXCLUSIONS[row.reason]), currency=row.currency,
        evidence_dates=row.evidence_dates, record_ids=row.record_ids,
        evidence_ids=_evidence_ids(projection, row.record_ids),
        account_ids=row.account_ids)


def _coverage_key(accounts: int, steps: int) -> str:
    return ("current_period_coverage_one_one" if accounts == 1 and steps == 1
            else "current_period_coverage_one_many" if accounts == 1
            else "current_period_coverage_many_one" if steps == 1
            else "current_period_coverage_many_many")


def _range(low, high, currency: str, locale: str) -> str:
    rendered_low = render.money(low, currency, locale=locale)
    rendered_high = render.money(high, currency, locale=locale)
    return f"{rendered_low} – {rendered_high}"


def _step(projection, row, currency: str, locale: str) -> CurrentPeriodStepView:
    amount = _range(row.amount_min, row.amount_max, currency, locale)
    balance = _range(row.balance_min, row.balance_max, currency, locale)
    fields = {
        "date": render.date(row.date), "amount": amount,
        "low": render.money(row.balance_min, currency, locale=locale),
        "high": render.money(row.balance_max, currency, locale=locale),
    }
    if row.kind != "balance":
        fields["subject"] = row.subject
    tooltip = moment(f"current_period_step_{row.kind}", **fields)
    return CurrentPeriodStepView(
        date=row.date, kind=row.kind, subject=row.subject,
        amount_display=amount, amount_min=str(row.amount_min),
        amount_max=str(row.amount_max), balance_display=balance,
        balance_min=str(row.balance_min), balance_max=str(row.balance_max),
        tooltip=tooltip, evidence_dates=row.evidence_dates,
        record_ids=row.record_ids,
        evidence_ids=_evidence_ids(projection, row.record_ids),
        account_ids=row.account_ids)


def _slice(projection, row, locale: str) -> CurrentPeriodSliceView:
    low = render.money(row.remainder_min, row.currency, locale=locale)
    high = render.money(row.remainder_max, row.currency, locale=locale)
    assumptions = tuple(moment(_ASSUMPTIONS[code]) for code in row.assumptions)
    caveats = [moment(_CAVEATS[code]) for code in row.caveats]
    if row.missing_inputs:
        caveats.append(moment("current_period_missing_plans"))
    exclusions = tuple(_exclusion(projection, item) for item in row.exclusions)
    for item in exclusions:
        if item.sentence not in caveats:
            caveats.append(item.sentence)
    series = tuple(_step(projection, point, row.currency, locale)
                   for point in row.steps)
    try:
        grade = FigureGrade(row.grade)
    except ValueError:
        grade = FigureGrade.UNVERIFIED
    grade_description = moment(STOOD_BEHIND_MOMENT + grade.value)
    whole = (all((row.completeness.balances, row.completeness.income,
                  row.completeness.obligations,
                  row.completeness.planned_spending,
                  row.completeness.goals)) and not row.exclusions)
    proof = proof_presentation_from_evidence(
        grade=grade, exactness="rounded",
        boundary={"whole": whole}, record_ids=row.record_ids,
        caveats=tuple(caveats),
        freshness_confirmed=freshness_confirmed_on(
            row.evidence_dates, row.horizon_start),
        mixed_vintage=len(set(row.evidence_dates)) > 1,
        grade_qualification=grade_description,
        inexact_qualification=moment("current_period_bounded_range"),
        missing_evidence_qualification=moment("proof_missing_evidence"),
        stale_qualification=moment("proof_stale_boundary"),
        mixed_vintage_qualification=moment("proof_mixed_vintage"),
        boundary_qualifications=tuple(caveats))
    account_count = len(row.steps[0].account_ids)
    step_count = max(len(row.steps) - 1, 0)
    return CurrentPeriodSliceView(
        id=f"current-period:{row.currency}", currency=row.currency,
        horizon_start=row.horizon_start, horizon_end=row.horizon_end,
        headline=moment("current_period_headline",
                        date=render.date(row.horizon_end), low=low, high=high),
        explanation=moment("current_period_explanation"),
        amount_display=_range(row.remainder_min, row.remainder_max,
                              row.currency, locale),
        liquid_balance=str(row.liquid_balance),
        expected_income_min=str(row.expected_income_min),
        expected_income_max=str(row.expected_income_max),
        obligations_min=str(row.obligations_min),
        obligations_max=str(row.obligations_max),
        remainder_min=str(row.remainder_min),
        remainder_max=str(row.remainder_max),
        coverage=moment(_coverage_key(account_count, step_count),
                        accounts=render.count(account_count),
                        steps=render.count(step_count)),
        grade=grade.value, grade_label=grade.value,
        grade_description=grade_description,
        proof_presentation=proof,
        evidence_label=moment("current_period_evidence_label",
                              currency=row.currency),
        evidence_heading=moment("current_period_evidence_heading",
                                currency=row.currency),
        assumptions=assumptions,
        caveats=tuple(caveats), missing_inputs=row.missing_inputs,
        completeness=CurrentPeriodCompletenessView(
            balances=row.completeness.balances,
            income=row.completeness.income,
            obligations=row.completeness.obligations,
            planned_spending=row.completeness.planned_spending,
            goals=row.completeness.goals),
        exclusions=exclusions, evidence_dates=row.evidence_dates,
        record_ids=row.record_ids,
        citations=_citations(projection, row.record_ids),
        evidence_ids=_evidence_ids(projection, row.record_ids),
        account_ids=row.account_ids, series=series)


def control(projection, locale: str, today: str) -> dict:
    """The whole block: absent, refused, ready, or limited by missing inputs."""
    result = projection.current_period(today)
    frame = {"title": moment("current_period_title"),
             "kicker": moment("current_period_kicker"),
             "exclusions": [
                 _exclusion(projection, row).as_dict()
                 for row in result.exclusions
             ]}
    if result.refused:
        if not projection.account_infos():
            return {**frame, "state": "absent", "horizon_start": result.horizon_start,
                    "horizon_end": result.horizon_end, "slices": [],
                    "refusal": ""}
        return {**frame, "state": "refused", "horizon_start": result.horizon_start,
                "horizon_end": result.horizon_end, "slices": [],
                "refusal": moment("current_period_refused")}
    slices = [_slice(projection, row, locale).as_dict() for row in result.slices]
    state = ("limited" if any(row.missing_inputs or not all((
        row.completeness.balances, row.completeness.income,
        row.completeness.obligations, row.completeness.planned_spending,
        row.completeness.goals)) for row in result.slices) else "ready")
    return {**frame, "state": state, "horizon_start": result.horizon_start,
            "horizon_end": result.horizon_end, "slices": slices,
            "refusal": ""}


__all__ = ["control"]
