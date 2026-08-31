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


def captured_filenames(core: ProjectionCore) -> dict[str, str]:
    """What each captured document was called where it came from.

    Empty for a document captured without a name — the capture records what it
    was given, and a name nobody supplied is not invented here."""
    return dict(core._captured_names)


def read_attempted_docs(core: ProjectionCore) -> set[str]:
    """Every document some model was asked about, whatever it answered.

    Membership says a read happened, not that it worked: a reply that never
    parsed is still a reading, and it is what separates a document that was
    read and yielded nothing from one nothing has ever looked at."""
    return set(core._read_attempted)


def read_parsed_docs(core: ProjectionCore) -> set[str]:
    """Every document whose reading declared itself usable.

    Read off the reading's own ``parse_ok`` on the pass that produces facts,
    which is what the vault recorded about that reading. Whether the ledger
    then posted it, held it or had nowhere to put it is a separate fact and is
    asked for separately: a document can reach a terminal state without any
    reading behind it, and one can be read perfectly and reach none."""
    return set(core._read_parsed)


def open_holds(core: ProjectionCore) -> list[dict]:
    """StatementHeld bodies for documents not since posted."""
    return [b for did, b in core._held.items() if did not in core._posted]


def open_activity_holds(core: ProjectionCore) -> list[dict]:
    """Brokerage activity streams still quarantined after snapshot posting."""
    return list(core._activity_held.values())


def gap_holds(core: ProjectionCore) -> list[dict]:
    return [b for b in open_holds(core) if b.get("reason") == "gap"]


def document_contributions(core: ProjectionCore) -> dict[str, dict]:
    """What each posted document actually put on the books.

    One entry per document that attested a closing balance: the account it
    spoke about, the figure that was accepted for it, the day that figure is
    good for, and the currency the account is held in. It is what the ledger
    recorded and nothing else — no wording, no grade, no derived total.

    The accepted figure is the corrected one where a person ruled on a misread,
    which is the figure that is actually on the books rather than the one the
    document printed. A document that posted movements and attested no closing
    has no entry: this says what a document was worth to the picture, and a
    document with nothing here contributed nothing a figure rests on.
    """
    accounts = {}
    for account, state in core._acct.items():
        for doc_id in state.doc_ids:
            accounts.setdefault(doc_id, (account, state.currency))
    found: dict[str, dict] = {}
    for doc_id, (amount, as_of) in core._doc_closing.items():
        account, currency = accounts.get(doc_id, ("", ""))
        found[doc_id] = {"account": account, "currency": currency,
                         "amount": str(amount), "as_of": as_of}
    return found
