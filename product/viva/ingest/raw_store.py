"""Raw capture: every uploaded file, encrypted, before any judgment.

Every uploaded file lands here before it is judged, including one no projector
can yet read, so a held document can be re-projected later.

Content-addressed by SHA-256: the address is the fingerprint, so re-uploading
the same file is a no-op rather than a duplicate. Each blob is sealed with the
same versioned AES-256-GCM envelope as the event log, with the content hash
bound into the aad.
"""

from __future__ import annotations

import hashlib
import base64
import stat
import json
import logging
import os
import tempfile
from contextlib import contextmanager

from ..ledger.platform_io import lock_writer, unlock_writer, replace_commit_head
from pathlib import Path

from ..crypto import (new_vault_header, open_sealed, open_vault_header, seal)

_HEADER = "raw-header.json"
log = logging.getLogger(__name__)


class RawStore:
    """An encrypted, content-addressed blob store for raw uploaded files."""

    def __init__(self, directory: Path, key: bytes) -> None:
        self.dir = Path(directory)
        self._key = key

    def fork(self) -> "RawStore":
        """A process-local handle sharing only the already-derived key."""
        return RawStore(self.dir, self._key)

    @classmethod
    def open(cls, directory: Path, passphrase: str) -> "RawStore":
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        header_path = directory / _HEADER
        if header_path.exists():
            from ..startup_diagnostics import span
            with span("credential_kdf"):
                key = open_vault_header(json.loads(header_path.read_text()), passphrase)
        else:
            from ..startup_diagnostics import span
            with span("credential_kdf"):
                header, key = new_vault_header(passphrase)
            _durable_json(header_path, header)
        return cls(directory, key)

    @staticmethod
    def fingerprint(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _blob_path(self, doc_id: str) -> Path:
        return self.dir / f"{doc_id}.blob"

    @contextmanager
    def document_lock(self, doc_id: str):
        """Serialize ingestion of this document across threads and processes."""
        if len(doc_id) != 64 or any(c not in "0123456789abcdef" for c in doc_id):
            raise ValueError("invalid document address")
        with (self.dir / f"{doc_id}.lock").open("a+b") as held:
            lock_writer(held.fileno())
            try:
                yield
            finally:
                unlock_writer(held.fileno())

    def put(self, data: bytes) -> str:
        """Store raw bytes encrypted; return the content-address (doc_id).
        Idempotent: the same bytes yield the same id and are written once."""
        doc_id = self.fingerprint(data)
        path = self._blob_path(doc_id)
        if not path.exists():
            sealed = seal(self._key, data, aad=doc_id.encode("utf-8"))
            _durable_json(path, sealed)
            log.debug("raw put: stored %d bytes as %s", len(data), doc_id[:12])
        else:
            if self.get(doc_id) != data:
                raise ValueError("captured content does not match its address")
            log.debug("raw put: %s already stored (dedup)", doc_id[:12])
        return doc_id

    def has(self, doc_id: str) -> bool:
        return self._blob_path(doc_id).exists()

    def get(self, doc_id: str) -> bytes:
        """Decrypt and return the raw bytes. Raises CryptoError on tampering."""
        sealed = json.loads(self._blob_path(doc_id).read_text())
        return open_sealed(self._key, sealed, aad=doc_id.encode("utf-8"))

    def get_bounded(self, doc_id: str, *, max_plaintext: int = 8 * 1024 * 1024,
                    max_envelope: int = 12 * 1024 * 1024) -> bytes:
        """Authenticate a bounded regular blob without following symlinks.

        Opening relative to an already opened directory avoids a pathname
        check/read race. Content-address verification is additional to AEAD.
        """
        if (not isinstance(doc_id, str) or len(doc_id) != 64 or
                any(c not in "0123456789abcdef" for c in doc_id)):
            raise ValueError("invalid document address")
        directory = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(f"{doc_id}.blob", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, "rb") as blob:
            before = os.fstat(blob.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("original is not regular")
            if before.st_size > max_envelope:
                raise OverflowError("original exceeds preview bound")
            encoded = blob.read(max_envelope + 1)
            after = os.fstat(blob.fileno())
            if (len(encoded) > max_envelope or before.st_size != after.st_size or
                    before.st_mtime_ns != after.st_mtime_ns):
                raise ValueError("original changed during read")
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate original envelope field")
                result[key] = value
            return result
        sealed = json.loads(encoded, object_pairs_hook=unique_object)
        from ..crypto import VERSION
        if (not isinstance(sealed, dict) or set(sealed) != {"v", "nonce", "ct"} or
                sealed["v"] != VERSION or
                not isinstance(sealed["nonce"], str) or not isinstance(sealed["ct"], str)):
            raise ValueError("invalid original envelope")
        if len(sealed["ct"]) > 4 * ((max_plaintext + 18) // 3):
            raise OverflowError("original exceeds preview bound")
        nonce = base64.b64decode(sealed["nonce"], validate=True)
        ciphertext = base64.b64decode(sealed["ct"], validate=True)
        if len(nonce) != 12 or len(ciphertext) < 16:
            raise ValueError("invalid original envelope")
        if len(ciphertext) > max_plaintext + 16:
            raise OverflowError("original exceeds preview bound")
        data = open_sealed(self._key, sealed, aad=doc_id.encode("ascii"))
        if hashlib.sha256(data).hexdigest() != doc_id:
            raise ValueError("original address mismatch")
        return data

    def doc_ids(self, *, max_count: int | None = None) -> list[str]:
        ids = []
        for path in self.dir.glob("*.blob"):
            ids.append(path.stem)
            if max_count is not None and len(ids) > max_count:
                raise ValueError("raw document presence exceeds its row bound")
        return sorted(ids)


def _durable_json(path: Path, value: dict) -> None:
    """Publish only a fully flushed encrypted envelope or key header."""
    fd, temporary_name = tempfile.mkstemp(prefix=".capture-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(value, ensure_ascii=False))
            output.flush()
            os.fsync(output.fileno())
        replace_commit_head(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
