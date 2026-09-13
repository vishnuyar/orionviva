"""Historical Overview composition over one held SQL revision."""

import pytest

from viva.demo import build_demo_vault
from viva.ledger import simple_transaction
from viva.ledger import EventStore, LedgerProjection
from viva.ledger.events import (account_opened, closing_balance_observed,
                                opening_balance_observed)
from viva.surface.overview import overview
from viva.read_store import ReadStore
from viva.vault import Vault
from viva.read_store.store import ReadStoreError

from test_read_store_composition import _composition_events


@pytest.mark.parametrize("as_of", ["2026-01-31", "2026-03-31", "2026-08-29"])
def test_sample_historical_overview_full_payload_parity(tmp_path, as_of):
    vault = build_demo_vault(tmp_path / "sample")
    expected = overview(vault.ledger.projection_as_of(as_of), "en-US", "2026-08-29")
    with vault.read_store.open_reader() as revision:
        actual = overview(revision.historical_overview_projection(
            as_of=as_of, today="2026-08-29"), "en-US", "2026-08-29")
    assert actual == expected


@pytest.mark.parametrize("as_of", ["2025-12-31", "2026-02-28", "2026-05-01"])
def test_composition_corpus_historical_overview_full_payload_parity(tmp_path, as_of):
    events = _composition_events()
    source = EventStore.open(tmp_path / "events.jsonl", "pw")
    source.append_atomically(lambda _existing: tuple(events))
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = overview(revision.historical_overview_projection(
                as_of=as_of, today="2026-05-01"), "en-US", "2026-05-01")
    expected = overview(LedgerProjection(events, as_of=as_of), "en-US", "2026-05-01")
    for key in actual:
        assert actual[key] == expected[key], key


def test_historical_overview_excludes_future_and_includes_late_backfill(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened("cash", "depository", "Cash", "USD", "2026-01-01"))
    vault.ledger.append(opening_balance_observed("cash", "100", "2026-01-01"))
    vault.ledger.append(simple_transaction("cash", "-10", "EARLY", "2026-01-10",
                                           kind="depository"))
    vault.ledger.append(closing_balance_observed("cash", "90", "2026-01-31"))
    vault.ledger.append(closing_balance_observed("cash", "50", "2026-03-31"))
    vault.ledger.append(simple_transaction("cash", "-5", "BACKFILL", "2026-01-15",
                                           kind="depository"))
    vault.synchronize_read_store()
    as_of, today = "2026-02-01", "2026-08-29"
    expected = overview(vault.ledger.projection_as_of(as_of), "en-US", today)
    current = overview(vault.ledger.projection(), "en-US", today)
    with vault.read_store.open_reader() as revision:
        actual = overview(revision.historical_overview_projection(
            as_of=as_of, today=today), "en-US", today)
    assert expected != current
    assert actual == expected


def test_historical_overview_direct_reader_does_not_touch_canonical_sources(
        tmp_path, monkeypatch):
    vault = build_demo_vault(tmp_path / "sample")
    expected = overview(vault.ledger.projection_as_of("2026-03-31"),
                        "en-US", "2026-08-29")
    monkeypatch.setattr(vault.ledger, "projection_as_of",
                        lambda *_args: pytest.fail("event projection"))
    monkeypatch.setattr(vault.ledger.store, "snapshot_events",
                        lambda: pytest.fail("event snapshot"))
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda: pytest.fail("raw enumeration"))
    with vault.read_store.open_reader() as revision:
        actual = overview(revision.historical_overview_projection(
            as_of="2026-03-31", today="2026-08-29"),
            "en-US", "2026-08-29")
    assert actual == expected


def test_historical_overview_held_revision_keeps_full_payload_after_write(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened("cash", "depository", "Cash", "USD", "2026-01-01"))
    vault.ledger.append(closing_balance_observed("cash", "100", "2026-01-31"))
    vault.synchronize_read_store()
    held = vault.read_store.open_reader()
    def payload(revision):
        return overview(revision.historical_overview_projection(
            as_of="2026-02-01", today="2026-08-29"), "en-US", "2026-08-29")
    before = payload(held)
    vault.ledger.append(closing_balance_observed("cash", "90", "2026-01-31"))
    assert payload(held) == before
    with vault.read_store.open_reader() as current:
        assert payload(current) != before
    held.close()


def test_historical_overview_refuses_observation_bound(tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened("cash", "depository", "Cash", "USD", "2026-01-01"))
    vault.ledger.append(closing_balance_observed("cash", "100", "2026-01-31"))
    vault.ledger.append(closing_balance_observed("cash", "90", "2026-01-30"))
    vault.synchronize_read_store()
    monkeypatch.setattr("viva.read_store.overview.MAX_OVERVIEW_OBSERVATIONS", 1)
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ReadStoreError, match="observation history.*bound"):
            revision.historical_overview_projection(
                as_of="2026-02-01", today="2026-08-29")


def test_historical_overview_query_budget_does_not_grow_per_account(tmp_path):
    source = EventStore.open(tmp_path / "events.jsonl", "pw")
    events = [account_opened(f"a-{number}", "depository", f"A {number}",
                             "USD", "2026-01-01") for number in range(40)]
    source.append_atomically(lambda _existing: tuple(events[:1]))
    with ReadStore.create(tmp_path / "read-model", "pw") as reads:
        reads.synchronize(source)
        def count():
            with reads.open_reader() as revision:
                statements = []
                revision.connection.set_trace_callback(statements.append)
                revision.historical_overview_projection(
                    as_of="2026-02-01", today="2026-08-29")
                revision.connection.set_trace_callback(None)
            return len([sql for sql in statements
                        if sql.lstrip().upper().startswith(("SELECT", "WITH"))])
        one = count()
        source.append_atomically(lambda _existing: tuple(events[1:]))
        reads.synchronize(source)
        many = count()
    assert one == many
    assert one <= 40


def test_historical_overview_eligible_fact_queries_use_persistent_indexes(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as revision:
        statements = []
        revision.connection.set_trace_callback(statements.append)
        revision.historical_overview_projection(
            as_of="2026-03-31", today="2026-08-29")
        revision.connection.set_trace_callback(None)
        selects = [statement for statement in statements
                   if statement.lstrip().upper().startswith(("SELECT", "WITH"))]
        plans = [" ".join(str(row[3]) for row in revision.connection.execute(
            "EXPLAIN QUERY PLAN " + statement).fetchall())
            for statement in selects]
    assert selects
    assert all("AUTOMATIC" not in plan.upper() for plan in plans)
    assert all("SCAN" in plan or "SEARCH" in plan for plan in plans)
    assert any("documents_by_doc" in plan for plan in plans)
    assert all("USE TEMP B-TREE" not in plan for plan in plans)
