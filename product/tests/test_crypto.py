"""The crypto envelope: round-trips, and every failure mode loud."""

import pytest

from viva.crypto import (KdfParams, CryptoError, derive_key, open_sealed, seal,
                         VERSION, KEY_LEN)


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
