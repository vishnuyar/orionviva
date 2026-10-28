"""Closed provenance for readings supplied by installed local sample resources."""
from __future__ import annotations
import re

VERSION_BINDINGS = {'five-year-life-v1': ((
    '97a92df2512beb4938c498d7f1b43d20d4e3800cc38e9ce83012dda252f46800',
    'dbd302f394113ecb66c730a6d4bb40636897ba40cb9c3e4345084fb215fe1eab', 'curated-source-reading-v2'),)}

FIELDS = {"kind", "sample_version", "corpus_manifest_sha256", "readings_sha256",
          "reading_contract", "document_sha256", "reading_sha256"}

def validate(value):
    if type(value) is not dict or set(value) != FIELDS:
        raise ValueError("invalid acquisition provenance")
    if (value["kind"] != "local-curation-v1" or value["sample_version"] != "five-year-life-v1"
            or value["reading_contract"] != "curated-source-reading-v2"):
        raise ValueError("unsupported acquisition provenance")
    for name in FIELDS - {"kind", "sample_version", "reading_contract"}:
        if type(value[name]) is not str or re.fullmatch("[0-9a-f]{64}", value[name]) is None:
            raise ValueError("invalid acquisition digest")
    bindings = VERSION_BINDINGS[value["sample_version"]]
    if (value["corpus_manifest_sha256"], value["readings_sha256"], value["reading_contract"]) not in bindings:
        raise ValueError("local curation resource identity is incompatible")
    return dict(value)

def local_read(body):
    if "acquisition" not in body:
        return False
    import hashlib
    source = validate(body["acquisition"])
    if (source["document_sha256"] != body.get("doc_id") or
            type(body.get("response_text")) is not str or
            source["reading_sha256"] != hashlib.sha256(body["response_text"].encode()).hexdigest()):
        raise ValueError("local reading content does not match its provenance")
    required = {"doc_id", "doc_type", "response_text", "parse_ok", "parse_error", "phase", "acquisition", "normalization_locale", "source_currency"}
    if not required <= set(body) or set(body) - required:
        raise ValueError("local acquisition read has unknown or missing fields")
    if body["phase"] != "extract" or body["normalization_locale"] != "en-US" or body["source_currency"] != "USD":
        raise ValueError("unsupported local acquisition normalization context")
    if set(body) & {"model", "model_role", "resolved_model", "prompt_version", "cost_usd",
                   "input_tokens", "output_tokens", "usage_reported"}:
        raise ValueError("local curation cannot claim model activity")
    return True


def classification(doc_id, confidence, acquisition):
    """Unavailable measured confidence needs explicit authorized local provenance."""
    if acquisition is None:
        if confidence is None:
            raise ValueError("model classification confidence is required")
        return
    source = validate(acquisition)
    if source["document_sha256"] != doc_id or confidence is not None:
        raise ValueError("local classification provenance does not match")
