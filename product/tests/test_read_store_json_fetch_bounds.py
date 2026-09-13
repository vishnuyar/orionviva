"""JSON read inputs refuse before an oversized SQL body reaches Python."""

import json

import pytest

from viva.ledger.events import (conversation_proposal_recorded,
                                conversation_turn_opened, goal_proposal_recorded,
                                read_recorded)
from viva.read_store.store import ReadStoreError
from viva.read_store.trust import outbound_events
from viva.vault import Vault


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("route,table,event", [
    ("trust", "document_reads", read_recorded(
        "doc-1", "route", "prompt", "text", "reply", 0, 1, 1, True,
        None, "2026-08-29")),
    ("conversation", "conversation_turn_history", conversation_turn_opened(
        "turn-1", "ask", "Question?", "2026-08-29")),
    ("conversation_proposal", "conversation_proposal_history",
     conversation_proposal_recorded(
         "proposal-1", "turn-1", "question-1", "Proposal",
         {"kind": "correction"}, {"amount": "123.45"}, "2026-08-29")),
    ("plans", "goal_proposal_history", goal_proposal_recorded(
        "proposal-1", "create", "Proposal",
        {"goal_id": "goal-1", "title": "Synthetic", "currency": "USD",
         "target_amount": "123.45"}, {"amount": "123.45"}, "2026-08-29")),
])
def test_route_body_byte_bound_is_enforced_in_select_before_decode(
        tmp_path, glyph, route, table, event):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(event)
    vault.synchronize_read_store()
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            f"SELECT body_json FROM {table} LIMIT 1").fetchone()[0]
    base = json.loads(original)
    bound = 1_000_000
    shell = json.dumps({**base, "padding": ""}, ensure_ascii=False)
    room = bound - len(shell.encode("utf-8"))
    glyph_bytes = len(glyph.encode("utf-8"))
    padding = glyph * (room // glyph_bytes) + "X" * (room % glyph_bytes)
    def read(revision):
        if route == "trust":
            return outbound_events(revision)
        if route == "conversation":
            return revision.conversation_projection(locale="en-US").conversation_turns()
        if route == "conversation_proposal":
            return revision.conversation_projection(locale="en-US").conversation_proposals()
        return revision.plans_projection().open_goal_proposals()
    for extra in ("", "X"):
        encoded = json.dumps({**base, "padding": padding + extra},
                             ensure_ascii=False)
        assert len(encoded.encode("utf-8")) == bound + len(extra)
        vault.read_store.publish(lambda connection: connection.execute(
            f"UPDATE {table} SET body_json=?", (encoded,)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            old_select = revision.connection.execute(
                f"SELECT body_json FROM {table} LIMIT 1").fetchone()[0]
            assert json.loads(old_select) == json.loads(encoded)
            traced = []
            revision.connection.set_trace_callback(traced.append)
            if extra:
                with pytest.raises(ReadStoreError, match="byte bound|read bound"):
                    read(revision)
            else:
                read(revision)
            revision.connection.set_trace_callback(None)
            bounded_queries = [query for query in traced if f"FROM {table}" in query
                               and "CASE WHEN length(CAST(" in query]
            assert len(bounded_queries) == 1, route
            plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + bounded_queries[0]).fetchall())
            assert "TEMP B-TREE" not in plan.upper(), (route, plan)
