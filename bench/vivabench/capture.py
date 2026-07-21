"""Raw capture: append-only, hash-chained JSONL run records (T3, ADR-004 spirit).

Every model interaction becomes one record. Each record embeds the hash of the
previous record, so any later tampering breaks the chain visibly. This is a
deliberate small rehearsal of the product's event log.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class RunStore:
    """One JSONL file of chained run records, plus resume bookkeeping."""

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = GENESIS
        self._completed: set[tuple[str, str, int, str]] = set()
        self._spent_usd = 0.0
        if self.path.exists():
            for record in self.iter_records():
                self._last_hash = record["record_hash"]
                if record.get("status") == "ok":
                    self._completed.add(self._cell(record))
                self._spent_usd += float(record.get("cost_usd", 0.0))

    @staticmethod
    def _cell(record: dict) -> tuple[str, str, int, str]:
        """A cell's identity. input_mode is part of it: the same document read by
        the same model in a different mode is a different answer, not a repeat.
        Records written before modes existed were all image mode."""
        return (
            record["doc_id"],
            record["candidate"],
            record["run_index"],
            record.get("input_mode", "image"),
        )

    # ---------------------------------------------------------------- reading

    def iter_records(self) -> Iterator[dict]:
        if not self.path.exists():
            return          # no log yet is an empty history, not an error
        with self.path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def verify_chain(self) -> tuple[bool, int]:
        """Recompute the chain. Returns (intact, records_checked)."""
        prev = GENESIS
        count = 0
        for record in self.iter_records():
            claimed = record["record_hash"]
            body = {k: v for k, v in record.items() if k != "record_hash"}
            if record.get("prev_hash") != prev:
                return False, count
            recomputed = hashlib.sha256(
                (_canonical(body)).encode("utf-8")
            ).hexdigest()
            if recomputed != claimed:
                return False, count
            prev = claimed
            count += 1
        return True, count

    # ---------------------------------------------------------------- writing

    def is_done(
        self, doc_id: str, candidate: str, run_index: int, input_mode: str = "image"
    ) -> bool:
        return (doc_id, candidate, run_index, input_mode) in self._completed

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    def append(self, record: dict) -> dict:
        """Chain and persist one record. Returns the record as written."""
        record = dict(record)
        record["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["prev_hash"] = self._last_hash
        record_hash = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
        record["record_hash"] = record_hash
        with self.path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._last_hash = record_hash
        if record.get("status") == "ok":
            self._completed.add(self._cell(record))
        self._spent_usd += float(record.get("cost_usd", 0.0))
        return record
