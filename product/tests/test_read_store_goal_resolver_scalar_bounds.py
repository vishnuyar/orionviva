"""Goal and resolver scalar boundaries on held SQL revisions."""

import json
import sqlite3
from types import SimpleNamespace

import pytest
from merchantcore.profile import Profile, Template

from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.demo import build_demo_vault
from viva.ledger.events import goal_created, goal_proposal_recorded
from viva.read_store.store import ReadRevision, ReadStoreError, RESOLVER_VERSION


def _exact(original, glyph):
    room = 4096 - len(original.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    result = original + glyph * (room // width) + "x" * (room % width)
    assert len(result.encode("utf-8")) == 4096
    return result


@pytest.mark.parametrize("glyph", ["x", "雪"])
@pytest.mark.parametrize("column", ["goal_id", "occurred_at"])
def test_goal_history_scalar_exact_boundary_and_bridge_refusal(
        tmp_path, glyph, column):
    vault = build_demo_vault(tmp_path / "sample")
    vault.ledger.append(goal_created(
        "goal-scalar", "Buffer", "USD", "10", "2026-01-02"))
    provider = OpenedVaultSurfaceProvider(vault)
    with vault.read_store.open_reader() as held:
        old = held.current_goal_states(as_of="9999-12-31")
        original = held.connection.execute(
            f"SELECT {column} FROM goal_event_history "
            "WHERE goal_id='goal-scalar'").fetchone()[0]
        exact = _exact(original, glyph)
        for value, refused in ((exact, False), (exact + "x", True)):
            vault.read_store.publish(
                lambda db: db.execute(
                    f"UPDATE goal_event_history SET {column}=? "
                    "WHERE source_sequence=(SELECT MAX(source_sequence) "
                    "FROM goal_event_history)", (value,)), copy_current=True)
            with vault.read_store.open_reader() as revision:
                assert revision.connection.execute(
                    f"SELECT {column} FROM goal_event_history "
                    "WHERE source_sequence=(SELECT MAX(source_sequence) "
                    "FROM goal_event_history)").fetchone()[0] == value
                if refused:
                    with pytest.raises(ReadStoreError, match="scalar byte bound"):
                        revision.current_goal_states(as_of="9999-12-31")
                else:
                    revision.current_goal_states(as_of="9999-12-31")
            if refused:
                with pytest.raises(BridgeRequestError):
                    provider.read_surface("plans", {})
        assert held.current_goal_states(as_of="9999-12-31") == old


@pytest.mark.parametrize("glyph", ["x", "雪"])
@pytest.mark.parametrize("field", ["title", "proposal_id"])
def test_goal_body_displayed_label_refuses_before_python_decode(
        tmp_path, glyph, field):
    vault = build_demo_vault(tmp_path / "sample")
    vault.ledger.append(goal_created(
        "goal-body", "Buffer", "USD", "10", "2026-01-02"))
    with vault.read_store.open_reader() as revision:
        original = json.loads(revision.connection.execute(
            "SELECT body_json FROM goal_event_history "
            "WHERE goal_id='goal-body'").fetchone()[0])[field]
    exact = _exact(original, glyph)
    for value, refused in ((exact, False), (exact + "x", True)):
        vault.read_store.publish(
            lambda db: db.execute(
                "UPDATE goal_event_history SET body_json=json_set(body_json,?,?) "
                "WHERE goal_id='goal-body'", (f"$.{field}", value)),
            copy_current=True)
        with vault.read_store.open_reader() as revision:
            assert json.loads(revision.connection.execute(
                "SELECT body_json FROM goal_event_history "
                "WHERE goal_id='goal-body'").fetchone()[0])[field] == value
            if refused:
                with pytest.raises(ReadStoreError, match="goal history body exceeds"):
                    revision.current_goal_states(as_of="9999-12-31")
            else:
                revision.current_goal_states(as_of="9999-12-31")


@pytest.mark.parametrize("glyph", ["x", "雪"])
@pytest.mark.parametrize("column", ["institution", "account_kind"])
def test_public_resolver_profile_label_exact_boundary_and_refusal(
        tmp_path, glyph, column):
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE resolver_profiles("
                       "institution TEXT,account_kind TEXT,profile_json TEXT,"
                       "PRIMARY KEY(institution,account_kind))")
    profile = Profile("Bound Bank", "depository", "v1",
                      templates=[Template("PAY {brand}")])
    connection.execute("INSERT INTO resolver_profiles VALUES(?,?,?)",
                       (profile.institution, profile.kind,
                        json.dumps(profile.to_dict())))
    revision = SimpleNamespace(connection=connection, resolver_version=RESOLVER_VERSION)
    try:
        original = connection.execute(
            f"SELECT {column} FROM resolver_profiles LIMIT 1").fetchone()[0]
        exact = _exact(original, glyph)
        for value, refused in ((exact, False), (exact + "x", True)):
            connection.execute(f"UPDATE resolver_profiles SET {column}=?", (value,))
            assert connection.execute(
                f"SELECT {column} FROM resolver_profiles LIMIT 1").fetchone()[0] == value
            if refused:
                with pytest.raises(ReadStoreError, match="scalar byte bound"):
                    ReadRevision.resolver(revision)
            else:
                assert callable(ReadRevision.resolver(revision))
            traced = []
            connection.set_trace_callback(traced.append)
            try:
                ReadRevision.resolver(revision)
            except ReadStoreError:
                assert refused
            connection.set_trace_callback(None)
            query = next(sql for sql in traced if "FROM resolver_profiles" in sql)
            plan = " ".join(str(row[-1]) for row in connection.execute(
                "EXPLAIN QUERY PLAN " + query).fetchall())
            assert "TEMP B-TREE" not in plan.upper()
    finally:
        connection.close()


@pytest.mark.parametrize("glyph", ["x", "雪"])
@pytest.mark.parametrize("field", ["summary", "proposal_id"])
def test_goal_proposal_display_labels_exact_and_refused_whole(tmp_path, glyph, field):
    vault = build_demo_vault(tmp_path / "sample")
    vault.ledger.append(goal_proposal_recorded(
        "proposal-scalar", "create", "Save more", {"kind": "goal"},
        {"version": 1}, "2026-01-02"))
    with vault.read_store.open_reader() as revision:
        original = json.loads(revision.connection.execute(
            "SELECT body_json FROM goal_proposal_history "
            "WHERE proposal_id='proposal-scalar'").fetchone()[0])[field]
    exact = _exact(original, glyph)
    for value, refused in ((exact, False), (exact + "x", True)):
        vault.read_store.publish(
            lambda db: db.execute(
                "UPDATE goal_proposal_history SET body_json=json_set(body_json,?,?) "
                "WHERE proposal_id='proposal-scalar'", (f"$.{field}", value)),
            copy_current=True)
        with vault.read_store.open_reader() as revision:
            assert json.loads(revision.connection.execute(
                "SELECT body_json FROM goal_proposal_history "
                "WHERE proposal_id='proposal-scalar'").fetchone()[0])[field] == value
            if refused:
                with pytest.raises(ReadStoreError, match="proposal body exceeds"):
                    revision.plans_projection().open_goal_proposals()
            else:
                revision.plans_projection().open_goal_proposals()
        if refused:
            with pytest.raises(BridgeRequestError):
                OpenedVaultSurfaceProvider(vault).read_surface("plans", {})


@pytest.mark.parametrize("glyph", ["x", "雪"])
def test_rhythm_account_institution_scalar_bound_and_held_reader(tmp_path, glyph):
    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as held:
        old = held.rhythm_hypotheses(as_of="2026-08-29")
        original = held.connection.execute(
            "SELECT institution FROM accounts WHERE institution<>'' LIMIT 1"
        ).fetchone()[0]
        exact = _exact(original, glyph)
        for value, refused in ((exact, False), (exact + "x", True)):
            vault.read_store.publish(
                lambda db: db.execute(
                    "UPDATE accounts SET institution=? WHERE institution<>''",
                    (value,)), copy_current=True)
            with vault.read_store.open_reader() as revision:
                assert revision.connection.execute(
                    "SELECT institution FROM accounts WHERE institution<>'' LIMIT 1"
                ).fetchone()[0] == value
                if refused:
                    with pytest.raises(ReadStoreError, match="scalar byte bound"):
                        revision.rhythm_hypotheses(as_of="2026-08-29")
                else:
                    revision.rhythm_hypotheses(as_of="2026-08-29")
        assert held.rhythm_hypotheses(as_of="2026-08-29") == old


def test_goal_and_resolver_scalar_selects_keep_named_order_plans(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as revision:
        traced = []
        revision.connection.set_trace_callback(traced.append)
        revision.current_goal_states(as_of="2026-08-29")
        revision.plans_projection().open_goal_proposals()
        revision.rhythm_hypotheses(as_of="2026-08-29")
        revision.resolver()
        revision.connection.set_trace_callback(None)
        fragments = (
            "FROM goal_event_history h INDEXED BY goal_events_by_source",
            "FROM goal_proposal_history h",
            "FROM resolver_profiles ORDER BY institution",
            "FROM accounts INDEXED BY accounts_by_source_date",
        )
        for fragment in fragments:
            queries = [query for query in traced if fragment in query
                       and query.lstrip().upper().startswith("SELECT")]
            assert queries, fragment
            for query in queries:
                plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                    "EXPLAIN QUERY PLAN " + query).fetchall())
                assert "TEMP B-TREE" not in plan.upper(), query
