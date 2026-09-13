"""Current Plans SQL payload parity and revision semantics."""

from pathlib import Path
import json

import pytest

from viva.demo import build_demo_vault
from viva.ledger.events import (goal_proposal_recorded,
                                goal_proposal_resolved)
from viva.read_store.plans import MAX_OPEN_GOAL_PROPOSALS
from viva.read_store.store import ReadStoreError
from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.surface.plans import plans


TODAY = "2026-08-29"


def _proposal(identity: str):
    return goal_proposal_recorded(
        identity, "create", "Synthetic plan", {
            "goal_id": f"goal:{identity}", "title": "Synthetic plan",
            "currency": "USD", "target_amount": "123.4500"},
        {"amount": "123.4500"}, "2026-08-28")


def test_current_plans_sql_matches_complete_surface_payload(tmp_path: Path):
    vault = build_demo_vault(tmp_path / "sample")
    vault.ledger.append(_proposal("proposal:one"))
    vault.ledger.append(_proposal("proposal:two"))
    vault.ledger.append(goal_proposal_resolved(
        "proposal:two", "set_aside", "2026-08-29"))
    expected = plans(vault.ledger.fresh_projection(), "en-US", TODAY)

    with vault.read_store.open_reader() as revision:
        actual = plans(revision.plans_projection(), "en-US", TODAY)

    assert actual == expected
    assert [row["id"] for row in actual["proposals"]] == ["proposal:one"]


def test_plans_reader_holds_old_payload_across_proposal_write(tmp_path: Path):
    vault = build_demo_vault(tmp_path / "sample")
    held = vault.read_store.open_reader()
    before = plans(held.plans_projection(), "en-US", TODAY)

    vault.ledger.append(_proposal("proposal:later"))

    assert plans(held.plans_projection(), "en-US", TODAY) == before
    with vault.read_store.open_reader() as current:
        after = plans(current.plans_projection(), "en-US", TODAY)
        assert current.generation != held.generation
    assert after != before
    assert [row["id"] for row in after["proposals"]] == ["proposal:later"]
    held.close()


def test_plans_open_proposals_refuse_n_plus_one(tmp_path: Path):
    vault = build_demo_vault(tmp_path / "sample")
    events = tuple(_proposal(f"proposal:{index:03d}")
                   for index in range(MAX_OPEN_GOAL_PROPOSALS + 1))
    vault.ledger.store.append_atomically(lambda _existing: events)
    vault.synchronize_read_store()

    with vault.read_store.open_reader() as revision:
        with pytest.raises(ReadStoreError, match="output bound"):
            revision.plans_projection().open_goal_proposals()


def test_plans_proposal_fold_uses_named_order_index(tmp_path: Path):
    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as revision:
        rows = revision.connection.execute(
            "EXPLAIN QUERY PLAN SELECT h.event_type,h.proposal_id,h.occurred_at,"
            "CASE WHEN length(CAST(h.body_json AS BLOB))<=? THEN h.body_json END,"
            "a.event_id FROM goal_proposal_history h "
            "JOIN applied_events a ON a.sequence=h.source_sequence "
            "ORDER BY h.source_sequence LIMIT ?", (1_000_000, 10_001)).fetchall()
    plan = " ".join(str(row[-1]) for row in rows)
    assert "SCAN h" in plan
    assert "SEARCH a USING INTEGER PRIMARY KEY" in plan
    assert "TEMP B-TREE" not in plan


def test_plans_bridge_refuses_oversized_goal_body_without_partial_payload(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as revision:
        row = revision.connection.execute(
            "SELECT goal_id,body_json FROM goal_event_history "
            "WHERE event_type='GoalCreated' LIMIT 1").fetchone()
    assert row is not None
    goal_id, original = row
    baseline = OpenedVaultSurfaceProvider(vault).read_surface(
        "plans", {"read_on": TODAY})
    body = json.loads(original)
    body["padding"] = "X" * 1_000_001
    vault.read_store.publish(lambda connection: connection.execute(
        "UPDATE goal_event_history SET body_json=? WHERE goal_id=? "
        "AND event_type='GoalCreated'", (json.dumps(body), goal_id)),
        copy_current=True)
    with pytest.raises(BridgeRequestError, match="could not answer plans"):
        OpenedVaultSurfaceProvider(vault).read_surface(
            "plans", {"read_on": TODAY})
    assert baseline["state"] in {"ready", "absent"}
