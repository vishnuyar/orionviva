"""Supported balances and explicit unsupported observations in SQL authority."""
from decimal import Decimal as D
import hashlib
import json

import pytest

from viva.ingest.pipeline_models import ReadResult
from viva.ingest.statement import StatementFacts, TxnFact, from_model_json
from viva.sql_authority import SQLAuthority

pytestmark = pytest.mark.production_kdf


def reading(doc_id, *, opening="100", closing="90", start="2026-01-01", end="2026-01-31", movement="-10", doc_type="checking_statement", number="1234567", institution="Synthetic Issuer", currency="USD", page=1):
    facts = StatementFacts(doc_id, doc_type, 1.0, "Synthetic Checking", currency,
        D(opening), start, D(closing), end,
        [TxnFact(start, "Synthetic movement", D(movement), page=page)],
        opening_page=1, closing_page=1, account_number=number, institution=institution)
    return ReadResult(doc_type, 1.0, facts=facts)


def ingest(store, data=b"synthetic source", **kwargs):
    return store.ingest(data, lambda _data, doc_id: reading(doc_id, **kwargs), contract="synthetic-balance-v1")


@pytest.fixture
def store(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as opened:
        yield opened


@pytest.mark.parametrize("doc_type,movement,counter", [
    ("checking_statement", "-10", "Expenses:Uncategorized"),
    ("savings_statement", "10", "Income:Uncategorized"),
    ("credit_card_statement", "10", "Expenses:Uncategorized"),
    ("credit_card_statement", "-10", "Transfers:Uncategorized"),
])
def test_supported_kind_exact_postings_and_evidence(store, doc_type, movement, counter):
    result = ingest(store, doc_type=doc_type, movement=movement, closing=str(D("100") + D(movement)))
    assert result.status == "accepted"
    legs = store.postings(result.doc_id)
    assert [(leg["account"], leg["amount"], leg["grade"]) for leg in legs] == [
        (result.account_id, movement, "verified"), (counter, str(-D(movement)), "unverified")]
    assert sum((D(leg["amount"]) for leg in legs), D(0)) == 0
    assert all(leg["provenance"]["doc_id"] == result.doc_id for leg in legs)
    assert store.original(result.doc_id) == b"synthetic source"
    assert store.receipt(result.doc_id)["facts"]["transactions"][0]["page"] == 1
    assert store.verify()["verified"]


def test_forward_backward_and_reopen(store):
    first = ingest(store)
    forward = ingest(store, b"next source", opening="90", closing="80", start="2026-01-31", end="2026-02-28")
    backward = ingest(store, b"earlier source", opening="110", closing="100", start="2025-12-01", end="2026-01-01")
    assert {first.status, forward.status, backward.status} == {"accepted"}
    assert {first.account_id, forward.account_id, backward.account_id} == {first.account_id}
    account = store.account(first.account_id)
    assert (account["earliest_opening"], account["running_balance"]) == ("110", "80")
    assert len(store.transactions(first.account_id)) == 3
    expected = store.head
    store.verify(expected_head=expected)
    with SQLAuthority.open(store.root, "synthetic passphrase") as reopened:
        assert reopened.verify(expected_head=expected)["verified"]
        assert reopened.original(first.doc_id) == b"synthetic source"
        assert reopened.receipt(first.doc_id)["contract"] == "synthetic-balance-v1"


def test_gap_reconsideration_queries_only_changed_boundary(store):
    first = ingest(store)
    gap = ingest(store, b"gap source", opening="80", closing="70", start="2026-02-28", end="2026-03-31")
    assert gap.status == "pending"
    assert store.postings(gap.doc_id) == []
    middle = ingest(store, b"connector source", opening="90", closing="80", start="2026-01-31", end="2026-02-28")
    assert middle.status == "accepted"
    assert store.item(gap.doc_id)["state"] == "accepted"
    assert store.account(first.account_id)["running_balance"] == "70"
    assert all("WHERE" in query for query in store.last_queries)
    assert any("d.boundary_amount=?" in query for query in store.last_queries)
    assert store.verify()["counts"]["transactions"] == 3


@pytest.mark.parametrize("changes,reason", [
    ({"number": "***4567"}, "identity_requires_review"),
    ({"institution": ""}, "identity_requires_review"),
    ({"closing": "91"}, "arithmetic_requires_review"),
    ({"movement": "0", "closing": "100"}, "unsupported_observation"),
    ({"page": 0}, "unsupported_observation"),
    ({"doc_type": "pay_stub"}, "unsupported_family"),
])
def test_unimplemented_rungs_never_create_financial_rows(store, changes, reason):
    result = ingest(store, **changes)
    assert result.status in {"pending", "unsupported"}
    assert result.reason == reason
    assert store.postings(result.doc_id) == []
    assert store.verify()["counts"]["accounts"] == 0
    assert store.receipt(result.doc_id)


def test_distinct_issuer_full_number_collision_requires_review(store):
    first = ingest(store)
    second = ingest(store, b"other issuer source", opening="90", closing="80", start="2026-01-31", end="2026-02-28", institution="Other Synthetic Issuer")
    assert second.status == "pending"
    assert second.reason == "institution_requires_review"
    assert store.account(first.account_id)["running_balance"] == "90"
    assert store.postings(second.doc_id) == []


def test_currency_conflict_does_not_create_second_account(store):
    ingest(store)
    result = ingest(store, b"other currency source", currency="EUR", opening="90", closing="80", start="2026-01-31", end="2026-02-28")
    assert result.status == "pending"
    assert result.reason == "currency_requires_review"
    assert store.verify()["counts"]["accounts"] == 1


def test_byte_duplicate_does_not_read_again_or_add_audit(store):
    first = ingest(store)
    head = store.head
    duplicate = store.ingest(b"synthetic source", lambda *_args: pytest.fail("duplicate reader invoked"), contract="synthetic-balance-v1")
    assert duplicate == first.__class__(first.doc_id, first.status, first.reason, first.account_id, first.revision)
    assert store.head == head
    assert store.verify()["counts"]["transactions"] == 1


def test_economic_duplicate_and_conflicting_reissue_do_not_post(store):
    first = ingest(store)
    duplicate = ingest(store, b"different encoded same period")
    reissue = ingest(store, b"conflicting period", closing="80", movement="-20")
    assert (duplicate.status, duplicate.reason) == ("pending", "economic_duplicate")
    assert (reissue.status, reissue.reason) == ("pending", "period_reissue")
    assert len(store.transactions(first.account_id)) == 1
    assert store.postings(duplicate.doc_id) == store.postings(reissue.doc_id) == []


def test_float_poison_stays_unaccepted(store):
    def poisoned(_source, doc_id):
        result = reading(doc_id)
        result.facts.opening_amount = 100.0
        return result
    result = store.ingest(b"float source", poisoned, contract="synthetic-balance-v1")
    assert (result.status, result.reason) == ("pending", "unsupported_observation")
    assert store.postings(result.doc_id) == []


def test_retained_response_and_typed_observations_must_agree(store):
    payload = {"doc_type": "checking_statement", "account_ref": "Synthetic Checking",
        "account_number": "1234567", "institution": "Synthetic Issuer",
        "opening": {"amount_raw": "100", "date_raw": "2026-01-01", "page": 1},
        "closing": {"amount_raw": "90", "date_raw": "2026-01-31", "page": 1},
        "transactions": [{"amount_raw": "10", "balance_effect": "decrease", "date_raw": "2026-01-01", "description": "Synthetic movement", "page": 1}]}
    raw = json.dumps(payload)
    def reader(_source, doc_id):
        facts, error = from_model_json(raw, doc_id, "en-US", "USD")
        assert error is None
        return ReadResult("checking_statement", 1.0, facts=facts, raw_text=raw, source_locale="en-US")
    accepted = store.ingest(b"raw consistent", reader, contract="synthetic-balance-v1")
    assert accepted.status == "accepted"
    def mismatch(source, doc_id):
        result = reader(source, doc_id)
        result.facts.opening_amount = D("110")
        result.facts.closing_amount = D("100")
        return result
    held = store.ingest(b"raw inconsistent", mismatch, contract="synthetic-balance-v1")
    assert (held.status, held.reason) == ("pending", "extraction_binding")
    assert store.receipt(held.doc_id)["reading"]["raw_text"] == raw
    assert store.postings(held.doc_id) == []


@pytest.mark.parametrize("amount", ["1E+100000", "1E-100000", "NaN", "Infinity", "12345678901234567890123456789"])
def test_unbounded_or_context_rounding_amounts_remain_pending(store, amount):
    def malformed(_source, doc_id):
        result = reading(doc_id)
        result.facts.opening_amount = D(amount)
        result.facts.closing_amount = D(amount)
        return result
    result = store.ingest(b"synthetic bounded observations", malformed, contract="synthetic-v1")
    assert (result.status, result.reason) == ("pending", "unsupported_observation")
    assert store.postings(result.doc_id) == []


def test_consumed_gap_dependencies_do_not_remain_in_active_lookup(store):
    ingest(store)
    gap = ingest(store, b"synthetic gap closure", opening="80", closing="70", start="2026-02-28", end="2026-03-31")
    assert gap.status == "pending"
    ingest(store, b"synthetic joining closure", opening="90", closing="80", start="2026-01-31", end="2026-02-28")
    assert store._db.execute("SELECT active FROM dependencies WHERE doc_id=?", (gap.doc_id,)).fetchall() == [(0,), (0,)]
    assert "active=?" in str(store.dependency_plans()["pending"])
    assert store.verify()["counts"]["dependencies"] == 2


@pytest.mark.parametrize("number", ["١٢٣٤٥٦٧", "１２３４５６７", "123٤٥٦٧"])
def test_unicode_number_signals_are_retained_pending_without_normalization(store, number):
    result = ingest(store, number=number)
    assert (result.status, result.reason) == ("pending", "identity_requires_review")
    assert store.item(result.doc_id)["state"] == "pending"
    assert store.receipt(result.doc_id)["facts"]["account_number"] == number
    assert store.postings(result.doc_id) == []
    assert store.verify()["counts"]["accounts"] == 0


@pytest.mark.parametrize("changes", [
    {"page": True}, {"page": "1"}, {"currency": "US1"},
    {"number": "1234"}, {"number": "***4567"},
])
def test_closed_protocol_admission_returns_pending_for_unsupported_observations(store, changes):
    result = ingest(store, **changes)
    assert result.status == "pending"
    assert result.reason in {"identity_requires_review", "unsupported_observation"}
    assert store.receipt(result.doc_id)
    assert store.postings(result.doc_id) == []
    assert store.verify()["counts"]["accounts"] == 0


@pytest.mark.parametrize("page_count", [True, False, 1.0, -1, 0, 201])
def test_source_page_count_requires_exact_bounded_integer_and_retains_invalid_metadata(store, page_count):
    def malformed(_source, doc_id):
        result = reading(doc_id)
        result.facts.validated_source_page_count = page_count
        return result
    result = store.ingest(b"synthetic fresh page count case", malformed, contract="synthetic-v1")
    assert (result.status, result.reason) == ("pending", "unsupported_observation")
    retained = store.receipt(result.doc_id)["facts"]["validated_source_page_count"]
    assert type(retained) is type(page_count) and retained == page_count
    assert store.postings(result.doc_id) == []
    assert store.verify()["counts"]["accounts"] == 0


@pytest.mark.parametrize("page_count", [None, 1, 200])
def test_valid_source_page_count_does_not_change_supported_financial_values(store, page_count):
    def reader(_source, doc_id):
        result = reading(doc_id)
        result.facts.validated_source_page_count = page_count
        return result
    result = store.ingest(b"synthetic fresh valid page count", reader, contract="synthetic-v1")
    assert result.status == "accepted"
    assert store.account(result.account_id)["running_balance"] == "90"
    assert [row["amount"] for row in store.postings(result.doc_id)] == ["-10", "10"]
    assert store.verify()["verified"]
