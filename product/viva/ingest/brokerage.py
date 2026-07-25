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
import re
from dataclasses import dataclass, field
from decimal import Decimal

from vivacore.verify.normalize import parse_amount, parse_date

from ..ledger.events import Provenance


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


@dataclass
class BrokerageFacts:
    doc_id: str
    doc_type: str
    doc_type_confidence: float
    account_ref: str
    currency: str
    as_of: str                         # the statement date the snapshot is measured at
    cash: Decimal                      # cash / sweep balance
    total: Decimal                     # stated total account value
    positions: list[PositionFact]
    account_number: str = ""
    institution: str = ""
    account_names: list[str] = field(default_factory=list)

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
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BrokerageFacts":
        return cls(
            doc_id=d["doc_id"], doc_type=d.get("doc_type", "brokerage_statement"),
            doc_type_confidence=d.get("doc_type_confidence", 0.0),
            account_ref=d.get("account_ref", ""), currency=d["currency"],
            as_of=d.get("as_of", ""), cash=Decimal(d["cash"]),
            total=Decimal(d["total"]),
            positions=[PositionFact.from_dict(x) for x in d.get("positions", [])],
            account_number=d.get("account_number", ""),
            institution=d.get("institution", ""),
            account_names=list(d.get("account_names", [])))


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
        cost = None
        if rp.get("cost_basis_raw") not in (None, ""):
            cb, cerr = _amount(rp.get("cost_basis_raw"), locale, currency)
            if cerr:
                return None, f"position {i} cost_basis {cerr}"
            cost = cb
        positions.append(PositionFact(
            instrument=str(rp.get("instrument", "")).strip(),
            units=units_n.decimal(), market_value=mv, cost_basis=cost,
            page=rp.get("page")))

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
        account_names=names)
    return facts, None
