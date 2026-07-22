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

    def provenance(self, doc_id: str) -> Provenance:
        return Provenance(doc_id=doc_id, page=self.page)


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
        d, err = _date(rt.get("date_raw"), locale)
        if err:
            return None, f"transaction {i} {err}"
        direction = str(rt.get("direction", "")).strip().lower()
        if direction not in ("credit", "debit"):
            return None, (f"transaction {i}: direction must be 'credit' or "
                          f"'debit', got {direction!r}")
        # amount_raw is a positive magnitude; direction gives the sign.
        signed = abs(mag) if direction == "credit" else -abs(mag)
        txns.append(TxnFact(date=d, description=str(rt.get("description", "")),
                            amount=signed, page=rt.get("page")))

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
