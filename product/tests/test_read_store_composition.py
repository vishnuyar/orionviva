"""Parity and bounds for final SQL-native current semantic composition."""
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from viva.ledger import (EventStore, LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, goal_created,
                         goal_funds_released, goal_funds_reserved,
                         goal_state_changed, simple_transaction)
from viva.ledger.events import (CORROBORATED, finding_set_aside,
                                category_assigned, merchant_enriched, question_declined,
                                transfer_linked, transfer_suggested)
from viva.read_store import ReadStore
from viva.read_store import composition
from viva.read_store import questions as sql_questions
from viva.read_store import store as read_store_module
from viva.read_store.rhythm import RhythmReadError
from viva.questions import open_questions


PASSPHRASE = "correct horse battery staple"


def _normal(value):
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: _normal(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normal(item) for item in value]
    return str(value) if value.__class__.__name__ == "Decimal" else value


def _events():
    provenance = Provenance("statement", 1, "balance", "issuer")
    events = [account_opened("cash", "depository", "Cash", "USD", "2025-12-01",
                             origin="issued", provenance=provenance),
              closing_balance_observed("cash", "1000.00", "2026-04-30", provenance)]
    events += [simple_transaction("cash", "-10.00", "LUMEN STREAMING", when,
                                  kind="depository", provenance=provenance)
               for when in ("2026-01-05", "2026-02-05", "2026-03-05", "2026-04-05")]
    events.append(merchant_enriched(
        "lumen streaming", "Subscriptions", grade=CORROBORATED,
        occurred_at="2026-04-06", by="model",
        attributes={"counterparty_kind": "business", "billing": "standing",
                    "billing_period": "monthly"}))
    return events


def _composition_events():
    """Return a varied corpus exercising the complete 4M compositions."""
    issued = Provenance("statement-α", 2, "closing", "issuer evidence")
    events = [
        account_opened("cash-us", "depository", "Daily ☕", "USD", "2025-11-01",
                       institution="North", origin="issued", provenance=issued),
        account_opened("cash-eu", "depository", "Travel", "EUR", "2025-11-01",
                       origin="issued", provenance=issued),
        account_opened("asserted", "depository", "Envelope", "USD", "2025-11-01",
                       origin="asserted"),
        account_opened("broker", "investment", "Broker", "USD", "2025-11-01"),
        closing_balance_observed("cash-us", "1800.1250", "2026-04-30", issued),
        closing_balance_observed("cash-eu", "400.50", "2026-04-29", issued),
        closing_balance_observed("asserted", "900", "2026-04-30"),
        # The broker has no closing balance, producing missing coverage and
        # non-depository exclusion therefore participate in the full payload.
    ]
    for month, amount in ((1, "-79.99"), (2, "-81.25"), (3, "-80.00"), (4, "-82.50")):
        events.extend((
            simple_transaction("cash-us", amount, "NORTH LOAN", f"2026-{month:02d}-05",
                               kind="depository", provenance=issued),
            simple_transaction("cash-us", "2500", "ACME PAY", f"2026-{month:02d}-15",
                               kind="depository", provenance=issued),
        ))
    events.extend((
        simple_transaction("cash-eu", "-19.95", "CAFÉ FUTUR", "2026-04-09",
                           kind="depository", provenance=issued),
        merchant_enriched("north loan", "Debt", grade=CORROBORATED,
                          occurred_at="2026-04-20", by="model",
                          attributes={"counterparty_kind": "business", "billing": "standing",
                                      "billing_period": "monthly"}),
        merchant_enriched("acme pay", "Income", grade=CORROBORATED,
                          occurred_at="2026-04-20", by="model",
                          attributes={"counterparty_kind": "business", "billing": "standing",
                                      "billing_period": "monthly"}),
        # A later source event backfills an earlier semantic correction.
        merchant_enriched("north loan", "Debt", grade=CORROBORATED,
                          occurred_at="2026-03-01", by="human",
                          attributes={"counterparty_kind": "business", "billing": "standing",
                                      "billing_period": "monthly"}),
        goal_created("rainy", "Rainy day", "USD", "1200", "2026-01-01",
                     target_date="2026-12-31", monthly_contribution="100",
                     contribution_day=10),
        goal_created("trip", "Voyage", "EUR", "500", "2026-01-02",
                     monthly_contribution="25", contribution_day=20),
        goal_funds_reserved("rainy", "cash-us", "300.1250", "2026-01-03"),
        goal_funds_reserved("trip", "cash-eu", "100", "2026-01-04"),
        goal_funds_released("rainy", "cash-us", "75", "reassigned", "2026-02-01"),
        # Over-release clamps the reservation at zero.
        goal_funds_released("trip", "cash-eu", "1000", "used_elsewhere", "2026-02-02"),
        goal_state_changed("trip", "paused", "2026-02-03"),
    ))
    return events


def _store(path: Path, events):
    source = EventStore.open(path / "events.jsonl", PASSPHRASE)
    source.append_atomically(lambda _existing: tuple(events))
    return source


def _complete_payload(revision):
    return {
        "findings": _normal(revision.findings(today="2026-05-01")),
        "current_period": _normal(revision.current_period(today="2026-05-01")),
        "questions": revision.open_questions(
            as_of="2026-05-01", locale="en-US", limit=None),
    }


def _canonical_payload(events):
    projection = LedgerProjection(events)
    expected_questions = open_questions(
        projection, as_of="2026-05-01", locale="en-US", limit=None)
    supported = {"transfer", "merchant", "nature", "rhythm",
                 "corroboration", "expectation", "interview"}
    expected_questions["questions"] = [
        row for row in expected_questions["questions"] if row["kind"] in supported]
    expected_questions["total"] = len(expected_questions["questions"])
    expected_questions["tail"] = {"count": 0, "amount": "0"}
    return {
        "findings": _normal(projection.findings("2026-05-01")),
        "current_period": _normal(projection.current_period("2026-05-01")),
        "questions": expected_questions,
    }


def test_findings_and_current_period_match_canonical(tmp_path: Path):
    events = _events()
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual_findings = revision.findings(today="2026-05-01")
            actual_period = revision.current_period(today="2026-05-01")
    oracle = LedgerProjection(events, as_of="2026-05-01")
    assert _normal(actual_findings) == _normal(oracle.findings("2026-05-01"))
    assert _normal(actual_period) == _normal(oracle.current_period("2026-05-01"))


@pytest.mark.parametrize("cuts", [(1, 4, 11), (7, 19), (2, 3, 5, 13, 21)])
def test_complete_composition_payload_survives_suffix_partitions_restart_and_reader_isolation(
        tmp_path: Path, cuts):
    events = _composition_events()
    expected = _canonical_payload(events)
    source = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    root = tmp_path / "read-model"
    reads = ReadStore.create(root, PASSPHRASE)
    cursor = 0
    held = None
    for end in (*cuts, len(events)):
        end = min(end, len(events))
        source.append_atomically(lambda _existing, batch=tuple(events[cursor:end]): batch)
        reads.synchronize(source)
        if held is None:
            held = reads.open_reader()
            held_payload = _complete_payload(held)
        cursor = end
    with reads.open_reader() as current:
        assert _complete_payload(current) == expected
    # A reader stays bound to the exact revision it opened, despite later suffixes.
    assert _complete_payload(held) == held_payload
    held.close()
    reads.close()
    with ReadStore.open(root, PASSPHRASE) as reopened:
        assert reopened.synchronize(EventStore.open(source.path, PASSPHRASE)).state == "equal"
        with reopened.open_reader() as revision:
            assert _complete_payload(revision) == expected


def test_actionable_sql_question_families_match_canonical(tmp_path: Path):
    events = _events()
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = revision.open_questions(
                as_of="2026-05-01", locale="en-US", limit=None)
    expected = open_questions(
        LedgerProjection(events), as_of="2026-05-01", jurisdiction="US",
        locale="en-US", limit=None)
    supported = {"transfer", "merchant", "nature", "rhythm", "interview"}
    expected["questions"] = [row for row in expected["questions"]
                             if row["kind"] in supported]
    expected["total"] = len(expected["questions"])
    expected["tail"] = {"count": 0, "amount": "0"}
    assert actual == expected


def test_question_family_temporal_scope_matches_canonical_projection(tmp_path: Path):
    events = _events()
    events += [simple_transaction(
        "cash", "-27.00", "FUTURE UNKNOWN COUNTERPARTY", f"2027-{month:02d}-05",
        kind="depository", provenance=Provenance("future", 1, "row", "future"))
        for month in range(1, 7)]
    movements = LedgerProjection(events).movements()
    old_key = next(row.key for row in movements if row.date == "2026-01-05")
    future_keys = [row.key for row in movements if row.date.startswith("2027-")]
    events += [
        transfer_suggested(old_key, future_keys[:2], {"future": True}, "2027-01-01"),
        transfer_linked(future_keys[0], future_keys[1], CORROBORATED,
                        {"future": True}, "2027-01-02"),
        merchant_enriched("future unknown counterparty", "Services",
                          grade=CORROBORATED, occurred_at="2027-01-03", by="model",
                          attributes={"counterparty_kind": "business", "billing": "standing",
                                      "billing_period": "monthly"}),
        category_assigned(future_keys[2], "FUTURE UNKNOWN COUNTERPARTY", "Services",
                          CORROBORATED, "2027-01-04", by="human", nature="spending"),
    ]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = revision.open_questions(
                as_of="2026-05-01", locale="en-US", limit=None)
            later = revision.open_questions(
                as_of="2027-05-01", locale="en-US", limit=None)
    expected = open_questions(
        LedgerProjection(events), as_of="2026-05-01", jurisdiction="US",
        locale="en-US", limit=None)
    for family in ("transfer", "merchant", "nature"):
        assert [row for row in actual["questions"] if row["kind"] == family] == [
            row for row in expected["questions"] if row["kind"] == family]
    # Only cadence is value-time bounded. Full-current transfer/merchant/nature
    # candidates therefore agree across the paired reads, while future cadence
    # evidence first becomes eligible at the later boundary.
    for family in ("transfer", "merchant", "nature"):
        assert [row for row in actual["questions"] if row["kind"] == family] == [
            row for row in later["questions"] if row["kind"] == family]
    assert not any(row["kind"] == "rhythm" and
                   row["refs"].get("merchant") == "future unknown counterparty"
                   for row in actual["questions"])
    assert any(row["kind"] == "rhythm" and
               row["refs"].get("merchant") == "future unknown counterparty"
               for row in later["questions"])


def test_latest_exact_finding_set_aside_suppresses_only_unchanged_stake(tmp_path: Path):
    events = _events()
    initial = LedgerProjection(events).findings("2026-05-01")[0]
    events.append(finding_set_aside(
        initial.id, initial.kind, initial.stake, "2026-05-01"))
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            actual = revision.findings(today="2026-05-01")
            revision.connection.set_trace_callback(None)
            assert _normal(actual) == _normal(
                LedgerProjection(events).findings("2026-05-01"))
    decisions = [statement for statement in traced
                 if "FROM REVIEW_DECISIONS" in statement.upper()]
    assert len(decisions) == 1
    assert "LIMIT" in decisions[0].upper() and "OFFSET" not in decisions[0].upper()


def test_finding_semantic_overlays_use_full_current_projection(tmp_path: Path):
    events = _events() + [merchant_enriched(
        "lumen streaming", "Fees", grade=CORROBORATED,
        occurred_at="2030-01-01", by="model",
        attributes={"counterparty_kind": "business", "billing": "standing",
                    "billing_period": "monthly"})]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = revision.findings(today="2026-05-01")
    assert _normal(actual) == _normal(
        LedgerProjection(events).findings("2026-05-01"))
    assert any(item.kind == "fee_observed" for item in actual)


def test_composition_refuses_invalid_limits_and_uses_no_offset(tmp_path: Path):
    source = _store(tmp_path, _events())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            with pytest.raises(ValueError, match="finding limit"):
                revision.findings(today="2026-05-01", limit=0)
            traced = []
            revision.connection.set_trace_callback(traced.append)
            revision.current_period(today="2026-05-01")
            revision.connection.set_trace_callback(None)
            assert "OFFSET" not in "\n".join(traced).upper()
            assert any("LIMIT" in statement.upper() for statement in traced)


def test_current_period_refuses_201_goals_instead_of_truncating(tmp_path: Path):
    events = _events() + [goal_created(
        f"goal-{index:03d}", f"Goal {index}", "USD", "100", "2026-01-01",
        monthly_contribution="1", contribution_day=1)
        for index in range(201)]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            with pytest.raises(RhythmReadError, match="200-goal"):
                revision.current_period(today="2026-05-01")


@pytest.mark.parametrize("events", [
    [account_opened("cash", "depository", "Cash", "", "2026-01-01",
                    origin="issued")],
    [account_opened("asserted", "depository", "Envelope", "USD", "2026-01-01",
                    origin="asserted"),
     account_opened("broker", "investment", "Broker", "USD", "2026-01-01",
                    origin="issued")],
    [],
], ids=("issuer-depository-without-usable-currency", "all-ineligible", "empty"))
def test_current_period_no_eligible_liquid_balance_matches_canonical_exactly(
        tmp_path: Path, events):
    expected = LedgerProjection(events).current_period("2026-05-01")
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = revision.current_period(today="2026-05-01")

    assert _normal(actual) == _normal(expected)
    assert actual.refused is True
    assert actual.refusal_reason == "no_eligible_liquid_balance"
    assert actual.slices == ()
    assert actual.excluded_accounts == tuple(item.identity for item in actual.exclusions)
    assert all(item.kind == "account" and item.account_ids == (item.identity,)
               for item in actual.exclusions)


def test_open_question_production_window_has_exact_deterministic_tail(tmp_path: Path):
    events = [account_opened("broker", "investment", "Broker", "USD", "2026-01-01")]
    transactions = [simple_transaction(
        "broker", str(index), f"TRANSFER SOURCE {index:03d}", "2026-01-02",
        kind="investment") for index in range(1, 206)]
    events.extend(transactions)
    movements = LedgerProjection(events).movements()
    events.extend(transfer_suggested(
        movement.key, [f"unmatched-{index:03d}"], {}, "2026-01-03")
        for index, movement in enumerate(movements, start=1))
    expected = open_questions(
        LedgerProjection(events), as_of="2026-05-01", jurisdiction="US",
        locale="en-US", limit=None)
    supported = [row for row in expected["questions"]
        if row["kind"] in {"transfer", "merchant", "nature", "rhythm",
                           "corroboration", "expectation", "interview"}]
    expected["questions"] = supported[:200]
    expected["total"] = len(supported)
    expected["tail"] = {
        "count": len(supported[200:]),
        "amount": str(sum((Decimal(row["amount"]) for row in supported[200:]),
                          Decimal(0))),
    }
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            first = revision.open_questions(
                as_of="2026-05-01", jurisdiction="US", locale="en-US", limit=200)
            second = revision.open_questions(
                as_of="2026-05-01", jurisdiction="US", locale="en-US", limit=200)

    assert first == second == expected
    assert len(first["questions"]) == 200
    assert [row["amount"] for row in first["questions"][:3]] == ["205", "204", "203"]
    assert [row["amount"] for row in first["questions"][-3:]] == ["8", "7", "6"]
    assert first["total"] == 207
    assert first["tail"] == {"count": 7, "amount": "15"}


def test_findings_above_public_limit_refuse_without_partial_result(tmp_path: Path):
    events = _events()
    for index in range(201):
        description = f"DUPLICATE {index:03d}"
        occurred_at = (date(2025, 9, 1) + timedelta(days=index)).isoformat()
        events.extend((
            simple_transaction("cash", "-1", description, occurred_at,
                               kind="depository"),
            simple_transaction("cash", "-1", description, occurred_at,
                               kind="depository"),
            merchant_enriched(description.lower(), "Services", grade=CORROBORATED,
                              occurred_at="2026-04-11", by="model",
                              attributes={"counterparty_kind": "business"}),
        ))
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            before = revision.connection.execute(
                "SELECT COUNT(*) FROM applied_events").fetchone()
            with pytest.raises(RhythmReadError,
                               match="finding result exceeds its requested 200-row bound"):
                revision.findings(today="2026-05-01", limit=200)
            assert revision.connection.execute(
                "SELECT COUNT(*) FROM applied_events").fetchone() == before


@pytest.mark.parametrize("case", ["links", "bytes", "candidates", "key"])
def test_transfer_production_envelopes_refuse_without_partial_results(
        tmp_path: Path, case, monkeypatch):
    events = _events()
    if case == "links":
        events += [transfer_linked(f"a-{i}", f"b-{i}", CORROBORATED, {}, "2026-01-01")
                   for i in range(10_001)]
        message = "transfer links"
    elif case == "bytes":
        events.append(transfer_suggested(
            "missing", ["x" * 5000 for _ in range(201)], {}, "2026-01-01"))
        message = "byte bound"
    elif case == "candidates":
        from viva.read_store import transfer_payload
        monkeypatch.setattr(transfer_payload, "MAX_TRANSFER_CONTAINER_ITEMS", 201)
        events.append(transfer_suggested(
            "missing", [f"candidate-{i}" for i in range(201)], {}, "2026-01-01"))
        message = "nested candidate"
    else:
        events.append(transfer_suggested(
            "missing", ["é" * 257], {}, "2026-01-01"))
        message = "field bound"
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            before = revision.connection.execute("SELECT COUNT(*) FROM applied_events").fetchone()
            with pytest.raises(RhythmReadError, match=message):
                revision.open_questions(as_of="2026-05-01")
            # Refusal returns no partial payload and cannot mutate the revision.
            assert revision.connection.execute("SELECT COUNT(*) FROM applied_events").fetchone() == before


def test_reservation_production_envelope_refuses_without_partial_result(tmp_path: Path):
    events = _events() + [goal_created(
        "bounded", "Bounded", "USD", "20000", "2026-01-01")]
    events += [goal_funds_reserved(
        "bounded", "cash", "1", f"2026-01-{(index % 28) + 1:02d}")
        for index in range(10_001)]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            before = revision.connection.execute("SELECT COUNT(*) FROM applied_events").fetchone()
            with pytest.raises(read_store_module.ReadStoreError,
                               match="reservation.*fold bound"):
                revision.current_period(today="2026-05-01")
            assert revision.connection.execute("SELECT COUNT(*) FROM applied_events").fetchone() == before


def test_review_decisions_chunk_more_than_four_hundred_subjects_and_use_indexed_window_sql(
        tmp_path: Path):
    events = _events()
    question_ids = [f"question-{i:03d}" for i in range(401)]
    finding_ids = [f"finding-{i:03d}" for i in range(401)]
    nested_stake = {"outer": {"amount": "12.3400", "why": ["a", {"b": "Ω"}]}}
    events += [question_declined(identity, "merchant", "2026-04-30",
                                 amount="1.00", count=2)
               for identity in question_ids]
    events += [finding_set_aside(identity, "possible_duplicate", nested_stake,
                                 "2026-04-30")
               for identity in finding_ids]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            question_rows = sql_questions._latest_decisions(
                revision.connection, "QuestionDeclined", question_ids)
            finding_rows = composition._latest_finding_decisions(
                revision.connection, finding_ids)
            revision.connection.set_trace_callback(None)
            assert len(question_rows) == len(finding_rows) == 401
            assert question_rows[question_ids[-1]]["amount"] == "1.00"
            assert finding_rows[finding_ids[-1]]["stake"] == nested_stake
            statements = [sql for sql in traced if "ROW_NUMBER() OVER" in sql.upper()]
            assert len(statements) == 2 * 3  # ceil(401 / 200), for both families.
            assert all(" IN (" in sql.upper() and "LIMIT" in sql.upper() for sql in statements)
            question_sql = [sql for sql in statements if
                            "EVENT_TYPE='QUESTIONDECLINED'" in sql.upper()]
            finding_sql = [sql for sql in statements if
                           "EVENT_TYPE='FINDINGSETASIDE'" in sql.upper()]
            assert len(question_sql) == len(finding_sql) == 3
            # Plan the exact SQL captured from production, including both full
            # 200-subject chunks and the one-row boundary chunk.
            for statement in (*question_sql, *finding_sql):
                plan = revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + statement).fetchall()
                rendered = " ".join(str(row[-1]) for row in plan)
                assert "review_decisions_by_current_subject" in rendered, rendered
                assert "USE TEMP B-TREE" not in rendered, rendered


def test_review_decisions_are_batched_and_latest_source_wins(tmp_path: Path):
    events = _events()
    question = next(row for row in open_questions(
        LedgerProjection(events), as_of="2026-05-01", locale="en-US", limit=None
    )["questions"] if row["kind"] in ("merchant", "nature", "rhythm"))
    events += [
        question_declined(question["id"], question["kind"], "2030-01-01",
                          amount=question["amount"], count=question["count"]),
        question_declined(question["id"], question["kind"], "2020-01-01",
                          amount="999", count=question["count"]),
    ]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            actual = revision.open_questions(
                as_of="2026-05-01", locale="en-US", limit=None)
            revision.connection.set_trace_callback(None)
    assert question["id"] in {row["id"] for row in actual["questions"]}
    decisions = [statement for statement in traced
                 if "FROM REVIEW_DECISIONS" in statement.upper()]
    assert len(decisions) == 1
    assert "LIMIT" in decisions[0].upper() and "OFFSET" not in decisions[0].upper()


def test_all_goal_reservation_fold_refuses_before_recursive_work(
        tmp_path: Path, monkeypatch):
    events = _events() + [
        goal_created("bounded", "Bounded", "USD", "100", "2026-01-01"),
        goal_funds_reserved("bounded", "cash", "1", "2026-01-02"),
        goal_funds_reserved("bounded", "cash", "1", "2026-01-03"),
    ]
    source = _store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            monkeypatch.setattr(read_store_module, "GOAL_RESERVATION_EVENT_LIMIT", 1)
            traced = []
            revision.connection.set_trace_callback(traced.append)
            with pytest.raises(read_store_module.ReadStoreError,
                               match="reservation.*fold bound"):
                revision.current_period(today="2026-05-01")
            revision.connection.set_trace_callback(None)
    assert not any("WITH RECURSIVE" in statement.upper() for statement in traced)


def test_composition_runtime_has_no_canonical_replay_imports():
    source = Path(composition.__file__).read_text()
    assert "LedgerProjection" not in source.replace("``LedgerProjection``", "")
    assert "EventStore" not in source
    assert "RawStore" not in source
