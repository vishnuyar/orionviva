"""Independent retained-instrument semantics and incremental writer boundaries."""
import hashlib
import hmac
import json

from ..crypto import CryptoError, open_sealed
from ..ingest import instrument_read
from ..ingest.instrument_contracts import ContractError
from .curated_instrument_contract import FAMILIES, PROFILE, INTERPRETATION_KIND, LEXICAL_SCOPE
from .schema import KEYS, valid_row
from .store import AuthorityError, IntegrityError, canonical


def _instrument_receipt(receipt):
    if receipt is None or receipt["facts_type"] != "curated":
        return False
    try:
        return json.loads(receipt["body"])["doc_type"] in FAMILIES
    except (ValueError, TypeError, KeyError):
        raise IntegrityError("curated instrument receipt is malformed") from None


def _expected(store, receipt, lookup):
    from .curated import instrument_inputs
    inputs = instrument_inputs(store, receipt, json.loads(receipt["body"]), lookup=lookup)
    admission, profile = inputs["admitted"], inputs["profile"]
    expected_facts = None
    outcome, failure = "unavailable", "parser_input_unavailable"
    if type(admission["currency"]) is str and admission["currency"]:
        failure = "parser_refused"
        try:
            parse = instrument_read.parser_for(inputs["doc_type"],
                source_contract=profile.instrument_source_contract, page_count=inputs["page_count"])
            proposal, error = parse(inputs["text"], receipt["doc_id"], admission["locale"], admission["currency"])
            if proposal is not None and not error:
                instrument_read.validate_sources(proposal.payload, receipt["doc_id"], inputs["page_count"])
                wrapper = instrument_read.InstrumentReadFacts(receipt["doc_id"], inputs["doc_type"], None,
                    proposal.payload, admission["currency"], dict(admission["acquisition"]))
                expected_facts = wrapper.to_dict()
                if instrument_read.InstrumentReadFacts.from_dict(expected_facts).to_dict() != expected_facts:
                    raise ValueError("instrument wrapper is not canonical")
                outcome, failure = "typed_retained", ""
        except (ContractError, ValueError, TypeError, KeyError):
            expected_facts = None
    expected_context = dict(version=1, profile=PROFILE, doc_type=inputs["doc_type"],
        parser_locale=admission["locale"], parser_currency=admission["currency"],
        instrument_source_contract=profile.instrument_source_contract, page_count=inputs["page_count"],
        validated_cell_count=inputs["validated_cell_count"], lexical_scope=LEXICAL_SCOPE,
        disposition=outcome, reason=failure, financial_admission=False)
    return dict(doc_id=receipt["doc_id"], facts_type=INTERPRETATION_KIND,
                facts=canonical(expected_facts), context=canonical(expected_context))


def _affected(store, lookup, operations):
    result = set()
    owned = None
    if store._curated_owner is not None:
        from .curated import _owned
        owned = _owned(store._curated_owner)
    for operation in operations:
        row = operation["row"]
        doc_id = row.get("doc_id")
        if doc_id is not None:
            receipt = lookup("receipts", (doc_id,))
            admission = lookup("source_admissions", (doc_id,))
            admitted_family = (admission is not None
                               and json.loads(admission["body"])["document"]["doc_type"] in FAMILIES)
            pinned_family = (owned is not None and doc_id in owned.rows
                             and json.loads(owned.rows[doc_id][0])["doc_type"] in FAMILIES)
            if _instrument_receipt(receipt) or receipt is not None and (admitted_family or pinned_family):
                result.add(doc_id)
        if operation["table"] == "interpretations" and row["facts_type"] == INTERPRETATION_KIND:
            result.add(doc_id)
    return result


def _verify(store, lookup, operations, revision):
    selected = _affected(store, lookup, operations)
    if not selected:
        return
    if len(selected) != 1:
        raise IntegrityError("curated instrument writer mixes documents")
    doc_id = next(iter(selected))
    receipt = lookup("receipts", (doc_id,))
    if not _instrument_receipt(receipt):
        raise IntegrityError("curated instrument interpretation has no raw reading")
    capturing = any(op["table"] == "receipts" for op in operations)
    allowed = ({"source_admissions", "receipts", "items"} if capturing
               else {"interpretations", "findings", "validation_runs", "items"})
    if any(op["table"] not in allowed or op["row"].get("doc_id") != doc_id for op in operations):
        raise IntegrityError("curated instrument writer creates foreign or financial rows")
    interpreted = lookup("interpretations", (doc_id,))
    if capturing:
        from .curated import instrument_inputs
        instrument_inputs(store, receipt, json.loads(receipt["body"]), lookup=lookup, derive=False)
        if interpreted is not None:
            raise IntegrityError("curated raw reading must precede derivation")
    elif interpreted != _expected(store, receipt, lookup):
        raise IntegrityError("curated instrument derivation differs from authenticated inputs")
    item = lookup("items", (doc_id,))
    expected_state = "staged" if capturing else "unsupported"
    expected_reason = "retained extraction awaiting validation" if capturing else "unsupported_family"
    if (item is None or item["state"] != expected_state or item["reason"] != expected_reason
            or item["account_id"] != "" or revision is not None and item["revision"] != revision):
        raise IntegrityError("curated instrument item acquired financial admission")
    for operation in operations:
        table, row = operation["table"], operation["row"]
        if table == "findings" and row != dict(doc_id=doc_id, code="unsupported_family", detail="No accepted financial rows were created."):
            raise IntegrityError("curated instrument unsupported finding differs")
        if table == "validation_runs" and (row["state"] != "unsupported" or row["detail"] != "unsupported_family"
                                           or revision is not None and row["revision"] != revision):
            raise IntegrityError("curated instrument validation acquired financial admission")


def verify_operations(store, state, operations, *, revision=None):
    """Check only documents affected by this authenticated audit prefix."""
    def lookup(table, key):
        return state[table].get(key)
    try:
        _verify(store, lookup, operations, revision)
    except (AuthorityError, ValueError, TypeError, KeyError, IndexError, UnicodeError) as error:
        raise IntegrityError("curated instrument audit boundary is invalid") from error


def _sql_lookup(store):
    memo = {}
    def lookup(table, key):
        identity = table, key
        if identity not in memo:
            memo[identity] = store._row(table, " AND ".join(name+"=?" for name in KEYS[table]), key)
        return memo[identity]
    return lookup


def _possible_scope(store, operations):
    if any(op["table"] == "interpretations" and op["row"]["facts_type"] == INTERPRETATION_KIND
           or op["table"] == "receipts" and _instrument_receipt(op["row"])
           or op["table"] == "source_admissions" and json.loads(op["row"]["body"])["document"]["doc_type"] in FAMILIES
           for op in operations):
        return True
    documents = {op["row"]["doc_id"] for op in operations if op["row"].get("doc_id") is not None}
    if store._curated_owner is not None:
        from .curated import _owned
        owned = _owned(store._curated_owner)
        return any(doc in owned.rows and json.loads(owned.rows[doc][0])["doc_type"] in FAMILIES for doc in documents)
    lookup = _sql_lookup(store)
    return bool(_affected(store, lookup, operations))


def verify_new_record(store, previous_revision, previous_head):
    """Recheck the prepared, sealed new record against current SQL before COMMIT."""
    try:
        terminal = store._read("SELECT revision,head,mac FROM control WHERE singleton=1")
        if len(terminal) != 1:
            raise ValueError("missing terminal")
        revision, head, mac = terminal[0]
        if not store._operations:
            if (revision, head) != (previous_revision, previous_head) or not hmac.compare_digest(mac, store._mac(revision, head)):
                raise ValueError("empty writer boundary differs")
            return
        if revision != previous_revision+1 or not hmac.compare_digest(mac, store._mac(revision, head)):
            raise ValueError("new terminal differs")
        records = store._read("SELECT sequence,previous_hash,envelope,record_hash FROM audit WHERE sequence=?", (revision,))
        commits = store._read("SELECT revision,head,mac FROM commits WHERE revision=?", (revision,))
        if len(records) != 1 or commits != [(revision, head, mac)]:
            raise ValueError("new commitment differs")
        sequence, previous, envelope, digest = records[0]
        if (sequence, previous, digest) != (revision, previous_head, head) or hashlib.sha256(canonical([sequence, previous, envelope]).encode()).hexdigest() != digest:
            raise ValueError("new record differs")
        payload = json.loads(open_sealed(store._audit_key, json.loads(envelope),
                             aad=canonical([revision, previous_head]).encode()))
        if (type(payload) is not dict or set(payload) != {"version", "operations"}
                or type(payload["version"]) is not int or payload["version"] != 1
                or type(payload["operations"]) is not list or not payload["operations"]):
            raise ValueError("new payload differs")
        operations = payload["operations"]
        for operation in operations:
            if type(operation) is not dict or set(operation) != {"table", "row"} or not valid_row(operation["table"], operation["row"]):
                raise ValueError("new operation differs")
        if operations != store._operations:
            raise ValueError("prepared operations differ from writer")
        if not _possible_scope(store, operations):
            return
        lookup = _sql_lookup(store)
        final = {}
        for operation in operations:
            table, row = operation["table"], operation["row"]
            final[table, tuple(row[name] for name in KEYS[table])] = row
        for (table, key), row in final.items():
            if lookup(table, key) != row:
                raise ValueError("new row differs from SQL")
        _verify(store, lookup, operations, revision)
    except (AuthorityError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError,
            OverflowError, CryptoError, OSError) as error:
        raise IntegrityError("new curated instrument boundary is invalid") from error
