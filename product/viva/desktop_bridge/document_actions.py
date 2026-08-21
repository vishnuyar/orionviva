"""Injected vault-backed document actions.

This module knows neither the vault implementation nor the desktop transport. A
sidecar entry point injects one already-open vault and gets back the handlers
for the document actions this build serves.

Capture is all this path does. It asks for the parking reader by name rather
than building one and discarding the live half, so no model runs here whatever
the machine's environment holds: what comes back cannot read, so there is no
branch in which it does. What is captured is therefore parked, and the reply
says which of two true things happened — that no reader has been chosen, or
that one is named and nothing on this path used it.

The request carries a path and nothing else. Nothing about the file decides
what is done with it: its name, its extension and its contents are never
consulted to route it, because a document is routed by what a read declares it
to be and not by what its bytes look like from outside. Size is the one
property read before opening, and it is read to refuse rather than to route.

The documents capability also declares a ``cancel`` action, and no handler for
it is registered. The operation is therefore declared and unserved: a frame
naming it is refused by the allowlist rather than by silence.
"""

from __future__ import annotations

import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError
from .review_actions import UnreadableOutcome

# Why a capture was refused, in the machine's own words. An outcome refuses to
# be built without one, so each of these travels beside the sentence a person
# reads and says the same thing to whatever is counting.
NO_SUCH_FILE = "file_unavailable"
NOT_A_FILE = "not_a_regular_file"
TOO_LARGE = "file_over_size_limit"
UNREADABLE = "file_unreadable"


class DocumentActions:
    """Adapt one already-open vault into the allowlisted document handlers."""

    def __init__(self, vault: Any) -> None:
        self._vault = vault

    def upload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Capture one file into the vault, and read nothing.

        The reply says what happened and carries no identity: this capture is
        finished by the time it answers, and an id nothing consumes is a word
        that looks like a capability."""
        from viva.engine import upload
        from viva.ingest.reader import live_reading_configured, parking_reader

        path = _upload_request(payload)
        refusal = _refusal(path)
        if refusal is not None:
            return refusal.as_dict()
        try:
            data = path.read_bytes()
        except OSError:
            return _refused(UNREADABLE, "documents_cannot_open").as_dict()
        result = upload(self._vault, path.name, data, parking_reader())
        return _outcome(result, live_reading_configured()).as_dict()


def _upload_request(payload: Mapping[str, Any]) -> Path:
    """The one thing an upload request carries.

    A field set of exactly one is what stops a caller asserting anything else
    about the work — an identity among them — rather than a rule somewhere
    saying it should not."""
    allowed = {"path"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            "viva.documents.upload does not accept fields: "
            + ", ".join(sorted(unexpected)))
    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        raise BridgeRequestError("path must be a non-empty string")
    return Path(path)


def _refusal(path: Path) -> ActionOutcome | None:
    """Why this file will not be captured, or nothing.

    Everything here is decided before the file is opened. The ceiling is the
    reader's own, so one number bounds what this product will take in whichever
    way a document arrives, and it refuses instead of sealing a file that would
    hold the window for as long as it took to read it."""
    from viva.ingest.reader import MAX_BYTES

    try:
        found = path.stat()
    except OSError:
        return _refused(NO_SUCH_FILE, "documents_cannot_open")
    if not stat.S_ISREG(found.st_mode):
        return _refused(NOT_A_FILE, "documents_cannot_open")
    if found.st_size > MAX_BYTES:
        return _refused(TOO_LARGE, "documents_too_large",
                        limit=_size_limit(MAX_BYTES))
    return None


def _size_limit(limit: int) -> str:
    """The ceiling as a person reads it, in the unit it is written in."""
    return f"{limit // (1024 * 1024)} MB"


def _refused(why: str, key: str, **fields) -> ActionOutcome:
    from viva.persona import moment

    return ActionOutcome("refused", moment(key, **fields), reason=why)


def _outcome(result: Mapping[str, Any], reading_configured: bool) -> ActionOutcome:
    """What the capture did, said in the vocabulary an action answers in.

    The word is read off the action the engine declared, never inferred from
    the shape of the reply. Two actions are reachable from a route that asks
    for the reader which cannot read: a document is parked, or it is one the
    vault has already settled. Every other action raises, and the sentence the
    raise carries names no queue and no next screen — the nearest sentence to
    an outcome this path has no words for is a sentence about a different
    event, said to somebody standing somewhere else.

    The sentence is the pack's in every branch. The engine writes a message of
    its own and it does not travel: it promises a document will be understood
    when a projector for its type arrives, which is not a thing this product
    can do, and a screen is not where a promise like that gets made.
    """
    from viva.ingest import DUPLICATE, PARKED
    from viva.persona import moment

    action = result.get("action")
    if action == PARKED:
        return ActionOutcome("completed", moment(
            "documents_saved_unread" if reading_configured
            else "documents_saved_no_reader"))
    if action == DUPLICATE:
        return ActionOutcome("completed", moment("documents_already_held"))
    raise UnreadableOutcome(moment("documents_outcome_unstated"))
