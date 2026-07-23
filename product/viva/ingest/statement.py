"""StatementFacts — the structured read of one statement, on the honesty contract.

A model reads the document and returns free-ish JSON. This module turns that into
a typed, canonical StatementFacts, and it does the turning through the shared
deterministic normalizers (``parse_amount`` / ``parse_date``), so:

  - amounts and dates are exact (Decimal, ISO), never floats;
  - a genuinely ambiguous figure (the "1.234" trap, "03/04/2025") comes back as
    a refusal to build the facts, not a silent guess — the statement goes to
    review instead of poisoning the ledger.

This is the product's claims-layer, statement-shaped. The model proposes; the
normalizer and (downstream) the reconciliation gate dispose.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal

from vivacore.verify.normalize import parse_amount, parse_date

from ..ledger.events import Provenance


@dataclass(frozen=True)
class TxnFact:
    date: str            # ISO yyyy-mm-dd (value time)
    description: str
    amount: Decimal      # signed: positive = money in, negative = money out
    page: int | None = None
    running_balance: Decimal | None = None   # the printed balance after this line

    def provenance(self, doc_id: str) -> Provenance:
        return Provenance(doc_id=doc_id, page=self.page)

    def to_dict(self) -> dict:
        return {"date": self.date, "description": self.description,
                "amount": str(self.amount), "page": self.page,
                "running_balance": (None if self.running_balance is None
                                    else str(self.running_balance))}

    @classmethod
    def from_dict(cls, d: dict) -> "TxnFact":
        rb = d.get("running_balance")
        return cls(date=d["date"], description=d.get("description", ""),
                   amount=Decimal(d["amount"]), page=d.get("page"),
                   running_balance=(None if rb is None else Decimal(rb)))


@dataclass
class StatementFacts:
    doc_id: str
    doc_type: str
    doc_type_confidence: float
    account_ref: str
    currency: str
    opening_amount: Decimal
    opening_date: str
    closing_amount: Decimal
    closing_date: str
    transactions: list[TxnFact]
    opening_page: int | None = None
    closing_page: int | None = None

    def opening_provenance(self) -> Provenance:
        return Provenance(doc_id=self.doc_id, page=self.opening_page,
                          note="opening balance")

    def closing_provenance(self) -> Provenance:
        return Provenance(doc_id=self.doc_id, page=self.closing_page,
                          note="closing balance")

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id, "doc_type": self.doc_type,
            "doc_type_confidence": self.doc_type_confidence,
            "account_ref": self.account_ref, "currency": self.currency,
            "opening_amount": str(self.opening_amount),
            "opening_date": self.opening_date,
            "closing_amount": str(self.closing_amount),
            "closing_date": self.closing_date,
            "opening_page": self.opening_page, "closing_page": self.closing_page,
            "transactions": [t.to_dict() for t in self.transactions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StatementFacts":
        return cls(
            doc_id=d["doc_id"], doc_type=d["doc_type"],
            doc_type_confidence=d.get("doc_type_confidence", 0.0),
            account_ref=d.get("account_ref", ""), currency=d["currency"],
            opening_amount=Decimal(d["opening_amount"]),
            opening_date=d["opening_date"],
            closing_amount=Decimal(d["closing_amount"]),
            closing_date=d["closing_date"],
            transactions=[TxnFact.from_dict(t) for t in d.get("transactions", [])],
            opening_page=d.get("opening_page"), closing_page=d.get("closing_page"))


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
    n = parse_date(str(raw), locale)
    if not n.ok:
        return None, f"date {raw!r}: {n.status} ({n.reason})"
    return n.value, None


def _txn_date(raw, locale: str, open_iso: str, close_iso: str
              ) -> tuple[str | None, str | None]:
    """A transaction date, whose year may be absent (statements print "04/17").
    The year is taken from the statement period, handling a year boundary
    (a December→January statement)."""
    n = parse_date(str(raw), locale)          # the model may have included a year
    if n.ok:
        return n.value, None
    oy, om = int(open_iso[:4]), int(open_iso[5:7])
    cy, cm = int(close_iso[:4]), int(close_iso[5:7])
    n = parse_date(str(raw), locale, default_year=oy)
    if not n.ok:
        return None, f"date {raw!r}: {n.status} ({n.reason})"
    # If the period crosses a year boundary, months before the opening month
    # belong to the closing year.
    if oy != cy and int(n.value[5:7]) < om:
        n = parse_date(str(raw), locale, default_year=cy)
    return n.value, None


def from_model_json(text: str, doc_id: str, locale: str,
                    currency: str) -> tuple[StatementFacts | None, str | None]:
    """Parse a model's statement read into canonical StatementFacts.

    Returns (facts, error). Any ambiguous/invalid figure fails the whole parse:
    a statement we cannot read to the cent is sent to review, never guessed."""
    blob = _find_json(text)
    if blob is None:
        return None, "no JSON object found in model output"
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        return None, f"JSON did not parse: {e}"
    if not isinstance(data, dict):
        return None, "top-level JSON is not an object"

    for section in ("opening", "closing"):
        if not isinstance(data.get(section), dict):
            return None, f"missing '{section}' object"
    if not isinstance(data.get("transactions"), list):
        return None, "missing 'transactions' array"

    open_amt, err = _amount(data["opening"].get("amount_raw"), locale, currency)
    if err:
        return None, f"opening {err}"
    open_date, err = _date(data["opening"].get("date_raw"), locale)
    if err:
        return None, f"opening {err}"
    close_amt, err = _amount(data["closing"].get("amount_raw"), locale, currency)
    if err:
        return None, f"closing {err}"
    close_date, err = _date(data["closing"].get("date_raw"), locale)
    if err:
        return None, f"closing {err}"

    txns: list[TxnFact] = []
    for i, rt in enumerate(data["transactions"]):
        if not isinstance(rt, dict):
            return None, f"transaction {i} is not an object"
        mag, err = _amount(rt.get("amount_raw"), locale, currency)
        if err:
            return None, f"transaction {i} {err}"
        d, err = _txn_date(rt.get("date_raw"), locale, open_date, close_date)
        if err:
            return None, f"transaction {i} {err}"
        direction = str(rt.get("direction", "")).strip().lower()
        if direction not in ("credit", "debit"):
            return None, (f"transaction {i}: direction must be 'credit' or "
                          f"'debit', got {direction!r}")
        # amount_raw is a positive magnitude; direction gives the sign.
        signed = abs(mag) if direction == "credit" else -abs(mag)
        # Running balance is an *aid* (a second identity for diagnosis), not core:
        # if it's present but unreadable, degrade it to None rather than failing
        # the whole statement over a column we only use to localize errors.
        running = None
        if rt.get("running_balance_raw") not in (None, ""):
            rb, rberr = _amount(rt["running_balance_raw"], locale, currency)
            running = rb if rberr is None else None
        txns.append(TxnFact(date=d, description=str(rt.get("description", "")),
                            amount=signed, page=rt.get("page"),
                            running_balance=running))

    facts = StatementFacts(
        doc_id=doc_id,
        doc_type=str(data.get("doc_type", "unknown")).strip().lower(),
        doc_type_confidence=float(data.get("doc_type_confidence", 0.0) or 0.0),
        account_ref=str(data.get("account_ref", "")),
        currency=currency.upper(),
        opening_amount=open_amt, opening_date=open_date,
        closing_amount=close_amt, closing_date=close_date,
        transactions=txns,
        opening_page=data["opening"].get("page"),
        closing_page=data["closing"].get("page"),
    )
    return facts, None
