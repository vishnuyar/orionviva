"""Immutable source proposals at the existing instrument reader boundary."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import math

from . import instrument_contracts as c
from .instrument_parser import parse_instrument_json

FAMILIES = {
    "term_deposit_statement": c.DepositFacts,
    "mortgage_statement": c.MortgageFacts,
    "refinance_settlement": c.RefinanceFacts,
    "property_tax_receipt": c.TaxReceiptFacts,
}


def validate_sources(value, doc_id: str, page_count: int | None = None):
    """Source identity comes from capture; a rendered page bounds its evidence."""
    if page_count is not None and (type(page_count) is not int or page_count < 1):
        raise c.ContractError("rendered source page count must be positive")
    if isinstance(value, c.Source):
        if value.doc_id != doc_id or (page_count is not None and value.page > page_count):
            raise c.ContractError("source evidence is outside the captured document")
    elif is_dataclass(value):
        for field in fields(value):
            validate_sources(getattr(value, field.name), doc_id, page_count)
    elif type(value) in (tuple, list):
        for item in value:
            validate_sources(item, doc_id, page_count)


@dataclass(frozen=True)
class InstrumentReadFacts(c.ClosedFact):
    doc_id: str
    doc_type: str
    doc_type_confidence: float | None
    payload: c.DepositFacts | c.MortgageFacts | c.RefinanceFacts | c.TaxReceiptFacts
    currency: str
    acquisition: dict | None = None

    def __post_init__(self):
        super().__post_init__()
        from ..acquisition import classification
        classification(self.doc_id, self.doc_type_confidence, self.acquisition)
        if (not self.doc_id.strip() or not self.currency.strip()
                or self.doc_type not in FAMILIES or type(self.payload) is not FAMILIES[self.doc_type]
                or (self.doc_type_confidence is not None and
                    (not math.isfinite(self.doc_type_confidence)
                     or not 0 <= self.doc_type_confidence <= 1))):
            raise c.ContractError("invalid instrument reader metadata")
        validate_sources(self.payload, self.doc_id)
        def check_currency(value):
            if isinstance(value, c.Money) and value.currency != self.currency:
                raise c.ContractError("instrument money has incompatible source currency")
            if is_dataclass(value):
                for field in fields(value):
                    check_currency(getattr(value, field.name))
            elif type(value) in (tuple, list):
                for item in value:
                    check_currency(item)
        check_currency(self.payload)

    @property
    def period_end(self):
        dated = getattr(self.payload, "end", None) or getattr(self.payload, "dated", None)
        terms = getattr(self.payload, "terms", None)
        dated = dated or (getattr(terms, "opened", None) if terms is not None else None)
        return dated.value if dated is not None else ""

    def to_dict(self):
        from ..ledger.instruments import encode
        return {"doc_id": self.doc_id, "doc_type": self.doc_type,
                "doc_type_confidence": self.doc_type_confidence,
                "currency": self.currency, "instrument_facts": encode(self.payload),
                **({"acquisition": dict(self.acquisition)} if self.acquisition is not None else {})}

    @classmethod
    def from_dict(cls, value):
        from ..ledger.instruments import decode
        names = {"doc_id", "doc_type", "doc_type_confidence", "currency", "instrument_facts"}
        if not isinstance(value, dict) or (set(value) != names and set(value) != names | {"acquisition"}) or type(value.get("doc_type")) is not str or value["doc_type"] not in FAMILIES:
            raise c.ContractError("stored instrument wrapper has missing or unknown fields")
        payload = decode(value["instrument_facts"], FAMILIES[value["doc_type"]])
        return cls(value["doc_id"], value["doc_type"], value["doc_type_confidence"], payload, value["currency"], value.get("acquisition"))


def parser_for(doc_type: str, *, source_contract=None, page_count=None):
    """Bind classification to the closed payload; the model cannot change it."""
    if type(doc_type) is not str or doc_type not in FAMILIES:
        raise c.ContractError("unsupported instrument document family")
    def parse(text, doc_id, locale, currency):
        try:
            payload = parse_instrument_json(text, doc_type, doc_id, locale, currency,
                                            source_contract=source_contract, page_count=page_count)
            return InstrumentReadFacts(doc_id, doc_type, 0.0, payload, currency), None
        except (c.ContractError, ValueError, TypeError, KeyError) as error:
            return None, str(error)
    return parse
