"""Double-entry posting shapes: balance law, splits, grades, no floats."""

from decimal import Decimal

import pytest

from viva.ledger import (EXPENSE_UNCATEGORIZED, INCOME_UNCATEGORIZED, Posting,
                         postings_of, simple_transaction, split_transaction,
                         transaction_balances)
from viva.ledger.events import UNVERIFIED, VERIFIED


def test_posting_rejects_float():
    with pytest.raises(TypeError):
        Posting("chk", 42.42)


def test_posting_coerces_str_to_decimal():
    p = Posting("chk", "42.42")
    assert p.amount == Decimal("42.42")


def test_posting_rejects_unknown_grade():
    with pytest.raises(ValueError):
        Posting("chk", "1", grade="pretty-sure")


def test_withdrawal_balances_and_grades():
    ev = simple_transaction("chk", "-42.42", "coffee", "2026-01-05")
    postings = postings_of(ev)
    assert transaction_balances(postings).passed
    chk = next(p for p in postings if p.account == "chk")
    counter = next(p for p in postings if p.account == EXPENSE_UNCATEGORIZED)
    assert chk.amount == Decimal("-42.42") and chk.grade == VERIFIED
    assert counter.amount == Decimal("42.42") and counter.grade == UNVERIFIED


def test_deposit_goes_to_income():
    ev = simple_transaction("chk", "1500.00", "paycheck", "2026-01-01")
    accounts = {p.account for p in postings_of(ev)}
    assert INCOME_UNCATEGORIZED in accounts


def test_zero_movement_rejected():
    with pytest.raises(ValueError):
        simple_transaction("chk", "0", "nothing", "2026-01-01")


def test_split_balances_and_covers_whole():
    ev = split_transaction(
        "chk", "-100.00",
        [("Expenses:Groceries", "70.00"), ("Expenses:Gifts", "30.00")],
        "walmart run", "2026-01-05",
    )
    postings = postings_of(ev)
    assert transaction_balances(postings).passed
    groceries = next(p for p in postings if p.account == "Expenses:Groceries")
    gifts = next(p for p in postings if p.account == "Expenses:Gifts")
    assert groceries.amount == Decimal("70.00")
    assert gifts.amount == Decimal("30.00")


def test_split_that_does_not_cover_whole_rejected():
    with pytest.raises(ValueError):
        split_transaction(
            "chk", "-100.00",
            [("Expenses:Groceries", "70.00"), ("Expenses:Gifts", "20.00")],
            "short split", "2026-01-05",
        )


def test_split_negative_magnitude_rejected():
    with pytest.raises(ValueError):
        split_transaction("chk", "-100.00", [("Expenses:X", "-50.00")],
                          "bad", "2026-01-05")


def test_tags_ride_along():
    ev = simple_transaction("chk", "-20.00", "cake", "2026-01-05",
                            tags=["groceries", "walmart", "birthday"])
    assert ev.body["tags"] == ["groceries", "walmart", "birthday"]


def test_transaction_balances_catches_imbalance():
    postings = [Posting("chk", "-100.00", VERIFIED),
                Posting("Expenses:X", "90.00", UNVERIFIED)]
    assert not transaction_balances(postings).passed
