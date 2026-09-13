"""Parity and bounds for the SQL-native current Documents read."""

from pathlib import Path

import pytest

from viva.demo import build_demo_vault
from viva.ledger import EventStore, LedgerProjection, Provenance
from viva.ledger.events import document_captured
from viva.read_store import ReadStore
from viva.read_store.documents import MAX_DOCUMENTS, MAX_DOCUMENT_SCALAR_BYTES
from viva.read_store.store import ReadStoreError
from viva.surface.documents import documents


PASSPHRASE = "documents-test-passphrase"


def _captured(number: int):
    doc_id = f"document-{number:04d}"
    return document_captured(
        doc_id, f"statement-{number:04d}.pdf", number + 1, "statement", 1,
        f"2026-01-{number % 28 + 1:02d}", Provenance(doc_id))


def test_current_documents_sql_matches_the_complete_surface_payload(tmp_path: Path):
    vault = build_demo_vault(tmp_path / "sample")
    raw_ids = frozenset(vault.raw.doc_ids())
    expected = documents(vault.ledger.projection(), raw_ids, False, "en-US")

    with vault.read_store.open_reader() as revision:
        actual = documents(revision.documents_projection(), raw_ids, False, "en-US")

    assert actual == expected


def test_documents_reader_holds_one_generation_across_later_publication(tmp_path: Path):
    source = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    source.append(_captured(1))
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        held = reads.open_reader()
        source.append(_captured(2))
        reads.synchronize(source)

        assert set(held.documents_projection().captured_docs()) == {"document-0001"}
        with reads.open_reader() as current:
            assert set(current.documents_projection().captured_docs()) == {
                "document-0001", "document-0002"}
        held.close()


def test_documents_refuses_the_first_identity_beyond_its_output_bound(tmp_path: Path):
    events = [_captured(number) for number in range(MAX_DOCUMENTS + 1)]
    source = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    source.append_atomically(lambda _existing: tuple(events))
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            with pytest.raises(ReadStoreError, match="document bound"):
                revision.documents_projection()


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("column", ["doc_id", "doc_type", "filename"])
def test_documents_scalar_prefetch_exact_utf8_boundary_and_refusal(
        tmp_path, glyph, column):
    source = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    source.append(_captured(1))
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            original = revision.connection.execute(
                f"SELECT {column} FROM documents LIMIT 1").fetchone()[0]
        room = MAX_DOCUMENT_SCALAR_BYTES - len(original.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            value = original + padding + extra
            assert len(value.encode("utf-8")) == MAX_DOCUMENT_SCALAR_BYTES + len(extra)
            reads.publish(lambda connection: connection.execute(
                f"UPDATE documents SET {column}=?", (value,)), copy_current=True)
            with reads.open_reader() as revision:
                assert revision.connection.execute(
                    f"SELECT {column} FROM documents LIMIT 1").fetchone()[0] == value
                traced = []
                revision.connection.set_trace_callback(traced.append)
                if extra:
                    with pytest.raises(ReadStoreError, match="scalar byte bound"):
                        revision.documents_projection()
                else:
                    projection = revision.documents_projection()
                    if column == "filename":
                        assert value in projection.captured_filenames().values()
                revision.connection.set_trace_callback(None)
                selected = [sql for sql in traced if "FROM documents INDEXED BY documents_by_source" in sql
                            and "length(CAST(filename AS BLOB))" in sql]
                assert len(selected) == 1
                plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + selected[0]).fetchall())
                assert "documents_by_source" in plan
                assert "TEMP B-TREE" not in plan.upper()


def test_documents_queries_use_named_order_compatible_indexes(tmp_path: Path):
    source = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    source.append(_captured(1))
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            plans = {
                "documents_by_source": revision.connection.execute(
                    "EXPLAIN QUERY PLAN SELECT "
                    "CASE WHEN length(CAST(doc_id AS BLOB))<=? THEN doc_id END,"
                    "CASE WHEN length(CAST(doc_type AS BLOB))<=? THEN doc_type END,"
                    "CASE WHEN length(CAST(filename AS BLOB))<=? THEN filename END "
                    "FROM documents INDEXED BY documents_by_source "
                    "ORDER BY source_sequence LIMIT ?",
                    (4096, 4096, 4096, 10_001)).fetchall(),
                "document_reads_by_source": revision.connection.execute(
                    "EXPLAIN QUERY PLAN SELECT doc_id,phase,parse_ok FROM document_reads "
                    "INDEXED BY document_reads_by_source ORDER BY source_sequence LIMIT ?",
                    (10_001,)).fetchall(),
                "statement_periods_by_document_source": revision.connection.execute(
                    "EXPLAIN QUERY PLAN SELECT doc_id,account_id,closing_amount_text,period_end "
                    "FROM statement_periods INDEXED BY statement_periods_by_document_source "
                    "ORDER BY doc_id,source_sequence LIMIT ?", (10_001,)).fetchall(),
            }

    for index, rows in plans.items():
        plan = " ".join(str(row[-1]) for row in rows)
        assert index in plan
        assert "TEMP B-TREE" not in plan
