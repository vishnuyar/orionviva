"""Shared account-ledger evidence identity and statement component rules."""

from __future__ import annotations

import datetime
from typing import Any


class AccountLedgerIdentityError(ValueError):
    """The requested account could not be identified exactly and safely."""


class AccountLedgerCursorError(ValueError):
    """A cursor is malformed, stale, or belongs to another account."""


def _coverage(records: list, runs: list[tuple[str, str]]) -> dict[str, Any]:
    # A malformed or adversarial register may contain nested or overlapping
    # runs. Coverage is their interval union, not a sequence whose intermediate
    # end points can manufacture gaps. Adjacent but unjoined runs stay separate:
    # their dates are continuous while their balance chain is not.
    normalized: list[list[str]] = []
    for start, end in sorted(runs):
        if normalized and start <= normalized[-1][1]:
            normalized[-1][1] = max(normalized[-1][1], end)
        else:
            normalized.append([start, end])

    structured_runs = [{"from": start, "to": end, "statement_ids": []}
                       for start, end in normalized]
    assigned: set[str] = set()
    for record in records:
        targets = [run for run in structured_runs
                   if run["from"] <= record.opening_date
                   and record.closing_date <= run["to"]]
        if len(targets) != 1 or not record.doc_id or record.doc_id in assigned:
            raise AccountLedgerIdentityError(
                "the statement coverage cannot be bound exactly")
        targets[0]["statement_ids"].append(record.doc_id)
        assigned.add(record.doc_id)

    gaps = []
    max_covered_end: datetime.date | None = None
    for start_raw, end_raw in normalized:
        start = datetime.date.fromisoformat(start_raw)
        end = datetime.date.fromisoformat(end_raw)
        if max_covered_end is not None and start > max_covered_end + datetime.timedelta(days=1):
            gaps.append({
                "from": (max_covered_end + datetime.timedelta(days=1)).isoformat(),
                "to": (start - datetime.timedelta(days=1)).isoformat(),
                "reason": "missing_statement_coverage",
            })
        max_covered_end = max(max_covered_end, end) if max_covered_end else end
    return {
        "state": ("unavailable" if not normalized else "gapped" if gaps else
                  "discontinuous" if len(normalized) > 1 else "continuous"),
        "runs": structured_runs,
        "gaps": gaps,
    }


def _overlap(records: list) -> dict[str, Any]:
    groups = []
    for index, left in enumerate(records):
        for right in records[index + 1:]:
            start = max(left.opening_date, right.opening_date)
            end = min(left.closing_date, right.closing_date)
            if start <= end:
                groups.append({"from": start, "to": end,
                               "document_ids": sorted([left.doc_id, right.doc_id])})
    groups.sort(key=lambda group: (group["from"], group["to"],
                                   group["document_ids"]))
    return {
        "state": "overlap_present" if groups else "none_observed",
        "groups": groups,
    }


def _deduplicate(movements: list, records: list) -> tuple[list, dict[str, Any]]:
    """Collapse only exact postings backed by overlapping statement periods."""
    by_doc = {record.doc_id: record for record in records}
    if len(by_doc) != len(records):
        raise AccountLedgerIdentityError("statement document identity is ambiguous")
    parents = {str(movement.key): str(movement.key) for movement in movements}
    by_id = {str(movement.key): movement for movement in movements}
    if len(by_id) != len(movements):
        raise AccountLedgerIdentityError("movement identity is ambiguous")

    def root(key: str) -> str:
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    def join(left: str, right: str) -> None:
        a, b = root(left), root(right)
        if a != b:
            parents[max(a, b)] = min(a, b)

    unresolved: list[dict[str, Any]] = []
    by_date: dict[str, list] = {}
    for movement in movements:
        by_date.setdefault(str(movement.date), []).append(movement)
    for same_day in by_date.values():
        for index, left in enumerate(same_day):
            left_doc = str(getattr(left.provenance, "doc_id", "") or "")
            for right in same_day[index + 1:]:
                right_doc = str(getattr(right.provenance, "doc_id", "") or "")
                if not left_doc or not right_doc or left_doc == right_doc:
                    continue
                left_record, right_record = by_doc.get(left_doc), by_doc.get(right_doc)
                if left_record is None or right_record is None:
                    continue
                overlap_start = max(left_record.opening_date, right_record.opening_date)
                overlap_end = min(left_record.closing_date, right_record.closing_date)
                if overlap_start > overlap_end or not all(
                        overlap_start <= str(item.date) <= overlap_end
                        for item in (left, right)):
                    continue
                exact = (str(left.date) == str(right.date)
                         and left.amount == right.amount
                         and left.currency == right.currency
                         and left.description == right.description
                         and left.kind == right.kind)
                if exact:
                    join(str(left.key), str(right.key))
                    continue
                probable = (str(left.date) == str(right.date)
                            and left.amount == right.amount
                            and left.currency == right.currency)
                conflicting = (str(left.date) == str(right.date)
                               and left.description == right.description
                               and (left.amount != right.amount
                                    or left.currency != right.currency))
                if probable or conflicting:
                    unresolved.append({
                        "kind": "conflicting" if conflicting else "probable",
                        "movement_ids": sorted([str(left.key), str(right.key)]),
                        "document_ids": sorted([left_doc, right_doc]),
                    })

    components: dict[str, list] = {}
    for movement in movements:
        components.setdefault(root(str(movement.key)), []).append(movement)
    entries = []
    collapsed = []
    for members in components.values():
        members.sort(key=lambda movement: str(movement.key))
        canonical = members[0]
        entries.append({"movement": canonical, "members": members})
        if len(members) > 1:
            collapsed.append({
                "canonical_movement_id": str(canonical.key),
                "member_movement_ids": [str(member.key) for member in members],
                "document_ids": sorted({
                    str(getattr(member.provenance, "doc_id", "") or "")
                    for member in members
                }),
            })
    collapsed.sort(key=lambda item: item["canonical_movement_id"])
    unresolved.sort(key=lambda item: (item["kind"], item["movement_ids"]))
    if collapsed and unresolved:
        state = "exact_duplicates_collapsed_with_unresolved_candidates"
    elif collapsed:
        state = "exact_duplicates_collapsed"
    elif unresolved:
        state = "unresolved_candidates_present"
    else:
        state = "none"
    return entries, {
        "state": state,
        "policy": "exact_economic_posting_in_overlapping_statements_only",
        "collapsed": collapsed,
        "unresolved": unresolved,
    }
