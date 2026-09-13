"""Account-ledger keyset reads from one immutable encrypted SQL generation."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, fields
from decimal import Decimal
from types import SimpleNamespace

from ..ledger.identity import masked
from ..ledger.projection.accounts import AccountInfo
from ..ledger.projection.movements import MovementInfo
from ..ledger.events import Provenance
from ..ledger.statements import StatementRecord, _runs
from ..ledger.account_ledger_contract import (
    AccountLedgerCursorError, AccountLedgerIdentityError, _coverage, _overlap)
from .account_ledger import MAX_COMPONENT_JSON_BYTES
from .store import ReadStoreError


MAX_CURSOR_BYTES = 4_096
MAX_PAGE_MEMBERS = 10_000
MEMBER_BATCH = 400
MAX_PAGE_CONTEXT = 10_000
MAX_PAGE_DOCUMENTS = 12_000
MAX_TRANSFER_CONTEXT = 4_000
MAX_LOAN_CONTEXT = 10_000
MAX_COMPONENT_JSON_DEPTH = 32
MAX_COMPONENT_JSON_NODES = 100_000
MAX_COMPONENT_CONTAINER_ITEMS = 10_000
MAX_FORMATTER_SCALAR_BYTES = 4_096
_BOUNDED_MOVEMENT_FIELDS = frozenset((
    "movement_key", "account_id", "account_kind", "occurred_at",
    "amount_text", "currency", "description", "provenance_doc_id",
    "provenance_region", "provenance_note", "nature", "nature_reason",
    "ruling_account", "category", "subcategory", "category_grade",
    "subcategory_grade", "category_by", "subcategory_by", "merchant_key"))


def _bounded_movement_columns():
    selected = tuple(
        f"CASE WHEN length(CAST({name} AS BLOB))<=? THEN {name} END"
        if name in _BOUNDED_MOVEMENT_FIELDS else name
        for name in _MOVEMENT_COLUMNS)
    return ",".join(selected), (MAX_FORMATTER_SCALAR_BYTES,) * len(
        _BOUNDED_MOVEMENT_FIELDS)


def _scalar(value, label):
    if (not isinstance(value, str)
            or len(value.encode("utf-8")) > MAX_FORMATTER_SCALAR_BYTES):
        raise ReadStoreError(f"account ledger {label} exceeds its scalar byte bound")
    return value


def _json(encoded, expected, label):
    if (not isinstance(encoded, str)
            or len(encoded.encode("utf-8")) > MAX_COMPONENT_JSON_BYTES):
        raise ReadStoreError(f"account ledger {label} exceeds its byte bound")
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ReadStoreError(f"account ledger {label} is invalid") from exc
    if not isinstance(value, expected):
        raise ReadStoreError(f"account ledger {label} has the wrong shape")
    stack = [(value, 1)]
    visited = 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        if visited > MAX_COMPONENT_JSON_NODES or depth > MAX_COMPONENT_JSON_DEPTH:
            raise ReadStoreError(f"account ledger {label} exceeds its nested work bound")
        if isinstance(item, (list, dict)):
            if len(item) > MAX_COMPONENT_CONTAINER_ITEMS:
                raise ReadStoreError(f"account ledger {label} exceeds its container bound")
            children = item.values() if isinstance(item, dict) else item
            stack.extend((child, depth + 1) for child in children)
            if isinstance(item, dict):
                stack.extend((key, depth + 1) for key in item)
        elif isinstance(item, str):
            _scalar(item, label)
    return value


def _source_identity(revision):
    row = revision.connection.execute(
        "SELECT source_count,source_head,publication_epoch FROM projection_meta "
        "WHERE singleton=1").fetchone()
    if row is None or not isinstance(row[0], int) or not isinstance(row[1], str):
        raise ReadStoreError("account ledger source identity is unavailable")
    return {"count": row[0], "head": row[1],
            "epoch": row[2], "generation": revision.generation}


def _cursor_body(account_id, source, date, key):
    return {"v": 2, "account_id": account_id, "source": source,
            "after": {"date": date, "movement_id": key}}


def _encode_cursor(account_id, source, date, key, secret):
    body = _cursor_body(account_id, source, date, key)
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    envelope = {"body": body,
                "mac": hmac.new(secret, canonical, hashlib.sha256).hexdigest()}
    raw = json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_CURSOR_BYTES:
        raise AccountLedgerCursorError("the account ledger cursor is too large")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor, account_id, source, secret):
    try:
        if (not isinstance(cursor, str) or not cursor
                or len(cursor) > MAX_CURSOR_BYTES * 2
                or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None):
            raise ValueError
        raw = base64.b64decode(
            (cursor + "=" * (-len(cursor) % 4)).encode("ascii"),
            altchars=b"-_", validate=True)
        if (len(raw) > MAX_CURSOR_BYTES
                or base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != cursor):
            raise ValueError
        envelope = json.loads(raw.decode("utf-8"))
        if not isinstance(envelope, dict) or set(envelope) != {"body", "mac"}:
            raise ValueError
        body = envelope["body"]
        if (not isinstance(body, dict)
                or set(body) != {"v", "account_id", "source", "after"}
                or type(body["v"]) is not int or body["v"] != 2
                or not isinstance(body["source"], dict)
                or set(body["source"]) != {"count", "head", "epoch", "generation"}
                or not isinstance(body["after"], dict)
                or set(body["after"]) != {"date", "movement_id"}
                or not all(isinstance(value, str) and value
                           for value in body["after"].values())):
            raise ValueError
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode("utf-8")
        expected = hmac.new(secret, canonical, hashlib.sha256).hexdigest()
        if (not isinstance(envelope["mac"], str)
                or not hmac.compare_digest(envelope["mac"], expected)
                or raw != json.dumps(envelope, sort_keys=True,
                                     separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")):
            raise ValueError
    except Exception as exc:
        raise AccountLedgerCursorError(
            "the account ledger cursor is malformed") from exc
    if body["account_id"] != account_id:
        raise AccountLedgerCursorError(
            "the account ledger cursor belongs to another account")
    if body["source"] != source:
        raise AccountLedgerCursorError("the account ledger cursor is stale")
    return body["after"]["date"], body["after"]["movement_id"]


def _index_page(revision, account_id, limit, anchor):
    where = "account_id=?"
    parameters = [account_id]
    if anchor is not None:
        date, key = anchor
        exists = revision.connection.execute(
            "SELECT 1 FROM account_ledger_component_index "
            "WHERE account_id=? AND occurred_at=? AND canonical_movement_key=?",
            (account_id, date, key)).fetchone()
        if exists is None:
            raise AccountLedgerCursorError(
                "the account ledger cursor anchor is unavailable")
        where += " AND (occurred_at<? OR (occurred_at=? AND canonical_movement_key<?))"
        parameters.extend((date, date, key))
    rows = revision.connection.execute(
        "SELECT occurred_at,canonical_movement_key,"
        "CASE WHEN length(CAST(members_json AS BLOB))<=? THEN members_json END "
        "FROM account_ledger_component_index "
        "INDEXED BY account_ledger_components_by_page "
        f"WHERE {where} ORDER BY occurred_at DESC,canonical_movement_key DESC LIMIT ?",
        (MAX_COMPONENT_JSON_BYTES, *parameters, limit + 1)).fetchall()
    page = rows[:limit]
    if page:
        last_date, last_key = page[-1][:2]
        remaining = revision.connection.execute(
            "SELECT COUNT(*) FROM account_ledger_component_index "
            "INDEXED BY account_ledger_components_by_page "
            "WHERE account_id=? AND (occurred_at<? OR "
            "(occurred_at=? AND canonical_movement_key<?))",
            (account_id, last_date, last_date, last_key)).fetchone()[0]
    else:
        remaining = 0
    return page, remaining


_MOVEMENT_COLUMNS = (
    "movement_key", "account_id", "account_kind", "occurred_at",
    "amount_text", "currency", "description", "provenance_doc_id",
    "provenance_page", "provenance_region", "provenance_note", "linked",
    "nature", "nature_reason", "provisional", "ruling_account",
    "category", "subcategory", "category_grade", "subcategory_grade",
    "category_by", "subcategory_by", "merchant_key")


def _movement_rows(connection, keys):
    if len(keys) > MAX_PAGE_MEMBERS:
        raise ReadStoreError("account ledger page members exceed their row bound")
    rows = {}
    selected_columns, scalar_parameters = _bounded_movement_columns()
    for start in range(0, len(keys), MEMBER_BATCH):
        batch = keys[start:start + MEMBER_BATCH]
        placeholders = ",".join("?" for _ in batch)
        selected = connection.execute(
            f"SELECT {selected_columns} FROM movements "
            f"WHERE movement_key IN ({placeholders}) LIMIT ?",
            (*scalar_parameters, *batch, len(batch) + 1)).fetchall()
        if len(selected) != len(batch):
            raise ReadStoreError("account ledger page movement identity is incomplete")
        for values in selected:
            row = dict(zip(_MOVEMENT_COLUMNS, values))
            for name in _BOUNDED_MOVEMENT_FIELDS:
                _scalar(row[name], name)
            key = row["movement_key"]
            rows[key] = row
    return rows


def _movement(row):
    return MovementInfo(
        key=row["movement_key"], account=row["account_id"],
        kind=row["account_kind"], date=row["occurred_at"],
        amount=Decimal(row["amount_text"]), currency=row["currency"],
        description=row["description"], provenance=Provenance(
            row["provenance_doc_id"], row["provenance_page"],
            row["provenance_region"], row["provenance_note"]),
        linked=bool(row["linked"]), nature=row["nature"],
        nature_reason=row["nature_reason"],
        provisional=bool(row["provisional"]),
        ruling_account=row["ruling_account"])


def _records(encoded):
    records = _json(encoded, list, "statement records")
    if len(records) > 2_000:
        raise ReadStoreError("account ledger statement records exceed their row bound")
    try:
        result = [StatementRecord(
            doc_id=row["doc_id"], account=row["account"],
            opening_date=row["opening_date"],
            opening_amount=Decimal(row["opening_amount"]),
            closing_date=row["closing_date"],
            closing_amount=Decimal(row["closing_amount"]))
            for row in records]
        for record in result:
            if (not record.doc_id or not record.account
                    or record.opening_date > record.closing_date
                    or not record.opening_amount.is_finite()
                    or not record.closing_amount.is_finite()):
                raise ValueError
            datetime.date.fromisoformat(record.opening_date)
            datetime.date.fromisoformat(record.closing_date)
        return result
    except (TypeError, ValueError, KeyError) as exc:
        raise ReadStoreError("account ledger statement records are invalid") from exc


def _evidence_shapes(records, coverage, overlap):
    try:
        if (set(coverage) != {"state", "runs", "gaps"}
                or not isinstance(coverage["runs"], list)
                or not isinstance(coverage["gaps"], list)
                or set(overlap) != {"state", "groups", "deduplication"}
                or not isinstance(overlap["groups"], list)):
            raise ValueError
        for run in coverage["runs"]:
            if (not isinstance(run, dict)
                    or set(run) != {"from", "to", "statement_ids"}
                    or not isinstance(run["statement_ids"], list)):
                raise ValueError
        if coverage != _coverage(records, _runs(records)):
            raise ValueError
        if {key: overlap[key] for key in ("state", "groups")} != _overlap(records):
            raise ValueError
        dedup = overlap["deduplication"]
        if (not isinstance(dedup, dict)
                or set(dedup) != {"state", "policy", "collapsed", "unresolved"}
                or dedup["policy"] != "exact_economic_posting_in_overlapping_statements_only"
                or dedup["state"] not in {
                    "none", "exact_duplicates_collapsed",
                    "unresolved_candidates_present",
                    "exact_duplicates_collapsed_with_unresolved_candidates"}
                or not isinstance(dedup["collapsed"], list)
                or not isinstance(dedup["unresolved"], list)):
            raise ValueError
        for item in dedup["collapsed"]:
            if (not isinstance(item, dict)
                    or set(item) != {"canonical_movement_id",
                                     "member_movement_ids", "document_ids"}
                    or not isinstance(item["canonical_movement_id"], str)
                    or not isinstance(item["member_movement_ids"], list)
                    or not isinstance(item["document_ids"], list)
                    or any(not isinstance(value, str) for value in
                           item["member_movement_ids"] + item["document_ids"])):
                raise ValueError
        for item in dedup["unresolved"]:
            if (not isinstance(item, dict)
                    or set(item) != {"kind", "movement_ids", "document_ids"}
                    or item["kind"] not in {"probable", "conflicting"}
                    or not isinstance(item["movement_ids"], list)
                    or not isinstance(item["document_ids"], list)
                    or any(not isinstance(value, str) for value in
                           item["movement_ids"] + item["document_ids"])):
                raise ValueError
        collapsed = bool(dedup["collapsed"])
        unresolved = bool(dedup["unresolved"])
        expected_state = (
            "exact_duplicates_collapsed_with_unresolved_candidates"
            if collapsed and unresolved else
            "exact_duplicates_collapsed" if collapsed else
            "unresolved_candidates_present" if unresolved else "none")
        if dedup["state"] != expected_state:
            raise ValueError
    except (TypeError, ValueError, KeyError, AccountLedgerIdentityError) as exc:
        raise ReadStoreError("account ledger statement evidence is invalid") from exc


def _balance_shape(raw):
    try:
        if (set(raw) != {"amount", "dated", "grade", "reconciliation"}
                or not all(isinstance(raw[key], str) for key in raw)
                or raw["reconciliation"] not in {
                    "not_established", "reconciled", "conflicted"}):
            raise ValueError
        amount = Decimal(raw["amount"])
        if not amount.is_finite():
            raise ValueError
        if raw["dated"]:
            datetime.date.fromisoformat(raw["dated"])
        return amount
    except (TypeError, ValueError, KeyError, ArithmeticError) as exc:
        raise ReadStoreError("account ledger balance is invalid") from exc


def _account_info(raw):
    names = {field.name for field in fields(AccountInfo)}
    if (set(raw) != names or not isinstance(raw["names"], list)
            or any(not isinstance(name, str) for name in raw["names"])
            or any(not isinstance(raw[name], str)
                   for name in names - {"names"})):
        raise ReadStoreError("account ledger account identity is invalid")
    return AccountInfo(**raw)


def _context(connection, members, account_info_value):
    keys = sorted(set(members))
    links, suggestions, counterpart_keys = [], [], set()
    for start in range(0, len(keys), MEMBER_BATCH):
        batch = keys[start:start + MEMBER_BATCH]
        placeholders = ",".join("?" for _ in batch)
        selected = connection.execute(
            "SELECT movement_a,movement_b,"
            "CASE WHEN length(CAST(grade AS BLOB))<=? THEN grade END,"
            "CASE WHEN length(CAST(by_actor AS BLOB))<=? THEN by_actor END,"
            "CASE WHEN length(CAST(decided_by AS BLOB))<=? THEN decided_by END "
            "FROM transfer_links WHERE movement_a IN (" + placeholders + ") "
            "OR movement_b IN (" + placeholders + ") LIMIT ?",
            (MAX_FORMATTER_SCALAR_BYTES,) * 3 +
            (*batch, *batch, MAX_TRANSFER_CONTEXT + 1)).fetchall()
        if len(selected) > MAX_TRANSFER_CONTEXT:
            raise ReadStoreError("account ledger transfer context exceeds its row bound")
        for a, b, grade, by, decided in selected:
            links.append({"a": _scalar(a, "transfer source"),
                          "b": _scalar(b, "transfer target"),
                          "grade": _scalar(grade, "transfer grade"),
                          "by": _scalar(by, "transfer actor"),
                          "decided_by": _scalar(decided, "transfer decision")})
            counterpart_keys.update((a, b))
        selected = connection.execute(
            "SELECT movement_a,"
            "CASE WHEN length(CAST(candidates_json AS BLOB))<=? THEN candidates_json END,"
            "CASE WHEN length(CAST(evidence_json AS BLOB))<=? THEN evidence_json END "
            "FROM transfer_suggestions WHERE movement_a IN (" + placeholders + ") "
            "LIMIT ?", (MAX_COMPONENT_JSON_BYTES, MAX_COMPONENT_JSON_BYTES,
                        *batch, MAX_TRANSFER_CONTEXT + 1)).fetchall()
        if len(selected) > MAX_TRANSFER_CONTEXT:
            raise ReadStoreError("account ledger transfer context exceeds its row bound")
        for a, candidates_raw, evidence_raw in selected:
            from .transfer_payload import (candidate_keys,
                                           decode as decode_transfer)
            try:
                candidates = candidate_keys(decode_transfer(
                    candidates_raw, list, maximum_bytes=MAX_COMPONENT_JSON_BYTES),
                    maximum_count=20)
                evidence = decode_transfer(
                    evidence_raw, (list, dict),
                    maximum_bytes=MAX_COMPONENT_JSON_BYTES)
            except ValueError as exc:
                raise ReadStoreError("account ledger transfer context is refused") from exc
            suggestions.append({"a": a, "candidates": candidates,
                                "evidence": evidence,
                                "status": "suggested"})
            counterpart_keys.update(candidates)
    if len(links) + len(suggestions) > MAX_TRANSFER_CONTEXT or len(counterpart_keys) > MAX_TRANSFER_CONTEXT:
        raise ReadStoreError("account ledger transfer context exceeds its row bound")
    context = _movement_rows(connection, sorted(counterpart_keys - set(keys)))
    selected_columns, scalar_parameters = _bounded_movement_columns()
    loan_rows = connection.execute(
        f"SELECT {selected_columns} FROM movements "
        "INDEXED BY movements_by_loan_ruling "
        "WHERE ruling_account>='Assets:Loans:' AND ruling_account<'Assets:Loans;' "
        "ORDER BY ruling_account,occurred_at,movement_key LIMIT ?",
        (*scalar_parameters, MAX_LOAN_CONTEXT + 1,)).fetchall()
    if len(loan_rows) > MAX_LOAN_CONTEXT:
        raise ReadStoreError("account ledger loan context exceeds its row bound")
    for values in loan_rows:
        row = dict(zip(_MOVEMENT_COLUMNS, values))
        for name in _BOUNDED_MOVEMENT_FIELDS:
            _scalar(row[name], name)
        context[row["movement_key"]] = row
    account_ids = sorted({row["account_id"] for row in context.values()}
                         - {account_info_value.account})
    accounts = {account_info_value.account: account_info_value}
    if len(account_ids) > MAX_TRANSFER_CONTEXT:
        raise ReadStoreError("account ledger account context exceeds its row bound")
    for start in range(0, len(account_ids), MEMBER_BATCH):
        batch = account_ids[start:start + MEMBER_BATCH]
        placeholders = ",".join("?" for _ in batch)
        selected = connection.execute(
            "SELECT account_id,CASE WHEN length(CAST(account_json AS BLOB))<=? "
            "THEN account_json END FROM account_ledger_component_state "
            f"WHERE account_id IN ({placeholders}) LIMIT ?",
            (MAX_COMPONENT_JSON_BYTES, *batch, len(batch) + 1)).fetchall()
        for account, encoded in selected:
            accounts[account] = _account_info(_json(
                encoded, dict, "counterpart identity"))
    return context, accounts, links, suggestions


def _tags(connection, keys):
    result = {}
    for start in range(0, len(keys), MEMBER_BATCH):
        batch = keys[start:start + MEMBER_BATCH]
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            "SELECT movement_key,"
            "CASE WHEN length(CAST(tag AS BLOB))<=? THEN tag END,source "
            "FROM movement_tags "
            f"WHERE movement_key IN ({placeholders}) LIMIT ?",
            (MAX_FORMATTER_SCALAR_BYTES, *batch,
             len(batch) * 200 + 1)).fetchall()
        if len(rows) > len(batch) * 200:
            raise ReadStoreError("account ledger tag context exceeds its row bound")
        for key, tag, source in rows:
            result.setdefault((_scalar(key, "tag movement key"),
                               _scalar(source, "tag source")), []).append(
                                   _scalar(tag, "tag"))
    return result


class _PageProjection:
    def __init__(self, revision, accounts, movements, rows, filenames,
                 tags, links, suggestions):
        self._revision, self._accounts = revision, accounts
        self._movements, self._rows, self._filenames = movements, rows, filenames
        self._tags, self._links, self._suggestions = tags, links, suggestions

    def movements(self):
        return list(self._movements)

    def account_info(self, account):
        if account not in self._accounts:
            raise AccountLedgerIdentityError("account context is unavailable")
        return self._accounts[account]

    def derived_category(self, movement):
        row = self._rows.get(movement.key)
        if row is None or not row["category"]:
            return None
        grades = [grade for grade in (row["category_grade"],
                                     row["subcategory_grade"]) if grade]
        ladder = ("verified", "corroborated", "unverified", "conflicted")
        grade = max(grades, key=ladder.index) if grades and all(
            item in ladder for item in grades) else ""
        return {"category": row["category"], "subcategory": row["subcategory"],
                "grade": grade,
                "by": (row["category_by"] if row["category_by"] ==
                       row["subcategory_by"] or not row["subcategory_by"] else "mixed")}

    def tags_of(self, movement):
        return list(self._tags.get((movement.key, "movement"), ()))

    def inherited_tags_of(self, movement):
        return list(self._tags.get((movement.key, "merchant"), ()))

    def transfer_links(self):
        return list(self._links)

    def transfer_suggestions(self):
        return list(self._suggestions)

    def linked_keys(self):
        return {key for row in self._links for key in (row["a"], row["b"])}

    def captured_filenames(self):
        return dict(self._filenames)


@dataclass(frozen=True)
class AccountLedgerPageParts:
    account_id: str
    info: AccountInfo
    number: str
    balance: object
    records: list[StatementRecord]
    coverage: dict
    overlap: dict
    recon_state: str
    projection: _PageProjection
    entries: list[dict]
    revision: str
    limit: int
    returned: int
    remaining: int
    next_cursor: str | None
    locale: str


def read_page(revision, account_id, locale, *, cursor_secret,
              limit=50, cursor=""):
    """Compose a complete account-ledger page from persisted component rows."""
    if not isinstance(account_id, str) or not account_id:
        raise AccountLedgerIdentityError("an exact account is required")
    _scalar(account_id, "account identity")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not isinstance(cursor_secret, bytes) or len(cursor_secret) < 32:
        raise ValueError("account ledger cursors require a private 256-bit key")
    state = revision.connection.execute(
        "SELECT locale,status,component_count,"
        "CASE WHEN length(CAST(coverage_json AS BLOB))<=? THEN coverage_json END,"
        "CASE WHEN length(CAST(overlap_json AS BLOB))<=? THEN overlap_json END,"
        "CASE WHEN length(CAST(records_json AS BLOB))<=? THEN records_json END,"
        "CASE WHEN length(CAST(account_json AS BLOB))<=? THEN account_json END,"
        "CASE WHEN length(CAST(balance_json AS BLOB))<=? THEN balance_json END "
        "FROM account_ledger_component_state WHERE account_id=?",
        (MAX_COMPONENT_JSON_BYTES,) * 5 + (account_id,)).fetchone()
    if state is None:
        raise AccountLedgerIdentityError(
            "the requested account could not be identified exactly")
    indexed_locale, status, total, coverage_raw, overlap_raw, records_raw, account_raw, balance_raw = state
    if indexed_locale != locale:
        raise ReadStoreError("account ledger index locale is stale")
    if status == "identity_error":
        raise AccountLedgerIdentityError(
            "the account ledger evidence belongs to another account")
    if status != "ready":
        raise ReadStoreError("account ledger component index is refused")
    info = _account_info(_json(account_raw, dict, "account identity"))
    for label in (info.account, info.name, info.number, info.kind, info.currency,
                  info.institution):
        _scalar(label, "account label")
    number = masked(info.number)
    if (info.account != account_id or not all((info.name, info.kind,
                                                info.currency, number))
            or info.kind not in ("depository", "liability", "investment")):
        raise AccountLedgerIdentityError(
            "the requested account does not have a complete safe identity")
    source = _source_identity(revision)
    anchor = _decode_cursor(cursor, account_id, source, cursor_secret) if cursor else None
    page, remaining = _index_page(revision, account_id, limit, anchor)
    members = []
    for _date, canonical, encoded in page:
        keys = _json(encoded, list, "component members")
        if (not keys or canonical not in keys
                or any(not isinstance(key, str) or not key for key in keys)):
            raise ReadStoreError("account ledger component members are invalid")
        for key in keys:
            _scalar(key, "component key")
        members.extend(keys)
    if len(members) > MAX_PAGE_MEMBERS or len(set(members)) != len(members):
        raise ReadStoreError("account ledger page members exceed their complete bound")
    rows = _movement_rows(revision.connection, members)
    entries = []
    for date, canonical, encoded in page:
        keys = _json(encoded, list, "component members")
        group = [_movement(rows[key]) for key in keys]
        if (rows[canonical]["occurred_at"] != date
                or any(movement.account != account_id for movement in group)):
            raise ReadStoreError("account ledger component ownership is invalid")
        entries.append({"movement": _movement(rows[canonical]), "members": group})
    records = _records(records_raw)
    if any(record.account != account_id for record in records):
        raise ReadStoreError("account ledger statement ownership is invalid")
    coverage = _json(coverage_raw, dict, "coverage")
    overlap = _json(overlap_raw, dict, "overlap")
    _evidence_shapes(records, coverage, overlap)
    balance_data = _json(balance_raw, dict, "balance")
    amount = _balance_shape(balance_data)
    recon_state = balance_data["reconciliation"]
    balance = SimpleNamespace(
        amount=amount,
        dated=balance_data["dated"], grade=balance_data["grade"],
        reconciliation=(None if recon_state == "not_established" else
                        SimpleNamespace(passed=recon_state == "reconciled")))
    doc_ids = {record.doc_id for record in records} | {
        movement.provenance.doc_id for entry in entries
        for movement in entry["members"] if movement.provenance.doc_id}
    filenames = _filenames(revision.connection, doc_ids)
    context, accounts, links, suggestions = _context(revision.connection, members, info)
    all_rows = {**rows, **context}
    projection = _PageProjection(
        revision, accounts, [_movement(row) for row in all_rows.values()],
        all_rows, filenames, _tags(revision.connection, members), links, suggestions)
    next_cursor = (_encode_cursor(account_id, source, page[-1][0], page[-1][1],
                                  cursor_secret) if remaining and page else None)
    return AccountLedgerPageParts(
        account_id, info, number, balance, records, coverage, overlap,
        recon_state, projection, entries, source["head"], limit, len(page),
        remaining, next_cursor, locale)


def _filenames(connection, doc_ids):
    if len(doc_ids) > MAX_PAGE_DOCUMENTS:
        raise ReadStoreError("account ledger document evidence exceeds its row bound")
    names = {}
    ordered = sorted(doc_ids)
    for start in range(0, len(ordered), MEMBER_BATCH):
        batch = ordered[start:start + MEMBER_BATCH]
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            "SELECT CASE WHEN length(CAST(d.doc_id AS BLOB))<=? THEN d.doc_id END,"
            "CASE WHEN length(CAST(d.filename AS BLOB))<=? THEN d.filename END "
            "FROM documents d INDEXED BY documents_by_doc "
            f"WHERE d.doc_id IN ({placeholders}) "
            "AND NOT EXISTS (SELECT 1 FROM documents newer "
            "INDEXED BY documents_by_doc WHERE newer.doc_id=d.doc_id "
            "AND newer.source_sequence>d.source_sequence) LIMIT ?",
            (MAX_FORMATTER_SCALAR_BYTES, MAX_FORMATTER_SCALAR_BYTES,
             *batch, MAX_PAGE_DOCUMENTS + 1)).fetchall()
        if len(rows) > MAX_PAGE_DOCUMENTS:
            raise ReadStoreError("account ledger document evidence exceeds its row bound")
        for doc_id, filename in rows:
            names[_scalar(doc_id, "document identity")] = _scalar(
                filename, "filename")
    return names
