"""Grounded obligations and deterministic quiet findings.

This module forecasts only from rhythms the ledger measured. Catalog knowledge
may license the relationship upstream, and a person's ruling may strengthen its
basis, but neither manufactures an interval, a date or an amount here.
"""

from __future__ import annotations

import hashlib
import calendar
import copy
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from ..streams import (FIXED_AMOUNT_CV, IN, MIN_FOR_CADENCE, OUT, Flow,
                       Occurrence, _as_date)
from . import categories as categories_view
from . import merchants as merchants_view
from . import movements as movements_view
from .core import ProjectionCore, _grade_rank
from .rhythm import rhythm_hypotheses


OBLIGATION_VERSION = "obligations-v1"
SUPPORTED_CADENCES = frozenset(("monthly", "annual"))
FINDING_KINDS = frozenset((
    "possible_duplicate", "amount_changed", "expected_outflow_missing",
    "income_interrupted", "fee_observed", "recurring_obligation",
))
_IMPORTANCE = {
    "income_interrupted": 6,
    "possible_duplicate": 5,
    "expected_outflow_missing": 4,
    "amount_changed": 3,
    "fee_observed": 2,
    "recurring_obligation": 1,
}


@dataclass(frozen=True)
class Obligation:
    id: str
    subject: str
    cadence: str
    expected_date: str
    amount_min: Decimal
    amount_max: Decimal
    currency: str
    basis: str
    status: str
    grade: str
    count: int
    dated_from: str
    dated_to: str
    record_ids: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()

    @property
    def exact(self) -> bool:
        return self.amount_min == self.amount_max


@dataclass(frozen=True)
class Finding:
    id: str
    kind: str
    subject: str
    importance: int
    amount: Decimal
    currency: str
    dated: str
    record_ids: tuple[str, ...]
    account_ids: tuple[str, ...]
    stake: dict = field(compare=False)
    expected_date: str = ""
    prior_amount: Decimal | None = None
    current_amount: Decimal | None = None

    def __post_init__(self) -> None:
        if self.kind not in FINDING_KINDS:
            raise ValueError(f"unknown finding kind: {self.kind!r}")


def _id(kind: str, subject: str) -> str:
    digest = hashlib.sha256(f"{kind}|{subject}".encode("utf-8")).hexdigest()[:20]
    return f"finding:{kind}:{digest}"


def _date(value: str) -> date | None:
    return _as_date(value)


def _advance(last: date, cadence: str, interval: int,
             anchor_day: int | None = None) -> date:
    """Advance a calendar rhythm without turning a month into 30 or 31 days."""
    if cadence == "monthly":
        year = last.year + (1 if last.month == 12 else 0)
        month = 1 if last.month == 12 else last.month + 1
        day = anchor_day or last.day
        return date(year, month, min(day, calendar.monthrange(year, month)[1]))
    if cadence == "annual":
        year = last.year + 1
        day = anchor_day or last.day
        return date(year, last.month,
                    min(day, calendar.monthrange(year, last.month)[1]))
    return last + timedelta(days=interval)


def _movement_rows(core: ProjectionCore, keys) -> list:
    by_key = {movement.key: movement for movement in movements_view.movements(core)}
    return [by_key[key] for key in keys if key in by_key]


def _records(rows) -> tuple[str, ...]:
    return tuple(sorted({row.key for row in rows}
                        | {row.provenance.doc_id for row in rows
                           if row.provenance.doc_id}))


def _accounts(rows) -> tuple[str, ...]:
    return tuple(sorted({row.account for row in rows if row.account}))


def _weakest(core: ProjectionCore, rows) -> str:
    grades = movements_view.movement_grades(core)
    present = [grades.get(row.key, "") for row in rows]
    present = [grade for grade in present if grade]
    return min(present, key=_grade_rank) if present else ""


def _shape(hypothesis, rows, today: date) -> dict | None:
    """The one component that can support an honestly qualified expectation."""
    currencies = {row.currency for row in rows if row.currency}
    if len(hypothesis.components) != 1 or len(currencies) != 1:
        return None
    dated = [(when, row) for row in rows
             if (when := _date(row.date)) is not None]
    dated.sort(key=lambda item: (item[0], item[1].key))
    if not dated:
        return None
    confirmed = tuple(period for period in hypothesis.confirmed
                      if period in SUPPORTED_CADENCES)
    measured = (hypothesis.measured and hypothesis.steady
                and hypothesis.cadence in SUPPORTED_CADENCES
                and hypothesis.count >= MIN_FOR_CADENCE
                and bool(hypothesis.interval_days))
    proposed = tuple(period for period in hypothesis.proposed
                     if period in SUPPORTED_CADENCES)
    # More than one confirmed or proposed cadence is not one forecast. A
    # person's single confirmed cadence outranks measurement; otherwise the
    # strong measurement speaks, and only then may a licensed prior support the
    # weaker "usually appears" row.
    cadence = (confirmed[0] if len(confirmed) == 1
               else hypothesis.cadence if measured
               else proposed[0] if len(proposed) == 1 else "")
    if not cadence:
        return None
    basis = ("confirmed" if len(confirmed) == 1 else
             "measured" if measured else "observed")
    qualified = basis in ("confirmed", "measured")
    if basis == "confirmed" and len(dated) < 2:
        # Confirmation can settle what the rhythm is, but cannot manufacture
        # an expected date without an observed interval.
        return None
    gaps = [(right[0] - left[0]).days
            for left, right in zip(dated, dated[1:])]
    interval = max(1, int(round(
        hypothesis.interval_days if measured and hypothesis.interval_days
        else statistics.median(gaps) if gaps
        else 30 if cadence == "monthly" else 365)))
    first, last = dated[0][0], dated[-1][0]
    expected = _advance(last, cadence, interval,
                        max(when.day for when, _row in dated))
    window = max(3, int(round(interval * 0.25)))
    # Adequate means at most one expected interval has gone unobserved. Beyond
    # it the pattern may produce an interruption finding, but not a due claim.
    adequate = today <= expected + timedelta(days=interval)
    amounts = [abs(row.amount) for _, row in dated]
    return {
        "dated": dated, "first": first, "last": last,
        "expected": expected, "interval": interval, "window": window,
        "adequate": adequate, "amounts": amounts, "cadence": cadence,
        "basis": basis, "qualified": qualified,
    }


def obligations(core: ProjectionCore, today: str) -> list[Obligation]:
    """Qualified outgoing arrangements, ordered by expected date and subject."""
    on = _date(today)
    if on is None:
        raise ValueError("obligations require an ISO read date")
    out: list[Obligation] = []
    for hypothesis in rhythm_hypotheses(core):
        if hypothesis.direction != OUT:
            continue
        rows = _movement_rows(core, hypothesis.movements)
        shape = _shape(hypothesis, rows, on)
        if shape is None or not shape["adequate"]:
            continue
        amounts = shape["amounts"]
        basis = shape["basis"]
        status = ("due" if shape["qualified"] and on >= shape["expected"]
                  else "expected")
        caveats = (() if basis == "confirmed" else
                   ("measured_not_confirmed",) if basis == "measured" else
                   ("observed_prior_only",))
        out.append(Obligation(
            id=f"obligation:{hypothesis.subject}", subject=hypothesis.merchant,
            cadence=shape["cadence"],
            expected_date=shape["expected"].isoformat(),
            amount_min=min(amounts), amount_max=max(amounts),
            currency=hypothesis.currency, basis=basis, status=status,
            grade=_weakest(core, rows), count=len(rows),
            dated_from=shape["first"].isoformat(),
            dated_to=shape["last"].isoformat(), record_ids=_records(rows),
            account_ids=_accounts(rows), caveats=caveats))
    out.sort(key=lambda item: (item.expected_date, item.subject, item.currency))
    return out


def _stake(kind: str, **values) -> dict:
    return {"machinery": OBLIGATION_VERSION, "kind": kind, **values}


def _finding(kind: str, identity: str, amount: Decimal, currency: str,
             dated: str, rows, *, label: str = "", **extra) -> Finding:
    stake = _stake(kind, subject=identity, amount=str(amount), dated=dated,
                   count=len(rows), record_ids=list(_records(rows)),
                   **{key: (str(value) if isinstance(value, Decimal) else value)
                      for key, value in extra.items() if value is not None})
    return Finding(
        id=_id(kind, identity), kind=kind, subject=label or identity,
        importance=_IMPORTANCE[kind], amount=amount, currency=currency,
        dated=dated, record_ids=_records(rows), account_ids=_accounts(rows),
        stake=stake, expected_date=str(extra.get("expected_date") or ""),
        prior_amount=extra.get("prior_amount"),
        current_amount=extra.get("current_amount"))


def _duplicate_findings(core: ProjectionCore) -> list[Finding]:
    groups: dict[tuple, list] = {}
    for movement in movements_view.movements(core):
        if movement.linked:
            continue
        merchant = merchants_view.merchant_key_of(core, movement)
        if not merchant:
            continue
        key = (movement.account, movement.date, merchant,
               movement.currency, abs(movement.amount))
        groups.setdefault(key, []).append(movement)
    out = []
    for (account, dated, merchant, currency, amount), rows in groups.items():
        if len(rows) < 2:
            continue
        subject = f"{account}|{dated}|{merchant}|{currency}|{amount}"
        out.append(_finding("possible_duplicate", subject,
                            amount * (len(rows) - 1), currency, dated, rows,
                            label=merchant))
    return out


def _flow(rows) -> Flow:
    occurrences = [Occurrence(_date(row.date), row.amount, row.account,
                              row.kind, row.description)
                   for row in rows if _date(row.date) is not None]
    direction = occurrences[0].direction if occurrences else OUT
    return Flow(direction=direction, occurrences=occurrences)


def _rhythm_findings(core: ProjectionCore, today: date) -> list[Finding]:
    out = []
    for hypothesis in rhythm_hypotheses(core):
        rows = sorted(_movement_rows(core, hypothesis.movements),
                      key=lambda row: (row.date, row.key))
        if len({row.currency for row in rows if row.currency}) != 1:
            # Amounts in unlike currencies have no common magnitude without a
            # sourced rate. The rhythm substrate does not split this axis, so
            # this projection refuses the mixed relationship whole.
            continue
        subject = hypothesis.subject
        # A newest amount can split the rhythm into two components, so detect
        # the change against the formerly fixed run before requiring the whole
        # relationship to remain one component.
        if len(rows) >= MIN_FOR_CADENCE:
            prior, current = rows[:-1], rows[-1]
            prior_flow = _flow(prior)
            median = prior_flow.amount_median
            changed = (prior_flow.amount_is_fixed is True and median > 0
                       and abs(abs(current.amount) - median)
                       > median * Decimal(str(FIXED_AMOUNT_CV)))
            if changed:
                out.append(_finding(
                    "amount_changed", subject, abs(current.amount),
                    current.currency, current.date, rows,
                    label=hypothesis.merchant,
                    prior_amount=median, current_amount=abs(current.amount)))

        shape = _shape(hypothesis, rows, today)
        if shape is None:
            continue
        latest = rows[-1]

        if (hypothesis.direction == OUT and shape["adequate"]
                and shape["qualified"]):
            out.append(_finding(
                "recurring_obligation", subject, abs(latest.amount),
                latest.currency, latest.date, rows,
                label=hypothesis.merchant,
                expected_date=shape["expected"].isoformat()))

        if (shape["qualified"]
                and today > shape["expected"] + timedelta(days=shape["window"])):
            kind = ("expected_outflow_missing" if hypothesis.direction == OUT
                    else "income_interrupted")
            out.append(_finding(
                kind, subject, abs(latest.amount), latest.currency,
                shape["last"].isoformat(), rows,
                label=hypothesis.merchant,
                expected_date=shape["expected"].isoformat()))

    return out


def _fee_findings(core: ProjectionCore) -> list[Finding]:
    out = []
    for movement in movements_view.movements(core):
        if not movements_view.counts_as_spending(movement):
            continue
        category = categories_view.derived_category(core, movement) or {}
        if str(category.get("category") or "").strip().lower() != "fees":
            continue
        subject = movement.key
        out.append(_finding("fee_observed", subject, abs(movement.amount),
                            movement.currency, movement.date, [movement],
                            label=(merchants_view.merchant_key_of(core, movement)
                                   or movement.description)))
    return out


def findings(core: ProjectionCore, today: str, *, include_set_aside: bool = False,
             limit: int | None = None) -> list[Finding]:
    """Ranked findings, with unchanged set-asides removed by default."""
    on = _date(today)
    if on is None:
        raise ValueError("findings require an ISO read date")
    rows = (_duplicate_findings(core) + _rhythm_findings(core, on)
            + _fee_findings(core))
    unique = {finding.id: finding for finding in rows}
    # Consequence is comparable only within one currency. Currency groups are
    # ordered by their stable code; no numeric magnitude is compared across
    # currencies without a sourced rate.
    ordered = sorted(unique.values(),
                     key=lambda item: (-item.importance, item.currency,
                                       -item.amount, item.id))
    if not include_set_aside:
        ordered = [finding for finding in ordered
                   if (core._finding_set_asides.get(finding.id) or {}).get("stake")
                   != finding.stake]
    return ordered if limit is None else ordered[:limit]


def finding_set_asides(core: ProjectionCore) -> dict[str, dict]:
    return copy.deepcopy(core._finding_set_asides)


__all__ = [
    "FINDING_KINDS", "OBLIGATION_VERSION", "Finding", "Obligation",
    "finding_set_asides", "findings", "obligations",
]
