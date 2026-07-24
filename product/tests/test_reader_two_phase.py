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
                       request={}, response={})


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
    doc_type, conf, phase = classify(adapter, _pages(5), "embedded text")
    assert doc_type == "credit_card_statement" and conf == 0.97
    assert adapter.image_counts == [1]            # cheap: one image, not all five
    assert phase.phase == "classify" and phase.prompt_version == "classify-v1"
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
        phases=[ModelPhase("classify", "m", "classify-v1", "{...}", 0.001),
                ModelPhase("extract", "m", "extract:base-v1+card-v1", _EXTRACT_JSON, 0.02)])
    res = capture_and_ingest(raw, ledger, b"card.pdf", _reads(rr),
                             captured_at="2026-02-01")
    assert res.action == POSTED
    phases = sorted(e.body["phase"] for e in _read_recordeds(ledger))
    assert phases == ["classify", "extract"]      # nothing thrown away


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
