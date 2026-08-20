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
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Iterator

from ..crypto import (KdfParams, CryptoError, new_vault_header,
                      open_vault_header, open_sealed, seal)
from .events import Event

GENESIS = "0" * 64

# Stamped into the header of every event log this build creates. Its presence is
# what makes a *missing* head file a failure rather than an older vault: without
# it, deleting the head file would put the log back to a state where truncation
# is invisible. A header lacking it opens exactly as before — the raw document
# store shares the crypto envelope and does not carry a chain, so it declares
# nothing here.
HEAD_VERSION = "head-v1"
log = logging.getLogger(__name__)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _record_hash(seq: int, prev_hash: str, sealed: dict) -> str:
    body = {"seq": seq, "prev_hash": prev_hash, "sealed": sealed}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


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
        self._last_hash = GENESIS
        self._count = 0
        for _seq, prev, sealed, rec_hash in self._iter_raw():
            self._last_hash = rec_hash
            self._count += 1
        self._size = self.path.stat().st_size if self.path.exists() else 0
        log.debug("EventStore opened %s with %d events", self.path, self._count)

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
            store = cls(path, key, KdfParams.from_dict(header["kdf"]))
            store._check_head(required=bool(header.get("head")))
            return store

        # New store: mint a header (KDF salt + check token) and write it as line 0.
        path.parent.mkdir(parents=True, exist_ok=True)
        header, key = new_vault_header(passphrase)
        header["head"] = HEAD_VERSION
        with path.open("w") as f:
            f.write(json.dumps(header, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        store = cls(path, key, KdfParams.from_dict(header["kdf"]))
        store._seal_head()          # an empty vault still states its length
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

        Durable before it returns: the line is flushed and fsynced, so a record
        this method has returned is a record on the platter.
        """
        with self.path.open("a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                # Another writer may have appended since this store last looked.
                # Size is the cheap witness: unchanged means the cached tail is
                # still the tail, and a rescan is only paid for when it is not.
                if self.path.stat().st_size != self._size:
                    self._reread_tail()

                seq = self._count
                prev = self._last_hash
                payload = {
                    "seq": seq,
                    "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": event.to_dict(),
                }
                aad = f"{seq}:{prev}".encode("utf-8")
                sealed = seal(self._key, _canonical(payload).encode("utf-8"), aad)
                rec_hash = _record_hash(seq, prev, sealed)
                record = {"seq": seq, "prev_hash": prev, "sealed": sealed,
                          "record_hash": rec_hash}

                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())

                self._last_hash = rec_hash
                self._count += 1
                self._size = self.path.stat().st_size
                self._seal_head()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        log.debug("append seq=%d type=%s", seq, event.event_type)
        return record

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
        if not self._head_path.exists():
            if required:
                raise CryptoError(
                    f"{self.path} declares a head record but {self._head_path} "
                    "is missing: it was deleted, and the length of the log "
                    "cannot be checked without it")
            return
        try:
            head = json.loads(self._head_path.read_text(encoding="utf-8"))
            body = {"count": head["count"], "head_hash": head["head_hash"]}
            mac = head["mac"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CryptoError(f"{self._head_path} is not a readable head record") from exc

        if not hmac.compare_digest(self._head_mac(body), mac):
            raise CryptoError(
                f"{self._head_path} does not authenticate: it was written under "
                "a different key, or it was edited")
        if (body["count"], body["head_hash"]) != (self._count, self._last_hash):
            raise CryptoError(
                f"the log holds {self._count} records ending {self._last_hash[:12]}, "
                f"but the head records {body['count']} ending "
                f"{str(body['head_hash'])[:12]} — records have been removed from "
                "the end of the log, or it was rolled back to an earlier state")

    def _reread_tail(self) -> None:
        """Recompute the cached tail from the file. Called under the lock when
        the file has grown underneath this store."""
        self._last_hash = GENESIS
        self._count = 0
        for _seq, _prev, _sealed, rec_hash in self._iter_raw():
            self._last_hash = rec_hash
            self._count += 1

    # ------------------------------------------------------------------- reads

    def _iter_raw(self) -> Iterator[tuple[int, str, dict, str]]:
        """Yield (seq, prev_hash, sealed, record_hash) for each record, skipping
        the header. No key needed."""
        if not self.path.exists():
            return
        with self.path.open() as f:
            first = True
            for line_no, line in enumerate(f):
                complete = line.endswith("\n")
                line = line.strip()
                if not line:
                    continue
                if first:                     # header line
                    first = False
                    continue
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

    def events(self) -> Iterator[Event]:
        """Replay the log as decrypted events, verifying the chain as it goes.

        Raises CryptoError on a broken chain or a record that fails to
        authenticate; it never yields a partially-trusted event."""
        prev = GENESIS
        for seq, rec_prev, sealed, rec_hash in self._iter_raw():
            if rec_prev != prev:
                raise CryptoError(
                    f"chain broken at seq {seq}: prev_hash does not match")
            if _record_hash(seq, rec_prev, sealed) != rec_hash:
                raise CryptoError(f"record hash mismatch at seq {seq}")
            aad = f"{seq}:{rec_prev}".encode("utf-8")
            payload = json.loads(open_sealed(self._key, sealed, aad))
            yield Event.from_dict(payload["event"])
            prev = rec_hash

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
        return self._count
