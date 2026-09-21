"""A vault: one directory, one passphrase, holding a person's whole ledger.

Bundles the encrypted event log (`events.jsonl`, via a `Ledger` with a cached
live projection) and the encrypted raw-blob store (`raw/`) under a single
directory, opened with one passphrase. This is the unit the surface and the
agent work against.

`open` creates the directory if it does not exist, which is right for the
engine: a command that is given a path is being told where a vault is to live,
and a missing directory there is not a failure at all.

It is not right for a person typing a path. A mistyped path answered as an
opened, brand-new empty vault, which reads to somebody as their records having
vanished. So the question "is there a vault here" is asked separately, by
:func:`holds_a_vault`, and a caller that must not create one says so — the
sidecar does. The default stays as it was, because every engine entry point
depends on it and changing it under them would be a second defect.
"""

from __future__ import annotations

import logging
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .crypto import CryptoError
from .ingest.raw_store import RawStore
from .ledger.ledger import Ledger
from .ledger.merchant_keys import installed_resolver
from .read_store import ReadStore, ReadStoreDegraded, ReadStoreError

log = logging.getLogger(__name__)

# What makes a directory a vault rather than a directory. The event log is the
# source of truth and everything else is a projection of it, so its presence is
# the question and nothing else is.
EVENTS = "events.jsonl"


class VaultNotFound(FileNotFoundError):
    """There is no vault at that path, and none was made there.

    Raised only where a caller asked not to create one. It carries the path so
    a caller can say which one, and nothing else: what a person is told about
    it is written where sentences are written."""

    def __init__(self, directory: Path) -> None:
        super().__init__(str(directory))
        self.directory = Path(directory)


def holds_a_vault(directory: Path | str) -> bool:
    """Whether there is a vault in that directory.

    Asked before opening, by any caller that must not make one. It reads the
    event log's presence and nothing else — not its contents, not the raw
    store, and not the passphrase, which is a separate question with a separate
    answer."""
    return (Path(directory) / EVENTS).is_file()


@dataclass
class Vault:
    ledger: Ledger
    raw: RawStore
    directory: Path
    read_store: ReadStore | None = None
    read_store_lifecycle: str = "unavailable"
    _read_store_event_source: object | None = None
    _read_store_worker: subprocess.Popen[bytes] | None = None
    _read_store_worker_started: float | None = None
    _read_store_worker_timeout: float = 120.0
    _read_store_worker_messages: queue.SimpleQueue[dict[str, str]] | None = None
    _read_store_worker_reader: threading.Thread | None = None
    _read_store_worker_busy: bool = False
    _read_store_worker_managed: bool = False
    _read_store_worker_token: str | None = None
    _read_store_worker_expected: tuple[int | None, str | None, int] | None = None
    _read_store_worker_serial: int = 0
    _read_store_worker_cancel: threading.Event | None = None
    _read_store_worker_lock: threading.RLock | None = None
    _read_store_visibility_held: bool = False
    _read_store_visibility_serial: int = 0
    _read_store_visibility_lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False)

    def hold_read_store_visibility(self) -> int:
        """Fence reads for one background writer and identify its ownership."""
        with self._read_store_visibility_lock:
            self._read_store_visibility_serial += 1
            self._read_store_visibility_held = True
            self.read_store_lifecycle = "stale"
            return self._read_store_visibility_serial

    def holds_read_store_visibility(self, serial: int) -> bool:
        """Whether this background writer still owns the read fence."""
        with self._read_store_visibility_lock:
            return (self._read_store_visibility_held
                    and serial == self._read_store_visibility_serial)

    def fork_for_background(self) -> "Vault":
        """Isolate background caches while retaining this unlocked vault."""
        return Vault(ledger=self.ledger.fork(), raw=self.raw.fork(),
                     directory=self.directory)

    @classmethod
    def open(cls, directory: Path, passphrase: str,
             create: bool = True, *, start_read_store_worker: bool = False) -> "Vault":
        """Open the vault in ``directory``, making one there if there is none.

        ``create=False`` refuses to make one: it raises :class:`VaultNotFound`
        for a directory holding no event log, and ``NotADirectoryError`` for a
        path that is not a directory at all. A caller that hands a person's
        typed path to this passes False, because the two failures it then gets
        are the two things that person needs to be told apart from a vault that
        opened."""
        directory = Path(directory)
        if not create:
            if directory.exists() and not directory.is_dir():
                raise NotADirectoryError(str(directory))
            if not holds_a_vault(directory):
                raise VaultNotFound(directory)
        directory.mkdir(parents=True, exist_ok=True)
        log.info("opening vault at %s", directory)
        # Every opened vault uses installed merchant identity resolution.
        ledger = Ledger.open(directory / "events.jsonl", passphrase,
                             resolve_keys=installed_resolver())
        raw = RawStore.open(directory / "raw", passphrase)
        read_store, lifecycle = cls._open_read_store(
            directory / "read-model", passphrase)
        vault = cls(ledger=ledger, raw=raw, directory=directory,
                    read_store=read_store, read_store_lifecycle=lifecycle,
                    _read_store_event_source=ledger.store.fork())
        ledger.store.observe_commits(vault._after_canonical_commit)
        if start_read_store_worker:
            vault._start_read_store_worker(passphrase)
        return vault

    def _after_canonical_commit(
            self, _identity: tuple[int | None, str | None, int]) -> None:
        """Catch up after commit, while keeping the event as the sole success boundary."""
        # A brand-new or recovering store already advertises rebuilding.  Its
        # owner performs one explicit full synchronization after the initial
        # event batch; per-event generations here would hide an earlier batch
        # failure and turn linear construction into quadratic copying.
        if self.read_store_lifecycle == "rebuilding":
            return
        self.read_store_lifecycle = ("stale" if self._has_read_revision()
                                     else "rebuilding")
        self.synchronize_read_store(_event_store=self._read_store_event_source)

    @staticmethod
    def _open_read_store(directory: Path, passphrase: str):
        """Authenticate a usable generation without rebuilding it inline."""
        existed = directory.exists()
        try:
            if directory.exists():
                try:
                    reads = ReadStore.open(directory, passphrase)
                except ReadStoreError:
                    reads = ReadStore.open_for_recovery(directory, passphrase)
            else:
                reads = ReadStore.create(directory, passphrase)
            try:
                with reads.open_reader():
                    return reads, "stale" if existed else "rebuilding"
            except ReadStoreError:
                return reads, "rebuilding"
        except ReadStoreError:
            # Quarantine is one atomic directory-entry operation.  Foreground
            # open never walks or deletes a corrupt tree; bounded retention is
            # background worker maintenance.  Canonical events and raw blobs
            # are outside this directory.
            if directory.exists() or directory.is_symlink():
                try:
                    if directory.is_symlink() or not directory.is_dir():
                        raise ReadStoreError("unsafe read-store root")
                    parent = directory.parent.resolve(strict=True)
                    if directory.resolve(strict=True).parent != parent:
                        raise ReadStoreError("unsafe read-store root")
                    target = parent / f".{directory.name}-quarantine-{secrets.token_hex(16)}"
                    os.replace(directory, target)
                except (OSError, ReadStoreError):
                    return None, "degraded"
            try:
                return ReadStore.create(directory, passphrase), "rebuilding"
            except ReadStoreError:
                return None, "degraded"

    def _start_read_store_worker(self, passphrase: str) -> None:
        """Start one disposable projection worker without retaining its secret.

        The secret crosses only the child's inherited stdin pipe. It is never
        placed in argv, the environment, a file, diagnostics, or a log.
        """
        self.stop_read_store_worker()
        if self._read_store_worker_lock is None:
            self._read_store_worker_lock = threading.RLock()
        token = secrets.token_urlsafe(32)
        expected = self.ledger.store.authenticated_identity()
        payload = bytearray((json.dumps({"directory": str(self.directory),
                                         "passphrase": passphrase,
                                         "token": token}) + "\n").encode("utf-8"))
        command = ([sys.executable, "--read-store-worker"]
                   if getattr(sys, "frozen", False)
                   else [sys.executable, "-m", "viva.desktop_bridge",
                         "--read-store-worker"])
        worker = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=(os.name != "nt"))
        assert worker.stdin is not None
        worker.stdin.write(payload)
        worker.stdin.flush()
        payload[:] = b"\0" * len(payload)
        with self._read_store_worker_lock:
            self._read_store_worker = worker
            self._read_store_worker_started = time.monotonic()
            self._read_store_worker_busy = True
            self._read_store_worker_managed = True
            self._read_store_worker_token = token
            self._read_store_worker_expected = expected
            self._read_store_worker_serial += 1
            serial = self._read_store_worker_serial
            cancel = threading.Event()
            self._read_store_worker_cancel = cancel
        messages: queue.SimpleQueue[dict[str, str]] = queue.SimpleQueue()
        self._read_store_worker_messages = messages

        def receive() -> None:
            assert worker.stdout is not None
            for line in worker.stdout:
                try:
                    reply = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if isinstance(reply, dict):
                    messages.put(reply)

        reader = threading.Thread(target=receive, name="read-store-worker-replies",
                                  daemon=True)
        self._read_store_worker_reader = reader
        reader.start()
        self._arm_read_store_watchdog(worker, token, serial, cancel)
        if self.read_store_lifecycle != "rebuilding":
            self.read_store_lifecycle = ("stale" if self._has_read_revision()
                                         else "rebuilding")

    def poll_read_store_worker(self, *, retry_stale: bool = False) -> str:
        """Refresh lifecycle without ever waiting on projection work."""
        worker = self._read_store_worker
        if worker is None:
            with self._read_store_visibility_lock:
                if self._read_store_visibility_held:
                    self.read_store_lifecycle = "stale"
            return self.read_store_lifecycle
        messages = self._read_store_worker_messages
        while messages is not None:
            try:
                reply = messages.get_nowait()
            except queue.Empty:
                break
            if not self._accept_read_store_reply(reply):
                continue
        if worker.poll() is not None:
            lock = self._read_store_worker_lock
            if lock is None:
                lock = self._read_store_worker_lock = threading.RLock()
            with lock:
                # Poll began against one generation. A concurrent close/open
                # may have installed another before process death was seen;
                # completion of the old generation must not unpublish it.
                if self._read_store_worker is worker:
                    self._clear_read_store_worker_locked(worker)
                    self.read_store_lifecycle = (
                        "stale" if self._has_read_revision() else "degraded")
        with self._read_store_visibility_lock:
            if self._read_store_visibility_held:
                self.read_store_lifecycle = "stale"
            elif (retry_stale and self.read_store_lifecycle in {"stale", "rebuilding"}
                  and self._read_store_worker_managed
                  and self._read_store_worker is not None
                  and not self._read_store_worker_busy):
                self.synchronize_read_store()
        return self.read_store_lifecycle

    def _arm_read_store_watchdog(self, worker, token: str, serial: int,
                                 cancel: threading.Event) -> None:
        """Own the hard deadline independently of foreground request traffic."""
        def watch() -> None:
            if cancel.wait(self._read_store_worker_timeout):
                return
            lock = self._read_store_worker_lock
            if lock is None:
                return
            with lock:
                if (self._read_store_worker is worker
                        and self._read_store_worker_busy
                        and self._read_store_worker_token == token
                        and self._read_store_worker_serial == serial):
                    self._stop_read_store_worker_locked(worker)
                    self.read_store_lifecycle = (
                        "stale" if self._has_read_revision() else "degraded")

        threading.Thread(target=watch, name="read-store-worker-watchdog",
                         daemon=True).start()

    def _accept_read_store_reply(self, reply: object) -> bool:
        """Authenticate IPC correlation, then authenticate durable publication."""
        if not isinstance(reply, dict) or set(reply) != {"state", "token"}:
            return False
        state, token = reply.get("state"), reply.get("token")
        if (state not in {"equal", "caught_up", "rebuilt", "degraded"}
                or not isinstance(token, str)
                or not secrets.compare_digest(token, self._read_store_worker_token or "")):
            return False
        cancel = self._read_store_worker_cancel
        if cancel is not None:
            cancel.set()
        self._read_store_worker_busy = False
        self._read_store_worker_started = None
        if state == "degraded":
            self.read_store_lifecycle = "stale" if self._has_read_revision() else "degraded"
            return True
        try:
            expected = self._read_store_worker_expected
            if expected is None or self.read_store is None:
                raise ReadStoreError("missing expected source identity")
            count, head, _end = expected
            # Bound publication authentication with two fresh canonical reads.
            # This rejects an append that lands after dispatch or while the SQL
            # generation is being opened and authenticated.  An append after
            # the second read is a later revision, not part of this acceptance
            # window, and will be caught by the next surface synchronization.
            if self.ledger.store.authenticated_identity() != expected:
                raise ReadStoreError("committed events advanced during projection")
            with self.read_store.open_reader() as revision:
                source = self.read_store.authenticated_source_identity(revision)
            if source["count"] != count or source["head"] != head:
                raise ReadStoreError("published revision does not match committed events")
            if self.ledger.store.authenticated_identity() != expected:
                raise ReadStoreError("committed events advanced during verification")
        except (ReadStoreError, CryptoError, OSError):
            self.read_store_lifecycle = "stale" if self._has_read_revision() else "degraded"
            return False
        self.read_store_lifecycle = state
        return True

    def _has_read_revision(self) -> bool:
        if self.read_store is None:
            return False
        try:
            with self.read_store.open_reader():
                return True
        except ReadStoreError:
            return False

    def stop_read_store_worker(self) -> None:
        """Cancel and reap projection work within two seconds."""
        if getattr(self, "_read_store_worker_lock", None) is None:
            self._read_store_worker_lock = threading.RLock()
        with self._read_store_worker_lock:
            self._stop_read_store_worker_locked(self._read_store_worker)

    def _stop_read_store_worker_locked(self, worker) -> None:
        if worker is None or self._read_store_worker is not worker:
            return
        cancel = getattr(self, "_read_store_worker_cancel", None)
        if cancel is not None:
            cancel.set()
        # Unpublish this exact generation before its termination becomes
        # externally observable. The lifecycle lock prevents a successor from
        # being installed until all handles below have been closed and reaped.
        self._clear_read_store_worker_locked(worker)
        if worker.poll() is None:
            try:
                if worker.stdin is not None:
                    worker.stdin.write(b'{"command":"close"}\n')
                    worker.stdin.flush()
                worker.wait(timeout=0.5)
            except (OSError, BrokenPipeError, subprocess.TimeoutExpired):
                worker.terminate()
            try:
                worker.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=1.0)
        for stream in (worker.stdin, worker.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def _clear_read_store_worker_locked(self, worker) -> None:
        """Forget only the generation named by ``worker`` while holding its lock."""
        if self._read_store_worker is not worker:
            return
        self._read_store_worker = None
        self._read_store_worker_started = None
        self._read_store_worker_busy = False
        self._read_store_worker_messages = None
        self._read_store_worker_reader = None
        self._read_store_worker_token = None
        self._read_store_worker_expected = None
        self._read_store_worker_cancel = None

    def close(self) -> None:
        self.ledger.store.observe_commits(None)
        self.stop_read_store_worker()
        if self.read_store is not None:
            self.read_store.close()

    def synchronize_read_store(self, *, _event_store=None) -> str:
        """Catch up the read store once; never repeat a canonical write."""
        event_store = (_event_store if _event_store is not None
                       else self.ledger.store)
        self.poll_read_store_worker()
        if self._read_store_worker is not None:
            if not self._read_store_worker_busy:
                try:
                    token = secrets.token_urlsafe(32)
                    expected = event_store.authenticated_identity()
                    assert self._read_store_worker.stdin is not None
                    request = json.dumps({"command": "synchronize", "token": token},
                                         separators=(",", ":")).encode() + b"\n"
                    self._read_store_worker.stdin.write(request)
                    self._read_store_worker.stdin.flush()
                    self._read_store_worker_busy = True
                    self._read_store_worker_started = time.monotonic()
                    self._read_store_worker_token = token
                    self._read_store_worker_expected = expected
                    self._read_store_worker_serial += 1
                    serial = self._read_store_worker_serial
                    cancel = threading.Event()
                    self._read_store_worker_cancel = cancel
                    self._arm_read_store_watchdog(
                        self._read_store_worker, token, serial, cancel)
                    self.read_store_lifecycle = ("stale" if self._has_read_revision()
                                                 else "rebuilding")
                except (OSError, BrokenPipeError):
                    self.stop_read_store_worker()
            return self.read_store_lifecycle
        if self._read_store_worker_managed:
            self.read_store_lifecycle = ("stale" if self._has_read_revision()
                                         else "degraded")
            return self.read_store_lifecycle
        if self.read_store is None:
            self.read_store_lifecycle = "degraded"
            return self.read_store_lifecycle
        try:
            result = self.read_store.synchronize(event_store)
            expected = event_store.authenticated_identity()
            with self.read_store.open_reader() as revision:
                source = self.read_store.authenticated_source_identity(revision)
            observed = event_store.authenticated_identity()
            if (expected != observed or source["count"] != observed[0]
                    or source["head"] != observed[1]):
                self.read_store_lifecycle = "stale"
            else:
                self.read_store_lifecycle = result.state
        except (ReadStoreDegraded, ReadStoreError):
            try:
                with self.read_store.open_reader():
                    self.read_store_lifecycle = "stale"
            except ReadStoreError:
                self.read_store_lifecycle = "degraded"
        return self.read_store_lifecycle

    def wait_for_read_store(self, *, timeout: float = 120.0,
                            checkpoint=None,
                            visibility_serial: int | None = None) -> bool:
        """Wait off the request loop for one authenticated current revision.

        A busy worker may have started before a background append, so its first
        reply is not proof of visibility. Keep requesting catch-up until the
        published source and two canonical reads agree, or the deadline ends.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if checkpoint is not None:
                checkpoint()
            expected = self.ledger.store.authenticated_identity()
            state = self.synchronize_read_store(
                _event_store=self._read_store_event_source)
            if self.read_store is not None:
                try:
                    if self.ledger.store.authenticated_identity() != expected:
                        continue
                    with self.read_store.open_reader() as revision:
                        source = self.read_store.authenticated_source_identity(revision)
                    if (source["count"] == expected[0]
                            and source["head"] == expected[1]
                            and self.ledger.store.authenticated_identity() == expected):
                        if checkpoint is not None:
                            checkpoint()
                        with self._read_store_visibility_lock:
                            if (visibility_serial is None or
                                    visibility_serial == self._read_store_visibility_serial):
                                self._read_store_visibility_held = False
                                self.read_store_lifecycle = "equal"
                        return True
                except (ReadStoreError, CryptoError, OSError):
                    pass
            if state == "degraded" or (
                    self._read_store_worker_managed
                    and self._read_store_worker is None):
                return False
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        return False

    @property
    def store(self):
        """The underlying event store (the Ledger owns it and the live projection)."""
        return self.ledger.store

    def events(self):
        return self.ledger.events()
