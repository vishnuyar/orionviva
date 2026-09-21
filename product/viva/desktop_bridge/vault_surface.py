"""Concrete read-only surface provider for an opened product vault."""

from __future__ import annotations

import datetime
import secrets
from collections.abc import Mapping
from typing import Any

from viva.questions import ACTIONABLE_QUESTION_WINDOW

from ..env import locale_from_env
from ..ingest.reader import live_reading_configured
from ..surface.documents import documents
from ..surface.overview import overview
from ..vault import Vault
from .handlers import BridgeRequestError
from ..startup_diagnostics import span

MAX_RAW_PRESENCE = 10_000


class OpenedVaultSurfaceProvider:
    """Expose reviewed read models from one already-open :class:`Vault`.

    Writes, unlock/open lifecycle, and model work remain outside this read-only
    provider.
    """

    _SURFACES = frozenset(("overview", "spending", "documents", "conversation", "review", "jobs", "trust",
                           "activity", "account_ledger", "plans"))
    _READS = _SURFACES | {"overview_accounts"}

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
        if surface not in self._READS:
            raise BridgeRequestError(f"unsupported surface: {surface!r}")
        params = _parameters(surface, parameters)
        if surface == "overview":
            return self._overview(params)
        if surface == "overview_accounts":
            return self._overview_accounts(params)
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

        self._vault.poll_read_store_worker()
        store = self._vault.read_store
        if (store is None or self._vault.read_store_lifecycle
                not in {"equal", "rebuilt", "caught_up"}):
            raise BridgeRequestError("current read store is not caught up")
        try:
            locale = locale_from_env()
            with store.open_reader() as revision:
                return review(
                    revision.review_projection(locale=locale), locale,
                    limit=parameters.get("limit", DEFAULT_LIMIT),
                    as_of=parameters.get("as_of", ""),
                    jurisdiction=parameters.get("jurisdiction", ""))
        except Exception:
            raise BridgeRequestError("current read store could not answer review") from None

    def _plans(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        from ..surface.plans import plans

        self._vault.poll_read_store_worker()
        store = self._vault.read_store
        if (store is None or self._vault.read_store_lifecycle
                not in {"equal", "rebuilt", "caught_up"}):
            raise BridgeRequestError("current read store is not caught up")
        try:
            with store.open_reader() as revision:
                return plans(revision.plans_projection(), locale_from_env(),
                             parameters.get("read_on") or _now())
        except Exception:
            raise BridgeRequestError("current read store could not answer plans") from None

    def _overview(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Compose current or value-time Overview from one held SQL revision."""
        as_of = parameters.get("as_of", "")
        read_on = parameters.get("read_on") or _now()
        locale = locale_from_env()
        self._vault.poll_read_store_worker()
        store = self._vault.read_store
        if (store is None or self._vault.read_store_lifecycle
                not in {"equal", "rebuilt", "caught_up"}):
            raise BridgeRequestError("current read store is not caught up")
        try:
            with store.open_reader() as revision:
                projection = (revision.historical_overview_projection(
                    as_of=as_of, today=read_on) if as_of
                    else revision.overview_projection(today=read_on))
                return overview(projection, locale, read_on)
        except Exception:
            raise BridgeRequestError(
                "current read store could not answer Overview") from None

    def _overview_accounts(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Return Overview and Accounts from one immutable SQL revision."""
        self._vault.poll_read_store_worker(retry_stale=parameters.get("refresh") != 1)
        if parameters.get("refresh") == 1:
            self._vault.synchronize_read_store()
        read_on = parameters.get("read_on") or _now()
        store = self._vault.read_store
        lifecycle = self._vault.read_store_lifecycle
        if store is None:
            return {"state": "degraded", "freshness": "unavailable",
                    "lifecycle": lifecycle, "revision": "", "overview": None,
                    "accounts": None, "error": "read_store_unavailable"}
        try:
            with store.open_reader() as revision:
                payload = overview(revision.overview_projection(today=read_on),
                                   locale_from_env(), read_on)
                usable = lifecycle not in {"degraded", "unavailable", "rebuilding"}
                current = usable and lifecycle not in {"stale", "rebuilding"}
                return {
                    "state": "ready" if current else "stale" if usable else "degraded",
                    "freshness": "current" if current else "stale" if usable else "unavailable",
                    "lifecycle": lifecycle, "revision": revision.generation,
                    "overview": payload if usable else None,
                    "accounts": payload if usable else None,
                    "error": "" if current else "read_store_stale" if usable else "read_store_unavailable",
                }
        except Exception:
            return {"state": "degraded", "freshness": "unavailable",
                    "lifecycle": "degraded", "revision": "", "overview": None,
                    "accounts": None, "error": "read_store_unavailable"}

    def _spending(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Compose one filterable chart without placing its arithmetic in UI."""
        from ..surface.spending import (SpendingBreakdownRequestError,
                                        spending_breakdown)

        self._vault.poll_read_store_worker()
        store = self._vault.read_store
        if (store is None or self._vault.read_store_lifecycle
                not in {"equal", "rebuilt", "caught_up"}):
            raise BridgeRequestError("current read store is not caught up")
        try:
            read_on = parameters.get("read_on") or _now()
            locale = locale_from_env()
            with store.open_reader() as revision:
                return spending_breakdown(
                    revision.spending_projection(today=read_on, locale=locale),
                    locale, read_on,
                    period=parameters.get("period", "latest_complete_month"),
                    granularity=parameters.get("granularity", "category"),
                    currency=parameters.get("currency", ""),
                    account_id=parameters.get("account_id", ""),
                    start_date=parameters.get("start_date", ""),
                    end_date=parameters.get("end_date", ""))
        except SpendingBreakdownRequestError as exc:
            raise BridgeRequestError(str(exc)) from None
        except Exception:
            raise BridgeRequestError("current read store could not answer spending") from None

    def _documents(self) -> dict[str, Any]:
        """Compose current Documents from SQL and explicit raw presence."""
        self._vault.poll_read_store_worker()
        store = self._vault.read_store
        if (store is None or self._vault.read_store_lifecycle
                not in {"equal", "rebuilt", "caught_up"}):
            raise BridgeRequestError("current read store is not caught up")
        try:
            with span("raw_store"):
                raw_ids = frozenset(self._vault.raw.doc_ids(
                    max_count=MAX_RAW_PRESENCE))
        except ValueError:
            raise BridgeRequestError("raw document presence exceeds its row bound") from None
        try:
            with store.open_reader() as revision:
                return documents(revision.documents_projection(), raw_ids,
                                 live_reading_configured(), locale_from_env())
        except Exception:
            raise BridgeRequestError(
                "current read store could not answer documents") from None

    def _activity(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Open the projection and hand it to the surface that composes it.

        Which way each movement went, what it is where it is not plain
        spending, and how it is written are all decided in the surface. What is
        decided here is only the horizon the projection is cut at, because this
        side of the boundary is where a caller's `as_of` is read."""
        from ..surface.activity import activity

        from ..surface.activity import DEFAULT_LIMIT
        as_of = parameters.get("as_of", "")
        self._vault.poll_read_store_worker()
        store = self._vault.read_store
        if (store is None or self._vault.read_store_lifecycle
                not in {"equal", "rebuilt", "caught_up"}):
            raise BridgeRequestError("current read store is not caught up")
        try:
            with store.open_reader() as revision:
                return activity(
                    (revision.historical_activity_projection(as_of=as_of)
                     if as_of else revision.activity_projection()),
                    locale_from_env(),
                    parameters.get("limit", DEFAULT_LIMIT),
                    parameters.get("focus", ""))
        except Exception:
            raise BridgeRequestError("current read store could not answer activity") from None

    def _account_ledger(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Read an indexed account page from one current SQL generation."""
        from ..surface.account_ledger import (
            DEFAULT_LIMIT, AccountLedgerCursorError,
            AccountLedgerIdentityError, sql_account_ledger_page)

        self._vault.poll_read_store_worker()
        store = self._vault.read_store
        if (store is None or self._vault.read_store_lifecycle
                not in {"equal", "rebuilt", "caught_up"}):
            raise BridgeRequestError("current read store is not caught up")
        try:
            with store.open_reader() as revision:
                parts = revision.account_ledger_page(
                    parameters["account_id"], locale=locale_from_env(),
                    cursor_secret=self._cursor_secret,
                    limit=parameters.get("limit", DEFAULT_LIMIT),
                    cursor=parameters.get("cursor", ""))
                return sql_account_ledger_page(parts)
        except (AccountLedgerCursorError, AccountLedgerIdentityError) as exc:
            raise BridgeRequestError(str(exc)) from None
        except Exception:
            raise BridgeRequestError(
                "current read store could not answer account ledger") from None

    def _trust(self) -> dict[str, Any]:
        """Return outbound model activity and explicit trust absences."""
        from ..surface.outbound import outbound
        from ..read_store.trust import outbound_events, has_agent_actions
        from ..persona import moment
        self._vault.poll_read_store_worker()
        store = self._vault.read_store
        if (store is None or self._vault.read_store_lifecycle
                not in {"equal", "rebuilt", "caught_up"}):
            raise BridgeRequestError("current read store is not caught up")
        try:
            with store.open_reader() as revision:
                return {
                    "state": "ready",
                    "outbound": outbound(outbound_events(revision), locale_from_env()),
                    "absences": [
                        {"id": "anchoring", "sentence": moment("trust_no_anchoring")},
                    ] + ([{"id": "maintenance",
                           "sentence": moment("trust_no_maintenance_yet")}]
                         if not has_agent_actions(revision) else []),
                    "notes": [],
                }
        except Exception:
            raise BridgeRequestError("current read store could not answer Trust") from None

    def _job_registry(self) -> dict[str, Any]:
        """Read bounded receipts; financial reconciliation happens on explicit recovery."""
        if self._jobs is None:
            return {"state": "absent", "jobs": [], "running": []}
        from .document_actions import document_recovery
        result = self._jobs.read()
        records = {record.job_id: record for record in self._jobs.records()}
        newest = {record.document_id: record.job_id for record in records.values()
                  if record.document_id}
        for row in result["jobs"]:
            record = records.get(row["job_id"])
            if record is None:
                continue
            if record.document_id and newest.get(record.document_id) != record.job_id:
                continue
            recovery = document_recovery(self._vault, record, inspect_ledger=False)
            if recovery is not None:
                row["recovery"] = recovery
        return result

    def _conversation(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        from ..surface.conversation import timeline
        from ..surface.review import question_review_binding
        self._vault.poll_read_store_worker()
        store = self._vault.read_store
        if (store is None or self._vault.read_store_lifecycle
                not in {"equal", "rebuilt", "caught_up"}):
            raise BridgeRequestError("current read store is not caught up")
        try:
            locale = parameters.get("locale", "") or locale_from_env()
            with store.open_reader() as revision:
                projection = revision.conversation_projection(locale=locale)
                queue = revision.open_questions(
                    limit=parameters.get("limit", ACTIONABLE_QUESTION_WINDOW),
                    as_of=parameters.get("as_of", "") or _now(),
                    jurisdiction=parameters.get("jurisdiction", ""), locale=locale,
                    held_as_of="9999-12-31")
                queue = {**queue, "questions": [{
                    **question, "review_binding": question_review_binding(
                        projection, question, locale),
                } for question in queue.get("questions", [])]}
                return timeline(projection, queue)
        except Exception:
            raise BridgeRequestError("current read store could not answer conversation") from None


def _now() -> str:
    """Today, as the one place this side of the boundary reads a clock."""
    return datetime.date.today().isoformat()


def _parameters(surface: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    # `as_of` is the horizon a projection is cut at; `read_on` is the day a
    # picture is read on. Two names one letter apart meaning two things is how
    # a later change gets one of them wrong, so they are not spelled alike.
    allowed_by_surface = {
        "overview": {"as_of", "read_on"},
        "overview_accounts": {"read_on", "refresh"},
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
        if surface == "activity":
            from ..read_store.overview import MAX_ACTIVITY_PAGE
            if limit > MAX_ACTIVITY_PAGE:
                raise BridgeRequestError(
                    f"activity limit must be at most {MAX_ACTIVITY_PAGE}")
    if "refresh" in result and result["refresh"] != 1:
        raise BridgeRequestError("refresh must be 1")
    if "focus" in result and (not isinstance(result["focus"], str)
                              or not result["focus"].strip()):
        raise BridgeRequestError("focus must be a non-empty movement identity")
    if surface == "account_ledger":
        account_id = result.get("account_id")
        if not isinstance(account_id, str) or not account_id.strip():
            raise BridgeRequestError("account_id must be a non-empty account identity")
    return result
