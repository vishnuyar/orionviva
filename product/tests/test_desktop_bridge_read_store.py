"""Phase 4A: one SQL revision owns the desktop Overview and Accounts read."""
import time
import pytest
from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger import (Provenance, account_opened, closing_balance_observed,
                         document_captured)
from viva.ledger.events import goal_proposal_recorded
from viva.read_store import ReadStoreDegraded, ReadStoreError
from viva.surface.activity import activity
from viva.surface.overview import overview
from viva.surface.plans import plans
from viva.vault import Vault


PASSPHRASE = "correct horse battery staple"


def _opened(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    vault.ledger.append(account_opened(
        "cash", "depository", "Cash", "USD", "2026-01-01"))
    vault.ledger.append(closing_balance_observed(
        "cash", "125.50", "2026-01-31"))
    deadline = time.monotonic() + 5
    while vault._read_store_worker is not None and time.monotonic() < deadline:
        vault.poll_read_store_worker()
        time.sleep(0.01)
    # The startup worker may have published before the two test writes. This
    # explicit test setup catch-up is not part of bridge.open_vault.
    vault.synchronize_read_store()
    return vault


def test_bundle_is_revision_bound_and_matches_the_existing_surface(tmp_path):
    vault = _opened(tmp_path)
    expected = overview(vault.ledger.projection(), "en-US", "2026-02-01")
    reply = OpenedVaultSurfaceProvider(vault).read_surface(
        "overview_accounts", {"read_on": "2026-02-01"})

    assert reply["state"] == "ready"
    assert reply["freshness"] == "current"
    assert reply["revision"].startswith("g-")
    assert reply["overview"] == expected
    assert reply["accounts"] == expected


def test_direct_current_overview_matches_priority_and_denies_canonical_raw(
        tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    provider = OpenedVaultSurfaceProvider(vault)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("current Overview opened canonical or raw storage")
    monkeypatch.setattr(vault.ledger, "projection_as_of", forbidden)
    monkeypatch.setattr(vault.ledger, "projection", forbidden)
    monkeypatch.setattr(vault.ledger, "snapshot_projection", forbidden)
    monkeypatch.setattr(vault.ledger.store, "snapshot_events", forbidden)
    monkeypatch.setattr(vault.raw, "doc_ids", forbidden)
    direct = provider.read_surface("overview", {"read_on": "2026-02-01"})
    priority = provider.read_surface(
        "overview_accounts", {"read_on": "2026-02-01"})
    assert direct == priority["overview"] == priority["accounts"]


@pytest.mark.parametrize("lifecycle", ["stale", "degraded", "rebuilding"])
def test_direct_current_overview_refuses_noncurrent_read_store(tmp_path, lifecycle):
    vault = _opened(tmp_path)
    vault.read_store_lifecycle = lifecycle
    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface(
            "overview", {"read_on": "2026-02-01"})


def test_direct_current_overview_refuses_failed_post_write_then_recovers(
        tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    provider = OpenedVaultSurfaceProvider(vault)
    prior = provider.read_surface("overview", {"read_on": "2026-02-01"})
    original = vault.read_store.synchronize
    def fail(*_args, **_kwargs):
        raise ReadStoreDegraded("injected catch-up failure")
    monkeypatch.setattr(vault.read_store, "synchronize", fail)
    vault.ledger.append(closing_balance_observed(
        "cash", "150.00", "2026-02-28"))
    with pytest.raises(BridgeRequestError, match="not caught up"):
        provider.read_surface("overview", {"read_on": "2026-03-01"})
    monkeypatch.setattr(vault.read_store, "synchronize", original)
    assert vault.synchronize_read_store() in {"equal", "rebuilt", "caught_up"}
    current = provider.read_surface("overview", {"read_on": "2026-03-01"})
    assert current != prior
    assert current == provider.read_surface(
        "overview_accounts", {"read_on": "2026-03-01"})["overview"]


def test_routine_bundle_never_opens_projection_event_or_raw_paths(tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    monkeypatch.setattr(vault.ledger, "projection",
                        lambda: (_ for _ in ()).throw(AssertionError("projection")))
    monkeypatch.setattr(vault.ledger.store, "snapshot_events",
                        lambda: (_ for _ in ()).throw(AssertionError("events")))
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda: (_ for _ in ()).throw(AssertionError("raw")))

    reply = OpenedVaultSurfaceProvider(vault).read_surface(
        "overview_accounts", {"read_on": "2026-02-01"})
    assert reply["state"] == "ready"


def test_failed_catch_up_retains_prior_revision_and_never_replays_write(
        tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    provider = OpenedVaultSurfaceProvider(vault)
    before = provider.read_surface(
        "overview_accounts", {"read_on": "2026-02-01"})
    def fail(*_args, **_kwargs):
        raise ReadStoreDegraded("injected catch-up failure")

    monkeypatch.setattr(vault.read_store, "synchronize", fail)
    vault.ledger.append(closing_balance_observed(
        "cash", "150.00", "2026-02-28"))
    appended = vault.ledger.store.authenticated_identity()[0]
    stale = provider.read_surface(
        "overview_accounts", {"read_on": "2026-02-01", "refresh": 1})

    assert stale["state"] == "stale"
    assert stale["freshness"] == "stale"
    assert stale["revision"] == before["revision"]
    assert stale["overview"] == before["overview"]
    assert vault.ledger.store.authenticated_identity()[0] == appended


def test_new_vault_opens_with_an_independently_keyed_read_store(tmp_path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    assert vault.read_store is not None
    assert vault.read_store_lifecycle in {"rebuilding", "stale", "equal", "rebuilt"}
    assert (vault.directory / "read-model" / "key.json").is_file()
    assert (vault.directory / "events.jsonl").read_text().splitlines()[0] \
        != (vault.directory / "read-model" / "key.json").read_text().strip()


def test_degraded_lifecycle_never_claims_ready_or_current(tmp_path):
    vault = _opened(tmp_path)
    vault.read_store_lifecycle = "degraded"

    reply = OpenedVaultSurfaceProvider(vault).read_surface(
        "overview_accounts", {"read_on": "2026-02-01"})

    assert reply["state"] == "degraded"
    assert reply["freshness"] == "unavailable"
    assert reply["revision"].startswith("g-")
    assert reply["error"] == "read_store_unavailable"


def test_unreadable_generation_never_falls_back_to_legacy_projection(
        tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    monkeypatch.setattr(vault.read_store, "open_reader",
                        lambda: (_ for _ in ()).throw(
                            ReadStoreError("injected unreadable generation")))
    monkeypatch.setattr(vault.ledger, "projection",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("legacy projection fallback")))

    reply = OpenedVaultSurfaceProvider(vault).read_surface(
        "overview_accounts", {"read_on": "2026-02-01"})

    assert reply == {"state": "degraded", "freshness": "unavailable",
                     "lifecycle": "degraded", "revision": "",
                     "overview": None, "accounts": None,
                     "error": "read_store_unavailable"}


@pytest.mark.parametrize("surface", ["activity", "spending"])
def test_current_activity_and_spending_deny_canonical_and_raw_paths(
        tmp_path, monkeypatch, surface):
    vault = _opened(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("converted current read touched canonical or raw storage")

    monkeypatch.setattr(vault.ledger, "projection", forbidden)
    monkeypatch.setattr(vault.ledger, "projection_as_of", forbidden)
    monkeypatch.setattr(vault.ledger.store, "events", forbidden)
    monkeypatch.setattr(vault.ledger.store, "snapshot_events", forbidden)
    monkeypatch.setattr(vault.ledger.store, "committed_snapshot", forbidden)
    monkeypatch.setattr(vault.raw, "doc_ids", forbidden)
    monkeypatch.setattr(vault.raw, "get", forbidden)
    payload = OpenedVaultSurfaceProvider(vault).read_surface(
        surface, {"read_on": "2026-02-01"} if surface == "spending" else {})

    assert payload["state"] in {"absent", "empty", "ready"}


@pytest.mark.parametrize("surface", ["activity", "spending"])
def test_current_activity_and_spending_refuse_stale_without_fallback(
        tmp_path, monkeypatch, surface):
    vault = _opened(tmp_path)
    vault.read_store_lifecycle = "stale"
    monkeypatch.setattr(
        vault.ledger, "projection",
        lambda: pytest.fail("stale read fell back to LedgerProjection"))

    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface(
            surface, {"read_on": "2026-02-01"}
            if surface == "spending" else {})


def test_historical_activity_uses_held_sql_revision_without_event_prefix(
        tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    expected = activity(
        vault.ledger.projection_as_of("2026-01-15"), "en-US")
    monkeypatch.setattr(vault.ledger, "projection_as_of",
                        lambda *_args: pytest.fail("historical event replay"))
    payload = OpenedVaultSurfaceProvider(vault).read_surface(
        "activity", {"as_of": "2026-01-15"})

    assert payload == expected


def test_current_documents_uses_sql_and_only_enumerates_raw_presence(
        tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    touched = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("current Documents touched a forbidden storage path")

    monkeypatch.setattr(vault.ledger, "projection", forbidden)
    monkeypatch.setattr(vault.ledger, "projection_as_of", forbidden)
    monkeypatch.setattr(vault.ledger.store, "events", forbidden)
    monkeypatch.setattr(vault.ledger.store, "snapshot_events", forbidden)
    monkeypatch.setattr(vault.ledger.store, "committed_snapshot", forbidden)
    monkeypatch.setattr(vault.raw, "get", forbidden)
    monkeypatch.setattr(vault.raw, "has", forbidden)
    monkeypatch.setattr(vault.raw, "fingerprint", forbidden)
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda **kwargs: touched.append(kwargs) or [])

    payload = OpenedVaultSurfaceProvider(vault).read_surface("documents", {})

    assert payload["state"] == "absent"
    assert touched == [{"max_count": 10_000}]


def test_current_documents_refuses_stale_before_raw_enumeration(
        tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    vault.read_store_lifecycle = "stale"
    monkeypatch.setattr(
        vault.raw, "doc_ids",
        lambda: pytest.fail("stale Documents enumerated raw storage"))
    monkeypatch.setattr(
        vault.ledger, "projection",
        lambda: pytest.fail("stale Documents fell back to LedgerProjection"))

    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface("documents", {})


def test_documents_raw_presence_is_bounded_only_after_explicit_navigation(
        tmp_path, monkeypatch):
    from viva.desktop_bridge import vault_surface

    vault = _opened(tmp_path)
    monkeypatch.setattr(vault_surface, "MAX_RAW_PRESENCE", 2)
    for name in ("a", "b"):
        (vault.raw.dir / f"{name}.blob").write_bytes(b"not opened")
    provider = OpenedVaultSurfaceProvider(vault)
    monkeypatch.setattr(vault.raw, "get", lambda *_: pytest.fail("raw opened"))
    assert provider.read_surface("overview_accounts", {
        "read_on": "2026-02-01"})["state"] == "ready"
    assert provider.read_surface("documents", {})["raw_document_count"] == 2
    (vault.raw.dir / "c.blob").write_bytes(b"not opened")
    assert provider.read_surface("overview_accounts", {
        "read_on": "2026-02-01"})["state"] == "ready"
    with pytest.raises(BridgeRequestError, match="raw document presence exceeds"):
        provider.read_surface("documents", {})


def test_acknowledged_document_write_is_visible_on_the_next_current_read(tmp_path):
    vault = _opened(tmp_path)
    doc_id = vault.raw.put(b"synthetic statement")

    vault.ledger.append(document_captured(
        doc_id, "synthetic-statement.pdf", 19, "statement", 1,
        "2026-02-02", Provenance(doc_id)))
    payload = OpenedVaultSurfaceProvider(vault).read_surface("documents", {})

    assert payload["documents"] == [{
        "id": doc_id,
        "filename": "synthetic-statement.pdf",
        "doc_type": "statement",
        "resolved": False,
        "raw_available": True,
        "reading": "never_read",
        "snapshot_status": "unavailable",
        "snapshot_sentence": "Nothing here establishes whether this document's snapshot reached your books.",
        "activity_status": "not_applicable",
        "activity_sentence": "This document does not carry a separate brokerage-activity status.",
        "contribution": "Nothing on your books rests on this one yet.",
    }]


def test_current_review_does_not_open_canonical_or_raw_paths(tmp_path, monkeypatch):
    vault = _opened(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("current Review touched canonical or raw storage")

    monkeypatch.setattr(vault.ledger, "projection", forbidden)
    monkeypatch.setattr(vault.ledger, "projection_as_of", forbidden)
    monkeypatch.setattr(vault.ledger.store, "events", forbidden)
    monkeypatch.setattr(vault.ledger.store, "committed_snapshot", forbidden)
    monkeypatch.setattr(vault.raw, "doc_ids", forbidden)
    monkeypatch.setattr(vault.raw, "get", forbidden)
    payload = OpenedVaultSurfaceProvider(vault).read_surface(
        "review", {"as_of": "2026-09-30"})

    assert payload["contract"] == "ReviewSummary.v1"


def test_current_review_refuses_stale_without_fallback(tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    vault.read_store_lifecycle = "stale"
    monkeypatch.setattr(vault.ledger, "projection",
                        lambda: pytest.fail("Review fell back to legacy projection"))

    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface(
            "review", {"as_of": "2026-09-30"})


def test_current_plans_matches_canonical_payload_and_denies_legacy_paths(
        tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    expected = plans(vault.ledger.fresh_projection(), "en-US", "2026-08-29")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("current Plans touched canonical or raw storage")

    monkeypatch.setattr(vault.ledger, "fresh_projection", forbidden)
    monkeypatch.setattr(vault.ledger, "projection", forbidden)
    monkeypatch.setattr(vault.ledger.store, "events", forbidden)
    monkeypatch.setattr(vault.ledger.store, "committed_snapshot", forbidden)
    monkeypatch.setattr(vault.raw, "doc_ids", forbidden)
    monkeypatch.setattr(vault.raw, "get", forbidden)

    assert OpenedVaultSurfaceProvider(vault).read_surface(
        "plans", {"read_on": "2026-08-29"}) == expected


def test_current_plans_refuses_stale_without_fallback(tmp_path, monkeypatch):
    vault = _opened(tmp_path)
    vault.read_store_lifecycle = "stale"
    monkeypatch.setattr(vault.ledger, "fresh_projection",
                        lambda: pytest.fail("Plans fell back to fresh_projection"))

    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface(
            "plans", {"read_on": "2026-08-29"})


def test_acknowledged_goal_proposal_is_visible_on_next_current_plans_read(tmp_path):
    vault = _opened(tmp_path)
    provider = OpenedVaultSurfaceProvider(vault)
    before = provider.read_surface("plans", {"read_on": "2026-08-29"})
    vault.ledger.append(goal_proposal_recorded(
        "proposal:one", "create", "Synthetic plan", {
            "goal_id": "goal:one", "title": "Synthetic plan",
            "currency": "USD", "target_amount": "123.45"},
        {"amount": "123.45"}, "2026-08-28"))
    after = provider.read_surface("plans", {"read_on": "2026-08-29"})

    assert after != before
    assert [item["id"] for item in after["proposals"]] == ["proposal:one"]
