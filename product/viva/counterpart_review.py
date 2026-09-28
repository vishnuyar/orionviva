"""Read-side routing for payments whose counterpart evidence is still owed."""
from __future__ import annotations


def route(implied: dict | None, *, linked: bool, nature_reason: str,
          transfer_review: bool) -> str:
    """Prefer settled facts, then live transfer review, then document evidence."""
    if linked or nature_reason in ("linked", "ruling"):
        return "settled"
    implied = implied or {}
    document = implied.get("documents")
    if (implied.get("major") == "liability"
            and implied.get("compound") is False
            and isinstance(document, str) and document.strip()):
        return "transfer" if transfer_review else "waiting"
    return "existing"


def live_candidates(source, candidates, movements, linked) -> list[str]:
    """Retain only unlinked current records that still pass the matcher gate."""
    from .ingest.transfers import is_transfer_candidate

    if source is None or source.key in linked:
        return []
    return [key for key in candidates
            if key not in linked and key in movements
            and is_transfer_candidate(source, movements[key])]
