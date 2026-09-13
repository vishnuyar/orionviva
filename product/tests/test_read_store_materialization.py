import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from viva.ledger import (EventStore, Provenance, Posting, account_identity_observed,
                         account_opened, closing_balance_observed, document_captured,
                         opening_balance_observed, transaction_recorded)
from viva.ledger.events import (Event, brokerage_activity_held,
                                brokerage_activity_resolved,
                                correction_applied, position_observed,
                                read_recorded, statement_held)
from viva.ledger.events import (category_assigned, movement_tagged,
                                account_alias_confirmed, merchant_enriched,
                                ruling_recorded,
                                transfer_linked, transfer_suggested,
                                transfer_unlinked)
from viva.ledger.events import (
    agent_acted, finding_set_aside, question_declined,
    conversation_proposal_recorded, conversation_proposal_resolved,
    conversation_turn_opened, conversation_turn_settled, goal_created,
    goal_funds_released, goal_funds_reserved, goal_proposal_recorded,
    goal_proposal_resolved, goal_state_changed, goal_terms_changed,
)
from viva.ledger.events import SCOPE_CATEGORY, SCOPE_MERCHANT, SCOPE_MOVEMENT, SCOPE_TAG
from viva.ledger.projection import LedgerProjection
from viva.read_store import ReadStore, ReadStoreError
from viva.read_store import store as read_store_module
from merchantcore.profile import Profile, ProfileStore, Template

PASSPHRASE = "correct horse battery staple"


def _corpus():
    source = Provenance(doc_id="声明-1", page=7, region="余额", note="café ☕")
    return [
        account_opened("acct-α", "brokerage", "Investments 🧭", "USD",
                       "2025-12-31", jurisdiction="US", institution="Bänk",
                       account_number="000123", account_names=["李雷", "李雷"],
                       origin="issued", provenance=source),
        account_identity_observed("acct-α", "2026-01-01", institution="Bänk",
                                  account_number="000123", account_names=["Léa"],
                                  provenance=source),
        opening_balance_observed("acct-α", "-999999999999999999.000000000000000001",
                                 "2025-12-31", source),
        document_captured("声明-1", "résumé-账单.pdf", 1234, "bank_statement",
                          0.987654321, "2026-01-31", source),
        transaction_recorded([
            Posting("acct-α", "-0.000000000000000001", "verified"),
            Posting("Expenses:Coffee", "0.000000000000000001", "unverified"),
        ], "Café 東京", "2026-01-02", tags=["travel", "travel", "家"],
           provenance=source),
        closing_balance_observed("acct-α", "1000000000000000000.1234500",
                                 "2026-01-31", source, confirmed_by="human"),
        position_observed("acct-α", "FUND/世界", "-1.230000000000000000",
                          "999999999999999999.000000000000000009", "JPY",
                          "2026-01-31", cost_basis="0.000000000000000001",
                          valuation_class="measured", grade="corroborated",
                          provenance=source),
        position_observed("acct-α", "NO-BASIS", "2", "3", "USD",
                          "2026-02-01", cost_basis=None, provenance=source),
        Event("CorrectionApplied", "2026-02-02", {"anything": ["合法", 1]}),
    ]


def _event_store(path: Path, events) -> EventStore:
    store = EventStore.open(path / "events.jsonl", PASSPHRASE)
    for event in events: store.append(event)
    return store


def _goal_conversation_corpus():
    source = Provenance("doc-plan", 2, "plan", "human words")
    return [
        goal_created("goal-旅", "Journey ✨", "usd", "999999999999.000000001",
                     "2026-01-03", target_date="2027-05-01",
                     monthly_contribution="123.4500", contribution_day=7,
                     proposal_id="gp-create", provenance=source),
        goal_terms_changed("goal-旅", "Journey revised", "USD", "1000000000000.01",
                           "2025-12-31", target_date="2027-06-01",
                           monthly_contribution="200.000", contribution_day=8,
                           proposal_id="gp-terms", provenance=source),
        goal_funds_reserved("goal-旅", "acct-α", "0.000000000000000001",
                            "2026-01-04", proposal_id="gp-reserve", provenance=source),
        goal_funds_released("goal-旅", "acct-α", "0.000000000000000001",
                           "used_elsewhere", "2026-01-05",
                           proposal_id="gp-release", provenance=source),
        goal_state_changed("goal-旅", "set_aside", "2026-01-06",
                           proposal_id="gp-state", provenance=source),
        goal_proposal_recorded("gp-1", "change_terms", "Change 🧭",
                               {"goal_id": "goal-旅", "amount": "10.000"},
                               {"version": "goals-v1", "reserved": "1.00"},
                               "2026-01-07", source),
        goal_proposal_resolved("gp-1", "stale", "2026-01-08",
                               reason="changed", provenance=source),
        conversation_turn_opened("turn-1", "answer", "What changed?",
                                 "2026-01-09", said="旅", question_id="q-1",
                                 mirrored=False, provenance=source),
        conversation_turn_settled("turn-1", "proposal", "Please confirm",
                                  "2026-01-10", answer={"amount": "10.00"},
                                  proposal_id="cp-1", provenance=source),
        conversation_proposal_recorded(
            "cp-1", "turn-1", "q-1", "Correction",
            {"type": "category", "nested": ["α", {"amount": "1.2300"}]},
            {"version": "conversation-v1", "count": 2},
            "2026-01-11", source),
        conversation_proposal_resolved("cp-1", "turn-1", "set_aside", "Later",
                                       "2026-01-12", reason="not now",
                                       provenance=source),
    ]


def _goal_conversation_planner_corpus(row_count: int = 72):
    """A representative corpus with dense identities and tied value-times."""
    source = Provenance("doc-semantic", 1, "history", "planner corpus")
    events = []
    for number in range(row_count):
        occurred_at = "2026-06-15" if number < row_count - 4 else f"2026-06-{number - row_count + 11:02d}"
        goal_id = "goal-dense" if number % 3 else f"goal-{number}"
        goal_proposal_id = "gp-dense" if number % 3 else f"gp-{number}"
        turn_id = "turn-dense" if number % 3 else f"turn-{number}"
        conversation_proposal_id = "cp-dense" if number % 3 else f"cp-{number}"
        events.extend([
            goal_created(goal_id, f"Goal {number}", "USD", str(number + 1),
                         occurred_at, provenance=source),
            goal_proposal_recorded(goal_proposal_id, "create", "new goal",
                                   {"goal_id": goal_id},
                                   {"version": "v1", "count": number},
                                   occurred_at, source),
            conversation_turn_opened(turn_id, "ask", f"status {number}?",
                                     occurred_at, provenance=source),
            conversation_proposal_recorded(
                conversation_proposal_id, turn_id, f"q-{number}", "change",
                {"kind": "category", "value": str(number)},
                {"version": "v1", "count": number}, occurred_at, source),
        ])
    return events


def _trust_review_corpus():
    source = Provenance("doc-信頼", 0, "region-α", "note ☕")
    return [
        document_captured("doc-信頼", "trust.pdf", 7, "statement", 0.7,
                          "2026-06-01", source),
        read_recorded("doc-信頼", "route-model", "extract-v1", "text",
                      "answer", 0.125, 0, 12,
                      True, None, "2026-06-02", phase="extract",
                      usage_reported=True, resolved_model="provider-model",
                      provenance=source),
        question_declined("q-α", "merchant", "2026-06-03", amount="1.2300",
                          count=2, pack_version="pack-β", provenance=source),
        finding_set_aside("finding-α", "fee_observed",
                          {"amount": "999999999.000000001", "nested": ["雪"]},
                          "2026-06-04", provenance=source),
        agent_acted("rule-α", "induce", "target-雪", "refused", "2026-06-05",
                    calls=2, stake={"count": 3, "amount": "1.2300"},
                    detail="kept local", provenance=source),
    ]


def test_trust_and_review_inputs_are_lossless_bounded_and_revision_local(tmp_path: Path):
    canonical = _event_store(tmp_path, _trust_review_corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            exchanges = revision.model_exchange_history(as_of="9999-12-31")
            assert len(exchanges) == 1
            assert exchanges[0]["cost_usd_text"] == "0.125"
            assert json.loads(exchanges[0]["body_json"])["response_text"] == "answer"
            actions = revision.agent_action_history(as_of="9999-12-31")
            assert json.loads(actions[0]["body_json"])["target"] == "target-雪"
            assert json.loads(actions[0]["stake_json"])["amount"] == "1.2300"
            assert (actions[0]["provenance_doc_id"], actions[0]["provenance_page"],
                    actions[0]["provenance_region"], actions[0]["provenance_note"]) == \
                   ("doc-信頼", 0, "region-α", "note ☕")
            assert [row["status"] for row in revision.review_decision_history(
                as_of="9999-12-31")] == ["set_aside", "declined"]
            assert revision.question_decision_history(
                as_of="9999-12-31")[0]["subject_id"] == "q-α"
            assert json.loads(revision.finding_decision_history(
                as_of="9999-12-31")[0]["body_json"])["stake"]["amount"] == \
                   "999999999.000000001"
            assert revision.model_exchange_history(as_of="2026-06-01") == []
            assert revision.agent_action_history(
                as_of="9999-12-31", outcome="done") == []
            assert exchanges[0]["resolved_model"] == "provider-model"
            assert exchanges[0]["provenance_page"] == 0
            with pytest.raises(ValueError):
                revision.agent_action_history(as_of="9999-12-31", limit=201)
            with pytest.raises(ValueError):
                revision.model_exchange_history(
                    as_of="9999-12-31", before=("2026-01-01", True))


def test_current_review_controls_use_exact_stakes_date_and_source_precedence(tmp_path: Path):
    source = Provenance("doc-review", 1, "stake", "current controls")
    events = [
        question_declined("q-1", "merchant", "2026-03-02",
                          amount="1.00", count=2, provenance=source),
        # A later canonical decision with an earlier value date wins whenever
        # it is eligible. This is the fold order used by LedgerProjection.
        question_declined("q-1", "merchant", "2026-03-01",
                          amount="2.000", count=3, provenance=source),
        finding_set_aside("f-1", "fee_observed",
                          {"amount": "9.00", "records": ["b", "a"]},
                          "2026-03-03", provenance=source),
        Event("FindingSetAside", "2026-03-01", {
            "finding_id": "f-1", "kind": "fee_observed", "stake": {},
            "by": "human"}, source),
        finding_set_aside("f-whitespace", "fee_observed",
                          {"amount": "-0.00", "label": "  ",
                           "nested": {"rows": [{"amount": "-12.3400"}]}},
                          "2026-03-03", provenance=source),
        Event("FindingSetAside", "2026-03-03", {
            "finding_id": "", "kind": "fee_observed", "stake": {},
            "by": "human"}, source),
    ]
    canonical = _event_store(tmp_path, events)
    oracle = LedgerProjection(events)
    assert oracle.declined_questions()["q-1"]["amount"] == "2.000"
    assert oracle.finding_set_asides()["f-1"]["stake"] == {}
    assert oracle.finding_set_asides()["f-whitespace"]["stake"] == {
        "amount": "-0.00", "label": "  ",
        "nested": {"rows": [{"amount": "-12.3400"}]}}
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            assert not revision.question_decline_matches(
                "q-1", amount_text="1.00", count=2, as_of="2026-03-02")
            assert revision.question_decline_matches(
                "q-1", amount_text="2.000", count=3, as_of="2026-03-02")
            assert not revision.question_decline_matches(
                "q-1", amount_text="2.00", count=3, as_of="2026-03-02")
            assert not revision.finding_set_aside_matches(
                "f-1", stake={"amount": "9.00", "records": ["b", "a"]},
                as_of="2026-03-02")
            assert not revision.finding_set_aside_matches(
                "f-1", stake={"amount": "9.00", "records": ["b", "a"]},
                as_of="2026-03-03")
            assert revision.finding_set_aside_matches(
                "f-1", stake={}, as_of="2026-03-03")
            assert not revision.finding_set_aside_matches(
                "f-1", stake={"amount": "9.00", "records": ["a", "b"]},
                as_of="2026-03-03")
            assert revision.finding_set_aside_matches(
                "f-whitespace",
                stake={"amount": "-0.00", "label": "  ",
                       "nested": {"rows": [{"amount": "-12.3400"}]}},
                as_of="2026-03-03")
            assert not revision.finding_set_aside_matches(
                "f-whitespace", stake={}, as_of="2026-03-03")
            with pytest.raises(ValueError, match="finding id is required"):
                revision.finding_set_aside_matches(
                    "", stake={}, as_of="2026-03-03")
            plan = revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT body_json FROM review_decisions "
                "WHERE event_type='QuestionDeclined' AND subject_id=? "
                "AND occurred_at<=? ORDER BY source_sequence DESC LIMIT 1",
                ("q-1", "2026-03-03")).fetchall()
            assert any("review_decisions_by_current_subject" in str(row)
                       for row in plan)
            assert not any("TEMP B-TREE" in str(row) for row in plan)
            finding_plan = revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT body_json FROM review_decisions "
                "WHERE event_type='FindingSetAside' AND subject_id=? "
                "AND occurred_at<=? ORDER BY source_sequence DESC LIMIT 1",
                ("f-1", "2026-03-03")).fetchall()
            assert any("review_decisions_by_current_subject" in str(row)
                       for row in finding_plan)
            assert not any("TEMP B-TREE" in str(row) for row in finding_plan)


def test_current_goal_states_match_canonical_fold_at_date_boundaries(tmp_path: Path):
    source = Provenance("doc-goal", 2, "terms", "current goal")
    events = [
        goal_created("goal-1", "Reserve", "USD", "100.00", "2026-01-02",
                     monthly_contribution="10.00", contribution_day=7,
                     provenance=source),
        goal_funds_reserved("goal-1", "cash", "12.3400", "2026-01-03",
                            provenance=source),
        goal_funds_released("goal-1", "cash", "20.00", "used_elsewhere", "2026-01-04",
                            provenance=source),
        goal_terms_changed("goal-1", "Renamed", "USD", "120.000",
                           "2026-01-01", monthly_contribution="15.00",
                           contribution_day=8, provenance=source),
        goal_state_changed("goal-1", "paused", "2026-01-05", provenance=source),
    ]
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            before_create = revision.current_goal_states(as_of="2026-01-01")
            assert before_create == []
            current = revision.current_goal_states(as_of="2026-01-05")
            assert len(current) == 1
            goal = current[0]
            assert goal["title"] == "Renamed"
            assert goal["target_amount"] == "120.000"
            assert goal["state"] == "paused"
            assert goal["reservations"] == {"cash": "0.0000"}
            assert goal["reservation_history"][1]["applied_amount"] == "12.3400"
            assert goal["reservation_history"][1]["valid"] is False
            assert goal["issues"] == [
                f"release_exceeds_reserved:cash:{goal['event_ids'][2]}"]
            assert goal["updated_at"] == "2026-01-05"
            # All eligible rows are folded in canonical source order. The
            # backfilled terms event therefore applies after the reservation.
            assert len(goal["event_ids"]) == 5


def _decimal_text(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _decimal_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimal_text(item) for item in value]
    return value


def test_current_goal_states_bound_identities_and_match_core_across_restart(
        tmp_path: Path):
    source = Provenance("doc-goal-oracle", 0, "goals", "parity")
    tied = "2026-04-01"
    events = [
        # Canonical core ignores changes which precede the first eligible create.
        goal_terms_changed("goal-b", "before", "USD", "1E-18", tied,
                           provenance=source),
        goal_funds_reserved("goal-b", "cash", "999.000", tied,
                            provenance=source),
        goal_created("goal-b", "B", "USD", "999999999999999999.0000000001",
                     tied, monthly_contribution="0.0100", contribution_day=1,
                     provenance=source),
        # A duplicate create is ignored, including all of its lexical values.
        goal_created("goal-b", "duplicate", "EUR", "2.0", tied,
                     provenance=source),
        goal_funds_reserved("goal-b", "cash", "12.3400", tied,
                            provenance=source),
        goal_funds_released("goal-b", "cash", "20.000", "used_elsewhere", tied,
                            provenance=source),
        goal_created("goal-a", "A", "USD", "1E-18", tied,
                     monthly_contribution="0.0100", contribution_day=2,
                     provenance=source),
        goal_state_changed("goal-a", "paused", tied, provenance=source),
        goal_created("goal-z", "Z", "USD", "3.000", tied,
                     provenance=source),
    ]
    canonical = _event_store(tmp_path, events[:3])
    root = tmp_path / "read-model"
    with ReadStore.create(root, PASSPHRASE) as reads:
        reads.synchronize(canonical)
        for event in events[3:6]:
            canonical.append(event)
        reads.synchronize(canonical)
        for event in events[6:]:
            canonical.append(event)
        reads.synchronize(canonical)

    oracle = LedgerProjection(events)
    expected = [_decimal_text(oracle._core._goals[key])
                for key in sorted(oracle._core._goals)[:2]]
    with ReadStore.open(root, PASSPHRASE) as reads:
        assert reads.synchronize(EventStore.open(canonical.path, PASSPHRASE)).state == "equal"
        with reads.open_reader() as revision:
            captured = []
            revision.connection.set_trace_callback(captured.append)
            actual = revision.current_goal_states(as_of=tied, limit=2)
            revision.connection.set_trace_callback(None)
            assert actual == expected
            assert [row["goal_id"] for row in actual] == ["goal-a", "goal-b"]
            assert len(actual) == 2
            assert actual[1]["target_amount"] == "999999999999999999.0000000001"
            assert actual[1]["reservations"] == {"cash": "0.0000"}
            assert actual[1]["reservation_history"][1]["applied_amount"] == "12.3400"

            statement = next(sql for sql in captured
                             if "WITH eligible_goals AS" in sql)
            plan = revision.connection.execute(
                "EXPLAIN QUERY PLAN " + statement).fetchall()
            plan_text = "\n".join(str(row) for row in plan)
            assert "goal_creates_by_current_id" in plan_text
            assert "goal_events_by_goal_order" in plan_text
            assert "SCAN h" not in plan_text
            with pytest.raises(ValueError):
                revision.current_goal_states(as_of=tied, limit=0)
            with pytest.raises(ValueError):
                revision.current_goal_states(as_of=tied, limit=201)


@pytest.mark.parametrize("table,wrong_type", [
    ("agent_action_history", "ReadRecorded"),
    ("document_reads", "AgentActed"),
])
def test_trust_rows_bind_the_exact_authenticated_event_family(
        tmp_path: Path, table: str, wrong_type: str):
    canonical = _event_store(tmp_path, _trust_review_corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        def substitute(db):
            sequence = db.execute(
                f"SELECT source_sequence FROM {table} LIMIT 1").fetchone()[0]
            db.execute("UPDATE applied_events SET event_type=? WHERE sequence=?",
                       (wrong_type, sequence))
        with pytest.raises(read_store_module.sqlcipher.IntegrityError,
                           match="FOREIGN KEY constraint failed"):
            reads.publish(substitute, copy_current=True)


@pytest.mark.parametrize(("event_type", "mutation"), [
    ("QuestionDeclined", {"event_type": "FindingSetAside"}),
    ("QuestionDeclined", {"status": "set_aside"}),
    ("QuestionDeclined", {
        "event_type": "FindingSetAside", "status": "set_aside"}),
])
def test_review_decision_family_status_binding_refuses_adversarial_publication(
        tmp_path: Path, event_type: str, mutation: dict[str, str]):
    canonical = _event_store(tmp_path, _trust_review_corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        published = reads.current_generation

        def substitute(db):
            sequence = db.execute(
                "SELECT source_sequence FROM review_decisions WHERE event_type=?",
                (event_type,)).fetchone()[0]
            assignments = ",".join(f"{column}=?" for column in mutation)
            db.execute(
                f"UPDATE review_decisions SET {assignments} WHERE source_sequence=?",
                (*mutation.values(), sequence))

        with pytest.raises(read_store_module.sqlcipher.IntegrityError):
            reads.publish(substitute, copy_current=True)
        assert reads.current_generation == published
        with reads.open_reader() as revision:
            row = revision.connection.execute(
                "SELECT event_type,status FROM review_decisions WHERE event_type=?",
                (event_type,)).fetchone()
            assert row == ("QuestionDeclined", "declined")


def test_trust_histories_survive_arbitrary_batches_restart_and_tied_pagination(tmp_path: Path):
    source = Provenance("doc-model", None, "", "")
    events = []
    for number in range(72):
        day = "2026-07-15" if number < 68 else f"2026-07-{number - 67:02d}"
        events.extend([
            read_recorded("doc-model", f"route-{number % 3}", "v1", "text",
                          f"response {number}", number / 100, number, number + 1,
                          True, None, day, phase="extract" if number % 2 else "classify",
                          provenance=source),
            agent_acted(f"rule-{number % 3}", "maintenance", f"target-{number}",
                        "done" if number % 2 else "refused", day, calls=number,
                        stake={"ordinal": number}, provenance=source),
            question_declined(f"q-{number}", "synthetic", day,
                              count=number, provenance=source),
            finding_set_aside(f"finding-{number}", "synthetic",
                              {"ordinal": number}, day, provenance=source),
        ])
    (tmp_path / "once").mkdir(); (tmp_path / "split").mkdir()
    once = _event_store(tmp_path / "once", events)
    split = _event_store(tmp_path / "split", events[:37])
    with ReadStore.create(tmp_path / "once-read", PASSPHRASE) as reads:
        reads.synchronize(once)
        with reads.open_reader() as revision:
            expected = {
                table: _rows(revision.connection, table)
                for table in ("document_reads", "agent_action_history", "review_decisions")}

            calls = (
                (lambda **kwargs: revision.model_exchange_history(
                    phase="extract", **kwargs), 36, "ReadRecorded"),
                (lambda **kwargs: revision.agent_action_history(
                    outcome="done", **kwargs), 36, "AgentActed"),
                (revision.question_decision_history, 72, "QuestionDeclined"),
                (revision.finding_decision_history, 72, "FindingSetAside"),
            )
            for method, expected_count, expected_type in calls:
                seen = []
                cursor = None
                while True:
                    page = method(as_of="9999-12-31", limit=11, before=cursor)
                    assert len(page) <= 11
                    if not page:
                        break
                    assert {row["event_type"] for row in page} == {expected_type}
                    if cursor is not None:
                        assert (page[0]["occurred_at"], page[0]["source_sequence"]) < cursor
                    seen.extend(row["source_sequence"] for row in page)
                    cursor = (page[-1]["occurred_at"], page[-1]["source_sequence"])
                assert len(seen) == expected_count
                assert len(set(seen)) == expected_count
                with pytest.raises(ValueError):
                    method(as_of="9999-12-31", limit=0)
                with pytest.raises(ValueError):
                    method(as_of="9999-12-31", limit=201)
                with pytest.raises(ValueError):
                    method(as_of="9999-12-31", before=("2026-01-01", True))

            unfiltered = revision.model_exchange_history(as_of="9999-12-31")
            assert unfiltered[0]["resolved_model"] is None
            assert unfiltered[0]["provenance_page"] is None
            assert unfiltered[0]["provenance_region"] == ""
            assert revision.agent_action_history(as_of="9999-12-31")[0]["produced"] == ""
    with ReadStore.create(tmp_path / "split-read", PASSPHRASE) as reads:
        reads.synchronize(split)
        for boundary in (81, 173, len(events)):
            for event in events[split.committed_snapshot().identity.count:boundary]:
                split.append(event)
            reads.synchronize(split)
        reads.close()
    with ReadStore.open(tmp_path / "split-read", PASSPHRASE) as reads:
        with reads.open_reader() as revision:
            assert expected == {
                table: _rows(revision.connection, table)
                for table in ("document_reads", "agent_action_history", "review_decisions")}
            checks = [
                ("model_exchanges_by_order",
                 "SELECT * FROM document_reads WHERE occurred_at<=? "
                 "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
                 ("9999-12-31", 20)),
                ("model_exchanges_by_phase_order",
                 "SELECT * FROM document_reads WHERE occurred_at<=? AND phase=? "
                 "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
                 ("9999-12-31", "extract", 20)),
                ("agent_actions_by_order",
                 "SELECT * FROM agent_action_history WHERE occurred_at<=? "
                 "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
                 ("9999-12-31", 20)),
                ("agent_actions_by_outcome_order",
                 "SELECT * FROM agent_action_history WHERE occurred_at<=? AND outcome=? "
                 "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
                 ("9999-12-31", "done", 20)),
            ]
            for index, query, parameters in checks:
                detail = " ".join(row[3] for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + query, parameters))
                assert f"USING INDEX {index}" in detail, detail
                assert "USE TEMP B-TREE" not in detail


def test_goal_and_conversation_histories_are_lossless_bounded_and_batch_invariant(tmp_path: Path):
    events = _goal_conversation_corpus()
    (tmp_path / "once").mkdir(); (tmp_path / "split").mkdir()
    once = _event_store(tmp_path / "once", events)
    split = _event_store(tmp_path / "split", events[:4])
    tables = ("goal_event_history", "goal_proposal_history",
              "conversation_turn_history", "conversation_proposal_history")
    with ReadStore.create(tmp_path / "once-read", PASSPHRASE) as reads:
        reads.synchronize(once)
        with reads.open_reader() as revision:
            expected = {table: _rows(revision.connection, table) for table in tables}
            goal_rows = revision.goal_event_history(as_of="9999-12-31", goal_id="goal-旅")
            assert [row["event_type"] for row in goal_rows] == [
                "GoalStateChanged", "GoalFundsReleased", "GoalFundsReserved",
                "GoalCreated", "GoalTermsChanged"]
            assert goal_rows[2]["amount_text"] == "1E-18"
            assert json.loads(goal_rows[-1]["body_json"])["target_amount"] == "1000000000000.01"
            assert json.loads(revision.conversation_proposal_history(
                as_of="9999-12-31", proposal_id="cp-1")[-1]["body_json"]
            )["proposal"]["nested"][1]["amount"] == "1.2300"
            page = revision.conversation_turn_history(as_of="9999-12-31", limit=1)
            cursor = (page[-1]["occurred_at"], page[-1]["source_sequence"])
            assert revision.conversation_turn_history(
                as_of="9999-12-31", limit=1, before=cursor)[0]["event_type"] == \
                "ConversationTurnOpened"
    with ReadStore.create(tmp_path / "split-read", PASSPHRASE) as reads:
        reads.synchronize(split)
        for event in events[4:]:
            split.append(event)
        reads.synchronize(split)
        with reads.open_reader() as revision:
            assert expected == {table: _rows(revision.connection, table) for table in tables}


@pytest.mark.parametrize("table,wrong_type", [
    ("goal_event_history", "ConversationTurnOpened"),
    ("goal_proposal_history", "GoalCreated"),
    ("conversation_turn_history", "GoalStateChanged"),
    ("conversation_proposal_history", "ConversationTurnSettled"),
])
def test_goal_conversation_rows_bind_exact_event_family(tmp_path: Path, table: str,
                                                        wrong_type: str):
    canonical = _event_store(tmp_path, _goal_conversation_corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        def substitute(db):
            sequence = db.execute(
                f"SELECT source_sequence FROM {table} LIMIT 1").fetchone()[0]
            db.execute("UPDATE applied_events SET event_type=? WHERE sequence=?",
                       (wrong_type, sequence))
        with pytest.raises(read_store_module.sqlcipher.IntegrityError,
                           match="FOREIGN KEY constraint failed"):
            reads.publish(substitute, copy_current=True)


def _captured_plan(revision, call):
    statements = []
    revision.connection.set_trace_callback(statements.append)
    try:
        assert call()
    finally:
        revision.connection.set_trace_callback(None)
    statement = next(row for row in reversed(statements) if row.startswith("SELECT "))
    return " ".join(row[-1] for row in revision.connection.execute(
        "EXPLAIN QUERY PLAN " + statement).fetchall())


def test_goal_conversation_named_reads_use_all_order_compatible_query_shapes(tmp_path: Path):
    canonical = _event_store(tmp_path, _goal_conversation_planner_corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            checks = [
                (lambda: revision.goal_event_history(as_of="9999-12-31"),
                 "goal_events_by_order"),
                (lambda: revision.goal_event_history(
                    as_of="9999-12-31", goal_id="goal-dense"),
                 "goal_events_by_goal_order"),
                (lambda: revision.goal_proposal_history(as_of="9999-12-31"),
                 "goal_proposals_by_order"),
                (lambda: revision.goal_proposal_history(
                    as_of="9999-12-31", proposal_id="gp-dense"),
                 "goal_proposals_by_id_order"),
                (lambda: revision.conversation_turn_history(as_of="9999-12-31"),
                 "conversation_turns_by_order"),
                (lambda: revision.conversation_turn_history(
                    as_of="9999-12-31", turn_id="turn-dense"),
                 "conversation_turns_by_id_order"),
                (lambda: revision.conversation_proposal_history(as_of="9999-12-31"),
                 "conversation_proposals_by_order"),
                (lambda: revision.conversation_proposal_history(
                    as_of="9999-12-31", proposal_id="cp-dense"),
                 "conversation_proposals_by_id_order"),
            ]
            for call, index_name in checks:
                detail = _captured_plan(revision, call)
                assert index_name in detail
                assert "USE TEMP B-TREE FOR ORDER BY" not in detail

            # Cursor-bearing SQL is a distinct planner shape. Exercise it for
            # every read in both its unfiltered and identity-filtered form.
            cursor_checks = [
                (revision.goal_event_history, {}, "goal_events_by_order"),
                (revision.goal_event_history, {"goal_id": "goal-dense"},
                 "goal_events_by_goal_order"),
                (revision.goal_proposal_history, {}, "goal_proposals_by_order"),
                (revision.goal_proposal_history, {"proposal_id": "gp-dense"},
                 "goal_proposals_by_id_order"),
                (revision.conversation_turn_history, {}, "conversation_turns_by_order"),
                (revision.conversation_turn_history, {"turn_id": "turn-dense"},
                 "conversation_turns_by_id_order"),
                (revision.conversation_proposal_history, {},
                 "conversation_proposals_by_order"),
                (revision.conversation_proposal_history,
                 {"proposal_id": "cp-dense"}, "conversation_proposals_by_id_order"),
            ]
            for method, selector, index_name in cursor_checks:
                first = method(as_of="9999-12-31", limit=7, **selector)
                cursor = (first[-1]["occurred_at"], first[-1]["source_sequence"])
                detail = _captured_plan(
                    revision,
                    lambda method=method, selector=selector, cursor=cursor: method(
                        as_of="9999-12-31", limit=7, before=cursor, **selector))
                assert index_name in detail
                assert "USE TEMP B-TREE FOR ORDER BY" not in detail


def test_goal_conversation_keysets_traverse_tied_timestamps_without_loss(tmp_path: Path):
    canonical = _event_store(tmp_path, _goal_conversation_planner_corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            reads_and_selectors = [
                (revision.goal_event_history, {}),
                (revision.goal_event_history, {"goal_id": "goal-dense"}),
                (revision.goal_proposal_history, {}),
                (revision.goal_proposal_history, {"proposal_id": "gp-dense"}),
                (revision.conversation_turn_history, {}),
                (revision.conversation_turn_history, {"turn_id": "turn-dense"}),
                (revision.conversation_proposal_history, {}),
                (revision.conversation_proposal_history,
                 {"proposal_id": "cp-dense"}),
            ]
            for method, selector in reads_and_selectors:
                expected = method(as_of="9999-12-31", limit=200, **selector)
                traversed = []
                before = None
                while True:
                    page = method(as_of="9999-12-31", limit=7,
                                  before=before, **selector)
                    if not page:
                        break
                    if before is not None:
                        assert all((row["occurred_at"], row["source_sequence"]) < before
                                   for row in page)
                    traversed.extend(page)
                    before = (page[-1]["occurred_at"], page[-1]["source_sequence"])
                assert traversed == expected
                identities = [row["source_sequence"] for row in traversed]
                assert len(identities) == len(set(identities))
                assert [(row["occurred_at"], row["source_sequence"])
                        for row in traversed] == sorted(
                            [(row["occurred_at"], row["source_sequence"])
                             for row in traversed], reverse=True)
                for valid_limit in (1, 200):
                    assert method(as_of="9999-12-31", limit=valid_limit,
                                  **selector)
                for invalid_limit in (0, 201, True, "7"):
                    with pytest.raises(ValueError):
                        method(as_of="9999-12-31", limit=invalid_limit,
                               **selector)
                for invalid_cursor in ((), ("2026-06-15",),
                                       ("2026-06-15", True), ["2026-06-15", 1]):
                    with pytest.raises(ValueError):
                        method(as_of="9999-12-31", before=invalid_cursor,
                               **selector)


def test_goal_conversation_irregular_suffix_batches_survive_read_store_restart(tmp_path: Path):
    events = _goal_conversation_planner_corpus(19)
    (tmp_path / "full").mkdir()
    (tmp_path / "incremental").mkdir()
    full_store = _event_store(tmp_path / "full", events)
    incremental_store = _event_store(tmp_path / "incremental", events[:1])
    tables = ("goal_event_history", "goal_proposal_history",
              "conversation_turn_history", "conversation_proposal_history")
    with ReadStore.create(tmp_path / "full-read", PASSPHRASE) as reads:
        reads.synchronize(full_store)
        with reads.open_reader() as revision:
            expected_tables = {table: _rows(revision.connection, table)
                               for table in tables}
            expected_reads = {
                "goals": revision.goal_event_history(as_of="9999-12-31"),
                "goal_proposals": revision.goal_proposal_history(as_of="9999-12-31"),
                "turns": revision.conversation_turn_history(as_of="9999-12-31"),
                "conversation_proposals": revision.conversation_proposal_history(
                    as_of="9999-12-31"),
            }
    root = tmp_path / "incremental-read"
    with ReadStore.create(root, PASSPHRASE) as reads:
        reads.synchronize(incremental_store)
        offset = 1
        for batch_size in (1, 7, 2, 13, 3, 17, 5, 11, 16):
            batch = events[offset:offset + batch_size]
            if not batch:
                break
            for event in batch:
                incremental_store.append(event)
            offset += len(batch)
            reads.synchronize(incremental_store)
        for event in events[offset:]:
            incremental_store.append(event)
        reads.synchronize(incremental_store)

    # This is a process-lifetime boundary for the read-store object, not merely
    # another reader on the already-open writer.
    with ReadStore.open(root, PASSPHRASE) as reopened:
        assert reopened.synchronize(EventStore.open(
            incremental_store.path, PASSPHRASE)).state == "equal"
        with reopened.open_reader() as revision:
            assert expected_tables == {table: _rows(revision.connection, table)
                                       for table in tables}
            assert expected_reads == {
                "goals": revision.goal_event_history(as_of="9999-12-31"),
                "goal_proposals": revision.goal_proposal_history(as_of="9999-12-31"),
                "turns": revision.conversation_turn_history(as_of="9999-12-31"),
                "conversation_proposals": revision.conversation_proposal_history(
                    as_of="9999-12-31"),
            }


def _rows(connection, table):
    return connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()


def test_normalized_families_are_lossless_without_event_body_mirror(tmp_path: Path):
    events = _corpus(); canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        assert reads.synchronize(canonical).applied_count == len(events)
        with reads.open_reader() as revision:
            db = revision.connection
            assert db.execute("SELECT name FROM sqlite_master WHERE name='materialized_events'").fetchone() is None
            account = db.execute("SELECT event_type,account_id,occurred_at,kind,name,currency,"
                                 "jurisdiction,institution,account_number,origin,provenance_doc_id,"
                                 "provenance_page,provenance_region,provenance_note FROM accounts "
                                 "WHERE event_type='AccountOpened'").fetchone()
            assert account == ("AccountOpened", "acct-α", "2025-12-31", "brokerage",
                               "Investments 🧭", "USD", "US", "Bänk", "000123",
                               "issued", "声明-1", 7, "余额", "café ☕")
            assert db.execute("SELECT name FROM account_names ORDER BY source_sequence,name_index").fetchall() == [("李雷",), ("李雷",), ("Léa",)]
            assert db.execute("SELECT description FROM transactions").fetchone() == ("Café 東京",)
            assert db.execute("SELECT tag FROM transaction_tags ORDER BY tag_index").fetchall() == [("travel",), ("travel",), ("家",)]
            assert db.execute("SELECT amount_text,grade FROM postings ORDER BY posting_index").fetchall() == [("-1E-18", "verified"), ("1E-18", "unverified")]
            assert db.execute("SELECT instrument_id,quantity_text,value_text,currency,cost_basis_text,valuation_class,grade FROM positions ORDER BY source_sequence").fetchall() == [
                ("FUND/世界", "-1.230000000000000000", "999999999999999999.000000000000000009", "JPY", "1E-18", "measured", "corroborated"),
                ("NO-BASIS", "2", "3", "USD", "", "measured", "corroborated")]
            assert db.execute("SELECT filename,byte_len,doc_type,doc_type_confidence_text FROM documents").fetchone() == ("résumé-账单.pdf", 1234, "bank_statement", "0.987654321")


def test_arbitrary_batches_backfills_duplicates_and_restart_have_identical_rows(tmp_path: Path):
    events = _corpus(); canonical = _event_store(tmp_path, events[:3]); root = tmp_path / "read-model"
    with ReadStore.create(root, PASSPHRASE) as reads:
        reads.synchronize(canonical)
        for event in events[3:]: canonical.append(event)
        assert reads.synchronize(canonical).state == "caught_up"
        with reads.open_reader() as revision:
            before = {table: _rows(revision.connection, table) for table in (
                "accounts", "account_names", "balance_observations", "transactions",
                "transaction_tags", "postings", "positions", "documents")}
    with ReadStore.open(root, PASSPHRASE) as reads:
        assert reads.synchronize(EventStore.open(canonical.path, PASSPHRASE)).state == "equal"
        with reads.open_reader() as revision:
            assert before == {table: _rows(revision.connection, table) for table in before}


def _document_review_corpus():
    source = Provenance("doc-statement", 0, "summary", "issuer")
    return [
        document_captured("doc-statement", "statement.pdf", 42,
                          "checking_statement", .99, "2026-01-01", source),
        read_recorded("doc-statement", "route", "prompt-v1", "text", "{}",
                      0, 0, 0, True, None, "2026-01-02", source,
                      usage_reported=False),
        account_opened("checking", "depository", "Checking", "USD",
                       "2026-01-01", provenance=source),
        opening_balance_observed("checking", "10.00", "2026-01-01", source),
        transaction_recorded(
            [Posting("checking", "-2.00", "verified"),
             Posting("Expenses:Food", "2.00")],
            "Lunch", "2026-01-15", provenance=source),
        statement_held("doc-statement", {"account": "checking"},
                       {"kind": "gap"}, "gap", "2026-01-20", source),
        closing_balance_observed("checking", "8.00", "2026-01-31", source,
                                 confirmed_by="human"),
        closing_balance_observed(
            "checking", "8.50", "2026-01-31",
            Provenance("doc-later-copy", 0, "summary", "duplicate period")),
        correction_applied("doc-statement", "closing", "7.00", "8.00",
                           "2026-02-01", provenance=source),
        Event("QuestionDeclined", "2026-02-02", {
            "question_id": "question:gap", "kind": "held_statement",
            "reason": "not_now", "amount": "0", "count": 1,
            "pack_version": "v1", "by": "human"}, source),
        Event("FindingSetAside", "2026-02-03", {
            "finding_id": "finding:fee", "kind": "fee_observed",
            "stake": {"version": "obligations-v1", "amount": "2.00"},
            "by": "human"}, source),
        Event("RulingRecorded", "2026-02-04", {
            "scope": "rhythm", "subject": "merchant:lunch", "legs": [],
            "by": "human", "grade": "verified", "said": "monthly",
            "corroborates": "", "same_as": "", "value": "monthly",
            "currency": "USD", "prompt_version": ""}, source),
    ]


def test_document_period_obligation_and_review_histories_match_event_fold(tmp_path: Path):
    events = _document_review_corpus()
    canonical = _event_store(tmp_path, events)
    oracle = LedgerProjection(events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            # Opening/transaction facts already posted this document. A later
            # hold cannot make accepted ledger facts appear unposted.
            assert revision.document_state_history(as_of="2026-01-19")[0]["state"] == "posted"
            assert revision.document_state_history(as_of="2026-01-20")[0]["state"] == "posted"
            current = revision.document_state_history(as_of="9999-12-31")[0]
            assert current["state"] == "posted"
            assert bool(current["read_attempted"]) == (
                "doc-statement" in oracle.read_attempted_docs())
            assert bool(current["read_parsed"]) == (
                "doc-statement" in oracle.read_parsed_docs())
            periods = revision.statement_period_history(as_of="9999-12-31")
            assert [row["closing_amount_text"] for row in periods] == ["8.50", "8.00"]
            coverage = revision.statement_coverage(as_of="9999-12-31")
            assert [(row["doc_id"], row["account_id"], row["period_end"],
                     row["closing_amount_text"]) for row in coverage] == [
                         ("doc-statement", "checking", "2026-01-31", "8.00")]
            assert oracle.posted_period("checking", "2026-01-31") == (
                "doc-statement", "8.00")
            reviews = revision.review_decision_history(as_of="9999-12-31")
            assert [row["status"] for row in reviews] == [
                "ruled", "set_aside", "declined", "corrected"]
            assert revision.obligation_control_history(as_of="9999-12-31")[0][
                "subject"] == "merchant:lunch"
            assert set(oracle.declined_questions()) == {"question:gap"}
            assert set(oracle.finding_set_asides()) == {"finding:fee"}


def test_document_review_materialization_is_batch_invariant_and_keyset_complete(tmp_path: Path):
    events = _document_review_corpus()
    (tmp_path / "full").mkdir(); (tmp_path / "split").mkdir()
    all_at_once = _event_store(tmp_path / "full", events)
    split = _event_store(tmp_path / "split", events[:4])
    with ReadStore.create(tmp_path / "full-read", PASSPHRASE) as full_reads:
        full_reads.synchronize(all_at_once)
        with full_reads.open_reader() as reader:
            expected = {table: _rows(reader.connection, table) for table in (
                "statement_periods", "posted_document_events", "review_decisions")}
    with ReadStore.create(tmp_path / "split-read", PASSPHRASE) as split_reads:
        split_reads.synchronize(split)
        for event in events[4:]:
            split.append(event)
        split_reads.synchronize(split)
        with split_reads.open_reader() as reader:
            assert expected == {table: _rows(reader.connection, table) for table in expected}
            seen = []
            before = None
            while True:
                page = reader.review_decision_history(
                    as_of="9999-12-31", limit=1, before=before)
                if not page:
                    break
                seen.extend(row["source_sequence"] for row in page)
                before = (page[-1]["occurred_at"], page[-1]["source_sequence"])
            assert seen == sorted(seen, reverse=True)
            assert len(seen) == len(set(seen)) == 4


@pytest.mark.parametrize("table,wrong_type", [
    ("statement_periods", "QuestionDeclined"),
    ("posted_document_events", "FindingSetAside"),
    ("review_decisions", "ClosingBalanceObserved"),
])
def test_document_review_rows_bind_exact_authenticated_event_family(
        tmp_path: Path, table: str, wrong_type: str):
    canonical = _event_store(tmp_path, _document_review_corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        def substitute(db):
            sequence = db.execute(
                f"SELECT source_sequence FROM {table} LIMIT 1").fetchone()[0]
            db.execute("UPDATE applied_events SET event_type=? WHERE sequence=?",
                       (wrong_type, sequence))
        with pytest.raises(read_store_module.sqlcipher.IntegrityError,
                           match="FOREIGN KEY constraint failed"):
            reads.publish(substitute, copy_current=True)


def test_document_period_review_and_obligation_queries_use_named_indexes(tmp_path: Path):
    events = _document_review_corpus()
    source = Provenance("doc-statement", 1, "rows", "synthetic")
    for number in range(250):
        day = f"2026-{number % 12 + 1:02d}-{number % 28 + 1:02d}"
        document_source = Provenance(
            f"doc-bulk-{number:04d}", 1, "summary", "synthetic")
        events.extend([
            document_captured(
                document_source.doc_id, f"bulk-{number:04d}.pdf", 100 + number,
                "checking_statement", .9, day, document_source),
            closing_balance_observed(
                "checking", str(number), day, document_source,
                confirmed_by="human"),
            Event("QuestionDeclined", day, {
                "question_id": f"question:{number}", "kind": "synthetic",
                "reason": "not_now", "amount": "0", "count": number,
                "pack_version": "v1", "by": "human"}, source),
            Event("RulingRecorded", day, {
                "scope": "rhythm", "subject": f"rhythm:{number}", "legs": [],
                "by": "human", "grade": "verified", "said": "monthly",
                "corroborates": "", "same_as": "", "value": "monthly",
                "currency": "USD", "prompt_version": ""}, source),
        ])
    for number in range(3):
        events.extend([
            read_recorded(
                "doc-statement", "route", "prompt-v1", "text", "{}",
                0, 1, 1, True, None, f"2026-11-{number + 1:02d}", source,
                usage_reported=True),
            statement_held(
                "doc-statement", {"row": number}, None, "synthetic",
                f"2026-11-{number + 1:02d}", source),
        ])
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            def public_plan(call):
                statements = []
                revision.connection.set_trace_callback(statements.append)
                try:
                    rows = call()
                finally:
                    revision.connection.set_trace_callback(None)
                assert len(rows) > 1
                query = next(statement for statement in reversed(statements)
                             if statement.startswith(("SELECT ", "WITH ")))
                return " ".join(row[3] for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + query))

            ordered_plans = [
                ("statement_periods_by_period_order", lambda: revision.statement_period_history(
                    as_of="9999-12-31", limit=50)),
                ("statement_periods_by_period_order", lambda: revision.statement_period_history(
                    as_of="9999-12-31", limit=50,
                    before=("2026-12-28", 10_000))),
                ("statement_periods_by_account_date", lambda: revision.statement_period_history(
                    as_of="9999-12-31", limit=50, account_id="checking")),
                ("statement_periods_by_account_date", lambda: revision.statement_period_history(
                    as_of="9999-12-31", limit=50, account_id="checking",
                    before=("2026-12-28", 10_000))),
                ("documents_by_date_keyset", lambda: revision.document_history(
                    as_of="9999-12-31", limit=50)),
                ("documents_by_date_keyset", lambda: revision.document_history(
                    as_of="9999-12-31", limit=50,
                    before=("2026-12-28", 10_000))),
                ("documents_by_date_keyset", lambda: revision.document_state_history(
                    as_of="9999-12-31", limit=50)),
                ("documents_by_date_keyset", lambda: revision.document_state_history(
                    as_of="9999-12-31", limit=50,
                    before=("2026-12-28", 10_000))),
                ("document_reads_by_doc_date", lambda: revision.document_read_history(
                    "doc-statement", as_of="9999-12-31", limit=50)),
                ("document_holds_by_doc_date", lambda: revision.document_hold_history(
                    "doc-statement", as_of="9999-12-31", limit=50)),
                ("review_decisions_by_order", lambda: revision.review_decision_history(
                    as_of="9999-12-31", limit=50)),
                ("review_decisions_by_order", lambda: revision.review_decision_history(
                    as_of="9999-12-31", limit=50,
                    before=("2026-12-28", 10_000))),
                ("review_decisions_by_status_order", lambda: revision.review_decision_history(
                    as_of="9999-12-31", limit=50, status="declined")),
                ("review_decisions_by_status_order", lambda: revision.review_decision_history(
                    as_of="9999-12-31", limit=50, status="declined",
                    before=("2026-12-28", 10_000))),
                ("ruling_history_by_scope_order", lambda: revision.obligation_control_history(
                    as_of="9999-12-31", limit=50)),
                ("ruling_history_by_scope_order", lambda: revision.obligation_control_history(
                    as_of="9999-12-31", limit=50,
                    before=("2026-12-28", 10_000))),
            ]
            for index, call in ordered_plans:
                detail = public_plan(call)
                assert f"USING INDEX {index}" in detail, detail
                assert "TEMP B-TREE" not in detail, detail

            state_detail = public_plan(lambda: revision.document_state_history(
                as_of="9999-12-31", limit=50))
            for index in (
                "statement_periods_by_document_date",
                "posted_document_events_by_doc_date",
                "document_holds_by_doc_date",
                "document_reads_by_doc_date",
            ):
                assert f"INDEX {index}" in state_detail, state_detail

            # Coverage's grouped first-writer rule needs both a grouping pass and
            # a final cross-account order. Its public contract does not promise a
            # sort-free plan, but it must use the statement account/period index.
            for before in (None, ("2026-12-28", "checking", 10_000)):
                detail = public_plan(lambda before=before: revision.statement_coverage(
                    as_of="9999-12-31", limit=50, before=before))
                assert "INDEX statement_periods_by_account_date" in detail, detail


def test_revision_binds_registered_resolver_identity(tmp_path: Path):
    canonical = _event_store(tmp_path, _corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        with pytest.raises(ReadStoreError, match="not registered"):
            reads.synchronize(canonical, resolver_version="resolver-v2")
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            assert revision.resolver_version == "resolver-v1"
            assert callable(revision.resolver(expected_version="resolver-v1"))
            with pytest.raises(ReadStoreError, match="not 'resolver-v2'"):
                revision.resolver(expected_version="resolver-v2")


def test_resolver_snapshot_hash_has_versioned_domain_and_semantic_binding():
    rows = (("Example Bank", "depository", '{"id":"profile-v1"}'),)
    payload = read_store_module._canonical({
        "schema_version": read_store_module.CONTROL_SCHEMA_VERSION,
        "projector_version": read_store_module.PROJECTOR_VERSION,
        "resolver_version": read_store_module.RESOLVER_VERSION,
        "profiles": rows,
    })

    actual = read_store_module._resolver_snapshot_hash(rows)

    assert actual != hashlib.sha256(payload).hexdigest()
    assert actual != read_store_module._resolver_snapshot_hash(
        rows, domain=b"different-resolver-snapshot-domain-v1\0")
    assert actual != read_store_module._resolver_snapshot_hash(
        rows, projector_version="different-projector-v1")


@pytest.mark.parametrize("mutation", ["altered", "missing", "extra_duplicate_identity"])
def test_encrypted_generation_resolver_row_tampering_refuses_open_and_rebuilds(
        tmp_path: Path, monkeypatch, mutation: str):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setenv("VIVA_PROFILES", str(profiles))
    profile_store = ProfileStore(profiles)
    institution = "Tamper Test Bank"
    profile = Profile(institution, "depository", "v1",
                      templates=[Template("PAY {brand}")])
    profile_store.write(profile)
    canonical = _event_store(tmp_path, _corpus())
    root = tmp_path / "read-model"

    with ReadStore.create(root, PASSPHRASE) as reads:
        reads.synchronize(canonical)
        database = root / "generations" / reads.current_generation / "projection.db"
        connection = read_store_module._connect(database, reads._database_key)
        if mutation == "altered":
            altered = Profile(institution, "depository", "v2",
                              templates=[Template("PAY {counterparty}")])
            connection.execute(
                "UPDATE resolver_profiles SET profile_json=?",
                (read_store_module._canonical(altered.to_dict()).decode(),))
        elif mutation == "missing":
            connection.execute("DELETE FROM resolver_profiles")
        else:
            connection.execute(
                "INSERT INTO resolver_profiles(institution, account_kind, profile_json) "
                "SELECT institution || ' duplicate', account_kind, profile_json "
                "FROM resolver_profiles LIMIT 1")
        connection.commit()
        connection.close()

    with pytest.raises(ReadStoreError, match="resolver snapshot|source revision"):
        ReadStore.open(root, PASSPHRASE)

    with ReadStore.open_for_recovery(root, PASSPHRASE) as recovering:
        assert recovering.synchronize(canonical).state == "rebuilt"
        with recovering.open_reader() as revision:
            assert revision.connection.execute(
                "SELECT institution, account_kind FROM resolver_profiles"
            ).fetchall() == [(institution, "depository")]


def test_open_revision_uses_frozen_profiles_and_profile_change_rebuilds(
        tmp_path: Path, monkeypatch):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setenv("VIVA_PROFILES", str(profiles))
    store = ProfileStore(profiles)
    institution = "Revision Stability Bank"
    store.write(Profile(institution, "depository", "v1",
                        templates=[Template("PAY {brand}")]))
    canonical = _event_store(tmp_path, _corpus())
    inputs = [("acct", institution, "depository", "PAY ALICE")]

    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        old_generation = reads.current_generation
        revision = reads.open_reader()
        old_resolver = revision.resolver()
        old_answer = old_resolver(inputs)
        old_hash = revision.connection.execute(
            "SELECT resolver_content_hash FROM projection_meta").fetchone()[0]

        store.write(Profile(institution, "depository", "v2",
                            templates=[Template("PAY {counterparty}")]))
        assert old_resolver(inputs) == old_answer
        assert old_resolver(inputs).persons == frozenset()

        result = reads.synchronize(canonical)
        assert result.state == "rebuilt"
        assert result.generation != old_generation
        assert revision.resolver()(inputs).persons == frozenset()
        with reads.open_reader() as current:
            assert current.connection.execute(
                "SELECT resolver_content_hash FROM projection_meta").fetchone()[0] != old_hash
            assert current.resolver()(inputs).persons == frozenset(
                {("acct", "PAY ALICE")})
        revision.close()


@pytest.mark.parametrize("table,wrong_type", [
    ("accounts", "OpeningBalanceObserved"),
    ("balance_observations", "AccountOpened"),
    ("transactions", "DocumentCaptured"),
    ("positions", "TransactionRecorded"),
    ("documents", "PositionObserved"),
])
def test_every_materialized_family_is_bound_to_its_canonical_event(
        tmp_path: Path, table: str, wrong_type: str):
    canonical = _event_store(tmp_path, _corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        before = reads.current_generation

        def substitute(db):
            sequence = db.execute(f"SELECT source_sequence FROM {table} LIMIT 1").fetchone()[0]
            db.execute("UPDATE applied_events SET event_type=? WHERE sequence=?",
                       (wrong_type, sequence))

        with pytest.raises(read_store_module.sqlcipher.IntegrityError,
                           match="FOREIGN KEY constraint failed"):
            reads.publish(substitute, copy_current=True)
        assert reads.current_generation == before
        with reads.open_reader() as revision:
            assert revision.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_applied_event_family_digest_tampering_forces_rebuild(tmp_path: Path):
    canonical = _event_store(tmp_path, _corpus() + [
        Event("FutureUnknown", "2026-02-03", {"target": "synthetic"})])
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)

        def tamper_unmaterialized_family(db):
            db.execute("UPDATE applied_events SET event_type='DocumentCaptured' "
                       "WHERE event_type='FutureUnknown'")

        reads.publish(tamper_unmaterialized_family, copy_current=True)
        assert reads.synchronize(canonical).state == "rebuilt"
        with reads.open_reader() as revision:
            assert revision.connection.execute(
                "SELECT event_type FROM applied_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone() == ("FutureUnknown",)
            assert revision.connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_as_of_boundaries_are_lexically_exact_in_normalized_history(tmp_path: Path):
    canonical = _event_store(tmp_path, _corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            query = "SELECT occurred_at FROM balance_observations WHERE occurred_at<=? ORDER BY occurred_at,source_sequence"
            assert revision.connection.execute(query, ("1900-01-01",)).fetchall() == []
            assert revision.connection.execute(query, ("2025-12-31",)).fetchall() == [("2025-12-31",)]
            assert revision.connection.execute(query, ("2026-01-15",)).fetchall() == [("2025-12-31",)]
            assert revision.connection.execute(query, ("9999-12-31",)).fetchall() == [("2025-12-31",), ("2026-01-31",)]


def test_named_queries_use_indexes_at_representative_cardinality(tmp_path: Path):
    events = _corpus()
    for number in range(250):
        account = f"bulk-{number:04d}"
        events.extend([
            account_opened(account, "depository", f"Account {number}", "USD", "2026-01-01"),
            opening_balance_observed(account, str(number), "2026-01-01"),
            transaction_recorded([Posting(account, "-1"), Posting("Expenses:Bulk", "1")], f"row {number}", "2026-01-02"),
            position_observed(account, "FUND", "1", str(number), "USD", "2026-01-31"),
            document_captured(f"doc-{number}", f"{number}.pdf", number, "statement", .9, "2026-01-31"),
        ])
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            plans = {
                "accounts_by_identity": ("SELECT * FROM accounts WHERE account_id=? ORDER BY occurred_at,source_sequence", ("bulk-0249",)),
                "observations_by_account_date": ("SELECT * FROM balance_observations WHERE account_id=? AND occurred_at<=? ORDER BY occurred_at,source_sequence", ("bulk-0249", "2026-12-31")),
                "postings_by_account": ("SELECT * FROM postings WHERE account_id=? ORDER BY source_sequence,posting_index", ("bulk-0249",)),
                "positions_by_account_date": ("SELECT * FROM positions WHERE account_id=? AND occurred_at<=? ORDER BY occurred_at,source_sequence", ("bulk-0249", "2026-12-31")),
                "documents_by_state_date": ("SELECT * FROM documents WHERE state=? AND occurred_at<=? ORDER BY occurred_at,source_sequence", ("captured", "2026-12-31")),
            }
            for index, (query, parameters) in plans.items():
                detail = " ".join(row[3] for row in revision.connection.execute("EXPLAIN QUERY PLAN " + query, parameters))
                assert f"USING INDEX {index}" in detail, detail


def test_constraints_have_no_orphans(tmp_path: Path):
    canonical = _event_store(tmp_path, _corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            assert revision.connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert revision.connection.execute("SELECT COUNT(*) FROM postings p LEFT JOIN transactions t ON t.source_sequence=p.source_sequence WHERE t.source_sequence IS NULL").fetchone() == (0,)

        def add_orphan_posting(db):
            db.execute("INSERT INTO account_entities VALUES('orphan-account')")
            db.execute("INSERT INTO postings VALUES(999999,0,'orphan-account','1','verified')")

        with pytest.raises(read_store_module.sqlcipher.IntegrityError,
                           match="FOREIGN KEY constraint failed"):
            reads.publish(add_orphan_posting, copy_current=True)


def test_movement_rows_match_projection_keys_and_survive_incremental_backfill(tmp_path: Path):
    source = Provenance(doc_id="doc-東京", page=2, region="table", note="café")
    base = [
        account_opened("checking", "depository", "Checking", "USD", "2026-01-01",
                       provenance=source),
        transaction_recorded([Posting("checking", "-12.3400", "verified"),
                              Posting("Expenses:Uncategorized", "12.3400")],
                             "Café 東京", "2026-02-01", provenance=source),
        transaction_recorded([Posting("checking", "-12.3400", "corroborated"),
                              Posting("Expenses:Uncategorized", "12.3400")],
                             "Café 東京", "2026-02-01", provenance=source),
    ]
    oracle = LedgerProjection(base)
    keys = [movement.key for movement in oracle.movements()]
    overlays = [
        category_assigned(keys[0], "Café 東京", "Dining", "verified",
                          "2026-02-02", subcategory="Coffee", provenance=source),
        movement_tagged(keys[0], ["旅", "coffee"], "2026-02-03", provenance=source),
        transfer_suggested(keys[1], [keys[0]], {"why": "same"}, "2026-02-04"),
        transfer_linked(keys[0], keys[1], "verified", {"decided_by": "human"},
                        "2026-02-05", by="human"),
        transfer_unlinked(keys[0], keys[1], "2026-02-06"),
    ]
    canonical = _event_store(tmp_path, base)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        for event in overlays:
            canonical.append(event)
        assert reads.synchronize(canonical).state == "caught_up"
        with reads.open_reader() as revision:
            rows = revision.movement_history(as_of="9999-12-31")
            assert {row["movement_key"] for row in rows} == set(keys)
            categorized = next(row for row in rows if row["movement_key"] == keys[0])
            assert (categorized["amount_text"], categorized["currency"],
                    categorized["category"], categorized["subcategory"],
                    categorized["provenance_doc_id"]) == (
                        "-12.3400", "USD", "Dining", "coffee", "doc-東京")
            assert categorized["linked"] == 0
            assert revision.connection.execute(
                "SELECT tag,source FROM movement_tags WHERE movement_key=? ORDER BY tag",
                (keys[0],)).fetchall() == [("coffee", "movement"), ("旅", "movement")]
            assert revision.connection.execute(
                "SELECT event_type,status FROM transfer_history ORDER BY source_sequence"
            ).fetchall() == [("TransferSuggested", "suggested"),
                             ("TransferLinked", "linked"),
                             ("TransferUnlinked", "unlinked")]
            assert revision.transfer_links() == []
            assert revision.transfer_suggestions() == []


def _movement_overlay_events(provenance):
    base = [
        account_opened("overlay-account", "depository", "Overlay", "USD",
                       "2026-01-01", provenance=provenance),
        transaction_recorded(
            [Posting("overlay-account", "-1"), Posting("Expenses:X", "1")],
            "Overlay Merchant", "2026-01-02", provenance=provenance),
    ]
    key = LedgerProjection(base).movements()[0].key
    return base + [
        transfer_suggested(key, ["candidate"], {"why": "近い"}, "2026-01-03",
                           provenance=provenance),
        category_assigned(key, "Overlay Merchant", "Dining", "verified",
                          "2026-01-04", provenance=provenance),
        merchant_enriched("overlay merchant", "Dining", occurred_at="2026-01-05",
                          provenance=provenance),
        movement_tagged(key, ["旅"], "2026-01-06", provenance=provenance),
        ruling_recorded(SCOPE_MOVEMENT, key, "2026-01-07",
                        legs=[{"major": "expense"}], provenance=provenance),
        account_alias_confirmed("alias", "overlay-account", "doc-alias",
                                "2026-01-08", provenance=provenance),
    ]


@pytest.mark.parametrize("provenance,expected", [
    (Provenance(doc_id="文書-α", page=0, region="表:一", note="café ☕"),
     ("文書-α", 0, "表:一", "café ☕")),
    (Provenance(doc_id="", page=None, region="", note=""),
     ("", None, "", "")),
])
def test_movement_overlay_histories_preserve_all_provenance_fields(
        tmp_path: Path, provenance: Provenance, expected):
    canonical = _event_store(tmp_path, _movement_overlay_events(provenance))
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            for table in ("transfer_history", "category_history", "merchant_history",
                          "tag_history", "ruling_history", "account_alias_history"):
                row = revision.connection.execute(
                    f"SELECT provenance_doc_id,provenance_page,provenance_region,"
                    f"provenance_note FROM {table}").fetchone()
                assert row == expected, table


@pytest.mark.parametrize("table,wrong_type", [
    ("transfer_history", "CategoryAssigned"),
    ("category_history", "MerchantEnriched"),
    ("merchant_history", "MovementTagged"),
    ("tag_history", "RulingRecorded"),
    ("ruling_history", "AccountAliasConfirmed"),
    ("account_alias_history", "TransferSuggested"),
])
def test_movement_overlay_rows_are_bound_to_exact_event_family(
        tmp_path: Path, table: str, wrong_type: str):
    canonical = _event_store(
        tmp_path, _movement_overlay_events(Provenance(doc_id="doc-family")))
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        before = reads.current_generation

        def substitute(db):
            sequence = db.execute(
                f"SELECT source_sequence FROM {table} LIMIT 1").fetchone()[0]
            db.execute("UPDATE applied_events SET event_type=? WHERE sequence=?",
                       (wrong_type, sequence))

        with pytest.raises(read_store_module.sqlcipher.IntegrityError,
                           match="FOREIGN KEY constraint failed"):
            reads.publish(substitute, copy_current=True)
        assert reads.current_generation == before


def test_movement_named_query_is_bounded_and_indexed(tmp_path: Path):
    events = [account_opened("checking", "depository", "Checking", "USD", "2026-01-01")]
    for number in range(250):
        events.append(transaction_recorded(
            [Posting("checking", "-1"), Posting("Expenses:Bulk", "1")],
            f"merchant {number}", f"2026-02-{number % 28 + 1:02d}"))
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            assert len(revision.movement_history(as_of="9999-12-31", limit=17,
                                                 account="checking")) == 17
            detail = " ".join(row[3] for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM movements WHERE account_id=? "
                "AND occurred_at<=? ORDER BY occurred_at DESC,movement_key LIMIT ?",
                ("checking", "9999-12-31", 20)))
            assert "USING INDEX movements_by_account_date" in detail
            plans = {
                "movements_by_date": ("occurred_at<=?", ("9999-12-31",)),
                "movements_by_currency_date": ("currency=? AND occurred_at<=?", ("USD", "9999-12-31")),
                "movements_by_nature_date": ("nature=? AND occurred_at<=?", ("spending", "9999-12-31")),
                "movements_by_category_date": ("category=? AND occurred_at<=?", ("", "9999-12-31")),
                "movements_by_document_date": ("provenance_doc_id=? AND occurred_at<=?", ("", "9999-12-31")),
                "movements_by_merchant_date": ("merchant_key=? AND occurred_at<=?", ("merchant 1", "9999-12-31")),
            }
            for index, (where, parameters) in plans.items():
                detail = " ".join(row[3] for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN SELECT * FROM movements WHERE " + where +
                    " ORDER BY occurred_at DESC,movement_key LIMIT 20", parameters))
                assert f"USING INDEX {index}" in detail, detail
            stable = " ".join(row[3] for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM movements WHERE movement_key=? LIMIT 1",
                (revision.movement_history(as_of="9999-12-31", limit=1)[0]["movement_key"],)))
            assert "sqlite_autoindex_movements_1" in stable


def test_movement_history_keyset_pages_are_complete_stable_and_exclusive(
        tmp_path: Path):
    source = Provenance(doc_id="doc-pages", page=None, region="", note="")
    events = [account_opened("checking", "depository", "Checking", "USD",
                             "2026-01-01", provenance=source)]
    for number in range(67):
        events.append(transaction_recorded(
            [Posting("checking", "-1"), Posting("Expenses:Bulk", "1")],
            "Same Merchant", f"2026-02-{number % 3 + 1:02d}", provenance=source))
    keys = [movement.key for movement in LedgerProjection(events).movements()]
    events.extend(category_assigned(
        key, "Same Merchant", "Dining", "verified", "2026-03-01",
        provenance=source) for key in keys)
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            selector_cases = (
                {}, {"account": "checking"}, {"currency": "USD"},
                {"nature": "spending"}, {"category": "Dining"},
                {"document": "doc-pages"}, {"merchant": "same merchant"},
            )
            for selectors in selector_cases:
                expected = revision.movement_history(
                    as_of="2026-12-31", limit=200, **selectors)
                observed, before = [], None
                while True:
                    page = revision.movement_history(
                        as_of="2026-12-31", limit=7, before=before, **selectors)
                    if not page:
                        break
                    if before is not None:
                        assert (page[0]["occurred_at"] < before[0]
                                or (page[0]["occurred_at"] == before[0]
                                    and page[0]["movement_key"] > before[1]))
                    observed.extend(page)
                    before = (page[-1]["occurred_at"], page[-1]["movement_key"])
                assert observed == expected, selectors
                assert len({row["movement_key"] for row in observed}) == len(observed)

            one = revision.movement_history(
                as_of="2026-12-31", stable_id=keys[13], limit=1)
            assert [row["movement_key"] for row in one] == [keys[13]]
            cursor = (one[0]["occurred_at"], one[0]["movement_key"])
            assert revision.movement_history(
                as_of="2026-12-31", stable_id=keys[13], before=cursor) == []


@pytest.mark.parametrize("limit", [0, 201, True, False, 1.5])
def test_movement_history_refuses_invalid_limits(tmp_path: Path, limit):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        with reads.open_reader() as revision:
            with pytest.raises(ValueError, match="limit"):
                revision.movement_history(as_of="2026-12-31", limit=limit)


@pytest.mark.parametrize("cursor", [
    (), ("2026-01-01",), ("2026-01-01", "key", "extra"),
    ["2026-01-01", "key"], ("", "key"), ("2026-01-01", ""),
    (None, "key"), ("2026-01-01", 1),
])
def test_movement_history_refuses_invalid_cursors(tmp_path: Path, cursor):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        with reads.open_reader() as revision:
            with pytest.raises(ValueError, match="cursor"):
                revision.movement_history(as_of="2026-12-31", before=cursor)


def test_materialized_movement_semantics_match_projection_oracle(tmp_path: Path):
    source = Provenance(doc_id="doc-semantic", page=4, region="rows", note="résumé")
    base = [
        account_opened("bank", "depository", "Everyday", "USD", "2026-01-01",
                       institution="Bank", account_number="1111", provenance=source),
        account_opened("card", "liability", "My Visa", "USD", "2026-01-01",
                       institution="Issuer", account_number="4321", provenance=source),
        transaction_recorded([Posting("bank", "-10.00"), Posting("Expenses:X", "10.00")],
                             "SHOP ALPHA", "2026-01-02", provenance=source),
        transaction_recorded([Posting("bank", "-20.00"), Posting("Expenses:X", "20.00")],
                             "MY VISA 4321", "2026-01-03", provenance=source),
        transaction_recorded([Posting("card", "30.00"), Posting("Expenses:X", "-30.00")],
                             "LENDER BETA", "2026-01-04", provenance=source),
    ]
    initial = LedgerProjection(base); first, own, implied = initial.movements()
    events = base + [
        merchant_enriched("shop alpha", "Old", grade="verified", occurred_at="2026-01-05",
                          aliases=["shop alpha"], provenance=source),
        merchant_enriched("shop alpha", "New", grade="unverified", occurred_at="2026-01-06",
                          provenance=source),
        category_assigned(first.key, first.description, "Default", "unverified",
                          "2026-01-07", by="default", subcategory="Coffee-Shop",
                          provenance=source),
        movement_tagged("shop alpha", ["Trip"], "2026-01-08", scope=SCOPE_MERCHANT),
        ruling_recorded(SCOPE_TAG, "trip", "2026-01-09", same_as="travel"),
        ruling_recorded(SCOPE_CATEGORY, "coffee shop", "2026-01-10",
                        same_as="coffee"),
        merchant_enriched("lender beta", "Loans", attributes={
            "implies": [{"on": "outflow", "major": "liability",
                         "confidence": "suggested"}]}, occurred_at="2026-01-11",
                          provenance=source),
        ruling_recorded(SCOPE_MOVEMENT, first.key, "2026-01-12",
                        legs=[{"major": "asset", "account": "Assets:Thing"}],
                        provenance=source),
    ]
    oracle = LedgerProjection(events)
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            actual = {row["movement_key"]: row for row in revision.movement_history(
                as_of="9999-12-31")}
            for movement in oracle.movements():
                row = actual[movement.key]
                category = oracle.derived_category(movement) or {}
                assert (row["nature"], row["nature_reason"], bool(row["provisional"]),
                        row["ruling_account"], row["merchant_key"], row["category"],
                        row["subcategory"]) == (
                            movement.nature, movement.nature_reason, movement.provisional,
                            movement.ruling_account, oracle.merchant_key_of(movement),
                            category.get("category", ""), category.get("subcategory", ""))
                assert [tag for tag, in revision.connection.execute(
                    "SELECT tag FROM movement_tags WHERE movement_key=? ORDER BY tag",
                    (movement.key,))] == oracle.tags_of(movement)


def test_movement_projection_is_identical_across_arbitrary_suffix_batches(tmp_path: Path):
    source = Provenance(doc_id="doc-batch")
    base = [
        account_opened("a", "depository", "A", "EUR", "2026-01-01",
                       institution="Bänk", provenance=source),
        transaction_recorded([Posting("a", "-1.2300"), Posting("Expenses:X", "1.2300")],
                             "Mérchant 家", "2025-12-01", provenance=source),
        transaction_recorded([Posting("a", "-1.2300"), Posting("Expenses:X", "1.2300")],
                             "Mérchant 家", "2025-12-01", provenance=source),
    ]
    keys = [movement.key for movement in LedgerProjection(base).movements()]
    events = base + [
        merchant_enriched("mérchant 家", "Food", subcategory="Coffee Shop",
                          grade="corroborated", occurred_at="2026-01-02"),
        category_assigned(keys[0], "Mérchant 家", "Travel", "verified",
                          "2026-01-03", subcategory="Rail"),
        movement_tagged(keys[0], ["one", "二"], "2026-01-04"),
        transfer_suggested(keys[1], [keys[0]], {}, "2026-01-05"),
    ]
    expected = None
    for run, batches in enumerate(((len(events),), (1, 2, 1, 3), (3, 4))):
        canonical = EventStore.open(tmp_path / f"events-{run}.jsonl", PASSPHRASE)
        with ReadStore.create(tmp_path / f"read-{run}", PASSPHRASE) as reads:
            offset = 0
            for size in batches:
                for event in events[offset:offset + size]: canonical.append(event)
                offset += size; reads.synchronize(canonical)
            with reads.open_reader() as revision:
                observed = {table: _rows(revision.connection, table) for table in (
                    "movements", "movement_tags", "transfer_history", "transfer_links",
                    "transfer_suggestions", "category_history", "merchant_history",
                    "tag_history", "ruling_history")}
        if expected is None: expected = observed
        else: assert observed == expected


def _document_lifecycle():
    source = Provenance(doc_id="doc-生命周期", page=3, region="table:1", note="résumé")
    return [
        document_captured("doc-生命周期", "账单.pdf", 42, "bank_statement", .75,
                          "2026-01-01", source),
        read_recorded("doc-生命周期", "route-a", "prompt-v1", "pdf_text",
                      "{\"answer\":\"秘密\"}", .125, 0, 0, False, "bad shape",
                      "2026-01-02", source, phase="classify", resolved_model="provider-x",
                      usage_reported=False),
        read_recorded("doc-生命周期", "route-a", "prompt-v2", "pdf_text",
                      "{\"answer\":\"ok\"}", .25, 12, 4, True, None,
                      "2026-01-03", source, usage_reported=True),
        statement_held("doc-生命周期", {"rows": [{"amount": "1.2300"}]},
                       {"kind": "gap", "missing": None}, "gap", "2026-01-04", source),
        brokerage_activity_held("doc-生命周期", {"trades": ["α", "α"]}, None,
                                "2026-01-05", source),
        brokerage_activity_resolved("doc-生命周期", "2026-01-06", source),
        correction_applied("doc-生命周期", "closing", "1.2300", "1.2400",
                           "2026-01-07", provenance=source),
    ]


def test_document_lifecycle_histories_are_lossless_bounded_and_revision_local(tmp_path: Path):
    canonical = _event_store(tmp_path, _document_lifecycle())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            assert revision.document_history(as_of="2025-12-31") == []
            documents = revision.document_history(as_of="2026-12-31", limit=1)
            assert documents[0]["doc_id"] == "doc-生命周期"
            assert documents[0]["doc_type_confidence_text"] == "0.75"
            reads_history = revision.document_read_history(
                "doc-生命周期", as_of="2026-12-31")
            assert [row["phase"] for row in reads_history] == ["extract", "classify"]
            assert reads_history[0]["cost_usd_text"] == "0.25"
            assert reads_history[0]["usage_reported"] == 1
            assert reads_history[1]["usage_reported"] is None
            assert reads_history[1]["resolved_model"] == "provider-x"
            holds = revision.document_hold_history(
                "doc-生命周期", as_of="2026-12-31")
            assert [row["event_type"] for row in holds] == [
                "BrokerageActivityHeld", "StatementHeld"]
            assert holds[0]["facts_json"] == '{"trades":["\\u03b1","\\u03b1"]}'
            assert holds[0]["finding_json"] is None
            assert holds[1]["facts_json"] == '{"rows":[{"amount":"1.2300"}]}'
            assert holds[1]["finding_json"] == '{"kind":"gap","missing":null}'
            db = revision.connection
            assert db.execute(
                "SELECT doc_id FROM document_hold_resolutions").fetchall() == [
                    ("doc-生命周期",)]
            assert db.execute(
                "SELECT target,from_value,to_value,decided_by FROM document_corrections"
            ).fetchall() == [("closing", "1.2300", "1.2400", "human")]
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_document_history_keyset_and_named_queries_use_indexes(tmp_path: Path):
    events = []
    for number in range(250):
        doc_id = f"doc-{number:04d}"
        events.extend([
            document_captured(doc_id, f"{number}.pdf", number, "statement", .9,
                              f"2026-01-{number % 28 + 1:02d}"),
            read_recorded(doc_id, "route", "v1", "text", "{}", 0, 1, 1,
                          True, None, f"2026-02-{number % 28 + 1:02d}"),
            statement_held(doc_id, {"row": number}, None, "gap",
                           f"2026-03-{number % 28 + 1:02d}"),
        ])
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            first = revision.document_history(as_of="2026-12-31", limit=17)
            anchor = (first[-1]["occurred_at"], first[-1]["source_sequence"])
            second = revision.document_history(
                as_of="2026-12-31", limit=17, before=anchor)
            assert len(first) == len(second) == 17
            assert {row["source_sequence"] for row in first}.isdisjoint(
                row["source_sequence"] for row in second)
            plans = {
                "documents_by_date_keyset": (
                    "SELECT * FROM documents WHERE occurred_at<=? "
                    "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
                    ("2026-12-31", 17)),
                "document_reads_by_doc_date": (
                    "SELECT * FROM document_reads WHERE doc_id=? AND occurred_at<=? "
                    "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
                    ("doc-0249", "2026-12-31", 17)),
                "document_holds_by_doc_date": (
                    "SELECT * FROM document_holds WHERE doc_id=? AND occurred_at<=? "
                    "ORDER BY occurred_at DESC,source_sequence DESC LIMIT ?",
                    ("doc-0249", "2026-12-31", 17)),
            }
            for index, (query, parameters) in plans.items():
                detail = " ".join(row[3] for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + query, parameters))
                assert f"USING INDEX {index}" in detail, detail


def test_document_lifecycle_incremental_batches_equal_complete_replay(tmp_path: Path):
    events = _document_lifecycle()
    incremental_path = tmp_path / "incremental"
    complete_path = tmp_path / "complete"
    incremental_path.mkdir(); complete_path.mkdir()
    incremental = _event_store(incremental_path, events[:2])
    with ReadStore.create(incremental_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(incremental)
        for event in events[2:5]:
            incremental.append(event)
            assert reads.synchronize(incremental).state == "caught_up"
        for event in events[5:]:
            incremental.append(event)
        assert reads.synchronize(incremental).state == "caught_up"
        with reads.open_reader() as revision:
            incremental_rows = {table: _rows(revision.connection, table) for table in (
                "documents", "document_reads", "document_holds",
                "document_hold_resolutions", "document_corrections")}

    complete = _event_store(complete_path, events)
    with ReadStore.create(complete_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(complete)
        with reads.open_reader() as revision:
            assert incremental_rows == {table: _rows(revision.connection, table)
                                        for table in incremental_rows}


@pytest.mark.parametrize("table,wrong_type", [
    ("document_reads", "DocumentCaptured"),
    ("document_holds", "ReadRecorded"),
    ("document_hold_resolutions", "StatementHeld"),
    ("document_corrections", "BrokerageActivityResolved"),
])
def test_document_lifecycle_rows_are_bound_to_exact_event_family(
        tmp_path: Path, table: str, wrong_type: str):
    canonical = _event_store(tmp_path, _document_lifecycle())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        before = reads.current_generation

        def substitute(db):
            sequence = db.execute(
                f"SELECT source_sequence FROM {table} LIMIT 1").fetchone()[0]
            db.execute("UPDATE applied_events SET event_type=? WHERE sequence=?",
                       (wrong_type, sequence))

        with pytest.raises(read_store_module.sqlcipher.IntegrityError,
                           match="FOREIGN KEY constraint failed"):
            reads.publish(substitute, copy_current=True)
        assert reads.current_generation == before


@pytest.mark.parametrize("method,arguments", [
    ("document_history", {"as_of": "2026-12-31", "limit": 0}),
    ("document_history", {"as_of": "2026-12-31", "limit": 201}),
    ("document_read_history", {"doc_id": "doc", "as_of": "2026-12-31", "limit": 51}),
    ("document_hold_history", {"doc_id": "doc", "as_of": "2026-12-31", "limit": 0}),
])
def test_document_named_reads_refuse_unbounded_limits(tmp_path: Path, method, arguments):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        with reads.open_reader() as revision:
            with pytest.raises(ValueError, match="limit"):
                getattr(revision, method)(**arguments)
