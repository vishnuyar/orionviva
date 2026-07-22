"""StatementFacts parsing: signs, normalization, and refusal on ambiguity."""

import json
from decimal import Decimal

from viva.ingest import from_model_json


def _stmt(txns, opening="$1,000.00", closing="$1,457.58"):
    return json.dumps({
        "doc_type": "checking_statement",
        "doc_type_confidence": 0.97,
        "account_ref": "Chase Total Checking ...1234",
        "opening": {"amount_raw": opening, "date_raw": "01/01/2026", "page": 1},
        "closing": {"amount_raw": closing, "date_raw": "01/31/2026", "page": 6},
        "transactions": txns,
    })


def test_parses_and_signs_by_direction():
    out = _stmt([
        {"date_raw": "01/10/2026", "description": "Payroll", "amount_raw": "$500.00", "direction": "credit", "page": 2},
        {"date_raw": "01/15/2026", "description": "Coffee", "amount_raw": "$42.42", "direction": "debit", "page": 3},
    ])
    facts, err = from_model_json(out, "doc1", "en-US", "USD")
    assert err is None
    assert facts.opening_amount == Decimal("1000.00")
    assert facts.closing_amount == Decimal("1457.58")
    assert facts.transactions[0].amount == Decimal("500.00")     # credit -> +
    assert facts.transactions[1].amount == Decimal("-42.42")     # debit  -> -
    assert facts.transactions[0].date == "2026-01-10"            # ISO normalized


def test_tolerates_fences_and_prose():
    out = "Sure:\n```json\n" + _stmt([]) + "\n```\nDone."
    facts, err = from_model_json(out, "doc1", "en-US", "USD")
    assert err is None and facts.currency == "USD"


def test_bad_direction_refused():
    out = _stmt([{"date_raw": "01/10/2026", "description": "x",
                  "amount_raw": "$5.00", "direction": "sideways", "page": 2}])
    facts, err = from_model_json(out, "doc1", "en-US", "USD")
    assert facts is None and "direction" in err


def test_unreadable_amount_refused_not_guessed():
    facts, err = from_model_json(_stmt([], opening="not-a-number"),
                                 "doc1", "en-US", "USD")
    assert facts is None and "opening" in err


def test_invalid_date_refused():
    out = _stmt([{"date_raw": "13/45/2026", "description": "x",
                  "amount_raw": "$5.00", "direction": "debit", "page": 2}])
    facts, err = from_model_json(out, "doc1", "en-US", "USD")
    assert facts is None and "date" in err


def test_missing_sections_refused():
    facts, err = from_model_json(json.dumps({"doc_type": "checking_statement"}),
                                 "doc1", "en-US", "USD")
    assert facts is None and "opening" in err


def test_no_json_refused():
    facts, err = from_model_json("I could not read this", "doc1", "en-US", "USD")
    assert facts is None and "no JSON" in err
