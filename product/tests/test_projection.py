"""The running-balance projection and its honest grade ladder."""

from decimal import Decimal

import pytest

from viva.ledger import (BalanceAnswer, LedgerProjection, Provenance,
                         UnknownAccountError, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction, split_transaction)
from viva.ledger.events import (CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED)


def _statement(closing="1457.58", extra=None):
    """A tiny checking statement: open 1000, +500 pay, -42.42 coffee => 1457.58."""
    evs = [
        account_opened("chk", "depository", "Checking", "USD", "2026-01-01"),
        opening_balance_observed("chk", "1000.00", "2026-01-01",
                                 Provenance("chase-jan", 1, "opening-box")),
        simple_transaction("chk", "500.00", "paycheck", "2026-01-10"),
        simple_transaction("chk", "-42.42", "coffee", "2026-01-15"),
    ]
    if extra:
        evs.extend(extra)
    if closing is not None:
        evs.append(closing_balance_observed(
            "chk", closing, "2026-01-31", Provenance("chase-jan", 6, "closing-box")))
    return evs


def test_running_balance_is_correct():
    proj = LedgerProjection(_statement())
    assert proj.balance("chk").amount == Decimal("1457.58")


def test_reconciled_statement_is_corroborated():
    ans = LedgerProjection(_statement()).balance("chk")
    assert ans.grade == CORROBORATED
    assert ans.reconciliation is not None and ans.reconciliation.passed
    assert ans.provenance.doc_id == "chase-jan" and ans.provenance.page == 6


def test_wrong_closing_is_conflicted_not_hidden():
    ans = LedgerProjection(_statement(closing="9999.99")).balance("chk")
    assert ans.grade == CONFLICTED
    assert not ans.reconciliation.passed
    # It still reports the attested figure and says the two disagree.
    assert ans.amount == Decimal("9999.99")
    assert "disagree" in ans.explanation


def test_no_closing_is_unverified():
    ans = LedgerProjection(_statement(closing=None)).balance("chk")
    assert ans.grade == UNVERIFIED
    assert ans.amount == Decimal("1457.58")   # still the replayed sum
    assert ans.reconciliation is None


def test_lone_snapshot_is_verified():
    evs = [
        account_opened("chk", "depository", "Checking", "USD", "2026-01-01"),
        closing_balance_observed("chk", "1457.58", "2026-01-31",
                                 Provenance("chase-jan", 6, "closing-box")),
    ]
    ans = LedgerProjection(evs).balance("chk")
    assert ans.grade == VERIFIED and ans.amount == Decimal("1457.58")


def test_unknown_account_refuses():
    with pytest.raises(UnknownAccountError):
        LedgerProjection(_statement()).balance("savings")


def test_split_transaction_reflected_in_balance():
    extra = [split_transaction(
        "chk", "-100.00",
        [("Expenses:Groceries", "70.00"), ("Expenses:Gifts", "30.00")],
        "walmart", "2026-01-20")]
    # closing now 1000 + 500 - 42.42 - 100 = 1357.58
    ans = LedgerProjection(_statement(closing="1357.58", extra=extra)).balance("chk")
    assert ans.grade == CORROBORATED and ans.amount == Decimal("1357.58")


def test_as_of_excludes_future_events():
    # As of Jan 12, only the paycheck has landed: 1000 + 500 = 1500, no closing.
    proj = LedgerProjection(_statement(), as_of="2026-01-12")
    ans = proj.balance("chk")
    assert ans.amount == Decimal("1500.00")
    assert ans.grade == UNVERIFIED       # closing is in the excluded future


def test_accounts_listing():
    proj = LedgerProjection(_statement())
    assert "chk" in proj.accounts()
