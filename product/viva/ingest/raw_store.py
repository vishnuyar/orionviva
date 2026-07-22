"""Raw capture: every uploaded file, encrypted, before any judgment (ADR-003/T3).

The doctrine is absolute — capture the raw bytes of everything, always, even a
document v0 cannot yet model. You can re-project a held document later; you can
never re-derive one you discarded. This store is where the raw bytes live.

Content-addressed by SHA-256 (ADR-007 record identity): the address *is* the
fingerprint, so re-uploading the same file is a free no-op rather than a
duplicate. Each blob is sealed with the same versioned AES-256-GCM envelope as
the event log (ADR-005), with the content hash bound into the aad.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..crypto import (new_vault_header, open_sealed, open_vault_header, seal)

_HEADER = "raw-header.json"


class RawStore:
    """An encrypted, content-addressed blob store for raw uploaded files."""

    def __init__(self, directory: Path, key: bytes) -> None:
        self.dir = Path(directory)
        self._key = key

    @classmethod
    def open(cls, directory: Path, passphrase: str) -> "RawStore":
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        header_path = directory / _HEADER
        if header_path.exists():
            key = open_vault_header(json.loads(header_path.read_text()), passphrase)
        else:
            header, key = new_vault_header(passphrase)
            header_path.write_text(json.dumps(header, ensure_ascii=False))
        return cls(directory, key)

    @staticmethod
    def fingerprint(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _blob_path(self, doc_id: str) -> Path:
        return self.dir / f"{doc_id}.blob"

    def put(self, data: bytes) -> str:
        """Store raw bytes encrypted; return the content-address (doc_id).
        Idempotent: the same bytes yield the same id and are written once."""
        doc_id = self.fingerprint(data)
        path = self._blob_path(doc_id)
        if not path.exists():
            sealed = seal(self._key, data, aad=doc_id.encode("utf-8"))
            path.write_text(json.dumps(sealed, ensure_ascii=False))
        return doc_id

    def has(self, doc_id: str) -> bool:
        return self._blob_path(doc_id).exists()

    def get(self, doc_id: str) -> bytes:
        """Decrypt and return the raw bytes. Raises CryptoError on tampering."""
        sealed = json.loads(self._blob_path(doc_id).read_text())
        return open_sealed(self._key, sealed, aad=doc_id.encode("utf-8"))

    def doc_ids(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.blob"))
