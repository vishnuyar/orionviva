"""Privately issued pinned public-source ownership and retained admissions."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import threading
import time
from types import MappingProxyType
import weakref

from ..sample import resources, curation
from ..ingest.pipeline_models import ReadResult
from ..ingest.statement import from_model_json
from .store import AuthorityError, canonical

_OWNERS = weakref.WeakKeyDictionary()
_LOCK = threading.RLock()


@dataclass(frozen=True)
class _OwnedPack:
    root: object
    identity: str
    documents: tuple[str, ...]
    rows: object
    setup_seconds: float


class CuratedSource:
    """A source capability issued only by complete pinned-pack validation."""
    __slots__ = ("__weakref__",)

    def __init__(self):
        raise AuthorityError("CuratedSource.open must validate the pinned source pack")

    @classmethod
    def open(cls, pack_root=None):
        if cls is not CuratedSource or (pack_root is not None and not isinstance(pack_root, Path)):
            raise AuthorityError("a public source directory is required")
        started = time.perf_counter()
        pack = resources.load_pack(pack_root)
        metadata = {"sample_version": resources.VERSION,
                    "manifest_sha256": resources.MANIFEST_SHA256,
                    "readings_sha256": resources.READINGS_SHA256,
                    "reading_contract": curation.CONTRACT,
                    "document_count": len(pack.documents), "source_event_count": pack.source_event_count}
        documents, rows = [], {}
        for document in pack.documents:
            reading = pack.readings[document["sha256"]]
            detached = {**document, "doc_type": reading["doc_type"]}
            documents.append(canonical(detached))
            rows[document["sha256"]] = (canonical(detached), canonical(reading))
        owner = object.__new__(CuratedSource)
        with _LOCK:
            _OWNERS[owner] = _OwnedPack(pack.root, canonical(metadata), tuple(documents),
                                      MappingProxyType(rows), time.perf_counter() - started)
        return owner

    @property
    def identity(self):
        return json.loads(_owned(self).identity)

    @property
    def setup_seconds(self):
        return _owned(self).setup_seconds

    @property
    def documents(self):
        return tuple(json.loads(document) for document in _owned(self).documents)

    def original(self, doc_id):
        state, document, _row = _member(self, doc_id)
        data = state.root.joinpath(document["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != doc_id:
            raise AuthorityError("pinned original changed")
        return data


def _owned(owner):
    with _LOCK:
        state = _OWNERS.get(owner) if type(owner) is CuratedSource else None
    if state is None:
        raise AuthorityError("source ownership was not issued by pinned validation")
    return state


def _member(owner, doc_id):
    state = _owned(owner)
    if type(doc_id) is not str or doc_id not in state.rows:
        raise AuthorityError("original is not a pinned source member")
    document, row = state.rows[doc_id]
    return state, json.loads(document), json.loads(row)


def issue(owner, original, doc_id):
    state, document, row = _member(owner, doc_id)
    if hashlib.sha256(original).hexdigest() != doc_id or row["document_sha256"] != doc_id or row["document_id"] != document["id"]:
        raise AuthorityError("pinned source membership differs")
    envelope = canonical(row["envelope"])
    source = {"kind": "local-curation-v1", "sample_version": resources.VERSION,
              "corpus_manifest_sha256": resources.MANIFEST_SHA256,
              "readings_sha256": resources.READINGS_SHA256,
              "reading_contract": curation.CONTRACT, "document_sha256": doc_id,
              "reading_sha256": hashlib.sha256(envelope.encode()).hexdigest()}
    admission = {"document": document, "reading_sha256": hashlib.sha256(canonical(row).encode()).hexdigest(),
                 "envelope_sha256": source["reading_sha256"], "locale": row["locale"],
                 "currency": row["currency"], "pack": json.loads(state.identity), "acquisition": source}
    reading = ReadResult(row["doc_type"], None, facts=None, raw_text=envelope,
                         source_locale=row["locale"], acquisition=source)
    return reading, admission


def authenticate(store, receipt, reading):
    """Recheck retained ownership independently of normalized interpretations."""
    admission_row = store._row("source_admissions", "doc_id=?", (receipt["doc_id"],))
    if admission_row is None or store._curated_owner is None:
        raise AuthorityError("the pinned source owner must be reattached")
    admitted = json.loads(admission_row["body"])
    original = store.original(receipt["doc_id"])
    expected_reading, expected = issue(store._curated_owner, original, receipt["doc_id"])
    from .store import _encode
    tags = json.loads(receipt["capture_types"])
    if (admitted != {**expected, "read_context_id": tags.get("read_context_id")}
            or reading != _encode(expected_reading) or receipt["contract"] != curation.CONTRACT):
        raise AuthorityError("retained reading differs from its pinned membership")
    return original, admitted


def derive(store, receipt, reading):
    """Pure source interpretation; no authority rows are created here."""
    started = time.perf_counter()
    original, admitted = authenticate(store, receipt, reading)
    body = {"doc_id": receipt["doc_id"], "doc_type": reading["doc_type"],
            "response_text": reading["raw_text"], "parse_ok": True, "parse_error": None,
            "phase": "extract", "acquisition": admitted["acquisition"],
            "normalization_locale": admitted["locale"], "source_currency": admitted["currency"]}
    text = curation.decode_retained_input(body)
    envelope = curation.decode_envelope(body["response_text"], body["doc_type"])
    pages = curation.validate_pdf_cells(original, envelope)
    if pages != admitted["document"]["page_count"]:
        raise AuthorityError("source page count differs from admitted manifest")
    store.last_source_timings["source_validation_seconds"] = time.perf_counter() - started
    from ..ingest.registry import profile_for, BALANCE_IDENTITY
    profile = profile_for(body["doc_type"])
    if profile is None or profile.identity != BALANCE_IDENTITY or profile.account_kind not in {"depository", "liability"}:
        return None, []
    parsed = time.perf_counter()
    facts, error = from_model_json(text, receipt["doc_id"], admitted["locale"], admitted["currency"])
    if facts is None or error:
        raise AuthorityError("bound source observations could not normalize")
    facts.doc_type = body["doc_type"]
    facts.doc_type_confidence = None
    facts.acquisition = dict(admitted["acquisition"])
    facts.validated_source_page_count = pages
    page_values = [facts.opening_page, facts.closing_page, facts.source_account_ref_page]
    page_values.extend(line.page for line in facts.transactions)
    if any(value is not None and (type(value) is not int or not 1 <= value <= pages) for value in page_values):
        raise AuthorityError("typed provenance is outside its captured source")
    occurrences = []
    for ordinal, event_id in enumerate(envelope["source_event_ids"]):
        cell = next(cell for cell in envelope["source_cells"] if cell["field"] == f"/transactions/{ordinal}/amount_raw")
        occurrences.append(dict(doc_id=receipt["doc_id"], line_index=ordinal,
            event_id=event_id, date=facts.transactions[ordinal].date, page=cell["page"], raw=cell["raw"]))
    store.last_source_timings["parse_seconds"] = time.perf_counter() - parsed
    return facts, occurrences


def interpret_curated(store, receipt, reading):
    facts, occurrences = derive(store, receipt, reading)
    for occurrence in occurrences:
        store._put("source_occurrences", occurrence)
    return facts
