"""Synthetic CD capture across encrypted receipts and application publication."""
import copy
import hashlib
import io
import json
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tarfile
import time

import pytest

from vivacore.verify.normalize import RULES_VERSION
from viva.ingest.instrument_parser import parse_instrument_json
from viva.ingest.instrument_read import InstrumentReadFacts
from viva.ingest.pipeline_models import ModelPhase, ReadResult
from viva.normalization_context import ExtractionNormalizationContext
from viva.sql_authority import SQLAuthority, AuthorityError, IntegrityError
from viva.sql_authority import cd_capture_contract, cd_receipt_verify
from viva.sql_authority.application import ApplicationSQLAuthority
from viva.sql_authority.application_io import RecoveryRequired


pytestmark = pytest.mark.production_kdf
OLD_PRODUCER = "13a41040029383bba43c6ad323300f7b7f4e6706"
SOURCE = b"synthetic ordinary deposit source"
DOC = hashlib.sha256(SOURCE).hexdigest()
FINANCIAL_TABLES = (
    "accounts", "account_keys", "postings", "transactions", "periods",
    "balance_observations", "source_occurrences", "transfer_assertions",
    "transfer_inventory", "transfer_bindings", "transfer_pairs", "transfer_members",
    "transfer_suggestions", "transfer_endpoints", "transfer_edges", "transfer_tokens",
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _printed(value):
    return {"raw": value, "page": 1}


def _raw():
    return {"identity": {"institution": _printed("Synthetic issuer"),
                         "account_reference": _printed("Synthetic deposit"),
                         "holder": _printed("Synthetic holder")},
            "subtype": "periodic", "start": _printed("2024-01-01"),
            "end": _printed("2024-01-31"), "opening": _printed("1000"),
            "closing": _printed("1010"), "movements": [
                {"kind": "interest_credit", "amount": _printed("10"),
                 "dated": _printed("2024-01-31"), "reference": _printed("Synthetic interest")}],
            "uncredited_interest": _printed("7")}


def _context(locale="en-US", currency="USD"):
    return ExtractionNormalizationContext(1, RULES_VERSION, locale, currency)


def _reading(doc=DOC, *, linked=False):
    raw = _canonical(_raw())
    payload = parse_instrument_json(raw, "term_deposit_statement", doc,
                                    locale="en-US", currency="USD")
    facts = InstrumentReadFacts(doc, "term_deposit_statement", 0.5, payload, "USD")
    result = ReadResult("term_deposit_statement", 0.5, facts=facts)
    if linked:
        result.raw_text, result.normalization_context = raw, _context()
    return result


def _engine(owner):
    return owner._engine if isinstance(owner, ApplicationSQLAuthority) else owner


def _ingest(owner, result=None, source=SOURCE):
    result = _reading(hashlib.sha256(source).hexdigest()) if result is None else result
    return owner.ingest(source, lambda _source, _doc: result,
                        contract="synthetic-cd-capture-v1")


def _receipt(owner, doc=DOC):
    return _engine(owner)._row("receipts", "doc_id=?", (doc,))


def _money(owner):
    db = _engine(owner)._db
    return {table: sorted(tuple(row) for row in db.execute("SELECT * FROM " + table))
            for table in FINANCIAL_TABLES}


def _disposition(owner, reason, *, binding="matched", linkage="not_evaluated"):
    value = owner.receipt(DOC)["reading"]["authority_context"]["cd_capture"]
    assert value == {"version": 1, "profile": "ordinary_cd_capture_v1",
                     "claim_binding": binding, "raw_linkage": linkage, "reason": reason}


@pytest.fixture
def owner(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "application", secrets.token_urlsafe(32),
                             verification="complete", application=True) as opened:
        yield opened


def _refuse_receipt(owner, mutate):
    row = copy.deepcopy(_receipt(owner))
    mutate(row)
    with pytest.raises(IntegrityError):
        cd_receipt_verify.decode_capture(row)


def _members(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def test_minimal_round_trip(owner):
    expected = _reading()
    outcome = _ingest(owner, expected)
    assert outcome.status == "unsupported"
    receipt = owner.receipt(DOC)
    assert receipt["facts_type"] == "cd_retained_v1"
    assert receipt["facts"] == InstrumentReadFacts.to_dict(expected.facts)
    assert receipt["raw_reading"]["facts"] == receipt["facts"]
    assert len(receipt["raw_reading"]) == 17
    _disposition(owner, "no_raw_response")
    assert owner.verify()["verified"]


def test_populated_round_trip(owner):
    result = _reading(linked=True)
    result.model, result.prompt_version = "synthetic-model", "synthetic-prompt"
    result.cost_usd, result.input_tokens, result.output_tokens = 0.125, 17, 29
    result.resolved_model, result.usage_reported = "synthetic-resolved", True
    result.source_locale, result.acquisition = "synthetic-locale", {"synthetic": [None, True]}
    _ingest(owner, result)
    body = owner.receipt(DOC)["raw_reading"]
    for key in ("model", "prompt_version", "cost_usd", "input_tokens", "output_tokens",
                "resolved_model", "usage_reported", "source_locale", "acquisition"):
        assert body[key] == getattr(result, key)
    _disposition(owner, "matched", linkage="matched")


def test_reader_error_retained(owner):
    result = _reading(linked=True)
    result.error = "synthetic reader failure"
    _ingest(owner, result)
    assert owner.receipt(DOC)["raw_reading"]["error"] == result.error
    _disposition(owner, "reader_error")


def test_wrong_classification_unbound(owner):
    result = _reading(linked=True)
    result.doc_type = "checking_statement"
    _ingest(owner, result)
    assert owner.receipt(DOC)["raw_reading"]["doc_type"] == "checking_statement"
    _disposition(owner, "classification_mismatch", binding="different")


def test_wrong_claimed_document_unbound(owner):
    result = _reading("e" * 64, linked=True)
    _ingest(owner, result)
    assert owner.receipt(DOC)["facts"]["doc_id"] == "e" * 64
    _disposition(owner, "document_mismatch", binding="different")


def test_absent_raw_unavailable(owner):
    _ingest(owner)
    _disposition(owner, "no_raw_response")


def test_invalid_raw_retained(owner):
    result = _reading(linked=True)
    result.raw_text = "synthetic invalid parser response"
    _ingest(owner, result)
    assert owner.receipt(DOC)["raw_reading"]["raw_text"] == result.raw_text
    _disposition(owner, "parser_refused", linkage="invalid")


def test_different_raw_unbound(owner):
    result = _reading(linked=True)
    raw = _raw()
    raw["closing"] = _printed("1011")
    result.raw_text = _canonical(raw)
    _ingest(owner, result)
    _disposition(owner, "facts_differ", linkage="different")


def test_matching_recorded_inputs(owner):
    result = _reading(linked=True)
    result.source_locale = "synthetic non-parser locale"
    _ingest(owner, result)
    _disposition(owner, "matched", linkage="matched")


def test_null_locale_preserved(tmp_path, monkeypatch):
    from viva.ingest import instrument_read
    parser = instrument_read.parse_instrument_json
    observed = []
    def observe(text, kind, doc, locale="en-US", currency="USD", **kwargs):
        observed.append((locale, currency))
        return parser(text, kind, doc, locale, currency, **kwargs)
    monkeypatch.setattr(instrument_read, "parse_instrument_json", observe)
    for index, locale in enumerate((None, "en-US")):
        with SQLAuthority.create(tmp_path.resolve() / str(index), secrets.token_urlsafe(32),
                                 verification="complete", application=True) as opened:
            result = _reading(linked=True)
            result.normalization_context = _context(locale, "USD")
            result.source_locale = "synthetic misleading locale"
            observed.clear()
            _ingest(opened, result)
            assert observed and all(value == (locale, "USD") for value in observed)
            assert opened.receipt(DOC)["raw_reading"]["normalization_context"]["parser_locale"] == locale
            _disposition(opened, "matched", linkage="matched")


def test_missing_context_or_currency_unavailable(tmp_path):
    cases = ((None, "no_parser_context", "not_evaluated"),
             (_context(None, None), "no_parser_context", "not_evaluated"),
             (_context("en-US", ""), "no_parser_context", "not_evaluated"),
             (_context(None, "   "), "no_parser_context", "not_evaluated"),
             (_context("en-US", "EUR"), "context_currency_mismatch", "different"))
    for index, (context, reason, linkage) in enumerate(cases):
        with SQLAuthority.create(tmp_path.resolve() / str(index), secrets.token_urlsafe(32),
                                 verification="complete", application=True) as opened:
            result = _reading(linked=True)
            result.normalization_context = context
            _ingest(opened, result)
            _disposition(opened, reason, linkage=linkage)


def test_foreign_context_refused(owner, tmp_path):
    _ingest(owner)
    row = copy.deepcopy(_receipt(owner))
    tags = json.loads(row["capture_types"])
    with SQLAuthority.create(tmp_path.resolve() / "same-contract-other-root", secrets.token_urlsafe(32),
                             verification="complete", application=True) as other:
        _ingest(other)
        other_tags = json.loads(_receipt(other)["capture_types"])
        assert other_tags["read_context_id"] == tags["read_context_id"]
        assert cd_receipt_verify.interpretation(_engine(owner), _receipt(other))["facts_type"] == "cd_retained_v1"
    tags["read_context_id"] = "f" * 64
    row["capture_types"] = _canonical(tags)
    with pytest.raises(IntegrityError):
        cd_receipt_verify.interpretation(_engine(owner), row)


def test_forged_capture_tag_refused(owner):
    _ingest(owner)
    def mutate(row):
        tags = json.loads(row["capture_types"])
        tags["mode"] = "ordinary_cd_v1"
        row["capture_types"] = _canonical(tags)
    _refuse_receipt(owner, mutate)


def test_body_facts_divergence_refused(owner, tmp_path, monkeypatch, record_property):
    from viva.sql_authority import cd_receipts
    _ingest(owner)
    def mutate(row):
        facts = json.loads(row["facts"])
        facts["doc_type_confidence"] = 0.75
        row["facts"] = _canonical(facts)
    _refuse_receipt(owner, mutate)
    original_decode = cd_receipt_verify.decode_capture
    original_encode = cd_receipts.encode_ordinary_cd_receipt
    variants = ("explicit_null_acquisition", "noncanonical_decimal")
    reached = []
    def coherent(row, variant):
        row = copy.deepcopy(row)
        facts = json.loads(row["facts"])
        if variant == "explicit_null_acquisition":
            assert "acquisition" not in facts
            facts["acquisition"] = None
        else:
            assert variant == "noncanonical_decimal"
            facts["instrument_facts"]["opening"]["value"] = "01"
        typed = InstrumentReadFacts.from_dict(facts)
        assert InstrumentReadFacts.to_dict(typed) != facts
        body = json.loads(row["body"])
        body["facts"] = facts
        row.update(body=_canonical(body), facts=_canonical(facts))
        assert json.loads(row["body"])["facts"] == json.loads(row["facts"])
        return row
    for variant in variants:
        mutated = coherent(_receipt(owner), variant)
        with pytest.raises(IntegrityError):
            original_decode(mutated)
        observed = []
        def encode(result, *, read_context_id):
            captured = original_encode(result, read_context_id=read_context_id)
            return coherent(captured, variant)
        def decode(receipt):
            facts = json.loads(receipt["facts"])
            if (facts.get("acquisition", "omitted") is None if variant == "explicit_null_acquisition"
                    else facts["instrument_facts"]["opening"]["value"] == "01"):
                observed.append(variant)
            return original_decode(receipt)
        monkeypatch.setattr(cd_receipts, "encode_ordinary_cd_receipt", encode)
        monkeypatch.setattr(cd_receipt_verify, "decode_capture", decode)
        with SQLAuthority.create(tmp_path.resolve() / variant, secrets.token_urlsafe(32),
                                 verification="complete") as opened:
            with pytest.raises(IntegrityError, match="new CD capture boundary is invalid"):
                _ingest(opened)
            assert observed and set(observed) == {variant}
            reached.append(variant)
            assert _receipt(opened) is None
            assert all(not rows for rows in _money(opened).values())
            assert opened.verify()["verified"]
    assert reached == list(variants)
    record_property("emitted_wire_refusals", ",".join(reached))


def test_duplicate_json_refused(owner):
    _ingest(owner)
    _refuse_receipt(owner, lambda row: row.update(body='{"error":null,' + row["body"][1:]))


def test_nonfinite_json_refused(owner):
    _ingest(owner)
    _refuse_receipt(owner, lambda row: row.update(body=row["body"].replace('"cost_usd":0.0', '"cost_usd":NaN')))


def test_utf8_ceiling_enforced(owner):
    from viva.sql_authority.schema import valid_row
    _ingest(owner)
    assert cd_capture_contract.MAX_CAPTURE_BYTES == 8 * 1024 * 1024
    baseline = _receipt(owner)
    body = json.loads(baseline["body"])
    overhead = len(baseline["body"].encode("utf-8"))
    body["raw_text"] = "λ" * ((cd_capture_contract.MAX_CAPTURE_BYTES - overhead) // 2)
    bounded = dict(baseline, body=_canonical(body))
    assert len(bounded["body"].encode("utf-8")) <= cd_capture_contract.MAX_CAPTURE_BYTES
    cd_receipt_verify.decode_capture(bounded)
    body["raw_text"] += "λ"
    oversized = dict(baseline, body=_canonical(body))
    assert len(oversized["body"]) < cd_capture_contract.MAX_CAPTURE_BYTES
    assert len(oversized["body"].encode("utf-8")) > cd_capture_contract.MAX_CAPTURE_BYTES
    with pytest.raises(IntegrityError):
        cd_receipt_verify.decode_capture(oversized)
    for column in ("body", "facts", "capture_types"):
        row = copy.deepcopy(baseline)
        row[column] = '"' + "λ" * ((cd_capture_contract.MAX_CAPTURE_BYTES - 2) // 2) + '"'
        assert len(row[column].encode("utf-8")) == cd_capture_contract.MAX_CAPTURE_BYTES
        assert valid_row("receipts", row)
        row[column] = row[column][:-1] + 'λ"'
        assert len(row[column]) < cd_capture_contract.MAX_CAPTURE_BYTES
        assert len(row[column].encode("utf-8")) > cd_capture_contract.MAX_CAPTURE_BYTES
        assert not valid_row("receipts", row)
        with pytest.raises(IntegrityError):
            cd_receipt_verify.decode_capture(row)


def test_phase_contexts_preserved(owner):
    result = _reading()
    contexts = (_context(None, None), None, _context("en-US", "USD"))
    for index, context in enumerate(contexts):
        phase = ModelPhase("synthetic-" + str(index), "synthetic-model", "synthetic-prompt", "synthetic raw")
        phase.normalization_context = context
        result.phases.append(phase)
    _ingest(owner, result)
    body = owner.receipt(DOC)["raw_reading"]
    assert [row["phase"] for row in body["phases"]] == [p.phase for p in result.phases]
    assert all(len(row) == 17 for row in body["phases"])
    assert [row["normalization_context"] for row in body["phases"]] == [
        {"schema_version": 1, "normalization_rules_version": RULES_VERSION,
         "parser_locale": None, "parser_currency": None}, None,
        {"schema_version": 1, "normalization_rules_version": RULES_VERSION,
         "parser_locale": "en-US", "parser_currency": "USD"}]


def test_phase_tag_mismatch_refused(owner):
    result = _reading()
    result.phases = [ModelPhase("synthetic", "synthetic", "synthetic", "synthetic")]
    _ingest(owner, result)
    def mutate(row):
        tags = json.loads(row["capture_types"])
        tags["phase_context_runtime_types"] = []
        row["capture_types"] = _canonical(tags)
    _refuse_receipt(owner, mutate)


def test_custody_mismatch_refused(owner, monkeypatch):
    _ingest(owner)
    engine = _engine(owner)
    actual = engine._original
    assert actual(DOC) == SOURCE
    monkeypatch.setattr(engine, "_original", lambda doc: actual(doc) + b"synthetic custody discrepancy")
    with pytest.raises(IntegrityError):
        cd_receipt_verify.interpretation(engine, _receipt(owner))


def test_zero_money_empty_root(owner):
    before = _money(owner)
    assert all(not rows for rows in before.values())
    _ingest(owner, _reading(linked=True))
    assert _money(owner) == before
    assert not owner.postings(DOC)
    assert owner.item(DOC)["state"] == "unsupported"
    assert owner.verify()["verified"]


def test_existing_transfer_unchanged(owner):
    from test_sql_authority_transfers import admit
    first = admit(owner, "synthetic-cd-transfer-out", number="100000001111", institution="Synthetic Alpha",
                  description="synthetic to 2222")
    admit(owner, "synthetic-cd-transfer-in", number="200000002222", institution="Synthetic Beta",
          amount="10.00", description="synthetic incoming")
    links = owner.transfer_links()
    assert len(links) == 1
    postings, before = owner.postings(first.doc_id), _money(owner)
    _ingest(owner)
    assert _money(owner) == before
    assert owner.transfer_links() == links
    assert owner.postings(first.doc_id) == postings


def _assert_noop_extension(owner, prior, earlier_history, before):
    assert owner._history.keys is not None
    terminal = owner.terminal
    scanned, records, payloads = owner._history.scan(expected=terminal, prefix=prior)
    assert scanned == terminal and len(records) == prior["sequence"] + 1
    record, payload = records[-1], payloads[-1]
    assert record["kind"] == "noop"
    assert record["sequence"] == prior["sequence"] + 1
    assert record["previous_hash"] == prior["head"]
    assert record["root_id"] == prior["root_id"]
    assert (record["sql_revision"], record["sql_head"]) == (before["head"]["revision"], before["head"]["head"])
    assert record["operation_id"] not in {entry["operation_id"] for entry in records[:-1]}
    issued = payload["issued"]
    assert issued == {"version": 1, "root_id": prior["root_id"],
                      "operation_id": record["operation_id"], "kind": "transaction",
                      "prior_terminal": prior, "prior_sql": before["head"], "capture": None}
    assert payload["body"] == {"intent_sha256": hashlib.sha256(_canonical(issued).encode()).hexdigest()}
    assert terminal == {"root_id": prior["root_id"], "sequence": prior["sequence"] + 1,
                        "head": record["record_hash"], "sql_revision": before["head"]["revision"],
                        "sql_head": before["head"]["head"]}
    history = _members(owner.root / "history")
    assert set(history) == set(earlier_history) | {f"{terminal['sequence']:020d}.json"}
    assert all(history[name] == digest for name, digest in earlier_history.items())
    assert owner.head == before["head"]
    assert owner.receipt(DOC) == before["receipt"]
    assert _receipt(owner) == before["raw_receipt"]
    assert owner.item(DOC) == before["item"]
    assert owner.original(DOC) == before["original"] == SOURCE
    assert _money(owner) == before["money"]
    assert not list((owner.root / "pending").iterdir())
    assert not (owner.root / "terminal.next").exists()
    assert not (owner.root / "sql" / "authority.db-journal").exists()
    assert owner.verify(expected_head=before["head"], expected_terminal=terminal)["verified"]


def test_duplicate_ingest_idempotent(owner):
    _ingest(owner)
    before = {"head": owner.head, "receipt": owner.receipt(DOC), "raw_receipt": _receipt(owner),
              "item": owner.item(DOC), "original": owner.original(DOC), "money": _money(owner)}
    initial = owner.terminal
    def forbidden(*_args):
        raise AssertionError("duplicate source invoked reader")
    for _ in range(2):
        prior, history = owner.terminal, _members(owner.root / "history")
        outcome = owner.ingest(SOURCE, forbidden, contract="synthetic-cd-capture-v1")
        assert outcome.doc_id == DOC and outcome.status == "unsupported"
        _assert_noop_extension(owner, prior, history, before)
    assert owner.terminal["sequence"] == initial["sequence"] + 2


def test_unsupported_resume_idempotent(owner):
    _ingest(owner)
    before = {"head": owner.head, "receipt": owner.receipt(DOC), "raw_receipt": _receipt(owner),
              "item": owner.item(DOC), "original": owner.original(DOC), "money": _money(owner)}
    initial = owner.terminal
    for _ in range(2):
        prior, history = owner.terminal, _members(owner.root / "history")
        outcome = owner.resume(DOC)
        assert outcome.doc_id == DOC and outcome.status == "unsupported"
        _assert_noop_extension(owner, prior, history, before)
    assert owner.terminal["sequence"] == initial["sequence"] + 2


def test_complete_reopen(tmp_path):
    root, secret = tmp_path.resolve() / "application", secrets.token_urlsafe(32)
    with SQLAuthority.create(root, secret, verification="complete", application=True) as opened:
        _ingest(opened, _reading(linked=True))
        receipt, head, terminal = opened.receipt(DOC), opened.head, opened.terminal
    with SQLAuthority.open(root, secret, verification="complete", application=True) as opened:
        assert opened.receipt(DOC) == receipt
        assert opened.verify(expected_head=head, expected_terminal=terminal)["verified"]


def test_receipt_only_prefix_valid(owner, monkeypatch):
    engine = _engine(owner)
    original = engine.resume
    def interrupt(doc):
        assert doc == DOC and _receipt(owner)["facts_type"] == "cd_capture_v1"
        raise RuntimeError("synthetic stop before interpretation")
    monkeypatch.setattr(engine, "resume", interrupt)
    with pytest.raises(RuntimeError, match="before interpretation"):
        _ingest(owner)
    assert engine._row("interpretations", "doc_id=?", (DOC,)) is None
    assert owner.receipt(DOC)["facts_type"] == "cd_capture_v1"
    assert "authority_context" not in owner.receipt(DOC)["reading"]
    assert owner.verify()["verified"]
    monkeypatch.setattr(engine, "resume", original)
    assert owner.resume(DOC).status == "unsupported"
    assert owner.verify()["verified"]


def test_forged_linkage_disposition_refused(owner, monkeypatch):
    from viva.sql_authority import reading
    original = reading._retained_cd_interpretation
    forged = []
    def propose(store, receipt):
        row = original(store, receipt)
        context = json.loads(row["context"])
        assert context["cd_capture"]["reason"] == "no_raw_response"
        context["cd_capture"]["reason"] = "matched"
        context["cd_capture"]["raw_linkage"] = "matched"
        row["context"] = _canonical(context)
        forged.append(True)
        return row
    monkeypatch.setattr(reading, "_retained_cd_interpretation", propose)
    with pytest.raises(IntegrityError):
        _ingest(owner)
    assert forged == [True]
    assert _engine(owner)._row("interpretations", "doc_id=?", (DOC,)) is None


def _is_receipt_writer(store):
    return any(op["table"] == "receipts" and op["row"]["facts_type"] == "cd_capture_v1"
               for op in (store._operations or ()))


def _reseal_writer(store, previous):
    from viva.crypto import seal, open_sealed
    operations = copy.deepcopy(store._operations)
    envelope = _canonical(seal(store._audit_key,
                               _canonical({"version": 1, "operations": operations}).encode(),
                               aad=_canonical([store._revision, previous]).encode()))
    assert json.loads(open_sealed(store._audit_key, json.loads(envelope),
                                 aad=_canonical([store._revision, previous]).encode()))["operations"] == operations
    digest = hashlib.sha256(_canonical([store._revision, previous, envelope]).encode()).hexdigest()
    mac = store._mac(store._revision, digest)
    store._db.execute("UPDATE audit SET envelope=?,record_hash=? WHERE sequence=?",
                      (envelope, digest, store._revision))
    store._db.execute("UPDATE commits SET head=?,mac=? WHERE revision=?", (digest, mac, store._revision))
    store._db.execute("UPDATE control SET head=?,mac=? WHERE singleton=1", (digest, mac))
    assert store._db.execute("SELECT revision,head,mac FROM control").fetchone() == (store._revision, digest, mac)


def _assert_existing_cd_writer_refused(tmp_path, mode, variant, monkeypatch, original, original_scope):
    from viva.sql_authority.schema import TABLES, valid_row
    with monkeypatch.context() as patch:
        patch.setattr(cd_receipt_verify, "verify_new_record", original)
        patch.setattr(cd_receipt_verify, "_verify_operations", original_scope)
        with SQLAuthority.create(tmp_path.resolve() / (mode + "-" + variant), secrets.token_urlsafe(32),
                                 verification=mode) as opened:
            assert _ingest(opened).status == "unsupported"
            assert _receipt(opened)["facts_type"] == "cd_capture_v1"
            assert opened._row("interpretations", "doc_id=?", (DOC,))["facts_type"] == "cd_retained_v1"
            assert opened.verify()["verified"]
            tables = tuple(TABLES) + ("control", "audit", "commits", "format")
            def state():
                return {table: sorted(_canonical(list(row)) for row in opened._db.execute('SELECT * FROM "' + table + '"'))
                        for table in tables}
            before = dict(sql=state(), head=opened.head, receipt=opened.receipt(DOC),
                          raw_receipt=_receipt(opened), item=opened.item(DOC),
                          original=opened.original(DOC), money=_money(opened),
                          originals=_members(opened.root / "originals"))
            observed = {"armed": False, "guard": 0, "scope": 0, "refused": False}
            commits = []
            reason = ("CD item acquired financial admission" if variant == "existing_cd_item_mutation"
                      else "CD writer contains foreign or financial operations")
            def scope(store, lookup, operations, **kwargs):
                if observed["armed"]:
                    observed["scope"] += 1
                    assert store._db.in_transaction
                    try:
                        result = original_scope(store, lookup, operations, **kwargs)
                    except IntegrityError as error:
                        assert str(error) == reason
                        observed["refused"] = True
                        raise
                    raise AssertionError("existing CD writer escaped its original scope verifier")
                return original_scope(store, lookup, operations, **kwargs)
            def guard(store, revision, head):
                if observed["armed"]:
                    observed["guard"] += 1
                    assert store._db.in_transaction
                    assert all(operation["table"] not in {"receipts", "interpretations"}
                               for operation in store._operations)
                    assert any(operation["table"] == "items" and operation["row"]["doc_id"] == DOC
                               for operation in store._operations)
                return original(store, revision, head)
            patch.setattr(cd_receipt_verify, "_verify_operations", scope)
            patch.setattr(cd_receipt_verify, "verify_new_record", guard)
            opened._db.set_trace_callback(lambda statement: commits.append(statement)
                                          if statement.strip().upper() == "COMMIT" else None)
            acknowledged = []
            try:
                with pytest.raises(IntegrityError, match="new CD capture boundary is invalid"):
                    with opened._transaction():
                        item = dict(before["item"], revision=opened._revision)
                        if variant == "existing_cd_item_mutation":
                            item["reason"] = "synthetic changed unsupported reason"
                        else:
                            assert variant == "existing_cd_financial_operation"
                        assert valid_row("items", item)
                        opened._put("items", item)
                        if variant == "existing_cd_financial_operation":
                            account = dict(account_id="d" * 64, identity="c" * 64, kind="depository", currency="USD",
                                           number="", normalized_number="", institution="Synthetic issuer", label="Synthetic account",
                                           names="[]", earliest_amount="0", earliest_date="2024-01-01",
                                           current_amount="0", current_date="2024-01-01")
                            assert valid_row("accounts", account)
                            opened._put("accounts", account)
                        observed["armed"] = True
                    acknowledged.append(True)
            finally:
                observed["armed"] = False
                opened._db.set_trace_callback(None)
            assert observed == {"armed": False, "guard": 1, "scope": 1, "refused": True}
            assert acknowledged == [] and commits == []
            assert not opened._db.in_transaction
            assert state() == before["sql"] and opened.head == before["head"]
            assert opened.receipt(DOC) == before["receipt"] and _receipt(opened) == before["raw_receipt"]
            assert opened.item(DOC) == before["item"] and _money(opened) == before["money"]
            assert opened.original(DOC) == before["original"] == SOURCE
            assert _members(opened.root / "originals") == before["originals"]
            assert opened.verify(expected_head=before["head"])["verified"]


def test_sealed_record_mutation_before_commit_refused(tmp_path, monkeypatch, record_property):
    from viva.sql_authority.cd_receipts import encode_ordinary_cd_receipt
    from viva.sql_authority.schema import valid_row
    original = cd_receipt_verify.verify_new_record
    original_scope = cd_receipt_verify._verify_operations
    variants = ("hash_mutation", "ordered_buffer_divergence", "actual_row_tamper",
                "coherent_financial_operation", "coherent_second_cd_document",
                "existing_cd_item_mutation", "existing_cd_financial_operation")
    reached, scopes = [], []
    for mode in ("indexed", "complete"):
        for variant in variants:
            if variant in {"existing_cd_item_mutation", "existing_cd_financial_operation"}:
                _assert_existing_cd_writer_refused(tmp_path, mode, variant, monkeypatch, original, original_scope)
                reached.append((mode, variant))
                scopes.append((mode, variant))
                continue
            active = {"mutated": False}
            with SQLAuthority.create(tmp_path.resolve() / (mode + "-" + variant), secrets.token_urlsafe(32), verification=mode) as opened:
                second_source = b"synthetic second independently captured deposit"
                second_doc = hashlib.sha256(second_source).hexdigest()
                if variant == "coherent_second_cd_document":
                    def interrupted_reader(_source, _doc):
                        raise RuntimeError("synthetic second admission without receipt")
                    with pytest.raises(RuntimeError, match="second admission"):
                        opened.ingest(second_source, interrupted_reader, contract="synthetic-cd-capture-v1")
                    assert opened.item(second_doc)["state"] == "read_uncertain"
                    assert _receipt(opened, second_doc) is None
                def scope(store, lookup, operations, **kwargs):
                    if not active["mutated"]:
                        return original_scope(store, lookup, operations, **kwargs)
                    scopes.append((mode, variant))
                    reason = ("CD writer contains foreign or financial operations" if variant == "coherent_financial_operation"
                              else "one CD writer must retain one document")
                    with pytest.raises(IntegrityError, match=reason):
                        original_scope(store, lookup, operations, **kwargs)
                    raise IntegrityError(reason)
                def guard(store, revision, head):
                    if not _is_receipt_writer(store):
                        return original(store, revision, head)
                    reached.append((mode, variant))
                    active["mutated"] = True
                    if variant == "hash_mutation":
                        store._db.execute("UPDATE audit SET record_hash=? WHERE sequence=?", ("f" * 64, store._revision))
                    elif variant == "ordered_buffer_divergence":
                        before = copy.deepcopy(store._operations)
                        assert len(before) == 2 and before[0] != before[1]
                        store._operations.reverse()
                        assert store._operations != before
                    elif variant == "actual_row_tamper":
                        row = _receipt(store)
                        body = json.loads(row["body"])
                        body["raw_text"] = "synthetic changed SQL-only receipt"
                        row["body"] = _canonical(body)
                        assert valid_row("receipts", row)
                        store._db.execute("UPDATE receipts SET body=? WHERE doc_id=?", (row["body"], DOC))
                    elif variant == "coherent_financial_operation":
                        row = dict(account_id="d" * 64, identity="c" * 64, kind="depository", currency="USD",
                                   number="", normalized_number="", institution="Synthetic issuer", label="Synthetic account",
                                   names="[]", earliest_amount="0", earliest_date="2024-01-01",
                                   current_amount="0", current_date="2024-01-01")
                        assert valid_row("accounts", row)
                        store._put("accounts", row)
                        _reseal_writer(store, head)
                    else:
                        assert variant == "coherent_second_cd_document"
                        main = _receipt(store)
                        context_id = json.loads(main["capture_types"])["read_context_id"]
                        captured = encode_ordinary_cd_receipt(_reading(second_doc), read_context_id=context_id)
                        row = dict(doc_id=second_doc, contract="synthetic-cd-capture-v1", facts_type="cd_capture_v1", **captured)
                        assert valid_row("receipts", row)
                        store._put("receipts", row)
                        store._item(second_doc, "staged", "retained extraction awaiting validation")
                        _reseal_writer(store, head)
                    try:
                        return original(store, revision, head)
                    finally:
                        active["mutated"] = False
                monkeypatch.setattr(cd_receipt_verify, "_verify_operations", scope)
                monkeypatch.setattr(cd_receipt_verify, "verify_new_record", guard)
                with pytest.raises(IntegrityError, match="new CD capture boundary is invalid"):
                    _ingest(opened)
                assert _receipt(opened) is None and _receipt(opened, second_doc) is None
                assert all(not rows for rows in _money(opened).values())
                assert opened.verify()["verified"]
    assert reached == [(mode, variant) for mode in ("indexed", "complete") for variant in variants]
    assert scopes == [(mode, variant) for mode in ("indexed", "complete")
                      for variant in ("coherent_financial_operation", "coherent_second_cd_document",
                                      "existing_cd_item_mutation", "existing_cd_financial_operation")]
    record_property("writer_guard_matrix", _canonical(reached))


def test_precommit_failure_cannot_ack_receipt(tmp_path, monkeypatch, record_property):
    original = cd_receipt_verify.verify_new_record
    reached = []
    for mode in ("indexed", "complete"):
        with SQLAuthority.create(tmp_path.resolve() / mode, secrets.token_urlsafe(32), verification=mode) as opened:
            def guard(store, revision, head):
                result = original(store, revision, head)
                if _is_receipt_writer(store):
                    reached.append(mode)
                    raise IntegrityError("synthetic independently verified precommit refusal")
                return result
            monkeypatch.setattr(cd_receipt_verify, "verify_new_record", guard)
            with pytest.raises(IntegrityError, match="precommit refusal"):
                _ingest(opened)
            assert _receipt(opened) is None
            assert opened.item(DOC)["state"] == "read_uncertain"
            assert all(not rows for rows in _money(opened).values())
            assert opened.verify()["verified"]
    assert reached == ["indexed", "complete"]
    record_property("writer_modes", ",".join(reached))


def test_genesis_profile_tamper_refused(owner, monkeypatch):
    from viva.sql_authority import application_schema
    original = application_schema.contract()
    contract = json.loads(original)
    assert set(contract) == {"version", "sql_schema", "receipt_profiles"}
    assert application_schema.descriptor(_engine(owner)._db) == application_schema.expected()
    contract["receipt_profiles"] = {"synthetic_altered_profile": 1}
    monkeypatch.setattr(application_schema, "contract", lambda: _canonical(contract))
    with pytest.raises(IntegrityError):
        owner.verify()


_OLD_CREATE = """
from pathlib import Path
from viva.sql_authority import SQLAuthority
from viva.sql_authority.schema import FORMAT, SCHEMA_VERSION
import viva.sql_authority.store as store_module
assert Path(store_module.__file__).resolve().is_relative_to(Path(request['producer']).resolve())
assert (FORMAT, SCHEMA_VERSION) == ('viva-sql-authority-prototype-v5', 5)
with SQLAuthority.create(Path(request['root']), request['passphrase'], verification='complete') as owner:
    assert owner.verify()['verified']
with SQLAuthority.create(Path(request['application_root']), request['passphrase'], verification='complete', application=True) as owner:
    assert owner.verify()['verified']
from viva.sql_authority.application_history import ENGINE_FORMAT
assert ENGINE_FORMAT == 'viva-sql-application-engine-v3'
print(json.dumps({'created': True, 'format': FORMAT, 'schema_version': SCHEMA_VERSION}), flush=True)
"""


def _process(program, payload, cwd, paths=None, timeout=60):
    request = dict(payload, import_paths=paths or [str(Path(p).resolve()) for p in sys.path])
    prefix = "import json,sys\nrequest=json.loads(sys.stdin.read())\nsys.path[:]=request['import_paths']\n"
    return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", prefix + program],
                          input=json.dumps(request), text=True, capture_output=True,
                          cwd=cwd, env={}, timeout=timeout, check=False)


def test_genuine_v5_refused_without_mutation(tmp_path, monkeypatch):
    from viva.sql_authority import store
    repository = Path(__file__).resolve().parents[2]
    archive = subprocess.run(["git", "archive", "--format=tar", OLD_PRODUCER], cwd=repository,
                             capture_output=True, timeout=30, check=True).stdout
    assert archive
    old = tmp_path.resolve() / "old-producer"
    old.mkdir(mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in bundle.getmembers():
            assert not Path(member.name).is_absolute() and ".." not in Path(member.name).parts
            assert member.isfile() or member.isdir()
        bundle.extractall(old, filter="data")
    secret, root = secrets.token_urlsafe(32), tmp_path.resolve() / "v5"
    application_root = tmp_path.resolve() / "inner-v3"
    paths = [str(old / "product"), str(old / "core"), str(old / "merchant")]
    paths.extend(str(Path(p).resolve()) for p in sys.path if Path(p).resolve() not in
                 {repository / "product", repository / "core", repository / "merchant"})
    completed = _process(_OLD_CREATE, {"root": str(root), "passphrase": secret,
                                     "producer": str(old), "application_root": str(application_root)}, tmp_path, paths)
    assert completed.returncode == 0, "pinned old producer did not complete"
    assert json.loads(completed.stdout) == {"created": True, "format": "viva-sql-authority-prototype-v5", "schema_version": 5}
    before, application_before, connected = _members(root), _members(application_root), []
    def forbidden(*args, **kwargs):
        connected.append(True)
        raise AssertionError("old format reached native connection")
    monkeypatch.setattr(store, "_connect", forbidden)
    from viva.sql_authority import application
    monkeypatch.setattr(application, "_connect", forbidden)
    with pytest.raises(AuthorityError):
        SQLAuthority.open(root, secret, verification="complete")
    with pytest.raises(AuthorityError):
        SQLAuthority.open(application_root, secret, verification="complete", application=True)
    assert connected == [] and _members(root) == before
    assert _members(application_root) == application_before


def test_backup_restore(tmp_path):
    root, backup, restored = (tmp_path.resolve() / name for name in ("application", "backup", "restored"))
    secret = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, secret, verification="complete", application=True) as opened:
        _ingest(opened, _reading(linked=True))
        receipt, head, terminal = opened.receipt(DOC), opened.head, opened.terminal
        before = _members(root)
        copied = opened.backup(backup, passphrase=secret, expected_terminal=terminal)
        assert _members(root) == before
    assert not (backup / "sql" / "authority.db").read_bytes().startswith(b"SQLite format 3")
    assert ApplicationSQLAuthority.restore(backup, restored, secret, expected_terminal=terminal) == copied
    with SQLAuthority.open(restored, secret, verification="complete", application=True) as opened:
        assert opened.receipt(DOC) == receipt and opened.original(DOC) == SOURCE
        assert opened.verify(expected_head=head, expected_terminal=terminal)["verified"]


_CRASH_RECEIPT = """
import os,signal
from pathlib import Path
from viva.sql_authority import SQLAuthority, cd_receipt_verify
from test_sql_cd_capture_integration import _ingest, _is_receipt_writer
owner = SQLAuthority.open(Path(request['root']), request['passphrase'], verification='complete', application=True)
original = cd_receipt_verify.verify_new_record
receipt_verified = False
def stop(boundary):
    assert receipt_verified
    issued = owner._pending[1]
    revision, head = owner._engine._db.execute('SELECT revision,head FROM control WHERE singleton=1').fetchone()
    print(json.dumps({'boundary': boundary, 'receipt_writer': True, 'verified_before_commit': receipt_verified,
                      'prior_sql': issued['prior_sql'], 'prior_terminal': issued['prior_terminal'],
                      'next_sql': {'revision': revision, 'head': head}}), flush=True)
    if request['termination'] == 'sigkill':
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(73)
def guard(store, revision, head):
    global receipt_verified
    result = original(store, revision, head)
    if _is_receipt_writer(store):
        receipt_verified = True
        if request['boundary'] == 'before_commit':
            stop('before_commit')
    return result
cd_receipt_verify.verify_new_record = guard
def fault(point):
    if point == 'after_sql_commit' and _is_receipt_writer(owner._engine) and request['boundary'] == 'after_commit':
        stop('after_commit')
owner._fault = fault
_ingest(owner)
raise AssertionError('required receipt crash boundary was not reached')
"""


def _crash(tmp_path, boundary, termination):
    started = time.monotonic()
    root, secret = tmp_path.resolve() / "application", secrets.token_urlsafe(32)
    with SQLAuthority.create(root, secret, verification="complete", application=True) as opened:
        before_money = _money(opened)
        trusted = opened.terminal
    completed = _process(_CRASH_RECEIPT,
                         {"root": str(root), "passphrase": secret, "boundary": boundary,
                          "termination": termination}, tmp_path,
                         timeout=max(1, 60 - (time.monotonic() - started)))
    assert completed.returncode == (-signal.SIGKILL if termination == "sigkill" else 73)
    event = json.loads(completed.stdout)
    assert set(event) == {"boundary", "receipt_writer", "verified_before_commit", "prior_sql", "prior_terminal", "next_sql"}
    assert event["boundary"] == boundary and event["receipt_writer"] is True
    assert event["verified_before_commit"] is True
    assert event["next_sql"]["revision"] == event["prior_sql"]["revision"] + 1
    assert event["next_sql"]["head"] != event["prior_sql"]["head"]
    pending_members = list((root / "pending").iterdir())
    assert len(pending_members) == 1
    residual = _members(root)
    with pytest.raises(RecoveryRequired):
        SQLAuthority.open(root, secret, verification="complete", application=True)
    assert _members(root) == residual
    with pytest.raises(RecoveryRequired):
        ApplicationSQLAuthority.verify_live_chain(root)
    preserved = {name: digest for name, digest in residual.items()
                 if name in {"application.json", "sql/authority.json"}
                 or name.startswith(("history/", "sql/originals/"))}
    recovered = ApplicationSQLAuthority.recover(root, secret, expected_prefix=trusted)
    assert recovered["status"] == "ready"
    assert recovered["outcome"] == ("aborted" if boundary == "before_commit" else "committed")
    assert not list((root / "pending").iterdir())
    assert not (root / "sql" / "authority.db-journal").exists()
    after = _members(root)
    assert all(after.get(name) == digest for name, digest in preserved.items())
    assert ApplicationSQLAuthority.verify_live_chain(root, expected_terminal=recovered["terminal"])["structural"]
    with SQLAuthority.open(root, secret, verification="complete", application=True) as opened:
        assert opened.verify()["verified"]
        assert _money(opened) == before_money
        assert opened.original(DOC) == SOURCE
        assert opened.head == event["prior_sql" if boundary == "before_commit" else "next_sql"]
        terminal, records, _payloads = opened._history.scan()
        assert terminal == recovered["terminal"]
        assert terminal["sequence"] == event["prior_terminal"]["sequence"] + 1
        assert records[-1]["kind"] == ("interrupted_abort" if boundary == "before_commit" else "sql_commit")
        if boundary == "before_commit":
            assert _receipt(opened) is None
            assert opened.item(DOC)["state"] == "read_uncertain"
        else:
            assert _receipt(opened)["facts_type"] == "cd_capture_v1"
            assert opened.item(DOC)["state"] == "staged"
            assert opened.receipt(DOC)["facts"]["doc_id"] == DOC
            assert opened.resume(DOC).status == "unsupported"
            assert opened.verify()["verified"]
        head, terminal = opened.head, opened.terminal
    with SQLAuthority.open(root, secret, verification="complete", application=True) as opened:
        assert opened.head == head and opened.terminal == terminal
        assert opened.verify()["verified"]
    duplicate = ApplicationSQLAuthority.recover(root, secret, expected_prefix=trusted)
    assert duplicate["outcome"] == "already_ready"
    assert duplicate["terminal"] == terminal
    assert time.monotonic() - started <= 60, "receipt crash/recovery case exceeded its complete-path clock"


def test_receipt_before_commit_exit(tmp_path):
    _crash(tmp_path, "before_commit", "exit")


def test_receipt_after_commit_exit(tmp_path):
    _crash(tmp_path, "after_commit", "exit")


def test_receipt_before_commit_sigkill(tmp_path):
    _crash(tmp_path, "before_commit", "sigkill")


def test_receipt_after_commit_sigkill(tmp_path):
    _crash(tmp_path, "after_commit", "sigkill")
