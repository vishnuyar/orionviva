"""Holdings as dated measurements, and the valuation an account composes to."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..events import Provenance
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


def snapshot_positions(st, as_of: str = "") -> dict:
    """An account's holdings from its LATEST statement at or before `as_of`
    (all statements when `as_of` is empty), as `{instrument: observation}`.
    Cash rows are excluded.

    A brokerage statement states everything the account holds on its date,
    so the holdings are one snapshot rather than a composition across
    statements: an instrument the newest statement does not list is no
    longer held, and composing would also let one instrument written two
    ways count twice."""
    obs = [(name, ob) for name, history in st.position_history.items()
           for ob in history
           if ob.get("as_of") and (not as_of or ob["as_of"] <= as_of)
           and not ob.get("is_cash")]
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


def holdings_as_of(core: ProjectionCore, account: str) -> tuple[str, bool]:
    """`(as_of, mixed)` for an account's composed value: the OLDEST
    measurement the figure rests on, and whether the parts it sums were
    measured on different dates. `("", False)` when nothing was measured.

    A cash measurement from one month can sit beside holdings from the next,
    so the composed figure is only good as of the oldest of them."""
    st = core._acct.get(account)
    measured = (list(st.positions.values()) + list(st.position_cash.values())
                if st else [])
    dates = {p["as_of"] for p in measured if p["as_of"]}
    if st is not None and st.closing_date:
        dates.add(st.closing_date)
    if not dates:
        return "", False
    return min(dates), len(dates) > 1


def account_value(core: ProjectionCore, account: str) -> Decimal:
    """An account's total value: for an investment account, cash plus Σ of
    the latest position market values; for any other, its balance.

    Pair with ``holdings_as_of``, which reports the date the composed figure
    is good as of and whether its parts were measured on different dates."""
    st = core._acct.get(account)
    if st is None or not st.seen:
        raise UnknownAccountError(account)
    if st.kind == "investment":
        return cash_value(core, account) + holdings_value(core, account)
    return balances_view.balance(core, account).amount


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
