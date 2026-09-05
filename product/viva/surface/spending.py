"""An authored spending breakdown over attested statement movements.

This surface owns every financial decision in the chart: its inclusive calendar
window, eligible movement population, duplicate handling, classification,
currency partitions, totals, ordering, and bar proportions.  Consumers choose
among the controls it advertises and render the returned words and integers.
"""

from __future__ import annotations

import calendar
import datetime
import hashlib
from collections import Counter
from decimal import Decimal, ROUND_FLOOR
from typing import Any

from .. import render
from ..ledger.events import CORROBORATED, VERIFIED
from ..ledger.projection.movements import (BY_DEFAULT, BY_RULING, MIXED, SETTLEMENT,
                                           SPENDING, TRANSFER)
from .account_ledger import AccountLedgerIdentityError, _deduplicate


PERIODS = (
    ("latest_complete_month", "Last complete month", False),
    ("current_month", "This month", False),
    ("last_3_months", "Last 3 months", False),
    ("year_to_date", "Year to date", False),
    ("custom", "Custom range", True),
)
GRANULARITIES = (("category", "Category"), ("subcategory", "Subcategory"))
COLOR_TOKENS = tuple(f"category-{number}" for number in range(1, 7))
ATTESTED_GRADES = frozenset((VERIFIED, CORROBORATED))


class SpendingBreakdownRequestError(ValueError):
    """A spending request cannot be interpreted without guessing."""


def spending_breakdown(projection, locale: str, read_on: str, *,
                       period: str = "latest_complete_month",
                       granularity: str = "category", currency: str = "",
                       account_id: str = "", start_date: str = "",
                       end_date: str = "") -> dict[str, Any]:
    """Return ``SpendingBreakdown.v1`` for one exact, inclusive date window."""
    today = _date(read_on, "read_on")
    period_ids = {item[0] for item in PERIODS}
    if period not in period_ids:
        raise SpendingBreakdownRequestError("period is not supported")
    if granularity not in {item[0] for item in GRANULARITIES}:
        raise SpendingBreakdownRequestError("granularity is not supported")
    if period == "custom":
        if not start_date or not end_date:
            raise SpendingBreakdownRequestError(
                "custom period requires start_date and end_date")
        start, end = _date(start_date, "start_date"), _date(end_date, "end_date")
        if start > end:
            raise SpendingBreakdownRequestError(
                "custom start_date must not follow end_date")
        if end > today:
            raise SpendingBreakdownRequestError(
                "custom end_date must not follow read_on")
    else:
        if start_date or end_date:
            raise SpendingBreakdownRequestError(
                "start_date and end_date are accepted only for custom period")
        start, end = _period_bounds(period, today)

    all_infos, infos, unsupported = _account_inventory(projection, account_id)
    scoped = [info for info in infos
              if not account_id or str(info.account) == account_id]
    currencies = sorted({str(info.currency) for info in scoped})
    if currency and currency not in currencies:
        raise SpendingBreakdownRequestError(
            "currency is not available in the selected account scope")
    shown_currencies = [currency] if currency else currencies

    ordered_accounts = sorted((scoped if account_id else infos), key=lambda item: (
        str(item.name).casefold(), str(item.account)))
    account_options = [{"id": str(info.account), "label": str(info.name),
                        "currency": str(info.currency), "order": index}
                       for index, info in enumerate(ordered_accounts)]
    currency_options = [{"id": value, "label": value, "order": index}
                        for index, value in enumerate(currencies)]
    covered_infos = [info for info in scoped
                     if not currency or str(info.currency) == currency]
    scoped_unsupported = _scoped_unsupported(unsupported, account_id, currency)
    evidence = _validated_evidence(projection, all_infos, covered_infos)
    coverage = _coverage(covered_infos, evidence, scoped_unsupported, start, end)
    grades = projection.movement_grades()
    groups: dict[str, dict[tuple[str, str], dict[str, Any]]] = {
        value: {} for value in shown_currencies}
    exclusions: Counter[str] = Counter()
    classification_uncertain = 0
    duplicate_count = 0

    for info in covered_infos:
        account_movements = [movement for movement in projection.movements()
                             if movement.account == info.account]
        records = evidence.get(str(info.account), [])
        try:
            entries, deduplication = _deduplicate(account_movements, records)
        except AccountLedgerIdentityError as exc:
            raise SpendingBreakdownRequestError(
                "statement overlap cannot be resolved safely") from exc
        duplicate_count += sum(len(item["member_movement_ids"]) - 1
                               for item in deduplication["collapsed"])
        for entry in entries:
            movement = entry["movement"]
            members = entry["members"]
            try:
                when = _date(str(movement.date), "movement date")
            except SpendingBreakdownRequestError:
                exclusions["invalid_date"] += 1
                continue
            if when < start or when > end:
                continue
            if (str(movement.currency) != str(info.currency)
                    or str(movement.kind) != str(info.kind)):
                exclusions["account_scope_conflict"] += 1
                continue
            if str(movement.currency) not in shown_currencies:
                continue
            if not _members_attested(records, members, when):
                exclusions["outside_attested_coverage"] += 1
                continue
            if any(member.account != movement.account
                   or member.currency != movement.currency
                   or member.kind != movement.kind for member in members):
                exclusions["duplicate_conflict"] += 1
                continue
            member_grades = {grades.get(str(member.key), "") for member in members}
            if not member_grades <= ATTESTED_GRADES:
                exclusions[("conflicted_posting" if "conflicted" in member_grades
                            else "unattested_posting")] += 1
                continue
            if any(member.provisional for member in members):
                exclusions["provisional_treatment"] += 1
                continue
            treatments = {(member.nature,
                           str(getattr(member, "nature_reason", "") or ""),
                           projection._is_expense(member))
                          for member in members}
            classifications = {_classification(projection, member)
                               for member in members}
            if len(treatments) != 1 or len(classifications) != 1:
                exclusions["duplicate_conflict"] += 1
                continue
            nature, nature_reason, expense_shaped = next(iter(treatments))
            if nature != SPENDING or not expense_shaped:
                exclusions[_non_spending_reason(nature, expense_shaped)] += 1
                continue
            if nature_reason != BY_RULING:
                exclusions[("undecided_treatment" if nature_reason == BY_DEFAULT
                            else "unknown_treatment")] += 1
                continue
            category, subcategory, uncertain = next(iter(classifications))
            if uncertain:
                classification_uncertain += 1
            label, identity = _group(category, subcategory, granularity)
            key = (identity, label)
            bucket = groups[str(movement.currency)].setdefault(
                key, {"amount": Decimal("0"), "count": 0})
            bucket["amount"] += abs(movement.amount)
            bucket["count"] += 1

    sections = [_section(value, groups[value], locale, index)
                for index, value in enumerate(shown_currencies)]
    included_count = sum(bar["count"] for section in sections
                         for bar in section["bars"])
    exclusion_rows = _exclusions(exclusions)
    notes = [
        "Only expense-shaped movements with an attested posting and a settled spending treatment are included.",
        "Each currency is totaled and scaled separately. No exchange rate or cross-currency total is used.",
    ]
    if classification_uncertain:
        notes.append(
            f"{classification_uncertain} included movement(s) with no complete, non-conflicted classification are shown as Uncategorized.")
    if duplicate_count:
        notes.append(
            f"{duplicate_count} exact duplicate posting(s) from overlapping statements were collapsed before totals were calculated.")
    if coverage["state"] != "complete":
        notes.append(
            "The selected range is not fully covered by continuous attested statements; totals include covered dates only.")

    return {
        "contract": "SpendingBreakdown.v1",
        "state": "ready" if any(section["bars"] for section in sections) else "empty",
        "title": "Spending breakdown",
        "as_of": today.isoformat(),
        "timezone_policy": "Local calendar dates supplied by the vault host; both range bounds are inclusive.",
        "period": {"id": period, "label": _period_label(period, start, end),
                   "start_date": start.isoformat(), "end_date": end.isoformat()},
        "granularity": granularity,
        "scope_summary": _scope_summary(covered_infos, account_id, currency),
        "controls": {
            "periods": [{"id": item[0], "label": item[1],
                         "requires_custom": item[2]} for item in PERIODS],
            "granularities": [{"id": item[0], "label": item[1]}
                              for item in GRANULARITIES],
            "accounts": account_options,
            "currencies": currency_options,
            "selected_period": period,
            "selected_granularity": granularity,
            "selected_account_id": account_id,
            "selected_currency": currency,
        },
        "sections": sections,
        "coverage": {**coverage, "included_count": included_count,
                     "excluded_count": sum(exclusions.values())},
        "exclusions": exclusion_rows,
        "notes": notes,
    }


def _date(value: str, name: str) -> datetime.date:
    try:
        parsed = datetime.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise SpendingBreakdownRequestError(f"{name} must be an ISO calendar date") from exc
    if parsed.isoformat() != value:
        raise SpendingBreakdownRequestError(f"{name} must be an ISO calendar date")
    return parsed


def _month_start(day: datetime.date, offset: int = 0) -> datetime.date:
    index = day.year * 12 + day.month - 1 + offset
    return datetime.date(index // 12, index % 12 + 1, 1)


def _period_bounds(period: str, today: datetime.date) -> tuple[datetime.date, datetime.date]:
    if period == "current_month":
        return today.replace(day=1), today
    if period == "latest_complete_month":
        start = _month_start(today, -1)
        return start, _month_start(today) - datetime.timedelta(days=1)
    if period == "last_3_months":
        return _month_start(today, -2), today
    if period == "year_to_date":
        return datetime.date(today.year, 1, 1), today
    raise SpendingBreakdownRequestError("period is not supported")


def _period_label(period: str, start: datetime.date, end: datetime.date) -> str:
    name = dict((item[0], item[1]) for item in PERIODS)[period]
    start_label = f"{calendar.month_abbr[start.month]} {start.day}, {start.year}"
    end_label = f"{calendar.month_abbr[end.month]} {end.day}, {end.year}"
    return f"{name} · {start_label}–{end_label}"


def _account_inventory(projection, account_id: str) -> tuple[list, list, list[dict[str, str]]]:
    all_infos = list(projection.account_infos())
    ids = [str(getattr(info, "account", "") or "").strip()
           for info in all_infos]
    named_ids = [value for value in ids if value]
    if len(named_ids) != len(set(named_ids)):
        raise SpendingBreakdownRequestError("account identity is ambiguous")

    eligible = []
    unsupported = []
    allowed_kinds = ("depository", "liability", "investment")
    for index, info in enumerate(all_infos):
        identity = str(getattr(info, "account", "") or "").strip()
        name = str(getattr(info, "name", "") or "").strip()
        kind = str(getattr(info, "kind", "") or "").strip()
        money = str(getattr(info, "currency", "") or "").strip()
        # Precedence is identity, name, kind, then currency.  An earlier
        # reason may therefore accompany empty later fields; a reason may
        # never claim its own field is missing when that field is present.
        reason = ("missing_account_id" if not identity else
                  "missing_account_name" if not name else
                  "unsupported_account_kind" if kind not in allowed_kinds else
                  "missing_account_currency" if not money else "")
        if not reason:
            eligible.append(info)
            continue
        label = name or (f"Account {identity}" if identity else
                         f"Unsupported account {index + 1}")
        sentences = {
            "missing_account_id": f"{label} has no stable account identity and is outside this spending scope.",
            "missing_account_name": f"{label} has no account name and is outside this spending scope.",
            "unsupported_account_kind": f"{label} has an unsupported account type and is outside this spending scope.",
            "missing_account_currency": f"{label} has no currency and is outside this spending scope.",
        }
        unsupported.append({
            # A missing source identity stays missing.  Fabricating an ID here
            # can collide with a real account ID and falsely join two scopes.
            "account_id": identity,
            "label": label,
            "currency": money,
            "reason": reason,
            "sentence": sentences[reason],
        })

    if account_id:
        matches = [info for info in all_infos
                   if str(getattr(info, "account", "") or "").strip() == account_id]
        if len(matches) != 1:
            raise SpendingBreakdownRequestError(
                "account_id does not identify one available account")
        if matches[0] not in eligible:
            raise SpendingBreakdownRequestError(
                "the selected account does not have a complete spending identity")
    return all_infos, eligible, unsupported


def _scoped_unsupported(unsupported: list[dict[str, str]], account_id: str,
                        currency: str) -> list[dict[str, str]]:
    if account_id:
        return []
    return [item for item in unsupported
            if not currency or not item["currency"] or item["currency"] == currency]


def _normalized_runs(runs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    normalized: list[list[str]] = []
    for raw in sorted(runs):
        if not isinstance(raw, (tuple, list)) or len(raw) != 2:
            raise SpendingBreakdownRequestError(
                "statement coverage does not contain valid date ranges")
        left = _date(str(raw[0]), "coverage start").isoformat()
        right = _date(str(raw[1]), "coverage end").isoformat()
        if left > right:
            raise SpendingBreakdownRequestError(
                "statement coverage contains a reversed date range")
        if normalized and left <= normalized[-1][1]:
            normalized[-1][1] = max(normalized[-1][1], right)
        else:
            normalized.append([left, right])
    return [(item[0], item[1]) for item in normalized]


def _validated_evidence(projection, all_infos: list,
                        selected_infos: list) -> dict[str, list]:
    statements_by_account: dict[str, Any] = {}
    document_owner: dict[str, str] = {}
    for info in all_infos:
        account = str(getattr(info, "account", "") or "").strip()
        if not account:
            continue
        statements = projection.statements(account)
        if statements is None:
            statements_by_account[account] = None
            continue
        if str(getattr(statements, "account", "") or "") != account:
            raise SpendingBreakdownRequestError(
                "statement evidence belongs to another account")
        records = list(getattr(statements, "records", []) or [])
        seen: set[str] = set()
        for record in records:
            document_id = str(getattr(record, "doc_id", "") or "").strip()
            if (str(getattr(record, "account", "") or "") != account
                    or not document_id or document_id in seen):
                raise SpendingBreakdownRequestError(
                    "statement document identity is ambiguous")
            opening = _date(str(record.opening_date), "statement opening date")
            closing = _date(str(record.closing_date), "statement closing date")
            if opening > closing:
                raise SpendingBreakdownRequestError(
                    "statement evidence contains a reversed date range")
            seen.add(document_id)
            prior = document_owner.get(document_id)
            if prior is not None and prior != account:
                raise SpendingBreakdownRequestError(
                    "statement evidence belongs to more than one account")
            document_owner[document_id] = account
        raw_runs = list(getattr(statements, "runs", []) or [])
        runs = _normalized_runs(raw_runs)
        for raw in raw_runs:
            left = _date(str(raw[0]), "coverage start").isoformat()
            right = _date(str(raw[1]), "coverage end").isoformat()
            if not any(left <= str(record.opening_date)
                       and str(record.closing_date) <= right
                       for record in records):
                raise SpendingBreakdownRequestError(
                    "statement coverage is not bound to a statement document")
        for record in records:
            if sum(left <= str(record.opening_date)
                   and str(record.closing_date) <= right
                   for left, right in runs) != 1:
                raise SpendingBreakdownRequestError(
                    "statement coverage cannot be bound exactly")
        statements_by_account[account] = records

    movement_owner: dict[str, str] = {}
    for movement in projection.movements():
        movement_id = str(getattr(movement, "key", "") or "").strip()
        movement_account = str(getattr(movement, "account", "") or "").strip()
        if not movement_id or not movement_account:
            raise SpendingBreakdownRequestError("movement identity is ambiguous")
        prior_movement = movement_owner.get(movement_id)
        if prior_movement is not None:
            raise SpendingBreakdownRequestError("movement identity is ambiguous")
        movement_owner[movement_id] = movement_account
        document_id = str(getattr(
            getattr(movement, "provenance", None), "doc_id", "") or "").strip()
        if document_id and (document_id in document_owner
                            and document_owner[document_id] != movement_account):
            raise SpendingBreakdownRequestError(
                "movement evidence belongs to another account")

    return {str(info.account): list(statements_by_account.get(
                str(info.account)) or []) for info in selected_infos}


def _members_attested(records: list, members: list,
                      when: datetime.date) -> bool:
    value = when.isoformat()
    by_document = {str(record.doc_id): record for record in records
                   if str(record.doc_id)}
    if len(by_document) != len(records):
        return False
    for member in members:
        document_id = str(getattr(member.provenance, "doc_id", "") or "")
        record = by_document.get(document_id)
        if record is None or not record.opening_date <= value <= record.closing_date:
            return False
    return True


def _coverage(infos: list, evidence: dict[str, list], unsupported: list,
              start: datetime.date, end: datetime.date) -> dict[str, Any]:
    gaps: list[dict[str, str]] = []
    covered_from: list[str] = []
    covered_to: list[str] = []
    for info in infos:
        records = evidence.get(str(info.account), [])
        runs = [(str(record.opening_date), str(record.closing_date))
                for record in records]
        clipped = [(max(start, _date(left, "coverage start")),
                    min(end, _date(right, "coverage end")))
                   for left, right in runs
                   if _date(right, "coverage end") >= start
                   and _date(left, "coverage start") <= end]
        clipped = [(left, right) for left, right in clipped if left <= right]
        for left, right in clipped:
            covered_from.append(left.isoformat())
            covered_to.append(right.isoformat())
        cursor = start
        for left, right in sorted(clipped):
            if left > cursor:
                gaps.append({"account_id": str(info.account),
                             "account_label": str(info.name),
                             "from": cursor.isoformat(),
                             "to": (left - datetime.timedelta(days=1)).isoformat(),
                             "reason": "missing_statement_coverage",
                             "sentence": (f"{info.name} has no attested statement "
                                          f"coverage from {cursor.isoformat()} "
                                          f"through {(left - datetime.timedelta(days=1)).isoformat()}.")})
            cursor = max(cursor, right + datetime.timedelta(days=1))
        if cursor <= end:
            gaps.append({"account_id": str(info.account),
                         "account_label": str(info.name),
                         "from": cursor.isoformat(), "to": end.isoformat(),
                         "reason": "missing_statement_coverage",
                         "sentence": (f"{info.name} has no attested statement "
                                      f"coverage from {cursor.isoformat()} "
                                      f"through {end.isoformat()}.")})
    state = ("unavailable" if not covered_from else
             "partial" if gaps or unsupported else "complete")
    label = ("Complete attested statement coverage for this range."
             if state == "complete" else
             "Partial attested statement coverage; uncovered dates are excluded."
             if state == "partial" else
             "No attested statement coverage is available for this range.")
    return {"state": state, "label": label,
            "covered_from": min(covered_from) if covered_from else "",
            "covered_to": max(covered_to) if covered_to else "",
            "gaps": [{**gap, "order": index}
                     for index, gap in enumerate(gaps)],
            "unsupported_accounts": [{**item, "order": index}
                                     for index, item in enumerate(unsupported)]}


def _classification(projection, movement) -> tuple[str, str, bool]:
    row = projection.derived_category(movement) or {}
    category = str(row.get("category") or "").strip()
    subcategory = str(row.get("subcategory") or "").strip()
    grade = str(row.get("grade") or "").strip()
    conflicted = grade == "conflicted"
    malformed = bool(subcategory) and not category
    if conflicted or malformed or not category:
        return "Uncategorized", "", True
    return category, subcategory, False


def _group(category: str, subcategory: str,
           granularity: str) -> tuple[str, str]:
    if granularity == "category":
        label = str(render.category(category))
        raw_id = f"category:{category}"
    elif category == "Uncategorized":
        label, raw_id = "Uncategorized", "subcategory:Uncategorized"
    else:
        sub_label = str(render.label(subcategory)) if subcategory else "Unassigned"
        label = f"{render.category(category)} · {sub_label}"
        raw_id = f"subcategory:{category}/{subcategory or 'unassigned'}"
    digest = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]
    return label, f"spend-{digest}"


def _basis_points(amounts: list[Decimal], denominator: Decimal) -> list[int]:
    if not amounts or denominator <= 0:
        return [0 for _ in amounts]
    exact = [amount * Decimal(10000) / denominator for amount in amounts]
    floor = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
    remaining = 10000 - sum(floor)
    order = sorted(range(len(amounts)), key=lambda index: (
        exact[index] - Decimal(floor[index]), amounts[index], -index), reverse=True)
    for index in order[:remaining]:
        floor[index] += 1
    return floor


def _section(currency: str, grouped: dict, locale: str,
             section_order: int) -> dict[str, Any]:
    rows = sorted(((identity, label, values["amount"], values["count"])
                   for (identity, label), values in grouped.items()),
                  key=lambda row: (-row[2], row[1].casefold(), row[0]))
    total = sum((row[2] for row in rows), Decimal("0"))
    maximum = rows[0][2] if rows else Decimal("0")
    shares = _basis_points([row[2] for row in rows], total)
    widths = [int((amount * Decimal(10000) / maximum).to_integral_value(
        rounding=ROUND_FLOOR)) if maximum else 0 for _, _, amount, _ in rows]
    bars = [{"id": identity, "order": index, "label": label,
             "amount_display": str(render.money(amount, currency, locale=locale)),
             "share_basis_points": shares[index],
             "bar_basis_points": widths[index],
             "count": count,
             "color_token": COLOR_TOKENS[index % len(COLOR_TOKENS)]}
            for index, (identity, label, amount, count) in enumerate(rows)]
    return {"currency": currency, "order": section_order,
            "included_count": sum(row[3] for row in rows),
            "total_display": str(render.money(total, currency, locale=locale)),
            "bars": bars,
            "empty_message": ("No eligible spending is attested for this selection."
                              if not bars else "")}


def _non_spending_reason(nature: str, expense_shaped: bool) -> str:
    if not expense_shaped:
        return "income_or_non_expense"
    return {TRANSFER: "transfer", SETTLEMENT: "debt_or_settlement",
            MIXED: "mixed_treatment"}.get(nature, "unknown_treatment")


def _exclusions(counts: Counter[str]) -> list[dict[str, Any]]:
    copy = {
        "outside_attested_coverage": "Movement(s) outside attested statement coverage were excluded.",
        "unattested_posting": "Movement(s) without an attested posting grade were excluded.",
        "conflicted_posting": "Movement(s) with conflicted posting evidence were excluded.",
        "provisional_treatment": "Movement(s) with provisional treatment were excluded.",
        "transfer": "Own-account transfer movement(s) were excluded.",
        "debt_or_settlement": "Debt or settlement movement(s) were excluded.",
        "mixed_treatment": "Movement(s) with an unresolved mixed treatment were excluded.",
        "income_or_non_expense": "Income and movements without an expense direction were excluded.",
        "unknown_treatment": "Movement(s) with an unknown treatment were excluded.",
        "undecided_treatment": "Movement(s) whose spending treatment rested only on a default were excluded.",
        "duplicate_conflict": "Overlapping duplicate movement(s) with inconsistent meaning were excluded.",
        "account_scope_conflict": "Movement(s) whose currency or account kind conflicted with their account were excluded.",
        "invalid_date": "Movement(s) without a valid calendar date were excluded.",
    }
    return [{"kind": kind, "count": counts[kind], "sentence": copy[kind]}
            for kind in copy if counts[kind]]


def _scope_summary(infos: list, account_id: str, currency: str) -> str:
    account = (infos[0].name if account_id and infos else
               f"All available {currency} accounts" if currency else
               "All available accounts")
    money = currency if currency else "currencies shown separately"
    return f"{account} · {money}"
