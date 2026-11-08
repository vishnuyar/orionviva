"""Compact accepted-read bindings for investment measurement composition."""
import json
from hashlib import sha256
from dataclasses import asdict, replace
from decimal import Decimal
from datetime import date, timedelta

from ..ledger.projection.investment_snapshots import (
    SnapshotBoundary, _statement_matches, terms_digest, add_missing_binding_barriers)

MAX_BINDINGS = 10000
MAX_BINDING_BYTES = 262144
MAX_BINDING_TOTAL_BYTES = 4_000_000


def _typed_segments(connection):
    from ..investment.events import decode_statement
    from ..investment.contracts import digest, EvidenceError
    rows = connection.execute("SELECT effective_from,effective_to,status,record_json,record_digest "
                              "FROM investment_evidence_statements WHERE facet='positions'").fetchall()
    segments = []
    for left, right, status, text, expected in rows:
        if type(text) is not str or len(text.encode()) > MAX_BINDING_BYTES:
            raise EvidenceError("investment source storage limit")
        statement = decode_statement(json.loads(text))
        if digest(statement) != expected:
            raise EvidenceError("investment source digest mismatch")
        segments.append((left, right, status, statement))
    return segments


def materialize(connection, events):
    """Bind the accepted source to the already validated native lifecycle table."""
    from ..ledger.projection.core import ProjectionCore
    from ..ledger.projection.measurements import MeasurementSources
    core = ProjectionCore(events, measurement_sources=MeasurementSources(validate_lifecycle=False))
    segments = _typed_segments(connection)
    typed_documents = {statement.account.document for _, _, _, statement in segments}
    add_missing_binding_barriers(core, (statement for _, _, _, statement in segments), events)
    points = sorted({"0001-01-01", *(left for left, _, _, _ in segments),
                     *((date.fromisoformat(right) + timedelta(days=1)).isoformat()
                       for _, right, _, _ in segments if right < "9999-12-31")})
    connection.execute("DELETE FROM investment_accepted_bindings")
    for state in core._acct.values():
        for boundary in state.investment_snapshots:
            if boundary.document in typed_documents:
                statuses = []
                for index, left in enumerate(points):
                    right = ((date.fromisoformat(points[index + 1]) - timedelta(days=1)).isoformat()
                             if index + 1 < len(points) else "9999-12-31")
                    sources = [(status, statement) for start, end, status, statement in segments
                               if start <= left <= end and statement.account.document == boundary.document]
                    matches = [(status, statement) for status, statement in sources
                               if _statement_matches(boundary, statement)]
                    status = (matches[0][0] if len(matches) == len(sources) == 1
                              else "retracted" if not sources else "unavailable")
                    statuses.append((left, right, status))
                boundary = replace(boundary, intervals=tuple(statuses))
            data = asdict(boundary)
            data.update(cash=str(boundary.cash), total=str(boundary.total), expected=[],
                        expected_count=boundary.position_count,
                        expected_digest=terms_digest(boundary.expected))
            encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
            if len(encoded.encode()) > MAX_BINDING_BYTES:
                raise ValueError("investment accepted binding storage limit")
            connection.execute("INSERT INTO investment_accepted_bindings VALUES(?,?,?,?,?)",
                               (boundary.sequence, boundary.account, boundary.document,
                                boundary.dated, encoded))


def load(connection, states, horizon):
    """Load compact bindings without an event-log read or a source-index replay."""
    from .store import ReadStoreError
    rows = _bounded_rows(connection)
    authority = connection.execute("SELECT source_count,source_head,binding_count,binding_digest "
                                   "FROM investment_binding_frontier WHERE singleton=1").fetchone()
    source = connection.execute("SELECT source_count,source_head FROM projection_meta WHERE singleton=1").fetchone()
    _load_verified_rows(rows, authority, source, states, horizon)


def _load_verified_rows(rows, authority, source, states, horizon):
    from .store import ReadStoreError
    if (authority is None or source is None or tuple(authority[:2]) != tuple(source)
            or type(authority[0]) is not int or authority[0] < 0
            or type(authority[1]) is not str or len(authority[1]) != 64
            or type(authority[2]) is not int or authority[2] != len(rows)
            or authority[3] != _binding_digest(rows)):
        raise ReadStoreError("investment accepted binding set is incomplete or changed")
    for sequence, account, document, dated, text in rows:
        if account not in states or dated > horizon:
            continue
        try:
            if type(text) is not str:
                raise ValueError("investment accepted binding byte bound")
            data = json.loads(text)
            if (data["sequence"], data["account"], data["document"], data["dated"]) != (sequence, account, document, dated):
                raise ValueError("investment accepted binding identity mismatch")
            if (type(data["expected_count"]) is not int or not 0 <= data["expected_count"] <= 1000
                    or type(data["expected_digest"]) is not str or len(data["expected_digest"]) != 64
                    or data["expected"] != [] or type(data["intervals"]) is not list):
                raise ValueError("invalid investment accepted binding shape")
            data.update(cash=Decimal(data["cash"]), total=Decimal(data["total"]),
                        expected=(), intervals=tuple(tuple(row) for row in data["intervals"]))
            boundary = SnapshotBoundary(**data)
            if not boundary.cash.is_finite() or not boundary.total.is_finite():
                raise ValueError("invalid investment accepted amount")
            states[account].investment_snapshots.append(boundary)
        except (ValueError, TypeError, KeyError, ArithmeticError) as error:
            raise ReadStoreError("invalid investment accepted binding") from error


def _bounded_rows(connection):
    from .store import ReadStoreError
    count, size = connection.execute("SELECT COUNT(*),COALESCE(SUM(length(CAST(binding_json AS BLOB))"
        "+length(CAST(account_id AS BLOB))+length(CAST(doc_id AS BLOB))+length(CAST(dated AS BLOB))),0) "
        "FROM investment_accepted_bindings").fetchone()
    if (type(count) is not int or not 0 <= count <= MAX_BINDINGS
            or type(size) is not int or not 0 <= size <= MAX_BINDING_TOTAL_BYTES):
        raise ReadStoreError("investment accepted binding set exceeds read bound")
    rows = connection.execute("SELECT source_sequence,"
        "CASE WHEN length(CAST(account_id AS BLOB))<=1024 THEN account_id END,"
        "CASE WHEN length(CAST(doc_id AS BLOB))<=1024 THEN doc_id END,"
        "CASE WHEN length(CAST(dated AS BLOB))<=64 THEN dated END,"
        "CASE WHEN length(CAST(binding_json AS BLOB))<=? THEN binding_json END "
        "FROM investment_accepted_bindings ORDER BY source_sequence LIMIT ?",
        (MAX_BINDING_BYTES, MAX_BINDINGS + 1)).fetchall()
    if len(rows) != count or any(type(row[0]) is not int or row[0] < 0
            or any(type(value) is not str or not value for value in row[1:]) for row in rows):
        raise ReadStoreError("investment accepted binding rows are incomplete or invalid")
    return rows


def _binding_digest(rows):
    digest = sha256(b"viva-investment-accepted-bindings-v1\0")
    for row in rows:
        encoded = json.dumps(tuple(row), separators=(",", ":"), ensure_ascii=False).encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def seal(connection, source_count=None, source_head=None):
    """Commit binding completeness atomically with its authenticated generation."""
    rows = _bounded_rows(connection)
    if source_count is None:
        source_count, source_head = connection.execute(
            "SELECT source_count,source_head FROM projection_meta WHERE singleton=1").fetchone()
    connection.execute("INSERT OR REPLACE INTO investment_binding_frontier VALUES(1,?,?,?,?)",
                       (source_count, source_head, len(rows), _binding_digest(rows)))


def captured_history_query(selected, bounds, horizon, position_limit):
    """One traced query captures bounded positions and complete binding authority."""
    gate = f"l.binding_count<={MAX_BINDINGS} AND l.binding_bytes<={MAX_BINDING_TOTAL_BYTES}"
    padding = ",NULL" * 9
    control_padding = ",NULL" * 6
    query = f"""WITH position_rows AS (
        SELECT {selected} FROM positions WHERE occurred_at<=?
        ORDER BY source_sequence LIMIT ?),
      binding_limits AS MATERIALIZED (
        SELECT COUNT(*) AS binding_count,
          COALESCE(SUM(length(CAST(binding_json AS BLOB))+length(CAST(account_id AS BLOB))
              +length(CAST(doc_id AS BLOB))+length(CAST(dated AS BLOB))),0) AS binding_bytes
        FROM investment_accepted_bindings),
      binding_rows AS (
        SELECT b.source_sequence,
          CASE WHEN {gate} AND length(CAST(b.account_id AS BLOB))<=1024 THEN b.account_id END AS account_id,
          CASE WHEN {gate} AND length(CAST(b.doc_id AS BLOB))<=1024 THEN b.doc_id END AS doc_id,
          CASE WHEN {gate} AND length(CAST(b.dated AS BLOB))<=64 THEN b.dated END AS dated,
          CASE WHEN {gate} AND length(CAST(b.binding_json AS BLOB))<={MAX_BINDING_BYTES} THEN b.binding_json END AS binding_json
        FROM investment_accepted_bindings b CROSS JOIN binding_limits l LIMIT {MAX_BINDINGS + 1}),
      binding_control AS (
        SELECT l.binding_count,l.binding_bytes,
          CASE WHEN typeof(f.source_count)='integer' AND f.source_count>=0 THEN f.source_count END AS source_count,
          CASE WHEN length(CAST(f.source_head AS BLOB))=64 THEN f.source_head END AS source_head,
          CASE WHEN typeof(f.binding_count)='integer' AND f.binding_count>=0 THEN f.binding_count END AS expected_count,
          CASE WHEN length(CAST(f.binding_digest AS BLOB))=64 THEN f.binding_digest END AS binding_digest,
          CASE WHEN typeof(m.source_count)='integer' AND m.source_count>=0 THEN m.source_count END AS native_count,
          CASE WHEN length(CAST(m.source_head AS BLOB))=64 THEN m.source_head END AS native_head
        FROM binding_limits l LEFT JOIN investment_binding_frontier f ON f.singleton=1
          LEFT JOIN projection_meta m ON m.singleton=1)
      SELECT 'position',* FROM position_rows
      UNION ALL SELECT 'binding',*{padding} FROM binding_rows
      UNION ALL SELECT 'control',*{control_padding} FROM binding_control"""
    return query, (*bounds, horizon, position_limit + 1)


def unpack_history(rows, states, horizon, position_limit):
    """Validate the bounded all-set capture before publishing any source binding."""
    from .store import ReadStoreError
    positions, bindings, controls = [], [], []
    if len(rows) > position_limit + MAX_BINDINGS + 3:
        raise ReadStoreError("investment history capture exceeds its row bound")
    for row in rows:
        if len(row) != 15:
            raise ReadStoreError("invalid investment history capture shape")
        if row[0] == "position":
            positions.append(tuple(row[1:]))
        elif row[0] == "binding":
            bindings.append(tuple(row[1:6]))
        elif row[0] == "control":
            controls.append(tuple(row[1:9]))
        else:
            raise ReadStoreError("unknown investment history capture kind")
    if len(positions) > position_limit:
        raise ReadStoreError(f"Overview position history exceeds its {position_limit}-row read bound")
    if len(controls) != 1:
        raise ReadStoreError("investment binding authority capture is incomplete")
    count, size, source_count, source_head, expected_count, expected_digest, native_count, native_head = controls[0]
    if (type(count) is not int or not 0 <= count <= MAX_BINDINGS
            or type(size) is not int or not 0 <= size <= MAX_BINDING_TOTAL_BYTES
            or len(bindings) != count or any(type(row[0]) is not int or row[0] < 0
                or any(type(value) is not str or not value for value in row[1:]) for row in bindings)):
        raise ReadStoreError("investment accepted binding capture exceeds its bound or is incomplete")
    bindings.sort(key=lambda row: row[0])
    _load_verified_rows(bindings, (source_count, source_head, expected_count, expected_digest),
                        (native_count, native_head), states, horizon)
    return positions
