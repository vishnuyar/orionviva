"""The crypto envelope: round-trips, and every failure mode loud."""

import pytest

from viva import crypto
from viva.crypto import (KdfParams, CryptoError, derive_key, new_vault_header,
                         open_sealed, open_vault_header, seal, SALT_LEN,
                         VERSION, KEY_LEN)

# The vault is this file's subject, so it pays the real scrypt cost rather than
# the cheap one the rest of the suite mints under (tests/conftest.py).
pytestmark = pytest.mark.production_kdf


def _key(passphrase="correct horse battery staple"):
    return derive_key(passphrase, KdfParams.new())


def test_seal_open_roundtrip():
    key = _key()
    sealed = seal(key, b"hello money")
    assert sealed["v"] == VERSION
    assert open_sealed(key, sealed) == b"hello money"


def test_derived_key_is_correct_length():
    assert len(_key()) == KEY_LEN


def test_empty_passphrase_refused():
    with pytest.raises(CryptoError):
        derive_key("", KdfParams.new())


def test_wrong_key_fails_loudly():
    sealed = seal(_key("right"), b"secret")
    with pytest.raises(CryptoError):
        open_sealed(_key("wrong"), sealed)


def test_same_passphrase_same_salt_reproduces_key():
    params = KdfParams.new()
    assert derive_key("pw", params) == derive_key("pw", params)


def test_different_salt_different_key():
    assert derive_key("pw", KdfParams.new()) != derive_key("pw", KdfParams.new())


def test_aad_mismatch_fails():
    key = _key()
    sealed = seal(key, b"payload", aad=b"position-3")
    with pytest.raises(CryptoError):
        open_sealed(key, sealed, aad=b"position-4")


def test_tampered_ciphertext_fails():
    key = _key()
    sealed = seal(key, b"payload")
    # Flip a base64 char in the ciphertext.
    ct = list(sealed["ct"])
    ct[0] = "A" if ct[0] != "A" else "B"
    sealed["ct"] = "".join(ct)
    with pytest.raises(CryptoError):
        open_sealed(key, sealed)


def test_unknown_version_refused():
    key = _key()
    sealed = seal(key, b"x")
    sealed["v"] = "some-future-scheme-v9"
    with pytest.raises(CryptoError):
        open_sealed(key, sealed)


def test_kdf_params_roundtrip():
    p = KdfParams.new()
    p2 = KdfParams.from_dict(p.to_dict())
    assert p2.salt == p.salt and p2.n == p.n and p2.r == p.r and p2.p == p.p


def test_the_vault_header_never_stores_the_passphrase_or_the_key():
    """The header carries the KDF parameters and a sealed check token. Neither
    the passphrase nor the derived key appears anywhere in what is written."""
    import base64
    import json

    passphrase = "correct horse battery staple"
    header, key = new_vault_header(passphrase)
    written = json.dumps(header)

    assert passphrase not in written
    assert base64.b64encode(key).decode("ascii") not in written
    assert key.hex() not in written
    # The salt is stored — it is not secret and the key cannot be re-derived
    # without the passphrase.
    assert header["kdf"]["salt"]
    assert derive_key(passphrase, KdfParams.from_dict(header["kdf"])) == key


def test_a_wrong_passphrase_is_refused_by_the_header_alone():
    """`open_vault_header` fails before any record is read, and the failure is
    a CryptoError rather than a silently different key."""
    header, key = new_vault_header("right")
    assert open_vault_header(header, "right") == key
    with pytest.raises(CryptoError):
        open_vault_header(header, "wrong")


def test_the_production_cost_parameters_are_not_quietly_lowered():
    """The suite mints its vaults cheaply (tests/conftest.py), so the real cost
    needs something holding it in place. Nothing else in the repo does: before
    this test, `2 ** 15` appeared exactly once, at its own definition.

    Both halves matter. The constant is what a reader changes; the field default
    is what `KdfParams.new()` actually reads, since it passes only a salt. They
    can drift apart, and a vault minted after they do would be stretched at a
    cost nobody chose. Asserting the field default is also what keeps this test
    honest whatever the conftest does — the fixture replaces `new`, never this.
    """
    assert crypto.SCRYPT_N == 2 ** 15     # interactive-login grade, ~0.1s a derivation
    assert crypto.SCRYPT_R == 8
    assert crypto.SCRYPT_P == 1

    minted = KdfParams(salt=b"\x00" * SALT_LEN)
    assert (minted.n, minted.r, minted.p) == (2 ** 15, 8, 1)

    # And the opt-out is live. Without this, a typo in the marker name would
    # leave this file minting cheaply and silently stop exercising the real
    # parameters — the assertions above would still pass, because the fixture
    # replaces `new` and never touches the field default.
    assert KdfParams.new().n == 2 ** 15
