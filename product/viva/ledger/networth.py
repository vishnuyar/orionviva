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
    it belongs to. Where the line composes several measurements it is the
    oldest of them, and `mixed_vintage` says that they were not all taken on
    one day — a fact about the figure rather than a doubt about it."""
    account: str
    amount: Decimal
    currency: str
    as_of: str
    grade: str
    origin: str
    kind: str
    proves: str = ""          # the document behind the figure
    mixed_vintage: bool = False

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
                       "provable": ln.provable, "proves": ln.proves,
                       "mixed_vintage": ln.mixed_vintage}
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


def _asserted_asset_lines(proj, as_of: str, valued: set):
    """Assets the person asserted, as ``(lines, gaps, superseded)``.

    An asserted asset with a stated gating figure becomes a line at cost,
    graded ``verified`` and origin ``asserted``; one without becomes a
    disclosed gap naming the question that closes it. ``superseded`` are
    accounts whose cash-derived line the stated figure replaces.

    Reads only what was known at ``as_of``, so a later answer does not change
    an earlier point."""
    from .. import schemas
    from ..env import jurisdiction_from_env
    from ..interview import attributes
    from .events import ASSERTED as _ASSERTED
    answers = attributes(proj, as_of=as_of)
    # The SAME fallback the interview uses. Two readers of one pack that
    # resolved it differently would demand a figure through one door and refuse
    # to record it at the other.
    here = jurisdiction_from_env()
    lines, gaps, superseded = [], [], set()
    for info in proj.account_infos():
        account = info.account
        # Only what the PERSON says they hold. An issued account is valued from
        # its statements, and announcing a gap on one would be a second, louder
        # answer to a question its documents already settle.
        if not account.startswith(ASSET_ROOT) or info.origin != _ASSERTED:
            continue
        answered = answers.get(account, {})
        stated = _stated_cost(proj, info, answered, here)
        if account in valued:
            # A stated cost replaces the cash-derived line for this account
            # rather than adding to it.
            if stated is not None:
                lines.append(stated)
                superseded.add(account)
            continue
        # The curve grows forward: a thing disclosed before it existed would be
        # a claim about a date it does not apply to.
        opened = (info.opened_at or "")[:10]
        if opened and opened > as_of:
            continue
        if stated is not None:
            lines.append(stated)
            continue
        gaps.append(_gap_for(proj, info, answered, here))
    return lines, gaps, superseded


def _schema_for_account(proj, info, here):
    """The schema for an account, resolved where its instrument lives — or
    where the vault is, when nobody has said."""
    from .. import schemas
    where = info.jurisdiction or here
    return schemas.schema_for(
        schemas.kind_of_account(info.account, where, ledger_kind=info.kind,
                                doc_types=proj.document_types_of(info.account)),
        where)


def _gating(schema, answered):
    """The questions whose answers let net worth carry the thing, and that
    apply given what is already known. A conditional essential — a term
    deposit's principal — is not owed on an account it was never about."""
    if schema is None:
        return []
    return [q for q in schema.questions
            if q.gates_net_worth and q.required(answered)]


def _stated_cost(proj, info, answered, here):
    """The line an asserted asset earns from what the person stated, or None.

    None is never silence — the caller turns it into a disclosed gap."""
    schema = _schema_for_account(proj, info, here)
    gating = _gating(schema, answered)
    if not gating:
        return None
    answer = answered.get(gating[0].key)
    if answer is None or any(q.key not in answered for q in gating):
        return None
    amount = _stated_amount(answer.get("value"))
    if amount is None:
        return None
    return NetWorthLine(
        # One line per account, never one per question: a point holds one
        # contribution per account, and two would read as two things.
        account=info.account, amount=amount,
        currency=answer.get("currency") or info.currency,
        as_of=(_dated_at(schema, answered) or answer.get("at")
               or (info.opened_at or "")[:10]),
        # Their word, which no document has checked — so it stays outside the
        # provable subtotal until one does.
        grade=VERIFIED, origin=ASSERTED, kind="asserted")


def _gap_for(proj, info, answered, here) -> dict:
    """What is missing, said plainly — including when the missing thing is the
    QUESTION. An asset the pack cannot yet ask about is still disclosed rather
    than omitted, because "I have no way to ask about this one" is an honest
    answer where inventing a zero is not."""
    schema = _schema_for_account(proj, info, here)
    want = next((q for q in _gating(schema, answered) if q.key not in answered),
                None)
    if want is None:
        return {
            "account": info.account,
            "why": "you've told me this exists; I have no way to ask what it "
                   "cost yet, so I am not carrying it",
            "ask": "",
            "would_fix": "a schema for this kind of thing"}
    return {
        "account": info.account,
        # The gap is about what the thing cost, never about what it is worth
        # today — that is a different claim, and not one this product makes.
        "why": "you've told me this exists; nobody has told me what it cost",
        "ask": want.asks,
        "would_fix": (want.corroborated_by[0] if want.corroborated_by
                      else "the paperwork for it")}


def _stated_amount(value):
    """A figure the ledger can stand behind, or None.

    None is never silence: the caller turns it back into a disclosed gap, so a
    value that cannot be read is reported rather than dropped."""
    try:
        amount = Decimal(str(value))
    except Exception:                                  # noqa: BLE001 - not a figure
        return None
    return amount if amount.is_finite() else None


def _dated_at(schema, answered) -> str:
    """When the thing was acquired, if the schema collects it — the value time
    the figure belongs to, rather than the day it was typed."""
    for q in schema.questions:
        if q.dates_net_worth and q.key in answered:
            return str((answered.get(q.key) or {}).get("value", ""))[:10]
    return ""


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
    # An asset a person told us about is a change even before any money moves
    # through it: from that date the curve is either carrying it or saying it
    # cannot, and both are answers. Without this the point does not exist and
    # the gap could not be disclosed at all.
    for account in proj.accounts():
        info = proj.account_info(account)
        if info.origin == ASSERTED and info.opened_at:
            dates.add(info.opened_at[:10])
    # And on the day the person states what one of them cost.
    from .events import SCOPE_ATTRIBUTE
    for ruling in proj.rulings(SCOPE_ATTRIBUTE):
        at = str(ruling.get("occurred_at", ""))[:10]
        if at:
            dates.add(at)
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

        # One account is one line. A brokerage's cash and its securities are
        # one thing a person owns, so they compose into one value, dated by the
        # oldest measurement under it and graded by the weakest — the same rule
        # every other read of that account states it by. Holdings in a currency
        # the cash is not in stay a line of their own, because nothing here
        # converts between currencies.
        composed = proj.composed_values(account, as_of)
        if not composed:
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
            continue
        for value in composed:
            point.lines.append(NetWorthLine(
                account=account, amount=_side(info.kind, value.amount),
                currency=value.currency, as_of=value.as_of, grade=value.grade,
                origin=info.origin or ISSUED, kind=info.kind,
                proves=value.proves, mixed_vintage=value.mixed_vintage))

    asserted, missing = _asserted_lines(proj, as_of)
    point.lines.extend(asserted)
    point.missing.extend(missing)
    valued = ({ln.account for ln in point.lines}
              | {row["account"] for row in point.missing})
    stated, gaps, superseded = _asserted_asset_lines(proj, as_of, valued)
    point.lines = [ln for ln in point.lines if ln.account not in superseded]
    point.lines.extend(stated)
    point.missing.extend(gaps)
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
