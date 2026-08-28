"""Explicit actions over the obligations and quiet-findings surface."""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping
from typing import Any

from ..ledger.events import finding_set_aside
from ..persona import moment
from ..surface.models import ActionOutcome
from .handlers import BridgeRequestError


class ObligationActions:
    """Set aside one live finding at the stake the backend currently reads."""

    def __init__(self, vault, today: Callable[[], str] | None = None) -> None:
        self._vault = vault
        self._today = today or (lambda: datetime.date.today().isoformat())

    def set_aside(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        finding_id = _request(payload)
        today = self._today()
        projection = self._vault.ledger.projection()
        current = next((finding for finding in projection.findings(today)
                        if finding.id == finding_id), None)
        if current is None:
            return ActionOutcome(
                "stale", moment("finding_stale"),
                state={"finding_id": finding_id}).as_dict()
        self._vault.ledger.append(finding_set_aside(
            current.id, current.kind, current.stake, today))
        return ActionOutcome(
            "set_aside", moment("finding_set_aside"),
            state={"finding_id": current.id}).as_dict()


def _request(payload: Mapping[str, Any]) -> str:
    allowed = {"finding_id"}
    if set(payload) != allowed:
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise BridgeRequestError(
                "viva.overview.set_aside_finding does not accept fields: "
                + ", ".join(unexpected))
        raise BridgeRequestError("finding_id is required")
    finding_id = payload.get("finding_id")
    if not isinstance(finding_id, str) or not finding_id.strip():
        raise BridgeRequestError("finding_id must be a non-empty string")
    return finding_id


__all__ = ["ObligationActions"]
