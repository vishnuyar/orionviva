"""Encryption-at-rest envelope for OrionViva's ledger (ADR-005).

Encryption from commit one, not a later optimization: the ledger holds the
user's real financial life, and what cannot be decrypted cannot be leaked or
subpoenaed (principle 3 — a breach must be a bad day, not a ruin). This module
is the versioned crypto envelope that promise stands on.

Design — deliberately boring, because trust wants boring crypto:
  - **AES-256-GCM** for authenticated encryption. Every sealed record carries
    its own authentication tag, so tampering with a ciphertext is detected on
    open, never silently accepted.
  - The key is derived from a passphrase with **scrypt** (memory-hard), and is
    never stored. A random salt sits beside the data; the passphrase does not.
  - The envelope is **versioned**. ``VERSION`` names the algorithm and the KDF,
    so a future scheme can be introduced without stranding data written under
    this one. Changing a parameter is a new version, never a silent edit.

Nothing here reads the passphrase from disk or config — it comes from the caller
(who reads it from an env var or an interactive prompt). A passphrase sitting in
a file would defeat the entire point.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

VERSION = "viva-vault-aesgcm-scrypt-v1"

# scrypt cost parameters — interactive-login grade. Recorded here (not hidden)
# because they are part of the versioned envelope and travel in the file header.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1

KEY_LEN = 32     # AES-256
SALT_LEN = 16
NONCE_LEN = 12   # 96-bit nonce, the GCM standard


class CryptoError(Exception):
    """Encryption or decryption failed. On open this most often means a wrong
    passphrase or tampered data — both must be loud, never swallowed."""


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

# One passphrase protects a whole vault (the event log and the raw-blob store
# alike). These two helpers are the shared discipline: mint a header that records
# the KDF and a check token, and re-derive + verify the key on open. Fail fast on
# a wrong passphrase, even before a single record is read.

CHECK_TOKEN = b"viva-vault-ok"
CHECK_AAD = b"header"


def new_vault_header(passphrase: str) -> tuple[dict, bytes]:
    """Create a fresh vault header and return (header, derived_key)."""
    kdf = KdfParams.new()
    key = derive_key(passphrase, kdf)
    header = {"v": VERSION, "kdf": kdf.to_dict(),
              "check": seal(key, CHECK_TOKEN, CHECK_AAD)}
    return header, key


def open_vault_header(header: dict, passphrase: str) -> bytes:
    """Re-derive the key from a stored header, verifying the passphrase."""
    if header.get("v") != VERSION:
        raise CryptoError(
            f"header written with envelope {header.get('v')!r}; "
            f"this build reads {VERSION!r}"
        )
    key = derive_key(passphrase, KdfParams.from_dict(header["kdf"]))
    if open_sealed(key, header["check"], CHECK_AAD) != CHECK_TOKEN:
        raise CryptoError("wrong passphrase")
    return key
