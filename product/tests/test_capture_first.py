"""Capture happens before reading, and a failed read cannot lose the bytes.

The ordering inside ``capture_and_ingest`` is the whole of capture-first: the
encrypted, content-addressed blob is written, and only then is the document
handed to whatever reads it. Every other guarantee in ingest rests on that one
statement being true in that one order — a reader that raises, refuses, or is
never configured still leaves the original recoverable.

The order is a property of one function and nothing else asserts it. A suite
that stayed green with the capture moved after the read would be reporting on
parsing, posting and parking while the invariant underneath them had gone, so
this file drives the ordering directly: one reader that looks in the store at
the moment it is called, and one that throws.

Both readers record what they saw and assert outside the call, because the
pipeline catches a raising reader by design — an assertion made inside one
would be swallowed and reported as a parked document.
"""

from __future__ import annotations

import pytest

from viva.ingest import PARKED, RawStore, ReadResult, capture_and_ingest
from viva.ledger import EventStore, Ledger

PW = "capture-first passphrase"
DOCUMENT = b"a document nothing in this suite can read"


def _stores(tmp_path):
    return (RawStore.open(tmp_path / "raw", PW),
            Ledger(EventStore.open(tmp_path / "events.jsonl", PW)))


def test_the_raw_blob_is_stored_before_the_reader_is_called(tmp_path):
    """The reader is handed a document the vault already holds.

    What is checked is not that the blob exists afterwards — it would, either
    way — but that it exists *at the instant the reader runs*, which is the
    only moment at which the two possible orderings differ."""
    raw, ledger = _stores(tmp_path)
    seen: dict[str, object] = {}

    def read_fn(data, doc_id):
        seen["id"] = doc_id
        seen["stored"] = raw.has(doc_id)
        seen["ids"] = list(raw.doc_ids())
        seen["bytes"] = raw.get(doc_id) if raw.has(doc_id) else None
        return ReadResult("unknown", 0.0, None, "nothing read this document")

    capture_and_ingest(raw, ledger, DOCUMENT, read_fn, filename="parked.pdf",
                       captured_at="2026-01-01")

    assert seen["id"] == RawStore.fingerprint(DOCUMENT)
    assert seen["stored"] is True, (
        "the reader was called before the document was captured; capture-first "
        "means the blob is already in the raw store when the read begins")
    assert seen["ids"] == [RawStore.fingerprint(DOCUMENT)]
    assert seen["bytes"] == DOCUMENT


def test_a_reader_that_raises_does_not_take_the_document_with_it(tmp_path):
    """A read that blows up costs the reading and never the original.

    The bytes are recoverable afterwards, byte for byte, under the address the
    content itself decides."""
    raw, ledger = _stores(tmp_path)
    doc_id = RawStore.fingerprint(DOCUMENT)

    def read_fn(data, did):
        raise RuntimeError("the reader fell over")

    result = capture_and_ingest(raw, ledger, DOCUMENT, read_fn,
                                filename="parked.pdf", captured_at="2026-01-01")

    assert result.action == PARKED
    assert raw.has(doc_id), (
        "the read raised and the document is gone; a document is captured "
        "before it is read so that a failing reader cannot lose it")
    assert raw.get(doc_id) == DOCUMENT


def test_a_reader_that_refuses_the_document_does_not_lose_it(tmp_path):
    """The same, for the refusal the pipeline handles by name rather than by
    catching everything: a document too costly to read is still a document the
    vault holds."""
    from viva.ingest.pipeline import DocumentTooLarge

    raw, ledger = _stores(tmp_path)
    doc_id = RawStore.fingerprint(DOCUMENT)

    def read_fn(data, did):
        raise DocumentTooLarge("beyond what this reader will take")

    result = capture_and_ingest(raw, ledger, DOCUMENT, read_fn,
                                filename="parked.pdf", captured_at="2026-01-01")

    assert result.action == PARKED
    assert raw.has(doc_id)
    assert raw.get(doc_id) == DOCUMENT


@pytest.mark.parametrize("outcome", ["read", "raised"])
def test_the_document_is_addressed_by_its_own_content_whatever_the_read_did(
        tmp_path, outcome):
    """One document, one address, decided by the bytes rather than by how the
    read went. A capture that waited on the read would have no address to give
    the reader in the first place."""
    raw, ledger = _stores(tmp_path)

    def read_fn(data, doc_id):
        if outcome == "raised":
            raise RuntimeError("the reader fell over")
        return ReadResult("unknown", 0.0, None, "nothing read this document")

    capture_and_ingest(raw, ledger, DOCUMENT, read_fn,
                       captured_at="2026-01-01")

    assert raw.doc_ids() == [RawStore.fingerprint(DOCUMENT)]
