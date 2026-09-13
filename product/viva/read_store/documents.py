"""SQL-native input adapter for the current Documents surface."""

from __future__ import annotations

from ..ingest.registry import (BALANCE_IDENTITY, BROKERAGE_IDENTITY,
                               identity_of_facts)
from ..ledger.identity import masked_label
from .held import (_bounded, _identity_core, _open_hold_rows,
                   held_items as sql_held_items)
from .store import ReadStoreError
from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars


CURRENT_EVIDENCE_BOUNDARY = "9999-12-31"
MAX_DOCUMENTS = 200
MAX_DOCUMENT_HISTORY = 10_000
MAX_DOCUMENT_READS = 10_000
MAX_DOCUMENT_CONTRIBUTIONS = 10_000
MAX_DOCUMENT_SCALAR_BYTES = 4_096


class SQLDocumentsProjection:
    """Supply the Documents surface from one immutable read revision."""

    def __init__(self, revision):
        self.connection = revision.connection
        self._boundary = CURRENT_EVIDENCE_BOUNDARY
        rows = _bounded(
            self.connection,
            "SELECT "
            "CASE WHEN length(CAST(doc_id AS BLOB))<=? THEN doc_id END,"
            "CASE WHEN length(CAST(doc_type AS BLOB))<=? THEN doc_type END,"
            "CASE WHEN length(CAST(filename AS BLOB))<=? THEN filename END "
            "FROM documents INDEXED BY documents_by_source "
            "ORDER BY source_sequence LIMIT ?",
            (MAX_DOCUMENT_SCALAR_BYTES,) * 3,
            MAX_DOCUMENT_HISTORY, "Documents capture history")
        self._captured: dict[str, str] = {}
        self._filenames: dict[str, str] = {}
        for doc_id, doc_type, filename in rows:
            if any(value is None for value in (doc_id, doc_type, filename)):
                raise ReadStoreError("Documents capture field exceeds its scalar byte bound")
            self._captured[doc_id] = doc_type
            self._filenames[doc_id] = filename
        if len(self._captured) > MAX_DOCUMENTS:
            raise ReadStoreError(
                f"Documents output exceeds its {MAX_DOCUMENTS}-document bound")

        read_columns = ("doc_id", "phase", "parse_ok")
        selected, bounds = scalar_selected(read_columns, ("parse_ok",))
        reads = _bounded(
            self.connection,
            f"SELECT {selected} FROM document_reads "
            "INDEXED BY document_reads_by_source ORDER BY source_sequence LIMIT ?",
            bounds, MAX_DOCUMENT_READS, "Documents reading history")
        refuse_scalars(reads, read_columns, ("parse_ok",),
                       label="Documents reading labels")
        self._attempted = {doc_id for doc_id, _phase, _parsed in reads}
        self._parsed = {doc_id for doc_id, phase, parsed in reads
                        if phase == "extract" and parsed}

        regular, activity = _open_hold_rows(self.connection, self._boundary)
        self._regular_holds = regular
        self._activity_holds = activity
        selected, bounds = scalar_selected(("doc_id",))
        posted_rows = _bounded(
            self.connection,
            f"SELECT {selected} FROM posted_document_events "
            "INDEXED BY posted_document_events_by_doc_date ORDER BY doc_id LIMIT ?",
            bounds, MAX_DOCUMENT_CONTRIBUTIONS, "Documents posted identities")
        refuse_scalars(posted_rows, ("doc_id",), label="Documents posted identity")
        self._posted = {row[0] for row in posted_rows}
        self._core = _identity_core(self.connection, self._boundary)

    def captured_docs(self) -> dict[str, str]:
        return dict(self._captured)

    def captured_filenames(self) -> dict[str, str]:
        return dict(self._filenames)

    def read_attempted_docs(self) -> set[str]:
        return set(self._attempted)

    def read_parsed_docs(self) -> set[str]:
        return set(self._parsed)

    def posted_doc_ids(self) -> set[str]:
        return set(self._posted)

    def is_resolved(self, doc_id: str) -> bool:
        return doc_id in self._posted or any(
            row[2] == doc_id for row in self._regular_holds)

    @staticmethod
    def _hold_body(row) -> dict:
        _sequence, _event_type, doc_id, _occurred, reason, facts, finding = row
        return {"doc_id": doc_id, "reason": reason, "facts": facts,
                "finding": finding}

    def open_holds(self) -> list[dict]:
        return [self._hold_body(row) for row in self._regular_holds]

    def open_activity_holds(self) -> list[dict]:
        return [self._hold_body(row) for row in self._activity_holds]

    def document_contributions(self) -> dict[str, dict]:
        columns = ("doc_id", "account_id", "closing_amount_text", "period_end")
        selected, bounds = scalar_selected(columns)
        rows = _bounded(
            self.connection,
            f"SELECT {selected} "
            "FROM statement_periods INDEXED BY statement_periods_by_document_source "
            "ORDER BY doc_id,source_sequence LIMIT ?",
            bounds, MAX_DOCUMENT_CONTRIBUTIONS, "Documents contribution history")
        refuse_scalars(rows, columns, label="Documents contribution labels")
        found = {}
        for doc_id, account, amount, as_of in rows:
            state = self._core._acct.get(account)
            found[doc_id] = {
                "account": account,
                "currency": "" if state is None else state.currency,
                "amount": amount,
                "as_of": as_of,
            }
        return found

    def document_holds(self) -> list[dict]:
        primary = []
        for item in sql_held_items(self.connection, as_of=self._boundary):
            primary.append({key: item[key] for key in (
                "doc_id", "reason", "account_ref", "account_label",
                "currency", "opening_amount", "opening_date",
                "closing_amount", "closing_date", "period", "held_balance",
                "transactions", "finding")})
        other = []
        for row in (*self._regular_holds, *self._activity_holds):
            _sequence, event_type, doc_id, _occurred, reason, facts, finding = row
            identity = identity_of_facts(facts)
            if (event_type != "BrokerageActivityHeld" and reason != "activity"
                    and (identity == BALANCE_IDENTITY or
                         (identity == BROKERAGE_IDENTITY and reason == "identity"))):
                continue
            other.append({
                "doc_id": doc_id,
                "doc_type": facts.get("doc_type", "brokerage_statement"
                                      if event_type == "BrokerageActivityHeld"
                                      or reason == "activity" else "unknown"),
                "reason": "activity" if event_type == "BrokerageActivityHeld"
                or reason == "activity" else reason,
                "account_ref": masked_label(
                    facts.get("account_ref", "") or facts.get("employer", "")
                ).replace("••••", "····"),
                "message": (finding or {}).get("message", ""),
            })
        return [*primary, *other]
