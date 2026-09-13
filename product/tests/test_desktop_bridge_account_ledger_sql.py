"""Desktop account-ledger reads use only the held encrypted SQL generation."""

from __future__ import annotations

import pytest

from viva.demo import build_demo_vault
from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger import simple_transaction
from viva.surface.account_ledger import account_ledger


def test_desktop_account_ledger_matches_canonical_payload_across_pages(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    secret = b"desktop-ledger-parity-secret-key-32"
    provider = OpenedVaultSurfaceProvider(vault, cursor_secret=secret)
    canonical = vault.ledger.projection()
    with vault.read_store.open_reader() as held:
        head = held.connection.execute(
            "SELECT source_head FROM projection_meta WHERE singleton=1").fetchone()[0]
    assert provider.read_surface(
        "account_ledger", {"account_id": "acct:everyday-checking"})["revision"] == head
    for info in canonical.account_infos():
        if not info.number:
            continue
        actual_cursor = expected_cursor = ""
        while True:
            actual = provider.read_surface(
                "account_ledger", {"account_id": info.account, "limit": 1,
                                   "cursor": actual_cursor})
            expected = account_ledger(
                canonical, info.account, "en-US", head,
                cursor_secret=secret, limit=1, cursor=expected_cursor)
            assert {**actual, "page": {**actual["page"], "next_cursor": None}} == {
                **expected, "page": {**expected["page"], "next_cursor": None}}
            actual_cursor = actual["page"]["next_cursor"] or ""
            expected_cursor = expected["page"]["next_cursor"] or ""
            if not actual_cursor:
                assert not expected_cursor
                break


def test_desktop_account_ledger_denies_projection_event_and_raw_access(
        tmp_path, monkeypatch):
    vault = build_demo_vault(tmp_path / "sample")
    provider = OpenedVaultSurfaceProvider(vault)
    monkeypatch.setattr(vault.ledger, "snapshot_projection",
                        lambda: pytest.fail("event snapshot fallback"))
    monkeypatch.setattr(vault.ledger, "projection",
                        lambda: pytest.fail("canonical projection fallback"))
    monkeypatch.setattr(vault.ledger.store, "snapshot_events",
                        lambda: pytest.fail("event prefix fallback"))
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda: pytest.fail("raw enumeration"))
    monkeypatch.setattr(vault.raw, "get",
                        lambda *_a: pytest.fail("raw blob read"))
    payload = provider.read_surface(
        "account_ledger", {"account_id": "acct:everyday-checking", "limit": 1})
    assert payload["state"] == "ready"
    assert payload["page"]["returned"] == 1


def test_desktop_account_ledger_refuses_stale_and_catches_up_after_write(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    provider = OpenedVaultSurfaceProvider(vault)
    account = "acct:everyday-checking"
    initial = provider.read_surface(
        "account_ledger", {"account_id": account, "limit": 1})
    cursor = initial["page"]["next_cursor"]
    vault.ledger.append(simple_transaction(
        account, "-9.00", "NEW MOVEMENT", "2026-07-01", kind="depository"))
    vault.read_store_lifecycle = "stale"
    with pytest.raises(BridgeRequestError, match="not caught up"):
        provider.read_surface("account_ledger", {"account_id": account})
    assert vault.synchronize_read_store() in {"equal", "rebuilt", "caught_up"}
    current = provider.read_surface(
        "account_ledger", {"account_id": account, "limit": 1})
    assert current["revision"] != initial["revision"]
    assert current["groups"][0]["movements"][0]["description"] == "NEW MOVEMENT"
    with pytest.raises(BridgeRequestError, match="stale"):
        provider.read_surface(
            "account_ledger", {"account_id": account, "limit": 1,
                               "cursor": cursor})
    vault.read_store_lifecycle = "degraded"
    with pytest.raises(BridgeRequestError, match="not caught up"):
        provider.read_surface("account_ledger", {"account_id": account})


def test_desktop_account_ledger_refuses_missing_identity_without_fallback(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    provider = OpenedVaultSurfaceProvider(vault)
    with pytest.raises(BridgeRequestError, match="identified exactly"):
        provider.read_surface(
            "account_ledger", {"account_id": "acct:unknown"})


def test_desktop_account_ledger_refuses_failed_post_write_projection_then_recovers(
        tmp_path, monkeypatch):
    vault = build_demo_vault(tmp_path / "sample")
    provider = OpenedVaultSurfaceProvider(vault)
    account = "acct:everyday-checking"
    before = provider.read_surface("account_ledger", {"account_id": account})
    from viva.read_store import account_ledger as component_module
    original = component_module.materialize_component_index

    def fail(_connection):
        raise RuntimeError("injected component publication failure")

    monkeypatch.setattr(component_module, "materialize_component_index", fail)
    vault.ledger.append(simple_transaction(
        account, "-4.00", "AFTER FAILURE", "2026-07-02", kind="depository"))
    assert vault.read_store_lifecycle in {"stale", "degraded"}
    with pytest.raises(BridgeRequestError, match="not caught up"):
        provider.read_surface("account_ledger", {"account_id": account})
    monkeypatch.setattr(component_module, "materialize_component_index", original)
    assert vault.synchronize_read_store() in {"equal", "rebuilt", "caught_up"}
    after = provider.read_surface("account_ledger", {"account_id": account})
    assert after["revision"] != before["revision"]
    assert after["groups"][0]["movements"][0]["description"] == "AFTER FAILURE"
