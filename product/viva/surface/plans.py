"""Reviewed GoalsAndPlans.v1 read model; the desktop only renders it."""

from __future__ import annotations

from decimal import Decimal

from .. import render
from ..persona import STOOD_BEHIND_MOMENT, moment
from .models import (Citation, CitationRelation, GoalAccountView,
                     GoalHistoryView, GoalPlanView, GoalProposalView)


_EXCLUSIONS = {
    "account_not_depository": "plans_exclusion_not_depository",
    "account_not_issuer": "plans_exclusion_not_issuer",
    "account_currency_unstated": "plans_exclusion_currency",
    "account_currency_differs": "plans_exclusion_currency",
    "account_balance_conflicted": "plans_exclusion_conflicted",
}


def _account(projection, row, locale: str) -> GoalAccountView:
    record_id = row.provenance.doc_id
    documents = projection.captured_docs()
    evidence = (record_id,) if record_id and record_id in documents else ()
    citations = tuple(Citation(
        document_id=item,
        label=projection.captured_filenames().get(item, ""),
        page=str(row.provenance.page or ""),
        relation=CitationRelation.ATTESTS) for item in evidence)
    return GoalAccountView(
        id=row.account_id, name=row.name, currency=row.currency,
        eligible=True, balance=str(row.balance),
        balance_display=render.money(row.balance, row.currency, locale=locale),
        reserved=str(row.reserved),
        reserved_display=render.money(row.reserved, row.currency, locale=locale),
        available=str(row.available),
        available_display=render.money(row.available, row.currency, locale=locale),
        grade=row.grade,
        grade_description=moment(STOOD_BEHIND_MOMENT + row.grade),
        dated=row.dated, as_of=str(row.as_of or ""),
        balance_explanation=row.explanation,
        source_document_id=record_id,
        source_page=str(row.provenance.page or ""),
        source_region=row.provenance.region,
        source_note=row.provenance.note,
        caveats=(row.explanation,) if row.explanation else (),
        sentence=moment(
            "plans_account_available",
            balance=render.money(row.balance, row.currency, locale=locale),
            reserved=render.money(row.reserved, row.currency, locale=locale),
            available=render.money(row.available, row.currency, locale=locale)),
        evidence_ids=evidence, citations=citations)


def _excluded(row) -> GoalAccountView:
    return GoalAccountView(
        id=row.account_id, name=row.name, currency=row.currency,
        eligible=False, reason=row.reason,
        sentence=moment(_EXCLUSIONS[row.reason]))


def _history(row, currency: str, locale: str) -> GoalHistoryView:
    amount = row.applied_amount
    return GoalHistoryView(
        kind=row.kind, account_id=row.account_id, amount=str(amount),
        amount_display=render.money(amount, currency, locale=locale),
        reason=row.reason, occurred_at=row.occurred_at,
        sentence=moment(
            "plans_history_reserved" if row.kind == "reserved"
            else "plans_history_released",
            amount=render.money(amount, currency, locale=locale)),
        valid=row.valid)


def _actions(row) -> tuple[str, ...]:
    if row.state == "set_aside":
        return ()
    actions = ["change_terms"]
    if row.state == "active":
        actions.append("pause")
    elif row.state == "paused":
        actions.append("resume")
    if row.available_accounts and row.state != "set_aside":
        actions.append("reserve")
    if row.reserved:
        actions.append("release")
    elif row.state != "set_aside":
        actions.append("set_aside")
    return tuple(actions)


def _goal(projection, row, locale: str) -> GoalPlanView:
    monthly = row.monthly_contribution
    required = row.required_monthly
    deviation = row.deviation
    group = "complete" if row.status == "complete" else row.state
    accounts = tuple(_account(projection, item, locale)
                     for item in row.available_accounts)
    accounts += tuple(_excluded(item) for item in row.exclusions)
    return GoalPlanView(
        id=row.goal_id, title=row.title, group=group, state=row.state,
        status=row.status, status_label=moment("plans_status_" + row.status),
        headline=moment("plans_goal_headline"),
        explanation=moment("plans_goal_explanation"), currency=row.currency,
        target_amount=str(row.target_amount),
        target_display=render.money(
            row.target_amount, row.currency, locale=locale),
        target_date=row.target_date, reserved=str(row.reserved),
        reserved_display=render.money(row.reserved, row.currency, locale=locale),
        remaining=str(row.remaining),
        remaining_display=render.money(
            row.remaining, row.currency, locale=locale),
        monthly_contribution=str(monthly) if monthly is not None else "",
        monthly_display=(render.money(monthly, row.currency, locale=locale)
                         if monthly is not None else ""),
        contribution_day=row.contribution_day,
        required_monthly=str(required) if required is not None else "",
        required_monthly_display=(
            render.money(required, row.currency, locale=locale)
            if required is not None else ""),
        projected_completion_date=row.projected_completion_date,
        deviation=str(deviation) if deviation is not None else "",
        deviation_display=(render.money(
            deviation, row.currency, locale=locale)
            if deviation is not None else ""),
        next_contribution_date=row.next_contribution_date,
        no_money_moved=moment("plans_local_reservation"),
        accounts=accounts,
        history=tuple(_history(item, row.currency, locale)
                      for item in row.history),
        history_note=(moment("plans_history_withheld") if row.issues else ""),
        assumptions=(moment("plans_goal_explanation"),),
        caveats=((moment("plans_history_withheld"),) if row.issues else ()),
        event_ids=row.event_ids,
        actions=_actions(row))


def _proposal(projection, row: dict, locale: str, today: str) -> GoalProposalView:
    exact = dict(row.get("proposal") or {})
    verb = str(row.get("verb") or "")
    currency = str(exact.get("currency") or "")
    goal = None
    if not currency and exact.get("goal_id"):
        try:
            goal = projection.goal(str(exact["goal_id"]), today)
            currency = goal.currency
        except KeyError:
            currency = ""
    amount_text = exact.get("target_amount") \
        if verb in ("create", "change_terms") else exact.get("amount")
    fields = {}
    if amount_text not in (None, ""):
        fields["amount"] = render.money(
            Decimal(str(amount_text)), currency, locale=locale)
    display = {}
    title = str(exact.get("title") or getattr(goal, "title", ""))
    if title:
        display["plan_name"] = title
    account_id = str(exact.get("account_id") or "")
    if goal is not None and account_id:
        accounts = (*goal.available_accounts, *goal.exclusions)
        account = next((item for item in accounts
                        if item.account_id == account_id), None)
        if account is not None:
            display["account_name"] = account.name
    if exact.get("target_amount") not in (None, ""):
        display["target_amount"] = render.money(
            Decimal(str(exact["target_amount"])), currency, locale=locale)
    if exact.get("amount") not in (None, ""):
        display["amount"] = render.money(
            Decimal(str(exact["amount"])), currency, locale=locale)
    if exact.get("monthly_contribution") not in (None, ""):
        display["monthly_contribution"] = render.money(
            Decimal(str(exact["monthly_contribution"])), currency,
            locale=locale)
    for name in ("target_date", "contribution_day"):
        if exact.get(name) not in (None, ""):
            display[name] = str(exact[name])
    return GoalProposalView(
        id=str(row.get("proposal_id") or ""), verb=verb,
        goal_id=str(exact.get("goal_id") or ""),
        summary=moment("plans_proposal_" + verb, **fields),
        consequence=moment("plans_proposal_consequence"),
        no_money_moved=moment("plans_local_reservation"), exact=exact,
        display=display,
        assumptions=(moment("plans_goal_explanation"),))


def plans(projection, locale: str, today: str) -> dict:
    """Compose the durable plan workspace from one projection read."""
    goals = tuple(_goal(projection, row, locale)
                  for row in projection.goals(today))
    proposals = tuple(_proposal(projection, row, locale, today)
                      for row in projection.open_goal_proposals())
    if not goals and not proposals:
        state = "absent"
    elif any(row.caveats for row in goals):
        state = "partial"
    else:
        state = "ready"
    return {
        "state": state, "title": moment("plans_title"),
        "invitation": {
            "title": moment("plans_empty_title"),
            "body": moment("plans_empty_body"),
        },
        "no_money_moved": moment("plans_local_reservation"),
        "goals": [row.as_dict() for row in goals],
        "groups": {
            group: [row.id for row in goals if row.group == group]
            for group in ("active", "paused", "complete", "set_aside")
        },
        "proposals": [row.as_dict() for row in proposals],
        "actions": ["draft", "propose", "confirm", "decline"],
    }


__all__ = ["plans"]
