"""Startup gates over valid encrypted event logs at realistic cardinalities.

These tests intentionally do not use wall-clock ratios.  They prove the
complexity boundary directly: warm open may authenticate the header/head and
terminal record, but it may not enter the committed-record iterator at 1k,
10k, or 50k records.
"""
from __future__ import annotations

import time

import pytest

from viva.ingest.raw_store import RawStore
from viva.ledger import account_opened, simple_transaction
from viva.ledger.store import EventStore
from viva.read_store import ReadStore
from viva.vault import Vault


PASSPHRASE = "startup-scale-passphrase"
MAX_SYNTHETIC_OPEN_SECONDS = 3.0


def _synthetic_log(path, count: int) -> None:
    store = EventStore.open(path, PASSPHRASE)
    events = [account_opened(
        "cash", "depository", "Cash", "USD", "2026-01-01")]
    events.extend(simple_transaction(
        "cash", "-1.00", f"Synthetic {sequence}", "2026-01-02")
                  for sequence in range(1, count))
    # One durable encrypted batch keeps fixture construction linear.  Unlike
    # the former placeholder ciphertext, these logs pass canonical decryption,
    # event decoding, hash-chain, and authenticated-head audits.
    store.append_atomically(lambda _before: events)
    snapshot = store.committed_snapshot()
    assert snapshot.identity.count == count and len(snapshot.events) == count


@pytest.mark.parametrize("count", [1_000, 10_000, 50_000])
def test_warm_open_complexity_is_independent_of_committed_event_count(
        tmp_path, monkeypatch, count):
    path = tmp_path / f"events-{count}.jsonl"
    _synthetic_log(path, count)
    traversals = 0

    def traversed(*_args, **_kwargs):
        nonlocal traversals
        traversals += 1
        raise AssertionError("warm open traversed the committed prefix")

    monkeypatch.setattr(EventStore, "_iter_raw", traversed)
    started = time.perf_counter()
    opened = EventStore.open(path, PASSPHRASE)
    elapsed = time.perf_counter() - started
    assert opened._cached_identity()[:2] == (count, opened._last_hash)
    assert traversals == 0
    assert elapsed < MAX_SYNTHETIC_OPEN_SECONDS, (count, elapsed)


@pytest.mark.parametrize("count", [1_000, 10_000, 50_000])
@pytest.mark.parametrize("read_model", ["missing", "corrupt"])
def test_missing_or_corrupt_read_model_ack_does_not_replay_events(
        tmp_path, monkeypatch, count, read_model):
    directory = tmp_path / f"vault-{count}-{read_model}"
    directory.mkdir()
    _synthetic_log(directory / "events.jsonl", count)
    RawStore.open(directory / "raw", PASSPHRASE)
    if read_model == "corrupt":
        reads = ReadStore.create(directory / "read-model", PASSPHRASE)
        reads.close()
        (directory / "read-model" / "current.json").write_text("not-a-generation")

    monkeypatch.setattr(
        EventStore, "_iter_raw",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("open replayed canonical events")))
    started = time.perf_counter()
    vault = Vault.open(directory, PASSPHRASE, create=False)
    elapsed = time.perf_counter() - started
    try:
        assert vault.read_store_lifecycle in {"rebuilding", "stale"}
        assert elapsed < MAX_SYNTHETIC_OPEN_SECONDS, (count, read_model, elapsed)
    finally:
        vault.close()
