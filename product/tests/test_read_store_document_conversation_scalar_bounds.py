"""Read-time scalar limits for Documents, Conversation, and Trust."""

import json

import pytest

from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger.events import (conversation_turn_opened, document_captured,
                                read_recorded)
from viva.ledger import Provenance
from viva.read_store.store import ReadStoreError
from viva.read_store.trust import outbound_events
from viva.vault import Vault


def _vault(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(document_captured(
        "doc-1", "statement.pdf", 12, "statement", 1, "2026-08-29",
        Provenance("doc-1")))
    vault.ledger.append(read_recorded(
        "doc-1", "route", "prompt", "text", "reply", 0, 1, 1, True,
        None, "2026-08-29"))
    vault.ledger.append(conversation_turn_opened(
        "turn-1", "ask", "Question?", "2026-08-29"))
    vault.synchronize_read_store()
    return vault


@pytest.mark.parametrize("table,column,surface", [
    ("document_reads", "phase", "documents"),
    ("documents", "filename", "conversation"),
    ("conversation_turn_history", "occurred_at", "conversation"),
])
@pytest.mark.parametrize("glyph", ["x", "雪"])
def test_scalar_label_exact_boundary_and_whole_surface_refusal(
        tmp_path, table, column, surface, glyph):
    vault = _vault(tmp_path)
    provider = OpenedVaultSurfaceProvider(vault)
    params = {"as_of": "2026-08-29"} if surface == "conversation" else {}
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0]
    width = len(glyph.encode("utf-8"))
    room = 4096 - len(original.encode("utf-8"))
    exact = original + glyph * (room // width) + "x" * (room % width)
    for value, refused in ((exact, False), (exact + "x", True)):
        vault.read_store.publish(
            lambda db: db.execute(f"UPDATE {table} SET {column}=?", (value,)),
            copy_current=True)
        with vault.read_store.open_reader() as revision:
            assert revision.connection.execute(
                f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0] == value
            selected = []
            revision.connection.set_trace_callback(selected.append)
            if refused:
                with pytest.raises(ReadStoreError, match="scalar byte bound"):
                    if surface == "documents":
                        revision.documents_projection()
                    else:
                        projection = revision.conversation_projection(locale="en-US")
                        projection.conversation_turns()
            else:
                if surface == "documents":
                    revision.documents_projection()
                else:
                    projection = revision.conversation_projection(locale="en-US")
                    projection.conversation_turns()
            revision.connection.set_trace_callback(None)
            matched = [query for query in selected if f"FROM {table} " in query
                       and (f"length(CAST({column} AS BLOB))" in query or
                            f"length(CAST(h.{column} AS BLOB))" in query)]
            assert matched
            plans = [" ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + query).fetchall()) for query in matched]
            assert all("TEMP B-TREE" not in plan.upper() for plan in plans)
        if refused:
            with pytest.raises(BridgeRequestError):
                provider.read_surface(surface, params)


@pytest.mark.parametrize("glyph", ["x", "雪"])
@pytest.mark.parametrize("field", ["model", "resolved_model", "phase"])
def test_trust_displayed_model_fields_are_gated_before_body_decode(
        tmp_path, glyph, field):
    vault = _vault(tmp_path)
    provider = OpenedVaultSurfaceProvider(vault)
    for extra in ("", "x"):
        width = len(glyph.encode("utf-8"))
        value = glyph * (4096 // width) + "x" * (4096 % width) + extra
        vault.read_store.publish(
            lambda db: db.execute(
                "UPDATE document_reads SET body_json=json_set(body_json,?,?)",
                (f"$.{field}", value)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            encoded = revision.connection.execute(
                "SELECT body_json FROM document_reads LIMIT 1").fetchone()[0]
            assert json.loads(encoded)[field] == value
            selected = []
            revision.connection.set_trace_callback(selected.append)
            if extra:
                with pytest.raises(ReadStoreError, match="byte bound"):
                    outbound_events(revision)
            else:
                assert outbound_events(revision)
            revision.connection.set_trace_callback(None)
            assert any("json_extract(body_json" in query and "FROM document_reads" in query
                       for query in selected)
        if extra:
            with pytest.raises(BridgeRequestError):
                provider.read_surface("trust", {})
        else:
            assert provider.read_surface("trust", {})["outbound"]["state"] == "ready"


def test_optional_reported_model_and_held_trust_revision(tmp_path):
    vault = _vault(tmp_path)
    with vault.read_store.open_reader() as held:
        original = outbound_events(held)
        assert "resolved_model" not in original[0].body
        vault.read_store.publish(
            lambda db: db.execute(
                "UPDATE document_reads SET body_json=json_set(body_json,"
                "'$.resolved_model','')"), copy_current=True)
        with vault.read_store.open_reader() as current:
            assert outbound_events(current)[0].body["resolved_model"] == ""
        assert outbound_events(held) == original


def test_document_conversation_trust_named_plans_have_no_temp_sort(tmp_path):
    vault = _vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        traced = []
        revision.connection.set_trace_callback(traced.append)
        revision.documents_projection().document_contributions()
        revision.conversation_projection(locale="en-US").conversation_turns()
        outbound_events(revision)
        revision.connection.set_trace_callback(None)
        reads = [sql for sql in traced if sql.lstrip().upper().startswith("SELECT")]
        assert any("FROM document_reads INDEXED BY document_reads_by_source" in sql
                   for sql in reads)
        assert any("FROM conversation_turn_history h" in sql for sql in reads)
        assert any("FROM statement_periods INDEXED BY statement_periods_by_document_source"
                   in sql for sql in reads)
        bounded = [query for query in reads if any(fragment in query for fragment in (
            "CASE WHEN length(CAST(h.event_type AS BLOB))",
            "CASE WHEN length(CAST(doc_id AS BLOB))",
            "CASE WHEN length(CAST(occurred_at AS BLOB))"))]
        assert bounded
        for query in bounded:
            plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + query).fetchall())
            assert "TEMP B-TREE" not in plan.upper(), query
