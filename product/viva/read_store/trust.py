"""Complete bounded Trust inputs from an immutable SQL revision."""

from __future__ import annotations

import json
from types import SimpleNamespace

from .store import ReadStoreError
from .scalar_bounds import MAX_SCALAR_BYTES, refuse as refuse_scalars

MAX_TRUST_EXCHANGES = 10_000
MAX_TRUST_BODY_BYTES = 1_000_000


def outbound_events(revision):
    model_lengths = ",".join(
        f"coalesce(length(CAST(json_extract(body_json,'$.{name}') AS BLOB)),0)"
        for name in ("model", "resolved_model", "phase", "model_role"))
    rows = revision.connection.execute(
        "SELECT CASE WHEN length(CAST(occurred_at AS BLOB))<=? "
        "THEN occurred_at END,CASE WHEN length(CAST(body_json AS BLOB))>? "
        "THEN NULL WHEN max(" + model_lengths + ")>? THEN NULL "
        "ELSE body_json END FROM document_reads "
        "INDEXED BY document_reads_by_source ORDER BY source_sequence LIMIT ?",
        (MAX_SCALAR_BYTES, MAX_TRUST_BODY_BYTES, MAX_SCALAR_BYTES,
         MAX_TRUST_EXCHANGES + 1,)).fetchall()
    if len(rows) > MAX_TRUST_EXCHANGES:
        raise ReadStoreError("Trust exchange history exceeds its read bound")
    refuse_scalars([(occurred,) for occurred, _body in rows],
                   ("occurred_at",), label="Trust date label")
    events = []
    for occurred_at, encoded in rows:
        if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > MAX_TRUST_BODY_BYTES:
            raise ReadStoreError("Trust exchange body exceeds its byte bound")
        try:
            body = json.loads(encoded)
        except (TypeError, ValueError) as exc:
            raise ReadStoreError("Trust exchange body is invalid") from exc
        if not isinstance(body, dict):
            raise ReadStoreError("Trust exchange body has the wrong shape")
        events.append(SimpleNamespace(event_type="ReadRecorded", occurred_at=occurred_at,
                                      body=body))
    return events


def has_agent_actions(revision):
    return revision.connection.execute(
        "SELECT 1 FROM agent_action_history INDEXED BY agent_actions_by_order "
        "ORDER BY occurred_at DESC,source_sequence DESC LIMIT 1").fetchone() is not None
