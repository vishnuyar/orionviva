"""Holdings as dated measurements, and the valuation an account composes to."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..events import GRADES, Provenance
from . import balances as balances_view
from .core import ProjectionCore, UnknownAccountError


@dataclass
class PositionRecord:
    """One holding measured at a date. A measurement, not a posting; unrealized
    gain is derived here, as-of that date, and is never a stored ledger fact."""
    account: str
    instrument: str
    units: Decimal
    market_value: Decimal
    currency: str
    as_of: str
    cost_basis: Decimal | None
    valuation_class: str
    grade: str
    provenance: Provenance

    def unrealized_gain(self) -> Decimal | None:
        """market_value − cost_basis, or None when the cost basis is unknown.
        Computed on demand; never posted or reconciled."""
        return None if self.cost_basis is None else self.market_value - self.cost_basis

    def to_dict(self) -> dict:
        ug = self.unrealized_gain()
        return {"account": self.account, "instrument": self.instrument,
                "units": str(self.units), "market_value": str(self.market_value),
                "currency": self.currency, "as_of": self.as_of,
                "cost_basis": (str(self.cost_basis)
                               if self.cost_basis is not None else None),
                "unrealized_gain": (str(ug) if ug is not None else None),
                "valuation_class": self.valuation_class, "grade": self.grade,
                "provenance": self.provenance.to_dict()}


def snapshot_positions(st, as_of: str = "", *, cash: bool = False) -> dict:
    """An account's holdings from its LATEST statement at or before `as_of`
    (all statements when `as_of` is empty), as `{instrument: observation}`.
    Cash rows are excluded, or with `cash=True` are the only rows returned —
    a cash line an older read misfiled as a holding is the account's cash. The
    latest date is taken over the rows this call returns, so the cash rows and
    the holdings each answer for the newest statement that listed THEM, which
    need not be the same statement. A value composed from both carries the days
    it rests on, and the reads that state it say when those differ.

    A brokerage statement states everything the account holds on its date,
    so the holdings are one snapshot rather than a composition across
    statements: an instrument the newest statement does not list is no
    longer held, and composing would also let one instrument written two
    ways count twice."""
    obs = [(name, ob) for name, history in st.position_history.items()
           for ob in history
           if ob.get("as_of") and (not as_of or ob["as_of"] <= as_of)
           and bool(ob.get("is_cash")) == cash]
    if not obs:
        return {}
    newest = max(ob["as_of"] for _n, ob in obs)
    return {name: ob for name, ob in obs if ob["as_of"] == newest}


def positions(core: ProjectionCore,
              account: str | None = None) -> list[PositionRecord]:
    """Measured holdings from each account's latest statement, one snapshot
    per account, or from `account` alone if given. Each is a dated
    measurement carrying its as-of date and grade, never a current price."""
    out: list[PositionRecord] = []
    for acct, st in core._acct.items():
        if account is not None and acct != account:
            continue
        for instrument, p in sorted(snapshot_positions(st).items()):
            out.append(PositionRecord(
                account=acct, instrument=instrument, units=p["units"],
                market_value=p["market_value"], currency=p["currency"],
                as_of=p["as_of"], cost_basis=p["cost_basis"],
                valuation_class=p["valuation_class"], grade=p["grade"],
                provenance=p["provenance"]))
    return out


def holdings_value(core: ProjectionCore, account: str) -> Decimal:
    """Σ market value of an account's latest statement's holdings (no cash)."""
    st = core._acct.get(account)
    if st is None:
        return Decimal("0")
    return sum((p["market_value"] for p in snapshot_positions(st).values()),
               start=Decimal("0"))


def cash_value(core: ProjectionCore, account: str) -> Decimal:
    """An account's cash: its observed closing balance, or its replayed sum
    when none was attested, plus any cash/sweep line an older read misfiled
    as a "position". Raises UnknownAccountError on an unseen account."""
    st = core._acct.get(account)
    if st is None or not st.seen:
        raise UnknownAccountError(account)
    base = balances_view.effective(st) if st.closing is None else st.closing
    return base + sum((p["market_value"] for p in st.position_cash.values()),
                      start=Decimal("0"))


def _composed_grade(grades) -> str:
    """The grade a sum of measurements carries: the weakest of its terms, and
    none at all where any term carries no grade.

    The ladder is written strongest first, so the weakest term is the one
    furthest along it. A term nothing graded is not merely a weak term — adding
    a quantity nothing attested leaves a total nothing attested, which no rung
    on the ladder is true of — so the sum carries no grade rather than the
    weakest one present."""
    terms = list(grades)
    if not terms or any(g not in GRADES for g in terms):
        return ""
    return max(terms, key=GRADES.index)


@dataclass
class ComposedValue:
    """One account's worth as a single figure, in one currency: its cash plus
    the holdings its latest statement measured.

    `dates` are the distinct days the measurements under it were taken, oldest
    first. So `as_of` is the oldest of them — a sum is only as current as the
    stalest thing in it — and more than one of them is a fact about the figure
    that the reads stating it disclose rather than average away."""
    account: str
    amount: Decimal
    currency: str
    dates: tuple
    grade: str
    proves: str = ""

    @property
    def as_of(self) -> str:
        return self.dates[0] if self.dates else ""

    @property
    def mixed_vintage(self) -> bool:
        return len(self.dates) > 1


def _cash_term(core: ProjectionCore, st, account: str, as_of: str):
    """The account's cash and what attests it, as `(amount, currency, date,
    grade, doc)`, or None where nothing was attested by the date asked about.

    With no date asked about this is the balances view's own answer, replayed
    sum and all, graded by the ladder that says how well the figure standing
    now is stood behind. As of a date it is the closing the issuer attested on
    or before that date, and an account nothing measured by then has no cash
    term at all: a point on a curve is made of measurements, and replaying
    postings that may be dated later than the point would move an earlier
    answer every time a later document arrived."""
    if not as_of:
        ba = balances_view.balance(core, account)
        return ba.amount, st.currency, ba.dated, ba.grade, ba.provenance.doc_id
    best = None
    for date, amount, grade, doc in st.closings:
        if date <= as_of and (best is None or date >= best[0]):
            best = (date, amount, grade, doc)
    if best is None:
        return None
    date, amount, grade, doc = best
    return amount, st.currency, date, grade, doc


def composed_values(core: ProjectionCore, account: str,
                    as_of: str = "") -> list[ComposedValue]:
    """What an account is worth, as one figure per currency, as of a date.

    A brokerage account is one thing a person owns, so its cash and the
    holdings of its latest statement at or before `as_of` are one value. That
    value is dated by the OLDEST measurement under it, graded by the weakest of
    them, and carries the days it rests on so a read can say when they differ.
    An account with no holdings composes to its balance, which is the same rule
    with one term.

    Holdings in a currency the cash is not in make a SECOND entry rather than a
    bigger number: what cannot be summed is not summed, and nothing here
    converts between currencies.

    This is the one place the composition is computed. Every read that states
    an account's value — the balances read, the provenance read, and each point
    on the net-worth curve — asks here, so no two of them can describe one
    account differently."""
    st = core._acct.get(account)
    if st is None or not st.seen:
        raise UnknownAccountError(account)
    terms = []
    cash = _cash_term(core, st, account, as_of)
    if cash is not None:
        terms.append(cash)
    # Every measurement is its own term, carrying its own day and its own
    # grade, because those are what the date and the grade of the sum are read
    # off.
    for p in (list(snapshot_positions(st, as_of, cash=True).values())
              + list(snapshot_positions(st, as_of).values())):
        terms.append((p["market_value"], p["currency"] or st.currency,
                      p["as_of"], p["grade"], ""))
    groups: dict[str, dict] = {}
    for amount, currency, date, grade, doc in terms:
        g = groups.setdefault(currency, {"amount": Decimal("0"), "dates": set(),
                                         "grades": [], "proves": ""})
        g["amount"] += amount
        # A term nothing dated is a gap rather than a second vintage: it neither
        # dates the value nor makes it one that rests on more than one day.
        if date:
            g["dates"].add(date)
        g["grades"].append(grade)
        g["proves"] = g["proves"] or doc
    return [ComposedValue(account=account, amount=g["amount"], currency=currency,
                          dates=tuple(sorted(g["dates"])),
                          grade=_composed_grade(g["grades"]),
                          proves=g["proves"])
            for currency, g in sorted(groups.items())]


def holdings_as_of(core: ProjectionCore, account: str) -> tuple[str, bool]:
    """`(as_of, mixed)` for an account's composed value: the OLDEST
    measurement the figure rests on, and whether the parts it sums were
    measured on different dates. `("", False)` when nothing was measured.

    A cash measurement from one month can sit beside holdings from the next,
    so the composed figure is only good as of the oldest of them. Only what the
    figure is actually summed out of counts: a holding the newest statement no
    longer lists is not in the value, so its date is not one of the value's
    dates either."""
    st = core._acct.get(account)
    if st is None or not st.seen:
        return "", False
    dates = sorted({d for v in composed_values(core, account) for d in v.dates})
    return (dates[0] if dates else ""), len(dates) > 1


def account_value(core: ProjectionCore, account: str) -> Decimal:
    """An account's composed value as a bare number, in the account's own
    currency: for an investment account, cash plus the latest snapshot's
    holdings; for any other, its balance.

    ``composed_values`` is what a read states, because it carries the date, the
    grade and the days the figure rests on, and keeps holdings in a second
    currency as their own figure rather than folding them into this one."""
    values = composed_values(core, account)
    if len(values) == 1:
        return values[0].amount
    own = core._acct[account].currency
    return next((v.amount for v in values if v.currency == own), Decimal("0"))


def unrealized_gain(core: ProjectionCore,
                    account: str | None = None) -> Decimal | None:
    """The derived paper gain over held positions (Σ market_value − Σ cost
    basis) as of the latest measurements, for one account or all of them.
    A read-side view, never a ledger fact. None when no position carries a
    cost basis to compare."""
    total = Decimal("0")
    any_basis = False
    for p in positions(core, account):
        if p.cost_basis is not None:
            any_basis = True
            total += p.market_value - p.cost_basis
    return total if any_basis else None
