"""Tests for verify.arithmetic — the document self-checks."""

from decimal import Decimal

import pytest

from vivacore.verify.arithmetic import (check_balance_identity,
                                        check_brokerage_identity, check_sum)


def test_brokerage_identity_passes():
    # Σ position market values + cash = total account value.
    r = check_brokerage_identity(
        position_values=["18400.00", "6600.00"], cash="1000.00", total="26000.00")
    assert r.passed, r.explain()


def test_brokerage_identity_catches_a_misread_holding():
    r = check_brokerage_identity(
        position_values=["18400.00", "5600.00"], cash="1000.00", total="26000.00")
    assert not r.passed
    assert r.delta == "1000.00"


def test_brokerage_identity_positions_only_no_cash():
    r = check_brokerage_identity(
        position_values=["1600.00"], cash="0", total="1600.00")
    assert r.passed, r.explain()


def test_balance_identity_passes():
    r = check_balance_identity(
        opening="1000.00",
        transactions=["-45.67", "-12.00", "2500.00", "-899.99"],
        closing="2542.34",
    )
    assert r.passed, r.explain()


def test_balance_identity_catches_one_cent():
    # A single cent off fails; there is no implicit tolerance.
    r = check_balance_identity(
        opening="1000.00",
        transactions=["-45.67", "-12.00", "2500.00", "-899.99"],
        closing="2542.35",
    )
    assert not r.passed
    assert r.delta == "0.01"


def test_float_poison_rejected():
    with pytest.raises(TypeError):
        check_balance_identity(opening=1000.0, transactions=["1.00"], closing="1001.00")


def test_no_float_drift():
    # 0.1 added ten times equals exactly 1.0 under Decimal.
    r = check_sum(items=["0.1"] * 10, total="1.0")
    assert r.passed, r.explain()


def test_check_sum_passes_and_fails():
    assert check_sum(["10.00", "20.00", "30.00"], "60.00").passed
    assert not check_sum(["10.00", "20.00", "30.00"], "60.01").passed


def test_empty_transactions_means_opening_equals_closing():
    assert check_balance_identity("500.00", [], "500.00").passed
    assert not check_balance_identity("500.00", [], "500.01").passed


def test_explicit_tolerance_is_honored_but_never_default():
    r = check_sum(["33.33", "33.33", "33.33"], "100.00", tolerance="0.01")
    assert r.passed
    r2 = check_sum(["33.33", "33.33", "33.33"], "100.00")
    assert not r2.passed  # default is exact


def test_explain_is_human_readable():
    r = check_sum(["1.00"], "2.00")
    text = r.explain()
    assert "FAIL" in text and "expected 1.00" in text and "got 2.00" in text


def test_negative_transactions_and_negative_balances():
    r = check_balance_identity(
        opening="-250.00",
        transactions=["-100.00", "50.00"],
        closing="-300.00",
    )
    assert r.passed, r.explain()
