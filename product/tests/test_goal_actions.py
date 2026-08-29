"""Goal drafts write nothing; exact persisted proposals gate every change."""

from decimal import Decimal

import pytest

from viva.goals import GoalService
from viva.ledger import (Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)
from viva.vault import Vault


def _vault(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened(
        "checking", "depository", "Checking", "USD", "2026-01-01"))
    vault.ledger.append(closing_balance_observed(
        "checking", "1000", "2026-08-29",
        Provenance("statement", 1, "closing")))
    return vault


def _service(vault, ids=None, today="2026-08-29"):
    minted = iter(ids or ["goal-1", "proposal-1"])
    return GoalService(vault, clock=lambda: today, mint=lambda: next(minted))


def _create(**more):
    return {"verb": "create", "title": "Trip", "currency": "USD",
            "target_amount": "600", "target_date": "2026-11-15",
            "contribution_day": 15, **more}


def _record_goal(vault):
    proposed = _service(vault).propose(_create())
    completed = _service(vault, []).confirm(proposed.proposal_id)
    assert completed.kind == "completed"
    return completed.goal_id


def test_draft_is_pure_and_calculates_the_date_only_path(tmp_path):
    vault = _vault(tmp_path)
    before = len(vault.ledger)

    result = _service(vault).draft(_create())

    assert result.state == "ready"
    assert result.draft["calculated"]["required_monthly"] == "200.00"
    assert result.draft["calculated"]["status"] == "unscheduled"
    assert len(vault.ledger) == before


def test_missing_cadence_input_is_needs_input_and_writes_nothing(tmp_path):
    vault = _vault(tmp_path)
    before = len(vault.ledger)

    result = _service(vault).draft({
        "verb": "create", "title": "Trip", "currency": "USD",
        "target_amount": "600", "target_date": "2026-11-15"})

    assert (result.state, result.reason) == (
        "needs_input", "contribution_day_required")
    assert len(vault.ledger) == before


def test_proposal_persists_exact_terms_without_creating_the_goal(tmp_path):
    vault = _vault(tmp_path)

    result = _service(vault).propose(_create())

    assert result.kind == "proposal"
    assert vault.ledger.projection().goals("2026-08-29") == []
    held = vault.ledger.projection().goal_proposal(result.proposal_id)
    assert held["proposal"] == {
        "title": "Trip", "currency": "USD", "target_amount": "600",
        "target_date": "2026-11-15", "monthly_contribution": "",
        "contribution_day": 15, "goal_id": "goal-1"}
    assert held["stake"] == {"goal_id": "goal-1", "absent": True}


def test_confirm_records_exact_proposal_and_resolution(tmp_path):
    vault = _vault(tmp_path)
    proposal = _service(vault).propose(_create())

    result = _service(vault, []).confirm(proposal.proposal_id)

    assert result.kind == "completed"
    row = vault.ledger.projection().goal("goal-1", "2026-08-29")
    assert row.title == "Trip"
    assert row.target_amount == Decimal("600")
    held = vault.ledger.projection().goal_proposal(proposal.proposal_id)
    assert (held["status"], held["outcome"]) == ("resolved", "completed")


def test_open_proposal_survives_vault_restart(tmp_path):
    vault = _vault(tmp_path)
    proposal = _service(vault).propose(_create())

    reopened = Vault.open(vault.directory, "pw", create=False)
    held = reopened.ledger.projection().goal_proposal(proposal.proposal_id)

    assert held["status"] == "open"
    assert held["proposal"]["target_amount"] == "600"
    assert _service(reopened, []).confirm(proposal.proposal_id).kind == "completed"


def test_decline_resolves_proposal_without_goal_write(tmp_path):
    vault = _vault(tmp_path)
    proposal = _service(vault).propose(_create())

    result = _service(vault, []).decline(proposal.proposal_id)

    assert result.kind == "set_aside"
    assert vault.ledger.projection().goals("2026-08-29") == []
    assert vault.ledger.projection().goal_proposal(
        proposal.proposal_id)["outcome"] == "set_aside"


def test_reservation_rechecks_exact_account_stake_and_stales_after_balance_move(
        tmp_path):
    vault = _vault(tmp_path)
    goal_id = _record_goal(vault)
    proposal = _service(vault, ["reserve-proposal"]).propose({
        "verb": "reserve", "goal_id": goal_id,
        "account_id": "checking", "amount": "200"})
    vault.ledger.append(closing_balance_observed(
        "checking", "900", "2026-08-30",
        Provenance("new-statement", 1, "closing")))

    result = _service(vault, [], today="2026-08-30").confirm(
        proposal.proposal_id)

    assert (result.kind, result.reason) == (
        "stale", "proposal_basis_changed")
    assert vault.ledger.projection().goal(
        goal_id, "2026-08-30").reserved == Decimal("0")


def test_two_reservations_cannot_spend_the_same_availability(tmp_path):
    vault = _vault(tmp_path)
    goal_id = _record_goal(vault)
    first = _service(vault, ["p1"]).propose({
        "verb": "reserve", "goal_id": goal_id,
        "account_id": "checking", "amount": "600"})
    second = _service(vault, ["p2"]).propose({
        "verb": "reserve", "goal_id": goal_id,
        "account_id": "checking", "amount": "600"})

    assert _service(vault, []).confirm(first.proposal_id).kind == "completed"
    stale = _service(vault, []).confirm(second.proposal_id)

    assert stale.kind == "stale"
    assert vault.ledger.projection().goal(
        goal_id, "2026-08-29").reserved == Decimal("600")


def test_reserve_and_release_refuse_amounts_outside_live_bounds(tmp_path):
    vault = _vault(tmp_path)
    goal_id = _record_goal(vault)

    too_much = _service(vault, ["unused"]).propose({
        "verb": "reserve", "goal_id": goal_id,
        "account_id": "checking", "amount": "1001"})
    release = _service(vault, ["unused"]).propose({
        "verb": "release", "goal_id": goal_id,
        "account_id": "checking", "amount": "1",
        "reason": "used_elsewhere"})

    assert (too_much.kind, too_much.reason) == (
        "refused", "reservation_exceeds_available")
    assert (release.kind, release.reason) == (
        "refused", "release_exceeds_reserved")


def test_pause_keeps_reservation_and_set_aside_requires_explicit_release(tmp_path):
    vault = _vault(tmp_path)
    goal_id = _record_goal(vault)
    reserve = _service(vault, ["reserve"]).propose({
        "verb": "reserve", "goal_id": goal_id,
        "account_id": "checking", "amount": "200"})
    _service(vault, []).confirm(reserve.proposal_id)
    pause = _service(vault, ["pause"]).propose({
        "verb": "pause", "goal_id": goal_id})
    _service(vault, []).confirm(pause.proposal_id)

    row = vault.ledger.projection().goal(goal_id, "2026-08-29")
    assert (row.state, row.reserved) == ("paused", Decimal("200"))
    refused = _service(vault, ["unused"]).propose({
        "verb": "set_aside", "goal_id": goal_id})
    assert (refused.kind, refused.reason) == (
        "refused", "goal_still_reserved")


def test_term_change_cannot_switch_currency_while_money_is_reserved(tmp_path):
    vault = _vault(tmp_path)
    goal_id = _record_goal(vault)
    reserve = _service(vault, ["reserve"]).propose({
        "verb": "reserve", "goal_id": goal_id,
        "account_id": "checking", "amount": "100"})
    _service(vault, []).confirm(reserve.proposal_id)

    result = _service(vault, ["unused"]).propose({
        "verb": "change_terms", "goal_id": goal_id, "title": "Trip",
        "currency": "EUR", "target_amount": "600",
        "target_date": "2026-11-15", "contribution_day": 15})

    assert (result.kind, result.reason) == (
        "refused", "reserved_goal_currency_fixed")


def test_confirm_replays_writes_from_another_open_vault_before_applying(tmp_path):
    first = _vault(tmp_path)
    goal_id = _record_goal(first)
    proposal = _service(first, ["reserve"]).propose({
        "verb": "reserve", "goal_id": goal_id,
        "account_id": "checking", "amount": "600"})
    second = Vault.open(first.directory, "pw", create=False)
    second.ledger.append(closing_balance_observed(
        "checking", "500", "2026-08-30",
        Provenance("later", 1, "closing")))

    result = _service(first, [], today="2026-08-30").confirm(
        proposal.proposal_id)

    assert result.kind == "stale"
    reopened = Vault.open(first.directory, "pw", create=False)
    assert reopened.ledger.projection().goal(
        goal_id, "2026-08-30").reserved == Decimal("0")


def test_two_open_vaults_cannot_confirm_one_proposal_twice(tmp_path):
    first = _vault(tmp_path)
    goal_id = _record_goal(first)
    proposal = _service(first, ["reserve"]).propose({
        "verb": "reserve", "goal_id": goal_id,
        "account_id": "checking", "amount": "400"})
    second = Vault.open(first.directory, "pw", create=False)

    assert _service(first, []).confirm(proposal.proposal_id).kind == "completed"
    duplicate = _service(second, []).confirm(proposal.proposal_id)

    assert (duplicate.kind, duplicate.reason) == (
        "refused", "proposal_not_open")
    reopened = Vault.open(first.directory, "pw", create=False)
    assert reopened.ledger.projection().goal(
        goal_id, "2026-08-29").reserved == Decimal("400")


def test_release_stake_keeps_full_balance_evidence_when_account_is_excluded(
        tmp_path):
    vault = _vault(tmp_path)
    goal_id = _record_goal(vault)
    reserve = _service(vault, ["reserve"]).propose({
        "verb": "reserve", "goal_id": goal_id,
        "account_id": "checking", "amount": "100"})
    _service(vault, []).confirm(reserve.proposal_id)
    # Opening plus activity says 900 while the attested closing remains 1,000.
    vault.ledger.append(opening_balance_observed(
        "checking", "1000", "2026-01-01",
        Provenance("opening", 1, "opening")))
    vault.ledger.append(simple_transaction(
        "checking", "-100", "OUTGOING", "2026-08-01",
        kind="depository"))

    release = _service(vault, ["release"]).propose({
        "verb": "release", "goal_id": goal_id,
        "account_id": "checking", "amount": "50",
        "reason": "used_elsewhere"})
    stake = vault.ledger.projection().goal_proposal(
        release.proposal_id)["stake"]["account"]

    assert stake["eligible"] is False
    assert stake["exclusion_reason"] == "account_balance_conflicted"
    assert {"balance", "dated", "grade", "currency", "reserved",
            "available", "record_id"} <= set(stake)

    other = Vault.open(vault.directory, "pw", create=False)
    other.ledger.append(closing_balance_observed(
        "checking", "800", "2026-08-29",
        Provenance("moves-again", 1, "closing")))
    assert _service(vault, []).confirm(release.proposal_id).kind == "stale"


@pytest.mark.parametrize("payload", [
    {"verb": "reserve", "goal_id": "g", "amount": "1"},
    {"verb": "reserve", "goal_id": "g", "account_id": "checking"},
    {"verb": "release", "goal_id": "g", "account_id": "checking",
     "amount": "1"},
])
def test_missing_goal_action_meaning_needs_input(tmp_path, payload):
    result = _service(_vault(tmp_path)).draft(payload)

    assert (result.state, result.reason) == (
        "needs_input", "goal_action_fields_required")


def test_projection_names_the_durable_open_proposal_read(tmp_path):
    vault = _vault(tmp_path)
    proposal = _service(vault).propose(_create())

    assert [row["proposal_id"] for row in
            vault.ledger.projection().open_goal_proposals()] == [
                proposal.proposal_id]
