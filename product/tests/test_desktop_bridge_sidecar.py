from __future__ import annotations

import io
import json

from viva.desktop_bridge import __main__ as sidecar_module
from viva.desktop_bridge.__main__ import Sidecar


def _frame(operation: str, payload: dict | None = None, request_id: str = "req-1") -> str:
    return json.dumps({
        "protocol": "2.0",
        "request_id": request_id,
        "operation": operation,
        "payload": payload or {},
    })


def test_sidecar_refuses_live_reads_until_host_opens_a_vault(tmp_path):
    sidecar = Sidecar(io.StringIO())
    response = json.loads(sidecar.handle(_frame("viva.surface.read", {"surface": "overview"}))[0])
    assert response["ok"] is False
    assert response["error"]["code"] == "operation_not_allowed"


def test_sidecar_opens_vault_and_enables_only_surface_reads(tmp_path):
    output = io.StringIO()
    sidecar = Sidecar(output)
    opened = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "vault"), "passphrase": "test-passphrase"},
    ))[0])
    assert opened["ok"] is True
    assert opened["result"]["state"] == "opened"

    response = json.loads(sidecar.handle(_frame(
        "viva.surface.read", {"surface": "overview", "job_id": "job-1"}, "req-2",
    ))[-1])
    assert response["ok"] is True
    assert response["result"]["surface"] == "overview"
    assert 'test-passphrase' not in output.getvalue()


def test_sidecar_open_failure_is_safe_and_does_not_echo_secret(tmp_path):
    sidecar = Sidecar(io.StringIO())
    secret = "super-secret-passphrase"
    response = json.loads(sidecar.handle(_frame(
        "bridge.open_vault", {"vault_directory": str(tmp_path / "vault"), "passphrase": secret},
    ))[0])
    assert response["ok"] is True
    assert secret not in json.dumps(response)


def test_sidecar_rejects_invalid_open_payload_without_activating_live_reads():
    sidecar = Sidecar(io.StringIO())
    response = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": "/tmp/vault", "passphrase": "secret", "extra": True},
    ))[0])

    assert response["ok"] is False
    assert response["error"]["code"] == "vault_open_failed"
    assert "secret" not in json.dumps(response)

    read = json.loads(sidecar.handle(_frame(
        "viva.surface.read", {"surface": "overview"}, "read-after-failure",
    ))[0])
    assert read["ok"] is False
    assert read["error"]["code"] == "operation_not_allowed"


def test_sidecar_failed_reopen_preserves_the_existing_open_vault(monkeypatch, tmp_path):
    output = io.StringIO()
    sidecar = Sidecar(output)
    opened = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "first"), "passphrase": "first-secret"},
    ))[0])
    assert opened["ok"] is True

    def fail_open(*_args, **_kwargs):
        raise RuntimeError("wrong passphrase")

    monkeypatch.setattr(sidecar_module.Vault, "open", fail_open)
    failed = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "second"), "passphrase": "second-secret"},
        "failed-reopen",
    ))[0])
    assert failed["ok"] is False
    assert failed["error"]["code"] == "vault_open_failed"
    assert "second-secret" not in json.dumps(failed)

    read = json.loads(sidecar.handle(_frame(
        "viva.surface.read", {"surface": "overview", "job_id": "still-open"}, "read-after-reopen-failure",
    ))[-1])
    assert read["ok"] is True
    assert read["result"]["surface"] == "overview"
