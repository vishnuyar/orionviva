"""The current-period surface carries a whole bounded answer and chart."""

from dataclasses import replace

from viva.ledger import (LedgerProjection, account_opened,
                         closing_balance_observed)
from viva.surface.current_period import control
from viva.surface.capabilities import capabilities

from test_current_period import _projection


class _AnsweredProjection:
    def __init__(self, projection, answer):
        self._projection = projection
        self._answer = answer

    def current_period(self, _today):
        return self._answer

    def __getattr__(self, name):
        return getattr(self._projection, name)


def test_limited_answer_carries_reviewed_bounds_assumptions_and_tooltips():
    read = control(_projection(), "en-US", "2026-05-01")

    assert read["state"] == "limited"
    (row,) = read["slices"]
    assert row["remainder_min"] == "900.00"
    assert row["remainder_max"] == "2900.00"
    assert "known remainder" in row["headline"].lower()
    assert "safe to spend" not in row["headline"].lower()
    assert "permission to spend" in " ".join(row["caveats"]).lower()
    assert row["missing_inputs"] == ["planned_spending", "goal_contributions"]
    assert [point["kind"] for point in row["series"]] == [
        "balance", "obligation", "income"]
    assert all(point["tooltip"] for point in row["series"])
    assert row["liquid_balance"] == "1000.00"
    assert row["expected_income_max"] == "2000.00"
    assert row["obligations_max"] == "100.00"
    assert row["evidence_dates"]
    assert row["completeness"] == {
        "balances": True, "income": True, "obligations": True,
        "planned_spending": False, "goals": False,
    }
    assert row["exclusions"] == []
    assert row["evidence_label"]
    assert row["evidence_heading"]


def test_equal_bounds_stay_visibly_range_shaped():
    projection = LedgerProjection([
        account_opened("checking", "depository", "Checking", "USD",
                       "2026-05-01"),
        closing_balance_observed("checking", "100.00", "2026-05-01"),
    ])

    (row,) = control(projection, "en-US", "2026-05-01")["slices"]

    assert row["remainder_min"] == row["remainder_max"]
    low, high = row["amount_display"].split(" – ")
    assert low == high
    assert low in row["headline"] and high in row["headline"]


def test_empty_vault_is_absent_but_a_nonliquid_vault_is_a_reviewed_refusal():
    assert control(LedgerProjection([]), "en-US", "2026-05-01")["state"] == "absent"
    projection = LedgerProjection([
        account_opened("card", "liability", "Card", "USD", "2026-01-01"),
        closing_balance_observed("card", "250", "2026-05-01"),
    ])

    read = control(projection, "en-US", "2026-05-01")

    assert read["state"] == "refused"
    assert "depository balance" in read["refusal"]
    assert read["slices"] == []


def test_ready_answer_crosses_when_every_input_family_is_complete():
    projection = _projection()
    result = projection.current_period("2026-05-01")
    row = result.slices[0]
    complete = replace(
        row.completeness, planned_spending=True, goals=True)
    answered = replace(
        result, slices=(replace(row, missing_inputs=(),
                                completeness=complete),))

    read = control(_AnsweredProjection(projection, answered),
                   "en-US", "2026-05-01")

    assert read["state"] == "ready"
    assert read["slices"]


def test_missed_income_crosses_as_a_structured_visible_exclusion():
    read = control(_projection(today="2026-05-16"),
                   "en-US", "2026-05-16")

    (row,) = read["slices"]
    assert row["expected_income_max"] == "0"
    assert any(item["reason"] == "incoming_interrupted"
               for item in row["exclusions"])
    assert any("expected deposit" in caveat.lower()
               for caveat in row["caveats"])


def test_contract_inventory_names_every_current_period_state_fixture():
    spec = next(item for item in capabilities()
                if item.id == "overview.current_period")

    assert spec.fixture_ids == (
        "overview.current_period.ready",
        "overview.current_period.limited",
        "overview.current_period.refused",
    )


def test_overview_carries_current_period_without_recalculating_it():
    from viva.surface.overview import overview

    direct = control(_projection(), "en-US", "2026-05-01")
    carried = overview(_projection(), "en-US", "2026-05-01")

    assert carried["current_period"] == direct
