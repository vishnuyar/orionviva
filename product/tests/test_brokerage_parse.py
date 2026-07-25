"""The three failures the first real Stage-2 brokerage statement produced.

Each is a red test written from the actual log: an optional field's junk value
killed a whole read; a year-less activity date was rejected outright; and the
retry told the model its JSON was invalid when the JSON was fine.
"""

import json

from decimal import Decimal

from viva.ingest.brokerage import from_brokerage_json
from viva.ingest.reader import _is_syntax_error
from viva.ingest.statement import period_date


def _doc(**over):
    """A minimal well-formed brokerage read; override any field per test."""
    base = {
        "doc_type_confidence": 1.0, "account_number": "000000009999",
        "institution": "Fidelity", "account_ref": "Individual",
        "as_of_raw": "11/30/2024", "cash_raw": "1000.00", "total_raw": "3000.00",
        "positions": [{"instrument": "SPXS", "units_raw": "100",
                       "market_value_raw": "2000.00", "cost_basis_raw": ""}],
    }
    base.update(over)
    return json.dumps(base)


# --- 1. an optional field's junk value must not kill the read ----------------

def test_unreadable_cost_basis_is_unknown_not_fatal():
    """The real failure: cost_basis 'not applicable' lost the whole statement."""
    text = _doc(positions=[{"instrument": "SPXS", "units_raw": "100",
                            "market_value_raw": "2000.00",
                            "cost_basis_raw": "not applicable"}])
    facts, err = from_brokerage_json(text, "doc1", "en-US", "USD")
    assert err is None                              # the document still reads
    assert facts.positions[0].cost_basis is None    # unknown, not invented
    assert facts.positions[0].market_value == Decimal("2000.00")


def test_unreadable_realized_gain_is_unknown_not_fatal():
    text = _doc(opening_cash_raw="0.00",
                activity=[{"date_raw": "11/04", "kind": "sell",
                           "amount_raw": "1000.00", "realized_gain_raw": "N/A"}])
    facts, err = from_brokerage_json(text, "doc1", "en-US", "USD")
    assert err is None
    assert facts.activity[0].realized_gain is None


def test_an_identity_bearing_figure_is_still_fatal():
    """Tolerance is only for OPTIONAL fields — a load-bearing figure we cannot
    read still sends the document to review rather than guessing."""
    text = _doc(positions=[{"instrument": "SPXS", "units_raw": "100",
                            "market_value_raw": "not applicable"}])
    facts, err = from_brokerage_json(text, "doc1", "en-US", "USD")
    assert facts is None and "market_value" in err


# --- 2. year-less dates resolve against the statement period -----------------

def test_year_less_activity_date_resolves_against_the_period():
    """'11/04' on a statement dated 30 Nov 2024 is 4 Nov 2024."""
    text = _doc(opening_cash_raw="0.00",
                activity=[{"date_raw": "11/04", "kind": "contribution",
                           "amount_raw": "1000.00"}])
    facts, err = from_brokerage_json(text, "doc1", "en-US", "USD")
    assert err is None
    assert facts.activity[0].date == "2024-11-04"


def test_period_date_handles_the_year_boundary():
    # A statement dated 15 Jan 2025: a "12/28" line belongs to the PREVIOUS year.
    assert period_date("12/28", "en-US", "2025-01-15") == ("2024-12-28", None)
    # ...while a line inside the period keeps the period's year.
    assert period_date("01/05", "en-US", "2025-01-15") == ("2025-01-05", None)


def test_period_date_never_invents_a_year_without_a_period():
    value, err = period_date("11/04", "en-US", "")
    assert value is None and "no statement period" in err


def test_a_full_date_is_respected_over_the_period():
    assert period_date("03/04/2023", "en-US", "2025-01-15") == ("2023-03-04", None)


# --- 3. the retry must describe the ACTUAL failure ---------------------------

def test_syntax_and_value_failures_are_told_apart():
    assert _is_syntax_error("JSON did not parse: Expecting ',' delimiter")
    assert _is_syntax_error("no JSON object found in model output")
    # The real one: valid JSON, one unreadable value — NOT a syntax error.
    assert not _is_syntax_error(
        "position 0 cost_basis amount 'not applicable': invalid")
    assert not _is_syntax_error("activity 0 date '11/04': invalid")
