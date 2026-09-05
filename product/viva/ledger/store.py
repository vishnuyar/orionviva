"""The encrypted, append-only, hash-chained event store.

The events are the source of truth; everything else is a projection rebuilt by
replaying them. This store is where they live, and it holds two properties at
once:

  - **Append-only and tamper-evident.** Each record embeds the hash of the
    record before it, so dropping, reordering or splicing records breaks the
    chain visibly. The chain verifies *without the key*, so integrity is
    checkable by someone who cannot read the contents.
  - **Encrypted at rest.** Each event body is sealed with AES-256-GCM under a
    passphrase-derived key. The record's position (sequence number + previous
    hash) is bound into the GCM aad, so a ciphertext cannot be moved to a
    different slot and still decrypt. GCM gives confidentiality and per-record
    integrity; the chain gives sequence integrity.

File format (one JSON object per line):
    line 0   header:  {"v", "kdf", "check"}   — the versioned crypto envelope +
             a sealed check token that fails fast on a wrong passphrase.
    line 1.. records: {"seq", "prev_hash", "sealed", "record_hash"} — the chain.

The authenticated sibling ``.head`` file is also the commit boundary.  Record
lines beyond the count/hash it authenticates are an uncommitted suffix and are
never replayed; recovery removes them under the writer lock.  This gives a
multi-event append one durable all-or-none boundary without changing the JSONL
record format or rewriting existing records.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from pathlib import Path
from collections.abc import Callable, Iterable
from typing import Iterator

from ..crypto import (HEAD_BOUND_HEADER_VERSION, HEAD_CAPABILITY_VERSION,
                      KdfParams, CryptoError, new_vault_header,
                      open_vault_header, open_sealed, rebind_vault_header,
                      seal, verify_vault_header)
from .events import Event

GENESIS = "0" * 64

# Bound into the check-token AAD selected by HEAD_BOUND_HEADER_VERSION for every
# event log this build creates. That authenticated capability makes a *missing*
# head a failure rather than an older vault. Genuinely legacy headers have the
# legacy envelope version and remain readable until their first nonempty append.
#
# One pre-release implementation wrote this value as an unauthenticated `head`
# field. Such a header is refused: accepting or ignoring that field would revive
# the downgrade it was meant to prevent. A legacy header with no such field may
# have an optional authenticated .head after a crash between the first migration
# phase and the header upgrade; it reopens at that boundary and upgrades on the
# next nonempty append.
HEAD_VERSION = HEAD_CAPABILITY_VERSION
log = logging.getLogger(__name__)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _record_hash(seq: int, prev_hash: str, sealed: dict) -> str:
    body = {"seq": seq, "prev_hash": prev_hash, "sealed": sealed}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def _write_batch(stream, content: str) -> None:
    """Write one prepared batch, rejecting a silent short write."""
    written = stream.write(content)
    if written != len(content):
        raise OSError(
            f"event batch write accepted {written} of {len(content)} characters")


def _header_requires_head(header: dict) -> bool:
    """Return whether the authenticated header requires a commit head.

    Early, unshipped builds wrote a plain ``head`` field beside a legacy check
    token.  That field was not authenticated and therefore cannot grant or
    remove authority.  Refuse it rather than treating it as a capability.
    """
    if "head" in header:
        raise CryptoError(
            "vault header contains an unauthenticated head marker from an "
            "unsupported pre-release format")
    return header.get("v") == HEAD_BOUND_HEADER_VERSION


def _upgrade_header_in_place(path: Path, key: bytes) -> None:
    """Durably bind head-required mode without moving any record bytes.

    The legacy and head-bound version strings have equal length.  Compact JSON
    plus harmless trailing whitespace therefore always fits in the existing
    header line, including when the legacy line was already compact.  Writing
    exactly that line in place preserves both the locked inode and every event
    byte offset.  A torn upgrade cannot fall back: it leaves an unreadable or
    unauthenticated header and opening fails closed.
    """
    with path.open("r+b") as target:
        old_line = target.readline()
        if not old_line.endswith(b"\n"):
            raise CryptoError(f"{path} has an incomplete vault header")
        try:
            header = json.loads(old_line)
        except json.JSONDecodeError as exc:
            raise CryptoError(f"{path} has an unreadable vault header") from exc
        upgraded = rebind_vault_header(
            header, key, header_version=HEAD_BOUND_HEADER_VERSION)
        compact = json.dumps(
            upgraded, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")
        capacity = len(old_line) - 1
        if len(compact) > capacity:
            raise CryptoError(
                f"{path} legacy header cannot be upgraded in place")
        new_line = compact + (b" " * (capacity - len(compact))) + b"\n"
        target.seek(0)
        written = target.write(new_line)
        if written != len(new_line):
            raise OSError(
                "authenticated header upgrade did not reach its exact byte "
                "boundary")
        target.flush()
        os.fsync(target.fileno())


def head_path_for(path: Path) -> Path:
    """The head record that sits beside a log."""
    return path.with_suffix(path.suffix + ".head")


def head_mac(key: bytes, body: dict) -> str:
    """A MAC over the head record, under a key derived from the vault key.

    Derived rather than reused so that a MAC and a record seal never run under
    the same key material."""
    subkey = hmac.new(key, b"viva-head-mac-v1", hashlib.sha256).digest()
    return hmac.new(subkey, _canonical(body).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def write_head(path: Path, key: bytes, count: int, head_hash: str) -> None:
    """Record how long a log is and what its last record hashes to.

    The chain proves that record N follows record N-1; it cannot prove that
    record N is the last one, because a walk forward from GENESIS over a
    truncated file is a walk over a shorter valid chain. Truncation was the one
    edit the log did not notice. This is what it is compared against.

    Written in the clear and authenticated, rather than sealed: `verify_chain`
    advertises that it runs for someone holding the file but not the passphrase,
    and sealing the count would take that away. So a keyless reader can still
    compare the count and the head against the chain and catch a plain
    truncation, while a tamperer who rewrites this file to match cannot forge
    the MAC and is caught the moment the owner opens the vault.

    Every writer of a log calls this, not only `EventStore.append` — a log
    rebuilt in place is a new log and needs a new head.
    """
    body = {"count": count, "head_hash": head_hash}
    head = dict(body, mac=head_mac(key, body))
    # Written whole or not at all: a half-written head would fail the check on
    # next open and look exactly like tampering.
    target = head_path_for(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w") as f:
        f.write(json.dumps(head, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)
    # The rename is the commit point.  Sync its directory so returning from a
    # successful append means that commit point itself, not only the temp file,
    # has reached durable storage.
    directory_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _authenticated_head(path: Path, key: bytes, *,
                        required: bool) -> tuple[int, str] | None:
    """Read the durable commit boundary, authenticating it when present."""
    target = head_path_for(path)
    if not target.exists():
        if required:
            raise CryptoError(
                f"{path} declares a head record but {target} is missing: it "
                "was deleted, and the length of the log cannot be checked "
                "without it")
        return None
    try:
        head = json.loads(target.read_text(encoding="utf-8"))
        count = head["count"]
        head_hash = head["head_hash"]
        body = {"count": count, "head_hash": head_hash}
        mac = head["mac"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CryptoError(f"{target} is not a readable head record") from exc
    if (isinstance(count, bool) or not isinstance(count, int) or count < 0
            or not isinstance(head_hash, str) or not isinstance(mac, str)):
        raise CryptoError(f"{target} is not a readable head record")
    if not hmac.compare_digest(head_mac(key, body), mac):
        raise CryptoError(
            f"{target} does not authenticate: it was written under a "
            "different key, or it was edited")
    return count, head_hash


def _committed_prefix_end(
        path: Path, count: int, expected_hash: str, *,
        expected_prefix: tuple[int, str] | None = None) -> int:
    """Return the byte immediately after the authenticated committed prefix.

    Bytes beyond that point are an uncommitted append attempt.  Only the
    authenticated head may advance the boundary; a complete JSON line by
    itself is never a commit.
    """
    previous = GENESIS
    prefix_count, prefix_hash = expected_prefix or (0, GENESIS)
    if prefix_count > count:
        raise CryptoError("authenticated head moved behind the observed commit")
    try:
        with path.open("rb") as source:
            header = source.readline()
            if not header or not header.endswith(b"\n"):
                raise CryptoError(f"{path} has an incomplete vault header")
            end = source.tell()
            for expected_seq in range(count):
                line = source.readline()
                if not line or not line.endswith(b"\n"):
                    raise CryptoError(
                        f"{path} has records removed from the end, or an "
                        "interrupted record inside its committed batch")
                record = json.loads(line)
                seq = record["seq"]
                rec_previous = record["prev_hash"]
                sealed = record["sealed"]
                rec_hash = record["record_hash"]
                if seq != expected_seq or rec_previous != previous:
                    raise CryptoError(
                        f"chain broken at committed seq {expected_seq}")
                if _record_hash(seq, rec_previous, sealed) != rec_hash:
                    raise CryptoError(
                        f"record hash mismatch at committed seq {expected_seq}")
                previous = rec_hash
                if expected_prefix is not None and expected_seq + 1 == prefix_count \
                        and previous != prefix_hash:
                    raise CryptoError(
                        "the current committed chain does not extend the "
                        "commit this handle already observed")
                end = source.tell()
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CryptoError(
            f"{path} has an unreadable record inside its committed batch") from exc
    if previous != expected_hash:
        raise CryptoError(
            f"the log holds a different committed head than its authenticated "
            f"head record")
    return end


def _recover_to_authenticated_head(path: Path, key: bytes, *, required: bool,
                                   truncate_fd: int,
                                   expected_head: tuple[int, str] | None = None
                                   ) -> tuple[int, str, int] | None:
    """Discard a suffix the authenticated head never committed.

    The caller holds the exclusive writer lock.  Truncation is fsynced before
    the repaired boundary is returned, so a later append cannot promote a
    complete prefix left by a failed multi-event write.
    """
    head = _authenticated_head(path, key, required=required)
    if head is None:
        return None
    count, committed_hash = head
    if expected_head is not None:
        expected_count, expected_hash = expected_head
        if count < expected_count or (
                count == expected_count and committed_hash != expected_hash):
            raise CryptoError(
                "authenticated head moved backward or changed at an already "
                "observed commit")
    end = _committed_prefix_end(
        path, count, committed_hash, expected_prefix=expected_head)
    size = path.stat().st_size
    if size > end:
        os.ftruncate(truncate_fd, end)
        os.fsync(truncate_fd)
        size = path.stat().st_size
        if size != end:
            raise CryptoError(
                f"{path} could not be restored to its committed boundary")
    elif size < end:  # Defensive: the scanner should already have caught it.
        raise CryptoError(f"{path} has records removed from the end")
    return count, committed_hash, size



class EventStore:
    """An encrypted, append-only, hash-chained log of ledger events.

    Open (or create) with a passphrase via :meth:`open`. The key is derived on
    open and held only in memory for the store's lifetime; it is never written
    anywhere."""

    def __init__(self, path: Path, key: bytes, kdf: KdfParams) -> None:
        # Prefer EventStore.open(); this constructor assumes an initialised file.
        self.path = Path(path)
        self._key = key
        self._kdf = kdf
        self._write_failed = False
        self._decision_owner: int | None = None
        self._head_required = False
        self._committed_head: tuple[int, str] | None = None
        self._last_hash = GENESIS
        self._count = 0
        for _seq, prev, sealed, rec_hash in self._iter_raw():
            self._last_hash = rec_hash
            self._count += 1
        self._size = self.path.stat().st_size if self.path.exists() else 0
        # A partial write can leave a tail that cannot be replayed.  This
        # handle then refuses every later append; reopening after repairing the
        # interrupted final line is the only safe way to resume.
        log.debug("EventStore opened %s with %d events", self.path, self._count)

    def fork(self) -> "EventStore":
        """Return a handle sharing the derived key but not the tail cache."""
        self._refuse_decision_reentry("fork")
        if self._write_failed:
            raise CryptoError(
                "this event-store handle cannot be forked after an uncertain "
                "write; reopen the vault to recover its committed boundary")
        with self.path.open("a", encoding="utf-8") as locked:
            fcntl.flock(locked.fileno(), fcntl.LOCK_EX)
            try:
                self._reread_tail(locked.fileno())
            except Exception:
                self._write_failed = True
                raise
            finally:
                fcntl.flock(locked.fileno(), fcntl.LOCK_UN)
        forked = EventStore(self.path, self._key, self._kdf)
        forked._head_required = self._head_required
        forked._committed_head = self._committed_head
        return forked

    # --------------------------------------------------------------- lifecycle

    @classmethod
    def open(cls, path: Path, passphrase: str) -> "EventStore":
        """Open an existing store or create a new one, verifying the passphrase.

        A wrong passphrase raises CryptoError immediately on the header check
        token, even for an empty store."""
        path = Path(path)
        if path.exists():
            with path.open() as f:
                header_line = f.readline()
            if not header_line.strip():
                raise CryptoError(f"{path} exists but has no header")
            header = json.loads(header_line)
            key = open_vault_header(header, passphrase)   # fails fast on wrong pass
            required = _header_requires_head(header)
            # The authenticated head is the commit point.  A process may have
            # died after appending any prefix of a batch but before advancing
            # it; remove that uncommitted suffix before constructing a store
            # that could replay it.
            with path.open("a", encoding="utf-8") as locked:
                fcntl.flock(locked.fileno(), fcntl.LOCK_EX)
                try:
                    recovered = _recover_to_authenticated_head(
                        path, key, required=required,
                        truncate_fd=locked.fileno())
                finally:
                    fcntl.flock(locked.fileno(), fcntl.LOCK_UN)
            store = cls(path, key, KdfParams.from_dict(header["kdf"]))
            store._head_required = required
            store._committed_head = (recovered[0], recovered[1]) \
                if recovered is not None else None
            store._check_head(required=required)
            return store

        # New store: mint a header (KDF salt + check token) and write it as line 0.
        path.parent.mkdir(parents=True, exist_ok=True)
        header, key = new_vault_header(
            passphrase, header_version=HEAD_BOUND_HEADER_VERSION)
        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(header, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        store = cls(path, key, KdfParams.from_dict(header["kdf"]))
        store._head_required = True
        store._seal_head()          # an empty vault still states its length
        store._committed_head = (store._count, store._last_hash)
        return store

    # ------------------------------------------------------------------ append

    def append(self, event: Event) -> dict:
        """Seal, chain, and persist one event. Returns the record as written.

        Held under an exclusive lock for the whole read-modify-write, because
        `seq` and `prev_hash` are read from the tail and then written back to
        it. Two unlocked writers each read the same tail, mint the same `seq`,
        and leave a chain that will not verify — reachable through ordinary use,
        since the desktop sidecar holds a store open while the command-line
        scripts write. The lock is advisory, so it binds every writer that goes
        through this method and none that does not.

        Durable before it returns: the line is flushed and fsynced and its
        authenticated head commit is directory-synced, so a record this method
        has returned is a committed record on the platter.
        """
        return self.append_atomically(lambda _events: (event,))[0]

    def append_atomically(
        self, decide: Callable[[tuple[Event, ...]], Iterable[Event]]
    ) -> list[dict]:
        """Run ``decide`` under the writer lock and append its events in order.

        ``decide`` receives a fresh replay of the current event stream.
        """
        self._refuse_decision_reentry("append")
        if self._write_failed:
            raise CryptoError(
                "this event-store handle observed an incomplete write and "
                "will not append again; repair the interrupted tail and reopen")
        with self.path.open("a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                # The authenticated head, not file metadata, is the security
                # witness. Validate it on every append even when the JSONL size
                # is unchanged, and only accept a forward extension of a head
                # this handle has already observed.
                try:
                    self._reread_tail(f.fileno())
                except Exception:
                    self._write_failed = True
                    raise
                current = tuple(self._events_unlocked())
                self._decision_owner = threading.get_ident()
                try:
                    events = tuple(decide(current))
                finally:
                    self._decision_owner = None
                if any(not isinstance(item, Event) for item in events):
                    raise TypeError("an atomic append decision returns only events")
                if not events:
                    return []
                # A legacy log has no authenticated boundary. Establish one
                # only after the decision is known to be nonempty, so a strict
                # no-op changes neither JSONL nor metadata.
                if not self._head_required:
                    self._seal_head()
                    try:
                        _upgrade_header_in_place(self.path, self._key)
                    except BaseException:
                        # The header write may have reached disk even when its
                        # caller did not observe success.  This handle cannot
                        # safely guess which mode won; reopening authenticates
                        # the durable result.
                        self._write_failed = True
                        raise
                    self._head_required = True
                    self._committed_head = (self._count, self._last_hash)
                    self._size = self.path.stat().st_size
                records = []
                lines = []
                # Preparation is speculative.  Do not publish these candidate
                # tail values to the handle until the bytes and authenticated
                # head have both been durably written.
                candidate_count = self._count
                candidate_hash = self._last_hash
                for event in events:
                    seq = candidate_count
                    prev = candidate_hash
                    payload = {
                        "seq": seq,
                        "recorded_at": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "event": event.to_dict(),
                    }
                    aad = f"{seq}:{prev}".encode("utf-8")
                    sealed = seal(
                        self._key, _canonical(payload).encode("utf-8"), aad)
                    rec_hash = _record_hash(seq, prev, sealed)
                    record = {"seq": seq, "prev_hash": prev,
                              "sealed": sealed, "record_hash": rec_hash}
                    lines.append(json.dumps(record, ensure_ascii=False) + "\n")
                    records.append(record)
                    candidate_hash = rec_hash
                    candidate_count += 1
                if lines:
                    content = "".join(lines)
                    try:
                        _write_batch(f, content)
                        f.flush()
                        os.fsync(f.fileno())
                        expected_size = self._size + len(
                            content.encode("utf-8"))
                        if self.path.stat().st_size != expected_size:
                            raise OSError(
                                "event batch did not reach its exact prepared "
                                "byte boundary")
                        write_head(self.path, self._key, candidate_count,
                                   candidate_hash)
                        candidate_size = self.path.stat().st_size
                    except Exception:
                        # Once writing starts, failure is ambiguous: no bytes,
                        # every byte, or an interrupted last line may be on
                        # disk.  Re-read what is actually there before this
                        # handle is allowed to chain another record.  If the
                        # tail itself is unreadable, refuse later appends.
                        try:
                            self._reread_tail(f.fileno())
                            self._write_failed = False
                        except Exception:
                            self._write_failed = True
                        raise
                    self._count = candidate_count
                    self._last_hash = candidate_hash
                    self._size = candidate_size
                    self._committed_head = (candidate_count, candidate_hash)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        for record, event in zip(records, events):
            log.debug("append seq=%d type=%s", record["seq"], event.event_type)
        return records

    # -------------------------------------------------------------- the head

    @property
    def _head_path(self) -> Path:
        return head_path_for(self.path)

    def _head_mac(self, body: dict) -> str:
        return head_mac(self._key, body)

    def _seal_head(self) -> None:
        write_head(self.path, self._key, self._count, self._last_hash)

    def _check_head(self, required: bool = False) -> None:
        """Compare the chain against the recorded head. Raises on disagreement.

        `required` comes from the vault header. A vault minted before head
        records existed says nothing there, and its missing head file is an
        older vault rather than a damaged one — it is adopted on the next
        append. A vault whose header declares a head and has none has had it
        removed, which is exactly the move that would otherwise turn truncation
        back into something nothing notices."""
        head = _authenticated_head(self.path, self._key, required=required)
        if head is None:
            return
        if head != (self._count, self._last_hash):
            raise CryptoError(
                f"the log holds {self._count} records ending {self._last_hash[:12]}, "
                f"but the head records {head[0]} ending "
                f"{head[1][:12]} — records have been removed from "
                "the end of the log, or it was rolled back to an earlier state")

    def _reread_tail(self, truncate_fd: int) -> None:
        """Authenticate the commit boundary and synchronize the cached tail.

        The caller holds the exclusive writer lock.  This is deliberately run
        even when the JSONL file metadata is unchanged: the authenticated head
        can be deleted, forged, or rolled back independently of the log.
        """
        required = self._authenticate_current_header()
        if self._head_required and not required:
            raise CryptoError(
                "authenticated vault header was downgraded from head-required "
                "mode")
        if required:
            self._head_required = True
        recovered = _recover_to_authenticated_head(
            self.path, self._key,
            required=required or self._head_required
            or self._committed_head is not None,
            truncate_fd=truncate_fd, expected_head=self._committed_head)
        if recovered is None:
            last_hash = GENESIS
            count = 0
            for _seq, _prev, _sealed, rec_hash in self._iter_raw():
                last_hash = rec_hash
                count += 1
            size = self.path.stat().st_size
        else:
            count, last_hash, size = recovered
            self._committed_head = (count, last_hash)
        self._last_hash = last_hash
        self._count = count
        self._size = size

    def _authenticate_current_header(self) -> bool:
        try:
            with self.path.open("r", encoding="utf-8") as source:
                header = json.loads(source.readline())
            verify_vault_header(header, self._key)
            if KdfParams.from_dict(header["kdf"]) != self._kdf:
                raise CryptoError(
                    "vault header KDF changed after this handle opened")
        except CryptoError:
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise CryptoError(f"{self.path} has an unreadable vault header") from exc
        return _header_requires_head(header)

    def _refuse_decision_reentry(self, operation: str) -> None:
        if self._decision_owner == threading.get_ident():
            raise CryptoError(
                f"event-store {operation} cannot be called from its own "
                "atomic decision callback")

    # ------------------------------------------------------------------- reads

    def _iter_raw(self, limit: int | None = None) \
            -> Iterator[tuple[int, str, dict, str]]:
        """Yield (seq, prev_hash, sealed, record_hash) for each record, skipping
        the header. No key needed."""
        if not self.path.exists():
            return
        with self.path.open() as f:
            first = True
            yielded = 0
            for line_no, line in enumerate(f):
                complete = line.endswith("\n")
                line = line.strip()
                if not line:
                    continue
                if first:                     # header line
                    first = False
                    continue
                if limit is not None and yielded >= limit:
                    return
                if not complete:
                    # A line with no newline is the last one, and it was cut
                    # short: the process died mid-append. Named as its own
                    # failure so it is not read as tampering — every record
                    # before it is intact, and the fix is to drop this one.
                    raise CryptoError(
                        f"{self.path} ends in a partial record at line "
                        f"{line_no}: a write was interrupted. Every record "
                        "before it is intact; remove the final line to reopen.")
                rec = json.loads(line)
                yield (rec["seq"], rec["prev_hash"], rec["sealed"],
                       rec["record_hash"])
                yielded += 1

    def _events_unlocked(self) -> Iterator[Event]:
        """Replay the log as decrypted events, verifying the chain as it goes.

        Raises CryptoError on a broken chain or a record that fails to
        authenticate; it never yields a partially-trusted event."""
        if self._write_failed:
            raise CryptoError(
                "this event-store handle cannot replay after an uncertain "
                "write; reopen the vault to recover its committed boundary")
        prev = GENESIS
        for seq, rec_prev, sealed, rec_hash in self._iter_raw(self._count):
            if rec_prev != prev:
                raise CryptoError(
                    f"chain broken at seq {seq}: prev_hash does not match")
            if _record_hash(seq, rec_prev, sealed) != rec_hash:
                raise CryptoError(f"record hash mismatch at seq {seq}")
            aad = f"{seq}:{rec_prev}".encode("utf-8")
            payload = json.loads(open_sealed(self._key, sealed, aad))
            yield Event.from_dict(payload["event"])
            prev = rec_hash

    def events(self) -> Iterator[Event]:
        """Return an authenticated writer-excluded event snapshot."""
        self._refuse_decision_reentry("events")
        return iter(self.snapshot_events())

    def snapshot_events(self) -> tuple[Event, ...]:
        """Replay one complete writer-excluded snapshot of the event log."""
        self._refuse_decision_reentry("snapshot")
        return self.snapshot_events_with_identity()[0]

    def snapshot_events_with_identity(
            self) -> tuple[tuple[Event, ...],
                           tuple[int | None, str | None, int]]:
        """Replay events and return their commit witness under one lock."""
        self._refuse_decision_reentry("snapshot")
        if self._write_failed:
            raise CryptoError(
                "this event-store handle cannot snapshot after an uncertain "
                "write; reopen the vault to recover its committed boundary")
        # Recovery may need to truncate an uncommitted suffix, so snapshots use
        # the exclusive writer lock.  Reads remain local and deterministic;
        # they simply cannot overlap the small commit/recovery critical section.
        with self.path.open("a", encoding="utf-8") as source:
            fcntl.flock(source.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    self._reread_tail(source.fileno())
                except Exception:
                    self._write_failed = True
                    raise
                events = tuple(self._events_unlocked())
                return events, self._cached_identity()
            finally:
                fcntl.flock(source.fileno(), fcntl.LOCK_UN)

    def authenticated_identity(self) -> tuple[int | None, str | None, int]:
        """Validate and return the current commit witness for cache users."""
        self._refuse_decision_reentry("read")
        if self._write_failed:
            raise CryptoError(
                "this event-store handle cannot validate after an uncertain "
                "write; reopen the vault to recover its committed boundary")
        with self.path.open("a", encoding="utf-8") as source:
            fcntl.flock(source.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    self._reread_tail(source.fileno())
                except Exception:
                    self._write_failed = True
                    raise
                return self._cached_identity()
            finally:
                fcntl.flock(source.fileno(), fcntl.LOCK_UN)

    def _cached_identity(self) -> tuple[int | None, str | None, int]:
        if self._committed_head is None:
            return None, None, self._size
        return (*self._committed_head, self._size)

    def verify_chain(self) -> tuple[bool, int]:
        """Recompute the hash chain without decrypting. Returns (intact, count).

        Needs no key, so it runs for someone who holds the file but not the
        passphrase. Returns False and the count reached at the first break.

        The walk alone cannot see a truncation — a chain with its last records
        removed is a shorter chain that verifies. So the length and the head are
        compared against the head record too, in the clear. That check is what a
        keyless holder gets; authenticating the head record needs the key and
        happens on open."""
        prev = GENESIS
        count = 0
        for seq, rec_prev, sealed, rec_hash in self._iter_raw():
            if rec_prev != prev:
                return False, count
            if _record_hash(seq, rec_prev, sealed) != rec_hash:
                return False, count
            prev = rec_hash
            count += 1

        if self._head_path.exists():
            try:
                head = json.loads(self._head_path.read_text(encoding="utf-8"))
                if (head["count"], head["head_hash"]) != (count, prev):
                    return False, count
            except (json.JSONDecodeError, KeyError, TypeError):
                return False, count
        return True, count

    def __len__(self) -> int:
        self._refuse_decision_reentry("len")
        self.authenticated_identity()
        return self._count
