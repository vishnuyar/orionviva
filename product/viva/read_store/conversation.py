"""Durable conversation inputs from one immutable SQL revision."""

from __future__ import annotations

import json

from .store import ReadStoreError
from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars

MAX_CONVERSATION_EVENTS = 10_000
MAX_CONVERSATION_ROWS = 10_000
MAX_CONVERSATION_BODY_BYTES = 1_000_000


def _body(encoded):
    if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > MAX_CONVERSATION_BODY_BYTES:
        raise ReadStoreError("conversation body exceeds its read bound")
    try:
        body = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ReadStoreError("conversation body is invalid") from exc
    if not isinstance(body, dict):
        raise ReadStoreError("conversation body has the wrong shape")
    return body


class SQLConversationProjection:
    """Supply the timeline protocol without reopening canonical or raw stores."""

    def __init__(self, revision, *, locale):
        self._revision = revision
        self.connection = revision.connection
        self._review = revision.review_projection(locale=locale)
        columns = ("doc_id", "filename")
        selected, bounds = scalar_selected(columns)
        documents = self.connection.execute(
            f"SELECT {selected} FROM documents INDEXED BY documents_by_source "
            "ORDER BY source_sequence LIMIT ?",
            (*bounds, MAX_CONVERSATION_ROWS + 1,)).fetchall()
        if len(documents) > MAX_CONVERSATION_ROWS:
            raise ReadStoreError("conversation documents exceed their read bound")
        refuse_scalars(documents, columns, label="conversation citation labels")
        self._documents = dict(documents)

    def __getattr__(self, name):
        return getattr(self._review, name)

    def captured_docs(self):
        return list(self._documents)

    def captured_filenames(self):
        return dict(self._documents)

    def _history(self, table):
        columns = ("h.event_type", "h.occurred_at", "a.event_id")
        selected, bounds = scalar_selected(columns)
        selected = selected.split(",")
        rows = self.connection.execute(
            f"SELECT {selected[0]},{selected[1]},"
            f"CASE WHEN length(CAST(h.body_json AS BLOB))<=? THEN h.body_json END,"
            f"{selected[2]} "
            f"FROM {table} h JOIN applied_events a ON a.sequence=h.source_sequence "
            "ORDER BY h.source_sequence LIMIT ?",
            (*bounds[:2], MAX_CONVERSATION_BODY_BYTES, bounds[2],
             MAX_CONVERSATION_EVENTS + 1,)).fetchall()
        if len(rows) > MAX_CONVERSATION_EVENTS:
            raise ReadStoreError("conversation history exceeds its read bound")
        refuse_scalars([row[:2] + row[3:] for row in rows], columns,
                       label="conversation history labels")
        return rows

    def conversation_turns(self):
        turns, indexes = [], {}
        for event_type, occurred_at, encoded, event_id in self._history("conversation_turn_history"):
            body = _body(encoded)
            identity = body.get("turn_id", "")
            if event_type == "ConversationTurnOpened":
                if identity and identity not in indexes:
                    indexes[identity] = len(turns)
                    turns.append({**body, "occurred_at": occurred_at, "event_id": event_id,
                                  "outcome": "stale", "message": "", "reason": "interrupted",
                                  "answer": {}, "proposal_id": ""})
            elif identity in indexes:
                turns[indexes[identity]].update({
                    "outcome": body.get("outcome", ""), "message": body.get("message", ""),
                    "reason": body.get("reason", ""), "answer": dict(body.get("answer") or {}),
                    "proposal_id": body.get("proposal_id", ""),
                    "settled_event_id": event_id})
        return turns

    def conversation_proposals(self):
        proposals = {}
        for event_type, occurred_at, encoded, event_id in self._history("conversation_proposal_history"):
            body = _body(encoded)
            identity = body.get("proposal_id", "")
            if event_type == "ConversationProposalRecorded":
                if identity and identity not in proposals:
                    proposals[identity] = {
                        **body, "occurred_at": occurred_at, "event_id": event_id,
                        "status": "open", "outcome": "proposal", "message": "", "reason": ""}
            elif identity in proposals and proposals[identity]["status"] == "open":
                proposals[identity].update({
                    "status": "resolved", "resolution_turn_id": body.get("turn_id", ""),
                    "outcome": body.get("outcome", ""), "message": body.get("message", ""),
                    "reason": body.get("reason", ""), "resolved_event_id": event_id})
        if len(proposals) > MAX_CONVERSATION_ROWS:
            raise ReadStoreError("conversation proposals exceed their read bound")
        return list(proposals.values())
