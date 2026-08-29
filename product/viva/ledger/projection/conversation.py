"""Durable conversation turns and unapplied correction proposals."""

from __future__ import annotations

import copy


def conversation_turns(core) -> list[dict]:
    """Every product-facing turn in append order, detached from live state."""
    return copy.deepcopy(core._conversation_turns)


def conversation_proposals(core, *, open_only: bool = False) -> list[dict]:
    """Persisted proposals in the order they were opened."""
    rows = list(core._conversation_proposals.values())
    if open_only:
        rows = [row for row in rows if row.get("status") == "open"]
    return copy.deepcopy(rows)


def conversation_proposal(core, proposal_id: str) -> dict | None:
    """One persisted proposal, or nothing when the identity was never opened."""
    found = core._conversation_proposals.get(proposal_id)
    return copy.deepcopy(found) if found is not None else None
