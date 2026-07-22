"""Raw capture: content-addressed, encrypted, deduplicated, tamper-evident."""

import json

import pytest

from viva.crypto import CryptoError
from viva.ingest import RawStore

PW = "raw store passphrase"


def test_put_is_content_addressed(tmp_path):
    store = RawStore.open(tmp_path, PW)
    doc_id = store.put(b"a checking statement PDF")
    assert doc_id == RawStore.fingerprint(b"a checking statement PDF")
    assert store.get(doc_id) == b"a checking statement PDF"


def test_same_bytes_dedup(tmp_path):
    store = RawStore.open(tmp_path, PW)
    a = store.put(b"same bytes")
    b = store.put(b"same bytes")
    assert a == b
    assert store.doc_ids() == [a]     # written once


def test_nothing_readable_at_rest(tmp_path):
    store = RawStore.open(tmp_path, PW)
    doc_id = store.put(b"ACCOUNT 12345 balance 9999.99")
    blob = (tmp_path / f"{doc_id}.blob").read_text()
    assert "ACCOUNT" not in blob and "9999.99" not in blob


def test_reopen_with_passphrase(tmp_path):
    doc_id = RawStore.open(tmp_path, PW).put(b"held file")
    assert RawStore.open(tmp_path, PW).get(doc_id) == b"held file"


def test_wrong_passphrase_rejected(tmp_path):
    RawStore.open(tmp_path, PW).put(b"held file")
    with pytest.raises(CryptoError):
        RawStore.open(tmp_path, "wrong")


def test_tampered_blob_fails(tmp_path):
    store = RawStore.open(tmp_path, PW)
    doc_id = store.put(b"held file")
    path = tmp_path / f"{doc_id}.blob"
    sealed = json.loads(path.read_text())
    sealed["ct"] = "AAAA" + sealed["ct"][4:]
    path.write_text(json.dumps(sealed))
    with pytest.raises(CryptoError):
        RawStore.open(tmp_path, PW).get(doc_id)
