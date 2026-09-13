"""Direct document and model histories have bounded SQL payload reads."""

import json

import pytest

from viva.ledger import EventStore
from viva.ledger.events import read_recorded
from viva.read_store import ReadStore, ReadStoreError
from viva.read_store import store


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("column,method", [
    ("response_text", "document_read_history"),
    ("body_json", "model_exchange_history"),
])
def test_direct_history_sql_refuses_exact_utf8_plus_one_before_fetch(
        tmp_path, glyph, column, method):
    canonical = EventStore.open(tmp_path / "events.jsonl", "pw")
    canonical.append(read_recorded(
        "doc-1", "route", "prompt", "text", "reply", 0, 1, 1,
        True, None, "2026-08-29"))
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        reads.synchronize(canonical)
        bound = (store.MAX_DOCUMENT_RESPONSE_BYTES if column == "response_text"
                 else store.MAX_MODEL_EXCHANGE_BODY_BYTES)
        with reads.open_reader() as revision:
            original = revision.connection.execute(
                f"SELECT {column} FROM document_reads LIMIT 1").fetchone()[0]
        base = json.loads(original) if column == "body_json" else None
        shell = json.dumps({**base, "padding": ""}, ensure_ascii=False) if base else ""
        room = bound - len(shell.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            encoded = (json.dumps({**base, "padding": padding + extra},
                                  ensure_ascii=False) if base else padding + extra)
            assert len(encoded.encode("utf-8")) == bound + len(extra)
            reads.publish(lambda connection: connection.execute(
                f"UPDATE document_reads SET {column}=?", (encoded,)),
                copy_current=True)
            with reads.open_reader() as revision:
                old_select = revision.connection.execute(
                    f"SELECT {column} FROM document_reads LIMIT 1").fetchone()[0]
                assert old_select == encoded
                if base:
                    assert json.loads(old_select) == json.loads(encoded)
                traced = []
                revision.connection.set_trace_callback(traced.append)
                def read():
                    return (revision.document_read_history(
                        "doc-1", as_of="2026-08-29") if method == "document_read_history"
                        else revision.model_exchange_history(as_of="2026-08-29"))
                if extra:
                    with pytest.raises(ReadStoreError, match="byte bound"):
                        read()
                else:
                    assert read()[0][column] == encoded
                revision.connection.set_trace_callback(None)
                bounded = [sql for sql in traced if "FROM document_reads" in sql
                           and f"length(CAST({column} AS BLOB))" in sql]
                assert len(bounded) == 1
                plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + bounded[0]).fetchall())
                assert "TEMP B-TREE" not in plan.upper()


def test_empty_document_response_and_empty_model_body_remain_distinct(tmp_path):
    canonical = EventStore.open(tmp_path / "events.jsonl", "pw")
    canonical.append(read_recorded(
        "doc-1", "route", "prompt", "text", "reply", 0, 1, 1,
        True, None, "2026-08-29"))
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        reads.synchronize(canonical)
        reads.publish(lambda connection: connection.execute(
            "UPDATE document_reads SET response_text='',body_json='{}'"),
            copy_current=True)
        with reads.open_reader() as revision:
            assert revision.document_read_history("doc-1", as_of="2026-08-29")[0][
                "response_text"] == ""
            assert revision.model_exchange_history(as_of="2026-08-29")[0][
                "body_json"] == "{}"
