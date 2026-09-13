"""Current Review parity, revision isolation, and explicit work bounds."""

from pathlib import Path

import pytest

from viva.demo import build_demo_vault
from viva.ledger.events import question_declined
from viva.surface.review import review


@pytest.mark.parametrize("limit", [1, 100, 500])
def test_current_review_sql_matches_complete_canonical_payload(
        tmp_path: Path, limit: int):
    vault = build_demo_vault(tmp_path / "sample")
    expected = review(vault.ledger.projection(), "en-US", limit=limit,
                      as_of="2026-09-30")

    with vault.read_store.open_reader() as revision:
        actual = review(revision.review_projection(), "en-US", limit=limit,
                        as_of="2026-09-30")

    assert actual == expected


def test_review_reader_holds_one_generation_across_later_publication(tmp_path: Path):
    vault = build_demo_vault(tmp_path / "sample")
    held = vault.read_store.open_reader()
    before = review(held.review_projection(), "en-US", as_of="2026-09-30")
    queue = held.open_questions(as_of="2026-09-30", limit=100)
    question = queue["questions"][0]
    vault.ledger.append(question_declined(
        question["id"], question["kind"], "2026-09-30",
        amount=question["amount"], count=question["count"]))

    assert review(held.review_projection(), "en-US", as_of="2026-09-30") == before
    with vault.read_store.open_reader() as current:
        after = review(current.review_projection(), "en-US",
                       as_of="2026-09-30")
        assert current.generation != held.generation
    assert after != before
    assert after["actionable_count"] == before["actionable_count"] - 1
    held.close()


def test_acknowledged_review_decline_changes_next_sql_read_exactly_once(
        tmp_path: Path):
    vault = build_demo_vault(tmp_path / "sample")
    before = review(vault.ledger.projection(), "en-US", as_of="2026-09-30")
    question = before["groups"][0]["items"][0]
    with vault.read_store.open_reader() as revision:
        queue = revision.open_questions(as_of="2026-09-30", limit=100)
    source = next(item for item in queue["questions"]
                  if item["id"] == question["target"]["question_id"])

    vault.ledger.append(question_declined(
        source["id"], source["kind"], "2026-09-30",
        amount=source["amount"], count=source["count"]))
    with vault.read_store.open_reader() as revision:
        actual = review(revision.review_projection(), "en-US",
                        as_of="2026-09-30")
    expected = review(vault.ledger.projection(), "en-US", as_of="2026-09-30")

    assert actual == expected
    assert actual["actionable_count"] == before["actionable_count"] - 1


@pytest.mark.parametrize("limit", [0, 501, True])
def test_review_sql_refuses_out_of_contract_limit(tmp_path: Path, limit):
    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ValueError, match="review limit"):
            review(revision.review_projection(), "en-US", limit=limit,
                   as_of="2026-09-30")


def test_review_binding_inputs_have_named_order_compatible_plans(tmp_path: Path):
    vault = build_demo_vault(tmp_path / "sample")
    statements = (
        ("movements_by_activity_order",
         "SELECT movement_key FROM movements INDEXED BY movements_by_activity_order "
         "ORDER BY occurred_at DESC,movement_key DESC LIMIT ?", (10_001,)),
        ("statement_periods_by_account_date",
         "SELECT account_id,period_end FROM statement_periods "
         "INDEXED BY statement_periods_by_account_date "
         "WHERE account_id=? ORDER BY period_end DESC,source_sequence DESC LIMIT ?",
         ("acct:everyday-checking", 10_001)),
        ("review_decisions_by_current_subject",
         "SELECT subject_id,source_sequence FROM review_decisions "
         "INDEXED BY review_decisions_by_current_subject "
         "WHERE event_type=? AND subject_id=? ORDER BY source_sequence DESC LIMIT ?",
         ("QuestionDeclined", "question:synthetic", 201)),
    )
    with vault.read_store.open_reader() as revision:
        for index, sql, parameters in statements:
            rows = revision.connection.execute(
                "EXPLAIN QUERY PLAN " + sql, parameters).fetchall()
            plan = " ".join(str(row[-1]) for row in rows)
            assert index in plan
            assert "TEMP B-TREE" not in plan
