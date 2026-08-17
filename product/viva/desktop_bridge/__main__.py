"""Run the OrionViva desktop bridge as a JSON-lines sidecar."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from viva.vault import Vault
from viva.desktop_bridge.handlers import (
    BridgeDispatcher,
    default_handlers,
    handlers_for_opened_vault,
)
from viva.desktop_bridge.rpc import CURRENT_PROTOCOL, dispatch_frame, encode_frame

log = logging.getLogger(__name__)


def _open_vault(payload: dict[str, Any]) -> Vault:
    allowed = {"vault_directory", "passphrase"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise ValueError("bridge.open_vault does not accept fields: " + ", ".join(sorted(unexpected)))
    directory = payload.get("vault_directory")
    passphrase = payload.get("passphrase")
    if not isinstance(directory, str) or not directory.strip():
        raise ValueError("vault_directory must be a non-empty string")
    if not isinstance(passphrase, str) or not passphrase:
        raise ValueError("passphrase must be a non-empty string")
    return Vault.open(Path(directory), passphrase)


class Sidecar:
    """Own the process-local opened-vault lifecycle and allowlist."""

    def __init__(self, output) -> None:
        self._output = output
        self._dispatcher: BridgeDispatcher = default_handlers()
        self._vault: Vault | None = None

    @property
    def handlers(self) -> BridgeDispatcher:
        return self._dispatcher

    def handle(self, frame: str) -> list[str]:
        request = _decode_request_id(frame)
        if request is not None and request["operation"] == "bridge.open_vault":
            response = self._open(request["request_id"], request["payload"])
            return [response]
        return [dispatch_frame(frame, self._dispatcher.handlers)]

    def _open(self, request_id: str, payload: dict[str, Any]) -> str:
        try:
            vault = _open_vault(payload)
        except Exception as exc:  # noqa: BLE001 - protocol must stay alive.
            log.debug("vault open failed: %s", exc)
            return encode_frame({
                "protocol": CURRENT_PROTOCOL.wire(),
                "request_id": request_id,
                "ok": False,
                "error": {"code": "vault_open_failed", "message": "unable to open vault"},
            })
        self._vault = vault
        self._dispatcher = handlers_for_opened_vault(
            vault,
            lambda event: self._write_event(request_id, event.as_dict()),
        )
        return encode_frame({
            "protocol": CURRENT_PROTOCOL.wire(),
            "request_id": request_id,
            "ok": True,
            "result": {"state": "opened", "surfaces": ["overview", "documents", "review"]},
        })

    def _write_event(self, request_id: str, event: dict[str, Any]) -> None:
        self._output.write(encode_frame({
            "protocol": CURRENT_PROTOCOL.wire(),
            "request_id": request_id,
            "event": "job.progress",
            "result": event,
        }))
        self._output.flush()


def _decode_request_id(frame: str) -> dict[str, Any] | None:
    import json

    try:
        payload = json.loads(frame)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    operation = payload.get("operation")
    request_id = payload.get("request_id")
    if operation == "bridge.open_vault" and isinstance(request_id, str):
        return {"operation": operation, "request_id": request_id, "payload": payload.get("payload", {})}
    return None


def main() -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    sidecar = Sidecar(sys.stdout)
    for line in sys.stdin:
        if not line.strip():
            continue
        for response in sidecar.handle(line):
            sys.stdout.write(response)
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
