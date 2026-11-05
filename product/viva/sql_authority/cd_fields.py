"""Lossless structural associations for a retained CD reader wire value.

Caller-supplied document and page bounds check pointers only; they do not
authenticate custody, rendered pages, lexical evidence or financial authority.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math

from ..ingest.instrument_read import InstrumentReadFacts, validate_sources
from .store import MAX_RECEIPT_BYTES


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate wire object key")
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError("nonfinite wire number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite wire number")
    return number


def enumerate_wire_associations(
    wire_text: str, *, facts_id: str, document_id: str, page_count: int
) -> list[dict]:
    """Describe every retained typed field, preserving its decoded wire subtree.

    ``facts_id`` is an opaque caller namespace, not an issued permanent ID.
    Existing reader contracts validate the input; this function adds no monetary
    policy and never reencodes the typed facts to replace the original wire.
    """
    if type(wire_text) is not str:
        raise ValueError("wire input must be text")
    if any(type(value) is not str or not value.strip()
           for value in (facts_id, document_id)):
        raise ValueError("nonblank caller facts and document context required")
    if type(page_count) is not int or page_count < 1:
        raise ValueError("positive exact page count required")
    if len(wire_text.encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise ValueError("wire input exceeds receipt byte ceiling")
    try:
        wire = json.loads(wire_text, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant, parse_float=_finite_float)
    except RecursionError:
        raise ValueError("wire nesting exceeds decoder bounds") from None
    if type(wire) is not dict or wire.get("doc_type") != "term_deposit_statement":
        raise ValueError("CD reader wrapper required")
    facts = InstrumentReadFacts.from_dict(wire)
    if facts.doc_id != document_id:
        raise ValueError("wire document differs from supplied document context")
    validate_sources(facts.payload, document_id, page_count)

    rows = []

    def emit(path, field_type, value, *, omitted=False, mode=None, source_path=None):
        binding = None
        if value is not None and mode is not None:
            source = wire
            for token in source_path:
                source = source[token]
            if source is not None:
                binding = {"mode": mode, "source_path": source_path,
                           "document_id": source["doc_id"], "page": source["page"]}
        # Copy the complete association independently: parent subtrees, children,
        # paths and bindings must never share mutable objects across rows.
        rows.append(deepcopy({
            "version": 1, "facts_id": facts_id, "field_path": path,
            "field_type": field_type,
            "state": "omitted" if omitted else "null" if value is None else "present",
            "wire_value": value, "source_binding": binding, "lexical_binding": None,
        }))

    def own(path, field_type, value):
        emit(path, field_type, value, mode="own", source_path=path + ["source"])

    for name in ("doc_id", "doc_type", "doc_type_confidence", "currency", "acquisition"):
        emit([name], "metadata", wire.get(name), omitted=name not in wire)

    base = ["instrument_facts"]
    payload = wire["instrument_facts"]
    emit(base, "object", payload)
    identity_path = base + ["identity"]
    identity = payload["identity"]
    emit(identity_path, "object", identity)
    for name in ("institution", "account_reference", "holder"):
        own(identity_path + [name], "text", identity[name])

    emit(base + ["subtype"], "enum", payload["subtype"])
    for name, field_type in (("start", "date"), ("end", "date"),
                             ("opening", "money"), ("closing", "money")):
        own(base + [name], field_type, payload[name])

    movements_path = base + ["movements"]
    movements = payload["movements"]
    emit(movements_path, "population", movements)
    if movements is not None:
        for ordinal, movement in enumerate(movements):
            path = movements_path + [ordinal]
            emit(path, "object", movement)
            emit(path + ["kind"], "enum", movement["kind"])
            for name, field_type in (("amount", "money"), ("dated", "date"),
                                     ("reference", "text"), ("counterparty_reference", "text")):
                own(path + [name], field_type, movement[name])

    terms_path = base + ["terms"]
    terms = payload["terms"]
    emit(terms_path, "object", terms)
    if terms is not None:
        for name, field_type in (("principal", "money"), ("opened", "date"),
                                 ("maturity", "date"), ("rate", "rate")):
            own(terms_path + [name], field_type, terms[name])
        for name in ("rate_basis", "day_count"):
            emit(terms_path + [name], "enum", terms[name], mode="companion",
                 source_path=terms_path + [name + "_source"])
        for name in ("compounding", "withdrawal_restriction"):
            own(terms_path + [name], "text", terms[name])
        for name in ("rate_basis_source", "day_count_source"):
            path = terms_path + [name]
            emit(path, "source", terms[name], mode="self", source_path=path)

    own(base + ["uncredited_interest"], "money", payload["uncredited_interest"])
    return rows
