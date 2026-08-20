"""The ingest read-model: what is captured, what posted, what held."""

from __future__ import annotations

from .core import ProjectionCore


def is_resolved(core: ProjectionCore, doc_id: str) -> bool:
    """A document has reached a terminal state — posted, or held for review."""
    return doc_id in core._posted or doc_id in core._held


def posted_period(core: ProjectionCore, account: str,
                  period_end: str) -> tuple | None:
    """The document already posted for this account and period end, as
    ``(doc_id, closing_amount)`` — or None if the period is unclaimed."""
    return core._periods.get((account, period_end))


def is_pay_decomposed(core: ProjectionCore, description: str, pay_date: str,
                      gross: str) -> bool:
    """Whether this pay has already been broken out of its deposit."""
    return (description, pay_date, gross) in core._decomposed


def posted_doc_ids(core: ProjectionCore) -> set[str]:
    return set(core._posted)


def captured_docs(core: ProjectionCore) -> dict[str, str]:
    return dict(core._captured)


def open_holds(core: ProjectionCore) -> list[dict]:
    """StatementHeld bodies for documents not since posted."""
    return [b for did, b in core._held.items() if did not in core._posted]


def gap_holds(core: ProjectionCore) -> list[dict]:
    return [b for b in open_holds(core) if b.get("reason") == "gap"]
