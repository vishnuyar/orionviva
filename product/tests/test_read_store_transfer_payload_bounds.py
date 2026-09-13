"""Transfer JSON is byte- and work-bounded across current and temporal reads."""

import json

import pytest

from viva.ledger import EventStore, LedgerProjection, account_opened, simple_transaction
from viva.ledger.events import transfer_suggested
from viva.read_store import ReadStore, ReadStoreError
from viva.read_store import account_ledger_page, questions, temporal_activity
from viva.read_store.rhythm import RhythmReadError
from viva.read_store.transfer_payload import candidate_keys, decode


def _source(tmp_path):
    events = [account_opened("cash", "depository", "Cash", "USD", "2026-01-01")]
    events += [simple_transaction("cash", "-10", "TRANSFER", day,
                                  kind="depository")
               for day in ("2026-01-05", "2026-01-06")]
    movements = LedgerProjection(events).movements()
    events.append(transfer_suggested(
        movements[0].key, [movements[1].key], {"reason": "amount"},
        "2026-01-07"))
    source = EventStore.open(tmp_path / "events.jsonl", "pw")
    source.append_atomically(lambda _existing: tuple(events))
    return source


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("table", ["transfer_suggestions", "transfer_history"])
def test_transfer_evidence_refuses_exact_utf8_plus_one_before_fetch(
        tmp_path, glyph, table):
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        reads.synchronize(_source(tmp_path))
        with reads.open_reader() as revision:
            original = revision.connection.execute(
                f"SELECT evidence_json FROM {table} "
                "WHERE evidence_json<>'{}' LIMIT 1").fetchone()[0]
        base = json.loads(original)
        bound = 1_000_000
        shell = json.dumps({**base, "padding": ""}, ensure_ascii=False)
        room = bound - len(shell.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            encoded = json.dumps({**base, "padding": padding + extra},
                                 ensure_ascii=False)
            assert len(encoded.encode("utf-8")) == bound + len(extra)
            reads.publish(lambda connection: connection.execute(
                f"UPDATE {table} SET evidence_json=? WHERE evidence_json<>'{{}}'",
                (encoded,)), copy_current=True)
            with reads.open_reader() as revision:
                old_select = revision.connection.execute(
                    f"SELECT evidence_json FROM {table} "
                    "WHERE evidence_json<>'{}' LIMIT 1").fetchone()[0]
                assert json.loads(old_select) == json.loads(encoded)
                traced = []
                revision.connection.set_trace_callback(traced.append)
                def read():
                    if table == "transfer_history":
                        rows = temporal_activity.eligible_family(
                            revision, table, "2026-01-31")
                        return temporal_activity.transfer_state(rows)[1]
                    return revision.activity_projection().transfer_suggestions()
                if extra:
                    with pytest.raises(ReadStoreError, match="byte bound"):
                        read()
                else:
                    assert read()[0]["evidence"]["padding"] == padding
                    if table == "transfer_suggestions":
                        assert revision.transfer_suggestions()[0][
                            "evidence"]["padding"] == padding
                revision.connection.set_trace_callback(None)
                bounded = [sql for sql in traced if f"FROM {table}" in sql
                           and "length(CAST(evidence_json AS BLOB))" in sql]
                assert bounded
                for sql in bounded:
                    plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                        "EXPLAIN QUERY PLAN " + sql).fetchall())
                    assert "TEMP B-TREE" not in plan.upper()


def test_transfer_nested_work_envelope_refuses_before_formatter():
    assert decode(json.dumps({"nested": [1, 2]}), dict,
                  maximum_bytes=1_000_000) == {"nested": [1, 2]}
    with pytest.raises(ValueError, match="container bound"):
        decode(json.dumps(list(range(201))), list, maximum_bytes=1_000_000)
    nested = "leaf"
    for _ in range(32):
        nested = [nested]
    with pytest.raises(ValueError, match="nested work bound"):
        decode(json.dumps(nested), list, maximum_bytes=1_000_000)
    assert candidate_keys(["movement-a", "movement-b"]) == [
        "movement-a", "movement-b"]
    with pytest.raises(ValueError, match="key or count bound"):
        candidate_keys(["雪" * 171])
    with pytest.raises(ValueError, match="key or count bound"):
        candidate_keys(["movement"] * 201)


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_transfer_candidate_array_prefetch_refuses_plus_one_before_nested_key(
        tmp_path, glyph):
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        reads.synchronize(_source(tmp_path))
        with reads.open_reader() as revision:
            original = revision.connection.execute(
                "SELECT candidates_json FROM transfer_suggestions LIMIT 1").fetchone()[0]
        assert len(json.loads(original)) == 1
        bound = 1_000_000
        shell = json.dumps([""], ensure_ascii=False)
        room = bound - len(shell.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            encoded = json.dumps([padding + extra], ensure_ascii=False)
            assert len(encoded.encode("utf-8")) == bound + len(extra)
            reads.publish(lambda connection: connection.execute(
                "UPDATE transfer_suggestions SET candidates_json=?", (encoded,)),
                copy_current=True)
            with reads.open_reader() as revision:
                old_select = revision.connection.execute(
                    "SELECT candidates_json FROM transfer_suggestions LIMIT 1"
                ).fetchone()[0]
                assert json.loads(old_select) == [padding + extra]
                traced = []
                revision.connection.set_trace_callback(traced.append)
                with pytest.raises(ReadStoreError):
                    revision.activity_projection().transfer_suggestions()
                revision.connection.set_trace_callback(None)
                bounded = [sql for sql in traced if "FROM transfer_suggestions" in sql
                           and "length(CAST(candidates_json AS BLOB))" in sql]
                assert len(bounded) == 1
                with pytest.raises(ReadStoreError, match="payload is refused"):
                    revision.transfer_suggestions()
                if extra:
                    with pytest.raises(RhythmReadError, match="byte bound"):
                        questions.candidates(revision.connection, as_of="2026-01-31")
                    source_key = revision.connection.execute(
                        "SELECT movement_a FROM transfer_suggestions LIMIT 1"
                    ).fetchone()[0]
                    with pytest.raises(ReadStoreError, match="transfer context is refused"):
                        account_ledger_page._context(
                            revision.connection, [source_key], None)
