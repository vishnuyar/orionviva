"""Ordinary typed CD capture encoding, without storage or custody authority."""
from __future__ import annotations

from dataclasses import fields
import json
import math
import re

from ..ingest import instrument_contracts as c
from ..ingest.instrument_read import InstrumentReadFacts
from ..ingest.pipeline_models import ModelPhase, ReadResult
from ..normalization_context import ExtractionNormalizationContext, encode_context


_MAX_BODY_BYTES = 8 * 1024 * 1024


class ReceiptEncodingError(ValueError):
    """A supplied reading cannot be represented by this capture profile."""


def _safe_json(value, active=None):
    """Check exact JSON shapes, Unicode, finite numbers and ancestor cycles."""
    if value is None or type(value) in (bool, int):
        return
    if type(value) is str:
        value.encode("utf-8")
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ReceiptEncodingError("nonfinite capture number")
        return
    if type(value) not in (list, dict):
        raise ReceiptEncodingError("capture value is outside JSON shapes")
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ReceiptEncodingError("cyclic capture value")
    active.add(identity)
    try:
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise ReceiptEncodingError("capture object key must be exact text")
                key.encode("utf-8")
                _safe_json(item, active)
        else:
            for item in value:
                _safe_json(item, active)
    finally:
        active.remove(identity)


def _canonical(value):
    _safe_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _typed_fact(value):
    # Validate each actual node before descending, then reconstruct through its
    # class constructor. Instance overrides of validation/serialization methods
    # cannot conceal corrupted frozen dataclass fields.
    c.ClosedFact.__post_init__(value)
    values = {}
    for field in fields(value):
        item = getattr(value, field.name)
        if isinstance(item, c.ClosedFact):
            item = _typed_fact(item)
        elif type(item) is tuple:
            item = tuple(_typed_fact(child) if isinstance(child, c.ClosedFact) else child
                         for child in item)
        values[field.name] = item
    return type(value)(**values)


def _context(value):
    if value is None:
        return None
    if type(value) is not ExtractionNormalizationContext or value.schema_version != 1:
        raise ReceiptEncodingError("exact schema one extraction context required")
    checked = ExtractionNormalizationContext(
        value.schema_version, value.normalization_rules_version,
        value.parser_locale, value.parser_currency, value.instrument_source_contract)
    wire = encode_context(checked)
    if type(wire) is not dict or set(wire) != {
        "schema_version", "normalization_rules_version", "parser_locale", "parser_currency"
    }:
        raise ReceiptEncodingError("unexpected extraction context wire profile")
    return wire


def _metadata(value, *, phase=False):
    strings = (("phase", "model", "prompt_version", "raw_text", "input_mode",
                "resolved_model", "extraction_id") if phase else
               ("doc_type", "raw_text", "model", "prompt_version", "input_mode",
                "resolved_model", "source_locale"))
    for name in strings:
        if type(getattr(value, name)) is not str:
            raise ReceiptEncodingError("capture text metadata has the wrong type")
    if value.error is not None and type(value.error) is not str:
        raise ReceiptEncodingError("capture error metadata has the wrong type")
    for name in (("cost_usd",) if phase else ("doc_type_confidence", "cost_usd")):
        number = getattr(value, name)
        if type(number) not in (int, float) or (type(number) is float and not math.isfinite(number)):
            raise ReceiptEncodingError("capture numeric metadata must be finite")
    for name in (("input_tokens", "output_tokens", "phase_attempt") if phase else
                 ("input_tokens", "output_tokens")):
        if type(getattr(value, name)) is not int:
            raise ReceiptEncodingError("capture counter must be exact integer")
    for name in (("parse_ok", "usage_reported") if phase else ("usage_reported",)):
        if type(getattr(value, name)) is not bool:
            raise ReceiptEncodingError("capture flag must be exact boolean")


def encode_ordinary_cd_receipt(result, *, read_context_id) -> dict:
    """Return detached canonical strings under a capture-only CD profile.

    Context identifiers are shape checked only. Neither these tags nor a typed
    context authenticates source custody, locator linkage or financial meaning.
    """
    try:
        return _encode(result, read_context_id)
    except ReceiptEncodingError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise ReceiptEncodingError("invalid ordinary CD capture input") from None


def _encode(result, read_context_id):
    if (type(read_context_id) is not str
            or re.fullmatch("[0-9a-f]{64}", read_context_id) is None):
        raise ReceiptEncodingError("read context identifier must be a lowercase digest")
    if type(result) is not ReadResult:
        raise ReceiptEncodingError("exact ReadResult required")
    if (type(result.facts) is not InstrumentReadFacts
            or type(result.facts.payload) is not c.DepositFacts
            or result.facts.doc_type != "term_deposit_statement"):
        raise ReceiptEncodingError("exact CD reader facts and payload required")
    _metadata(result)
    checked = _typed_fact(result.facts)
    fact_wire = InstrumentReadFacts.to_dict(checked)
    InstrumentReadFacts.from_dict(fact_wire)
    if result.acquisition is not None and type(result.acquisition) is not dict:
        raise ReceiptEncodingError("capture acquisition must be a JSON object or null")
    _safe_json(result.acquisition)
    top_context = _context(result.normalization_context)
    if type(result.phases) is not list:
        raise ReceiptEncodingError("capture phases must be an exact list")
    phase_wires = []
    phase_types = []
    for phase in result.phases:
        if type(phase) is not ModelPhase:
            raise ReceiptEncodingError("exact ModelPhase required")
        _metadata(phase, phase=True)
        ids = phase.transport_receipt_ids
        if ids is not None and (type(ids) is not list or any(type(item) is not str for item in ids)):
            raise ReceiptEncodingError("transport identifiers must be a text list or null")
        if phase.transport_complete is not None and type(phase.transport_complete) is not bool:
            raise ReceiptEncodingError("transport completion must be boolean or null")
        context = _context(phase.normalization_context)
        phase_types.append("none" if context is None else "ExtractionNormalizationContext")
        phase_wires.append({
            "phase": phase.phase, "model": phase.model, "prompt_version": phase.prompt_version,
            "raw_text": phase.raw_text, "cost_usd": phase.cost_usd,
            "input_tokens": phase.input_tokens, "output_tokens": phase.output_tokens,
            "input_mode": phase.input_mode, "parse_ok": phase.parse_ok, "error": phase.error,
            "resolved_model": phase.resolved_model, "usage_reported": phase.usage_reported,
            "transport_receipt_ids": ids, "transport_complete": phase.transport_complete,
            "extraction_id": phase.extraction_id, "phase_attempt": phase.phase_attempt,
            "normalization_context": context,
        })
    body = {
        "doc_type": result.doc_type, "doc_type_confidence": result.doc_type_confidence,
        "facts": fact_wire, "error": result.error, "raw_text": result.raw_text,
        "model": result.model, "prompt_version": result.prompt_version,
        "input_mode": result.input_mode, "cost_usd": result.cost_usd,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        "phases": phase_wires, "resolved_model": result.resolved_model,
        "usage_reported": result.usage_reported, "source_locale": result.source_locale,
        "acquisition": result.acquisition, "normalization_context": top_context,
    }
    tags = {
        "version": 1, "mode": "ordinary_cd_capture_v1",
        "facts_runtime_type": "InstrumentReadFacts", "payload_runtime_type": "DepositFacts",
        "facts_wire_profile": "instrument_wrapper_emitted_capture_v1",
        "normalization_context_runtime_type": "none" if top_context is None else "ExtractionNormalizationContext",
        "context_wire_profile": "none" if top_context is None else "extraction_context_capture_encode_v1",
        "phase_context_runtime_types": phase_types, "read_context_id": read_context_id,
    }
    body_text = _canonical(body)
    if len(body_text.encode("utf-8")) > _MAX_BODY_BYTES:
        raise ReceiptEncodingError("capture body exceeds byte ceiling")
    return {"body": body_text, "facts": _canonical(fact_wire), "capture_types": _canonical(tags)}
