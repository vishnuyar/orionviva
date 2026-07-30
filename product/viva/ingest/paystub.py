"""PayStubFacts — the structured read of one pay stub.

A divergent sibling of StatementFacts: its identity is
`gross − Σ deductions = net`, so it has its own facts type, parser and
verification identity, selected by its registry profile. Amounts and dates go
through the shared deterministic normalizers, and an ambiguous figure is a
refusal to build the facts rather than a guess.

Each deduction carries a **category** — the universal bucket (tax / retirement /
insurance / other) it belongs to, jurisdiction-free so equivalent schemes in
any country land in the same bucket. The category is the model's proposal,
graded downstream, and an unrecognized one falls back to `other`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal

from vivacore.verify.normalize import parse_amount, parse_date

from ..ledger.events import Provenance

# The universal deduction buckets. Jurisdiction is an attribute, not a bucket.
TAX = "tax"
RETIREMENT = "retirement"
INSURANCE = "insurance"
OTHER = "other"
CATEGORIES = (TAX, RETIREMENT, INSURANCE, OTHER)


@dataclass(frozen=True)
class Deduction:
    label: str                 # as printed on the stub
    amount: Decimal            # positive magnitude withheld
    category: str = OTHER      # universal bucket; the model's graded proposal

    def to_dict(self) -> dict:
        return {"label": self.label, "amount": str(self.amount),
                "category": self.category}

    @classmethod
    def from_dict(cls, d: dict) -> "Deduction":
        cat = str(d.get("category", OTHER)).strip().lower()
        return cls(label=d.get("label", ""), amount=Decimal(d["amount"]),
                   category=cat if cat in CATEGORIES else OTHER)


@dataclass
class PayStubFacts:
    doc_id: str
    doc_type: str
    doc_type_confidence: float
    employer: str
    currency: str
    pay_date: str
    period_start: str
    period_end: str
    gross: Decimal
    net: Decimal
    deductions: list[Deduction]
    employee_names: list[str] = field(default_factory=list)
    gross_page: int | None = None
    net_page: int | None = None

    def provenance(self, note: str = "") -> Provenance:
        return Provenance(doc_id=self.doc_id, note=note)

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id, "doc_type": self.doc_type,
            "doc_type_confidence": self.doc_type_confidence,
            "employer": self.employer, "currency": self.currency,
            "pay_date": self.pay_date, "period_start": self.period_start,
            "period_end": self.period_end,
            "gross": str(self.gross), "net": str(self.net),
            "deductions": [d.to_dict() for d in self.deductions],
            "employee_names": list(self.employee_names),
            "gross_page": self.gross_page, "net_page": self.net_page,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PayStubFacts":
        return cls(
            doc_id=d["doc_id"], doc_type=d.get("doc_type", "pay_stub"),
            doc_type_confidence=d.get("doc_type_confidence", 0.0),
            employer=d.get("employer", ""), currency=d["currency"],
            pay_date=d.get("pay_date", ""), period_start=d.get("period_start", ""),
            period_end=d.get("period_end", ""),
            gross=Decimal(d["gross"]), net=Decimal(d["net"]),
            deductions=[Deduction.from_dict(x) for x in d.get("deductions", [])],
            employee_names=list(d.get("employee_names", [])),
            gross_page=d.get("gross_page"), net_page=d.get("net_page"))


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


def _date(raw, locale: str) -> tuple[str | None, str | None]:
    if raw in (None, ""):
        return "", None
    n = parse_date(str(raw), locale)
    if not n.ok:
        return None, f"date {raw!r}: {n.status} ({n.reason})"
    return n.value, None


def from_paystub_json(text: str, doc_id: str, locale: str,
                      currency: str) -> tuple[PayStubFacts | None, str | None]:
    """Parse a model's pay-stub read into canonical PayStubFacts.

    Returns (facts, error). Any ambiguous or invalid figure fails the whole
    parse, sending the pay stub to review. An absent date is "", not an error;
    an unrecognized deduction category falls back to `other`."""
    blob = _find_json(text)
    if blob is None:
        return None, "no JSON object found in model output"
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        return None, f"JSON did not parse: {e}"
    if not isinstance(data, dict):
        return None, "top-level JSON is not an object"

    gross, err = _amount(data.get("gross_raw"), locale, currency)
    if err:
        return None, f"gross {err}"
    net, err = _amount(data.get("net_raw"), locale, currency)
    if err:
        return None, f"net {err}"

    pay_date, err = _date(data.get("pay_date_raw"), locale)
    if err:
        return None, f"pay_date {err}"
    p_start, err = _date(data.get("period_start_raw"), locale)
    if err:
        return None, f"period_start {err}"
    p_end, err = _date(data.get("period_end_raw"), locale)
    if err:
        return None, f"period_end {err}"

    if not isinstance(data.get("deductions"), list):
        return None, "missing 'deductions' array"
    deductions: list[Deduction] = []
    for i, rd in enumerate(data["deductions"]):
        if not isinstance(rd, dict):
            return None, f"deduction {i} is not an object"
        amt, err = _amount(rd.get("amount_raw"), locale, currency)
        if err:
            return None, f"deduction {i} {err}"
        cat = str(rd.get("category", OTHER)).strip().lower()
        deductions.append(Deduction(
            label=str(rd.get("label", "")), amount=abs(amt),
            category=cat if cat in CATEGORIES else OTHER))

    raw_names = data.get("employee_names")
    if isinstance(raw_names, list):
        names = [str(n).strip() for n in raw_names if str(n).strip()]
    elif raw_names:
        names = [str(raw_names).strip()]
    else:
        names = []

    facts = PayStubFacts(
        doc_id=doc_id,
        doc_type=str(data.get("doc_type", "pay_stub")).strip().lower() or "pay_stub",
        doc_type_confidence=float(data.get("doc_type_confidence", 0.0) or 0.0),
        employer=str(data.get("employer", "")).strip(),
        currency=currency.upper(),
        pay_date=pay_date, period_start=p_start, period_end=p_end,
        gross=gross, net=net, deductions=deductions,
        employee_names=names,
        gross_page=data.get("gross_page"), net_page=data.get("net_page"))
    return facts, None
