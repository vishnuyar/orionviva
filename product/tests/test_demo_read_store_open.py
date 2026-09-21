from __future__ import annotations

import io
import json

from viva.desktop_bridge.__main__ import Sidecar
from viva.read_store import ReadStore, ReadStoreDegraded


def _frame(request_id: str, operation: str, payload=None) -> str:
    return json.dumps({"protocol": "2.0", "request_id": request_id,
                       "operation": operation, "payload": payload or {}})


def test_sample_open_returns_only_after_exact_encrypted_projection_is_current(
        tmp_path, monkeypatch):
    monkeypatch.setenv("VIVA_DEMO_HOME", str(tmp_path / "sample"))
    sidecar = Sidecar(io.StringIO())

    opened = json.loads(sidecar.handle(_frame("open", "bridge.open_demo_vault"))[0])
    assert opened["ok"] is True
    assert sidecar._vault is not None
    assert sidecar._vault.read_store_lifecycle in {"rebuilt", "caught_up", "equal"}
    assert sidecar._vault._read_store_worker is None

    priority = json.loads(sidecar.handle(_frame("read", "viva.surface.read", {
        "surface": "overview_accounts", "parameters": {}, "job_id": "priority",
    }))[0])
    assert priority["ok"] is True
    assert priority["result"]["data"]["state"] == "ready"
    assert priority["result"]["data"]["freshness"] == "current"
    assert priority["result"]["data"]["overview"]["accounts"]
    sidecar._vault.close()


def test_equal_sample_generation_is_authenticated_without_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("VIVA_DEMO_HOME", str(tmp_path / "sample"))
    first = Sidecar(io.StringIO())
    assert json.loads(first.handle(_frame("one", "bridge.open_demo_vault"))[0])["ok"]
    assert first._vault is not None
    first._vault.close()

    def rebuilt(*_args, **_kwargs):
        raise AssertionError("equal sample generation was rebuilt")

    monkeypatch.setattr(ReadStore, "publish", rebuilt)
    second = Sidecar(io.StringIO())
    opened = json.loads(second.handle(_frame("two", "bridge.open_demo_vault"))[0])
    assert opened["ok"] is True
    assert second._vault is not None
    assert second._vault.read_store_lifecycle == "equal"
    assert second._vault._read_store_worker is None
    second._vault.close()


def test_sample_projection_failure_refuses_open_instead_of_showing_empty_picture(
        tmp_path, monkeypatch):
    monkeypatch.setenv("VIVA_DEMO_HOME", str(tmp_path / "sample"))

    def failed(*_args, **_kwargs):
        raise ReadStoreDegraded("synthetic projector failure")

    monkeypatch.setattr(ReadStore, "synchronize", failed)
    sidecar = Sidecar(io.StringIO())
    response = json.loads(sidecar.handle(_frame("open", "bridge.open_demo_vault"))[0])
    assert response["ok"] is False
    assert response["error"]["code"] == "sample_vault_unopened"
    assert "synthetic projector failure" not in json.dumps(response)
    assert sidecar._vault is None


def test_sample_projection_failure_closes_attempt_and_a_later_open_recovers(
        tmp_path, monkeypatch):
    monkeypatch.setenv("VIVA_DEMO_HOME", str(tmp_path / "sample"))
    synchronize = ReadStore.synchronize
    attempts = 0

    def fail_once(store, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ReadStoreDegraded("synthetic interrupted projection")
        return synchronize(store, *args, **kwargs)

    monkeypatch.setattr(ReadStore, "synchronize", fail_once)
    sidecar = Sidecar(io.StringIO())
    refused = json.loads(sidecar.handle(_frame("one", "bridge.open_demo_vault"))[0])
    recovered = json.loads(sidecar.handle(_frame("two", "bridge.open_demo_vault"))[0])
    assert refused["ok"] is False
    assert recovered["ok"] is True
    assert sidecar._vault is not None
    assert sidecar._vault.read_store_lifecycle in {"equal", "caught_up", "rebuilt"}
    sidecar._vault.close()


def test_sample_creation_directly_publishes_authenticated_read_store(tmp_path, monkeypatch):
    # Exercise the real sample API outside the bridge's intentionally generic
    # refusal so platform failures retain their traceback in synthetic CI.
    from viva.demo import open_demo_vault

    monkeypatch.setenv("VIVA_DEMO_HOME", str(tmp_path / "sample"))
    vault, made = open_demo_vault()
    try:
        assert made is True
        assert vault.read_store_lifecycle in {"rebuilt", "caught_up", "equal"}
        assert vault.read_store is not None
        expected = vault.ledger.store.authenticated_identity()
        with vault.read_store.open_reader() as revision:
            source = vault.read_store.authenticated_source_identity(revision)
        assert source["count"] == expected[0]
        assert source["head"] == expected[1]
    finally:
        vault.close()
