"""Startup gates over valid encrypted event logs at realistic cardinalities.

These tests intentionally do not use wall-clock ratios.  They prove the
complexity boundary directly: warm open may authenticate the header/head and
terminal record, but it may not enter the committed-record iterator at 1k,
10k, or 50k records.
"""
from __future__ import annotations

import shutil
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
def test_warm_open_and_unusable_read_models_do_not_replay_committed_events(
        tmp_path, monkeypatch, count):
    seed = tmp_path / "seed"
    seed.mkdir()
    path = seed / "events.jsonl"
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
    assert elapsed < MAX_SYNTHETIC_OPEN_SECONDS, (count, "warm", elapsed)

    # Clone the authenticated log and its sibling head for each independent
    # scenario. Building and auditing the same encrypted prefix three times
    # adds no coverage of the open operation whose traversal is forbidden.
    for read_model in ("missing", "corrupt"):
        directory = tmp_path / f"vault-{count}-{read_model}"
        shutil.copytree(seed, directory)
        RawStore.open(directory / "raw", PASSPHRASE)
        if read_model == "corrupt":
            reads = ReadStore.create(directory / "read-model", PASSPHRASE)
            reads.close()
            (directory / "read-model" / "current.json").write_text("not-a-generation")

        started = time.perf_counter()
        vault = Vault.open(directory, PASSPHRASE, create=False)
        elapsed = time.perf_counter() - started
        try:
            assert vault.read_store_lifecycle in {"rebuilding", "stale"}, read_model
            assert elapsed < MAX_SYNTHETIC_OPEN_SECONDS, (count, read_model, elapsed)
        finally:
            vault.close()
    assert traversals == 0
