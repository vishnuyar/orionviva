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
                       request={}, response={"usage": {"prompt_tokens": 10,
                                                        "completion_tokens": 20}})


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
    assert len(rr.phases) == 2                             # both requests durable
    assert [phase.parse_ok for phase in rr.phases] == [False, True]
    assert [phase.cost_usd for phase in rr.phases] == [0.05, 0.05]
    assert rr.input_tokens == 20 and rr.output_tokens == 40
    assert all(phase.usage_reported for phase in rr.phases)


def test_no_retry_when_first_read_is_good():
    calls = []

    def extract(prompt):
        calls.append(prompt)
        return _result(_GOOD)

    rr = read_with_retry(extract, "PROMPT", "doc", "en-US", "USD")
    assert rr.facts is not None and len(calls) == 1        # no wasted retry
    assert len(rr.phases) == 1


def test_gives_up_after_the_retry_and_parks():
    calls = []

    def extract(prompt):
        calls.append(prompt)
        return _result(_BAD)

    rr = read_with_retry(extract, "PROMPT", "doc", "en-US", "USD")
    assert rr.facts is None and rr.error is not None       # honestly failed
    assert len(calls) == 2                                 # tried once + one retry
    assert len(rr.phases) == 2


def test_value_retry_removes_a_summary_heading_instead_of_keeping_empty_date():
    heading = ('{"doc_type":"credit_card_statement","doc_type_confidence":1.0,'
               '"account_ref":"Card","opening":{"amount_raw":"100.00",'
               '"date_raw":"2026-01-01","page":1},"closing":'
               '{"amount_raw":"80.00","date_raw":"2026-01-31","page":1},'
               '"transactions":[{"date_raw":"","description":"Payments",'
               '"amount_raw":"20.00","balance_effect":"decrease"},'
               '{"date_raw":"2026-01-10","description":"PAYMENT",'
               '"amount_raw":"20.00","balance_effect":"decrease"}]}')
    corrected = heading.replace(
        '{"date_raw":"","description":"Payments","amount_raw":"20.00",'
        '"balance_effect":"decrease"},', "")
    calls = []

    def extract(prompt):
        calls.append(prompt)
        return _result(heading if len(calls) == 1 else corrected)

    rr = read_with_retry(extract, "PROMPT", "doc", "en-US", "USD")

    assert rr.facts is not None and len(rr.facts.transactions) == 1
    assert rr.facts.transactions[0].description == "PAYMENT"
    assert "remove that whole object" in calls[1]
    assert "empty string for a required" in calls[1]
    assert "transaction date or amount" in calls[1]
