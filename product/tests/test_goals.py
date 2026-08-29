"""Save-up goals keep intention, reservation and account evidence separate."""

from decimal import Decimal

import pytest

from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, goal_created,
                         goal_funds_released, goal_funds_reserved,
                         goal_state_changed, goal_terms_changed)
from viva.ledger.events import ASSERTED
from viva.ledger.projection.goals import contribution_dates
from viva.ledger.projection.goals import UnknownGoalError


def _cash(amount="1000.00", *, currency="USD"):
    return [
        account_opened("checking", "depository", "Checking", currency,
                       "2026-01-01"),
        closing_balance_observed(
            "checking", amount, "2026-08-29",
            Provenance("checking-statement", 1, "closing")),
    ]


def test_target_is_not_reserved_money_and_date_solves_monthly_path():
    projection = LedgerProjection([
        *_cash(),
        goal_created("trip", "Trip", "USD", "600", "2026-08-29",
                     target_date="2026-11-15", contribution_day=15),
    ])

    row = projection.goal("trip", "2026-08-29")

    assert row is not None
    assert row.reserved == Decimal("0")
    assert row.remaining == Decimal("600")
    assert row.required_monthly == Decimal("200.00")
    assert row.status == "unscheduled"


def test_reservations_are_account_backed_and_never_change_the_balance():
    projection = LedgerProjection([
        *_cash(),
        goal_created("trip", "Trip", "USD", "600", "2026-08-29",
                     target_date="2026-11-15", monthly_contribution="100",
                     contribution_day=15),
        goal_funds_reserved("trip", "checking", "250", "2026-08-29"),
    ])

    row = projection.goal("trip", "2026-08-29")

    assert row.reserved == Decimal("250")
    assert row.remaining == Decimal("350")
    assert projection.balance("checking").amount == Decimal("1000.00")
    assert row.available_accounts[0].reserved == Decimal("250")
    assert row.available_accounts[0].available == Decimal("750.00")
    assert row.available_accounts[0].grade == "verified"
    assert row.available_accounts[0].provenance.doc_id == "checking-statement"
    assert row.available_accounts[0].explanation


def test_all_goals_share_one_account_availability_without_double_use():
    projection = LedgerProjection([
        *_cash(),
        goal_created("a", "A", "USD", "500", "2026-08-29"),
        goal_created("b", "B", "USD", "500", "2026-08-29"),
        goal_funds_reserved("a", "checking", "300", "2026-08-29"),
        goal_funds_reserved("b", "checking", "200", "2026-08-29"),
    ])

    for row in projection.goals("2026-08-29"):
        assert row.available_accounts[0].reserved == Decimal("500")
        assert row.available_accounts[0].available == Decimal("500.00")


def test_release_compensates_and_history_remains_replayable():
    events = [
        *_cash(),
        goal_created("trip", "Trip", "USD", "600", "2026-08-29"),
        goal_funds_reserved("trip", "checking", "250", "2026-08-29"),
        goal_funds_released("trip", "checking", "50", "used_elsewhere",
                            "2026-08-30"),
    ]

    row = LedgerProjection(events).goal("trip", "2026-08-30")

    assert row.reserved == Decimal("200")
    assert [item.kind for item in row.history] == ["reserved", "released"]
    assert [item.amount for item in row.history] == [Decimal("250"), Decimal("50")]


def test_complete_is_derived_and_a_later_release_reopens_progress():
    base = [
        *_cash(),
        goal_created("trip", "Trip", "USD", "200", "2026-08-29"),
        goal_funds_reserved("trip", "checking", "200", "2026-08-29"),
    ]
    assert LedgerProjection(base).goal("trip", "2026-08-29").status == "complete"

    reopened = LedgerProjection([
        *base,
        goal_funds_released("trip", "checking", "25", "reassigned",
                            "2026-08-30"),
    ]).goal("trip", "2026-08-30")
    assert reopened.status == "unscheduled"
    assert reopened.remaining == Decimal("25")


def test_term_changes_are_complete_snapshots_and_pause_keeps_reservations():
    projection = LedgerProjection([
        *_cash(),
        goal_created("trip", "Trip", "USD", "600", "2026-08-29",
                     monthly_contribution="100", contribution_day=15),
        goal_funds_reserved("trip", "checking", "200", "2026-08-29"),
        goal_terms_changed("trip", "Long trip", "USD", "900", "2026-08-30",
                           target_date="2027-02-15",
                           monthly_contribution="125", contribution_day=15),
        goal_state_changed("trip", "paused", "2026-08-30"),
    ])

    row = projection.goal("trip", "2026-08-30")

    assert row.title == "Long trip"
    assert row.target_amount == Decimal("900")
    assert row.monthly_contribution == Decimal("125")
    assert row.reserved == Decimal("200")
    assert row.status == "paused"


def test_schedule_math_is_calendar_based_and_rounded_up_to_money_scale():
    projection = LedgerProjection([
        *_cash(),
        goal_created("trip", "Trip", "USD", "1000", "2026-08-29",
                     target_date="2026-12-10", monthly_contribution="250",
                     contribution_day=10),
    ])

    row = projection.goal("trip", "2026-08-29")

    assert contribution_dates("2026-08-29", 10, through="2026-12-10") == (
        "2026-09-10", "2026-10-10", "2026-11-10", "2026-12-10")
    assert row.required_monthly == Decimal("250.00")
    assert row.projected_completion_date == "2026-12-10"
    assert row.status == "on_track"
    assert row.deviation == Decimal("0.00")


def test_a_larger_contribution_is_ahead_and_a_small_one_is_at_risk():
    common = [*_cash()]
    ahead = LedgerProjection([
        *common,
        goal_created("g", "Goal", "USD", "900", "2026-08-29",
                     target_date="2026-12-10", monthly_contribution="300",
                     contribution_day=10),
    ]).goal("g", "2026-08-29")
    risk = LedgerProjection([
        *common,
        goal_created("g", "Goal", "USD", "900", "2026-08-29",
                     target_date="2026-12-10", monthly_contribution="100",
                     contribution_day=10),
    ]).goal("g", "2026-08-29")

    assert ahead.status == "ahead"
    assert risk.status == "at_risk"


def test_unlike_and_ineligible_accounts_are_named_as_exclusions():
    events = [
        *_cash(),
        account_opened("eur", "depository", "Euro", "EUR", "2026-01-01"),
        closing_balance_observed("eur", "400", "2026-08-29"),
        account_opened("asserted", "depository", "Cash", "USD",
                       "2026-01-01", origin=ASSERTED),
        closing_balance_observed("asserted", "100", "2026-08-29"),
        goal_created("trip", "Trip", "USD", "600", "2026-08-29"),
    ]

    row = LedgerProjection(events).goal("trip", "2026-08-29")

    assert [item.account_id for item in row.available_accounts] == ["checking"]
    assert {(item.account_id, item.reason) for item in row.exclusions} == {
        ("asserted", "account_not_issuer"),
        ("eur", "account_currency_differs"),
    }


def test_an_excess_release_cannot_manufacture_reserved_or_available_money():
    projection = LedgerProjection([
        *_cash(),
        goal_created("trip", "Trip", "USD", "600", "2026-08-29"),
        goal_funds_reserved("trip", "checking", "10", "2026-08-29"),
        goal_funds_released("trip", "checking", "20", "used_elsewhere",
                            "2026-08-30"),
    ])

    row = projection.goal("trip", "2026-08-30")

    assert row.reserved == Decimal("0")
    assert row.available_accounts[0].available == Decimal("1000.00")
    assert row.history[-1].amount == Decimal("20")
    assert row.history[-1].applied_amount == Decimal("10")
    assert row.history[-1].valid is False
    assert row.issues[0].startswith("release_exceeds_reserved:checking:")


def test_invalid_target_dates_refuse_at_the_typed_constructor():
    with pytest.raises(ValueError, match="ISO calendar date"):
        goal_created("g", "Goal", "USD", "100", "2026-08-29",
                     target_date="2026-02-31", contribution_day=15)


def test_long_valid_plans_have_no_arbitrary_projection_cutoff():
    row = LedgerProjection([
        *_cash(),
        goal_created("g", "Goal", "USD", "1201", "2026-08-29",
                     monthly_contribution="1", contribution_day=15),
    ]).goal("g", "2026-08-29")

    assert row.projected_completion_date == "2126-09-15"


def test_unknown_goal_is_an_explicit_refusal_not_none():
    with pytest.raises(UnknownGoalError):
        LedgerProjection(_cash()).goal("missing", "2026-08-29")


def test_returned_history_is_immutable_typed_data():
    row = LedgerProjection([
        *_cash(),
        goal_created("g", "Goal", "USD", "100", "2026-08-29"),
        goal_funds_reserved("g", "checking", "10", "2026-08-29"),
    ]).goal("g", "2026-08-29")

    with pytest.raises(Exception):
        row.history[0].amount = Decimal("99")


@pytest.mark.parametrize("value", [1.25, True, "0", "-1", "NaN"])
def test_goal_amounts_reject_float_poison_and_nonpositive_values(value):
    with pytest.raises((TypeError, ValueError)):
        goal_created("g", "Goal", "USD", value, "2026-08-29")


def test_monthly_contribution_requires_an_unambiguous_calendar_day():
    with pytest.raises(ValueError, match="day.*1 to 28"):
        goal_created("g", "Goal", "USD", "100", "2026-08-29",
                     monthly_contribution="10", contribution_day=31)
