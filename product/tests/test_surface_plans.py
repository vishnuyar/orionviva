"""GoalsAndPlans.v1 owns its copy, exact values, evidence and actions."""

import json
from decimal import Decimal
from pathlib import Path

from viva.desktop_bridge.handlers import (PLANS_OPERATIONS,
                                           handlers_for_opened_vault)
from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, document_captured,
                         goal_created, goal_funds_released,
                         goal_funds_reserved)
from viva.persona import moment
from viva.surface.capabilities import capabilities
from viva.surface.plans import plans
from viva.vault import Vault


TODAY = "2026-08-29"


def _events():
    return [
        account_opened("checking", "depository", "Checking", "USD",
                       "2026-01-01"),
        document_captured(
            "statement-1", "statement.pdf", 128, "bank_statement", 1.0,
            "2026-08-29", Provenance("statement-1")),
        closing_balance_observed(
            "checking", "1000", TODAY,
            Provenance("statement-1", 1, "closing")),
        goal_created(
            "trip", "Trip", "USD", "600", "2026-08-01",
            target_date="2026-11-15", monthly_contribution="150",
            contribution_day=15),
        goal_funds_reserved("trip", "checking", "200", "2026-08-02"),
    ]


def test_empty_plans_surface_is_an_invitation_not_a_claim():
    read = plans(LedgerProjection([]), "en-US", TODAY)

    assert read["state"] == "absent"
    assert read["goals"] == []
    assert "draft" in read["invitation"]["body"].lower()


def test_plan_values_are_separate_from_account_evidence():
    read = plans(LedgerProjection(_events()), "en-US", TODAY)

    assert read["state"] == "ready"
    (goal,) = read["goals"]
    assert (goal["target_amount"], goal["reserved"], goal["remaining"]) == (
        "600", "200", "400")
    assert "grade" not in {
        "target_amount": goal["target_amount"],
        "reserved": goal["reserved"], "remaining": goal["remaining"]}
    account = next(item for item in goal["accounts"] if item["eligible"])
    assert account["grade"] == "verified"
    assert account["as_of"] == ""
    assert account["dated"] == "2026-08-29"
    assert account["balance_explanation"]
    assert account["source_document_id"] == "statement-1"
    assert account["source_page"] == "1"
    assert account["source_region"] == "closing"
    assert account["caveats"] == [account["balance_explanation"]]
    assert account["evidence_ids"] == ["statement-1"]
    assert account["citations"][0]["document_id"] == "statement-1"
    assert "No bank money moved" in goal["no_money_moved"]
    assert goal["actions"] == ["change_terms", "pause", "reserve", "release"]


def test_invalid_reservation_history_crosses_as_reviewed_copy():
    events = _events() + [goal_funds_released(
        "trip", "checking", "999", "used_elsewhere", TODAY)]

    (goal,) = plans(LedgerProjection(events), "en-US", TODAY)["goals"]

    assert goal["history_note"] == moment("plans_history_withheld")
    assert goal["caveats"] == [moment("plans_history_withheld")]
    assert "release_exceeds_reserved" not in json.dumps(goal)


def test_open_proposal_crosses_with_exact_payload_and_consequence(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    for event in _events()[:3]:
        vault.ledger.append(event)
    handlers = handlers_for_opened_vault(vault).handlers

    proposal = handlers[PLANS_OPERATIONS["propose"]]({
        "verb": "create", "title": "Buffer", "currency": "USD",
        "target_amount": "300", "monthly_contribution": "50",
        "contribution_day": 1})
    read = plans(vault.ledger.fresh_projection(), "en-US", TODAY)

    assert proposal["kind"] == "proposal"
    (held,) = read["proposals"]
    assert held["exact"]["target_amount"] == "300"
    assert held["exact"]["monthly_contribution"] == "50"
    assert "exactly this proposal" in held["consequence"].lower()
    assert held["actions"] == ["confirm", "decline"]


def test_bridge_draft_reports_needs_input_without_writing(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    handlers = handlers_for_opened_vault(vault).handlers
    before = len(vault.ledger)

    result = handlers[PLANS_OPERATIONS["draft"]]({
        "verb": "create", "title": "Trip", "currency": "USD",
        "target_amount": "600", "target_date": "2026-11-15"})

    assert result["kind"] == "waiting"
    assert result["state"]["draft_state"] == "needs_input"
    assert len(vault.ledger) == before


def test_capability_serves_every_reviewed_plan_state():
    spec = next(item for item in capabilities() if item.id == "plans.goals")

    assert spec.contract == "GoalsAndPlans.v1"
    assert spec.destination.value == "plans"
    assert spec.maturity.value == "stable"
    assert spec.actions == ("draft", "propose", "confirm", "decline")
    assert spec.fixture_ids == tuple(
        f"plans.goals.{state}" for state in (
            "absent", "ready", "needs_input", "partial", "refused",
            "open", "completed", "stale"))


def test_every_plan_fixture_contains_a_renderable_surface_and_action_state():
    fixture = json.loads((Path(__file__).parents[1] /
                          "viva/surface/fixtures/surface-v1.json").read_text())
    rows = [row for row in fixture["fixtures"]
            if row["capability_id"] == "plans.goals"]

    assert {row["state"] for row in rows} == {
        "absent", "ready", "needs_input", "partial", "refused", "open",
        "completed", "stale"}
    for row in rows:
        surface = row["payload"]["surface"]
        assert {"state", "title", "invitation", "goals", "groups",
                "proposals", "actions"} <= set(surface)
        if row["state"] in {
                "needs_input", "refused", "open", "completed", "stale"}:
            assert row["payload"]["action"]["kind"]
