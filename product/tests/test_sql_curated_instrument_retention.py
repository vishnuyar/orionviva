"""Authenticated curated derivations retain evidence without financial admission."""
import copy
import hashlib
import json
import secrets

import pytest

from viva.crypto import seal
from viva.ingest import instrument_read
from viva.ingest.instrument_read import InstrumentReadFacts, validate_sources
from viva.sample import curation
from viva.sql_authority import AuthorityError, CuratedSource, IntegrityError, SQLAuthority
from viva.sql_authority import curated, curated_instrument, curated_instrument_verify
from viva.sql_authority import curated_instrument_contract as contract
from viva.sql_authority.application import ApplicationSQLAuthority
from viva.sql_authority.schema import TABLES, valid_row
from viva.sql_authority.store import canonical, _encode


pytestmark = pytest.mark.production_kdf
FAMILIES = ("term_deposit_statement", "mortgage_statement", "refinance_settlement", "property_tax_receipt")
CONTEXT_KEYS = {"version", "profile", "doc_type", "parser_locale", "parser_currency",
                "instrument_source_contract", "page_count", "validated_cell_count", "lexical_scope",
                "disposition", "reason", "financial_admission"}


@pytest.fixture(scope="module")
def instrument_source():
    # The genuine pack owner is shared only within this module; no fabricated
    # owner/admission replaces pinned membership or original PDF authentication.
    return CuratedSource.open()


def _member(source, family="term_deposit_statement"):
    return next(document for document in source.documents if document["doc_type"] == family)


def _economic_state(owner):
    evidence = {"documents", "source_admissions", "read_contexts", "receipts", "interpretations",
                "items", "findings", "validation_runs"}
    return {table: owner._db.execute('SELECT * FROM "' + table + '" ORDER BY '
                                     + ','.join(str(i + 1) for i in range(len(columns)))).fetchall()
            for table, columns in TABLES.items() if table not in evidence}


def _prefix(owner, source, document):
    def stop(point):
        if point == "after_raw_receipt":
            raise RuntimeError("controlled receipt-only prefix")
    owner._fault = stop
    try:
        with pytest.raises(RuntimeError, match="controlled receipt-only prefix"):
            owner.ingest_curated(source.original(document["sha256"]), source)
    finally:
        owner._fault = lambda point: None
    receipt = owner._row("receipts", "doc_id=?", (document["sha256"],))
    assert receipt is not None and receipt["facts"] == "null"
    assert owner._row("interpretations", "doc_id=?", (document["sha256"],)) is None
    assert owner.item(document["sha256"])["state"] == "staged"
    return receipt


def test_four_family_retention_preserves_raw_null_and_unrelated_finances(tmp_path, instrument_source):
    from test_sql_payroll import _deposit, _payroll
    from test_sql_investment import _investment
    source = instrument_source
    assert set(contract.FAMILIES) == set(FAMILIES)
    assert contract.INTERPRETATION_KIND == "curated_instrument_retained_v1"
    assert contract.PROFILE == "curated_instrument_derivation_v1"
    root = tmp_path.resolve() / "four-family"
    passphrase = secrets.token_urlsafe(32)
    retained = {}
    with SQLAuthority.create(root, passphrase, verification="complete") as owner:
        bank, payroll, investment = _deposit(owner), _payroll(owner), _investment(owner)
        assert bank.status == payroll.status == investment.status == "accepted"
        before = _economic_state(owner)
        for family in FAMILIES:
            document = _member(source, family)
            doc_id = document["sha256"]
            original = source.original(doc_id)
            issued, admission = curated.issue(source, original, doc_id)
            outcome = owner.ingest_curated(original, source)
            assert (outcome.status, outcome.reason, outcome.account_id) == ("unsupported", "unsupported_family", "")
            stored = owner._row("receipts", "doc_id=?", (doc_id,))
            receipt = owner.receipt(doc_id)
            assert stored["contract"] == curation.CONTRACT and stored["facts"] == "null"
            assert json.loads(stored["body"]) == receipt["raw_reading"] == _encode(issued)
            assert receipt["raw_reading"]["facts"] is None
            assert receipt["reading"]["facts"] is None
            assert receipt["facts_type"] == "curated_instrument_retained_v1"
            context = receipt["reading"]["authority_context"]
            assert set(context) == CONTEXT_KEYS
            assert context["version"] == 1 and context["profile"] == "curated_instrument_derivation_v1"
            assert context["doc_type"] == family
            assert context["parser_locale"] == admission["locale"]
            assert context["parser_currency"] == admission["currency"]
            assert context["page_count"] == document["page_count"]
            envelope = curation.decode_envelope(issued.raw_text, family)
            assert context["validated_cell_count"] == len(envelope["source_cells"])
            assert context["lexical_scope"] == "declared_validated_cells_only"
            assert context["financial_admission"] is False
            assert (context["disposition"], context["reason"]) == ("typed_retained", "")
            facts = InstrumentReadFacts.from_dict(receipt["facts"])
            assert (facts.doc_id, facts.doc_type, facts.currency) == (doc_id, family, admission["currency"])
            assert facts.doc_type_confidence is None and facts.acquisition == admission["acquisition"]
            validate_sources(facts.payload, doc_id, document["page_count"])
            assert owner.original(doc_id) == original
            assert owner.source_occurrences(doc_id) == [] and owner.postings(doc_id) == []
            assert _economic_state(owner) == before
            retained[doc_id] = receipt
        head = owner.head
        assert owner.verify(expected_head=head)["verified"]
    with SQLAuthority.open(root, passphrase, verification="complete", curated_source=source) as reopened:
        assert reopened.head == head and _economic_state(reopened) == before
        for doc_id, receipt in retained.items():
            assert reopened.receipt(doc_id) == receipt
        assert reopened.verify()["verified"]


def test_declared_token_row_and_page_counterfacts_reach_actual_pdf_guard(tmp_path, instrument_source, monkeypatch):
    source = instrument_source
    document = _member(source)
    with SQLAuthority.create(tmp_path.resolve() / "pdf-guards", secrets.token_urlsafe(32)) as owner:
        receipt = _prefix(owner, source, document)
        reading = json.loads(receipt["body"])
        original_decode, actual_guard = curation.decode_envelope, curation.validate_pdf_cells
        clean = original_decode(reading["raw_text"], document["doc_type"])
        assert clean["source_cells"]
        nonzero = next(i for i, cell in enumerate(clean["source_cells"]) if float(cell["raw"]) != 0)
        for mutation in ("signed_token", "physical_row", "physical_page"):
            calls = []
            def changed(text, family):
                envelope = copy.deepcopy(original_decode(text, family))
                cell = envelope["source_cells"][nonzero]
                if mutation == "signed_token":
                    cell["raw"] = cell["raw"][1:] if cell["raw"].startswith("-") else "-" + cell["raw"].lstrip("+")
                elif mutation == "physical_row":
                    cell["association"]["row_reference"] = "E999999"
                else:
                    cell["page"] = 200
                assert envelope["parser_input"] == clean["parser_input"]
                return envelope
            def checked_pdf(data, envelope):
                calls.append(mutation)
                assert data == source.original(document["sha256"])
                return actual_guard(data, envelope)
            with monkeypatch.context() as patch:
                patch.setattr(curation, "decode_envelope", changed)
                patch.setattr(curation, "validate_pdf_cells", checked_pdf)
                with pytest.raises((AuthorityError, IntegrityError, ValueError)):
                    curated_instrument.interpretation(owner, receipt)
            assert calls, "counterfactual must reach the real PDF validator"
            assert owner._row("interpretations", "doc_id=?", (document["sha256"],)) is None
        assert owner.verify()["verified"]


def test_custody_and_context_refuse_tamper_but_global_descriptor_reuses_across_roots(tmp_path, instrument_source):
    source = instrument_source
    document = _member(source)
    context_rows = []
    for label in ("first", "second"):
        with SQLAuthority.create(tmp_path.resolve() / label, secrets.token_urlsafe(32)) as owner:
            receipt = _prefix(owner, source, document)
            context_id = json.loads(receipt["capture_types"])["read_context_id"]
            row = owner._row("read_contexts", "context_id=?", (context_id,))
            assert hashlib.sha256(row["body"].encode()).hexdigest() == context_id
            context_rows.append(row)
            valid = curated_instrument.interpretation(owner, receipt)
            assert json.loads(valid["context"])["disposition"] == "typed_retained"
            admission = owner._row("source_admissions", "doc_id=?", (document["sha256"],))
            altered = json.loads(admission["body"])
            altered["document"]["id"] = "foreign-member"
            owner._db.execute("UPDATE source_admissions SET body=? WHERE doc_id=?",
                              (canonical(altered), document["sha256"]))
            with pytest.raises((AuthorityError, IntegrityError)):
                curated_instrument.interpretation(owner, receipt)
            owner._db.execute("UPDATE source_admissions SET body=? WHERE doc_id=?",
                              (admission["body"], document["sha256"]))
            for changed_body in ("{}", canonical({**json.loads(row["body"]), "schema_version": -1})):
                owner._db.execute("UPDATE read_contexts SET body=? WHERE context_id=?", (changed_body, context_id))
                with pytest.raises((AuthorityError, IntegrityError)):
                    curated_instrument.interpretation(owner, receipt)
                owner._db.execute("UPDATE read_contexts SET body=? WHERE context_id=?", (row["body"], context_id))
            owner._db.execute("DELETE FROM read_contexts WHERE context_id=?", (context_id,))
            with pytest.raises((AuthorityError, IntegrityError)):
                curated_instrument.interpretation(owner, receipt)
            owner._db.execute("INSERT INTO read_contexts(context_id,body) VALUES(?,?)", (context_id, row["body"]))
            assert curated_instrument.interpretation(owner, receipt) == valid
            assert owner.verify()["verified"]
    assert context_rows[0] == context_rows[1], "descriptor identity is global, not root/document origin"


def test_authenticated_parser_refusal_keeps_valid_receipt_only_prefix(tmp_path, instrument_source, monkeypatch):
    source, document = instrument_source, _member(instrument_source)
    root, passphrase = tmp_path.resolve() / "parser-refusal", secrets.token_urlsafe(32)
    calls = []
    def refused(family, *, source_contract=None, page_count=None):
        def parse(text, doc_id, locale, currency):
            calls.append((family, source_contract, page_count, locale, currency))
            return None, "controlled parser refusal; never persist this exception detail"
        return parse
    with monkeypatch.context() as patch:
        patch.setattr(instrument_read, "parser_for", refused)
        with SQLAuthority.create(root, passphrase, verification="complete") as owner:
            raw = _prefix(owner, source, document)
            assert owner.verify()["verified"], "later parser refusal cannot poison raw custody"
            prefix_head = owner.head
            outcome = owner.resume(document["sha256"])
            assert outcome.status == "unsupported"
            receipt = owner.receipt(document["sha256"])
            context = receipt["reading"]["authority_context"]
            assert (context["disposition"], context["reason"], receipt["facts"]) == ("unavailable", "parser_refused", None)
            assert owner._row("receipts", "doc_id=?", (document["sha256"],)) == raw
            assert owner.head != prefix_head and owner.postings(document["sha256"]) == []
            assert owner.verify()["verified"]
            head = owner.head
        with SQLAuthority.open(root, passphrase, verification="complete", curated_source=source) as reopened:
            assert reopened.receipt(document["sha256"]) == receipt
            assert reopened.verify(expected_head=head)["verified"]
    assert calls and all(call[2] == document["page_count"] for call in calls)


def _reseal_current_writer(owner, previous):
    revision = owner._revision
    envelope = canonical(seal(owner._audit_key, canonical({"version": 1, "operations": owner._operations}).encode(),
                              aad=canonical([revision, previous]).encode()))
    digest = hashlib.sha256(canonical([revision, previous, envelope]).encode()).hexdigest()
    mac = owner._mac(revision, digest)
    owner._db.execute("UPDATE audit SET envelope=?,record_hash=? WHERE sequence=?", (envelope, digest, revision))
    owner._db.execute("UPDATE commits SET head=?,mac=? WHERE revision=?", (digest, mac, revision))
    owner._db.execute("UPDATE control SET head=?,mac=? WHERE singleton=1", (digest, mac))


def test_forged_interpretation_and_financial_piggyback_fail_before_commit(tmp_path, instrument_source, monkeypatch):
    from test_sql_payroll import _deposit
    source, document = instrument_source, _member(instrument_source)
    for mode in ("indexed", "complete"):
        root, passphrase = tmp_path.resolve() / mode, secrets.token_urlsafe(32)
        with SQLAuthority.create(root, passphrase, verification=mode) as owner:
            bank = _deposit(owner)
            assert bank.status == "accepted"
            raw = _prefix(owner, source, document)
            before_head, before_economic = owner.head, _economic_state(owner)
            before_audit = owner.export_audit()
            original_event = owner._application_event
            actual_verify = curated_instrument_verify.verify_new_record
            for mutation in ("payload", "context", "disposition", "financial_piggyback", "foreign_document"):
                prepared, verified, native_commits = [], [], []
                def after_prepare(event, *args, **kwargs):
                    answer = original_event(event, *args, **kwargs)
                    if event == "prepare_transaction" and any(op["table"] == "interpretations" for op in owner._operations):
                        prepared.append(mutation)
                        operation = next(op for op in owner._operations if op["table"] == "interpretations")
                        row = operation["row"]
                        if mutation == "payload":
                            facts = json.loads(row["facts"])
                            facts["instrument_facts"]["identity"]["holder"]["value"] += " forged"
                            row["facts"] = canonical(facts)
                        elif mutation in ("context", "disposition"):
                            context = json.loads(row["context"])
                            if mutation == "context":
                                context["page_count"] += 1
                            else:
                                context["disposition"], context["reason"] = "unavailable", "parser_refused"
                                row["facts"] = "null"
                            row["context"] = canonical(context)
                        if mutation in ("payload", "context", "disposition"):
                            owner._db.execute("UPDATE interpretations SET facts=?,context=? WHERE doc_id=?",
                                              (row["facts"], row["context"], row["doc_id"]))
                        elif mutation == "financial_piggyback":
                            account = owner._row("accounts", "account_id=?", (bank.account_id,))
                            # A schema-valid, already-present economic row still
                            # cannot be piggybacked onto this unsupported writer.
                            owner._operations.append({"table": "accounts", "row": account})
                        else:
                            foreign = owner._row("items", "doc_id=?", (bank.doc_id,))
                            owner._operations.append({"table": "items", "row": foreign})
                        assert all(valid_row(op["table"], op["row"]) for op in owner._operations)
                        _reseal_current_writer(owner, before_head["head"])
                    return answer
                def checked_verify(store, previous_revision, previous_head):
                    if prepared:
                        verified.append(mutation)
                    return actual_verify(store, previous_revision, previous_head)
                with monkeypatch.context() as patch:
                    patch.setattr(owner, "_application_event", after_prepare)
                    patch.setattr(curated_instrument_verify, "verify_new_record", checked_verify)
                    owner._db.set_trace_callback(lambda statement: native_commits.append(statement)
                                                 if statement.strip().upper() == "COMMIT" else None)
                    try:
                        with pytest.raises(IntegrityError):
                            owner.resume(document["sha256"])
                    finally:
                        owner._db.set_trace_callback(None)
                assert prepared == verified == [mutation], "must reach fresh semantic verification after prepare"
                assert native_commits == [], "refusal must precede native COMMIT"
                assert not owner._db.in_transaction
                assert owner.head == before_head and owner.export_audit() == before_audit
                assert owner._row("receipts", "doc_id=?", (document["sha256"],)) == raw
                assert owner._row("interpretations", "doc_id=?", (document["sha256"],)) is None
                assert _economic_state(owner) == before_economic
                assert owner.verify()["verified"]
            # Begin from a genuine committed instrument. Complete mode receives
            # its valid preimage with the source attached; detachment happens
            # only after preparation, never as a claimed valid detached open.
            assert owner.resume(document["sha256"]).status == "unsupported"
            committed = owner.receipt(document["sha256"])
            before_head, before_audit = owner.head, owner.export_audit()
            before_economic = _economic_state(owner)
            admission = owner._row("source_admissions", "doc_id=?", (document["sha256"],))
            genuine_receipt = owner._row("receipts", "doc_id=?", (document["sha256"],))
            prepared, verified, native_commits = [], [], []
            def detach_after_prepare(event, *args, **kwargs):
                answer = original_event(event, *args, **kwargs)
                if event == "prepare_transaction":
                    prepared.append("receipt_kind_detached")
                    owner._curated_owner = None
                return answer
            def checked_detached(store, previous_revision, previous_head):
                assert prepared == ["receipt_kind_detached"] and store._curated_owner is None
                verified.append("receipt_kind_detached")
                return actual_verify(store, previous_revision, previous_head)
            with monkeypatch.context() as patch:
                patch.setattr(owner, "_application_event", detach_after_prepare)
                patch.setattr(curated_instrument_verify, "verify_new_record", checked_detached)
                owner._db.set_trace_callback(lambda statement: native_commits.append(statement)
                                             if statement.strip().upper() == "COMMIT" else None)
                try:
                    with pytest.raises(IntegrityError):
                        with owner._transaction():
                            changed = {**genuine_receipt, "facts_type": "unsupported"}
                            assert valid_row("receipts", changed)
                            owner._db.execute("UPDATE receipts SET facts_type=? WHERE doc_id=?",
                                              (changed["facts_type"], document["sha256"]))
                            owner._operations.append({"table": "receipts", "row": changed})
                finally:
                    owner._db.set_trace_callback(None)
                    owner._curated_owner = source
            assert prepared == verified == ["receipt_kind_detached"]
            assert native_commits == [] and not owner._db.in_transaction
            assert owner.head == before_head and owner.export_audit() == before_audit
            assert owner.receipt(document["sha256"]) == committed
            assert owner._row("source_admissions", "doc_id=?", (document["sha256"],)) == admission
            assert _economic_state(owner) == before_economic
            assert owner.verify()["verified"]
        with SQLAuthority.open(root, passphrase, verification=mode, curated_source=source) as reopened:
            assert reopened.head == before_head and reopened.verify()["verified"]


def test_independent_replay_never_calls_derivation_producer(tmp_path, instrument_source, monkeypatch):
    source, document = instrument_source, _member(instrument_source)
    root, passphrase = tmp_path.resolve() / "independent", secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete") as owner:
        outcome = owner.ingest_curated(source.original(document["sha256"]), source)
        assert outcome.status == "unsupported"
        retained, head = owner.receipt(outcome.doc_id), owner.head
    def forbidden(*args, **kwargs):
        pytest.fail("independent replay called the derivation producer")
    with monkeypatch.context() as patch:
        patch.setattr(curated_instrument, "interpretation", forbidden)
        with SQLAuthority.open(root, passphrase, verification="complete", curated_source=source) as reopened:
            assert reopened.receipt(outcome.doc_id) == retained
            assert reopened.verify(expected_head=head)["verified"]


def test_new_profile_reuses_application_backup_restore_and_ready_recovery(tmp_path, instrument_source):
    source, document = instrument_source, _member(instrument_source)
    root, backup, restored = (tmp_path.resolve() / name for name in ("application", "backup", "restored"))
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        outcome = owner.ingest_curated(source.original(document["sha256"]), source)
        assert outcome.status == "unsupported"
        retained, terminal, head = owner.receipt(outcome.doc_id), owner.terminal, owner.head
        economic = _economic_state(owner._engine)
        copied = owner.backup(backup, passphrase=passphrase, expected_terminal=terminal)
        assert copied["terminal"] == terminal and owner.terminal == terminal
    assert ApplicationSQLAuthority.restore(backup, restored, passphrase, curated_source=source,
                                           expected_terminal=terminal) == copied
    assert ApplicationSQLAuthority.recover(restored, passphrase, curated_source=source,
                                           expected_prefix=terminal)["outcome"] == "already_ready"
    with SQLAuthority.open(restored, passphrase, verification="complete", application=True,
                           curated_source=source) as reopened:
        assert reopened.receipt(outcome.doc_id) == retained
        assert reopened.original(outcome.doc_id) == source.original(outcome.doc_id)
        assert reopened.head == head and reopened.terminal == terminal
        assert _economic_state(reopened._engine) == economic
        assert reopened.verify(expected_head=head, expected_terminal=terminal)["verified"]


def test_previous_format_metadata_counterfacts_refuse_before_native_connect(tmp_path, monkeypatch):
    """Metadata counterfactuals only; these are not genuine legacy vaults."""
    from viva.sql_authority import application, store
    for application_mode, old_format in ((False, "viva-sql-authority-prototype-v6"),
                                         (True, "viva-sql-application-engine-v4")):
        root = tmp_path.resolve() / ("application-format" if application_mode else "direct-format")
        passphrase = secrets.token_urlsafe(32)
        with SQLAuthority.create(root, passphrase, verification="complete", application=application_mode):
            pass
        metadata_path = (root / "sql" if application_mode else root) / "authority.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["format"] = old_format
        metadata_path.write_text(canonical(metadata))
        before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        native_calls = []
        def forbidden(*args, **kwargs):
            native_calls.append("connect")
            pytest.fail("old-format metadata reached native connection")
        with monkeypatch.context() as patch:
            patch.setattr(store, "_connect", forbidden)
            patch.setattr(application, "_connect", forbidden)
            with pytest.raises((AuthorityError, IntegrityError)):
                SQLAuthority.open(root, passphrase, verification="complete", application=application_mode)
        assert native_calls == []
        assert before == {str(path.relative_to(root)): path.read_bytes()
                          for path in root.rglob("*") if path.is_file()}
