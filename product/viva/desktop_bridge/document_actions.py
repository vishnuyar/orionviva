"""Injected vault-backed document actions.

This module knows neither the vault implementation nor the desktop transport. A
sidecar entry point injects one already-open vault and gets back the handlers
for the document actions this build serves.

Capture comes first and always: the bytes are sealed into the vault before
anything looks at them, so a document is kept whatever the reading then does.

Whether it is then **read** is decided by one question, asked in one place —
whether this machine names a model. Until somebody has said yes to naming one,
the reader that comes back cannot read, so there is no branch on this path in
which a model runs; once one is named, the same call returns the reader that
does. The permission is the configuration, and the configuration is a proposal
somebody agreed to.

The reply says which of five true things happened, each read off the action the
engine declared: the document was posted, it was read and could not be
reconciled, it was kept unread because no model is named, it was kept unread
though one is, or the vault already held it.

The request carries a path and nothing else. Nothing about the file decides
what is done with it: its name, its extension and its contents are never
consulted to route it, because a document is routed by what a read declares it
to be and not by what its bytes look like from outside. Size is the one
property read before opening, and it is read to refuse rather than to route.

The documents capability also declares a ``cancel`` action, and it is served
here, against the job registry rather than against the file: a person stops a
job, not a document. Cancellation is honoured between steps and never inside
one, so a cancelled capture leaves the vault at a step that finished rather
than in the middle of one.

The three steps a capture declares are the three it actually reaches — the
file is checked, its bytes are opened, and the engine settles it. Naming a
fourth would move a bar past a place nothing happens.
"""

from __future__ import annotations

import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError
from .jobs import JobCancelled, JobRegistry
from .review_actions import UnreadableOutcome

# Why a capture was refused, in the machine's own words. An outcome refuses to
# be built without one, so each of these travels beside the sentence a person
# reads and says the same thing to whatever is counting.
NO_SUCH_FILE = "file_unavailable"
NOT_A_FILE = "not_a_regular_file"
TOO_LARGE = "file_over_size_limit"
UNREADABLE = "file_unreadable"
CANCELLED = "job_cancelled"
NO_SUCH_JOB = "job_unknown"
JOB_OVER = "job_already_settled"

# The steps one capture declares, in the order it reaches them. Each is a thing
# that happens: the file is checked against the limits, its bytes are opened,
# and the engine says what became of it. The channel reports these and no
# others, because a step nothing does is a bar moving for its own sake.
CHECKED = "checked"
OPENED = "opened"
SETTLED = "settled"
CAPTURE_STEPS = (CHECKED, OPENED, SETTLED)

# The steps a capture declares when a model is named. `read` is a step of its
# own because it is the one that takes time and the one that costs money: a
# person watching a bar move deserves to know which part of it is the part
# they are paying for.
READ = "read"
READING_STEPS = (CHECKED, OPENED, READ, SETTLED)


class DocumentActions:
    """Adapt one already-open vault into the allowlisted document handlers."""

    def __init__(self, vault: Any, jobs: JobRegistry | None = None) -> None:
        self._vault = vault
        self._jobs = jobs if jobs is not None else JobRegistry()

    def upload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Capture one file into the vault, and read nothing.

        The reply carries the identity the sidecar minted for the work. It is
        the sidecar's because a caller cannot mint one nothing else can
        collide with, and it travels outward because a second frame — the
        cancel — has to be able to name this job and no other.

        The capture is finished by the time this answers on the transport as
        it stands, which is a fact about the transport rather than about this
        handler: the identity is what a channel able to deliver a frame
        mid-job would use, and the checkpoints below are where it would land.
        """
        from viva.engine import upload
        from viva.ingest.reader import build_reader, live_reading_configured

        from viva.persona import moment

        path = _upload_request(payload)
        # One question, asked once, deciding both what the job declares it will
        # do and what actually happens. Two answers to it would be a bar that
        # promises a step nothing runs, or one that runs a step nobody was
        # shown.
        read_fn, reading = build_reader()
        job = self._jobs.open("viva.documents.upload",
                              READING_STEPS if reading else CAPTURE_STEPS)
        try:
            with job:
                job.checkpoint()
                refusal = _refusal(path)
                if refusal is not None:
                    job.fail(refusal.reason or "")
                    return _with_job(refusal, job.job_id)
                job.reached(CHECKED)
                job.checkpoint()
                try:
                    data = path.read_bytes()
                except OSError:
                    unreadable = _refused(UNREADABLE, "documents_cannot_open")
                    job.fail(UNREADABLE)
                    return _with_job(unreadable, job.job_id)
                job.reached(OPENED)
                job.checkpoint()
                result = upload(self._vault, path.name, data, read_fn)
                if reading:
                    job.reached(READ)
                job.reached(SETTLED)
                return _with_job(_outcome(result, live_reading_configured()),
                                 job.job_id)
        except JobCancelled:
            # A person stopped this. It is an ordinary reply rather than a
            # failure, and the sentence says what the vault holds now — which
            # is whatever the last finished step left, and never a guess at
            # what the step that did not run would have done.
            return _with_job(
                ActionOutcome("refused", moment("jobs_stopped_capture"),
                              reason=CANCELLED),
                job.job_id)

    def cancel(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Ask one job to stop, and say what asking reached.

        Three answers, and each is a different fact. A job the registry does
        not hold is refused, because a cancel that quietly succeeds against an
        identity nothing minted tells a person their work stopped when nothing
        was ever asked. A job already over is refused too, and says which of
        the two it is. Only a job the ask actually moved comes back completed.
        """
        from viva.persona import moment

        job_id = _cancel_request(payload)
        try:
            before = self._jobs.record(job_id)
        except KeyError:
            return _refused(NO_SUCH_JOB, "jobs_unknown").as_dict()
        from .jobs import TERMINAL
        if before.state in TERMINAL:
            return ActionOutcome("refused", moment("jobs_already_settled"),
                                 reason=JOB_OVER,
                                 state={"job": before.as_dict()}).as_dict()
        record = self._jobs.cancel(job_id)
        return ActionOutcome("completed", moment("jobs_stopped"),
                             state={"job": record.as_dict()}).as_dict()


def _with_job(outcome: ActionOutcome, job_id: str) -> dict[str, Any]:
    """The outcome, carrying the identity of the job that produced it.

    The identity goes beside the sentence rather than into it: a person reads
    the sentence and a cancel names the identity, and a sentence a caller has
    to parse to find one is a contract nobody wrote down."""
    state = dict(outcome.state or {})
    state["job_id"] = job_id
    return ActionOutcome(outcome.kind, outcome.message, state=state,
                         reason=outcome.reason).as_dict()


def _cancel_request(payload: Mapping[str, Any]) -> str:
    allowed = {"job_id"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            "viva.documents.cancel does not accept fields: "
            + ", ".join(sorted(unexpected)))
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise BridgeRequestError("job_id must be a non-empty string")
    return job_id


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
    from viva.ingest.pipeline import (AWAITING, CONFLICT, DUPLICATE, GAP,
                                      IDENTITY, PARKED, POSTED)
    from viva.persona import moment

    # Each action the engine can declare, against the sentence for that action
    # and no other. A reading that did not post is four different facts, and a
    # table is how they stay four rather than collapsing into the nearest one
    # the day somebody adds a branch.
    said = {POSTED: "documents_posted", CONFLICT: "documents_held",
            GAP: "documents_gap", IDENTITY: "documents_identity",
            AWAITING: "documents_awaiting"}
    action = result.get("action")
    if action in said:
        terminal = "posted" if action == POSTED else "held"
        return ActionOutcome("completed", moment(said[action]),
                             state={"terminal_state": terminal,
                                    "ingest_action": action})
    if action == PARKED:
        reading = str(result.get("reading") or "")
        terminal = ("read_yielded_nothing"
                    if reading == "read_yielded_nothing"
                    or (not reading and reading_configured)
                    else "captured_only")
        message_key = ("documents_read_yielded_nothing"
                       if terminal == "read_yielded_nothing"
                       else "documents_saved_unread" if reading_configured
                       else "documents_saved_no_reader")
        return ActionOutcome("completed", moment(message_key),
            state={"terminal_state": terminal, "ingest_action": action,
                   "reading": reading or ("never_read" if not reading_configured
                                           else "read_yielded_nothing")})
    if action == DUPLICATE:
        return ActionOutcome("completed", moment("documents_already_held"),
                             state={"terminal_state": "duplicate",
                                    "ingest_action": action})
    raise UnreadableOutcome(moment("documents_outcome_unstated"))
