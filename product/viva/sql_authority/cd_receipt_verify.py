"""Independent capture and incremental audit checks for retained CD readings."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum

from ..crypto import CryptoError
from .cd_capture_contract import (
    MAX_CAPTURE_BYTES, PROFILE, RECEIPT_KIND, INTERPRETATION_KIND,
    RESULT_FIELDS, PHASE_FIELDS, TAG_FIELDS,
)
from .store import IntegrityError, canonical


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate capture key")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("nonfinite capture number")


def _load(text, *, bound=None):
    if type(text) is not str or (bound is not None and len(text.encode("utf-8")) > bound):
        raise ValueError("capture text exceeds its bound")
    value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    if canonical(value) != text:
        raise ValueError("noncanonical capture text")
    text.encode("utf-8")
    return value


def _context(value):
    if value is None:
        return "none"
    from ..normalization_context import decode_context
    if (type(value) is not dict or set(value) != {
            "schema_version", "normalization_rules_version", "parser_locale", "parser_currency"
    } or type(value["schema_version"]) is not int or value["schema_version"] != 1):
        raise ValueError("unknown CD extraction context")
    decode_context(value)
    return "ExtractionNormalizationContext"


def _metadata(value, *, phase=False):
    strings = (("phase", "model", "prompt_version", "raw_text", "input_mode",
                "resolved_model", "extraction_id") if phase else
               ("doc_type", "raw_text", "model", "prompt_version", "input_mode",
                "resolved_model", "source_locale"))
    if any(type(value[key]) is not str for key in strings):
        raise ValueError("invalid CD capture text metadata")
    if value["error"] is not None and type(value["error"]) is not str:
        raise ValueError("invalid CD capture error")
    for key in (("cost_usd",) if phase else ("cost_usd", "doc_type_confidence")):
        number = value[key]
        if type(number) not in (int, float) or (type(number) is float and not math.isfinite(number)):
            raise ValueError("invalid CD capture number")
    for key in (("input_tokens", "output_tokens", "phase_attempt") if phase else
                ("input_tokens", "output_tokens")):
        if type(value[key]) is not int:
            raise ValueError("invalid CD capture counter")
    for key in (("usage_reported", "parse_ok") if phase else ("usage_reported",)):
        if type(value[key]) is not bool:
            raise ValueError("invalid CD capture flag")


def _emitted_payload(value):
    """Reconstruct the closed emitted representation from independently decoded nodes."""
    if is_dataclass(value):
        return {field.name: _emitted_payload(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("nonfinite emitted instrument value")
        return str(value)
    if type(value) is tuple:
        return [_emitted_payload(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("unknown emitted instrument node")


def decode_capture(receipt):
    """Decode closed retained wire without invoking its encoding producer."""
    try:
        if (type(receipt) is not dict or set(receipt) != {
                "doc_id", "contract", "body", "facts_type", "facts", "capture_types"
        } or receipt["facts_type"] != RECEIPT_KIND):
            raise ValueError("unknown CD receipt row")
        from .schema import valid_row
        if not valid_row("receipts", receipt):
            raise ValueError("invalid CD receipt row")
        body, facts, tags = (_load(receipt[key], bound=MAX_CAPTURE_BYTES)
                             for key in ("body", "facts", "capture_types"))
        if type(body) is not dict or set(body) != set(RESULT_FIELDS):
            raise ValueError("unknown CD reading fields")
        if type(tags) is not dict or set(tags) != set(TAG_FIELDS):
            raise ValueError("unknown CD capture tags")
        expected = {
            "version": 1, "mode": PROFILE, "facts_runtime_type": "InstrumentReadFacts",
            "payload_runtime_type": "DepositFacts",
            "facts_wire_profile": "instrument_wrapper_emitted_capture_v1",
        }
        if type(tags["version"]) is not int or any(tags[key] != value for key, value in expected.items()):
            raise ValueError("unsupported CD capture profile")
        context_id = tags["read_context_id"]
        if (type(context_id) is not str or len(context_id) != 64
                or any(char not in "0123456789abcdef" for char in context_id)):
            raise ValueError("invalid CD read-context reference")
        _metadata(body)
        if body["acquisition"] is not None and type(body["acquisition"]) is not dict:
            raise ValueError("invalid CD acquisition capture")
        context_type = _context(body["normalization_context"])
        if (tags["normalization_context_runtime_type"] != context_type
                or tags["context_wire_profile"] != (
                    "none" if context_type == "none" else "extraction_context_capture_encode_v1")):
            raise ValueError("CD context tag differs")
        if type(body["phases"]) is not list:
            raise ValueError("invalid CD phase capture")
        phase_types = []
        for phase in body["phases"]:
            if type(phase) is not dict or set(phase) != set(PHASE_FIELDS):
                raise ValueError("unknown CD phase fields")
            _metadata(phase, phase=True)
            ids = phase["transport_receipt_ids"]
            if ids is not None and (type(ids) is not list or any(type(item) is not str for item in ids)):
                raise ValueError("invalid CD transport identifiers")
            if phase["transport_complete"] is not None and type(phase["transport_complete"]) is not bool:
                raise ValueError("invalid CD transport completion")
            phase_types.append(_context(phase["normalization_context"]))
        if type(tags["phase_context_runtime_types"]) is not list or tags["phase_context_runtime_types"] != phase_types:
            raise ValueError("CD phase context tags differ")
        if body["facts"] != facts:
            raise ValueError("CD body and facts differ")
        from ..ingest.instrument_read import InstrumentReadFacts
        from ..ingest.instrument_contracts import DepositFacts
        typed = InstrumentReadFacts.from_dict(facts)
        if type(typed.payload) is not DepositFacts or typed.doc_type != "term_deposit_statement":
            raise ValueError("CD receipt has another typed family")
        emitted = {
            "doc_id": typed.doc_id, "doc_type": typed.doc_type,
            "doc_type_confidence": typed.doc_type_confidence, "currency": typed.currency,
            "instrument_facts": _emitted_payload(typed.payload),
        }
        if typed.acquisition is not None:
            emitted["acquisition"] = typed.acquisition
        if emitted != facts:
            raise ValueError("CD facts are outside the emitted wrapper profile")
        return body, tags, typed
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, UnicodeError):
        raise IntegrityError("retained CD capture is invalid") from None


def _dependencies(store, receipt, lookup):
    body, tags, facts = decode_capture(receipt)
    document = lookup("documents", (receipt["doc_id"],))
    captured = lookup("read_contexts", (tags["read_context_id"],))
    if document is None or document["contract"] != receipt["contract"] or captured is None:
        raise IntegrityError("CD capture dependencies are missing")
    try:
        original = store._original(receipt["doc_id"])
        if len(original) != document["byte_count"] or hashlib.sha256(original).hexdigest() != receipt["doc_id"]:
            raise ValueError("CD original custody differs")
        context = _load(captured["body"])
        from .reading import current_read_context
        if (hashlib.sha256(captured["body"].encode()).hexdigest() != tags["read_context_id"]
                or context != current_read_context(store._implementation_identity)):
            raise ValueError("CD installed read contract differs")
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError, CryptoError, OSError):
        raise IntegrityError("CD capture dependency binding differs") from None
    return body, facts, context


def _disposition(body, facts, doc_id):
    binding = "matched"
    if facts.doc_id != doc_id:
        reason = "document_mismatch"
        binding = "different"
    elif body["doc_type"] != facts.doc_type:
        reason = "classification_mismatch"
        binding = "different"
    elif body["error"] is not None:
        reason = "reader_error"
    elif not body["raw_text"]:
        reason = "no_raw_response"
    else:
        context = body["normalization_context"]
        currency = context["parser_currency"] if context is not None else None
        if context is None or currency is None or not currency.strip():
            reason = "no_parser_context"
        elif currency != facts.currency:
            reason = "context_currency_mismatch"
        else:
            from ..ingest.instrument_read import parser_for
            parsed, error = parser_for("term_deposit_statement")(
                body["raw_text"], doc_id, context["parser_locale"], currency)
            if parsed is None or error:
                reason = "parser_refused"
            else:
                reason = ("matched" if (parsed.doc_id, parsed.doc_type, parsed.currency, parsed.payload)
                          == (facts.doc_id, facts.doc_type, facts.currency, facts.payload) else "facts_differ")
    linkage = ("matched" if reason == "matched" else "invalid" if reason == "parser_refused" else
               "different" if reason in {"context_currency_mismatch", "facts_differ"} else "not_evaluated")
    return {"version": 1, "profile": PROFILE, "claim_binding": binding,
            "raw_linkage": linkage, "reason": reason}


def _interpretation(store, receipt, lookup):
    body, facts, captured = _dependencies(store, receipt, lookup)
    profile = captured["profiles"].get(body["doc_type"].strip().lower())
    context = {
        "format": captured["format"], "schema_version": captured["schema_version"],
        "implementation": captured["implementation"],
        "normalization_rules_version": captured["normalization_rules_version"],
        "profile_version": profile["profile_version"] if profile else None,
        "profile_identity": profile["identity"] if profile else None,
        "profile_kind": profile["account_kind"] if profile else None,
        "profile_descriptor": profile,
        "cd_capture": _disposition(body, facts, receipt["doc_id"]),
    }
    return dict(doc_id=receipt["doc_id"], facts_type=INTERPRETATION_KIND,
                facts=receipt["facts"], context=canonical(context))


def _lookup(store):
    from .schema import KEYS
    memo = {}
    def row(table, key):
        address = (table, key)
        if address not in memo:
            memo[address] = store._row(table, " AND ".join(name + "=?" for name in KEYS[table]), key)
        return memo[address]
    return row


def interpretation(store, receipt):
    """Describe retained inputs without admitting financial observations."""
    return _interpretation(store, receipt, _lookup(store))


def verify_operations(store, state, operations, *, revision=None):
    """Check affected CD records once at their authenticated replay prefix."""
    def lookup(table, key):
        return state[table].get(key)
    _verify_operations(store, lookup, operations, revision=revision)


def _affected_documents(lookup, operations):
    affected = set()
    checked = set()
    for operation in operations:
        row = operation["row"]
        doc_id = row.get("doc_id")
        if doc_id is not None and doc_id not in checked:
            checked.add(doc_id)
            receipt = lookup("receipts", (doc_id,))
            if receipt is not None and receipt["facts_type"] == RECEIPT_KIND:
                affected.add(doc_id)
        if operation["table"] == "interpretations" and row["facts_type"] == INTERPRETATION_KIND:
            affected.add(doc_id)
        if operation["table"] == "receipts" and row["facts_type"] == RECEIPT_KIND:
            affected.add(doc_id)
    return affected


def _verify_operations(store, lookup, operations, *, revision):
    affected = _affected_documents(lookup, operations)
    if not affected:
        return
    if len(affected) != 1:
        raise IntegrityError("one CD writer must retain one document")
    doc_id = next(iter(affected))
    receipt = lookup("receipts", (doc_id,))
    if receipt is None or receipt["facts_type"] != RECEIPT_KIND:
        raise IntegrityError("CD interpretation has no retained capture")
    receipt_writer = any(op["table"] == "receipts" for op in operations)
    allowed = {"receipts", "items"} if receipt_writer else {"interpretations", "findings", "validation_runs", "items"}
    if any(op["table"] not in allowed or op["row"].get("doc_id") != doc_id for op in operations):
        raise IntegrityError("CD writer contains foreign or financial operations")
    interpreted = lookup("interpretations", (doc_id,))
    if receipt_writer:
        _dependencies(store, receipt, lookup)
        if interpreted is not None:
            raise IntegrityError("CD capture must precede its interpretation")
    elif interpreted != _interpretation(store, receipt, lookup):
        raise IntegrityError("CD interpretation differs from retained inputs")
    item = lookup("items", (doc_id,))
    if (item is None or item["state"] != ("staged" if receipt_writer else "unsupported")
            or item["account_id"] != "" or item["reason"] != (
                "retained extraction awaiting validation" if receipt_writer else "unsupported_family")
            or (revision is not None and item["revision"] != revision)):
        raise IntegrityError("CD item acquired financial admission")
    for operation in operations:
        table, row = operation["table"], operation["row"]
        if table == "findings" and row != dict(doc_id=doc_id, code="unsupported_family", detail="No accepted financial rows were created."):
            raise IntegrityError("unknown CD unsupported finding")
        if table == "validation_runs" and (row["state"] != "unsupported" or row["detail"] != "unsupported_family"
                                           or (revision is not None and row["revision"] != revision)):
            raise IntegrityError("CD validation acquired financial admission")


def _current_sql_cd_scope(store, operations):
    """Test empty CD scope without materializing unrelated receipt bodies."""
    documents, explicit = set(), False
    for operation in operations:
        table, row = operation["table"], operation["row"]
        if row.get("doc_id") is not None:
            documents.add(row["doc_id"])
        if ((table == "receipts" and row["facts_type"] == RECEIPT_KIND)
                or (table == "interpretations" and row["facts_type"] == INTERPRETATION_KIND)):
            explicit = True
    if explicit:
        return True
    ordered = sorted(documents)
    for start in range(0, len(ordered), 200):
        chunk = ordered[start:start + 200]
        placeholders = ",".join("?" for _ in chunk)
        if store._read("SELECT 1 FROM receipts WHERE facts_type=? AND doc_id IN ("
                       + placeholders + ") LIMIT 1", (RECEIPT_KIND, *chunk)):
            return True
    return False


def verify_new_record(store, previous_revision, previous_head):
    """Authenticate the actual new SQL record before its native COMMIT."""
    from .schema import KEYS, valid_row
    from ..crypto import open_sealed
    try:
        terminal = store._read("SELECT revision,head,mac FROM control WHERE singleton=1")
        if len(terminal) != 1:
            raise ValueError("missing writer terminal")
        revision, head, mac = terminal[0]
        if not store._operations:
            if (revision, head) != (previous_revision, previous_head) or not hmac.compare_digest(mac, store._mac(revision, head)):
                raise ValueError("empty writer changed its boundary")
            return
        if revision != previous_revision + 1 or not hmac.compare_digest(mac, store._mac(revision, head)):
            raise ValueError("new writer terminal differs")
        records = store._read("SELECT sequence,previous_hash,envelope,record_hash FROM audit WHERE sequence=?", (revision,))
        commits = store._read("SELECT revision,head,mac FROM commits WHERE revision=?", (revision,))
        if len(records) != 1 or commits != [(revision, head, mac)]:
            raise ValueError("new writer commitment differs")
        sequence, previous, envelope, digest = records[0]
        if (sequence, previous, digest) != (revision, previous_head, head) or hashlib.sha256(canonical([sequence, previous, envelope]).encode()).hexdigest() != digest:
            raise ValueError("new writer record differs")
        payload = _load(open_sealed(store._audit_key, _load(envelope), aad=canonical([revision, previous_head]).encode()).decode())
        if (type(payload) is not dict or set(payload) != {"version", "operations"}
                or type(payload["version"]) is not int or payload["version"] != 1
                or type(payload["operations"]) is not list or not payload["operations"]):
            raise ValueError("unknown new audit payload")
        operations = payload["operations"]
        for operation in operations:
            if (type(operation) is not dict or set(operation) != {"table", "row"}
                    or not valid_row(operation["table"], operation["row"])):
                raise ValueError("unknown new audit operation")
        if operations != store._operations:
            raise ValueError("sealed operations differ from writer buffer")
        if not _current_sql_cd_scope(store, operations):
            return
        lookup = _lookup(store)
        # Ordered equality binds discovery to both the sealed record and buffer.
        if not _affected_documents(lookup, operations):
            return
        final = {}
        for operation in operations:
            table, row = operation["table"], operation["row"]
            key = tuple(row[column] for column in KEYS[table])
            final[table, key] = row
        for (table, key), row in final.items():
            if lookup(table, key) != row:
                raise ValueError("new audited row differs from SQL")
        _verify_operations(store, lookup, operations, revision=revision)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError, OverflowError, CryptoError, OSError):
        raise IntegrityError("new CD capture boundary is invalid") from None
