"""Concrete read-only surface provider for an opened product vault."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any

from viva.questions import open_questions

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

    _SURFACES = frozenset(("overview", "documents", "review", "jobs"))

    def __init__(self, vault: Vault, jobs: Any = None) -> None:
        self._vault = vault
        self._jobs = jobs

    def read_surface(
        self, surface: str, parameters: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if surface not in self._SURFACES:
            raise BridgeRequestError(f"unsupported surface: {surface!r}")
        params = _parameters(parameters)
        if surface == "overview":
            return self._overview(params)
        if surface == "documents":
            return self._documents()
        if surface == "jobs":
            return self._job_registry()
        return self._review(params)

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
                         live_reading_configured())

    def _job_registry(self) -> dict[str, Any]:
        """What the sidecar is doing, or has just done, for this vault.

        The one read here that opens no projection: a job is work this process
        is doing and is not a thing the ledger records, so nothing about it
        survives the sidecar. A build with no registry answers absent rather
        than with an empty list — there is a difference between a sidecar that
        has run no job and one that cannot say."""
        if self._jobs is None:
            return {"state": "absent", "jobs": [], "running": []}
        return self._jobs.read()

    def _review(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        projection = self._vault.ledger.projection()
        queue = open_questions(
            projection,
            limit=parameters.get("limit", 10),
            as_of=parameters.get("as_of", ""),
            jurisdiction=parameters.get("jurisdiction", ""),
            locale=parameters.get("locale", ""),
        )
        return {"state": "ready", **queue}


def _now() -> str:
    """Today, as the one place this side of the boundary reads a clock."""
    return datetime.date.today().isoformat()


def _parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    # `as_of` is the horizon a projection is cut at; `read_on` is the day a
    # picture is read on. Two names one letter apart meaning two things is how
    # a later change gets one of them wrong, so they are not spelled alike.
    allowed = {"as_of", "limit", "jurisdiction", "locale", "read_on"}
    unexpected = set(parameters) - allowed
    if unexpected:
        raise BridgeRequestError(
            "surface parameters do not accept fields: "
            + ", ".join(sorted(unexpected))
        )
    result = dict(parameters)
    for name in ("as_of", "jurisdiction", "locale", "read_on"):
        value = result.get(name, "")
        if not isinstance(value, str):
            raise BridgeRequestError(f"{name} must be a string")
    limit = result.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise BridgeRequestError("limit must be a positive integer")
    result["limit"] = limit
    return result
