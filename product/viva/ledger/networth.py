"""Net worth (Slice 7) — a CURVE, not a number with a date attached.

    net_worth(proj)            what you are worth at the latest date we know
    net_worth(proj, "2026-03-31")   ... and at any other date
    series(proj)               the whole curve

The reframe that made this simple (Vishnu, 2026-07-26): *"net worth is always
as-of date, it should be from the earliest date available to latest date."*

Three plausible answers to "what date does a net-worth figure carry?" were on
the table — one coherent date (pure, but one stale statement drags the headline
months backwards), latest-known-per-account (current, but a number that was
never true at any instant), or both. All three assume net worth is a NUMBER that
needs a date. It is a FUNCTION of date, and asking "what am I worth?" is asking
for a point on it. That dissolves the problem instead of answering it: there is
no *the* net worth to be wrong about.

It also needs no new event type. The ledger is already an append-only log of
dated observations, so `net_worth(D)` is just "every account's last-known
measurement at or before D" — which is why this whole slice is a projection.

WHY OBSERVATIONS AND NOT OUR OWN ARITHMETIC. A depository balance here is the
**observed closing balance** the issuer attested, not the sum of postings we
hold. Summing postings would be *our* arithmetic over a run that may be missing
a month, and it would produce a confident figure from incomplete data — the
exact failure this product exists to refuse. A statement's closing balance is a
measurement (M1: measurements, not generations).

See docs/net-worth.md for the four decisions.
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

    `amount` is SIGNED in the ledger's own convention — a liability's balance is
    already negative — so a point is a plain sum and no code re-decides which
    side an account is on. `as_of` is the date this figure was measured, which
    is usually EARLIER than the point it belongs to; that gap is the honesty the
    whole slice exists to report."""
    account: str
    amount: Decimal
    currency: str
    as_of: str
    grade: str
    origin: str
    kind: str
    proves: str = ""          # the document behind the figure (T1)

    @property
    def provable(self) -> bool:
        """`corroborated` means we hold the attesting document AND the
        arithmetic checks. That is exactly what "provable" means, which is why
        net worth reads the existing grade instead of inventing a second
        issued/asserted vocabulary for the same idea (D4)."""
        return self.grade == CORROBORATED


@dataclass
class NetWorthPoint:
    as_of: str
    lines: list = field(default_factory=list)
    missing: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """False when something we KNOW you owe has no usable figure. The total
        is then knowingly too favourable, and says so rather than absorbing it."""
        return not self.missing

    @property
    def oldest_input(self) -> str:
        """The stalest measurement in this point. A total resting on a
        four-month-old brokerage statement should say so out loud."""
        return min((ln.as_of for ln in self.lines), default="")

    def by_currency(self) -> dict:
        """Per-currency subtotals, and deliberately **no grand total** (D5).

        One financial life can hold several currencies, and we have no FX source
        with a date, a provenance and a grade of its own. A converted total would
        be a figure no document attests — a bluff by construction."""
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
            "missing": self.missing}


# --- the pieces of one point -------------------------------------------------

def _closing_at(state, as_of: str):
    """The latest closing balance observed at or before `as_of`.

    None when the account had no measurement by then — and the caller must then
    contribute NOTHING rather than zero. An account we had not yet seen is not
    an account worth nothing; treating absence as zero is a claim we cannot
    make, and it would make the early curve confidently wrong."""
    best = None
    for date, amount, grade, doc in state.closings:
        if date <= as_of and (best is None or date >= best[0]):
            best = (date, amount, grade, doc)
    return best


def _holdings_at(state, as_of: str) -> dict:
    """Each instrument's latest measurement at or before `as_of`, summed per
    currency. A later revaluation must never move an earlier point on the curve,
    which is why the projection keeps the whole observation history and not just
    the newest one."""
    out: dict[str, dict] = {}
    for _instrument, observations in state.position_history.items():
        best = None
        for ob in observations:
            if ob["as_of"] <= as_of and (best is None or ob["as_of"] >= best["as_of"]):
                best = ob
        if best is None:
            continue
        cur = best["currency"] or state.currency
        row = out.setdefault(cur, {"value": Decimal("0"), "as_of": "",
                                   "grade": CORROBORATED})
        row["value"] += best["market_value"]
        row["as_of"] = max(row["as_of"], best["as_of"])
        # A mixed-grade holding drags the line's grade down to its weakest part.
        if best["grade"] and best["grade"] != CORROBORATED:
            row["grade"] = best["grade"]
    return out


def _asserted_lines(proj, as_of: str):
    """Accounts a person's own rulings brought into being (Slice 9a), and the
    ones we must refuse to value.

    Three cases, and the difference between them is the whole of decision D3:

    * ``Assets:`` with every contributing movement decided — include at **cost**,
      what you paid, never what it is now worth (M1). Badged `asserted`: your
      word, trusted, and honestly marked (D2).
    * ``Assets:`` where any movement was ``MIXED`` — the cash is a fact but how
      much of it bought equity is not. Refuse, and say what is missing.
    * ``Liabilities:`` — **always refused from cash flow alone.** Money reaching
      a lender tells us nothing about the balance owed: part of it was interest,
      and no amount of trusting the person fixes that, because they do not know
      either. Only the statement does. So it goes to `missing`, and the queue
      asks for a rough figure that a 1098 later upgrades.
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
            # VERIFIED, deliberately not CORROBORATED: a human attested this
            # figure, and no document has checked it. That single character of
            # difference is what keeps it out of the provable subtotal until an
            # invoice or a 1098 arrives — the grade ladder doing the work a
            # separate issued/asserted badge would have duplicated (D4).
            as_of=g["as_of"], grade=VERIFIED,
            origin=ASSERTED, kind="asserted"))
    return lines, missing


# --- the curve ---------------------------------------------------------------

def change_dates(proj) -> list[str]:
    """Every date on which net worth can move: a statement closed, a holding was
    measured, or a ruling was made. Evaluating between them would only repeat a
    point, so the curve is exactly as long as it has evidence to be."""
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
        if closing is not None:
            date, amount, grade, doc = closing
            point.lines.append(NetWorthLine(
                account=account, amount=amount, currency=info.currency,
                as_of=date, grade=grade or CORROBORATED,
                origin=info.origin or ISSUED, kind=info.kind, proves=doc))

        for currency, row in _holdings_at(st, as_of).items():
            point.lines.append(NetWorthLine(
                account=f"{account}:Holdings", amount=row["value"],
                currency=currency, as_of=row["as_of"], grade=row["grade"],
                origin=info.origin or ISSUED, kind="holdings"))

    asserted, missing = _asserted_lines(proj, as_of)
    point.lines.extend(asserted)
    point.missing.extend(missing)
    return point


def series(proj) -> list[NetWorthPoint]:
    """The whole curve, earliest evidence to latest.

    The property that makes it trustworthy: **an earlier point never changes
    when a later document arrives.** Each point reads only measurements dated at
    or before itself, so history is stable and the curve grows forward — which
    is what lets a person compare this month against last month and believe the
    comparison."""
    return [net_worth(proj, d) for d in change_dates(proj)]
