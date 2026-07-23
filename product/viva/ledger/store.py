"""The encrypted, append-only, hash-chained event store (ADR-004 + ADR-005).

The events are the source of truth; everything else is a projection rebuilt by
replaying them. This store is where they live, and it reconciles two invariants
at once:

  - **Append-only + tamper-evident** (ADR-004). Each record embeds the hash of
    the record before it, so dropping, reordering, or splicing records breaks
    the chain visibly. The chain can be verified *without the key* — integrity
    is checkable even by someone who cannot read the contents.
  - **Encrypted from commit one** (ADR-005). Each event body is sealed with
    AES-256-GCM under a passphrase-derived key. The record's position (sequence
    number + previous hash) is bound into the GCM aad, so a ciphertext cannot be
    moved to a different slot and still decrypt. Confidentiality and per-record
    integrity from GCM; sequence integrity from the chain — defence in depth.

File format (one JSON object per line):
    line 0   header:  {"v", "kdf", "check"}   — the versioned crypto envelope +
             a sealed check token that fails fast on a wrong passphrase.
    line 1.. records: {"seq", "prev_hash", "sealed", "record_hash"} — the chain.

This is the product-grade sibling of viva-bench's ``capture.py``: the same
hash-chain pattern, now carrying real money and therefore encrypted.
"""

from __future__ import annotations

import hashlib
import json
import logging
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

    Open (or create) with a passphrase. The key is derived on open and held only
    in memory for the store's lifetime; it is never written anywhere."""

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
        log.debug("EventStore opened %s with %d events", self.path, self._count)

    # --------------------------------------------------------------- lifecycle

    @classmethod
    def open(cls, path: Path, passphrase: str) -> "EventStore":
        """Open an existing store or create a new one, verifying the passphrase.

        A wrong passphrase fails immediately on the header check token, even for
        an empty store — you never get a silently-unreadable ledger."""
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
        return cls(path, key, KdfParams.from_dict(header["kdf"]))

    # ------------------------------------------------------------------ append

    def append(self, event: Event) -> dict:
        """Seal, chain, and persist one event. Returns the record as written."""
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
        with self.path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._last_hash = rec_hash
        self._count += 1
        log.debug("append seq=%d type=%s", seq, event.event_type)
        return record

    # ------------------------------------------------------------------- reads

    def _iter_raw(self) -> Iterator[tuple[int, str, dict, str]]:
        """Yield (seq, prev_hash, sealed, record_hash) for each record, skipping
        the header. No key needed."""
        if not self.path.exists():
            return
        with self.path.open() as f:
            first = True
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if first:                     # header line
                    first = False
                    continue
                rec = json.loads(line)
                yield (rec["seq"], rec["prev_hash"], rec["sealed"],
                       rec["record_hash"])

    def events(self) -> Iterator[Event]:
        """Replay the log as decrypted events, verifying the chain as it goes.

        Raises CryptoError on a broken chain or a record that fails to
        authenticate — a corrupted ledger must refuse to read, never guess."""
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

        This is the integrity check someone can run who holds the file but not
        the passphrase — the tamper-evidence promise, standing on its own."""
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
