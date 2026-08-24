"""The two-phase read: a cheap classify pass, then a per-type extract pass — and
both recorded verbatim in the claims layer."""

from decimal import Decimal

from viva.ingest import (PARKED, POSTED, RawStore, ReadResult, capture_and_ingest)
from viva.ingest.pipeline import ModelPhase
from viva.ingest.reader import classify, read_with_retry
from viva.ledger import EventStore, Ledger
from vivacore.models.base import ModelResult, PageImage


def _result(text, cost=0.01):
    return ModelResult(text=text, resolved_model="m", input_tokens=5,
                       output_tokens=5, cost_usd=cost, latency_s=0.0,
                       request={}, response={"usage": {"prompt_tokens": 5,
                                                        "completion_tokens": 5}})


class _FakeAdapter:
    """Records how many images each call received (classify should get 1)."""
    def __init__(self, text, cost=0.01):
        self._text, self._cost = text, cost
        self.image_counts = []

    def extract(self, pages, prompt):
        self.image_counts.append(len(pages))
        return _result(self._text, self._cost)


def _pages(n):
    return [PageImage(i + 1, b"img", f"sha{i}") for i in range(n)]


def test_classify_uses_only_the_first_page_and_records_a_phase():
    adapter = _FakeAdapter('{"doc_type":"credit_card_statement","doc_type_confidence":0.97}')
    doc_type, conf, phase = classify(adapter, _pages(5), "embedded text",
                                     configured_model="configured-route")
    assert doc_type == "credit_card_statement" and conf == 0.97
    assert adapter.image_counts == [1]            # cheap: one image, not all five
    # The frame that holds the document's own text apart from the instructions
    # is part of what produced the reading, so it is named in the recorded
    # version and the whole id resolves back to the exact trusted text.
    assert phase.phase == "classify"
    assert phase.model == "configured-route"
    assert phase.resolved_model == "m"
    assert phase.usage_reported
    assert phase.prompt_version == "classify-v2+untrusted-frame-v1"
    from viva.ingest import prompt_library
    assert prompt_library.resolve(phase.prompt_version)
    assert phase.parse_ok and phase.cost_usd == 0.01


def test_classify_unreadable_is_unknown_not_a_guess():
    doc_type, conf, phase = classify(_FakeAdapter("I cannot tell"), _pages(1), "")
    assert doc_type == "unknown" and not phase.parse_ok


_EXTRACT_JSON = (
    '{"doc_type_confidence":1.0,"account_ref":"Amex","account_number":"1234",'
    '"institution":"Amex","account_names":["Jane"],'
    '"opening":{"amount_raw":"$200.00","date_raw":"2026-01-01","page":1},'
    '"closing":{"amount_raw":"$650.00","date_raw":"2026-01-31","page":1},'
    '"transactions":[{"date_raw":"2026-01-05","description":"Buy",'
    '"amount_raw":"500.00","balance_effect":"increase"},'
    '{"date_raw":"2026-01-20","description":"Payment",'
    '"amount_raw":"50.00","balance_effect":"decrease"}]}')


def test_extract_phase_stamps_the_composite_prompt_version():
    rr = read_with_retry(lambda p: _result(_EXTRACT_JSON), "PROMPT", "doc",
                         "en-US", "USD", prompt_version="extract:base-v1+card-v1")
    assert rr.facts is not None and rr.error is None
    assert len(rr.phases) == 1
    assert rr.phases[0].phase == "extract"
    assert rr.phases[0].prompt_version == "extract:base-v1+card-v1"


# --- pipeline: both phases land in the claims layer -------------------------

def _reads(rr):
    def rf(data, doc_id):
        if rr.facts is not None:
            rr.facts.doc_id = doc_id
        return rr
    return rf


def _stores(tmp_path):
    return (RawStore.open(tmp_path / "raw", "pw"),
            Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")))


def _read_recordeds(ledger):
    return [e for e in ledger.events() if e.event_type == "ReadRecorded"]


def test_two_phase_read_records_both_claims(tmp_path):
    from viva.ingest import StatementFacts, TxnFact
    raw, ledger = _stores(tmp_path)
    facts = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.97,
        account_ref="Amex 1234", currency="USD",
        opening_amount=Decimal("200.00"), opening_date="2026-01-01",
        closing_amount=Decimal("650.00"), closing_date="2026-01-31",
        transactions=[TxnFact("2026-01-05", "Buy", Decimal("500.00")),
                      TxnFact("2026-01-20", "Payment", Decimal("-50.00"))])
    rr = ReadResult(
        doc_type="credit_card_statement", doc_type_confidence=0.97, facts=facts,
        phases=[ModelPhase("classify", "configured-route", "classify-v1",
                          "{...}", 0.001, resolved_model="provider-classifier"),
                ModelPhase("extract", "configured-route",
                           "extract:base-v1+card-v1", _EXTRACT_JSON, 0.02,
                           resolved_model="provider-extractor")])
    res = capture_and_ingest(raw, ledger, b"card.pdf", _reads(rr),
                             captured_at="2026-02-01")
    assert res.action == POSTED
    phases = sorted(e.body["phase"] for e in _read_recordeds(ledger))
    assert phases == ["classify", "extract"]      # nothing thrown away
    calls = _read_recordeds(ledger)
    assert {e.body["model"] for e in calls} == {"configured-route"}
    assert {e.body["resolved_model"] for e in calls} == {
        "provider-classifier", "provider-extractor"}


def test_each_extract_retry_becomes_its_own_outbound_event(tmp_path):
    raw, ledger = _stores(tmp_path)
    replies = iter([_result("{broken json"), _result(_EXTRACT_JSON)])
    rr = read_with_retry(lambda prompt: next(replies), "PROMPT", "temporary",
                         "en-US", "USD", prompt_version="extract:base-v1",
                         configured_model="configured-route")
    rr.doc_type = "credit_card_statement"
    rr.facts.doc_type = "credit_card_statement"

    result = capture_and_ingest(raw, ledger, b"card-with-retry.pdf", _reads(rr),
                                captured_at="2026-02-01")

    assert result.action == POSTED
    calls = _read_recordeds(ledger)
    assert len(calls) == 2
    assert [event.body["parse_ok"] for event in calls] == [False, True]
    assert {event.body["model"] for event in calls} == {"configured-route"}
    assert sum(event.body["input_tokens"] for event in calls) == 10
    assert sum(event.body["output_tokens"] for event in calls) == 10


def test_unsupported_type_records_only_the_cheap_classify(tmp_path):
    # A pay stub is classified cheaply and parked — no expensive extract claim.
    raw, ledger = _stores(tmp_path)
    rr = ReadResult(
        doc_type="pay_stub", doc_type_confidence=0.9, facts=None,
        error="no projector yet for 'pay_stub'",
        phases=[ModelPhase("classify", "m", "classify-v1", "{...}", 0.001)])
    res = capture_and_ingest(raw, ledger, b"paystub.pdf", _reads(rr),
                             captured_at="2026-02-01")
    assert res.action == PARKED
    recs = _read_recordeds(ledger)
    assert [e.body["phase"] for e in recs] == ["classify"]
