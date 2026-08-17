"""The encrypted, append-only, hash-chained event store."""

import json

import pytest

from viva.crypto import CryptoError
from viva.ledger import (EventStore, account_opened, opening_balance_observed,
                         simple_transaction)

# The vault is this file's subject, so it pays the real scrypt cost rather than
# the cheap one the rest of the suite mints under (tests/conftest.py).
pytestmark = pytest.mark.production_kdf

PW = "a strong test passphrase"


def _seed(store):
    store.append(account_opened("chk", "depository", "Everyday Checking",
                                "USD", "2026-01-01"))
    store.append(opening_balance_observed("chk", "1000.00", "2026-01-01"))
    store.append(simple_transaction("chk", "-42.42", "SECRETMERCHANT",
                                    "2026-01-05"))


def test_create_append_and_replay(tmp_path):
    path = tmp_path / "ledger.jsonl"
    store = EventStore.open(path, PW)
    _seed(store)
    assert len(store) == 3
    events = list(store.events())
    assert [e.event_type for e in events] == [
        "AccountOpened", "OpeningBalanceObserved", "TransactionRecorded"]


def test_reload_from_disk_resumes_chain(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    # A fresh process reopens and appends onto the existing chain.
    store2 = EventStore.open(path, PW)
    assert len(store2) == 3
    store2.append(simple_transaction("chk", "500.00", "paycheck", "2026-01-10"))
    intact, count = store2.verify_chain()
    assert intact and count == 4


def test_wrong_passphrase_rejected(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    with pytest.raises(CryptoError):
        EventStore.open(path, "not the passphrase")


def test_chain_detects_tampering(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    lines = path.read_text().splitlines()
    # Adversary edits the sealed blob of the first record (line 1; line 0 header).
    rec = json.loads(lines[1])
    rec["sealed"]["ct"] = "AAAA" + rec["sealed"]["ct"][4:]
    lines[1] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    intact, _ = EventStore.open(path, PW).verify_chain()
    assert not intact


def test_reordering_breaks_replay(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    lines = path.read_text().splitlines()
    lines[1], lines[2] = lines[2], lines[1]      # swap two records
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(CryptoError):
        list(EventStore.open(path, PW).events())


def test_nothing_readable_at_rest(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    raw = path.read_text()
    # Neither the amount nor the merchant appears in the encrypted file.
    assert "SECRETMERCHANT" not in raw
    assert "42.42" not in raw
    assert "1000.00" not in raw


def test_empty_store_wrong_passphrase_still_caught(tmp_path):
    path = tmp_path / "ledger.jsonl"
    EventStore.open(path, PW)      # header only, no records
    with pytest.raises(CryptoError):
        EventStore.open(path, "wrong")


def test_the_chain_verifies_without_the_passphrase(tmp_path):
    """`verify_chain` recomputes the hash chain from the header and the record
    envelopes alone, so integrity is checkable by a holder of the file who
    cannot decrypt it. Reading the events still requires the key."""
    from viva.crypto import KdfParams

    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    header = json.loads(path.read_text().splitlines()[0])
    blind = EventStore(path, b"\x00" * 32, KdfParams.from_dict(header["kdf"]))
    assert blind.verify_chain() == (True, 3)
    with pytest.raises(CryptoError):
        list(blind.events())
