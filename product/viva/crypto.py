"""Encryption-at-rest envelope for OrionViva's ledger.

The versioned envelope every sealed record in a vault is written under:

  - **AES-256-GCM** for authenticated encryption. Every sealed record carries
    its own authentication tag, so tampering with a ciphertext is detected on
    open, never silently accepted.
  - The key is derived from a passphrase with **scrypt** (memory-hard), and is
    never stored. A random salt sits beside the data; the passphrase does not.
  - The envelope is **versioned**. ``VERSION`` names the record/raw-store
    algorithm and KDF; ``HEAD_BOUND_HEADER_VERSION`` additionally binds the
    event log's authenticated commit-head requirement into its check token.
    Changing either contract is a new version, never a silent edit.

Nothing here reads the passphrase from disk or config: it comes from the caller,
which reads it from an env var or an interactive prompt.

The passphrase is the only way in: there is no second wrap of this key and no
recovery phrase, so a lost passphrase is a lost vault.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

VERSION = "viva-vault-aesgcm-scrypt-v1"
# Event logs which require an authenticated commit head use a distinct header
# envelope version.  It is deliberately the same byte length as the legacy
# version: a legacy JSONL header can be upgraded in place without moving any
# encrypted record or replacing the inode writers have locked.
HEAD_BOUND_HEADER_VERSION = "viva-vault-aesgcm-scrypt-h1"
HEAD_CAPABILITY_VERSION = "head-v1"

# scrypt cost parameters — interactive-login grade. They are part of the
# versioned envelope and travel in the vault header.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1

KEY_LEN = 32     # AES-256
SALT_LEN = 16
NONCE_LEN = 12   # 96-bit nonce, the GCM standard


class CryptoError(Exception):
    """Encryption or decryption failed — on open, a wrong passphrase or tampered
    data. Every failure in this module raises it; none is swallowed."""


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


@dataclass(frozen=True)
class KdfParams:
    """How the key is stretched from the passphrase. The salt is stored (it is
    not secret); the passphrase never is."""

    salt: bytes
    n: int = SCRYPT_N
    r: int = SCRYPT_R
    p: int = SCRYPT_P

    def to_dict(self) -> dict:
        return {"salt": _b64e(self.salt), "n": self.n, "r": self.r, "p": self.p}

    @classmethod
    def from_dict(cls, d: dict) -> "KdfParams":
        return cls(salt=_b64d(d["salt"]), n=int(d["n"]), r=int(d["r"]), p=int(d["p"]))

    @classmethod
    def new(cls) -> "KdfParams":
        return cls(salt=os.urandom(SALT_LEN))


def derive_key(passphrase: str, params: KdfParams) -> bytes:
    """Stretch a passphrase into a 32-byte AES key. Never persist the result."""
    if not passphrase:
        raise CryptoError("empty passphrase: refusing to derive a key from nothing")
    kdf = Scrypt(salt=params.salt, length=KEY_LEN, n=params.n, r=params.r, p=params.p)
    return kdf.derive(passphrase.encode("utf-8"))


def seal(key: bytes, plaintext: bytes, aad: bytes = b"") -> dict:
    """Encrypt one payload into a JSON-serialisable sealed record.

    ``aad`` (additional authenticated data) is authenticated but not encrypted.
    The store binds each record's position — its sequence number and the hash of
    the record before it — into the aad, so a ciphertext cannot be silently
    moved to a different place in the chain and still decrypt."""
    if len(key) != KEY_LEN:
        raise CryptoError(f"key must be {KEY_LEN} bytes, got {len(key)}")
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return {"v": VERSION, "nonce": _b64e(nonce), "ct": _b64e(ct)}


def open_sealed(key: bytes, sealed: dict, aad: bytes = b"") -> bytes:
    """Decrypt and authenticate a sealed record. Raises loudly on any failure."""
    v = sealed.get("v")
    if v != VERSION:
        raise CryptoError(
            f"unknown envelope version {v!r}; this build reads {VERSION!r}"
        )
    try:
        return AESGCM(key).decrypt(_b64d(sealed["nonce"]), _b64d(sealed["ct"]), aad)
    except Exception as e:  # InvalidTag and friends — wrong key or tampering
        raise CryptoError("decryption failed: wrong passphrase or tampered data") from e


# ------------------------------------------------------------------ vault header

# One passphrase protects a whole vault — the event log and the raw-blob store
# alike. These two helpers mint a header recording the KDF parameters and a
# sealed check token, and re-derive and verify the key on open, so a wrong
# passphrase fails before any record is read. The header holds the salt and the
# check token; it never holds the passphrase or the key.

CHECK_TOKEN = b"viva-vault-ok"
CHECK_AAD = b"header"


def _header_check_aad(version: str) -> bytes:
    if version == VERSION:
        return CHECK_AAD
    if version == HEAD_BOUND_HEADER_VERSION:
        return CHECK_AAD + b":" + json.dumps(
            {"event_head": HEAD_CAPABILITY_VERSION}, sort_keys=True,
            separators=(",", ":")).encode("utf-8")
    raise CryptoError(
        f"header written with envelope {version!r}; this build reads "
        f"{VERSION!r} and {HEAD_BOUND_HEADER_VERSION!r}")


def new_vault_header(
        passphrase: str, *, header_version: str = VERSION
        ) -> tuple[dict, bytes]:
    """Create a fresh vault header and return (header, derived_key)."""
    aad = _header_check_aad(header_version)
    kdf = KdfParams.new()
    key = derive_key(passphrase, kdf)
    header = {"v": header_version, "kdf": kdf.to_dict(),
              "check": seal(key, CHECK_TOKEN, aad)}
    return header, key


def rebind_vault_header(header: dict, key: bytes, *,
                        header_version: str) -> dict:
    """Return ``header`` with its check token bound to ``header_version``.

    The KDF stays byte-for-byte the same, so the vault key does not change.
    This is used to upgrade a legacy event-log header before the first modern
    append.  Unknown top-level fields are not copied: none were authenticated
    by the legacy format, and carrying one into the new header would imply
    authority it never had.
    """
    aad = _header_check_aad(header_version)
    return {
        "v": header_version,
        "kdf": dict(header["kdf"]),
        "check": seal(key, CHECK_TOKEN, aad),
    }


def verify_vault_header(header: dict, key: bytes) -> str:
    """Authenticate a header with an already-derived key; return its version."""
    version = header.get("v")
    aad = _header_check_aad(version)
    try:
        opened = open_sealed(key, header["check"], aad)
    except (KeyError, TypeError) as exc:
        raise CryptoError("vault header is incomplete") from exc
    if opened != CHECK_TOKEN:
        raise CryptoError("wrong passphrase")
    return version


def open_vault_header(header: dict, passphrase: str) -> bytes:
    """Re-derive the key from a stored header, verifying the passphrase."""
    try:
        key = derive_key(passphrase, KdfParams.from_dict(header["kdf"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CryptoError("vault header has invalid KDF parameters") from exc
    verify_vault_header(header, key)
    return key
