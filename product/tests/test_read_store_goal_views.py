"""Parity proof for revision-local calendar-dependent goal composition."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json

import pytest

from viva.ledger import (EventStore, LedgerProjection, Posting, Provenance,
                         account_opened, closing_balance_observed, goal_created,
                         goal_funds_released, goal_funds_reserved,
                         goal_state_changed, goal_terms_changed,
                         opening_balance_observed,
                         transaction_recorded)
from viva.read_store import ReadStore
from viva.read_store import store as read_store_module


PASSPHRASE = "correct horse battery staple"


def _event_store(path: Path, events) -> EventStore:
    store = EventStore.open(path / "events.jsonl", PASSPHRASE)
    for event in events:
        store.append(event)
    return store


def _normalize(value):
    if hasattr(value, "to_dict"):
        return _normalize(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return _normalize(asdict(value))
    if isinstance(value, dict):
        lv = {key: _normalize(item) for key, item in value.items()}
        # SQL state intentionally retains its fold substrate too.
        for key in ("reservation_history", "event_ids", "proposal_id"):
            lv.pop(key, None)
        return lv
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    return str(value) if value.__class__.__name__ == "Decimal" else value


def _corpus():
    source = Provenance("doc-goals", 2, "balance", "issuer")
    return [
        account_opened("cash", "depository", "Cash", "USD", "2026-01-01",
                       origin="issued", provenance=source),
        opening_balance_observed("cash", "1000.000", "2026-01-01", source),
        transaction_recorded([Posting("cash", "-100"),
                              Posting("Expenses:Other", "100")],
                             "purchase", "2026-01-10", provenance=source),
        closing_balance_observed("cash", "900.000", "2026-01-31", source),
        account_opened("eur", "depository", "Euro", "EUR", "2026-01-01",
                       origin="issued", provenance=source),
        closing_balance_observed("eur", "25", "2026-01-31", source),
        account_opened("card", "liability", "Card", "USD", "2026-01-01",
                       origin="issued", provenance=source),
        goal_created("g1", "Buffer", "USD", "1200.00", "2026-01-02",
                     target_date="2026-06-30", monthly_contribution="200.00",
                     contribution_day=15, provenance=source),
        goal_funds_reserved("g1", "cash", "300.00", "2026-01-03",
                            provenance=source),
        goal_funds_released("g1", "cash", "50.00", "used_elsewhere",
                            "2026-01-04", provenance=source),
        goal_created("g2", "Later", "EUR", "100", "2026-02-02",
                     provenance=source),
        goal_terms_changed("g2", "Later revised", "EUR", "80", "2026-02-03",
                           target_date="2026-01-01", provenance=source),
        goal_state_changed("g2", "paused", "2026-02-04", provenance=source),
    ]


@pytest.mark.parametrize("today", ["2025-12-31", "2026-01-31", "2026-02-04",
                                    "2026-02-05", "2027-01-01"])
def test_current_goal_views_match_canonical_projection(tmp_path: Path, today: str):
    events = _corpus()
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            actual = revision.current_goal_views(today=today)
    expected = LedgerProjection(events, as_of=today).goals(today)
    assert _normalize(actual) == _normalize(expected)


@pytest.mark.parametrize("glyph", ["X", "雪"])
def test_goal_history_body_prefetch_exact_utf8_boundary_and_whole_read_refusal(
        tmp_path: Path, glyph: str):
    canonical = _event_store(tmp_path, _corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            original = revision.connection.execute(
                "SELECT body_json FROM goal_event_history "
                "WHERE event_type='GoalCreated' AND goal_id='g1'"
            ).fetchone()[0]
        base = json.loads(original)
        bound = read_store_module.MAX_GOAL_HISTORY_BODY_BYTES
        shell = json.dumps({**base, "padding": ""}, ensure_ascii=False)
        room = bound - len(shell.encode("utf-8"))
        width = len(glyph.encode("utf-8"))
        padding = glyph * (room // width) + "X" * (room % width)
        for extra in ("", "X"):
            encoded = json.dumps({**base, "padding": padding + extra},
                                 ensure_ascii=False)
            assert len(encoded.encode("utf-8")) == bound + len(extra)
            assert json.loads(encoded)["padding"] == padding + extra
            reads.publish(lambda connection: connection.execute(
                "UPDATE goal_event_history SET body_json=? "
                "WHERE event_type='GoalCreated' AND goal_id='g1'",
                (encoded,)), copy_current=True)
            with reads.open_reader() as revision:
                traced = []
                revision.connection.set_trace_callback(traced.append)
                if extra:
                    with pytest.raises(read_store_module.ReadStoreError,
                                       match="goal history body exceeds its byte bound"):
                        revision.current_goal_states(as_of="2026-02-05")
                else:
                    assert revision.current_goal_states(as_of="2026-02-05")
                revision.connection.set_trace_callback(None)
                selected = [sql for sql in traced
                            if "length(CAST(h.body_json AS BLOB))" in sql
                            and "LIMIT" in sql]
                assert len(selected) == 1
                plan = " ".join(str(row[-1]) for row in
                                revision.connection.execute(
                                    "EXPLAIN QUERY PLAN " + selected[0]).fetchall())
                assert "TEMP B-TREE" not in plan.upper()


def test_goal_history_total_row_cap_refuses_instead_of_truncating(tmp_path, monkeypatch):
    canonical = _event_store(tmp_path, _corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        monkeypatch.setattr(read_store_module, "MAX_GOAL_HISTORY_ROWS", 1)
        with reads.open_reader() as revision:
            assert revision.connection.execute(
                "SELECT COUNT(*) FROM goal_event_history WHERE goal_id='g1'"
            ).fetchone()[0] > 1
            with pytest.raises(read_store_module.ReadStoreError,
                               match="goal history exceeds its read row bound"):
                revision.current_goal_states(as_of="2026-02-05")


def test_current_goal_view_query_is_revision_bound_and_tamper_detected(tmp_path: Path):
    canonical = _event_store(tmp_path, _corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        reader = reads.open_reader()
        before = reader.current_goal_views(today="2026-02-05")
        canonical.append(goal_funds_reserved(
            "g1", "cash", "1.00", "2026-02-05"))
        reads.synchronize(canonical)
        assert reader.current_goal_views(today="2026-02-05") == before
        reader.close()
        with reads.open_reader() as current:
            assert current.current_goal_views(today="2026-02-05") != before
            with pytest.raises(Exception):
                current.connection.execute(
                    "UPDATE goal_event_history SET amount_text='9'")


def test_current_goal_view_named_queries_are_indexed_and_bounded(tmp_path: Path):
    canonical = _event_store(tmp_path, _corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            assert len(revision.current_goal_views(today="2026-02-05", limit=1)) == 1
            with pytest.raises(ValueError, match="limit"):
                revision.current_goal_views(today="2026-02-05", limit=201)
            detail = " ".join(row[3] for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN SELECT goal_id FROM goal_event_history "
                "WHERE event_type='GoalCreated' AND occurred_at<=? AND goal_id<>'' "
                "GROUP BY goal_id ORDER BY goal_id LIMIT ?", ("2026-02-05", 10)))
            assert "goal_creates_by_current_id" in detail


@pytest.mark.parametrize("limit", [1, 2])
def test_goal_page_uses_account_reservations_from_all_current_goals(
        tmp_path: Path, limit: int):
    """A later goal page cannot make an earlier page overstate availability."""
    source = Provenance("doc-shared", 1, "goals", "shared account")
    events = [
        account_opened("cash", "depository", "Cash", "USD", "2026-01-01",
                       origin="issued", provenance=source),
        opening_balance_observed("cash", "100.00", "2026-01-01", source),
        goal_created("goal-a", "First", "USD", "100", "2026-01-02",
                     provenance=source),
        goal_funds_reserved("goal-a", "cash", "10.00", "2026-01-03",
                            provenance=source),
        goal_created("goal-z", "Later page", "USD", "100", "2026-01-04",
                     provenance=source),
        goal_funds_reserved("goal-z", "cash", "30.00", "2026-01-05",
                            provenance=source),
        # A later-source correction with earlier value time must participate
        # in the canonical source-order fold at this read date.
        goal_funds_released("goal-z", "cash", "5.00", "reassigned",
                            "2026-01-03", provenance=source),
    ]
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            actual = revision.current_goal_views(today="2026-01-31", limit=limit)
    expected = LedgerProjection(events, as_of="2026-01-31").goals("2026-01-31")[:limit]
    assert _normalize(actual) == _normalize(expected)
    assert actual[0]["available_accounts"][0]["reserved"] == pytest.approx(
        expected[0].available_accounts[0].reserved)
    assert str(actual[0]["available_accounts"][0]["reserved"]) == "35.00"


def test_goal_view_refuses_oversized_account_universe(tmp_path: Path):
    source = Provenance("doc-many", 1, "accounts", "bounded")
    events = [goal_created("goal", "Goal", "USD", "1", "2026-01-01",
                           provenance=source)]
    events.extend(account_opened(
        f"cash-{index:03}", "depository", f"Cash {index}", "USD", "2026-01-01",
        origin="issued", provenance=source) for index in range(201))
    canonical = _event_store(tmp_path, events)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            with pytest.raises(read_store_module.ReadStoreError,
                               match="200-account bound"):
                revision.current_goal_views(today="2026-01-31")


def test_goal_view_refuses_history_and_posting_overflow_without_truncation(
        tmp_path: Path, monkeypatch):
    source = Provenance("doc-bounds", 1, "goal", "bounded")
    history_events = [
        goal_created("goal", "Goal", "USD", "100", "2026-01-01",
                     provenance=source),
        goal_funds_reserved("goal", "cash", "1", "2026-01-02", provenance=source),
        goal_funds_reserved("goal", "cash", "1", "2026-01-03", provenance=source),
    ]
    canonical = _event_store(tmp_path / "history", history_events)
    with ReadStore.create(tmp_path / "history" / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        monkeypatch.setattr(read_store_module, "GOAL_HISTORY_PER_GOAL_LIMIT", 2)
        with reads.open_reader() as revision:
            with pytest.raises(read_store_module.ReadStoreError,
                               match="2-event current-view bound"):
                revision.current_goal_views(today="2026-01-31")

    monkeypatch.setattr(read_store_module, "GOAL_HISTORY_PER_GOAL_LIMIT", 2_000)
    posting_events = [
        account_opened("cash", "depository", "Cash", "USD", "2026-01-01",
                       origin="issued", provenance=source),
        opening_balance_observed("cash", "10", "2026-01-01", source),
        goal_created("goal", "Goal", "USD", "100", "2026-01-01",
                     provenance=source),
        transaction_recorded([Posting("cash", "-1"), Posting("Expenses:Other", "1")],
                             "one", "2026-01-02", provenance=source),
        transaction_recorded([Posting("cash", "-1"), Posting("Expenses:Other", "1")],
                             "two", "2026-01-03", provenance=source),
    ]
    canonical = _event_store(tmp_path / "postings", posting_events)
    with ReadStore.create(tmp_path / "postings" / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        monkeypatch.setattr(read_store_module, "GOAL_POSTINGS_PER_ACCOUNT_LIMIT", 1)
        with reads.open_reader() as revision:
            with pytest.raises(read_store_module.ReadStoreError,
                               match="1-posting goal-view bound"):
                revision.current_goal_views(today="2026-01-31")


def test_goal_view_production_queries_have_indexed_plans_and_bounded_crossings(
        tmp_path: Path):
    canonical = _event_store(tmp_path, _corpus())
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(canonical)
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            revision.current_goal_views(today="2026-02-05", limit=1)
            revision.connection.set_trace_callback(None)
            selects = [sql for sql in traced if sql.lstrip().upper().startswith(
                ("SELECT", "WITH"))]
            account_count = revision.connection.execute(
                "SELECT COUNT(*) FROM account_entities").fetchone()[0]
            # Four fixed goal/aggregate queries (including the reservation
            # overflow probe), one account-universe query,
            # then four current-input statements per account. The hard
            # 200-account refusal therefore bounds statement count at 805.
            assert len(selects) <= 5 + 4 * account_count
            plans = [revision.connection.execute(
                "EXPLAIN QUERY PLAN " + sql).fetchall() for sql in selects]
            plan_text = "\n".join(str(row) for plan in plans for row in plan)
            assert "goal_creates_by_current_id" in plan_text
            assert "goal_events_by_goal_order" in plan_text
            assert "accounts_by_identity" in plan_text
            assert "observations_by_account_date" in plan_text
            assert "postings_by_account" in plan_text
