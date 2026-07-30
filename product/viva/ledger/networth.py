"""Net worth — a curve, not a number with a date attached.

    net_worth(proj)                 the latest date there is evidence for
    net_worth(proj, "2026-03-31")   ... and any other date
    series(proj)                    the whole curve

Net worth is a function of date: `net_worth(D)` is every account's last-known
measurement at or before D. It needs no event type of its own — the ledger is
already an append-only log of dated observations, so this is a projection.

A depository balance here is the **observed closing balance** the issuer
attested, not the sum of postings the ledger holds: a statement's closing
balance is a measurement, while a sum of postings over a run that may be missing
a month is a derivation from incomplete data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .events import ASSERTED, CORROBORATED, ISSUED, VERIFIED
from .projection import MIXED

ASSET_ROOT = "Assets:"
LIABILITY_ROOT = "Liabilities:"


@dataclass
class NetWorthLine:
    """One account's contribution to one point on the curve.

    `amount` is signed FOR NET WORTH: positive is something you own, negative
    something you owe. That is not how the ledger stores a card, whose balance
    is money owed held as a positive magnitude, so the side is decided by the
    account's KIND rather than by the sign of the number (see `_side`).

    `as_of` is the date this figure was measured, usually earlier than the point
    it belongs to."""
    account: str
    amount: Decimal
    currency: str
    as_of: str
    grade: str
    origin: str
    kind: str
    proves: str = ""          # the document behind the figure

    @property
    def provable(self) -> bool:
        """True at grade `corroborated` — the attesting document is held and the
        arithmetic checks. Net worth reads the existing grade rather than a
        second issued/asserted vocabulary."""
        return self.grade == CORROBORATED


@dataclass
class NetWorthPoint:
    as_of: str
    lines: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    # Real accounts that contributed nothing to this point, and why.
    skipped: list = field(default_factory=list)
    # Documents read but not posted. They may name an account that does not
    # exist yet, so they cannot appear in `skipped`.
    held: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """False when something known to be owed has no usable figure, or when a
        document is read and not posted — the total is then partial."""
        return not self.missing and not self.held

    @property
    def oldest_input(self) -> str:
        """The stalest measurement this point rests on, or '' with no lines."""
        return min((ln.as_of for ln in self.lines), default="")

    def by_currency(self) -> dict:
        """Per-currency subtotals — ``{currency: {assets, liabilities, net,
        provable}}`` — and no grand total.

        There is no FX source with a date, a provenance and a grade of its own,
        so a converted total would be a figure no document attests."""
        out: dict[str, dict] = {}
        for ln in self.lines:
            row = out.setdefault(ln.currency, {
                "assets": Decimal("0"), "liabilities": Decimal("0"),
                "net": Decimal("0"), "provable": Decimal("0")})
            if ln.amount >= 0:
                row["assets"] += ln.amount
            else:
                row["liabilities"] += -ln.amount
            row["net"] += ln.amount
            if ln.provable:
                row["provable"] += ln.amount
        return out

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of, "complete": self.complete,
            "oldest_input": self.oldest_input,
            "by_currency": {c: {k: str(v) for k, v in row.items()}
                            for c, row in self.by_currency().items()},
            "lines": [{"account": ln.account, "amount": str(ln.amount),
                       "currency": ln.currency, "as_of": ln.as_of,
                       "grade": ln.grade, "origin": ln.origin, "kind": ln.kind,
                       "provable": ln.provable, "proves": ln.proves}
                      for ln in sorted(self.lines, key=lambda l: l.account)],
            "missing": self.missing, "skipped": self.skipped,
            "held": self.held}


def _side(kind: str, balance: Decimal) -> Decimal:
    """The contribution of a balance to net worth, decided by account KIND.

    A `liability` balance is money owed, so it is negated rather than
    absolute-valued: an overpaid card carries a negative owed figure and is
    genuinely an asset, which `abs()` would book as a debt."""
    return -balance if kind == "liability" else balance


# --- the pieces of one point -------------------------------------------------

def _closing_at(state, as_of: str):
    """The latest `(date, amount, grade, doc_id)` closing observed at or before
    `as_of`, or None when the account had no measurement by then.

    A None caller contributes NOTHING to the point, not zero: an account not yet
    seen is not an account worth nothing."""
    best = None
    for date, amount, grade, doc in state.closings:
        if date <= as_of and (best is None or date >= best[0]):
            best = (date, amount, grade, doc)
    return best


def _holdings_at(state, as_of: str) -> dict:
    """Holdings at `as_of`, summed per currency: ``{currency: {value, as_of,
    grade}}``. A later revaluation never moves an earlier point on the curve,
    which is why the projection keeps the whole observation history."""
    out: dict[str, dict] = {}
    # One snapshot, not a composition: the holdings that count at this date are
    # the ones on the latest statement at or before it, so an earlier point
    # still uses the statement that was current then and a holding the newest
    # statement no longer lists is no longer held.
    observed = [ob for history in state.position_history.values() for ob in history
                if ob.get("as_of") and ob["as_of"] <= as_of]
    if not observed:
        return out
    newest = max(ob["as_of"] for ob in observed)
    for best in (ob for ob in observed if ob["as_of"] == newest):
        cur = best["currency"] or state.currency
        row = out.setdefault(cur, {"value": Decimal("0"), "as_of": "",
                                   "grade": CORROBORATED})
        row["value"] += best["market_value"]
        row["as_of"] = max(row["as_of"], best["as_of"])
        # A line's grade is the weakest grade among the holdings it sums.
        if best["grade"] and best["grade"] != CORROBORATED:
            row["grade"] = best["grade"]
    return out


def _asserted_lines(proj, as_of: str):
    """Accounts a person's rulings brought into being. Returns
    ``(lines, missing)``.

    Three cases:

    * ``Assets:`` with every contributing movement decided — a line at **cost**,
      what was paid, never a present-day value. Badged `asserted`.
    * ``Assets:`` where any movement was ``MIXED`` — the cash is a fact, but how
      much of it bought equity is not. Goes to `missing`, naming what would fix
      it.
    * ``Liabilities:`` — always refused from cash flow alone, because money
      reaching a lender says nothing about the balance owed. Goes to `missing`
      with the ask and the document that would answer it.
    """
    groups: dict[tuple, dict] = {}
    for m in proj.movements():
        if not m.ruling_account or m.date > as_of:
            continue
        g = groups.setdefault((m.ruling_account, m.currency), {
            "paid": Decimal("0"), "as_of": "", "reliable": True})
        g["paid"] += abs(m.amount)
        g["as_of"] = max(g["as_of"], m.date)
        if m.nature == MIXED:
            g["reliable"] = False

    lines, missing = [], []
    for (account, currency), g in groups.items():
        if account.startswith(LIABILITY_ROOT):
            missing.append({
                "account": account, "why": "cash paid does not tell us the balance owed",
                "ask": "Roughly what do you owe on this?",
                "would_fix": "the loan or mortgage statement"})
            continue
        if not g["reliable"]:
            missing.append({
                "account": account,
                "why": "part of this payment was interest, not equity",
                "ask": "Roughly what is this worth to you now?",
                "would_fix": "the mortgage statement or 1098"})
            continue
        lines.append(NetWorthLine(
            account=account, amount=g["paid"], currency=currency,
            # VERIFIED, not CORROBORATED: a person attested this figure and no
            # document has checked it, which keeps it out of the provable
            # subtotal until one does.
            as_of=g["as_of"], grade=VERIFIED,
            origin=ASSERTED, kind="asserted"))
    return lines, missing


# --- the curve ---------------------------------------------------------------

def change_dates(proj) -> list[str]:
    """Every date on which net worth can move, sorted: a statement closed, a
    holding was measured, or a ruling was made. Evaluating between them repeats
    a point, so the curve is exactly as long as its evidence."""
    dates: set[str] = set()
    for account in proj.accounts():
        st = proj._state(account)
        dates.update(d for d, *_ in st.closings)
        for observations in st.position_history.values():
            dates.update(ob["as_of"] for ob in observations)
    dates.update(m.date for m in proj.movements() if m.ruling_account)
    return sorted(d for d in dates if d)


def net_worth(proj, as_of: str | None = None) -> NetWorthPoint:
    """One point on the curve. With no date, the latest one we have evidence for."""
    dates = change_dates(proj)
    if as_of is None:
        as_of = dates[-1] if dates else ""
    point = NetWorthPoint(as_of=as_of)
    if not as_of:
        return point

    for account in proj.accounts():
        info = proj.account_info(account)
        st = proj._state(account)
        if info.kind not in ("depository", "liability", "investment"):
            continue

        closing = _closing_at(st, as_of)
        if closing is None and not _holdings_at(st, as_of):
            # An account held but not valuable at this date: named in `skipped`
            # so the point says what it does not include.
            later = min((d for d, *_ in st.closings if d > as_of), default="")
            point.skipped.append({
                "account": account, "kind": info.kind,
                "why": (f"no statement on or before this date — the first is {later}"
                        if later else
                        "no balance has ever been observed for this account; if "
                        "its statements were held (parked or unreconciled), they "
                        "are not in your net worth")})
        if closing is not None:
            date, amount, grade, doc = closing
            point.lines.append(NetWorthLine(
                account=account, amount=_side(info.kind, amount),
                currency=info.currency,
                as_of=date, grade=grade or CORROBORATED,   # pre-grade events
                origin=info.origin or ISSUED, kind=info.kind, proves=doc))

        for currency, row in _holdings_at(st, as_of).items():
            point.lines.append(NetWorthLine(
                account=f"{account}:Holdings", amount=row["value"],
                currency=currency, as_of=row["as_of"], grade=row["grade"],
                origin=info.origin or ISSUED, kind="holdings"))

    asserted, missing = _asserted_lines(proj, as_of)
    point.lines.extend(asserted)
    point.missing.extend(missing)
    for hold in proj.open_holds():
        point.held.append({"doc_id": hold.get("doc_id", ""),
                           "reason": hold.get("reason", ""),
                           "why": "read but not posted, so nothing it attests is in this figure"})
    return point


def series(proj) -> list[NetWorthPoint]:
    """The whole curve, earliest evidence to latest.

    An earlier point never changes when a later document arrives: each point
    reads only measurements dated at or before itself, so the curve grows
    forward and history is stable."""
    return [net_worth(proj, d) for d in change_dates(proj)]
