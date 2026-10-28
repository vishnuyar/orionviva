"""Complete bounded Trust inputs from an immutable SQL revision."""

from __future__ import annotations

import json
from types import SimpleNamespace

from .store import ReadStoreError
from .scalar_bounds import MAX_SCALAR_BYTES, refuse as refuse_scalars

MAX_TRUST_EXCHANGES = 10_000
MAX_TRUST_BODY_BYTES = 1_000_000


def outbound_events(revision):
    """Fetch a complete bounded union of phase receipts and response metadata."""
    from ..extraction_responses import RESPONSE_EVENT

    phase_scalars = ("model", "resolved_model", "phase", "model_role")
    response_scalars = ("doc_id", "extraction_id", "phase", "response_id", "cost_usd")

    def bounded_body(column, names):
        lengths = ",".join(
            f"coalesce(length(CAST(json_extract({column},'$.{name}') AS BLOB)),0)"
            for name in names)
        return (f"CASE WHEN length(CAST({column} AS BLOB))>? THEN NULL "
                f"WHEN max({lengths})>? THEN NULL ELSE {column} END")

    date = ("CASE WHEN length(CAST(occurred_at AS BLOB))<=? "
            "THEN occurred_at END")
    encoded_phase = bounded_body("body_json", phase_scalars)
    encoded_response = bounded_body("summary_json", response_scalars)
    rows = revision.connection.execute(
        "SELECT source_sequence,event_type,NULL," + date + "," + encoded_phase +
        " FROM document_reads INDEXED BY document_reads_by_source UNION ALL "
        "SELECT source_sequence,event_type,CASE WHEN "
        "length(CAST(event_id AS BLOB))<=? THEN event_id END," + date + "," +
        encoded_response + " FROM extraction_responses "
        "INDEXED BY extraction_responses_by_source ORDER BY source_sequence LIMIT ?",
        (MAX_SCALAR_BYTES, MAX_TRUST_BODY_BYTES, MAX_SCALAR_BYTES,
         MAX_SCALAR_BYTES, MAX_SCALAR_BYTES, MAX_TRUST_BODY_BYTES,
         MAX_SCALAR_BYTES, MAX_TRUST_EXCHANGES + 1)).fetchall()
    if len(rows) > MAX_TRUST_EXCHANGES:
        raise ReadStoreError("Trust exchange history exceeds its read bound")
    refuse_scalars([(occurred,) for _, _, _, occurred, _ in rows],
                   ("occurred_at",), label="Trust date label")
    events = []
    for _, kind, event_id, occurred_at, encoded in rows:
        if not isinstance(occurred_at, str):
            raise ReadStoreError("Trust date label exceeds its scalar byte bound")
        if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > MAX_TRUST_BODY_BYTES:
            raise ReadStoreError("Trust exchange body exceeds its byte bound")
        try:
            body = json.loads(encoded)
        except (TypeError, ValueError) as exc:
            raise ReadStoreError("Trust exchange body is invalid") from exc
        if not isinstance(body, dict):
            raise ReadStoreError("Trust exchange body has the wrong shape")
        if kind == RESPONSE_EVENT:
            if not isinstance(event_id, str) or not event_id:
                raise ReadStoreError("Trust response identity exceeds its scalar byte bound")
            events.append(SimpleNamespace(event_type=kind, event_id=event_id,
                occurred_at=occurred_at, body={}, response_summary=body))
        else:
            events.append(SimpleNamespace(event_type=kind, occurred_at=occurred_at,
                                          body=body))
    return events


def has_agent_actions(revision):
    return revision.connection.execute(
        "SELECT 1 FROM agent_action_history INDEXED BY agent_actions_by_order "
        "ORDER BY occurred_at DESC,source_sequence DESC LIMIT 1").fetchone() is not None
