"""SQL-backed protocol for the current GoalsAndPlans surface."""

from __future__ import annotations

import json
from types import SimpleNamespace

from .store import ReadStoreError
from .scalar_bounds import (MAX_SCALAR_BYTES, selected as scalar_selected,
                            refuse as refuse_scalars)


MAX_PLAN_DOCUMENTS = 10_000
MAX_GOAL_PROPOSAL_EVENTS = 10_000
MAX_OPEN_GOAL_PROPOSALS = 200
MAX_PROPOSAL_BYTES = 1_000_000
CURRENT_EVIDENCE_BOUNDARY = "9999-12-31"


def _view(row):
    if isinstance(row, dict):
        return SimpleNamespace(**{key: _view(value) for key, value in row.items()})
    if isinstance(row, (tuple, list)):
        return tuple(_view(item) for item in row)
    return row


class SQLPlansProjection:
    """Supply GoalsAndPlans.v1 from one immutable read revision."""

    def __init__(self, revision):
        self._revision = revision
        self.connection = revision.connection
        columns = ("doc_id", "filename")
        selected, bounds = scalar_selected(columns)
        rows = self.connection.execute(
            f"SELECT {selected} FROM documents INDEXED BY documents_by_source "
            "ORDER BY source_sequence LIMIT ?",
            (*bounds, MAX_PLAN_DOCUMENTS + 1,)).fetchall()
        if len(rows) > MAX_PLAN_DOCUMENTS:
            raise ReadStoreError("Plans document history exceeds its read bound")
        refuse_scalars(rows, columns, label="Plans document labels")
        self._documents = {doc_id: filename for doc_id, filename in rows}

    def captured_docs(self):
        return list(self._documents)

    def captured_filenames(self):
        return dict(self._documents)

    def goals(self, today):
        rows = self._revision.current_goal_views(
            today=today, evidence_as_of=CURRENT_EVIDENCE_BOUNDARY)
        for row in rows:
            for account in row["available_accounts"]:
                account["as_of"] = ""
        return [_view(row) for row in rows]

    def goal(self, goal_id, today):
        found = next((row for row in self.goals(today)
                      if row.goal_id == goal_id), None)
        if found is None:
            raise KeyError(goal_id)
        return found

    def open_goal_proposals(self):
        columns = ("h.event_type", "h.proposal_id", "h.occurred_at", "a.event_id")
        selected, bounds = scalar_selected(columns)
        expressions = selected.split(",")
        body_lengths = ",".join(
            f"coalesce(length(CAST(json_extract(h.body_json,'$.{name}') AS BLOB)),0)"
            for name in ("proposal_id", "verb", "summary", "outcome", "reason"))
        rows = self.connection.execute(
            f"SELECT {expressions[0]},{expressions[1]},{expressions[2]},"
            "CASE WHEN length(CAST(h.body_json AS BLOB))<=? AND max(" +
            body_lengths + ")<=? THEN h.body_json END,"
            f"{expressions[3]} FROM goal_proposal_history h "
            "JOIN applied_events a ON a.sequence=h.source_sequence "
            "ORDER BY h.source_sequence LIMIT ?",
            (*bounds[:3], MAX_PROPOSAL_BYTES, MAX_SCALAR_BYTES, bounds[3],
             MAX_GOAL_PROPOSAL_EVENTS + 1,)).fetchall()
        if len(rows) > MAX_GOAL_PROPOSAL_EVENTS:
            raise ReadStoreError("Plans proposal history exceeds its read bound")
        refuse_scalars([row[:3] + row[4:] for row in rows], columns,
                       label="Plans proposal labels")
        proposals = {}
        for event_type, proposal_id, occurred_at, encoded, event_id in rows:
            if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > MAX_PROPOSAL_BYTES:
                raise ReadStoreError("Plans proposal body exceeds its byte bound")
            try:
                body = json.loads(encoded)
            except (TypeError, ValueError) as exc:
                raise ReadStoreError("Plans proposal body is invalid") from exc
            if not isinstance(body, dict):
                raise ReadStoreError("Plans proposal body has the wrong shape")
            if event_type == "GoalProposalRecorded":
                if proposal_id and proposal_id not in proposals:
                    proposals[proposal_id] = {
                        **body, "occurred_at": occurred_at,
                        "event_id": event_id, "status": "open",
                        "outcome": "proposal", "reason": ""}
            elif event_type == "GoalProposalResolved":
                proposal = proposals.get(proposal_id)
                if proposal is not None and proposal["status"] == "open":
                    proposal.update({
                        "status": "resolved",
                        "outcome": body.get("outcome", ""),
                        "reason": body.get("reason", ""),
                        "resolved_event_id": event_id})
        opened = [row for row in proposals.values() if row["status"] == "open"]
        if len(opened) > MAX_OPEN_GOAL_PROPOSALS:
            raise ReadStoreError("Plans open proposals exceed their output bound")
        return opened
