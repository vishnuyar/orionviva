"""The ingest read-model: what is captured, what posted, what held."""

from __future__ import annotations

from .core import ProjectionCore


def is_resolved(core: ProjectionCore, doc_id: str) -> bool:
    """A document has reached a terminal state — posted, or held for review."""
    return doc_id in core._posted or doc_id in core._held


def posted_doc_ids(core: ProjectionCore) -> set[str]:
    return set(core._posted)


def captured_docs(core: ProjectionCore) -> dict[str, str]:
    return dict(core._captured)


def open_holds(core: ProjectionCore) -> list[dict]:
    """StatementHeld bodies for documents not since posted."""
    return [b for did, b in core._held.items() if did not in core._posted]


def gap_holds(core: ProjectionCore) -> list[dict]:
    return [b for b in open_holds(core) if b.get("reason") == "gap"]


def attested_period(core: ProjectionCore, account: str) -> tuple[str, str]:
    """The period this account's statements attest, as `(from, to)`.

    A statement enters the ledger only by reconciling, and attaches only to a
    chain it continues — forward from the running balance or backward onto the
    earliest opening — so an account's posted statements are one unbroken
    stretch and its ends are the earliest opening date and the latest closing
    date. Empty when no statement has posted for the account: an account whose
    period is unknown says so rather than borrowing the dates of its
    movements."""
    st = core._acct.get(account)
    if st is None or not st.opening_date or not st.closing_date:
        return "", ""
    return st.opening_date, st.closing_date


def attested_periods(core: ProjectionCore) -> dict[str, tuple[str, str]]:
    """Every account's attested period, including the empty ones, so a caller
    can tell an account with no statement from an account it never asked
    about."""
    return {a: attested_period(core, a) for a in core._acct}
