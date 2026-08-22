"""Run the OrionViva desktop bridge as a JSON-lines sidecar.

The loop answers one request before it reads the next, which is what keeps one
writer on the vault at a time. A job that runs for a while would therefore be
unstoppable: the frame asking it to stop would sit unread on the transport
until the work it names had finished.

So a running job pumps. Between its steps — never inside one — it asks this
module to read whatever has already arrived on standard input. A frame asking
to stop a job is answered there and then, because that is the only moment at
which answering it can change anything. Every other frame is held in arrival
order and served by the ordinary loop once the current one is answered, which
is exactly what would have happened had nothing pumped. Ordering is preserved
and no second writer is created; the only thing that changes is that a stop
can be heard.

Nothing is interrupted mid-write. The pump reads; the checkpoint that called
it decides; and a job that stops does so between two steps, leaving the vault
at a step that finished.
"""

from __future__ import annotations

import logging
import select
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

# The operations a running job may be interrupted to serve. Every one of them
# stops work; none of them starts any. A frame outside this set waits, because
# serving it here would put a second handler on the vault while the first is
# still working.
CANCEL_OPERATIONS = frozenset({"viva.documents.cancel"})


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

    def __init__(self, output, source=None) -> None:
        self._output = output
        self._source = source
        self._dispatcher: BridgeDispatcher = default_handlers()
        self._vault: Vault | None = None
        # Frames the pump read while a job was running, in the order they
        # arrived. The loop drains this before it reads the transport again,
        # so a frame that was pumped is served at the point in the sequence it
        # would have been served at anyway.
        self._held: list[str] = []

    @property
    def handlers(self) -> BridgeDispatcher:
        return self._dispatcher

    def handle(self, frame: str) -> list[str]:
        request = _decode_request_id(frame)
        if request is not None and request["operation"] == "bridge.open_vault":
            response = self._open(request["request_id"], request["payload"])
            return [response]
        return [dispatch_frame(frame, self._dispatcher.handlers)]

    # --------------------------------------------------------------- pumping

    def pump(self) -> None:
        """Read what has already arrived, and answer only a stop.

        Called by a running job between its steps. It never blocks: a
        transport with nothing waiting leaves this a no-op, so a job that
        finishes quickly pays nothing for being stoppable.

        A stop is answered here because answering it later cannot change
        anything. Every other frame is held, because answering it here would
        run a second handler against the vault while the first is still
        working — which is the one thing the single-frame loop exists to
        prevent."""
        for frame in self._arrived():
            if _is_cancel(frame):
                self._write(dispatch_frame(frame, self._dispatcher.handlers))
            else:
                self._held.append(frame)

    def _arrived(self) -> list[str]:
        """Every whole line already waiting on the transport, and no more.

        A source that cannot be asked without blocking — anything that is not
        a real file — is not asked at all, which leaves a job unstoppable
        rather than leaving the loop stuck."""
        source = self._source
        if source is None:
            return []
        try:
            fileno = source.fileno()
        except (AttributeError, OSError, ValueError):
            return []
        lines: list[str] = []
        while True:
            try:
                ready, _, _ = select.select([fileno], [], [], 0)
            except (OSError, ValueError):
                return lines
            if not ready:
                return lines
            line = source.readline()
            if not line:
                return lines
            if line.strip():
                lines.append(line)

    def held(self) -> list[str]:
        """The frames the pump read and did not answer, oldest first."""
        held, self._held = self._held, []
        return held

    def _write(self, response: str) -> None:
        self._output.write(response)
        self._output.flush()

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
            self.pump,
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


def _is_cancel(frame: str) -> bool:
    """Whether this frame asks to stop a job.

    Read off the operation name and off nothing else. A frame is answered
    mid-job only when it is one of the operations that can change what a
    running job does, and that set is named here rather than guessed at from
    the shape of a payload."""
    import json

    try:
        payload = json.loads(frame)
    except (TypeError, json.JSONDecodeError):
        return False
    return (isinstance(payload, dict)
            and payload.get("operation") in CANCEL_OPERATIONS)


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
    sidecar = Sidecar(sys.stdout, sys.stdin)
    # `readline` rather than iteration: a file iterator reads ahead into a
    # buffer of its own, and a frame sitting in that buffer is invisible both
    # to this loop and to the pump. Reading a line at a time is what keeps the
    # transport the one place a frame waits.
    while True:
        for held in sidecar.held():
            for response in sidecar.handle(held):
                sys.stdout.write(response)
                sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            return 0
        if not line.strip():
            continue
        for response in sidecar.handle(line):
            sys.stdout.write(response)
            sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
