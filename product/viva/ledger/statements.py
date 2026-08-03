"""What each account's statements say about themselves, and where they join.

A statement declares the period it covers. That declaration is already in the
vault — every document's reply is stored verbatim — but nothing read it, so
coverage was inferred from the dates of the movements a read happened to see.
Those are different facts: a quiet fortnight inside a reconciled month is not a
hole in the evidence.

This module recovers the declaration by running today's parser over the stored
reply, through the same dispatch the reader uses, and joins consecutive
statements into runs. Two statements join when the later one opens at the
balance the earlier one closed at AND opens on or immediately after the day it
closed. The balance test alone is what the ingest stitch uses, and a month whose
net change is zero passes it while leaving a gap; requiring the dates to meet is
what makes a missing statement visible instead of invisible.

Nothing here writes. The register is derived, so a re-read or a corrected
document changes it for free, and no event carries a period that could later
disagree with the document it came from.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class StatementRecord:
    """One statement, as the document declared itself."""
    doc_id: str
    account: str
    opening_date: str
    opening_amount: Decimal
    closing_date: str
    closing_amount: Decimal


@dataclass
class AccountStatements:
    """Every statement held for one account, and the periods they attest.

    `runs` holds one `(from, to)` per unbroken stretch, in order. Two runs mean
    a statement is missing between them, and the gap is the space between them:
    an account with runs is never described by their outer hull, because that
    hull is exactly the claim the missing statement cannot support."""
    account: str
    records: list = field(default_factory=list)
    runs: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)

    def covering(self, when: str) -> tuple[str, str] | None:
        """The run containing a date, or None when nothing attests it."""
        for start, end in self.runs:
            if start <= when <= end:
                return start, end
        return None

    def to_dict(self) -> dict:
        return {"account": self.account, "count": self.count,
                "runs": [{"from": a, "to": b} for a, b in self.runs],
                "statements": [
                    {"doc_id": r.doc_id, "from": r.opening_date,
                     "to": r.closing_date, "opening": str(r.opening_amount),
                     "closing": str(r.closing_amount)} for r in self.records]}


def register(core, locale: str = "") -> dict:
    """Every account's statements, derived once per fold and cached.

    Returns `{account: AccountStatements}`. An account whose documents declare
    no period is absent rather than present and empty: nothing is inferred for
    it, and a caller asking about it learns that nothing is held."""
    if core._statements is None:
        core._statements = _build(core, locale or _locale())
    return core._statements


def _locale() -> str:
    """The configured locale, or the default when it is unusable.

    A read answers or refuses; it never exits. The entry points validate the
    setting and say so loudly, which is where a bad value should be caught."""
    try:
        from ..env import locale_from_env
        return locale_from_env()
    except BaseException:
        return "en-US"


def _build(core, locale: str) -> dict:
    from ..ingest.registry import BALANCE_IDENTITY, profile_for
    from ..ingest.statement import from_model_json

    by_account: dict = {}
    for account, state in core._acct.items():
        records = []
        for doc_id in sorted(getattr(state, "doc_ids", ()) or ()):
            reply = core._replies.get(doc_id)
            if not reply:
                continue
            profile = profile_for(core._captured.get(doc_id, ""))
            # Only a document whose identity is the balance chain declares a
            # period this way. A holdings snapshot measures a moment and
            # attests nothing about the days around it.
            if profile is None or profile.identity != BALANCE_IDENTITY:
                continue
            facts, error = from_model_json(reply, doc_id, locale,
                                           state.currency or "USD")
            if error or facts is None:
                continue
            record = _record(doc_id, account, facts,
                             core._doc_closing.get(doc_id))
            if record is not None:
                records.append(record)
        records = [r for r in records if _within(r, core.as_of)]
        if records:
            records.sort(key=lambda r: (r.opening_date, r.closing_date))
            by_account[account] = AccountStatements(
                account=account, records=records, runs=_runs(records))
    return by_account


def _within(record: StatementRecord, as_of: str | None) -> bool:
    """Whether a statement's period is one an as-of read may speak for.

    A read as of a past date holds only the movements up to it, so attesting a
    period that runs past it would claim completeness for days it is
    deliberately not showing."""
    return not as_of or record.closing_date <= as_of[:10]


def _record(doc_id: str, account: str, facts,
            accepted: tuple | None) -> StatementRecord | None:
    """A record only when the document declared both ends of its period as real
    dates and both balances as numbers. A statement that did not say where it
    starts cannot say what it covers.

    `accepted` is what the ledger posted for this document's closing. It is
    authoritative over the reply, because a correction changes what posts and
    leaves the reply as it was read."""
    opening, closing = facts.opening_date[:10], facts.closing_date[:10]
    closing_amount = facts.closing_amount
    if accepted is not None:
        closing_amount, accepted_date = accepted
        if _is_date(accepted_date[:10]):
            closing = accepted_date[:10]
    if not (_is_date(opening) and _is_date(closing)) or opening > closing:
        return None
    try:
        return StatementRecord(
            doc_id=doc_id, account=account,
            opening_date=opening, opening_amount=Decimal(facts.opening_amount),
            closing_date=closing, closing_amount=Decimal(closing_amount))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _is_date(value: str) -> bool:
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except (ValueError, TypeError):
        return False


def _runs(records: list) -> list:
    """Consecutive statements joined into periods.

    A later statement continues an earlier one when it opens at the balance the
    earlier one closed at and opens on the day it closed or the day after.
    Anything else starts a new run, which is how a missing statement stays
    visible."""
    runs: list = []
    start = end = ""
    previous = None
    for record in records:
        if previous is not None and _joins(previous, record):
            end = max(end, record.closing_date)
        else:
            if start:
                runs.append((start, end))
            start, end = record.opening_date, record.closing_date
        previous = record
    if start:
        runs.append((start, end))
    return runs


def _joins(earlier: StatementRecord, later: StatementRecord) -> bool:
    if later.opening_amount != earlier.closing_amount:
        return False
    gap = (datetime.date.fromisoformat(later.opening_date)
           - datetime.date.fromisoformat(earlier.closing_date)).days
    return 0 <= gap <= 1
