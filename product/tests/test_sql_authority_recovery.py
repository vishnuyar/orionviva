"""Durable staged work, lost acknowledgments and serialized SQL writers."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import threading

import pytest
from sqlcipher3 import dbapi2 as sql

from viva.sql_authority import SQLAuthority, AuthorityError
from test_sql_authority_bank import reading, ingest

pytestmark = pytest.mark.production_kdf


def test_reader_failure_is_uncertain_and_never_automatically_repeated(tmp_path):
    root = tmp_path.resolve() / "authority"
    data = b"synthetic uncertain source"
    doc_id = hashlib.sha256(data).hexdigest()
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def fail(_source, _doc_id):
            assert store.original(doc_id) == data
            assert store.item(doc_id)["state"] == "read_uncertain"
            raise TimeoutError("synthetic uncertain request")
        with pytest.raises(TimeoutError):
            store.ingest(data, fail, contract="synthetic-v1")
    with SQLAuthority.open(root, "synthetic passphrase") as reopened:
        result = reopened.ingest(data, lambda *_args: pytest.fail("uncertain request repeated"), contract="synthetic-v1")
        assert result.status == "read_uncertain"
        assert reopened.original(doc_id) == data
        assert reopened.postings(doc_id) == []
        assert reopened.verify()["verified"]


def test_receipt_commit_lost_acknowledgment_resumes_without_reader(tmp_path):
    root = tmp_path.resolve() / "authority"
    data = b"synthetic retained response"
    doc_id = hashlib.sha256(data).hexdigest()
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def fault(point):
            if point == "after_commit" and store.item(doc_id)["state"] == "staged":
                raise SystemExit("synthetic lost acknowledgment")
        store._fault = fault
        with pytest.raises(SystemExit):
            store.ingest(data, lambda _source, captured: reading(captured), contract="synthetic-v1")
        assert store.receipt(doc_id)["reading"]["facts"]["doc_id"] == doc_id
    with SQLAuthority.open(root, "synthetic passphrase") as reopened:
        result = reopened.ingest(data, lambda *_args: pytest.fail("retained reader repeated"), contract="synthetic-v1")
        assert result.status == "accepted"
        assert reopened.verify()["counts"]["transactions"] == 1


@pytest.mark.parametrize("point,error", [("after_financial_rows", SystemExit), ("before_audit", RuntimeError), ("before_commit", sql.OperationalError)])
def test_financial_fault_rolls_back_entire_promotion(tmp_path, point, error):
    root = tmp_path.resolve() / "authority"
    data = b"synthetic interrupted promotion"
    doc_id = hashlib.sha256(data).hexdigest()
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def fault(at):
            if at == point and any(operation["table"] == "periods" for operation in store._operations):
                raise error("synthetic interruption")
        store._fault = fault
        with pytest.raises(error):
            store.ingest(data, lambda _source, captured: reading(captured), contract="synthetic-v1")
        assert store.item(doc_id)["state"] == "staged"
        assert store._db.execute("SELECT count(*) FROM accounts").fetchone() == (0,)
        assert store.postings(doc_id) == []
        assert store.verify()["counts"]["transactions"] == 0
    with SQLAuthority.open(root, "synthetic passphrase") as reopened:
        assert reopened.resume(doc_id).status == "accepted"
        assert reopened.resume(doc_id).status == "accepted"
        assert reopened.verify()["counts"]["transactions"] == 1


def test_accepted_commit_lost_acknowledgment_cannot_duplicate(tmp_path):
    root = tmp_path.resolve() / "authority"
    data = b"synthetic accepted lost response"
    doc_id = hashlib.sha256(data).hexdigest()
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def fault(point):
            if point == "after_commit" and store.item(doc_id)["state"] == "accepted":
                raise SystemExit("synthetic acknowledgment lost")
        store._fault = fault
        with pytest.raises(SystemExit):
            store.ingest(data, lambda _source, captured: reading(captured), contract="synthetic-v1")
    with SQLAuthority.open(root, "synthetic passphrase") as reopened:
        head = reopened.head
        assert reopened.ingest(data, lambda *_args: pytest.fail("reader repeated"), contract="synthetic-v1").status == "accepted"
        assert reopened.head == head
        assert reopened.verify()["counts"]["transactions"] == 1


def test_two_writers_serialize_economic_duplicate(tmp_path):
    root = tmp_path.resolve() / "authority"
    with SQLAuthority.create(root, "synthetic passphrase"):
        pass
    barrier = threading.Barrier(2)
    def writer(index):
        with SQLAuthority.open(root, "synthetic passphrase") as store:
            def reader(_source, doc_id):
                barrier.wait(timeout=5)
                return reading(doc_id)
            return store.ingest(f"synthetic duplicate encoding {index}".encode(), reader, contract="synthetic-v1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, range(2)))
    assert sorted(result.status for result in results) == ["accepted", "pending"]
    assert next(result for result in results if result.status == "pending").reason == "economic_duplicate"
    with SQLAuthority.open(root, "synthetic passphrase") as store:
        assert store.verify()["counts"]["transactions"] == 1


def test_reader_sees_complete_prior_state_during_uncommitted_promotion(tmp_path):
    root = tmp_path.resolve() / "authority"
    with SQLAuthority.create(root, "synthetic passphrase") as writer:
        first = ingest(writer)
        with SQLAuthority.open(root, "synthetic passphrase") as reader:
            def fault(point):
                if point == "after_financial_rows":
                    assert reader.account(first.account_id)["running_balance"] == "90"
                    assert len(reader.transactions(first.account_id)) == 1
            writer._fault = fault
            second = ingest(writer, b"synthetic second source", opening="90", closing="80", start="2026-01-31", end="2026-02-28")
            assert second.status == "accepted"
            assert reader.account(first.account_id)["running_balance"] == "80"
            assert len(reader.transactions(first.account_id)) == 2


def test_retained_contract_cannot_silently_change(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        ingest(store)
        with pytest.raises(AuthorityError, match="contract differs"):
            store.ingest(b"synthetic source", lambda *_args: pytest.fail("reader repeated"), contract="different-contract")


def test_actual_sqlite_full_rolls_back_promotion_but_retains_reading(tmp_path):
    from viva.ingest.statement import TxnFact
    from decimal import Decimal as D
    root = tmp_path.resolve() / "authority"
    data = b"synthetic page budget source"
    doc_id = hashlib.sha256(data).hexdigest()
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def bounded_reader(_source, captured):
            result = reading(captured)
            result.facts.transactions = [TxnFact("2026-01-01", "Synthetic bounded line " + "x" * 1000, D("-1"), page=1) for _ in range(500)]
            result.facts.closing_amount = D("-400")
            return result
        def cap_after_receipt(point):
            if point == "after_commit" and store.item(doc_id)["state"] == "staged":
                pages = store._db.execute("PRAGMA page_count").fetchone()[0]
                store._db.execute(f"PRAGMA max_page_count={pages}")
        store._fault = cap_after_receipt
        with pytest.raises(sql.OperationalError, match="full"):
            store.ingest(data, bounded_reader, contract="synthetic-v1")
        assert store.item(doc_id)["state"] == "staged"
        assert store.receipt(doc_id)
        assert store.verify()["counts"]["transactions"] == 0
        store._fault = lambda _point: None
        store._db.execute("PRAGMA max_page_count=100000")
        assert store.resume(doc_id).status == "accepted"
        assert store.verify()["counts"]["transactions"] == 500


@pytest.mark.parametrize("child", [{"date": "2026-01-10", "amount": "-10"}, None, "invalid typed child", 7])
def test_returned_json_serializable_invalid_children_retain_receipt_and_do_not_reread(tmp_path, child):
    root = tmp_path.resolve() / "authority"
    data = b"synthetic malformed typed child"
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def malformed(_source, doc_id):
            result = reading(doc_id)
            result.facts.transactions = [child]
            result.raw_text = '{"retained":"original response"}'
            return result
        result = store.ingest(data, malformed, contract="synthetic-v1")
        assert (result.status, result.reason) == ("pending", "unsupported_observation")
        receipt = store.receipt(result.doc_id)
        assert receipt["facts"]["transactions"] == [child]
        assert receipt["reading"]["raw_text"] == '{"retained":"original response"}'
        assert store.postings(result.doc_id) == []
        assert store.verify()["verified"]
    with SQLAuthority.open(root, "synthetic passphrase") as reopened:
        retried = reopened.ingest(data, lambda *_args: pytest.fail("completed invalid reading repeated"), contract="synthetic-v1")
        assert (retried.status, retried.reason) == ("pending", "unsupported_observation")
        assert reopened.resume(result.doc_id).status == "pending"
        assert reopened.receipt(result.doc_id) == receipt
        assert reopened.verify()["counts"]["transactions"] == 0


@pytest.mark.parametrize("field", ["doc_type", "raw_text", "source_locale"])
@pytest.mark.parametrize("value", [None, {}, [], True, 123, 1.5])
def test_malformed_finite_json_reading_metadata_is_retained_then_explicitly_pending(tmp_path, field, value):
    root = tmp_path.resolve() / "authority"
    data = b"synthetic malformed reading metadata"
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def malformed(_source, doc_id):
            result = reading(doc_id)
            # A real raw response ensures malformed locale reaches the same
            # admission boundary as a completed extraction.
            result.raw_text = '{"opening":{"amount_raw":"100"}}'
            setattr(result, field, value)
            return result
        result = store.ingest(data, malformed, contract="synthetic-v1")
        assert (result.status, result.reason) == ("pending", "invalid_reading")
        receipt = store.receipt(result.doc_id)
        assert receipt["raw_reading"][field] == value
        assert type(receipt["raw_reading"][field]) is type(value)
        assert store.postings(result.doc_id) == []
        assert store.verify()["verified"]
    with SQLAuthority.open(root, "synthetic passphrase") as reopened:
        assert reopened.ingest(data, lambda *_args: pytest.fail("malformed completed reading repeated"), contract="synthetic-v1").status == "pending"
        assert reopened.resume(result.doc_id).reason == "invalid_reading"
        assert reopened.receipt(result.doc_id) == receipt
        assert reopened.verify()["counts"]["transactions"] == 0


def test_raw_receipt_is_durable_before_profile_or_interpretation_and_resumes(tmp_path, monkeypatch):
    import viva.sql_authority.reading as interpretation
    from viva.sql_authority.store import _encode
    root = tmp_path.resolve() / "authority"
    data = b"synthetic raw receipt interruption"
    doc_id = hashlib.sha256(data).hexdigest()
    returned = reading(doc_id)
    expected = _encode(returned)
    original_profile = interpretation.profile_for
    monkeypatch.setattr(interpretation, "profile_for", lambda *_args: pytest.fail("profile helper ran before durable receipt"))
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def fault(point):
            if point == "after_raw_receipt":
                assert store.receipt(doc_id)["raw_reading"] == expected
                assert store._db.execute("SELECT count(*) FROM interpretations").fetchone() == (0,)
                raise SystemExit("synthetic interruption before interpretation")
        store._fault = fault
        with pytest.raises(SystemExit):
            store.ingest(data, lambda *_args: returned, contract="synthetic-v1")
        assert store.item(doc_id)["state"] == "staged"
        assert store.receipt(doc_id)["raw_reading"] == expected
        assert store.verify()["counts"]["transactions"] == 0
    monkeypatch.setattr(interpretation, "profile_for", original_profile)
    with SQLAuthority.open(root, "synthetic passphrase") as reopened:
        result = reopened.ingest(data, lambda *_args: pytest.fail("raw retained reading repeated"), contract="synthetic-v1")
        assert result.status == "accepted"
        assert reopened.receipt(doc_id)["raw_reading"] == expected
        assert reopened.verify()["counts"]["transactions"] == 1


@pytest.mark.parametrize("changed", ["profile", "normalizer", "missing_descriptor"])
def test_resume_after_raw_receipt_cannot_rebind_new_or_missing_interpretation_contract(tmp_path, monkeypatch, changed):
    from dataclasses import replace
    from viva.ingest import registry
    from vivacore.verify import normalize
    root = tmp_path.resolve() / "authority"
    data = b"synthetic retained contract boundary"
    doc_id = hashlib.sha256(data).hexdigest()
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def stop(point):
            if point == "after_raw_receipt":
                raise SystemExit("synthetic stopped before interpretation")
        store._fault = stop
        with pytest.raises(SystemExit):
            store.ingest(data, lambda _source, captured: reading(captured), contract="synthetic-v1")
        raw = store.receipt(doc_id)["raw_reading"]
        tags = __import__("json").loads(store._row("receipts", "doc_id=?", (doc_id,))["capture_types"])
        if changed == "missing_descriptor":
            store._db.execute("DELETE FROM read_contexts WHERE context_id=?", (tags["read_context_id"],))
    if changed == "profile":
        prior = registry.profile_for("checking_statement")
        monkeypatch.setitem(registry._INDEX, "checking_statement", replace(prior, profile_version="synthetic changed profile"))
    elif changed == "normalizer":
        monkeypatch.setattr(normalize, "RULES_VERSION", "synthetic changed normalizer")
    with SQLAuthority.open(root, "synthetic passphrase") as reopened:
        result = reopened.ingest(data, lambda *_args: pytest.fail("retained reading repeated"), contract="synthetic-v1")
        assert (result.status, result.reason) == ("pending", "extraction_contract_changed")
        assert reopened.receipt(doc_id)["raw_reading"] == raw
        assert reopened.postings(doc_id) == []
        if changed != "missing_descriptor":
            assert reopened.verify()["verified"]


@pytest.mark.parametrize("field,value", [("opening_amount", "100"), ("closing_amount", "90")])
def test_plain_json_string_money_is_not_promoted_as_original_decimal(tmp_path, field, value):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        def malformed(_source, doc_id):
            result = reading(doc_id)
            setattr(result.facts, field, value)
            return result
        result = store.ingest(b"synthetic original runtime amount type", malformed, contract="synthetic-v1")
        assert (result.status, result.reason) == ("pending", "unsupported_observation")
        assert store.receipt(result.doc_id)["raw_reading"]["facts"][field] == value
        assert store.postings(result.doc_id) == []
        assert store.verify()["verified"]


def test_complete_transaction_dictionary_cannot_impersonate_typed_original_child(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        def malformed(_source, doc_id):
            result = reading(doc_id)
            result.facts.transactions = [result.facts.transactions[0].to_dict()]
            return result
        result = store.ingest(b"synthetic complete dictionary transaction", malformed, contract="synthetic-v1")
        assert (result.status, result.reason) == ("pending", "unsupported_observation")
        assert store.receipt(result.doc_id)["facts"]["transactions"][0]["amount"] == "-10"
        assert store.postings(result.doc_id) == []
        assert store.verify()["verified"]


def test_same_version_interpretation_bytes_change_holds_retained_reading(tmp_path, monkeypatch):
    from viva.sql_authority import reading as interpretation
    root = tmp_path.resolve() / "authority"
    data = b"synthetic implementation boundary"
    doc_id = hashlib.sha256(data).hexdigest()
    original_identity = interpretation.implementation_identity
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def stop(point):
            if point == "after_raw_receipt":
                raise SystemExit("synthetic paused before interpretation")
        store._fault = stop
        with pytest.raises(SystemExit):
            store.ingest(data, lambda _source, captured: reading(captured), contract="synthetic-v1")
        raw = store.receipt(doc_id)["raw_reading"]
    def changed_bytes():
        result = original_identity()
        result["files"]["viva.ingest.statement"] = "f" * 64
        # The injected observation models a different helper closure with the
        # same public version strings; no real source file is edited.
        result["sha256"] = "e" * 64
        return result
    monkeypatch.setattr(interpretation, "implementation_identity", changed_bytes)
    with SQLAuthority.open(root, "synthetic passphrase") as reopened:
        result = reopened.ingest(data, lambda *_args: pytest.fail("retained reader repeated"), contract="synthetic-v1")
        assert (result.status, result.reason) == ("pending", "extraction_contract_changed")
        assert reopened.receipt(doc_id)["raw_reading"] == raw
        assert reopened.postings(doc_id) == []
        assert reopened.verify()["verified"]


def test_interpretation_digest_is_once_per_handle_and_missing_source_fails_closed(tmp_path, monkeypatch):
    from viva.sql_authority import reading as interpretation
    import viva.sql_authority.bank as bank
    calls = []
    original = interpretation.implementation_identity
    def counted():
        calls.append(True)
        return original()
    monkeypatch.setattr(interpretation, "implementation_identity", counted)
    root = tmp_path.resolve() / "authority"
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        assert len(calls) == 1
        ingest(store)
        ingest(store, b"synthetic second digest case", opening="90", closing="80", start="2026-01-31", end="2026-02-28")
        assert len(calls) == 1
        assert store._db.execute("SELECT count(*) FROM read_contexts").fetchone() == (1,)
        assert store.verify()["verified"]
    monkeypatch.setattr(bank, "__file__", str(tmp_path.resolve() / "missing-helper.py"))
    with pytest.raises(AuthorityError, match="source is missing"):
        SQLAuthority.open(root, "synthetic passphrase")
