"""The encrypted, append-only, hash-chained event store."""

import json
import subprocess
import sys
import textwrap
from importlib import import_module
from pathlib import Path

import pytest

from viva.crypto import (HEAD_BOUND_HEADER_VERSION, VERSION, CryptoError,
                         open_vault_header, rebind_vault_header)
from viva.ledger import (EventStore, Ledger, account_opened,
                         opening_balance_observed, simple_transaction)

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


def _rewrite_header(path, transform):
    lines = path.read_text().splitlines(True)
    header = transform(json.loads(lines[0]))
    path.write_text(json.dumps(header) + "\n" + "".join(lines[1:]))
    return header


def _make_genuine_legacy(path):
    def legacy(header):
        key = open_vault_header(header, PW)
        return rebind_vault_header(
            header, key, header_version=VERSION)

    header = _rewrite_header(path, legacy)
    head_path = path.with_suffix(path.suffix + ".head")
    if head_path.exists():
        head_path.unlink()
    return header


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


def test_atomic_preparation_failure_does_not_advance_the_cached_tail(
        tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_seal = module.seal
    calls = 0
    before_bytes = path.read_bytes()
    before_cache = (
        store._count, store._last_hash, store._size, store._write_failed)

    def fail_on_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic second-seal failure")
        return real_seal(*args, **kwargs)

    monkeypatch.setattr(module, "seal", fail_on_second)
    with pytest.raises(RuntimeError, match="second-seal"):
        store.append_atomically(lambda _events: (
            account_opened("chk", "depository", "Checking", "USD",
                           "2026-01-01"),
            simple_transaction("chk", "-1", "ONE", "2026-01-02"),
        ))

    assert path.read_bytes() == before_bytes
    assert (
        store._count, store._last_hash, store._size,
        store._write_failed) == before_cache

    monkeypatch.setattr(module, "seal", real_seal)
    store.append(account_opened(
        "chk", "depository", "Checking", "USD", "2026-01-01"))
    assert list(store.events())[0].event_type == "AccountOpened"
    assert EventStore.open(path, PW).verify_chain() == (True, 1)


def test_log_fsync_failure_fails_closed_and_reopen_rolls_back_the_batch(
        tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_fsync = module.os.fsync

    monkeypatch.setattr(
        module.os, "fsync",
        lambda _fd: (_ for _ in ()).throw(OSError("synthetic fsync failure")))
    with pytest.raises(OSError, match="fsync failure"):
        store.append(account_opened(
            "chk", "depository", "Checking", "USD", "2026-01-01"))

    # Rollback itself could not be fsynced under this injected fault, so the
    # handle cannot safely expose or extend either possible disk state.
    with pytest.raises(CryptoError, match="cannot validate"):
        len(store)
    with pytest.raises(CryptoError, match="cannot snapshot"):
        list(store.events())

    monkeypatch.setattr(module.os, "fsync", real_fsync)
    reopened = EventStore.open(path, PW)
    assert list(reopened.events()) == []
    reopened.append(account_opened(
        "chk", "depository", "Checking", "USD", "2026-01-01"))
    assert EventStore.open(path, PW).verify_chain() == (True, 1)


def test_head_failure_rolls_back_before_the_next_append(
        tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_write_head = module.write_head

    monkeypatch.setattr(
        module, "write_head",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("synthetic head failure")))
    with pytest.raises(OSError, match="head failure"):
        store.append(account_opened(
            "chk", "depository", "Checking", "USD", "2026-01-01"))

    assert len(store) == 0
    assert list(store.events()) == []

    monkeypatch.setattr(module, "write_head", real_write_head)
    store.append(account_opened(
        "chk", "depository", "Checking", "USD", "2026-01-01"))
    assert EventStore.open(path, PW).verify_chain() == (True, 1)


def test_error_after_head_commit_keeps_the_whole_batch_and_resynchronizes(
        tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_write_head = module.write_head

    def commit_then_raise(*args, **kwargs):
        real_write_head(*args, **kwargs)
        raise OSError("synthetic reply lost after commit")

    monkeypatch.setattr(module, "write_head", commit_then_raise)
    with pytest.raises(OSError, match="after commit"):
        store.append_atomically(lambda _events: (
            account_opened("chk", "depository", "Checking", "USD",
                           "2026-01-01"),
            simple_transaction("chk", "-1", "ONE", "2026-01-02"),
        ))

    assert len(store) == 2
    assert [event.event_type for event in store.events()] == [
        "AccountOpened", "TransactionRecorded"]
    assert EventStore.open(path, PW).verify_chain() == (True, 2)


def test_reopen_rolls_back_a_crash_after_durable_complete_prefix(
        tmp_path, monkeypatch):
    class SimulatedProcessExit(BaseException):
        pass

    path = tmp_path / "ledger.jsonl"
    writer = EventStore.open(path, PW)
    already_open_reader = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_write = module._write_batch

    def crash_after_first(stream, content):
        first = content.splitlines(keepends=True)[0]
        assert stream.write(first) == len(first)
        stream.flush()
        module.os.fsync(stream.fileno())
        raise SimulatedProcessExit()

    monkeypatch.setattr(module, "_write_batch", crash_after_first)
    with pytest.raises(SimulatedProcessExit):
        writer.append_atomically(lambda _events: (
            account_opened("chk", "depository", "Checking", "USD",
                           "2026-01-01"),
            simple_transaction("chk", "-1", "ONE", "2026-01-02"),
        ))

    # A reader opened before the crash also consults the commit boundary; it
    # cannot expose the complete first JSON line as a committed event.
    assert already_open_reader.snapshot_events() == ()
    monkeypatch.setattr(module, "_write_batch", real_write)
    reopened = EventStore.open(path, PW)
    assert list(reopened.events()) == []
    reopened.append(account_opened(
        "chk", "depository", "Checking", "USD", "2026-01-01"))
    assert EventStore.open(path, PW).verify_chain() == (True, 1)


def test_reopen_rolls_back_a_crash_after_log_sync_before_head_commit(
        tmp_path, monkeypatch):
    class SimulatedProcessExit(BaseException):
        pass

    path = tmp_path / "ledger.jsonl"
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    monkeypatch.setattr(
        module, "write_head",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SimulatedProcessExit()))

    with pytest.raises(SimulatedProcessExit):
        store.append_atomically(lambda _events: (
            account_opened("chk", "depository", "Checking", "USD",
                           "2026-01-01"),
            simple_transaction("chk", "-1", "ONE", "2026-01-02"),
        ))

    assert list(store.events()) == []
    assert list(EventStore.open(path, PW).events()) == []


def test_reopen_keeps_the_whole_batch_after_head_commit_process_exit(
        tmp_path, monkeypatch):
    class SimulatedProcessExit(BaseException):
        pass

    path = tmp_path / "ledger.jsonl"
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_write_head = module.write_head

    def commit_then_exit(*args, **kwargs):
        real_write_head(*args, **kwargs)
        raise SimulatedProcessExit()

    monkeypatch.setattr(module, "write_head", commit_then_exit)
    with pytest.raises(SimulatedProcessExit):
        store.append_atomically(lambda _events: (
            account_opened("chk", "depository", "Checking", "USD",
                           "2026-01-01"),
            simple_transaction("chk", "-1", "ONE", "2026-01-02"),
        ))

    reopened = EventStore.open(path, PW)
    assert [event.event_type for event in reopened.events()] == [
        "AccountOpened", "TransactionRecorded"]
    assert reopened.verify_chain() == (True, 2)


def test_uncertain_write_with_unreadable_tail_refuses_later_appends(
        tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_fsync = module.os.fsync
    real_reread_tail = store._reread_tail
    rereads = 0

    def fail_recovery_after_write(truncate_fd):
        nonlocal rereads
        rereads += 1
        if rereads == 2:
            raise CryptoError("synthetic broken tail")
        return real_reread_tail(truncate_fd)

    monkeypatch.setattr(
        module.os, "fsync",
        lambda _fd: (_ for _ in ()).throw(OSError("synthetic write failure")))
    monkeypatch.setattr(
        store, "_reread_tail", fail_recovery_after_write)

    with pytest.raises(OSError, match="write failure"):
        store.append(account_opened(
            "chk", "depository", "Checking", "USD", "2026-01-01"))

    monkeypatch.setattr(module.os, "fsync", real_fsync)
    with pytest.raises(CryptoError, match="will not append again"):
        store.append(simple_transaction("chk", "-1", "ONE", "2026-01-02"))


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
    with pytest.raises(CryptoError, match="record hash mismatch"):
        EventStore.open(path, PW)


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


def test_an_uncommitted_torn_suffix_is_dropped_at_the_authenticated_head(
        tmp_path):
    """A torn suffix beyond the authenticated commit point is not replayed."""
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    with path.open("a") as f:
        f.write('{"seq": 3, "prev_ha')

    reopened = EventStore.open(path, PW)
    assert reopened.verify_chain() == (True, 3)
    assert len(list(reopened.events())) == 3
    assert path.read_bytes().endswith(b"\n")


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
    _make_genuine_legacy(path)

    store = EventStore.open(path, PW)          # opens, does not raise
    assert store.verify_chain() == (True, 3)
    store.append(simple_transaction("chk", "-3.00", "LATER", "2026-03-01"))
    assert json.loads(path.with_suffix(path.suffix + ".head")
                      .read_text())["count"] == 4


def test_first_modern_batch_on_a_legacy_log_establishes_rollback_boundary(
        tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    _make_genuine_legacy(path)
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_write = module._write_batch

    def write_first_then_fail(stream, content):
        first = content.splitlines(keepends=True)[0]
        assert stream.write(first) == len(first)
        stream.flush()
        module.os.fsync(stream.fileno())
        raise OSError("synthetic legacy batch interruption")

    monkeypatch.setattr(module, "_write_batch", write_first_then_fail)
    with pytest.raises(OSError, match="legacy batch interruption"):
        store.append_atomically(lambda _events: (
            simple_transaction("chk", "-1", "ONE", "2026-03-02"),
            simple_transaction("chk", "-2", "TWO", "2026-03-03"),
        ))

    assert len(list(store.events())) == 3
    monkeypatch.setattr(module, "_write_batch", real_write)
    reopened = EventStore.open(path, PW)
    assert len(list(reopened.events())) == 3
    reopened.append(simple_transaction(
        "chk", "-3", "THREE", "2026-03-04"))
    assert EventStore.open(path, PW).verify_chain() == (True, 4)


def _restore_an_observed_older_head(path):
    store = EventStore.open(path, PW)
    store.append(account_opened(
        "chk", "depository", "Checking", "USD", "2026-01-01"))
    head_path = path.with_suffix(path.suffix + ".head")
    older_head = head_path.read_bytes()
    store.append(simple_transaction(
        "chk", "-1", "SECOND", "2026-01-02"))
    current_head = head_path.read_bytes()
    assert len(older_head) == len(current_head)
    unchanged_log = path.read_bytes()
    head_path.write_bytes(older_head)
    assert path.read_bytes() == unchanged_log
    return store, older_head, unchanged_log


@pytest.mark.parametrize("operation", ["snapshot", "append"])
def test_open_handle_rejects_same_size_authenticated_head_rollback(
        tmp_path, operation):
    path = tmp_path / f"{operation}.jsonl"
    store, older_head, unchanged_log = _restore_an_observed_older_head(path)

    with pytest.raises(CryptoError, match="moved backward"):
        if operation == "snapshot":
            store.snapshot_events()
        else:
            store.append(simple_transaction(
                "chk", "-2", "THIRD", "2026-01-03"))

    assert path.read_bytes() == unchanged_log
    assert path.with_suffix(path.suffix + ".head").read_bytes() == older_head


@pytest.mark.parametrize("operation", ["snapshot", "append"])
@pytest.mark.parametrize("tamper", ["forged_mac", "missing_head"])
def test_open_handle_authenticates_head_on_every_read_and_append(
        tmp_path, operation, tamper):
    path = tmp_path / f"{tamper}-{operation}.jsonl"
    store = EventStore.open(path, PW)
    store.append(account_opened(
        "chk", "depository", "Checking", "USD", "2026-01-01"))
    head_path = path.with_suffix(path.suffix + ".head")
    log_before = path.read_bytes()
    if tamper == "forged_mac":
        head = json.loads(head_path.read_text())
        head["mac"] = "0" * 64
        head_path.write_text(json.dumps(head) + "\n")
        match = "does not authenticate"
    else:
        head_path.unlink()
        match = "is missing"

    with pytest.raises(CryptoError, match=match):
        if operation == "snapshot":
            store.snapshot_events()
        else:
            store.append(simple_transaction(
                "chk", "-1", "SECOND", "2026-01-02"))

    assert path.read_bytes() == log_before


def test_reopen_recovers_to_restored_commit_without_promoting_suffix(tmp_path):
    path = tmp_path / "ledger.jsonl"
    store, _older_head, log_with_uncommitted_second = \
        _restore_an_observed_older_head(path)

    with pytest.raises(CryptoError, match="moved backward"):
        store.snapshot_events()

    reopened = EventStore.open(path, PW)
    recovered = list(reopened.events())
    assert [event.event_type for event in recovered] == ["AccountOpened"]
    assert path.read_bytes() != log_with_uncommitted_second
    reopened.append(simple_transaction(
        "chk", "-3", "AFTER RECOVERY", "2026-01-03"))
    final_events = list(EventStore.open(path, PW).events())
    assert [event.event_type for event in final_events] == [
        "AccountOpened", "TransactionRecorded"]
    assert final_events[-1].body["description"] == "AFTER RECOVERY"


@pytest.mark.parametrize("tamper", ["rollback", "forged_mac", "missing_head"])
def test_ledger_cached_projection_validates_head_identity(tmp_path, tamper):
    path = tmp_path / f"{tamper}.jsonl"
    ledger = Ledger.open(path, PW)
    ledger.append(account_opened(
        "chk", "depository", "Checking", "USD", "2026-01-01"))
    head_path = path.with_suffix(path.suffix + ".head")
    older_head = head_path.read_bytes()
    ledger.append(simple_transaction(
        "chk", "-1", "SECOND", "2026-01-02"))
    log_size = path.stat().st_size

    if tamper == "rollback":
        assert len(older_head) == len(head_path.read_bytes())
        head_path.write_bytes(older_head)
        match = "moved backward"
    elif tamper == "forged_mac":
        head = json.loads(head_path.read_text())
        head["mac"] = "0" * 64
        head_path.write_text(json.dumps(head) + "\n")
        match = "does not authenticate"
    else:
        head_path.unlink()
        match = "is missing"

    assert path.stat().st_size == log_size
    with pytest.raises(CryptoError, match=match):
        ledger.projection()


def test_empty_atomic_decision_does_not_migrate_a_legacy_log(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    head_path = path.with_suffix(path.suffix + ".head")
    _make_genuine_legacy(path)
    store = EventStore.open(path, PW)
    before = path.read_bytes()

    assert store.append_atomically(lambda _events: ()) == []

    assert path.read_bytes() == before
    assert not head_path.exists()


def test_new_event_store_binds_head_requirement_into_the_header(tmp_path):
    path = tmp_path / "ledger.jsonl"
    EventStore.open(path, PW)

    header = json.loads(path.read_text().splitlines()[0])
    assert header["v"] == HEAD_BOUND_HEADER_VERSION
    assert "head" not in header
    assert path.with_suffix(path.suffix + ".head").exists()
    assert EventStore.open(path, PW).verify_chain() == (True, 0)


@pytest.mark.parametrize("mutation", ["remove", "legacy", "unknown"])
def test_fresh_open_refuses_an_edited_or_removed_authenticated_head_mode(
        tmp_path, mutation):
    path = tmp_path / f"{mutation}.jsonl"
    _seed(EventStore.open(path, PW))
    lines = path.read_text().splitlines(True)
    header = json.loads(lines[0])
    if mutation == "remove":
        del header["v"]
    elif mutation == "legacy":
        header["v"] = VERSION
    else:
        header["v"] = "forged-head-mode"
    path.write_text(json.dumps(header) + "\n" + "".join(lines[1:]))

    with pytest.raises(CryptoError):
        EventStore.open(path, PW)


def test_fresh_open_refuses_legacy_check_token_transplanted_into_bound_header(
        tmp_path):
    path = tmp_path / "ledger.jsonl"
    EventStore.open(path, PW)
    lines = path.read_text().splitlines(True)
    modern = json.loads(lines[0])
    key = open_vault_header(modern, PW)
    legacy = rebind_vault_header(
        modern, key, header_version=VERSION)
    modern["check"] = legacy["check"]
    path.write_text(json.dumps(modern) + "\n" + "".join(lines[1:]))

    with pytest.raises(CryptoError, match="decryption failed"):
        EventStore.open(path, PW)


def test_fresh_open_refuses_truncate_delete_head_and_header_downgrade(
        tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    lines = path.read_text().splitlines(True)
    header = json.loads(lines[0])
    header["v"] = VERSION
    path.write_text(json.dumps(header) + "\n" + "".join(lines[1:-1]))
    path.with_suffix(path.suffix + ".head").unlink()

    with pytest.raises(CryptoError):
        EventStore.open(path, PW)


@pytest.mark.parametrize("operation", ["snapshot", "append"])
def test_open_handle_refuses_authenticated_header_downgrade(
        tmp_path, operation):
    path = tmp_path / f"{operation}.jsonl"
    store = EventStore.open(path, PW)
    store.append(account_opened(
        "chk", "depository", "Checking", "USD", "2026-01-01"))
    before_log = path.read_bytes()
    _rewrite_header(path, lambda header: {**header, "v": VERSION})

    with pytest.raises(CryptoError):
        if operation == "snapshot":
            store.snapshot_events()
        else:
            store.append(simple_transaction(
                "chk", "-1", "SECOND", "2026-01-02"))
    assert len(path.read_bytes()) == len(before_log)


def test_unauthenticated_pre_release_head_marker_is_never_trusted(tmp_path):
    path = tmp_path / "ledger.jsonl"
    EventStore.open(path, PW)
    _make_genuine_legacy(path)
    _rewrite_header(path, lambda header: {**header, "head": "head-v1"})

    with pytest.raises(CryptoError, match="unauthenticated head marker"):
        EventStore.open(path, PW)


def test_legacy_upgrade_crash_after_initial_head_commits_no_new_data(
        tmp_path, monkeypatch):
    class SimulatedProcessExit(BaseException):
        pass

    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    _make_genuine_legacy(path)
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_upgrade = module._upgrade_header_in_place
    monkeypatch.setattr(
        module, "_upgrade_header_in_place",
        lambda *_args: (_ for _ in ()).throw(SimulatedProcessExit()))

    with pytest.raises(SimulatedProcessExit):
        store.append(simple_transaction(
            "chk", "-1", "NOT COMMITTED", "2026-03-02"))

    assert json.loads(path.read_text().splitlines()[0])["v"] == VERSION
    assert path.with_suffix(path.suffix + ".head").exists()
    monkeypatch.setattr(module, "_upgrade_header_in_place", real_upgrade)
    reopened = EventStore.open(path, PW)
    assert len(list(reopened.events())) == 3
    reopened.append(simple_transaction(
        "chk", "-2", "AFTER RECOVERY", "2026-03-03"))
    assert EventStore.open(path, PW).verify_chain() == (True, 4)


def test_legacy_upgrade_crash_after_header_binding_before_append_is_safe(
        tmp_path, monkeypatch):
    class SimulatedProcessExit(BaseException):
        pass

    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    _make_genuine_legacy(path)
    store = EventStore.open(path, PW)
    module = import_module("viva.ledger.store")
    real_seal = module.seal
    monkeypatch.setattr(
        module, "seal",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SimulatedProcessExit()))

    with pytest.raises(SimulatedProcessExit):
        store.append(simple_transaction(
            "chk", "-1", "NOT COMMITTED", "2026-03-02"))

    assert json.loads(path.read_text().splitlines()[0])["v"] == \
        HEAD_BOUND_HEADER_VERSION
    monkeypatch.setattr(module, "seal", real_seal)
    reopened = EventStore.open(path, PW)
    assert len(list(reopened.events())) == 3
    reopened.append(simple_transaction(
        "chk", "-2", "AFTER RECOVERY", "2026-03-03"))
    assert EventStore.open(path, PW).verify_chain() == (True, 4)


def test_legacy_nonempty_append_upgrades_header_and_reopens(tmp_path):
    path = tmp_path / "ledger.jsonl"
    _seed(EventStore.open(path, PW))
    _make_genuine_legacy(path)

    store = EventStore.open(path, PW)
    store.append(simple_transaction(
        "chk", "-1", "UPGRADE", "2026-03-02"))

    assert json.loads(path.read_text().splitlines()[0])["v"] == \
        HEAD_BOUND_HEADER_VERSION
    assert EventStore.open(path, PW).verify_chain() == (True, 4)


@pytest.mark.parametrize("operation", [
    "store_snapshot", "store_events", "store_len", "store_fork",
    "store_append", "ledger_projection", "ledger_append",
    "ledger_append_atomically",
])
def test_atomic_decision_reentry_fails_fast_without_mutation(
        tmp_path, operation):
    path = tmp_path / f"{operation}.jsonl"
    program = textwrap.dedent("""
        import sys
        from pathlib import Path
        from viva.crypto import CryptoError
        from viva.ledger import EventStore, Ledger, account_opened

        path = Path(sys.argv[1])
        operation = sys.argv[2]
        store = EventStore.open(path, "pw")
        ledger = Ledger(store)
        event = account_opened(
            "chk", "depository", "Checking", "USD", "2026-01-01")
        before = (path.read_bytes(), store._head_path.read_bytes(),
                  store._count, store._last_hash, store._size)

        def reenter(_projection):
            calls = {
                "store_snapshot": store.snapshot_events,
                "store_events": lambda: list(store.events()),
                "store_len": lambda: len(store),
                "store_fork": store.fork,
                "store_append": lambda: store.append(event),
                "ledger_projection": ledger.projection,
                "ledger_append": lambda: ledger.append(event),
                "ledger_append_atomically": lambda: ledger.append_atomically(
                    lambda _inner: ()),
            }
            calls[operation]()
            return ()

        try:
            ledger.append_atomically(reenter)
        except CryptoError as exc:
            assert "atomic decision callback" in str(exc)
        else:
            raise AssertionError("reentrant callback unexpectedly completed")

        after = (path.read_bytes(), store._head_path.read_bytes(),
                 store._count, store._last_hash, store._size)
        assert after == before
        ledger.append(event)
        assert EventStore.open(path, "pw").verify_chain() == (True, 1)
    """)

    subprocess.run(
        [sys.executable, "-c", program, str(path), operation],
        check=True, timeout=10, cwd=str(Path(__file__).parents[1]))


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
