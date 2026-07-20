"""Tests for verify.normalize — product-embryo standard.

Every invariant claim the docs make about normalization is a test here.
If a rule isn't tested, it doesn't exist.
"""

from decimal import Decimal

import pytest

from vivabench.verify.normalize import parse_amount, parse_date


# ---------------------------------------------------------------- amounts: US


def test_us_plain():
    assert parse_amount("1,234.56", "en-US").decimal() == Decimal("1234.56")

def test_us_with_dollar():
    r = parse_amount("$1,234.56", "en-US")
    assert r.decimal() == Decimal("1234.56")
    assert r.currency == "USD"

def test_us_millions_grouping():
    assert parse_amount("12,345,678.90", "en-US").decimal() == Decimal("12345678.90")

def test_negative_parentheses():
    r = parse_amount("(45.00)", "en-US")
    assert r.decimal() == Decimal("-45.00")
    assert any("parentheses" in a for a in r.assumptions)

def test_negative_trailing_minus():
    assert parse_amount("45.00-", "en-US").decimal() == Decimal("-45.00")

def test_negative_leading_minus():
    assert parse_amount("-45.00", "en-US").decimal() == Decimal("-45.00")

def test_dr_suffix_is_negative():
    r = parse_amount("500.00 DR", "en-IN")
    assert r.decimal() == Decimal("-500.00")

def test_cr_suffix_is_positive():
    assert parse_amount("500.00 CR", "en-IN").decimal() == Decimal("500.00")


# ------------------------------------------------------------ amounts: Europe


def test_german_comma_decimal():
    assert parse_amount("1.234,56", "de-DE").decimal() == Decimal("1234.56")

def test_german_grouping_only():
    # "1.234" in a German document is one thousand two hundred thirty-four.
    assert parse_amount("1.234", "de-DE").decimal() == Decimal("1234")

def test_french_with_euro():
    r = parse_amount("€1.234,56", "fr-FR")
    assert r.decimal() == Decimal("1234.56")
    assert r.currency == "EUR"

def test_swiss_apostrophe_grouping():
    assert parse_amount("1'234'567.89", "de-CH").decimal() == Decimal("1234567.89")


# ------------------------------------------------------- amounts: India/Japan


def test_indian_lakh_grouping():
    # 12,34,567.89 — grouping by lakh/crore must parse without special-casing.
    assert parse_amount("12,34,567.89", "en-IN").decimal() == Decimal("1234567.89")

def test_indian_rupee_symbol():
    r = parse_amount("₹1,00,000", "en-IN")
    assert r.decimal() == Decimal("100000")
    assert r.currency == "INR"

def test_japanese_yen():
    r = parse_amount("¥1,234,567", "ja-JP")
    assert r.decimal() == Decimal("1234567")
    assert r.currency == "JPY"


# ----------------------------------------------------- amounts: honesty rules


def test_ambiguous_without_locale_is_ambiguous_not_guessed():
    # THE core honesty test: "1.234" with no locale could be 1.234 or 1234.
    r = parse_amount("1.234", None)
    assert r.status == "ambiguous"
    assert r.value is None

def test_same_string_resolves_differently_by_locale():
    assert parse_amount("1.234", "de-DE").decimal() == Decimal("1234")
    assert parse_amount("1.234", "en-US").decimal() == Decimal("1.234")

def test_currency_conflict_is_invalid_not_silently_resolved():
    r = parse_amount("€100.00", "en-US", currency="USD")
    assert r.status == "invalid"
    assert "conflict" in (r.reason or "")

def test_document_currency_flows_through():
    r = parse_amount("100.00", "en-US", currency="usd")
    assert r.currency == "USD"

def test_garbage_is_invalid():
    assert parse_amount("N/A", "en-US").status == "invalid"

def test_empty_is_invalid():
    assert parse_amount("  ", "en-US").status == "invalid"

def test_assumptions_are_recorded():
    r = parse_amount("(1.234,56)", "de-DE")
    assert r.decimal() == Decimal("-1234.56")
    assert len(r.assumptions) >= 2  # parentheses + separator reasoning

def test_no_floats_anywhere():
    # Classic float trap: 0.1 + 0.2. Decimal must make this exact.
    a = parse_amount("0.10", "en-US").decimal()
    b = parse_amount("0.20", "en-US").decimal()
    assert a + b == Decimal("0.30")


# ------------------------------------------------------------------- dates


def test_iso_date():
    assert parse_date("2026-07-04").value == "2026-07-04"

def test_us_numeric_date():
    assert parse_date("03/04/2025", "en-US").value == "2025-03-04"

def test_european_numeric_date():
    assert parse_date("03/04/2025", "de-DE").value == "2025-04-03"

def test_the_trap_without_locale_is_ambiguous():
    # The load-bearing honesty test for dates.
    r = parse_date("03/04/2025", None)
    assert r.status == "ambiguous"

def test_unambiguous_day_over_12():
    # 13 can't be a month: locale not needed.
    assert parse_date("13/04/2025", None).value == "2025-04-13"
    assert parse_date("04/13/2025", None).value == "2025-04-13"

def test_same_day_month_needs_no_locale():
    assert parse_date("3/3/2026", None).value == "2026-03-03"

def test_month_name_forms():
    assert parse_date("Jan 5, 2026").value == "2026-01-05"
    assert parse_date("5 Jan 2026").value == "2026-01-05"
    assert parse_date("05-Jan-2026").value == "2026-01-05"
    assert parse_date("September 30, 2025").value == "2025-09-30"

def test_two_digit_year():
    r = parse_date("03/04/25", "en-US")
    assert r.value == "2025-03-04"
    assert any("two-digit year" in a for a in r.assumptions)

def test_invalid_dates_rejected():
    assert parse_date("02/30/2026", "en-US").status == "invalid"
    assert parse_date("31/04/2025", "de-DE").status == "invalid"
    assert parse_date("29/02/2025", "de-DE").status == "invalid"  # not a leap year

def test_leap_year_accepted():
    assert parse_date("29/02/2028", "de-DE").value == "2028-02-29"

def test_assumption_recorded_for_locale_resolution():
    r = parse_date("03/04/2025", "en-US")
    assert any("month-first" in a for a in r.assumptions)
