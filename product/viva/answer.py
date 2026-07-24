"""The v0 answer path — deterministic, and honest about what it doesn't know.

No model sits here (the v0 decision). A "question" is a fixed function call over
the projection, and the whole job of this layer is the *honesty envelope* around
the number: a cited source, a confidence grade, a coverage statement, and — the
part that is the actual product — a clean refusal when the honest answer is "I
can't tell you that reliably" rather than a bluffed figure (principle 2).

Three questions, and their refusals:
  - ``answer_balance``  — one account's balance, or a refusal (unknown account,
                          no data as of a date, or a conflicted figure we won't
                          assert). An unverified figure is given but flagged.
  - ``answer_total``    — the coverage-aware sum across checking accounts, per
                          currency (no FX — cross-currency totals are not faked).
  - ``coverage_summary``— what is answerable vs. what is held awaiting review
                          ("5 posted, 2 not yet readable"), from the ledger alone.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from .ledger import (CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED,
                     LedgerProjection, Provenance, UnknownAccountError)

# Grades safe to assert as an answer and to include in a total. Conflicted is
# never asserted; unverified is asserted only with a visible caveat.
TRUSTWORTHY = (VERIFIED, CORROBORATED)
DEPOSITORY = "depository"
LIABILITY = "liability"


def _projection(source, as_of: str | None = None) -> LedgerProjection:
    """Accept a live projection (the Ledger's cache) or an iterable of events.
    A live projection already has its as_of baked in; events build one on demand."""
    if isinstance(source, LedgerProjection):
        return source
    return LedgerProjection(source, as_of)


@dataclass
class Answer:
    question: str
    answered: bool
    text: str                                  # one honest sentence
    amount: Decimal | None = None
    currency: str | None = None
    grade: str | None = None
    as_of: str | None = None
    provenance: list[Provenance] = field(default_factory=list)
    subtotals: dict[str, str] = field(default_factory=dict)  # currency -> total
    coverage: str = ""
    caveats: list[str] = field(default_factory=list)
    reason: str = ""                           # machine tag when answered is False

    def to_dict(self) -> dict:
        return {
            "question": self.question, "answered": self.answered,
            "text": self.text,
            "amount": None if self.amount is None else str(self.amount),
            "currency": self.currency, "grade": self.grade, "as_of": self.as_of,
            "provenance": [p.to_dict() for p in self.provenance],
            "subtotals": self.subtotals, "coverage": self.coverage,
            "caveats": self.caveats, "reason": self.reason,
        }


@dataclass
class Coverage:
    documents_held: int
    posted: int
    awaiting: int
    awaiting_types: dict[str, int]
    text: str


def _money(amount: Decimal, currency: str) -> str:
    return f"{currency + ' ' if currency else ''}{amount}"


def answer_balance(source, account: str, as_of: str | None = None) -> Answer:
    """One account's balance — with grade and source, or an honest refusal."""
    proj = _projection(source, as_of)
    q = f"balance of {account}" + (f" as of {as_of}" if as_of else "")

    try:
        ba = proj.balance(account)
    except UnknownAccountError:
        return Answer(
            question=q, answered=False, reason="unknown_account",
            text=(f"I don't have an account '{account}' on file, so I can't give "
                  "you its balance — I'd rather say so than make one up."),
            coverage=_accounts_line(proj))

    info = proj.account_info(account)
    name = info.name or account

    if ba.grade == CONFLICTED:
        return Answer(
            question=q, answered=False, reason="conflicted", grade=CONFLICTED,
            as_of=ba.dated, provenance=[ba.provenance],
            text=(f"I can't give you a trustworthy balance for {name}: its "
                  f"statement doesn't reconcile ({ba.reconciliation.explain()}). "
                  "Here's the conflict rather than a number I don't believe."))

    caveats: list[str] = []
    if ba.grade == UNVERIFIED:
        caveats.append("Computed from transactions; no closing statement has "
                       "confirmed this figure yet.")

    # A liability's balance is money owed, not held — say so, and report the owed
    # magnitude as a positive figure a person recognizes from their bill.
    as_of = f" as of {ba.dated}" if ba.dated else ""
    if info.kind == LIABILITY:
        text = (f"You owe {_money(abs(ba.amount), ba.currency)} on {name}"
                f"{as_of} ({ba.grade}).")
    else:
        text = (f"Your {name} balance is {_money(ba.amount, ba.currency)}"
                f"{as_of} ({ba.grade}).")

    return Answer(
        question=q, answered=True, amount=ba.amount, currency=ba.currency,
        grade=ba.grade, as_of=ba.dated, provenance=[ba.provenance],
        caveats=caveats, text=text)


def answer_total(source, as_of: str | None = None) -> Answer:
    """Coverage-aware total across checking accounts, per currency (no FX)."""
    proj = _projection(source, as_of)
    q = "total across checking accounts" + (f" as of {as_of}" if as_of else "")

    infos = [i for i in proj.account_infos() if i.kind == DEPOSITORY]
    if not infos:
        return Answer(question=q, answered=False, reason="no_accounts",
                      text="I don't have any checking accounts on file yet.")

    sums: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    included: dict[str, list] = defaultdict(list)
    excluded: list[str] = []
    provenance: list[Provenance] = []

    for info in infos:
        ba = proj.balance(info.account)
        cur = info.currency or "?"
        if ba.grade in TRUSTWORTHY:
            sums[cur] += ba.amount
            included[cur].append((info, ba))
            provenance.append(ba.provenance)
        else:
            excluded.append(f"{info.name or info.account} "
                            f"({ba.grade}, not counted)")

    if not sums:                       # nothing trustworthy to total
        return Answer(
            question=q, answered=False, reason="nothing_trustworthy",
            caveats=excluded,
            text=("I can't total your checking accounts — none currently has a "
                  "balance I'd stand behind. " + "; ".join(excluded)))

    subtotals = {cur: str(total) for cur, total in sums.items()}
    coverage = _total_coverage(included, excluded)

    if len(sums) == 1:
        cur, total = next(iter(sums.items()))
        n = len(included[cur])
        return Answer(
            question=q, answered=True, amount=total, currency=cur,
            grade=CORROBORATED, as_of=as_of, provenance=provenance,
            subtotals=subtotals, coverage=coverage, caveats=excluded,
            text=(f"Your total across {n} checking account"
                  f"{'s' if n != 1 else ''} is {_money(total, cur)}, as of each "
                  "account's latest statement."))

    # Multiple currencies: report subtotals, never a faked converted sum.
    parts = "; ".join(f"{cur} {tot}" for cur, tot in subtotals.items())
    return Answer(
        question=q, answered=True, amount=None, currency=None,
        grade=CORROBORATED, as_of=as_of, provenance=provenance,
        subtotals=subtotals, coverage=coverage, caveats=excluded,
        text=(f"Across currencies (I don't convert between them): {parts}. "
              "Each is the sum of that currency's checking accounts."))


def answer_spending(source, as_of: str | None = None) -> Answer:
    """Real external spending, per currency — money that left your asset accounts
    to the outside world, with internal transfers (moving your own money)
    EXCLUDED (Slice 3). A minimal seed of the S5 spending view; its point here is
    to prove transfers don't inflate the number."""
    proj = _projection(source, as_of)
    q = "external spending" + (f" as of {as_of}" if as_of else "")
    sums = proj.spending_by_currency()
    if not sums:
        return Answer(question=q, answered=True, amount=Decimal("0"),
                      text="No external spending recorded yet.")
    pending = len(proj.transfer_suggestions())
    caveat = ([f"{pending} possible transfer(s) await your confirmation — "
               "confirming them would exclude that money from spending."]
              if pending else [])
    if len(sums) == 1:
        cur, total = next(iter(sums.items()))
        return Answer(
            question=q, answered=True, amount=total, currency=cur,
            subtotals={cur: str(total)}, caveats=caveat,
            text=(f"You spent {_money(total, cur)} externally"
                  f"{f' as of {as_of}' if as_of else ''} — internal transfers "
                  "between your own accounts are excluded."))
    parts = "; ".join(f"{c} {t}" for c, t in sums.items())
    return Answer(question=q, answered=True, amount=None,
                  subtotals={c: str(t) for c, t in sums.items()}, caveats=caveat,
                  text=(f"External spending (transfers excluded), per currency: "
                        f"{parts}."))


def coverage_summary(source) -> Coverage:
    """What we hold vs. what is answerable — read straight from the projection."""
    proj = _projection(source)
    captured = proj.captured_docs()
    posted_docs = proj.posted_doc_ids()

    held = [dt for did, dt in captured.items() if did not in posted_docs]
    awaiting_types: dict[str, int] = defaultdict(int)
    for dt in held:
        awaiting_types[dt] += 1
    posted = len(captured) - len(held)

    text = f"{len(captured)} document(s) held; {posted} posted to accounts"
    if held:
        types = ", ".join(f"{n} {t}" for t, n in sorted(awaiting_types.items()))
        text += f"; {len(held)} awaiting review ({types})"
    return Coverage(documents_held=len(captured), posted=posted,
                    awaiting=len(held), awaiting_types=dict(awaiting_types),
                    text=text + ".")


# ------------------------------------------------------------------ helpers


def _accounts_line(proj: LedgerProjection) -> str:
    names = [i.name or i.account for i in proj.account_infos()]
    if not names:
        return "I don't have any accounts on file yet."
    return "Accounts I do have: " + ", ".join(names) + "."


def _total_coverage(included: dict, excluded: list) -> str:
    parts = []
    for cur, rows in included.items():
        for info, ba in rows:
            parts.append(f"{info.name or info.account}: "
                         f"{_money(ba.amount, cur)} (as of {ba.dated})")
    line = "Included — " + "; ".join(parts) if parts else ""
    if excluded:
        line += ". Excluded — " + "; ".join(excluded)
    return line
