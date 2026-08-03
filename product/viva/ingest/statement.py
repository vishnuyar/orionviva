"""StatementFacts — the structured read of one balance-family statement.

Turns a model's loosely-shaped JSON into typed, canonical facts through the
shared deterministic normalizers (``parse_amount`` / ``parse_date``), so:

  - amounts and dates are exact (Decimal, ISO), never floats;
  - a genuinely ambiguous figure ("1.234", "03/04/2025") comes back as a refusal
    to build the facts rather than a guess, and the statement goes to review.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal

from vivacore.verify.normalize import parse_amount, parse_date

from ..ledger.events import Provenance


@dataclass(frozen=True)
class TxnFact:
    date: str            # ISO yyyy-mm-dd (value time)
    description: str
    amount: Decimal      # signed by effect on printed balance: + raises it, - lowers it
    page: int | None = None
    running_balance: Decimal | None = None   # the printed balance after this line
    # A leg supplied by cross-document corroboration sets these: its source is
    # the counterparty document rather than this statement, and its grade is
    # `corroborated`. Empty means an ordinary line read from this statement.
    source_doc_id: str = ""
    grade: str = ""
    note: str = ""

    def provenance(self, doc_id: str) -> Provenance:
        return Provenance(doc_id=self.source_doc_id or doc_id, page=self.page,
                          note=self.note)

    def to_dict(self) -> dict:
        return {"date": self.date, "description": self.description,
                "amount": str(self.amount), "page": self.page,
                "running_balance": (None if self.running_balance is None
                                    else str(self.running_balance)),
                "source_doc_id": self.source_doc_id, "grade": self.grade,
                "note": self.note}

    @classmethod
    def from_dict(cls, d: dict) -> "TxnFact":
        rb = d.get("running_balance")
        return cls(date=d["date"], description=d.get("description", ""),
                   amount=Decimal(d["amount"]), page=d.get("page"),
                   running_balance=(None if rb is None else Decimal(rb)),
                   source_doc_id=d.get("source_doc_id", ""),
                   grade=d.get("grade", ""), note=d.get("note", ""))


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
    # Identity signals, extracted separately so account identity anchors to the
    # stable number rather than a free-text label. `account_names` is a list
    # because a joint account has two.
    account_number: str = ""
    institution: str = ""
    account_names: list[str] = field(default_factory=list)

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
            "account_number": self.account_number,
            "institution": self.institution,
            "account_names": list(self.account_names),
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
            opening_page=d.get("opening_page"), closing_page=d.get("closing_page"),
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


def _date(raw, locale: str) -> tuple[str | None, str | None]:
    n = parse_date(str(raw), locale)
    if not n.ok:
        return None, f"date {raw!r}: {n.status} ({n.reason})"
    return n.value, None


def period_date(raw, locale: str, period_end: str,
                ) -> tuple[str | None, str | None]:
    """Resolve a printed date that may omit its year, given only the period END.

    The close-only variant of ``_txn_date``, for a document that states a single
    as-of date rather than a period. Uses the period-end year, and the year
    before it when that would land after the period end. Returns
    ``(iso, None)``, or ``(None, error)`` when the date is unreadable or has no
    year and there is no period to infer one from."""
    n = parse_date(str(raw), locale)              # the model may have included one
    if n.ok:
        return n.value, None
    if not period_end:
        return None, f"date {raw!r}: no year printed and no statement period to infer it from"
    year = int(period_end[:4])
    n = parse_date(str(raw), locale, default_year=year)
    if not n.ok:
        return None, f"date {raw!r}: {n.status} ({n.reason})"
    if n.value > period_end:
        n = parse_date(str(raw), locale, default_year=year - 1)
        if not n.ok:
            return None, f"date {raw!r}: {n.status} ({n.reason})"
    return n.value, None


def _signed_amount(rt: dict, mag: Decimal, i: int
                   ) -> tuple[Decimal | None, str | None]:
    """Sign a transaction's positive magnitude by its effect on the printed
    balance.

    Prefers ``balance_effect`` (increase/decrease) and falls back to
    ``direction`` (credit=increase, debit=decrease), so a read stored under the
    older shape reparses unchanged. Returns (signed, error)."""
    effect = str(rt.get("balance_effect", "")).strip().lower()
    if effect in ("increase", "decrease"):
        return (mag if effect == "increase" else -mag), None
    direction = str(rt.get("direction", "")).strip().lower()   # legacy stmt-v2
    if direction in ("credit", "debit"):
        return (mag if direction == "credit" else -mag), None
    return None, (f"transaction {i}: balance_effect must be 'increase' or "
                  f"'decrease' (got {effect!r})")


def _txn_date(raw, locale: str, open_iso: str, close_iso: str
              ) -> tuple[str | None, str | None]:
    """A transaction date whose year may be absent (statements print "04/17").

    The year is taken from the statement period, and from the closing year for a
    month before the opening month when the period crosses a year boundary."""
    n = parse_date(str(raw), locale)          # the model may have included a year
    if n.ok:
        return n.value, None
    oy, om = int(open_iso[:4]), int(open_iso[5:7])
    cy = int(close_iso[:4])
    n = parse_date(str(raw), locale, default_year=oy)
    if not n.ok:
        return None, f"date {raw!r}: {n.status} ({n.reason})"
    # If the period crosses a year boundary, months before the opening month
    # belong to the closing year.
    if oy != cy and int(n.value[5:7]) < om:
        n = parse_date(str(raw), locale, default_year=cy)
    return n.value, None


def period_from_model_json(text: str, locale: str, currency: str):
    """The two figures that bound a statement, and nothing else.

    Returns `((opening_amount, opening_date), (closing_amount, closing_date))`,
    or None when either box is unreadable. A caller that needs only the period
    a statement declares reads it this way rather than through the full parse:
    the transactions are irrelevant to it, and a defect among them would
    otherwise take the period down with it."""
    blob = _find_json(text)
    if blob is None:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    ends = []
    for section in ("opening", "closing"):
        box = data.get(section)
        if not isinstance(box, dict):
            return None
        amount, err = _amount(box.get("amount_raw"), locale, currency)
        if err:
            return None
        when, err = _date(box.get("date_raw"), locale)
        if err:
            return None
        ends.append((amount, when))
    return tuple(ends)


def from_model_json(text: str, doc_id: str, locale: str,
                    currency: str) -> tuple[StatementFacts | None, str | None]:
    """Parse a model's statement read into canonical StatementFacts.

    Returns (facts, error). Any ambiguous or invalid figure fails the whole
    parse, sending the statement to review. An unreadable running balance is the
    exception: it degrades to None, since it only aids diagnosis."""
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
        # amount_raw is a positive magnitude; the sign is the movement's effect
        # on the printed balance. Account-kind-agnostic, so one identity
        # reconciles checking, savings and cards alike.
        signed, err = _signed_amount(rt, abs(mag), i)
        if err:
            return None, err
        # The running balance is a diagnosis aid, not part of the identity: if
        # it is present but unreadable it degrades to None rather than failing
        # the parse.
        running = None
        if rt.get("running_balance_raw") not in (None, ""):
            rb, rberr = _amount(rt["running_balance_raw"], locale, currency)
            running = rb if rberr is None else None
        txns.append(TxnFact(date=d, description=str(rt.get("description", "")),
                            amount=signed, page=rt.get("page"),
                            running_balance=running))

    raw_names = data.get("account_names")
    if isinstance(raw_names, list):
        names = [str(n).strip() for n in raw_names if str(n).strip()]
    elif raw_names:
        names = [str(raw_names).strip()]
    else:
        names = []

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
        account_number=str(data.get("account_number", "")),
        institution=str(data.get("institution", "")),
        account_names=names,
    )
    return facts, None
