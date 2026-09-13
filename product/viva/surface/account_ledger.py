"""One account's continuous, evidence-bearing movement ledger.

Statement overlap is resolved only at the strongest safe rung: postings whose
complete economic identity is equal and whose two source periods overlap are
one row.  Every other possible match remains distinct and is disclosed.  This
decision is made here, before pagination, so no consumer has to guess whether
two document rows are the same movement.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import hmac
import json
import re
from decimal import Decimal
from typing import Any, Iterable

from .. import render
from ..ledger.events import Event
from ..ledger.account_ledger_contract import (
    AccountLedgerCursorError, AccountLedgerIdentityError,
    _coverage, _deduplicate, _overlap)
from ..ledger.identity import masked
from ..ledger.streams import money_effect
from .activity import _row


DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def snapshot_revision(events: Iterable[Event]) -> str:
    """A stable identity for the exact event prefix used by one read."""
    # Event IDs are opaque write receipts. Two independently built fixtures
    # holding the same ordered facts should have the same read revision, while
    # appending even an identical fact still changes the list and its digest.
    payload = []
    for event in events:
        item = event.to_dict()
        item.pop("event_id", None)
        payload.append(item)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def account_ledger(projection, account_id: str, locale: str,
                   revision: str, *, cursor_secret: bytes,
                   limit: int = DEFAULT_LIMIT,
                   cursor: str = "") -> dict[str, Any]:
    """Read one exact account, newest first, against one immutable revision."""
    if not account_id or not revision:
        raise AccountLedgerIdentityError("an exact account and revision are required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    if not isinstance(cursor_secret, bytes) or len(cursor_secret) < 32:
        raise ValueError("account ledger cursors require a private 256-bit key")

    matches = [info for info in projection.account_infos()
               if info.account == account_id]
    if len(matches) != 1:
        raise AccountLedgerIdentityError(
            "the requested account could not be identified exactly")
    info = matches[0]
    number = masked(info.number)
    if (not all((info.account, info.name, info.kind, info.currency, number))
            or info.kind not in ("depository", "liability", "investment")):
        raise AccountLedgerIdentityError(
            "the requested account does not have a complete safe identity")

    movements = [movement for movement in projection.movements()
                 if movement.account == account_id]
    statements = projection.statements(account_id)
    if statements is not None and getattr(statements, "account", None) != account_id:
        raise AccountLedgerIdentityError("the statement projection belongs to another account")
    records = list(statements.records) if statements else []
    if any(record.account != account_id for record in records):
        raise AccountLedgerIdentityError("the statement projection contains another account")
    requested_document_ids = {record.doc_id for record in records} | {
        str(getattr(movement.provenance, "doc_id", "") or "")
        for movement in movements
    }
    requested_document_ids.discard("")
    for other_info in projection.account_infos():
        if other_info.account == account_id:
            continue
        other_statements = projection.statements(other_info.account)
        other_document_ids = {
            record.doc_id for record in (
                list(other_statements.records) if other_statements else [])
        }
        if requested_document_ids & other_document_ids:
            raise AccountLedgerIdentityError(
                "the account ledger evidence belongs to another account")
    coverage = _coverage(records, list(statements.runs) if statements else [])
    overlap = _overlap(records)
    entries, deduplication = _deduplicate(movements, records)
    overlap["deduplication"] = deduplication
    # De-duplication precedes ordering and pagination. A canonical movement ID
    # is the stable tie-breaker for the authoritative rendered row.
    ordered = sorted(entries, key=lambda entry: (
        str(entry["movement"].date), str(entry["movement"].key)), reverse=True)
    start = (_cursor_start(cursor, account_id, revision, ordered,
                           cursor_secret) if cursor else 0)
    page_movements = ordered[start:start + limit]
    next_cursor = ""
    if start + len(page_movements) < len(ordered) and page_movements:
        last = page_movements[-1]["movement"]
        next_cursor = _encode_cursor(account_id, revision,
                                     str(last.date), str(last.key),
                                     cursor_secret)

    balance = projection.balance(account_id)
    reconciliation = {
        "balance": ("reconciled" if balance.reconciliation is not None
                    and balance.reconciliation.passed else
                    "conflicted" if balance.reconciliation is not None else
                    "not_established"),
        "overlap": overlap,
        # A statement-wide reconciliation does not establish a per-row running
        # balance across gaps or overlaps. No row receives a synthesized one.
        "running_balance": {"state": "absent",
                            "reason": "not_authoritatively_available"},
    }
    return {
        "state": "ready",
        "scope": {"kind": "account", "account_id": account_id},
        "revision": revision,
        "account": {
            "id": info.account,
            "name": info.name,
            "number_masked": number,
            "type": info.kind,
            "currency": info.currency,
            "balance": _balance(balance, info.kind, info.currency, locale),
        },
        "coverage": coverage,
        "reconciliation": reconciliation,
        "sources": _sources(projection, account_id, records, coverage,
                            overlap, page_movements),
        "groups": _groups(projection, page_movements, locale),
        "page": {
            "limit": limit,
            "returned": len(page_movements),
            "remaining": max(0, len(ordered) - start - len(page_movements)),
            "next_cursor": next_cursor or None,
        },
    }


def sql_account_ledger_page(parts) -> dict[str, Any]:
    """Present a bounded held SQL page with the AccountLedger.v1 vocabulary."""
    return {
        "state": "ready",
        "scope": {"kind": "account", "account_id": parts.account_id},
        "revision": parts.revision,
        "account": {
            "id": parts.info.account, "name": parts.info.name,
            "number_masked": parts.number, "type": parts.info.kind,
            "currency": parts.info.currency,
            "balance": _balance(parts.balance, parts.info.kind,
                                parts.info.currency, parts.locale),
        },
        "coverage": parts.coverage,
        "reconciliation": {
            "balance": parts.recon_state, "overlap": parts.overlap,
            "running_balance": {"state": "absent",
                                "reason": "not_authoritatively_available"},
        },
        "sources": _sources(parts.projection, parts.account_id, parts.records,
                            parts.coverage, parts.overlap, parts.entries),
        "groups": _groups(parts.projection, parts.entries, parts.locale),
        "page": {"limit": parts.limit, "returned": parts.returned,
                 "remaining": parts.remaining, "next_cursor": parts.next_cursor},
    }


def _groups(projection, entries: list, locale: str) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for entry in entries:
        movement = entry["movement"]
        month = str(movement.date)[:7]
        if not groups or groups[-1]["month"] != month:
            groups.append({"month": month, "label": _month_label(month),
                           "movements": []})
        row = _row(projection, movement, locale, _empty_vocabularies())
        row["direction_display"] = _direction_display(row.get("direction"))
        # AccountLedger.v1 is a read contract. Activity may expose writes over
        # this shared row composer; those operations do not cross this surface.
        row["actions"] = []
        evidence = []
        seen_evidence = set()
        for member in entry["members"]:
            for link in _row(projection, member, locale,
                             _empty_vocabularies())["evidence_links"]:
                identity = tuple(sorted(link.items()))
                if identity not in seen_evidence:
                    seen_evidence.add(identity)
                    evidence.append(link)
        row["evidence_links"] = evidence
        member_ids = sorted(str(member.key) for member in entry["members"])
        row["deduplication"] = {
            "state": "single" if len(member_ids) == 1 else "exact_duplicate",
            "canonical_movement_id": str(movement.key),
            "member_movement_ids": member_ids,
        }
        groups[-1]["movements"].append(row)
    return groups


def _direction_display(direction: Any) -> str:
    """The reviewed statement word shown beside an unsigned amount."""
    if direction == "out":
        return "Debit"
    if direction == "in":
        return "Credit"
    return "Direction unavailable"


def _empty_vocabularies() -> dict[str, Any]:
    # The account ledger is a read contract. Existing Activity actions remain
    # where they are and are not re-declared by this new surface.
    return {
        "categories": {"items": [], "complete": False, "limit": 0},
        "tags": {"items": [], "complete": False, "limit": 0,
                 "max_selected": 0, "max_label_length": 0},
    }


def _month_label(month: str) -> str:
    try:
        year, number = (int(part) for part in month.split("-", 1))
        if not 1 <= number <= 12:
            raise ValueError
    except (TypeError, ValueError):
        return month
    return f"{calendar.month_name[number]} {year}"


def _balance(balance, kind: str, currency: str, locale: str) -> dict[str, Any]:
    """Expose a figure only when a balance observation supplies its date."""
    if not str(balance.dated or "").strip():
        return {"state": "absent",
                "reason": "no_authoritative_balance_observation"}
    return {
        "state": "available",
        "kind": ("amount_owed" if kind == "liability"
                 and balance.amount >= Decimal("0") else "current_balance"),
        "exact_value": str(balance.amount),
        "display": str(render.money(balance.amount, currency, locale=locale)),
        "as_of": balance.dated,
        "grade": balance.grade,
    }




def _sources(projection, account_id: str, records: list,
             coverage: dict[str, Any], overlap: dict[str, Any],
             movements: list) -> list[dict[str, Any]]:
    filenames = projection.captured_filenames()
    periods = {record.doc_id: {"from": record.opening_date,
                               "to": record.closing_date}
               for record in records}
    statement_ids = {
        document_id for run in coverage["runs"]
        for document_id in run["statement_ids"]
    } | {
        document_id for group in overlap["groups"]
        for document_id in group["document_ids"]
    }
    evidence_ids = {
        str(getattr(member.provenance, "doc_id", "") or "").strip()
        for entry in movements for member in entry["members"]
    }
    evidence_ids.discard("")
    ids = statement_ids | evidence_ids
    return [{
        "document_id": document_id,
        "account_id": account_id,
        "filename": str(filenames.get(document_id) or ""),
        "relation": ("statement_and_movement_evidence"
                     if document_id in statement_ids
                     and document_id in evidence_ids
                     else "statement" if document_id in statement_ids
                     else "movement_evidence"),
        "period": periods.get(document_id) if document_id in statement_ids else None,
    } for document_id in sorted(ids)]


def _encode_cursor(account_id: str, revision: str, date: str,
                   movement_id: str, secret: bytes) -> str:
    body = {"v": 1, "account_id": account_id, "revision": revision,
            "after": {"date": date, "movement_id": movement_id}}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    envelope = {"body": body,
                "mac": hmac.new(secret, canonical.encode(),
                                hashlib.sha256).hexdigest()}
    raw = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _cursor_start(cursor: str, account_id: str, revision: str,
                  ordered: list, secret: bytes) -> int:
    try:
        if (not isinstance(cursor, str) or not cursor
                or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None):
            raise ValueError
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded.encode(), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode().rstrip("=") != cursor:
            raise ValueError
        envelope = json.loads(raw.decode())
        if set(envelope) != {"body", "mac"}:
            raise ValueError
        body = envelope["body"]
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        expected = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
        if not isinstance(envelope["mac"], str) or not hmac.compare_digest(
                envelope["mac"], expected):
            raise ValueError
        if set(body) != {"v", "account_id", "revision", "after"} or body["v"] != 1:
            raise ValueError
        after = body["after"]
        if set(after) != {"date", "movement_id"}:
            raise ValueError
        canonical_envelope = json.dumps(
            envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if raw != canonical_envelope:
            raise ValueError
    except Exception as exc:
        raise AccountLedgerCursorError("the account ledger cursor is malformed") from exc
    if body["account_id"] != account_id:
        raise AccountLedgerCursorError("the account ledger cursor belongs to another account")
    if body["revision"] != revision:
        raise AccountLedgerCursorError("the account ledger cursor is stale")
    anchor = next((index for index, entry in enumerate(ordered)
                   if entry["movement"].key == after["movement_id"]
                   and str(entry["movement"].date) == after["date"]), None)
    if anchor is None:
        raise AccountLedgerCursorError("the account ledger cursor anchor is unavailable")
    return anchor + 1
