"""Project bounded current-period balances from qualified ledger evidence.

Issuer-backed depository balances start each currency slice. Qualified
recurring money changes it; missing plans and goals remain explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ..events import ISSUED
from ..streams import IN
from . import balances as balances_view
from . import obligations as obligations_view
from .core import ProjectionCore, _grade_rank
from .rhythm import rhythm_hypotheses


DEFAULT_HORIZON_DAYS = 30
CURRENT_PERIOD_VERSION = "current-period-v1"


@dataclass(frozen=True)
class ProjectionStep:
    date: str
    kind: str
    subject: str
    amount_min: Decimal
    amount_max: Decimal
    balance_min: Decimal
    balance_max: Decimal
    evidence_dates: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectionExclusion:
    kind: str
    identity: str
    reason: str
    currency: str = ""
    evidence_dates: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CurrentPeriodCompleteness:
    balances: bool
    income: bool
    obligations: bool
    planned_spending: bool
    goals: bool


@dataclass(frozen=True)
class CurrentPeriodSlice:
    currency: str
    horizon_start: str
    horizon_end: str
    liquid_balance: Decimal
    expected_income_min: Decimal
    expected_income_max: Decimal
    obligations_min: Decimal
    obligations_max: Decimal
    remainder_min: Decimal
    remainder_max: Decimal
    grade: str
    evidence_dates: tuple[str, ...]
    record_ids: tuple[str, ...]
    account_ids: tuple[str, ...]
    steps: tuple[ProjectionStep, ...]
    assumptions: tuple[str, ...]
    caveats: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    completeness: CurrentPeriodCompleteness
    exclusions: tuple[ProjectionExclusion, ...]


@dataclass(frozen=True)
class CurrentPeriodResult:
    horizon_start: str
    horizon_end: str
    slices: tuple[CurrentPeriodSlice, ...]
    excluded_accounts: tuple[str, ...] = ()
    exclusions: tuple[ProjectionExclusion, ...] = ()
    refusal_reason: str = ""

    @property
    def refused(self) -> bool:
        return bool(self.refusal_reason)


@dataclass(frozen=True)
class _Expected:
    kind: str
    subject: str
    date: str
    amount_min: Decimal
    amount_max: Decimal
    currency: str
    grade: str
    evidence_dates: tuple[str, ...]
    record_ids: tuple[str, ...]
    account_ids: tuple[str, ...]


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        raise ValueError("current period requires an ISO read date") from None


def _weakest(grades) -> str:
    present = [grade for grade in grades if grade]
    return min(present, key=_grade_rank) if present else ""


def _evidence_dates(rows) -> tuple[str, ...]:
    return tuple(sorted({row.date[:10] for row in rows if row.date}))


def _incoming(core: ProjectionCore, today: date, end: date) \
        -> tuple[list[_Expected], list[ProjectionExclusion]]:
    """The next unmissed qualified incoming occurrence in the horizon."""
    out = []
    exclusions = []
    for hypothesis in rhythm_hypotheses(core):
        if hypothesis.direction != IN:
            continue
        rows = obligations_view._movement_rows(core, hypothesis.movements)
        shape = obligations_view._shape(hypothesis, rows, today)
        dates = _evidence_dates(rows)
        records = obligations_view._records(rows)
        accounts = obligations_view._accounts(rows)
        if shape is None or not shape["qualified"]:
            exclusions.append(ProjectionExclusion(
                kind="income", identity=hypothesis.subject,
                reason="incoming_not_qualified", currency=hypothesis.currency,
                evidence_dates=dates, record_ids=records,
                account_ids=accounts))
            continue
        if not shape["adequate"] or shape["expected"] < today:
            exclusions.append(ProjectionExclusion(
                kind="income", identity=hypothesis.subject,
                reason="incoming_interrupted", currency=hypothesis.currency,
                evidence_dates=dates, record_ids=records,
                account_ids=accounts))
            continue
        if shape["expected"] > end:
            continue
        out.append(_Expected(
            kind="income", subject=hypothesis.merchant,
            date=shape["expected"].isoformat(),
            amount_min=min(shape["amounts"]),
            amount_max=max(shape["amounts"]), currency=hypothesis.currency,
            grade=obligations_view._weakest(core, rows),
            evidence_dates=dates, record_ids=records,
            account_ids=accounts))
    return out, exclusions


def _outgoing(core: ProjectionCore, today: date, end: date) \
        -> tuple[list[_Expected], list[ProjectionExclusion]]:
    out = []
    exclusions = []
    for row in obligations_view.obligations(core, today.isoformat()):
        # An observed prior licenses context but not current-period arithmetic.
        if row.basis == "observed":
            exclusions.append(ProjectionExclusion(
                kind="obligation", identity=row.id,
                reason="obligation_not_qualified", currency=row.currency,
                evidence_dates=(row.dated_from, row.dated_to),
                record_ids=row.record_ids, account_ids=row.account_ids))
            continue
        if _date(row.expected_date) > end:
            continue
        out.append(_Expected(
            # A still-adequate past-due item affects the starting day. Keeping
            # its old expected day as a chart point would put a future series
            # before its own starting balance.
            kind="obligation", subject=row.subject,
            date=max(row.expected_date, today.isoformat()),
            amount_min=row.amount_min, amount_max=row.amount_max,
            currency=row.currency, grade=row.grade,
            evidence_dates=(row.dated_from, row.dated_to),
            record_ids=row.record_ids, account_ids=row.account_ids))
    return out, exclusions


def current_period(core: ProjectionCore, today: str,
                   horizon_days: int = DEFAULT_HORIZON_DAYS) -> CurrentPeriodResult:
    """Project qualified recurring money over issuer depository balances.

    The lower bound assumes expected income does not arrive and every qualified
    obligation lands at its observed maximum.  The upper bound includes every
    qualified income maximum and each obligation minimum.  Neither bound is
    treated as spend permission: plans and goals are explicitly unrepresented.
    """
    start = _date(today)
    if not isinstance(horizon_days, int) or isinstance(horizon_days, bool) \
            or horizon_days < 1 or horizon_days > 366:
        raise ValueError("current-period horizon must be 1 to 366 calendar days")
    end = start + timedelta(days=horizon_days)

    by_currency: dict[str, dict] = {}
    exclusions: list[ProjectionExclusion] = []
    for account in sorted(core._acct):
        state = core._acct[account]
        if not state.seen:
            continue
        if state.kind not in ("depository", "liability", "investment"):
            continue
        reason = ("account_not_depository" if state.kind != "depository" else
                  "account_not_issuer" if state.origin != ISSUED else
                  "account_currency_unstated" if not state.currency else "")
        if reason:
            exclusions.append(ProjectionExclusion(
                kind="account", identity=account, reason=reason,
                currency=state.currency or "", account_ids=(account,)))
            continue
        answer = balances_view.balance(core, account)
        bucket = by_currency.setdefault(state.currency, {
            "balance": Decimal("0"), "grades": [], "dates": set(),
            "records": set(), "accounts": set(), "balance_records": set(),
            "balance_accounts": set(), "balance_dates": set(),
            "caveats": [],
        })
        bucket["balance"] += answer.amount
        bucket["grades"].append(answer.grade)
        bucket["accounts"].add(account)
        bucket["balance_accounts"].add(account)
        if answer.dated:
            bucket["dates"].add(answer.dated[:10])
            bucket["balance_dates"].add(answer.dated[:10])
            if answer.dated[:10] != start.isoformat():
                bucket["caveats"].append("balance_freshness_unconfirmed")
        else:
            bucket["caveats"].append("balance_undated")
        if answer.grade == "conflicted":
            bucket["caveats"].append("balance_conflicted")
        if answer.provenance.doc_id:
            bucket["records"].add(answer.provenance.doc_id)
            bucket["balance_records"].add(answer.provenance.doc_id)

    if not by_currency:
        return CurrentPeriodResult(
            horizon_start=start.isoformat(), horizon_end=end.isoformat(),
            slices=(),
            excluded_accounts=tuple(row.identity for row in exclusions
                                    if row.kind == "account"),
            exclusions=tuple(exclusions),
            refusal_reason="no_eligible_liquid_balance")

    incoming, incoming_exclusions = _incoming(core, start, end)
    outgoing, outgoing_exclusions = _outgoing(core, start, end)
    exclusions.extend(incoming_exclusions)
    exclusions.extend(outgoing_exclusions)
    expected = incoming + outgoing
    for item in expected:
        if item.currency not in by_currency:
            continue
        bucket = by_currency[item.currency]
        bucket.setdefault("expected", []).append(item)
        bucket["grades"].append(item.grade)
        bucket["records"].update(item.record_ids)
        bucket["accounts"].update(item.account_ids)
        bucket["dates"].update(item.evidence_dates)

    slices = []
    for currency, bucket in sorted(by_currency.items()):
        relevant_exclusions = tuple(
            row for row in exclusions
            if not row.currency or row.currency == currency)
        if any(row.reason == "incoming_interrupted"
               for row in relevant_exclusions):
            bucket["caveats"].append("income_interrupted")
        running_low = running_high = bucket["balance"]
        income_max = obligation_min = obligation_max = Decimal("0")
        steps = [ProjectionStep(
            date=start.isoformat(), kind="balance", subject="liquid balance",
            amount_min=bucket["balance"], amount_max=bucket["balance"],
            balance_min=running_low, balance_max=running_high,
            evidence_dates=tuple(sorted(bucket["balance_dates"])),
            record_ids=tuple(sorted(bucket["balance_records"])),
            account_ids=tuple(sorted(bucket["balance_accounts"])))]
        rows = sorted(bucket.get("expected", []),
                      key=lambda row: (row.date, row.kind, row.subject))
        for row in rows:
            if row.kind == "income":
                income_max += row.amount_max
                running_high += row.amount_max
            else:
                obligation_min += row.amount_min
                obligation_max += row.amount_max
                running_low -= row.amount_max
                running_high -= row.amount_min
            steps.append(ProjectionStep(
                date=row.date, kind=row.kind, subject=row.subject,
                amount_min=row.amount_min, amount_max=row.amount_max,
                balance_min=running_low, balance_max=running_high,
                evidence_dates=row.evidence_dates,
                record_ids=row.record_ids, account_ids=row.account_ids))

        slices.append(CurrentPeriodSlice(
            currency=currency, horizon_start=start.isoformat(),
            horizon_end=end.isoformat(), liquid_balance=bucket["balance"],
            expected_income_min=Decimal("0"),
            expected_income_max=income_max,
            obligations_min=obligation_min,
            obligations_max=obligation_max,
            remainder_min=running_low, remainder_max=running_high,
            grade=_weakest(bucket["grades"]),
            evidence_dates=tuple(sorted(bucket["dates"])),
            record_ids=tuple(sorted(bucket["records"])),
            account_ids=tuple(sorted(bucket["accounts"])), steps=tuple(steps),
            assumptions=("rolling_30_day_horizon" if horizon_days == 30
                         else "caller_supplied_horizon",
                         "expected_income_not_guaranteed",
                         "qualified_recurring_money_only"),
            caveats=tuple(sorted(set(bucket["caveats"]))),
            missing_inputs=("planned_spending", "goal_contributions"),
            completeness=CurrentPeriodCompleteness(
                balances=not any(row.kind == "account"
                                 for row in relevant_exclusions),
                income=not any(row.kind == "income"
                               for row in relevant_exclusions),
                obligations=not any(row.kind == "obligation"
                                    for row in relevant_exclusions),
                planned_spending=False, goals=False),
            exclusions=relevant_exclusions))

    return CurrentPeriodResult(
        horizon_start=start.isoformat(), horizon_end=end.isoformat(),
        slices=tuple(slices),
        excluded_accounts=tuple(row.identity for row in exclusions
                                if row.kind == "account"),
        exclusions=tuple(exclusions))


__all__ = [
    "CURRENT_PERIOD_VERSION", "DEFAULT_HORIZON_DAYS",
    "CurrentPeriodCompleteness", "CurrentPeriodResult", "CurrentPeriodSlice",
    "ProjectionExclusion", "ProjectionStep", "current_period",
]
