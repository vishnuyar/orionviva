"""Acceptance contracts for the concrete opened-vault bridge provider."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from viva.desktop_bridge import dispatch_frame, handlers_with_surface_provider
from viva.vault import Vault


def _frame(*, operation: str, payload: dict[str, Any] | None = None) -> str:
    return json.dumps({
        "protocol": "2.0",
        "request_id": "vault-read-1",
        "operation": operation,
        "payload": payload or {},
    })


def _concrete_provider(vault: Vault):
    """Load the production opened-vault adapter."""

    try:
        module = importlib.import_module("viva.desktop_bridge.vault_provider")
    except ModuleNotFoundError as exc:
        pytest.fail(
            "missing concrete opened-Vault bridge adapter: expected "
            "viva.desktop_bridge.vault_provider"
        )
        raise AssertionError from exc

    factory = getattr(module, "create_vault_surface_provider", None)
    if factory is None:
        pytest.fail(
            "missing create_vault_surface_provider(vault) factory in "
            "viva.desktop_bridge.vault_provider"
        )
    return factory(vault)


def _read(vault: Vault, surface: str, events: list[Any] | None = None) -> dict[str, Any]:
    provider = _concrete_provider(vault)
    dispatcher = handlers_with_surface_provider(
        provider,
        events.append if events is not None else None,
    )
    response = json.loads(
        dispatch_frame(
            _frame(
                operation="viva.surface.read",
                payload={"surface": surface, "job_id": f"{surface}-job"},
            ),
            dispatcher.handlers,
        )
    )
    assert response["ok"] is True
    return response["result"]


def test_concrete_provider_reads_empty_open_vault_as_json_safe_surfaces(tmp_path: Path):
    vault = Vault.open(tmp_path / "empty-vault", "test-passphrase")
    vault.synchronize_read_store()

    for surface in ("overview", "documents", "conversation"):
        result = _read(vault, surface)
        json.dumps(result)
        assert result["surface"] == surface
        assert isinstance(result["data"], dict)


def test_concrete_provider_reads_open_vault_and_keeps_surface_payloads_json_safe(tmp_path: Path):
    directory = tmp_path / "vault"
    opened = Vault.open(directory, "test-passphrase")
    reopened = Vault.open(directory, "test-passphrase")
    reopened.synchronize_read_store()

    for surface in ("overview", "documents", "conversation"):
        result = _read(reopened, surface)
        assert result["surface"] == surface
        json.dumps(result["data"], allow_nan=False)

    assert opened.directory == reopened.directory


def test_concrete_provider_emits_started_and_completed_progress(tmp_path: Path):
    events: list[Any] = []
    vault = Vault.open(tmp_path / "vault", "test-passphrase")
    vault.synchronize_read_store()

    _read(vault, "overview", events)

    assert [event.status for event in events] == ["started", "completed"]
    assert [event.completed for event in events] == [0, 1]
    assert all(event.job_id == "overview-job" for event in events)


def test_concrete_provider_failure_emits_failed_progress_and_error_frame(tmp_path: Path):
    vault = Vault.open(tmp_path / "vault", "test-passphrase")
    provider = _concrete_provider(vault)
    events: list[Any] = []

    def failing_provider(_surface: str, _parameters: dict[str, Any]):
        raise RuntimeError("vault read failed")

    provider.read_surface = failing_provider
    dispatcher = handlers_with_surface_provider(provider, events.append)
    response = json.loads(
        dispatch_frame(
            _frame(operation="viva.surface.read", payload={"surface": "overview"}),
            dispatcher.handlers,
        )
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "handler_failed"
    assert events[-1].status == "failed"


def test_routine_startup_surfaces_do_not_enumerate_raw_store(tmp_path: Path, monkeypatch):
    vault = Vault.open(tmp_path / "vault", "test-passphrase")
    vault.synchronize_read_store()
    touched: list[str] = []

    def record(name, result):
        def spy(*_args, **_kwargs):
            touched.append(name)
            return result
        return spy

    # Cover every public route that can inspect blob names/content or compute a
    # raw-content address. Returning inert values lets the whole startup burst
    # run, so one early access cannot hide a later, different access.
    monkeypatch.setattr(vault.raw, "doc_ids", record("doc_ids", []))
    monkeypatch.setattr(vault.raw, "has", record("has", False))
    monkeypatch.setattr(vault.raw, "get", record("get", b""))
    monkeypatch.setattr(vault.raw, "fingerprint", record("fingerprint", "0" * 64))
    monkeypatch.setattr(vault.raw, "put", record("put", "0" * 64))
    for surface in ("overview_accounts", "jobs", "conversation", "review",
                    "activity", "spending", "plans", "trust"):
        _read(vault, surface)
    assert touched == []
