"""Concrete read-only surface provider for an opened product vault."""

from __future__ import annotations

import datetime
import secrets
from collections.abc import Mapping
from typing import Any

from viva.questions import ACTIONABLE_QUESTION_WINDOW, open_questions

from ..env import locale_from_env
from ..ingest.reader import live_reading_configured
from ..surface.documents import documents
from ..surface.overview import overview
from ..vault import Vault
from .handlers import BridgeRequestError


class OpenedVaultSurfaceProvider:
    """Expose reviewed read models from one already-open :class:`Vault`.

    This is deliberately read-only. Writes, unlock/open lifecycle, and model
    work remain outside the surface provider and must get separate reviewed
    bridge operations.
    """

    _SURFACES = frozenset(("overview", "spending", "documents", "conversation", "review", "jobs", "trust",
                           "activity", "account_ledger", "plans"))

    def __init__(self, vault: Vault, jobs: Any = None, *,
                 cursor_secret: bytes | None = None) -> None:
        self._vault = vault
        self._jobs = jobs
        # Cursors live only for this opened-provider session. Their contents
        # can be inspected for diagnostics, but cannot be altered into another
        # account, revision or anchor without this private key.
        self._cursor_secret = (secrets.token_bytes(32)
                               if cursor_secret is None else cursor_secret)
        if not isinstance(self._cursor_secret, bytes) \
                or len(self._cursor_secret) < 32:
            raise ValueError("cursor_secret must be at least 32 bytes")

    def read_surface(
        self, surface: str, parameters: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if surface not in self._SURFACES:
            raise BridgeRequestError(f"unsupported surface: {surface!r}")
        params = _parameters(surface, parameters)
        if surface == "overview":
            return self._overview(params)
        if surface == "spending":
            return self._spending(params)
        if surface == "documents":
            return self._documents()
        if surface == "jobs":
            return self._job_registry()
        if surface == "trust":
            return self._trust()
        if surface == "activity":
            return self._activity(params)
        if surface == "account_ledger":
            return self._account_ledger(params)
        if surface == "plans":
            return self._plans(params)
        if surface == "review":
            return self._review(params)
        return self._conversation(params)

    def _review(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        from ..surface.review import DEFAULT_LIMIT, review

        projection = self._vault.ledger.projection()
        return review(
            projection, locale_from_env(),
            limit=parameters.get("limit", DEFAULT_LIMIT),
            as_of=parameters.get("as_of", ""),
            jurisdiction=parameters.get("jurisdiction", ""))

    def _plans(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        from ..surface.plans import plans

        projection = self._vault.ledger.fresh_projection()
        return plans(projection, locale_from_env(),
                     parameters.get("read_on") or _now())

    def _overview(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Open the projection and hand it to the surface that composes it.

        Which accounts are shown, what each is worth, how well it is stood
        behind and what its figure covers are all decided in the surface, over
        the same read a conversation makes. Nothing about them is decided
        here.

        What is decided here is the day the picture is read on, because the
        surface holds no clock and this side of the boundary does. A caller may
        state the day, which is how a generated artifact stays the same bytes
        whenever it is run; with none stated it is the day it is asked on."""
        projection = self._vault.ledger.projection_as_of(parameters.get("as_of"))
        return overview(projection, locale_from_env(),
                        parameters.get("read_on") or _now())

    def _spending(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Compose one filterable chart without placing its arithmetic in UI."""
        from ..surface.spending import (SpendingBreakdownRequestError,
                                        spending_breakdown)

        projection = self._vault.ledger.projection()
        try:
            return spending_breakdown(
                projection, locale_from_env(),
                parameters.get("read_on") or _now(),
                period=parameters.get("period", "latest_complete_month"),
                granularity=parameters.get("granularity", "category"),
                currency=parameters.get("currency", ""),
                account_id=parameters.get("account_id", ""),
                start_date=parameters.get("start_date", ""),
                end_date=parameters.get("end_date", ""))
        except SpendingBreakdownRequestError as exc:
            raise BridgeRequestError(str(exc)) from None

    def _documents(self) -> dict[str, Any]:
        """Open the projection and the blob store, and hand both to the surface
        that composes them.

        Which documents are listed, what each is called, how far its reading
        got and what the panel says about reading are all decided in the
        surface. What is decided here is only what the surface cannot see for
        itself: which originals the vault still holds, and whether this machine
        names a reader at all."""
        return documents(self._vault.ledger.projection(),
                         frozenset(self._vault.raw.doc_ids()),
                         live_reading_configured(),
                         locale_from_env())

    def _activity(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Open the projection and hand it to the surface that composes it.

        Which way each movement went, what it is where it is not plain
        spending, and how it is written are all decided in the surface. What is
        decided here is only the horizon the projection is cut at, because this
        side of the boundary is where a caller's `as_of` is read."""
        from ..surface.activity import activity

        projection = self._vault.ledger.projection_as_of(parameters.get("as_of"))
        from ..surface.activity import DEFAULT_LIMIT
        return activity(projection, locale_from_env(),
                        parameters.get("limit", DEFAULT_LIMIT),
                        parameters.get("focus", ""))

    def _account_ledger(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Read one exact account from one event-prefix snapshot.

        The projection and revision are built from the same immutable tuple.
        A later page therefore either names that same tuple or is refused as
        stale; it can never continue by offset into a changed live projection.
        """
        from ..surface.account_ledger import (
            DEFAULT_LIMIT, AccountLedgerCursorError,
            AccountLedgerIdentityError, account_ledger, snapshot_revision)

        projection, events = self._vault.ledger.snapshot_projection()
        try:
            return account_ledger(
                projection, parameters["account_id"], locale_from_env(),
                snapshot_revision(events),
                cursor_secret=self._cursor_secret,
                limit=parameters.get("limit", DEFAULT_LIMIT),
                cursor=parameters.get("cursor", ""))
        except (AccountLedgerCursorError, AccountLedgerIdentityError) as exc:
            # These are safe contract refusals. They intentionally do not echo
            # an account path or movement identity from the vault.
            raise BridgeRequestError(str(exc)) from None

    def _trust(self) -> dict[str, Any]:
        """What this vault has sent, and what nothing here can establish.

        The event stream is handed to the surface that folds it, rather than a
        projection: a model call is recorded once and read once, and putting it
        through a projection would be a second opinion about a fact the log
        already states plainly.

        The absences travel inside the read for the same reason every other
        sentence does — a screen that composes its own caveats writes them out
        of date the day the capability lands, and nothing goes red when it
        does."""
        from ..surface.outbound import outbound

        from ..persona import moment

        events = list(self._vault.events())
        return {
            "state": "ready",
            "outbound": outbound(events, locale_from_env()),
            # What nothing on this machine can establish, said in the plainest
            # sentences the pack holds. An absent capability described in soft
            # words reads as a capability, and the difference is whether a
            # person checks a claim or takes it.
            "absences": [
                {"id": "anchoring", "sentence": moment("trust_no_anchoring")},
            ] + ([{"id": "maintenance",
                   "sentence": moment("trust_no_maintenance_yet")}]
                 if not self._vault.ledger.projection().agent_log() else []),
            # Trust's notes are owed by their own cycle. An empty list says
            # this build supplies none rather than that the vault has nothing
            # to say, and the panel's own state says which.
            "notes": [],
        }

    def _job_registry(self) -> dict[str, Any]:
        """Read bounded operational job receipts without opening a projection."""
        if self._jobs is None:
            return {"state": "absent", "jobs": [], "running": []}
        return self._jobs.read()

    def _conversation(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        from ..surface.conversation import timeline
        from ..surface.review import question_review_binding

        projection = self._vault.ledger.projection()
        queue = open_questions(
            projection,
            limit=parameters.get("limit", ACTIONABLE_QUESTION_WINDOW),
            as_of=parameters.get("as_of", ""),
            jurisdiction=parameters.get("jurisdiction", ""),
            locale=parameters.get("locale", ""),
        )
        locale = parameters.get("locale", "")
        queue = {
            **queue,
            "questions": [{
                **question,
                "review_binding": question_review_binding(
                    projection, question, locale),
            } for question in queue.get("questions", [])],
        }
        return timeline(projection, queue)


def _now() -> str:
    """Today, as the one place this side of the boundary reads a clock."""
    return datetime.date.today().isoformat()


def _parameters(surface: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    # `as_of` is the horizon a projection is cut at; `read_on` is the day a
    # picture is read on. Two names one letter apart meaning two things is how
    # a later change gets one of them wrong, so they are not spelled alike.
    allowed_by_surface = {
        "overview": {"as_of", "read_on"},
        "spending": {"period", "granularity", "currency", "account_id",
                     "start_date", "end_date", "read_on"},
        "documents": set(),
        "jobs": set(),
        "trust": set(),
        "activity": {"as_of", "limit", "focus"},
        "account_ledger": {"account_id", "cursor", "limit"},
        "plans": {"read_on"},
        "review": {"as_of", "limit", "jurisdiction"},
        "conversation": {"as_of", "limit", "jurisdiction", "locale"},
    }
    allowed = allowed_by_surface[surface]
    unexpected = set(parameters) - allowed
    if unexpected:
        raise BridgeRequestError(
            "surface parameters do not accept fields: "
            + ", ".join(sorted(unexpected))
        )
    result = dict(parameters)
    for name in ("as_of", "jurisdiction", "locale", "read_on", "cursor",
                 "period", "granularity", "currency", "account_id",
                 "start_date", "end_date"):
        value = result.get(name, "")
        if not isinstance(value, str):
            raise BridgeRequestError(f"{name} must be a string")
    if "limit" in result:
        limit = result["limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise BridgeRequestError("limit must be a positive integer")
        if surface == "account_ledger":
            from ..surface.account_ledger import MAX_LIMIT
            if limit > MAX_LIMIT:
                raise BridgeRequestError(
                    f"account ledger limit must be at most {MAX_LIMIT}")
        if surface == "review":
            from ..surface.review import MAX_LIMIT
            if limit > MAX_LIMIT:
                raise BridgeRequestError(
                    f"review limit must be at most {MAX_LIMIT}")
    if "focus" in result and (not isinstance(result["focus"], str)
                              or not result["focus"].strip()):
        raise BridgeRequestError("focus must be a non-empty movement identity")
    if surface == "account_ledger":
        account_id = result.get("account_id")
        if not isinstance(account_id, str) or not account_id.strip():
            raise BridgeRequestError("account_id must be a non-empty account identity")
    return result
