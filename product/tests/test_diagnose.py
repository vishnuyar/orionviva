"""Deterministic diagnosis: forced corrections, suggestions, and honest silence."""

from decimal import Decimal

from viva.ingest import FORCED, SUGGESTED, UNLOCALIZED, StatementFacts, TxnFact
from viva.ingest.diagnose import diagnose


def _facts(opening, rows, closing):
    """rows: (description, amount, running_balance_or_None)."""
    txns = [TxnFact(date="2026-01-05", description=desc, amount=Decimal(a),
                    running_balance=(Decimal(rb) if rb is not None else None))
            for desc, a, rb in rows]
    return StatementFacts(
        doc_id="d", doc_type="checking_statement", doc_type_confidence=0.9,
        account_ref="ref", currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-01-01",
        closing_amount=Decimal(closing), closing_date="2026-01-31",
        transactions=txns)


def test_clean_statement_reconciles():
    f = _facts("1000.00", [("Pay", "500.00", "1500.00"),
                           ("Coffee", "-42.42", "1457.58")], "1457.58")
    d = diagnose(f)
    assert d.reconciles and d.status == "none"


def test_forced_amount_misread_from_running_balance():
    # Coffee misread as -42.33, but its running balance (1457.58) is right.
    f = _facts("1000.00", [("Pay", "500.00", "1500.00"),
                           ("Coffee", "-42.33", "1457.58")], "1457.58")
    d = diagnose(f)
    assert d.status == FORCED and d.kind == "amount_misread"
    assert d.target_index == 1
    assert d.observed == "-42.33" and d.implied == "-42.42"


def test_forced_closing_misread_when_chain_is_consistent():
    # Every line and its running balance agree; only the closing figure is off.
    f = _facts("1000.00", [("Pay", "500.00", "1500.00"),
                           ("Coffee", "-42.42", "1457.58")], "1457.50")
    d = diagnose(f)
    assert d.status == FORCED and d.kind == "balance_misread"
    assert d.implied == "1457.58" and d.observed == "1457.50"


def test_suggested_missing_or_extra_line():
    # No running balances; the gap equals one line's amount.
    f = _facts("1000.00", [("Pay", "500.00", None),
                           ("Rent", "-100.00", None)], "1500.00")
    d = diagnose(f)
    assert d.status == SUGGESTED and d.kind == "missing_or_extra"
    assert d.target_index == 1


def test_suggested_transposition_multiple_of_nine():
    f = _facts("1000.00", [("Pay", "500.00", None)], "1500.09")
    d = diagnose(f)
    assert d.status == SUGGESTED and d.kind == "transposition"


def test_unlocalized_when_no_clean_explanation():
    f = _facts("1000.00", [("Pay", "500.00", None)], "1507.00")
    d = diagnose(f)
    assert d.status == UNLOCALIZED


def test_multiple_broken_rows_is_not_forced():
    # Two lines disagree with their running balances -> cannot cleanly force.
    f = _facts("1000.00", [("A", "-10.00", "985.00"),   # implies -15
                           ("B", "-20.00", "955.00")], "955.00")  # implies -30
    d = diagnose(f)
    assert d.status != FORCED
