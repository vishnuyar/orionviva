"""Run the OrionViva desktop bridge as a JSON-lines sidecar.

Foreground requests run sequentially. Foreground jobs pump stop frames between
completed steps while retaining all other frames in arrival order. Paid
maintenance runs on an independently cached vault handle and receives stop
requests through the shared job registry without reading transport input.
"""

from __future__ import annotations

import logging
import select
from threading import RLock
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

# The surfaces an opened vault answers for. Read off the provider that serves
# them rather than written twice: a list here that fell behind would promise a
# caller a read the sidecar no longer has.
def _surface_names() -> frozenset[str]:
    from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider

    return OpenedVaultSurfaceProvider._SURFACES

# The operations a running job may be interrupted to serve. Every one of them
# stops work; none of them starts any. A frame outside this set waits, because
# serving it here would put a second handler on the vault while the first is
# still working.
CANCEL_OPERATIONS = frozenset({"viva.documents.cancel"})


def _open_vault(payload: dict[str, Any]) -> tuple[Vault, bool]:
    """Open the vault a person named, or make one where they said to.

    ``create`` is the person's own word and defaults to false. A path typed
    with a letter wrong used to answer as an opened, brand-new empty vault,
    which reads to somebody as their records having vanished; nothing here
    makes a vault unless somebody asked for one at that exact path.

    Returns the vault and whether it was made, because a vault that was made is
    a different thing to be told about than one that was opened."""
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
    return Vault.open(Path(directory), passphrase, create=create), made


def _open_demo_vault(payload: dict[str, Any]) -> tuple[Vault, bool]:
    """Open the sample vault, minting it where it lives if it is not there yet.

    The request carries nothing. Where the sample vault lives and what opens it
    are the engine's own, so a caller cannot point this at a directory they
    keep their own records in, and cannot learn the passphrase by asking. That
    is a fence kept by the shape of the request rather than by a check.

    It is minted once and stays. A sample vault made fresh each launch would
    lose whatever a person did inside it, and a demo somebody cannot change is
    a screenshot."""
    allowed = ()
    extra = set(payload).difference(allowed)
    if extra:
        raise ValueError("bridge.open_demo_vault does not accept fields: "
                         + ", ".join(sorted(extra)))
    from viva.demo import open_demo_vault

    return open_demo_vault()


# The two ways a vault is opened, and the one place that says so. Both are
# answered before dispatch runs, so neither reaches an allowlist; keeping them
# in one table is what stops a second one being added without the branch that
# serves it.
OPEN_OPERATIONS = {
    BRIDGE_OPEN_VAULT: _open_vault,
    BRIDGE_OPEN_DEMO_VAULT: _open_demo_vault,
}


def _sample_frame() -> dict[str, str]:
    """The frame's own words: what the place is, what that means, and the one
    action that leaves it."""
    return {"title": _moment("sample_frame"),
            "detail": _moment("sample_frame_detail"),
            "leave": _moment("sample_frame_leave")}


def _what_opened(made: bool, sample: bool) -> str:
    """Which sentence a person gets about the vault that just opened.

    The sample vault says so in its own words rather than borrowing the private
    vault's: a screen that told somebody their vault was created, when what was
    created was the demo, has said something false about their records."""
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
        # Frames the pump read while a job was running, in the order they
        # arrived. The loop drains this before it reads the transport again,
        # so a frame that was pumped is served at the point in the sequence it
        # would have been served at anyway.
        self._held: list[str] = []
        self._output_lock = RLock()

    @property
    def handlers(self) -> BridgeDispatcher:
        return self._dispatcher

    def handle(self, frame: str) -> list[str]:
        request = _decode_request_id(frame)
        if request is not None and request["operation"] in OPEN_OPERATIONS:
            open_it = OPEN_OPERATIONS[request["operation"]]
            sample = request["operation"] == BRIDGE_OPEN_DEMO_VAULT
            return [self._open(request["request_id"], request["payload"],
                               open_it, sample)]
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
        with self._output_lock:
            self._output.write(response)
            self._output.flush()

    def _open(self, request_id: str, payload: dict[str, Any],
              open_it=_open_vault, sample: bool = False) -> str:
        try:
            vault, made = open_it(payload)
        except Exception as exc:  # noqa: BLE001 - protocol must stay alive.
            log.debug("vault open failed: %s", exc)
            # The sample vault fails differently, because a person opening it
            # named no folder and no passphrase. Telling them a directory was
            # absent would be telling them about a path they never typed.
            code, said = (("sample_vault_unopened", _moment("sample_vault_unopened"))
                          if sample else _why_it_did_not_open(exc))
            return encode_frame({
                "protocol": CURRENT_PROTOCOL.wire(),
                "request_id": request_id,
                "ok": False,
                "error": {"code": code, "message": said},
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
            # Whether this is the sample vault is stated by the side that
            # opened it. An interface deciding for itself which vault it is
            # looking at would be deciding whether to draw the frame that says
            # nothing here is real, and it would be right until the day it was
            # not.
            "result": {"state": "created" if made else "opened",
                       "message": _moment(_what_opened(made, sample)),
                       "sample": sample,
                       # The words the frame around the sample vault is drawn
                       # with, sent by the side that ships them. A shell
                       # composing its own frame would be writing the one
                       # sentence in this product that says nothing here is
                       # real, and writing it out of the pack's reach.
                       **({"frame": _sample_frame()} if sample else {}),
                       "surfaces": sorted(_surface_names())},
        })

    def _write_event(self, request_id: str, event: dict[str, Any]) -> None:
        self._write(encode_frame({
            "protocol": CURRENT_PROTOCOL.wire(),
            "request_id": request_id,
            "event": "job.progress",
            "result": event,
        }))


# Every way naming a folder can fail, against the code a caller reads and the
# sentence a person does. They are kept apart because they ask for completely
# different next steps — a folder holding no vault, a path that is not a folder,
# and a vault this passphrase will not open — and a single "unable to open
# vault" made all three look like the same mistake.
def _why_it_did_not_open(exc: Exception) -> tuple[str, str]:
    from viva.crypto import CryptoError
    from viva.vault import VaultNotFound

    if isinstance(exc, VaultNotFound):
        return "vault_absent", _moment("vault_absent")
    if isinstance(exc, NotADirectoryError):
        return "vault_not_a_directory", _moment("vault_not_a_folder")
    if isinstance(exc, CryptoError):
        return "vault_wrong_passphrase", _moment("vault_wrong_passphrase")
    # A request this handler would not take at all. Its own words travel,
    # because they are about the shape of the frame rather than about anybody's
    # money, and a caller needs to know which field it got wrong.
    if isinstance(exc, ValueError):
        return "invalid_request", str(exc)
    return "vault_open_failed", _moment("vault_absent")


def _moment(key: str) -> str:
    from viva.persona import moment

    return moment(key)


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
    if operation in OPEN_OPERATIONS and isinstance(request_id, str):
        return {"operation": operation, "request_id": request_id, "payload": payload.get("payload", {})}
    return None


def main() -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    # Restore persisted configuration before accepting the first frame.
    put_stored_in_force()
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
