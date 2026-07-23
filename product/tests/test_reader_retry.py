"""The reader's parse-retry — recovers a bad-JSON read without touching the net."""

from viva.ingest.reader import read_with_retry
from vivacore.models.base import ModelResult

_GOOD = ('{"doc_type":"checking_statement","doc_type_confidence":1.0,'
         '"account_ref":"Acme","account_number":"1234","institution":"Acme",'
         '"account_names":["Jane"],'
         '"opening":{"amount_raw":"$100.00","date_raw":"2026-01-01","page":1},'
         '"closing":{"amount_raw":"$150.00","date_raw":"2026-01-31","page":1},'
         '"transactions":[{"date_raw":"2026-01-10","description":"Dep",'
         '"amount_raw":"50.00","direction":"credit"}]}')

_BAD = '{"doc_type": "checking_statement" this is broken json}'


def _result(text, cost=0.05):
    return ModelResult(text=text, resolved_model="m", input_tokens=10,
                       output_tokens=20, cost_usd=cost, latency_s=0.1,
                       request={}, response={})


def test_retry_recovers_bad_json():
    calls = []

    def extract(prompt):
        calls.append(prompt)
        return _result(_BAD) if len(calls) == 1 else _result(_GOOD)

    rr = read_with_retry(extract, "PROMPT", "doc", "en-US", "USD")
    assert rr.facts is not None and rr.error is None      # recovered
    assert len(calls) == 2                                 # re-asked once
    assert "not valid JSON" in calls[1].lower() or "NOT valid JSON" in calls[1]
    assert abs(rr.cost_usd - 0.10) < 1e-9                  # both calls charged


def test_no_retry_when_first_read_is_good():
    calls = []

    def extract(prompt):
        calls.append(prompt)
        return _result(_GOOD)

    rr = read_with_retry(extract, "PROMPT", "doc", "en-US", "USD")
    assert rr.facts is not None and len(calls) == 1        # no wasted retry


def test_gives_up_after_the_retry_and_parks():
    calls = []

    def extract(prompt):
        calls.append(prompt)
        return _result(_BAD)

    rr = read_with_retry(extract, "PROMPT", "doc", "en-US", "USD")
    assert rr.facts is None and rr.error is not None       # honestly failed
    assert len(calls) == 2                                 # tried once + one retry
