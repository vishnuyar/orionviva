"""Save-up goals: intended terms, local reservations and calendar math."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_CEILING

from ..events import CONFLICTED, ISSUED, Provenance
from . import balances as balances_view

MONEY_SCALE = Decimal("0.01")

class UnknownGoalError(KeyError):
    """Asked for a goal identity the ledger has never recorded."""


@dataclass(frozen=True)
class GoalAccountAvailability:
    account_id: str
    name: str
    currency: str
    balance: Decimal
    reserved: Decimal
    available: Decimal
    grade: str
    dated: str
    as_of: str | None
    provenance: Provenance
    explanation: str


@dataclass(frozen=True)
class GoalAccountExclusion:
    account_id: str
    name: str
    currency: str
    reason: str


@dataclass(frozen=True)
class GoalActivity:
    kind: str
    account_id: str
    amount: Decimal
    applied_amount: Decimal
    reason: str
    occurred_at: str
    event_id: str
    proposal_id: str
    valid: bool


@dataclass(frozen=True)
class GoalView:
    goal_id: str
    kind: str
    title: str
    state: str
    status: str
    currency: str
    target_amount: Decimal
    target_date: str
    monthly_contribution: Decimal | None
    contribution_day: int | None
    reserved: Decimal
    remaining: Decimal
    reservations: tuple[tuple[str, Decimal], ...]
    required_monthly: Decimal | None
    projected_completion_date: str
    deviation: Decimal | None
    next_contribution_date: str
    available_accounts: tuple[GoalAccountAvailability, ...]
    exclusions: tuple[GoalAccountExclusion, ...]
    history: tuple[GoalActivity, ...]
    issues: tuple[str, ...]
    event_ids: tuple[str, ...]
    created_at: str
    updated_at: str


def _read_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ValueError("goals require an ISO read date") from None


def _target_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise ValueError("goal target date is not an ISO calendar date") from None


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def contribution_dates(today: str, contribution_day: int,
                       *, through: str = "", limit: int | None = None) \
        -> tuple[str, ...]:
    """Monthly occurrences on days every calendar month owns."""
    if not isinstance(contribution_day, int) or isinstance(contribution_day, bool) \
            or not 1 <= contribution_day <= 28:
        raise ValueError("contribution day must be from 1 to 28")
    start = _read_date(today)
    end = _target_date(through)
    if end is None and (not isinstance(limit, int) or limit < 1):
        raise ValueError("an open contribution schedule requires a positive limit")
    year, month = start.year, start.month
    out = []
    while year <= 9999:
        candidate = date(year, month, contribution_day)
        if candidate < start:
            year, month = _next_month(year, month)
            continue
        if end is not None and candidate > end:
            break
        out.append(candidate.isoformat())
        year, month = _next_month(year, month)
        if limit is not None and len(out) >= limit:
            break
    return tuple(out)


def _nth_contribution(today: str, contribution_day: int, occurrence: int) -> str:
    first = _read_date(contribution_dates(
        today, contribution_day, limit=1)[0])
    offset = occurrence - 1
    absolute_month = first.year * 12 + first.month - 1 + offset
    year, month_index = divmod(absolute_month, 12)
    if year > 9999:
        return ""
    return date(year, month_index + 1, contribution_day).isoformat()


def _ceil_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_SCALE, rounding=ROUND_CEILING)


def reserved_by_account(core) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for goal in core._goals.values():
        for account_id, amount in goal.get("reservations", {}).items():
            totals[account_id] = totals.get(account_id, Decimal("0")) + amount
    return totals


def account_stake(core, account_id: str, currency: str) -> dict:
    """Exact current reservation basis, even when the account is excluded."""
    account = core._acct.get(account_id)
    if account is None or not account.seen:
        return {"account_id": account_id, "present": False}
    answer = balances_view.balance(core, account_id)
    held = reserved_by_account(core).get(account_id, Decimal("0"))
    reason = ("account_not_depository" if account.kind != "depository" else
              "account_not_issuer" if account.origin != ISSUED else
              "account_currency_unstated" if not account.currency else
              "account_currency_differs" if account.currency != currency else
              "account_balance_conflicted" if answer.grade == CONFLICTED else "")
    return {
        "account_id": account_id, "present": True,
        "eligible": not reason, "exclusion_reason": reason,
        "balance": str(answer.amount), "currency": account.currency,
        "grade": answer.grade, "dated": answer.dated, "as_of": answer.as_of,
        "record_id": answer.provenance.doc_id,
        "reserved": str(held),
        "available": str(max(answer.amount - held, Decimal("0"))),
    }


def _availability(core, currency: str) -> tuple[
        tuple[GoalAccountAvailability, ...], tuple[GoalAccountExclusion, ...]]:
    reserved = reserved_by_account(core)
    available = []
    excluded = []
    for account_id in sorted(core._acct):
        account = core._acct[account_id]
        if not account.seen or account.kind not in (
                "depository", "liability", "investment"):
            continue
        reason = ("account_not_depository" if account.kind != "depository" else
                  "account_not_issuer" if account.origin != ISSUED else
                  "account_currency_unstated" if not account.currency else
                  "account_currency_differs" if account.currency != currency else "")
        answer = balances_view.balance(core, account_id)
        if not reason and answer.grade == CONFLICTED:
            reason = "account_balance_conflicted"
        if reason:
            excluded.append(GoalAccountExclusion(
                account_id, account.name, account.currency, reason))
            continue
        held = reserved.get(account_id, Decimal("0"))
        free = max(answer.amount - held, Decimal("0"))
        available.append(GoalAccountAvailability(
            account_id=account_id, name=account.name,
            currency=account.currency, balance=answer.amount,
            reserved=held, available=free, grade=answer.grade,
            dated=answer.dated, as_of=answer.as_of,
            provenance=answer.provenance,
            explanation=answer.explanation))
    return tuple(available), tuple(excluded)


def plan_math(row: dict, today: str) -> dict:
    target = Decimal(row["target_amount"])
    reserved = sum(row.get("reservations", {}).values(), Decimal("0"))
    remaining = max(target - reserved, Decimal("0"))
    monthly_text = row.get("monthly_contribution", "")
    monthly = Decimal(monthly_text) if monthly_text else None
    day = row.get("contribution_day")
    target_on = _target_date(row.get("target_date", ""))
    occurrences = contribution_dates(today, day, through=target_on.isoformat()) \
        if day is not None and target_on is not None else ()
    required = (_ceil_money(remaining / len(occurrences))
                if target_on is not None and occurrences and remaining else
                Decimal("0") if target_on is not None and not remaining else None)
    projected = ""
    if monthly is not None and day is not None and remaining:
        count = int((remaining / monthly).to_integral_value(
            rounding=ROUND_CEILING))
        projected = _nth_contribution(today, day, count)
    elif not remaining:
        projected = today[:10]
    read_on = _read_date(today)
    if not remaining:
        status = "complete"
    elif row.get("state") == "paused":
        status = "paused"
    elif target_on is not None and target_on < read_on:
        status = "at_risk"
    elif monthly is None:
        status = "unscheduled"
    elif target_on is None:
        status = "on_track"
    elif not projected or projected > target_on.isoformat():
        status = "at_risk"
    else:
        later_occurrence = any(
            occurrence > projected for occurrence in occurrences)
        status = "ahead" if later_occurrence else "on_track"
    deviation = monthly - required \
        if monthly is not None and required is not None else None
    upcoming = contribution_dates(today, day, limit=1)[0] \
        if monthly is not None and day is not None else ""
    return {"reserved": reserved, "remaining": remaining,
            "required": required, "projected": projected,
            "status": status, "deviation": deviation, "next": upcoming}


def goals(core, today: str) -> list[GoalView]:
    views = []
    for goal_id in sorted(core._goals):
        row = core._goals[goal_id]
        math = plan_math(row, today)
        available, excluded = _availability(core, row.get("currency", ""))
        monthly_text = row.get("monthly_contribution", "")
        history = tuple(GoalActivity(
            kind=item.get("kind", ""), account_id=item.get("account_id", ""),
            amount=Decimal(item.get("amount", "0")),
            applied_amount=Decimal(item.get("applied_amount", item.get("amount", "0"))),
            reason=item.get("reason", ""), occurred_at=item.get("occurred_at", ""),
            event_id=item.get("event_id", ""),
            proposal_id=item.get("proposal_id", ""),
            valid=bool(item.get("valid", True)))
            for item in row.get("reservation_history", []))
        views.append(GoalView(
            goal_id=goal_id, kind=row.get("kind", ""),
            title=row.get("title", ""), state=row.get("state", "active"),
            status=math["status"], currency=row.get("currency", ""),
            target_amount=Decimal(row["target_amount"]),
            target_date=row.get("target_date", ""),
            monthly_contribution=(Decimal(monthly_text) if monthly_text else None),
            contribution_day=row.get("contribution_day"),
            reserved=math["reserved"], remaining=math["remaining"],
            reservations=tuple(sorted(row.get("reservations", {}).items())),
            required_monthly=math["required"],
            projected_completion_date=math["projected"],
            deviation=math["deviation"], next_contribution_date=math["next"],
            available_accounts=available, exclusions=excluded,
            history=history, issues=tuple(row.get("issues", [])),
            event_ids=tuple(row.get("event_ids", [])),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", "")))
    return views


def goal(core, goal_id: str, today: str) -> GoalView:
    found = next((row for row in goals(core, today) if row.goal_id == goal_id), None)
    if found is None:
        raise UnknownGoalError(goal_id)
    return found


def goal_proposals(core, *, open_only: bool = False) -> list[dict]:
    rows = list(core._goal_proposals.values())
    if open_only:
        rows = [row for row in rows if row.get("status") == "open"]
    return copy.deepcopy(rows)


def goal_proposal(core, proposal_id: str) -> dict | None:
    found = core._goal_proposals.get(proposal_id)
    return copy.deepcopy(found) if found is not None else None


def open_goal_proposals(core) -> list[dict]:
    return goal_proposals(core, open_only=True)


__all__ = [
    "GoalAccountAvailability", "GoalAccountExclusion", "GoalActivity",
    "GoalView", "MONEY_SCALE", "UnknownGoalError", "account_stake",
    "contribution_dates", "goal", "goal_proposal", "goal_proposals", "goals",
    "open_goal_proposals", "plan_math", "reserved_by_account",
]
