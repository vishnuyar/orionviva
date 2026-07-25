"""BrokerageFacts — the structured read of one brokerage/retirement statement.

The second divergent sibling of StatementFacts (Slice 6). A brokerage statement's
shape is not a balance and not a pay stub: it holds a list of *positions*
(instrument + units + market value) plus a cash balance, and its self-check is a
snapshot — ``Σ position market_value + cash = account total`` — not a flow. So it
has its own facts type, its own parser, and its own verification identity, all
selected by its registry profile.

The load-bearing decision (Option A): a position is a dated MEASUREMENT, never a
posting; unrealized gain is a derived presentation view, never a ledger fact (M1,
cash-flow over accrual). This module only reads the numbers; the projector decides
what to measure and what (cash only) to post.

Same honesty contract as statements: amounts go through the shared deterministic
normalizer, and any ambiguous/invalid figure fails the whole parse — a brokerage
statement we cannot read to the cent goes to review, never guessed. Cost basis is
optional: absent when the statement omits it, never invented.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal

from vivacore.verify.normalize import parse_amount, parse_date

from ..ledger.events import Provenance
from ..ledger.postings import BROKERAGE_ACTIVITY_KINDS
from .statement import period_date

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PositionFact:
    instrument: str                    # ticker / name as printed (the identity key)
    units: Decimal                     # quantity held
    market_value: Decimal              # the statement's value for the holding
    cost_basis: Decimal | None = None  # optional — None when the statement omits it
    page: int | None = None

    def to_dict(self) -> dict:
        return {"instrument": self.instrument, "units": str(self.units),
                "market_value": str(self.market_value),
                "cost_basis": (str(self.cost_basis)
                               if self.cost_basis is not None else ""),
                "page": self.page}

    @classmethod
    def from_dict(cls, d: dict) -> "PositionFact":
        cb = d.get("cost_basis", "")
        return cls(instrument=d.get("instrument", ""), units=Decimal(d["units"]),
                   market_value=Decimal(d["market_value"]),
                   cost_basis=(Decimal(cb) if cb not in (None, "") else None),
                   page=d.get("page"))


@dataclass(frozen=True)
class BrokerageActivity:
    """One cash-affecting event in the period (Slice 6 Stage 2). ``amount`` is the
    positive magnitude; the sign is implied by ``kind``. ``realized_gain`` is the
    booked gain/loss on a sell when the statement reports it (else None — never
    invented)."""
    date: str
    kind: str                          # contribution|withdrawal|dividend|interest|fee|buy|sell
    amount: Decimal
    description: str = ""
    instrument: str = ""
    realized_gain: Decimal | None = None

    def to_dict(self) -> dict:
        return {"date": self.date, "kind": self.kind, "amount": str(self.amount),
                "description": self.description, "instrument": self.instrument,
                "realized_gain": (str(self.realized_gain)
                                  if self.realized_gain is not None else "")}

    @classmethod
    def from_dict(cls, d: dict) -> "BrokerageActivity":
        rg = d.get("realized_gain", "")
        return cls(date=d.get("date", ""), kind=d.get("kind", ""),
                   amount=Decimal(d["amount"]), description=d.get("description", ""),
                   instrument=d.get("instrument", ""),
                   realized_gain=(Decimal(rg) if rg not in (None, "") else None))


@dataclass
class BrokerageFacts:
    doc_id: str
    doc_type: str
    doc_type_confidence: float
    account_ref: str
    currency: str
    as_of: str                         # the statement date the snapshot is measured at
    cash: Decimal                      # cash / sweep balance (closing)
    total: Decimal                     # stated total account value
    positions: list[PositionFact]
    account_number: str = ""
    institution: str = ""
    account_names: list[str] = field(default_factory=list)
    # Stage 2 (cross-account cash flow) — optional; when both are present the cash
    # is reconciled as a flow (opening + Σ activity = closing) and posted, tying
    # contributions to the funding account and recognizing income/fees/gains.
    opening_cash: Decimal | None = None
    activity: list[BrokerageActivity] = field(default_factory=list)

    def provenance(self, note: str = "") -> Provenance:
        return Provenance(doc_id=self.doc_id, note=note)

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id, "doc_type": self.doc_type,
            "doc_type_confidence": self.doc_type_confidence,
            "account_ref": self.account_ref, "currency": self.currency,
            "as_of": self.as_of, "cash": str(self.cash), "total": str(self.total),
            "positions": [p.to_dict() for p in self.positions],
            "account_number": self.account_number, "institution": self.institution,
            "account_names": list(self.account_names),
            "opening_cash": (str(self.opening_cash)
                             if self.opening_cash is not None else ""),
            "activity": [a.to_dict() for a in self.activity],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BrokerageFacts":
        oc = d.get("opening_cash", "")
        return cls(
            doc_id=d["doc_id"], doc_type=d.get("doc_type", "brokerage_statement"),
            doc_type_confidence=d.get("doc_type_confidence", 0.0),
            account_ref=d.get("account_ref", ""), currency=d["currency"],
            as_of=d.get("as_of", ""), cash=Decimal(d["cash"]),
            total=Decimal(d["total"]),
            positions=[PositionFact.from_dict(x) for x in d.get("positions", [])],
            account_number=d.get("account_number", ""),
            institution=d.get("institution", ""),
            account_names=list(d.get("account_names", [])),
            opening_cash=(Decimal(oc) if oc not in (None, "") else None),
            activity=[BrokerageActivity.from_dict(x) for x in d.get("activity", [])])


# A brokerage account's "cash" is usually a money-market fund — Fidelity's core
# position is SPAXX — so the same money can appear as a cash line, as a holding,
# or (across two months of the SAME account) as one then the other. Two real
# statements proved it: November printed cash = the sweep balance exactly, while
# December printed cash EXCLUDING a separately-listed sweep. Treating the sweep as
# a holding double-counts in the first case; treating it as cash under-counts in
# the second. So we recognize it here and let the projector decide which reading
# reconciles (Slice 6 fix, 2026-07-25).
_CASH_INSTRUMENTS = frozenset({
    "cash", "cash balance", "cash & cash investments", "cash and equivalents",
    "cash equivalents", "sweep", "cash sweep", "core position", "money market"})

# Substrings that mark a holding as the cash sweep whatever else its label says
# (e.g. "FIDELITY GOVERNMENT MONEY MARKET (SPAXX)").
_CASH_MARKERS = ("money market", "cash sweep", "core position", "sweep account")


def is_cash_row(instrument: str) -> bool:
    """True when a listed 'position' is really the account's cash.

    Being wrong here is safe: the projector only *acts* on this when one reading
    of the tally reconciles exactly and the other doesn't. A misclassified holding
    simply fails to close and the statement is held, never silently mis-posted."""
    label = (instrument or "").strip().lower()
    if label in _CASH_INSTRUMENTS:
        return True
    return any(marker in label for marker in _CASH_MARKERS)


def resolve_sweep_cash(facts: "BrokerageFacts") -> tuple["BrokerageFacts", str]:
    """Decide whether the statement's cash line already includes the money-market
    sweep, and normalize so that it always does.

    The same account can print it either way month to month, so we don't guess: we
    try both readings and take the one whose tally closes **exactly**. If neither
    closes (or there is no sweep), the facts come back untouched and the ordinary
    gate decides — decisive-or-hold, never a fitted answer.

    Returns (facts, note); ``note`` is empty when nothing was decided. Shared by
    the projector and the claims diagnostic so they can never disagree."""
    from vivacore.verify.arithmetic import check_brokerage_identity

    sweeps = [p for p in facts.positions if is_cash_row(p.instrument)]
    if not sweeps:
        return facts, ""
    holdings = [p for p in facts.positions if not is_cash_row(p.instrument)]
    sweep_total = sum((p.market_value for p in sweeps), start=Decimal("0"))
    values = [p.market_value for p in holdings]
    separate = check_brokerage_identity(values, facts.cash + sweep_total, facts.total)
    included = check_brokerage_identity(values, facts.cash, facts.total)
    if not (separate.passed or included.passed):
        return facts, ""
    if included.passed and not separate.passed:
        return (replace(facts, positions=holdings),
                "the cash line already included it")
    return (replace(facts, cash=facts.cash + sweep_total, positions=holdings),
            "it was listed separately from the cash line")


def _find_json(text: str) -> str | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return None


def _amount(raw, locale: str, currency: str) -> tuple[Decimal | None, str | None]:
    n = parse_amount(str(raw), locale, currency)
    if not n.ok:
        return None, f"amount {raw!r}: {n.status} ({n.reason})"
    return n.decimal(), None


def _optional_amount(raw, locale: str, currency: str, what: str) -> Decimal | None:
    """An OPTIONAL figure: absent when the statement omits it, and absent when it
    prints something unreadable ("not applicable", "N/A", "—").

    The discipline (from a real run that lost a whole statement to a cost-basis of
    'not applicable'): **fail a parse only on figures the identity depends on.**
    Units, market value, cash and total are load-bearing — an unreadable one sends
    the document to review. An optional attribute that can't be read is simply
    *unknown*, which the model already represents as None. It is logged, never
    guessed and never fatal."""
    if raw in (None, ""):
        return None
    n = parse_amount(str(raw), locale, currency)
    if not n.ok:
        log.info("brokerage: %s %r is not a number (%s) — recorded as unknown",
                 what, raw, n.status)
        return None
    return n.decimal()


def from_brokerage_json(text: str, doc_id: str, locale: str,
                        currency: str) -> tuple[BrokerageFacts | None, str | None]:
    """Parse a model's brokerage read into canonical BrokerageFacts.

    Returns (facts, error). Any ambiguous/invalid figure fails the whole parse — a
    holding we cannot read to the cent sends the statement to review, never
    guessed. Units parse as a plain Decimal (a share count is locale-light);
    cost basis is optional and absent (not zero) when unreadable/omitted."""
    blob = _find_json(text)
    if blob is None:
        return None, "no JSON object found in model output"
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        return None, f"JSON did not parse: {e}"
    if not isinstance(data, dict):
        return None, "top-level JSON is not an object"

    cash, err = _amount(data.get("cash_raw"), locale, currency)
    if err:
        return None, f"cash {err}"
    total, err = _amount(data.get("total_raw"), locale, currency)
    if err:
        return None, f"total {err}"
    as_of, derr = "", None
    if data.get("as_of_raw") not in (None, ""):
        n = parse_date(str(data.get("as_of_raw")), locale)
        if not n.ok:
            return None, f"as_of date {data.get('as_of_raw')!r}: {n.status}"
        as_of = n.value

    if not isinstance(data.get("positions"), list):
        return None, "missing 'positions' array"
    positions: list[PositionFact] = []
    for i, rp in enumerate(data["positions"]):
        if not isinstance(rp, dict):
            return None, f"position {i} is not an object"
        units_n = parse_amount(str(rp.get("units_raw", "")), locale, currency)
        if not units_n.ok:
            return None, f"position {i} units {rp.get('units_raw')!r}: {units_n.status}"
        mv, err = _amount(rp.get("market_value_raw"), locale, currency)
        if err:
            return None, f"position {i} market_value {err}"
        # Optional: unreadable means unknown, never fatal (never invented either).
        cost = _optional_amount(rp.get("cost_basis_raw"), locale, currency,
                                f"position {i} cost_basis")
        # Sweep rows are kept AS READ here; only the projector can tell whether the
        # statement's cash line already includes them (it needs the stated total to
        # decide), so folding at parse time would destroy the evidence.
        positions.append(PositionFact(
            instrument=str(rp.get("instrument", "")).strip(),
            units=units_n.decimal(), market_value=mv,
            cost_basis=cost, page=rp.get("page")))

    # Stage 2 (optional): opening cash + the period's cash activity. Absent on a
    # holdings-only statement — then only the snapshot is recorded (Stage 1).
    opening_cash = None
    if data.get("opening_cash_raw") not in (None, ""):
        opening_cash, err = _amount(data.get("opening_cash_raw"), locale, currency)
        if err:
            return None, f"opening_cash {err}"
    activity: list[BrokerageActivity] = []
    if isinstance(data.get("activity"), list):
        for i, ra in enumerate(data["activity"]):
            if not isinstance(ra, dict):
                return None, f"activity {i} is not an object"
            kind = str(ra.get("kind", "")).strip().lower()
            if kind not in BROKERAGE_ACTIVITY_KINDS:
                return None, (f"activity {i} has unknown kind {kind!r} "
                              f"(expected one of {sorted(BROKERAGE_ACTIVITY_KINDS)})")
            amt, err = _amount(ra.get("amount_raw"), locale, currency)
            if err:
                return None, f"activity {i} amount {err}"
            gain = _optional_amount(ra.get("realized_gain_raw"), locale, currency,
                                    f"activity {i} realized_gain")
            adate = ""
            if ra.get("date_raw") not in (None, ""):
                # Activity lines print "11/04" — the year is in the header. Resolve
                # it against the statement's as-of date (never invent a year).
                adate, derr = period_date(ra.get("date_raw"), locale, as_of)
                if derr:
                    return None, f"activity {i} {derr}"
            activity.append(BrokerageActivity(
                date=adate, kind=kind, amount=abs(amt),
                description=str(ra.get("description", "")).strip(),
                instrument=str(ra.get("instrument", "")).strip(),
                realized_gain=gain))

    raw_names = data.get("account_names")
    if isinstance(raw_names, list):
        names = [str(n).strip() for n in raw_names if str(n).strip()]
    elif raw_names:
        names = [str(raw_names).strip()]
    else:
        names = []

    facts = BrokerageFacts(
        doc_id=doc_id,
        doc_type=str(data.get("doc_type", "brokerage_statement")).strip().lower()
        or "brokerage_statement",
        doc_type_confidence=float(data.get("doc_type_confidence", 0.0) or 0.0),
        account_ref=str(data.get("account_ref", "")).strip(),
        currency=currency.upper(), as_of=as_of, cash=cash, total=total,
        positions=positions,
        account_number=str(data.get("account_number", "")).strip(),
        institution=str(data.get("institution", "")).strip(),
        account_names=names, opening_cash=opening_cash, activity=activity)
    return facts, None
