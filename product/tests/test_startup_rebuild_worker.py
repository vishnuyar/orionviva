"""The disposable projection cannot occupy the foreground bridge queue."""
from __future__ import annotations

import io
from importlib import import_module
import json
import subprocess
import sys
import threading
import time

import pytest

from viva.desktop_bridge.__main__ import Sidecar
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger import account_opened
from viva.ledger.store import EventStore
from viva.read_store import ReadStoreDegraded
from viva.vault import Vault


PASSPHRASE = "startup-rebuild-worker-passphrase"


def test_priority_read_catches_up_after_startup_publication_is_superseded(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE,
                       start_read_store_worker=True)
    try:
        deadline = time.monotonic() + 5
        while vault._read_store_worker_messages.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not vault._read_store_worker_messages.empty()
        vault.ledger.append(account_opened(
            "cash", "depository", "Synthetic", "USD", "2026-01-01"))
        identity = vault.ledger.store.authenticated_identity()
        assert vault._read_store_worker_expected[0] == 0
        assert identity[0] == 1
        provider = OpenedVaultSurfaceProvider(vault)
        reply = provider.read_surface("overview_accounts", {})
        assert reply["freshness"] != "current"
        deadline = time.monotonic() + 5
        while reply["freshness"] != "current" and time.monotonic() < deadline:
            time.sleep(0.01)
            reply = provider.read_surface("overview_accounts", {})
        assert reply["freshness"] == "current"
        with vault.read_store.open_reader() as revision:
            published = vault.read_store.authenticated_source_identity(revision)
        assert (published["count"], published["head"]) == identity[:2]
        assert vault.ledger.store.authenticated_identity() == identity
        serial = vault._read_store_worker_serial
        assert provider.read_surface("overview_accounts", {})["freshness"] == "current"
        assert vault._read_store_worker_serial == serial
    finally:
        vault.close()


def _frame(request_id, operation, payload=None):
    return json.dumps({"protocol": "2.0", "request_id": request_id,
                       "operation": operation, "payload": payload or {}})


def test_modern_warm_open_does_not_scan_the_committed_prefix(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    store = EventStore.open(path, PASSPHRASE)
    store.append(account_opened("cash", "depository", "Cash", "USD", "2026-01-01"))

    def scanned(*_args, **_kwargs):
        raise AssertionError("warm open scanned canonical records")

    monkeypatch.setattr(EventStore, "_iter_raw", scanned)
    reopened = EventStore.open(path, PASSPHRASE)
    assert reopened._cached_identity()[0] == 1


def test_modern_fork_reuses_authenticated_tail_without_prefix_scan(
        tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    store = EventStore.open(path, PASSPHRASE)
    store.append(account_opened(
        "cash", "depository", "Cash", "USD", "2026-01-01"))
    expected = store.authenticated_identity()

    def scanned(*_args, **_kwargs):
        raise AssertionError("fork scanned canonical records")

    module = import_module("viva.ledger.store")
    monkeypatch.setattr(EventStore, "_iter_raw", scanned)
    monkeypatch.setattr(
        module, "open_vault_header",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fork derived the passphrase key again")))
    forked = store.fork()
    assert forked._cached_identity() == expected


@pytest.mark.parametrize("count", [1_000, 10_000, 50_000])
@pytest.mark.parametrize("read_model_state", ["missing", "corrupt"])
def test_large_startup_with_unusable_read_model_does_not_scan_event_prefix(
        tmp_path, monkeypatch, count, read_model_state):
    directory = tmp_path / f"vault-{count}-{read_model_state}"
    path = directory / "events.jsonl"
    store = EventStore.open(path, PASSPHRASE)
    header = path.read_text().splitlines(keepends=True)[0]
    module = import_module("viva.ledger.store")
    previous = "f" * 64
    sealed = {}
    record_hash = module._record_hash(count - 1, previous, sealed)
    terminal = json.dumps({
        "seq": count - 1,
        "prev_hash": previous,
        "sealed": sealed,
        "record_hash": record_hash,
    }) + "\n"
    # Startup trusts the authenticated head and terminal boundary. The inert
    # middle lines make any accidental prefix walk both visible and cheap to
    # construct; an explicit committed-log audit remains responsible for them.
    path.write_text(header + "{}\n" * (count - 1) + terminal)
    module.write_head(path, store._key, count, record_hash)
    if read_model_state == "corrupt":
        read_model = directory / "read-model"
        read_model.mkdir()
        (read_model / "key.json").write_text("not-json")

    def scanned(*_args, **_kwargs):
        raise AssertionError("startup scanned canonical records")

    monkeypatch.setattr(EventStore, "_iter_raw", scanned)
    opened = Vault.open(directory, PASSPHRASE, create=False)
    try:
        assert opened.ledger.store._cached_identity()[0] == count
        assert opened._read_store_event_source._cached_identity()[0] == count
        assert opened.read_store_lifecycle == "rebuilding"
    finally:
        opened.close()


def test_missing_store_open_acknowledges_while_worker_is_live(tmp_path):
    started = time.monotonic()
    vault = Vault.open(tmp_path / "vault", PASSPHRASE,
                       start_read_store_worker=True)
    elapsed = time.monotonic() - started
    try:
        assert elapsed < 3
        assert vault.read_store_lifecycle in {"rebuilding", "stale"}
        assert vault._read_store_worker is not None
    finally:
        vault.close()
    assert vault._read_store_worker is None


def test_jobs_reply_is_not_queued_behind_rebuild(tmp_path):
    sidecar = Sidecar(io.StringIO())
    opened = json.loads(sidecar.handle(_frame("open", "bridge.open_vault", {
        "vault_directory": str(tmp_path / "vault"), "passphrase": PASSPHRASE,
        "create": True,
    }))[0])
    assert opened["ok"] is True
    started = time.monotonic()
    jobs = json.loads(sidecar.handle(_frame("jobs", "viva.surface.read", {
        "surface": "jobs", "parameters": {},
    }))[0])
    try:
        assert time.monotonic() - started < 1
        assert jobs["ok"] is True
    finally:
        assert sidecar._vault is not None
        sidecar._vault.close()


def test_resident_worker_retries_with_derived_keys_not_parent_passphrase(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE,
                       start_read_store_worker=True)
    try:
        deadline = time.monotonic() + 5
        while vault._read_store_worker_busy and time.monotonic() < deadline:
            vault.poll_read_store_worker()
            time.sleep(0.01)
        worker = vault._read_store_worker
        assert worker is not None and worker.poll() is None
        assert PASSPHRASE not in repr(vars(vault))

        vault.ledger.append(account_opened(
            "later", "depository", "Later", "USD", "2026-01-01"))
        vault.synchronize_read_store()
        assert vault._read_store_worker is worker
        deadline = time.monotonic() + 5
        while vault._read_store_worker_busy and time.monotonic() < deadline:
            vault.poll_read_store_worker()
            time.sleep(0.01)
        vault.poll_read_store_worker()
        assert vault.read_store_lifecycle in {"caught_up", "rebuilt", "equal"}
        assert vault._read_store_worker is worker and worker.poll() is None
    finally:
        vault.close()


class _HungWorker:
    stdin = None
    stdout = io.BytesIO()

    def __init__(self):
        self.alive = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.alive else -9

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        if not self.killed:
            import subprocess
            raise subprocess.TimeoutExpired("worker", timeout)
        self.alive = False
        return -9

    def kill(self):
        self.killed = True


def test_close_escalates_and_reaps_a_stuck_worker_within_two_seconds():
    worker = _HungWorker()
    vault = Vault.__new__(Vault)
    vault._read_store_worker = worker
    vault._read_store_worker_started = time.monotonic()
    vault.read_store = None
    started = time.monotonic()
    vault.stop_read_store_worker()
    assert time.monotonic() - started < 2
    assert worker.terminated and worker.killed
    assert vault._read_store_worker is None


@pytest.mark.parametrize("program", [
    "import time; time.sleep(60)",
    "while True: pass",
    "import os; os.write(1, b'x' * (32 * 1024 * 1024))",
])
def test_watchdog_autonomously_reaps_real_cpu_and_pipe_blocked_children(
        tmp_path, program):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    worker = subprocess.Popen([sys.executable, "-c", program],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        vault._read_store_worker = worker
        vault._read_store_worker_busy = True
        vault._read_store_worker_token = "t" * 43
        vault._read_store_worker_serial = 9
        vault._read_store_worker_timeout = 0.05
        vault._read_store_worker_lock = threading.RLock()
        cancel = threading.Event()
        vault._read_store_worker_cancel = cancel
        started = time.monotonic()
        vault._arm_read_store_watchdog(worker, "t" * 43, 9, cancel)
        deadline = started + 2
        while (worker.poll() is None or vault._read_store_worker is not None) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert worker.poll() is not None
        assert time.monotonic() - started < 2
        assert vault._read_store_worker is None
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait()
        vault.close()


def test_expired_watchdog_cannot_kill_a_replacement_generation(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    old = subprocess.Popen([sys.executable, "-c", "while True: pass"],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    new = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        vault._read_store_worker_lock = threading.RLock()
        vault._read_store_worker = old
        vault._read_store_worker_busy = True
        vault._read_store_worker_token = "o" * 43
        vault._read_store_worker_serial = 1
        vault._read_store_worker_timeout = 0.05
        expired = threading.Event()
        vault._arm_read_store_watchdog(old, "o" * 43, 1, expired)
        vault._read_store_worker = new
        vault._read_store_worker_token = "n" * 43
        vault._read_store_worker_serial = 2
        time.sleep(0.15)
        assert new.poll() is None
    finally:
        for process in (old, new):
            if process.poll() is None:
                process.kill()
            process.wait()
        vault._read_store_worker = None
        vault.close()


def test_worker_reply_is_only_advisory_until_current_generation_authenticates(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    try:
        assert vault.synchronize_read_store() in {"equal", "rebuilt"}
        vault._read_store_worker_token = "a" * 43
        vault._read_store_worker_expected = vault.ledger.store.authenticated_identity()
        vault._read_store_worker_busy = True
        assert not vault._accept_read_store_reply(
            {"state": "rebuilt", "token": "forged-token-with-enough-characters-000"})
        assert not vault._accept_read_store_reply(
            {"state": "rebuilt", "token": "a" * 43, "extra": "current"})

        vault._read_store_worker_expected = (999, "0" * 64, 0)
        assert not vault._accept_read_store_reply(
            {"state": "rebuilt", "token": "a" * 43})
        assert vault.read_store_lifecycle in {"stale", "degraded"}

        vault._read_store_worker_expected = vault.ledger.store.authenticated_identity()
        assert vault._accept_read_store_reply(
            {"state": "equal", "token": "a" * 43})
        assert vault.read_store_lifecycle == "equal"
    finally:
        vault.close()


def test_worker_reply_cannot_accept_generation_after_canonical_source_advances(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    try:
        assert vault.synchronize_read_store() in {"equal", "rebuilt"}
        vault._read_store_worker_token = "a" * 43
        vault._read_store_worker_expected = vault.ledger.store.authenticated_identity()
        vault._read_store_worker_busy = True

        vault.ledger.append(account_opened(
            "later", "depository", "Later", "USD", "2026-01-01"))

        assert not vault._accept_read_store_reply(
            {"state": "equal", "token": "a" * 43})
        assert vault.read_store_lifecycle in {"stale", "degraded"}
    finally:
        vault.close()


def test_reply_after_sql_interruption_cannot_acknowledge_old_generation(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    try:
        assert vault.synchronize_read_store() in {"equal", "rebuilt"}
        old = vault.read_store.current_generation
        EventStore.open(vault.ledger.store.path, PASSPHRASE).append(account_opened(
            "later", "depository", "Later", "USD", "2026-01-01"))
        committed = vault.ledger.store.authenticated_identity()
        with pytest.raises(ReadStoreDegraded):
            vault.read_store.synchronize(vault.ledger.store,
                                         fail_at="after_metadata_advance")
        assert vault.read_store.current_generation == old

        vault._read_store_worker_token = "f" * 43
        vault._read_store_worker_expected = committed
        vault._read_store_worker_busy = True
        assert not vault._accept_read_store_reply(
            {"state": "caught_up", "token": "f" * 43})
        assert vault.read_store_lifecycle == "stale"
        assert vault.ledger.store.authenticated_identity() == committed

        assert vault.synchronize_read_store() == "caught_up"
        assert vault.read_store.current_generation != old
        assert vault.ledger.store.authenticated_identity() == committed
        vault._read_store_worker_token = "n" * 43
        vault._read_store_worker_expected = committed
        assert not vault._accept_read_store_reply(
            {"state": "caught_up", "token": "f" * 43})
        assert vault._accept_read_store_reply(
            {"state": "equal", "token": "n" * 43})
    finally:
        vault.close()


def test_worker_reply_cannot_accept_append_during_generation_verification(
        tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    try:
        assert vault.synchronize_read_store() in {"equal", "rebuilt"}
        vault._read_store_worker_token = "a" * 43
        vault._read_store_worker_expected = vault.ledger.store.authenticated_identity()
        vault._read_store_worker_busy = True
        original = vault.read_store.authenticated_source_identity

        def authenticate_then_advance(revision):
            source = original(revision)
            vault.ledger.append(account_opened(
                "during", "depository", "During", "USD", "2026-01-01"))
            return source

        monkeypatch.setattr(
            vault.read_store, "authenticated_source_identity",
            authenticate_then_advance)
        assert not vault._accept_read_store_reply(
            {"state": "equal", "token": "a" * 43})
        assert vault.read_store_lifecycle in {"stale", "degraded"}
    finally:
        vault.close()


def test_corrupt_read_store_root_is_renamed_without_foreground_tree_walk(tmp_path):
    directory = tmp_path / "read-model"
    reads = Vault._open_read_store(directory, PASSPHRASE)[0]
    assert reads is not None
    reads.close()
    (directory / "current.json").write_text("corrupt")
    huge = directory / "generations" / "junk"
    huge.mkdir()
    for index in range(1_000):
        (huge / str(index)).write_text("preserve")

    replacement, lifecycle = Vault._open_read_store(directory, PASSPHRASE)
    try:
        assert replacement is not None and lifecycle == "rebuilding"
        quarantined = list(tmp_path.glob(".read-model-quarantine-*"))
        assert len(quarantined) == 1
        assert len(list((quarantined[0] / "generations" / "junk").iterdir())) == 1_000
    finally:
        if replacement is not None:
            replacement.close()


def test_read_store_root_symlink_is_never_followed_or_replaced(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep"
    marker.write_text("present")
    root = tmp_path / "read-model"
    root.symlink_to(outside, target_is_directory=True)

    reads, lifecycle = Vault._open_read_store(root, PASSPHRASE)
    assert reads is None and lifecycle == "degraded"
    assert root.is_symlink() and marker.read_text() == "present"


def _wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert predicate()


def test_completed_wait_survives_idle_deadline_and_later_decline(tmp_path):
    from viva.ledger.events import (
        conversation_turn_opened, conversation_turn_settled, question_declined,
    )

    vault = Vault.open(tmp_path / "vault", PASSPHRASE,
                       start_read_store_worker=True)
    try:
        _wait_until(lambda: not vault._read_store_worker_messages.empty())
        vault.poll_read_store_worker()
        vault.ledger.append(account_opened(
            "cash", "depository", "Synthetic", "USD", "2026-01-01"))
        assert vault.wait_for_read_store(timeout=5)
        worker = vault._read_store_worker
        # Start an equal attempt whose receipt is observable without polling.
        _wait_until(lambda: not vault._read_store_worker_messages.empty())
        vault.poll_read_store_worker()
        vault._read_store_worker_timeout = 0.3
        vault.synchronize_read_store()
        cancel = vault._read_store_worker_cancel
        _wait_until(lambda: not vault._read_store_worker_messages.empty())
        assert cancel.is_set(), "received completion must end its own deadline"
        time.sleep(0.4)
        assert vault._read_store_worker is worker and worker.poll() is None
        assert not vault._read_store_worker_busy

        stamp = "2026-01-02"
        vault.ledger.append(conversation_turn_opened(
            "synthetic-turn", "decline", "Synthetic question", stamp,
            question_id="synthetic-question"))
        vault.ledger.append(question_declined(
            "synthetic-question", "merchant", stamp))
        vault.ledger.append(conversation_turn_settled(
            "synthetic-turn", "set_aside", "Set aside", stamp))
        identity = vault.ledger.store.authenticated_identity()
        assert identity[0] == 4
        assert vault.wait_for_read_store(timeout=5)
        with vault.read_store.open_reader() as revision:
            source = vault.read_store.authenticated_source_identity(revision)
        assert (source["count"], source["head"]) == identity[:2]
        assert vault.ledger.store.authenticated_identity() == identity
    finally:
        vault.close()


def test_immediate_completion_cannot_be_overwritten_by_dispatch(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    receiving = threading.Event()
    acknowledged = threading.Event()
    replies = []

    class ImmediatePipe:
        def write(self, request):
            token = json.loads(request)["token"]

            def complete():
                receiving.set()
                replies.append(vault._acknowledge_read_store_reply(
                    worker, {"state": "equal", "token": token}))
                acknowledged.set()

            threading.Thread(target=complete, daemon=True).start()
            assert receiving.wait(2)

        def flush(self):
            assert vault._read_store_worker_busy
            assert not acknowledged.is_set()

    class ImmediateWorker:
        stdin = ImmediatePipe()

        def poll(self):
            return None

    worker = ImmediateWorker()
    vault._read_store_worker_lock = threading.RLock()
    vault._read_store_worker = worker
    try:
        vault.synchronize_read_store()
        assert acknowledged.wait(2)
        assert replies == [True]
        assert vault._read_store_worker_cancel.is_set()
        assert not vault._read_store_worker_busy
        assert vault._read_store_worker_started is None
        assert vault.read_store_lifecycle in {"stale", "rebuilding"}
    finally:
        vault._read_store_worker = None
        vault.close()


@pytest.mark.parametrize("reply", [
    None, [], {}, {"state": [], "token": "current"},
    {"state": "equal", "token": []},
    {"state": "equal", "token": "non-ascii-\u2603"},
    {"state": "equal", "token": "old"},
    {"state": "equal", "token": "current", "extra": True},
])
def test_malformed_or_wrong_attempt_completion_preserves_deadline(tmp_path, reply):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    worker = object()
    vault._read_store_worker_lock = threading.RLock()
    vault._read_store_worker = worker
    vault._read_store_worker_busy = True
    vault._read_store_worker_token = "current"
    cancel = vault._read_store_worker_cancel = threading.Event()
    try:
        assert not vault._acknowledge_read_store_reply(worker, reply)
        assert not cancel.is_set()
        assert vault._read_store_worker_busy
        assert vault.read_store_lifecycle == "rebuilding"
    finally:
        cancel.set()
        vault._read_store_worker = None
        vault.close()


def test_obsolete_receiver_cannot_acknowledge_current_process(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    current = object()
    vault._read_store_worker_lock = threading.RLock()
    vault._read_store_worker = current
    vault._read_store_worker_busy = True
    vault._read_store_worker_token = "current"
    cancel = vault._read_store_worker_cancel = threading.Event()
    try:
        reply = {"state": "equal", "token": "current"}
        assert not vault._acknowledge_read_store_reply(object(), reply)
        assert not cancel.is_set() and vault._read_store_worker_busy
        assert vault._acknowledge_read_store_reply(current, reply)
        assert cancel.is_set() and not vault._read_store_worker_busy
        assert not vault._acknowledge_read_store_reply(current, reply)
        assert vault.read_store_lifecycle == "rebuilding"
    finally:
        cancel.set()
        vault._read_store_worker = None
        vault.close()


def test_late_completion_after_timeout_cannot_revive_worker(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    vault._read_store_worker_lock = threading.RLock()
    vault._read_store_worker = worker
    vault._read_store_worker_busy = True
    vault._read_store_worker_managed = True
    vault._read_store_worker_token = "expired"
    vault._read_store_worker_timeout = 0.05
    cancel = vault._read_store_worker_cancel = threading.Event()
    try:
        vault._arm_read_store_watchdog(worker, "expired", 0, cancel)
        _wait_until(lambda: vault._read_store_worker is None)
        assert worker.poll() is not None
        assert not vault._acknowledge_read_store_reply(
            worker, {"state": "equal", "token": "expired"})
        assert vault.synchronize_read_store() in {"stale", "degraded"}
        assert vault._read_store_worker is None
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait()
        vault.close()


def test_watchdog_reaps_when_dispatch_holds_lock_on_full_stdin(tmp_path):
    import os

    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    worker = subprocess.Popen(
        [sys.executable, "-c", "import os, time; os.write(1, b'ready\\n'); time.sleep(60)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert worker.stdout.readline() == b"ready\n"
    fd = worker.stdin.fileno()
    os.set_blocking(fd, False)
    try:
        while True:
            os.write(fd, b"x" * 4096)
    except BlockingIOError:
        pass
    finally:
        os.set_blocking(fd, True)
    flushing = threading.Event()
    finished = threading.Event()
    original = worker.stdin

    class ObservedPipe:
        def write(self, request):
            return original.write(request)

        def flush(self):
            flushing.set()
            return original.flush()

        def close(self):
            return original.close()

    worker.stdin = ObservedPipe()
    vault._read_store_worker_lock = threading.RLock()
    vault._read_store_worker = worker
    vault._read_store_worker_managed = True
    vault._read_store_worker_timeout = 0.1

    def dispatch():
        try:
            vault.synchronize_read_store()
        finally:
            finished.set()

    thread = threading.Thread(target=dispatch, daemon=True)
    started = time.monotonic()
    thread.start()
    try:
        assert flushing.wait(1)
        assert finished.wait(2)
        assert time.monotonic() - started < 2
        assert worker.poll() is not None
        assert vault._read_store_worker is None
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait()
        thread.join(2)
        vault.close()


def test_completion_ends_deadline_without_authenticating_advanced_source(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    assert vault.synchronize_read_store() in {"equal", "rebuilt"}
    worker = object()
    vault._read_store_worker_lock = threading.RLock()
    vault._read_store_worker = worker
    vault._read_store_worker_busy = True
    vault._read_store_worker_token = "current"
    vault._read_store_worker_expected = vault.ledger.store.authenticated_identity()
    cancel = vault._read_store_worker_cancel = threading.Event()
    try:
        EventStore.open(vault.ledger.store.path, PASSPHRASE).append(account_opened(
            "later", "depository", "Synthetic", "USD", "2026-01-01"))
        identity = vault.ledger.store.authenticated_identity()
        reply = {"state": "equal", "token": "current"}
        assert vault._acknowledge_read_store_reply(worker, reply)
        assert cancel.is_set() and not vault._read_store_worker_busy
        assert not vault._accept_read_store_reply(reply)
        assert vault.read_store_lifecycle == "stale"
        assert vault.ledger.store.authenticated_identity() == identity
    finally:
        cancel.set()
        vault._read_store_worker = None
        vault.close()
