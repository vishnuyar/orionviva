"""Historical desktop reads must use a held authenticated SQL revision."""

import pytest

from viva.demo import build_demo_vault
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.desktop_bridge.handlers import BridgeRequestError
from viva.ledger.events import (Posting, account_opened, category_assigned,
                                transaction_recorded)
from viva.surface.activity import activity
from viva.surface.overview import overview
from viva.vault import Vault
from viva.read_store import ReadStoreDegraded, ReadStoreError


@pytest.mark.parametrize("surface,parameters,compose", [
    ("overview", {"as_of": "2026-03-31", "read_on": "2026-08-29"},
     lambda vault: overview(vault.ledger.projection_as_of("2026-03-31"),
                            "en-US", "2026-08-29")),
    ("activity", {"as_of": "2026-03-31", "limit": 5},
     lambda vault: activity(vault.ledger.projection_as_of("2026-03-31"),
                            "en-US", 5)),
])
def test_historical_surface_uses_sql_not_event_prefix(
        tmp_path, monkeypatch, surface, parameters, compose):
    vault = build_demo_vault(tmp_path / "sample")
    expected = compose(vault)
    monkeypatch.setattr(vault.ledger, "projection_as_of",
                        lambda *_args: pytest.fail("historical event replay"))
    monkeypatch.setattr(vault.ledger.store, "snapshot_events",
                        lambda: pytest.fail("historical EventStore read"))
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda: pytest.fail("historical RawStore enumeration"))
    monkeypatch.setattr(vault.raw, "get",
                        lambda *_args: pytest.fail("historical RawStore read"))
    actual = OpenedVaultSurfaceProvider(vault).read_surface(surface, parameters)
    assert actual == expected


@pytest.mark.parametrize("surface,parameters", [
    ("overview", {"as_of": "2026-03-31", "read_on": "2026-08-29"}),
    ("activity", {"as_of": "2026-03-31", "limit": 5}),
])
def test_historical_bridge_opens_exactly_one_held_revision(
        tmp_path, monkeypatch, surface, parameters):
    vault = build_demo_vault(tmp_path / "sample")
    original = vault.read_store.open_reader
    calls = []
    def tracked():
        calls.append(1)
        return original()
    monkeypatch.setattr(vault.read_store, "open_reader", tracked)
    OpenedVaultSurfaceProvider(vault).read_surface(surface, parameters)
    assert calls == [1]


@pytest.mark.parametrize("lifecycle", ["stale", "degraded", "rebuilding"])
@pytest.mark.parametrize("surface,parameters", [
    ("overview", {"as_of": "2026-03-31", "read_on": "2026-08-29"}),
    ("activity", {"as_of": "2026-03-31", "limit": 5}),
])
def test_historical_bridge_refuses_non_current_generation_without_replay(
        tmp_path, monkeypatch, lifecycle, surface, parameters):
    vault = build_demo_vault(tmp_path / "sample")
    vault.read_store_lifecycle = lifecycle
    monkeypatch.setattr(vault.ledger, "projection_as_of",
                        lambda *_args: pytest.fail("historical replay fallback"))
    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface(surface, parameters)


@pytest.mark.parametrize("surface,parameters", [
    ("overview", {"as_of": "2026-03-31", "read_on": "2026-08-29"}),
    ("activity", {"as_of": "2026-03-31", "limit": 5}),
])
def test_historical_bridge_refuses_unreadable_generation_without_replay(
        tmp_path, monkeypatch, surface, parameters):
    vault = build_demo_vault(tmp_path / "sample")
    monkeypatch.setattr(vault.read_store, "open_reader",
                        lambda: (_ for _ in ()).throw(
                            ReadStoreError("injected unreadable generation")))
    monkeypatch.setattr(vault.ledger, "projection_as_of",
                        lambda *_args: pytest.fail("historical replay fallback"))
    with pytest.raises(BridgeRequestError, match="could not answer"):
        OpenedVaultSurfaceProvider(vault).read_surface(surface, parameters)


def test_historical_bridge_reads_acknowledged_backfilled_write(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened(
        "cash", "depository", "Cash", "USD", "2026-01-01"))
    vault.synchronize_read_store()
    provider = OpenedVaultSurfaceProvider(vault)
    parameters = {"as_of": "2026-01-31", "limit": 10}
    before = provider.read_surface("activity", parameters)
    vault.ledger.append(transaction_recorded([
        Posting("cash", "-10.00", "verified"),
        Posting("Expenses:Unknown", "10.00", "unverified")],
        "Backfilled synthetic merchant", "2026-01-15"))
    after = provider.read_surface("activity", parameters)
    assert len(after["items"]) == len(before["items"]) + 1


def test_historical_bridge_refuses_failed_post_write_sync_without_replay(
        tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened(
        "cash", "depository", "Cash", "USD", "2026-01-01"))
    vault.synchronize_read_store()
    monkeypatch.setattr(vault.read_store, "synchronize",
                        lambda *_args: (_ for _ in ()).throw(
                            ReadStoreDegraded("injected sync failure")))
    vault.ledger.append(transaction_recorded([
        Posting("cash", "-10.00", "verified"),
        Posting("Expenses:Unknown", "10.00", "unverified")],
        "Backfilled synthetic merchant", "2026-01-15"))
    monkeypatch.setattr(vault.ledger, "projection_as_of",
                        lambda *_args: pytest.fail("historical replay fallback"))
    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface(
            "activity", {"as_of": "2026-01-31", "limit": 10})


def test_historical_activity_filters_value_time_before_source_order_fold(
        tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened(
        "cash", "depository", "Cash", "USD", "2026-01-01"))
    vault.ledger.append(transaction_recorded([
        Posting("cash", "-1234.50", "verified"),
        Posting("Expenses:Unknown", "1234.50", "unverified")],
        "Synthetic merchant", "2026-01-10"))
    vault.ledger.append(transaction_recorded([
        Posting("cash", "-25.00", "verified"),
        Posting("Expenses:Unknown", "25.00", "unverified")],
        "Second merchant", "2026-01-10"))
    movements = {movement.description: movement.key
                 for movement in vault.ledger.projection().movements()}
    key, second_key = movements["Synthetic merchant"], movements["Second merchant"]
    vault.ledger.append(category_assigned(
        key, "Synthetic merchant", "Groceries", "verified", "2026-01-11"))
    vault.ledger.append(category_assigned(
        second_key, "Second merchant", "Services", "verified", "2026-01-11"))
    vault.ledger.append(category_assigned(
        key, "Synthetic merchant", "Food", "verified", "2026-02-01"))
    vault.ledger.append(category_assigned(
        second_key, "Second merchant", "Utilities", "verified", "2026-01-11"))
    vault.synchronize_read_store()
    historical = vault.ledger.projection_as_of("2026-01-15")
    by_key = {movement.key: movement for movement in historical.movements()}
    assert historical.derived_category(by_key[key])["category"] == "Groceries"
    assert historical.derived_category(by_key[second_key])["category"] == "Utilities"
    expected = activity(historical, "en-US", 10)
    assert expected["items"]
    assert expected != activity(vault.ledger.projection(), "en-US", 10)
    monkeypatch.setattr(vault.ledger, "projection_as_of",
                        lambda *_args: pytest.fail("historical event replay"))
    actual = OpenedVaultSurfaceProvider(vault).read_surface(
        "activity", {"as_of": "2026-01-15", "limit": 10})
    assert actual == expected
