"""Current-period control is bounded projected cash, never spend permission."""

from decimal import Decimal

import pytest

from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, simple_transaction)
from viva.ledger.events import ASSERTED, CORROBORATED, merchant_enriched


def _projection(*, currency="USD", balance="1000.00", today="2026-05-01"):
    events = [
        account_opened("checking", "depository", "Checking", currency,
                       "2026-01-01"),
    ]
    for month in range(1, 5):
        events.extend((
            simple_transaction("checking", "2000.00", "ACME PAYROLL",
                               f"2026-{month:02d}-15", kind="depository"),
            simple_transaction("checking", "-100.00", "NORTHBANK LOAN",
                               f"2026-{month:02d}-05", kind="depository"),
        ))
    events.extend((
        merchant_enriched(
            "acme payroll", "income", occurred_at="2026-04-16",
            grade=CORROBORATED,
            attributes={"counterparty_kind": "business",
                        "billing": "standing", "billing_period": "monthly"}),
        merchant_enriched(
            "northbank loan", "debt", occurred_at="2026-04-16",
            grade=CORROBORATED,
            attributes={"counterparty_kind": "business",
                        "billing": "standing", "billing_period": "monthly"}),
    ))
    events.append(closing_balance_observed(
        "checking", balance, today,
        Provenance("checking-current", 1, "closing-box")))
    return LedgerProjection(events)


def test_projected_remainder_is_a_range_over_qualified_recurring_money():
    (row,) = _projection().current_period("2026-05-01").slices

    assert row.horizon_start == "2026-05-01"
    assert row.horizon_end == "2026-05-31"
    assert row.liquid_balance == Decimal("1000.00")
    assert row.expected_income_min == Decimal("0")
    assert row.expected_income_max == Decimal("2000.00")
    assert row.obligations_min == row.obligations_max == Decimal("100.00")
    assert row.remainder_min == Decimal("900.00")
    assert row.remainder_max == Decimal("2900.00")
    assert [step.kind for step in row.steps] == [
        "balance", "obligation", "income"]
    assert row.missing_inputs == ("planned_spending", "goal_contributions")
    assert row.evidence_dates == (
        "2026-01-05", "2026-01-15", "2026-02-15", "2026-03-15",
        "2026-04-05", "2026-04-15", "2026-05-01")
    assert row.completeness.planned_spending is False
    assert row.completeness.goals is False


def test_expected_income_never_enters_the_lower_bound_before_it_arrives():
    row = _projection(balance="50.00").current_period("2026-05-01").slices[0]

    assert row.remainder_min == Decimal("-50.00")
    assert row.remainder_max == Decimal("1950.00")


def test_prior_only_obligations_are_context_not_arithmetic():
    events = [
        account_opened("checking", "depository", "Checking", "USD",
                       "2026-01-01"),
        simple_transaction("checking", "-25", "LUMEN STREAMING",
                           "2026-01-05", kind="depository"),
        simple_transaction("checking", "-25", "LUMEN STREAMING",
                           "2026-02-05", kind="depository"),
        merchant_enriched(
            "lumen streaming", "services", occurred_at="2026-02-06",
            grade=CORROBORATED,
            attributes={"counterparty_kind": "business",
                        "billing": "standing", "billing_period": "monthly"}),
        closing_balance_observed("checking", "100", "2026-03-01"),
    ]

    row = LedgerProjection(events).current_period("2026-03-01").slices[0]

    assert row.obligations_max == Decimal("0")
    assert row.remainder_min == row.remainder_max == Decimal("100")


def test_missed_income_is_not_optimistically_rolled_forward():
    result = _projection(today="2026-07-10").current_period("2026-07-10")

    row = result.slices[0]
    assert row.expected_income_max == Decimal("0")
    assert all(step.kind != "income" for step in row.steps)
    assert "income_interrupted" in row.caveats
    assert any(item.reason == "incoming_interrupted"
               for item in row.exclusions)


def test_a_still_adequate_past_due_obligation_lands_on_the_starting_day():
    row = _projection(today="2026-05-20").current_period("2026-05-20").slices[0]

    assert [step.date for step in row.steps] == ["2026-05-20", "2026-05-20"]
    assert row.steps[1].kind == "obligation"


def test_currencies_remain_independent_slices_without_a_grand_total():
    events = [
        account_opened("usd", "depository", "US", "USD", "2026-01-01"),
        closing_balance_observed("usd", "100", "2026-05-01"),
        account_opened("eur", "depository", "EU", "EUR", "2026-01-01"),
        closing_balance_observed("eur", "200", "2026-05-01"),
    ]

    result = LedgerProjection(events).current_period("2026-05-01")

    assert [(row.currency, row.liquid_balance) for row in result.slices] == [
        ("EUR", Decimal("200")), ("USD", Decimal("100"))]


def test_only_issuer_depository_balances_enter_liquid_funds():
    events = [
        account_opened("asserted", "depository", "Cash", "USD",
                       "2026-01-01", origin=ASSERTED),
        closing_balance_observed("asserted", "500", "2026-05-01"),
        account_opened("brokerage", "investment", "Brokerage", "USD",
                       "2026-01-01"),
        closing_balance_observed("brokerage", "900", "2026-05-01"),
    ]

    result = LedgerProjection(events).current_period("2026-05-01")

    assert result.refused
    assert result.refusal_reason == "no_eligible_liquid_balance"
    assert result.excluded_accounts == ("asserted", "brokerage")
    assert [(item.identity, item.reason) for item in result.exclusions] == [
        ("asserted", "account_not_issuer"),
        ("brokerage", "account_not_depository"),
    ]


def test_old_and_undated_balances_weaken_without_an_invented_expiry():
    old = _projection(today="2026-04-30").current_period("2026-05-01").slices[0]
    events = [account_opened("cash", "depository", "Cash", "USD",
                             "2026-01-01")]
    undated = LedgerProjection(events).current_period("2026-05-01").slices[0]

    assert "balance_freshness_unconfirmed" in old.caveats
    assert "balance_undated" in undated.caveats


@pytest.mark.parametrize("days", [0, 367, True])
def test_horizon_is_bounded(days):
    with pytest.raises(ValueError, match="1 to 366"):
        _projection().current_period("2026-05-01", days)
