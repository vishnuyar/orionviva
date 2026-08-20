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
log = logging.getLogger(__name__)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _record_hash(seq: int, prev_hash: str, sealed: dict) -> str:
    body = {"seq": seq, "prev_hash": prev_hash, "sealed": sealed}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


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
            return cls(path, key, KdfParams.from_dict(header["kdf"]))

        # New store: mint a header (KDF salt + check token) and write it as line 0.
        path.parent.mkdir(parents=True, exist_ok=True)
        header, key = new_vault_header(passphrase)
        with path.open("w") as f:
            f.write(json.dumps(header, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return cls(path, key, KdfParams.from_dict(header["kdf"]))

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
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        log.debug("append seq=%d type=%s", seq, event.event_type)
        return record

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
        passphrase. Returns False and the count reached at the first break."""
        prev = GENESIS
        count = 0
        for seq, rec_prev, sealed, rec_hash in self._iter_raw():
            if rec_prev != prev:
                return False, count
            if _record_hash(seq, rec_prev, sealed) != rec_hash:
                return False, count
            prev = rec_hash
            count += 1
        return True, count

    def __len__(self) -> int:
        return self._count
