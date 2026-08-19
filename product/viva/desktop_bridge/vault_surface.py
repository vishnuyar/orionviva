"""Concrete read-only surface provider for an opened product vault."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from viva.questions import open_questions

from ..env import locale_from_env
from ..ingest.review import held_items, other_holds
from ..surface.overview import overview
from ..vault import Vault
from .handlers import BridgeRequestError


class OpenedVaultSurfaceProvider:
    """Expose reviewed read models from one already-open :class:`Vault`.

    This is deliberately read-only. Writes, unlock/open lifecycle, and model
    work remain outside the surface provider and must get separate reviewed
    bridge operations.
    """

    _SURFACES = frozenset(("overview", "documents", "review"))

    def __init__(self, vault: Vault) -> None:
        self._vault = vault

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
        return self._review(params)

    def _overview(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Open the projection and hand it to the surface that composes it.

        Which accounts are shown, what each is worth, how well it is stood
        behind and what its figure covers are all decided in the surface, over
        the same read a conversation makes. Nothing about them is decided
        here."""
        projection = self._vault.ledger.projection_as_of(parameters.get("as_of"))
        return overview(projection, locale_from_env())

    def _documents(self) -> dict[str, Any]:
        projection = self._vault.ledger.projection()
        holds = [item.to_dict() for item in held_items(projection)]
        holds.extend(other_holds(projection))
        captured = projection.captured_docs()
        return {
            "state": "ready",
            "documents": [
                {
                    "id": doc_id,
                    "doc_type": doc_type,
                    "resolved": projection.is_resolved(doc_id),
                    "raw_available": self._vault.raw.has(doc_id),
                }
                for doc_id, doc_type in sorted(captured.items())
            ],
            "holds": holds,
            "raw_document_count": len(self._vault.raw.doc_ids()),
        }

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


def _parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"as_of", "limit", "jurisdiction", "locale"}
    unexpected = set(parameters) - allowed
    if unexpected:
        raise BridgeRequestError(
            "surface parameters do not accept fields: "
            + ", ".join(sorted(unexpected))
        )
    result = dict(parameters)
    for name in ("as_of", "jurisdiction", "locale"):
        value = result.get(name, "")
        if not isinstance(value, str):
            raise BridgeRequestError(f"{name} must be a string")
    limit = result.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise BridgeRequestError("limit must be a positive integer")
    result["limit"] = limit
    return result
