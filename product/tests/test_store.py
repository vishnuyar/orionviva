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


def _blind(path):
    """A store built the way a holder of the file but not the passphrase would
    build one: the real KDF parameters, a key that is not the key."""
    from viva.crypto import KdfParams
    header = json.loads(path.read_text().splitlines()[0])
    return EventStore(path, b"\x00" * 32, KdfParams.from_dict(header["kdf"]))


def test_records_removed_from_the_end_are_caught(tmp_path):
    """The chain proves each record follows the one before it, which a
    truncated log still satisfies — it is simply a shorter valid chain. Rolling
    a vault back to an earlier state was the one edit nothing noticed. The head
    record is what the length is compared against."""
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    lines = path.read_text().splitlines(True)
    path.write_text("".join(lines[:-1]))

    assert _blind(path).verify_chain() == (False, 2)
    with pytest.raises(CryptoError, match="removed from the end"):
        EventStore.open(path, PW)


def test_a_head_edited_to_match_a_truncation_fails_to_authenticate(tmp_path):
    """Writing the head in the clear is what lets a keyless holder check it. The
    MAC is what stops someone who truncates the log from simply rewriting the
    head to agree with it."""
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    lines = path.read_text().splitlines(True)
    path.write_text("".join(lines[:-1]))

    head_path = path.with_suffix(path.suffix + ".head")
    forged = json.loads(head_path.read_text())
    forged["count"] = 2
    forged["head_hash"] = json.loads(lines[-2])["record_hash"]
    head_path.write_text(json.dumps(forged))

    # The keyless check is satisfied — it has no key to detect the forgery with.
    assert _blind(path).verify_chain() == (True, 2)
    # The owner is not.
    with pytest.raises(CryptoError, match="does not authenticate"):
        EventStore.open(path, PW)


def test_an_interrupted_write_is_not_reported_as_tampering(tmp_path):
    """A process that dies mid-append leaves a line with no newline. Every
    record before it is intact, and the repair is to drop it — so it is named as
    an interrupted write rather than surfacing as a parse error the caller
    cannot tell from a hostile edit."""
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    with path.open("a") as f:
        f.write('{"seq": 3, "prev_ha')

    with pytest.raises(CryptoError, match="partial record"):
        EventStore.open(path, PW)


def test_two_open_stores_appending_do_not_collide(tmp_path):
    """The desktop sidecar holds a store open while the command-line scripts
    write. Both compute `seq` from the tail, so without a lock both mint the
    same one and the chain stops verifying."""
    path = tmp_path / "ledger.jsonl"
    first = EventStore.open(path, PW)
    _seed(first)
    second = EventStore.open(path, PW)

    second.append(simple_transaction("chk", "-1.00", "SECOND", "2026-02-01"))
    first.append(simple_transaction("chk", "-2.00", "FIRST", "2026-02-02"))

    seqs = [json.loads(line)["seq"] for line in path.read_text().splitlines()[1:]]
    assert seqs == [0, 1, 2, 3, 4]
    assert EventStore.open(path, PW).verify_chain() == (True, 5)


def test_a_vault_written_before_the_head_existed_still_opens(tmp_path):
    """A missing head record is an older vault, not a damaged one — but only for
    a vault whose header never declared one. That declaration is what separates
    the two cases."""
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    path.with_suffix(path.suffix + ".head").unlink()

    # Age the header back to one minted before head records existed.
    lines = path.read_text().splitlines(True)
    header = json.loads(lines[0])
    del header["head"]
    path.write_text(json.dumps(header) + "\n" + "".join(lines[1:]))

    store = EventStore.open(path, PW)          # opens, does not raise
    assert store.verify_chain() == (True, 3)
    store.append(simple_transaction("chk", "-3.00", "LATER", "2026-03-01"))
    assert json.loads(path.with_suffix(path.suffix + ".head")
                      .read_text())["count"] == 4


def test_deleting_the_head_record_is_refused(tmp_path):
    """Otherwise the head is a lock with the key beside it: truncate the log,
    delete the head, and the vault opens as a shorter one with nothing to
    compare against. The header says a head exists, so its absence is an
    answer."""
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    lines = path.read_text().splitlines(True)
    path.write_text("".join(lines[:-1]))
    path.with_suffix(path.suffix + ".head").unlink()

    with pytest.raises(CryptoError, match="is missing"):
        EventStore.open(path, PW)
