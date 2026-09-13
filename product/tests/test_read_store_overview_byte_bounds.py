"""Oversized SQL evidence cannot enter ordinary Overview composition."""

import json
from pathlib import Path

import pytest

from viva.ledger import EventStore
from viva.ledger import events
from viva.read_store import ReadStore, ReadStoreError


PASSPHRASE = "correct horse battery staple"
RULING_BYTE_BOUND = 1_000_000


def test_overview_refuses_oversized_ruling_legs_before_decoding(tmp_path: Path):
    canonical = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    canonical.append(events.ruling_recorded(
        events.SCOPE_MOVEMENT, "movement-α", "2026-01-01",
        legs=[{"major": "expense", "account": "Expenses:X"}]))
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        assert reads.synchronize(canonical).state == "rebuilt"
        shell = json.dumps([{"major": "expense", "account": ""}])
        at_limit = json.dumps([{"major": "expense",
                                "account": "X" * (RULING_BYTE_BOUND - len(shell))}])
        assert len(at_limit.encode("utf-8")) == RULING_BYTE_BOUND
        reads.publish(lambda connection: connection.execute(
            "UPDATE ruling_history SET legs_json=?", (at_limit,)),
            copy_current=True)
        with reads.open_reader() as revision:
            assert revision.overview_projection(today="2026-01-02").rulings()
        oversized = json.dumps([{"major": "expense",
                                 "account": "X" * (RULING_BYTE_BOUND - len(shell) + 1)}])
        assert len(oversized.encode("utf-8")) == RULING_BYTE_BOUND + 1
        reads.publish(lambda connection: connection.execute(
            "UPDATE ruling_history SET legs_json=?", (oversized,)),
            copy_current=True)
        with reads.open_reader() as revision:
            with pytest.raises(ReadStoreError, match="ruling.*byte bound"):
                revision.overview_projection(today="2026-01-02")
            plan = revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT scope,subject,"
                "CASE WHEN length(CAST(legs_json AS BLOB))<=? "
                "THEN legs_json ELSE NULL END FROM ruling_history "
                "WHERE occurred_at<=? ORDER BY source_sequence LIMIT ?",
                (RULING_BYTE_BOUND, "2026-01-02", 10_001)).fetchall()
            assert not any("TEMP B-TREE" in row[-1] for row in plan)
