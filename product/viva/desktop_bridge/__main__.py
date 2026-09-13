"""Run the OrionViva desktop bridge as a JSON-lines sidecar.

Foreground writes and vault operations run sequentially. A Jobs registry read
uses one bounded background slot so a delayed registry lock does not hold the
request loop; it has no vault mutation or read-store access. Foreground jobs pump stop frames between
completed steps while retaining all other frames in arrival order. Paid
maintenance runs on an independently cached vault handle and receives stop
requests through the shared job registry without reading transport input.
"""

from __future__ import annotations

import logging
import select
from threading import RLock, Thread
import sys
from pathlib import Path
from typing import Any

from viva.configuration import put_stored_in_force
from viva.vault import Vault
from viva.desktop_bridge.handlers import (
    BridgeDispatcher,
    default_handlers,
    handlers_for_opened_vault,
)
from viva.desktop_bridge.rpc import CURRENT_PROTOCOL, dispatch_frame, encode_frame
from viva.surface import BRIDGE_OPEN_DEMO_VAULT, BRIDGE_OPEN_VAULT

log = logging.getLogger(__name__)

# Surfaces exposed by the opened-vault provider.
def _surface_names() -> frozenset[str]:
    from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider

    return OpenedVaultSurfaceProvider._SURFACES

# Operations that may interrupt a running job.
CANCEL_OPERATIONS = frozenset({"viva.documents.cancel"})


def _open_vault(payload: dict[str, Any]) -> tuple[Vault, bool]:
    """Open the named vault and return it with whether ``create`` made it."""
    allowed = {"vault_directory", "passphrase", "create"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise ValueError("bridge.open_vault does not accept fields: " + ", ".join(sorted(unexpected)))
    directory = payload.get("vault_directory")
    passphrase = payload.get("passphrase")
    create = payload.get("create", False)
    if not isinstance(directory, str) or not directory.strip():
        raise ValueError("vault_directory must be a non-empty string")
    if not isinstance(passphrase, str) or not passphrase:
        raise ValueError("passphrase must be a non-empty string")
    if not isinstance(create, bool):
        raise ValueError("create must be true or false")
    from viva.vault import holds_a_vault

    made = create and not holds_a_vault(Path(directory))
    return Vault.open(Path(directory), passphrase, create=create,
                      start_read_store_worker=True), made


def _open_demo_vault(payload: dict[str, Any]) -> tuple[Vault, bool]:
    """Open or create the persistent sample vault from an empty payload."""
    allowed = ()
    extra = set(payload).difference(allowed)
    if extra:
        raise ValueError("bridge.open_demo_vault does not accept fields: "
                         + ", ".join(sorted(extra)))
    from viva.demo import open_demo_vault

    return open_demo_vault()


# Vault-open operations handled before ordinary dispatch.
OPEN_OPERATIONS = {
    BRIDGE_OPEN_VAULT: _open_vault,
    BRIDGE_OPEN_DEMO_VAULT: _open_demo_vault,
}


def _sample_frame() -> dict[str, str]:
    """Return the reviewed sample-frame copy."""
    return {"title": _moment("sample_frame"),
            "detail": _moment("sample_frame_detail"),
            "leave": _moment("sample_frame_leave")}


def _what_opened(made: bool, sample: bool) -> str:
    """Return the copy key for the completed open operation."""
    if sample:
        return "vault_sample_opened"
    return "vault_created" if made else "vault_opened"


class Sidecar:
    """Own the process-local opened-vault lifecycle and allowlist."""

    def __init__(self, output, source=None) -> None:
        self._output = output
        self._source = source
        self._dispatcher: BridgeDispatcher = default_handlers()
        self._vault: Vault | None = None
        # Frames buffered during a running job, in arrival order.
        self._held: list[str] = []
        self._output_lock = RLock()
        self._active_request_id: str | None = None
        self._vault_generation = 0
        self._jobs_pending: dict[str, int] = {}
        self._jobs_worker_busy = False

    @property
    def handlers(self) -> BridgeDispatcher:
        return self._dispatcher

    def handle(self, frame: str) -> list[str]:
        if self._vault is not None:
            self._vault.poll_read_store_worker()
        request = _decode_request_id(frame)
        if request is not None and request["operation"] in OPEN_OPERATIONS:
            open_it = OPEN_OPERATIONS[request["operation"]]
            sample = request["operation"] == BRIDGE_OPEN_DEMO_VAULT
            return [self._open(request["request_id"], request["payload"],
                               open_it, sample)]
        if request is None:
            return [dispatch_frame(frame, self._dispatcher.handlers)]
        self._active_request_id = request["request_id"]
        try:
            return [dispatch_frame(frame, self._dispatcher.handlers)]
        finally:
            self._active_request_id = None

    def serve(self, frame: str) -> None:
        """Dispatch one frame while isolating the registry-only read slot."""
        request = _decode_request_id(frame)
        if (self._vault is not None and request is not None
                and request["operation"] == "viva.surface.read"
                and isinstance(request["payload"], dict)
                and request["payload"].get("surface") == "jobs"):
            request_id = request["request_id"]
            with self._output_lock:
                if self._jobs_worker_busy:
                    self._output.write(_jobs_unavailable(request_id))
                    self._output.flush()
                    return
                generation = self._vault_generation
                self._jobs_pending[request_id] = generation
                self._jobs_worker_busy = True
            handlers = self._dispatcher.handlers

            def read_jobs() -> None:
                try:
                    response = dispatch_frame(frame, handlers)
                except BaseException:
                    response = _jobs_unavailable(request_id)
                with self._output_lock:
                    self._jobs_worker_busy = False
                    if self._jobs_pending.get(request_id) != generation:
                        return
                    del self._jobs_pending[request_id]
                    self._output.write(response)
                    self._output.flush()

            try:
                Thread(target=read_jobs, daemon=True, name="jobs-registry-read").start()
            except RuntimeError:
                with self._output_lock:
                    self._jobs_worker_busy = False
                    self._jobs_pending.pop(request_id, None)
                    self._output.write(_jobs_unavailable(request_id))
                    self._output.flush()
            return
        for response in self.handle(frame):
            self._write(response)

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

        Sources without a nonblocking file descriptor return no lines."""
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
        with self._output_lock:
            self._output.write(response)
            self._output.flush()

    def _open(self, request_id: str, payload: dict[str, Any],
              open_it=_open_vault, sample: bool = False) -> str:
        vault = None
        try:
            vault, made = open_it(payload)
            dispatcher = handlers_for_opened_vault(
                vault,
                lambda event: self._write_event(
                    self._active_request_id or request_id, event.as_dict()),
                self.pump,
            )
        except Exception as exc:  # noqa: BLE001 - protocol must stay alive.
            if vault is not None:
                try:
                    vault.close()
                except Exception:
                    pass
            log.debug("vault open failed: %s", exc)
            # Sample-open failures use sample-specific copy.
            code, said = (("sample_vault_unopened", _moment("sample_vault_unopened"))
                          if sample else _why_it_did_not_open(exc))
            return encode_frame({
                "protocol": CURRENT_PROTOCOL.wire(),
                "request_id": request_id,
                "ok": False,
                "error": {"code": code, "message": said},
            })
        if self._vault is not None:
            try:
                self._vault.close()
            except Exception:
                try:
                    vault.close()
                except Exception:
                    pass
                return encode_frame({
                    "protocol": CURRENT_PROTOCOL.wire(),
                    "request_id": request_id, "ok": False,
                    "error": {"code": "handler_failed", "message": "vault replacement unavailable"},
                })
        with self._output_lock:
            self._vault_generation += 1
            for pending_id in tuple(self._jobs_pending):
                self._output.write(_jobs_unavailable(pending_id))
            self._output.flush()
            self._jobs_pending.clear()
        self._vault = vault
        self._dispatcher = dispatcher
        return encode_frame({
            "protocol": CURRENT_PROTOCOL.wire(),
            "request_id": request_id,
            "ok": True,
            # The opening side declares whether the vault is the sample.
            "result": {"state": "created" if made else "opened",
                       "message": _moment(_what_opened(made, sample)),
                       "sample": sample,
                       # Supply the shipped sample-frame copy.
                       **({"frame": _sample_frame()} if sample else {}),
                       "surfaces": sorted(_surface_names()),
                       "priority_reads": ["overview_accounts"]},
        })

    def _write_event(self, request_id: str, event: dict[str, Any]) -> None:
        self._write(encode_frame({
            "protocol": CURRENT_PROTOCOL.wire(),
            "request_id": request_id,
            "event": "job.progress",
            "result": event,
        }))


# Map vault-open failures to stable caller codes and reviewed copy.
def _why_it_did_not_open(exc: Exception) -> tuple[str, str]:
    from viva.crypto import CryptoError
    from viva.vault import VaultNotFound

    if isinstance(exc, VaultNotFound):
        return "vault_absent", _moment("vault_absent")
    if isinstance(exc, NotADirectoryError):
        return "vault_not_a_directory", _moment("vault_not_a_folder")
    if isinstance(exc, CryptoError):
        return "vault_wrong_passphrase", _moment("vault_wrong_passphrase")
    # Preserve request-shape errors for the caller.
    if isinstance(exc, ValueError):
        return "invalid_request", str(exc)
    return "vault_open_failed", _moment("vault_absent")


def _moment(key: str) -> str:
    from viva.persona import moment

    return moment(key)


def _is_cancel(frame: str) -> bool:
    """Whether this frame asks to stop a job.

    Only named cancellation operations are answered during a running job."""
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
    if isinstance(operation, str) and isinstance(request_id, str):
        return {"operation": operation, "request_id": request_id, "payload": payload.get("payload", {})}
    return None


def _jobs_unavailable(request_id: str) -> str:
    return encode_frame({
        "protocol": CURRENT_PROTOCOL.wire(), "request_id": request_id,
        "ok": False, "error": {"code": "handler_failed", "message": "jobs read unavailable"},
    })


def main() -> int:
    if sys.argv[1:] == ["--read-store-worker"]:
        from viva.read_store.worker import main as worker_main
        return worker_main()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    # Verify SQLCipher before accepting requests.
    from viva.read_store import assert_sqlcipher_runtime
    assert_sqlcipher_runtime()
    # Restore persisted configuration before accepting the first frame.
    put_stored_in_force()
    sidecar = Sidecar(sys.stdout, sys.stdin)
    # ``readline`` keeps buffered frames visible to the request pump.
    while True:
        for held in sidecar.held():
            sidecar.serve(held)
        line = sys.stdin.readline()
        if not line:
            if sidecar._vault is not None:
                sidecar._vault.close()
            return 0
        if not line.strip():
            continue
        sidecar.serve(line)


if __name__ == "__main__":
    raise SystemExit(main())
