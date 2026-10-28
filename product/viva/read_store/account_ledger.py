"""Bounded per-account movement and statement components for ledger reads."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections import Counter
import json
from types import SimpleNamespace

from ..env import locale_from_env
from ..ingest.registry import BALANCE_IDENTITY, profile_for
from ..ingest.statement import period_from_model_json
from ..ledger.events import Provenance
from ..ledger.projection.movements import MovementInfo
from ..ledger.projection.accounts import account_info
from ..ledger.statements import AccountStatements, _record, _runs
from ..ledger.account_ledger_contract import (
    AccountLedgerIdentityError, _coverage, _deduplicate, _overlap)
from .store import ReadStoreError
from .document_index import (acquisition_scoped, account_acquisition_scoped, acquisition_currency, owned_read_rows, retained_input,
    READ_ACQUISITION_COLUMNS, READ_ACQUISITION_JOINS)


MAX_ACCOUNT_MOVEMENTS = 10_000
MAX_ACCOUNT_STATEMENTS = 2_000
MAX_ACCOUNT_EVIDENCE_DOCS = 12_000
MAX_OWNERSHIP_ROWS = 2_000
OWNERSHIP_BATCH = 400
MAX_SAME_DAY_PAIRS = 100_000
MAX_LEDGER_ACCOUNTS = 2_000
MAX_INDEX_COMPONENTS = 100_000
MAX_COMPONENT_JSON_BYTES = 1_000_000
MAX_STATEMENT_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class AccountLedgerComponents:
    movements: list[MovementInfo]
    statements: AccountStatements | None
    entries: list[dict]
    coverage: dict
    overlap: dict


def _movements(connection, account_id: str):
    columns = (
        "movement_key", "account_id", "account_kind", "occurred_at",
        "amount_text", "currency", "description", "provenance_doc_id",
        "provenance_page", "provenance_region", "provenance_note",
        "linked", "nature", "nature_reason", "provisional", "ruling_account")
    rows = connection.execute(
        f"SELECT {','.join(columns)} FROM movements "
        "INDEXED BY movements_by_account_ledger_order WHERE account_id=? "
        "ORDER BY occurred_at DESC,movement_key DESC LIMIT ?",
        (account_id, MAX_ACCOUNT_MOVEMENTS + 1)).fetchall()
    if len(rows) > MAX_ACCOUNT_MOVEMENTS:
        raise ReadStoreError("account ledger movements exceed their row bound")
    return [MovementInfo(
        key=key, account=account, kind=kind, date=occurred,
        amount=Decimal(amount), currency=currency, description=description,
        provenance=Provenance(doc, page, region, note), linked=bool(linked),
        nature=nature, nature_reason=reason, provisional=bool(provisional),
        ruling_account=ruling)
        for (key, account, kind, occurred, amount, currency, description,
             doc, page, region, note, linked, nature, reason, provisional,
             ruling) in rows]


@account_acquisition_scoped
def _statements(revision, account_id: str, locale: str):
    connection=revision.connection
    currency=acquisition_currency(revision,account_id)
    rows = owned_read_rows(revision,
        "SELECT p.doc_id,d.doc_type,"
        "CASE WHEN length(CAST(r.response_text AS BLOB))<=? THEN r.response_text END,"
        "p.closing_amount_text,"
        "p.period_end"+READ_ACQUISITION_COLUMNS+"FROM statement_periods p "
        "INDEXED BY statement_periods_by_account_date "
        "JOIN documents d INDEXED BY documents_by_doc ON d.doc_id=p.doc_id "
        "JOIN document_reads r INDEXED BY document_reads_by_doc_phase_source "
        "ON r.doc_id=p.doc_id AND r.phase='extract' AND r.parse_ok=1 "
        +READ_ACQUISITION_JOINS+"WHERE p.account_id=? "
        "AND NOT EXISTS (SELECT 1 FROM documents newer "
        "WHERE newer.doc_id=d.doc_id "
        "AND newer.source_sequence>d.source_sequence) "
        "AND NOT EXISTS (SELECT 1 FROM statement_periods newer "
        "WHERE newer.doc_id=p.doc_id AND newer.account_id=p.account_id "
        "AND newer.source_sequence>p.source_sequence) "
        "AND NOT EXISTS (SELECT 1 FROM document_reads newer "
        "WHERE newer.doc_id=r.doc_id AND newer.phase='extract' "
        "AND newer.parse_ok=1 AND newer.source_sequence>r.source_sequence) "
        "ORDER BY p.period_end DESC,p.source_sequence DESC LIMIT ?",
        (MAX_STATEMENT_RESPONSE_BYTES, account_id, MAX_ACCOUNT_STATEMENTS + 1))
    if len(rows) > MAX_ACCOUNT_STATEMENTS:
        raise ReadStoreError("account ledger statements exceed their row bound")
    records = []
    for doc, doc_type, reply, accepted_amount, accepted_date, witness in rows:
        reply,parse_locale,parse_currency,_acquisition=retained_input(revision,witness,doc,reply,locale,currency)
        if reply is None:
            raise ReadStoreError("account ledger statement response exceeds its byte bound")
        profile = profile_for(doc_type)
        if profile is None or profile.identity != BALANCE_IDENTITY:
            continue
        try:
            period = period_from_model_json(reply, parse_locale, parse_currency)
        except Exception as exc:
            raise ReadStoreError("account ledger statement period is invalid") from exc
        if period is None:
            continue
        record = _record(doc, account_id, period,
                         (Decimal(accepted_amount), accepted_date))
        if record is not None:
            records.append(record)
    records.sort(key=lambda record: (record.opening_date, record.closing_date))
    return (AccountStatements(account_id, records, _runs(records))
            if records else None)


@acquisition_scoped
def _check_ownership(revision, account_id: str, movements, records, locale: str):
    connection=revision.connection
    doc_ids = {record.doc_id for record in records} | {
        movement.provenance.doc_id for movement in movements
        if movement.provenance.doc_id}
    if len(doc_ids) > MAX_ACCOUNT_EVIDENCE_DOCS:
        raise ReadStoreError("account ledger evidence exceeds its document bound")
    ordered = sorted(doc_ids)
    seen = 0
    for start in range(0, len(ordered), OWNERSHIP_BATCH):
        batch = ordered[start:start + OWNERSHIP_BATCH]
        placeholders = ",".join("?" for _ in batch)
        rows = owned_read_rows(revision,
            "SELECT p.doc_id,p.account_id,d.doc_type,"
            "CASE WHEN length(CAST(r.response_text AS BLOB))<=? THEN r.response_text END,"
            "p.closing_amount_text,p.period_end,"
            "(SELECT a.currency FROM accounts a INDEXED BY accounts_by_identity_source "
            "WHERE a.account_id=p.account_id AND a.event_type='AccountOpened' "
            "ORDER BY a.source_sequence DESC LIMIT 1)"+READ_ACQUISITION_COLUMNS+
            "FROM statement_periods p INDEXED BY statement_periods_by_document_source "
            "JOIN documents d INDEXED BY documents_by_doc ON d.doc_id=p.doc_id "
            "JOIN document_reads r INDEXED BY document_reads_by_doc_phase_source "
            "ON r.doc_id=p.doc_id AND r.phase='extract' AND r.parse_ok=1 "
            +READ_ACQUISITION_JOINS+f"WHERE p.doc_id IN ({placeholders}) AND p.account_id<>? "
            "AND NOT EXISTS (SELECT 1 FROM statement_periods newer "
            "WHERE newer.doc_id=p.doc_id AND newer.account_id=p.account_id "
            "AND newer.source_sequence>p.source_sequence) "
            "AND NOT EXISTS (SELECT 1 FROM documents newer "
            "WHERE newer.doc_id=d.doc_id AND newer.source_sequence>d.source_sequence) "
            "AND NOT EXISTS (SELECT 1 FROM document_reads newer "
            "WHERE newer.doc_id=r.doc_id AND newer.phase='extract' "
            "AND newer.parse_ok=1 AND newer.source_sequence>r.source_sequence) "
            "LIMIT ?",
            (MAX_STATEMENT_RESPONSE_BYTES, *batch, account_id,
             MAX_OWNERSHIP_ROWS - seen + 1))
        seen += len(rows)
        if seen > MAX_OWNERSHIP_ROWS:
            raise ReadStoreError("account ledger ownership exceeds its row bound")
        for doc, other, doc_type, reply, amount, dated, currency, witness in rows:
            reply,parse_locale,parse_currency,_acquisition=retained_input(revision,witness,doc,reply,locale,currency or 'USD')
            if reply is None:
                raise ReadStoreError("account ledger ownership response exceeds its byte bound")
            profile = profile_for(doc_type)
            if profile is None or profile.identity != BALANCE_IDENTITY:
                continue
            try:
                period = period_from_model_json(reply, parse_locale, parse_currency)
            except Exception as exc:
                raise ReadStoreError("account ledger ownership period is invalid") from exc
            if period is None:
                continue
            if _record(doc, other, period, (Decimal(amount), dated)) is not None:
                raise AccountLedgerIdentityError(
                    "the account ledger evidence belongs to another account")


@account_acquisition_scoped
def components(revision, account_id: str, *, locale: str = "en-US"):
    """Resolve one account's deduplicated components before any page boundary."""
    if not isinstance(account_id, str) or not account_id:
        raise AccountLedgerIdentityError("an exact account is required")
    movements = _movements(revision.connection, account_id)
    per_day = Counter(movement.date for movement in movements)
    if sum(count * (count - 1) // 2 for count in per_day.values()) > MAX_SAME_DAY_PAIRS:
        raise ReadStoreError("account ledger overlap candidates exceed their pair bound")
    statements = _statements(revision, account_id, locale)
    records = list(statements.records) if statements else []
    _check_ownership(revision, account_id, movements, records, locale)
    coverage = _coverage(records, list(statements.runs) if statements else [])
    overlap = _overlap(records)
    entries, deduplication = _deduplicate(movements, records)
    overlap["deduplication"] = deduplication
    return AccountLedgerComponents(movements, statements, entries,
                                   coverage, overlap)


def _encoded(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_COMPONENT_JSON_BYTES:
        raise ReadStoreError("account ledger component payload exceeds its byte bound")
    return encoded


@acquisition_scoped
def materialize_component_index(revision):
    """Publish deduplicated component identities within the SQL generation."""
    from .store import _PublicationReadContext
    if type(revision) is not _PublicationReadContext:
        raise ReadStoreError('component publication requires an owned publication context')
    connection=revision.connection
    try:
        locale = locale_from_env()
    except SystemExit as exc:
        raise ReadStoreError("account ledger locale is invalid") from exc
    account_rows = connection.execute(
        "SELECT DISTINCT account_id FROM accounts WHERE event_type='AccountOpened' "
        "ORDER BY account_id LIMIT ?", (MAX_LEDGER_ACCOUNTS + 1,)).fetchall()
    if len(account_rows) > MAX_LEDGER_ACCOUNTS:
        raise ReadStoreError("account ledger identities exceed their generation bound")
    from .held import _identity_core
    from .store import ReadRevision
    identity = _identity_core(connection, "9999-12-31")
    balances = ReadRevision._load_goal_account_balances(
        SimpleNamespace(connection=connection),
        as_of="9999-12-31", limit=MAX_LEDGER_ACCOUNTS * 5)
    observations = connection.execute(
        "SELECT account_id,event_type FROM balance_observations "
        "WHERE event_type IN ('OpeningBalanceObserved','ClosingBalanceObserved') "
        "GROUP BY account_id,event_type LIMIT ?",
        (MAX_LEDGER_ACCOUNTS * 2 + 1,)).fetchall()
    if len(observations) > MAX_LEDGER_ACCOUNTS * 2:
        raise ReadStoreError("account ledger observations exceed their generation bound")
    observed = {}
    for account, kind in observations:
        observed.setdefault(account, set()).add(kind)
    connection.execute("DELETE FROM account_ledger_component_index")
    connection.execute("DELETE FROM account_ledger_component_state")
    total = 0
    for (account_id,) in account_rows:
        try:
            result = components(revision,
                                account_id, locale=locale)
            coverage = _encoded(result.coverage)
            overlap = _encoded(result.overlap)
            records = _encoded([{
                "doc_id": record.doc_id,
                "account": record.account,
                "opening_date": record.opening_date,
                "opening_amount": str(record.opening_amount),
                "closing_date": record.closing_date,
                "closing_amount": str(record.closing_amount),
            } for record in (result.statements.records if result.statements else ())])
            account = _encoded(vars(account_info(identity, account_id)))
            value = balances.get(account_id)
            if value is None:
                raise ReadStoreError("account ledger balance input is missing")
            observed_kinds = observed.get(account_id, set())
            reconciled = {"OpeningBalanceObserved", "ClosingBalanceObserved"} <= observed_kinds
            balance = _encoded({
                "amount": str(value["amount"]), "dated": value["dated"],
                "grade": value["grade"],
                "reconciliation": (
                    "reconciled" if reconciled and value["grade"] in
                    ("verified", "corroborated") else
                    "conflicted" if reconciled else "not_established"),
            })
            index_rows = [
                (account_id, entry["movement"].date, entry["movement"].key,
                 _encoded([member.key for member in entry["members"]]))
                for entry in result.entries]
        except AccountLedgerIdentityError:
            connection.execute(
                "INSERT INTO account_ledger_component_state VALUES(?,?,?,?,?,?,?,?,?)",
                (account_id, locale, "identity_error", 0, "{}", "{}", "[]", "{}", "{}"))
            continue
        except ReadStoreError as exc:
            if "bound" not in str(exc):
                raise
            connection.execute(
                "INSERT INTO account_ledger_component_state VALUES(?,?,?,?,?,?,?,?,?)",
                (account_id, locale, "refused", 0, "{}", "{}", "[]", "{}", "{}"))
            continue
        total += len(result.entries)
        if total > MAX_INDEX_COMPONENTS:
            raise ReadStoreError("account ledger components exceed their generation bound")
        connection.execute(
            "INSERT INTO account_ledger_component_state VALUES(?,?,?,?,?,?,?,?,?)",
            (account_id, locale, "ready", len(result.entries),
             coverage, overlap, records, account, balance))
        connection.executemany(
            "INSERT INTO account_ledger_component_index VALUES(?,?,?,?)",
            index_rows)
