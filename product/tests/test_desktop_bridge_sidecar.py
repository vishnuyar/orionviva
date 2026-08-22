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
        {"vault_directory": str(tmp_path / "vault"),
         "passphrase": "test-passphrase", "create": True},
    ))[0])
    assert opened["ok"] is True
    # Made on purpose, and said as that rather than as an ordinary open.
    assert opened["result"]["state"] == "created"

    response = json.loads(sidecar.handle(_frame(
        "viva.surface.read", {"surface": "overview", "job_id": "job-1"}, "req-2",
    ))[-1])
    assert response["ok"] is True
    assert response["result"]["surface"] == "overview"
    assert 'test-passphrase' not in output.getvalue()


def test_a_folder_holding_no_vault_is_refused_rather_than_filled_with_one(tmp_path):
    """A path typed with a letter wrong used to answer as an opened, brand-new
    empty vault, which reads to somebody as their records having vanished."""
    from viva.persona import moment

    sidecar = Sidecar(io.StringIO())
    secret = "super-secret-passphrase"
    response = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "typo"), "passphrase": secret},
    ))[0])

    assert response["ok"] is False
    assert response["error"]["code"] == "vault_absent"
    assert response["error"]["message"] == moment("vault_absent")
    assert secret not in json.dumps(response)
    assert not (tmp_path / "typo").exists()


def test_a_vault_this_passphrase_will_not_open_is_told_apart_from_an_absent_one(
        tmp_path):
    from viva.persona import moment
    from viva.vault import Vault

    Vault.open(tmp_path / "vault", "the-real-one")
    sidecar = Sidecar(io.StringIO())

    response = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "vault"), "passphrase": "not-it"},
    ))[0])

    assert response["error"]["code"] == "vault_wrong_passphrase"
    assert response["error"]["message"] == moment("vault_wrong_passphrase")
    assert "not-it" not in json.dumps(response)


def test_a_path_that_is_not_a_folder_is_told_apart_from_both(tmp_path):
    from viva.persona import moment

    (tmp_path / "a-file").write_text("not a vault")
    sidecar = Sidecar(io.StringIO())

    response = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "a-file"), "passphrase": "secret"},
    ))[0])

    assert response["error"]["code"] == "vault_not_a_directory"
    assert response["error"]["message"] == moment("vault_not_a_folder")


def test_a_vault_made_on_purpose_is_opened_and_reopened_without_asking_again(
        tmp_path):
    sidecar = Sidecar(io.StringIO())
    made = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "vault"), "passphrase": "secret",
         "create": True},
    ))[0])
    reopened = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "vault"), "passphrase": "secret"},
        "req-2",
    ))[0])

    assert made["result"]["state"] == "created"
    assert reopened["result"]["state"] == "opened"


def test_sidecar_rejects_invalid_open_payload_without_activating_live_reads():
    sidecar = Sidecar(io.StringIO())
    response = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": "/tmp/vault", "passphrase": "secret", "extra": True},
    ))[0])

    assert response["ok"] is False
    # A request this handler would not take at all, told apart from a folder
    # that held no vault: the caller got a field wrong and needs to know which.
    assert response["error"]["code"] == "invalid_request"
    assert "extra" in response["error"]["message"]
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
        {"vault_directory": str(tmp_path / "first"), "passphrase": "first-secret",
         "create": True},
    ))[0])
    assert opened["ok"] is True

    def fail_open(*_args, **_kwargs):
        raise RuntimeError("wrong passphrase")

    monkeypatch.setattr(sidecar_module.Vault, "open", fail_open)
    failed = json.loads(sidecar.handle(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "second"), "passphrase": "second-secret",
         "create": True},
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
