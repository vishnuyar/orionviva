"""Normalize closed instrument JSON into source-bound immutable facts.

Scalar source fields are {"raw": <printed text>, "page": <positive integer>}.
Document identity and currency come from the caller, never from model JSON.
"""
from __future__ import annotations

import json
import types
from dataclasses import MISSING, dataclass, fields, is_dataclass
from enum import Enum
from typing import Union, get_args, get_origin

from vivacore.verify.normalize import parse_amount, parse_date
from . import instrument_contracts as c

MAX_ROWS = 1000
MAX_TEXT = 2_000_000
FAMILIES = {
    "term_deposit_statement": c.DepositFacts,
    "mortgage_statement": c.MortgageFacts,
    "refinance_settlement": c.RefinanceFacts,
    "property_tax_receipt": c.TaxReceiptFacts,
    "position_classification": c.PositionClassification,
}


def _object(value, allowed, required):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise c.ContractError("object has missing or unknown fields")


def _printed(value, doc_id):
    _object(value, {"raw", "page"}, {"raw", "page"})
    if not isinstance(value["raw"], str) or not value["raw"].strip():
        raise c.ContractError("printed scalar must be nonempty text")
    return value["raw"], c.Source(doc_id, value["page"])


def decode(value, target, *, doc_id, locale, currency, source_contract=None, page_count=None):
    """Decode only declared dataclasses/enums; reject JSON coercions and extras."""
    origin, args = get_origin(target), get_args(target)
    if origin in (Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        choices = [t for t in args if t is not type(None)]
        if len(choices) != 1:
            raise c.ContractError("ambiguous union is not a source contract")
        return decode(value, choices[0], doc_id=doc_id, locale=locale, currency=currency,
                      source_contract=source_contract, page_count=page_count)
    if origin is tuple:
        if not isinstance(value, list) or len(value) > MAX_ROWS:
            raise c.ContractError("source rows must be a bounded JSON array")
        return tuple(decode(v, args[0], doc_id=doc_id, locale=locale, currency=currency,
                      source_contract=source_contract, page_count=page_count) for v in value)
    if target is c.Source:
        _object(value, {"page"}, {"page"})
        return c.Source(doc_id, value["page"])
    if target in (c.Money, c.SourcedDate, c.SourcedText, c.Rate):
        raw, source = _printed(value, doc_id)
        if target is c.SourcedText:
            return c.SourcedText(raw, source)
        if target is c.SourcedDate:
            normalized = parse_date(raw, locale)
            if not normalized.ok:
                raise c.ContractError("invalid or ambiguous printed date")
            return c.SourcedDate(normalized.value, source)
        text = raw[:-1].strip() if target is c.Rate and raw.endswith('%') else raw
        normalized = parse_amount(text, locale, currency)
        if not normalized.ok:
            raise c.ContractError("invalid or ambiguous printed amount")
        number = normalized.decimal()
        return c.Rate(number, source) if target is c.Rate else c.Money(number, currency, source)
    if isinstance(target, type) and issubclass(target, Enum):
        if not isinstance(value, str):
            raise c.ContractError("enum must be text")
        try:
            return target(value)
        except ValueError:
            raise c.ContractError("unknown source enum value") from None
    if target in (str, int, bool):
        if type(value) is not target:
            raise c.ContractError("scalar has the wrong JSON type")
        if target is str and not value.strip():
            raise c.ContractError("identity text cannot be blank")
        return value
    if target is c.PrincipalMovement and source_contract is not None:
        if isinstance(value, dict) and set(value) & {'signed_effect', 'effect_basis', 'kind_source'}:
            return _signed_principal(value, doc_id, locale, currency, page_count).lower()
    if is_dataclass(target):
        fs, hints = c._closed_fields(target)
        required = {f.name for f in fs if f.default is MISSING and f.default_factory is MISSING}
        _object(value, {f.name for f in fs}, required)
        kwargs = {key: decode(item, hints[key], doc_id=doc_id, locale=locale, currency=currency,
                      source_contract=source_contract, page_count=page_count)
                  for key, item in value.items()}
        return target(**kwargs)
    raise c.ContractError("unsupported source contract")



@dataclass(frozen=True)
class SignedPrincipalSource(c.ClosedFact):
    """One explicit source convention, retained verbatim in the read claim."""
    signed_raw: str
    signed_effect: c.Money
    effect_basis: str
    kind: c.PrincipalKind
    kind_source: c.Source
    dated: c.SourcedDate | None
    reference: c.SourcedText | None

    def lower(self):
        effect = self.signed_effect.value
        if self.effect_basis != 'principal_balance_effect-v1':
            raise c.ContractError('unsupported mortgage principal effect basis')
        if not effect.is_finite() or effect == 0:
            raise c.ContractError('signed principal effect must be finite and nonzero')
        decreases = {c.PrincipalKind.REDUCTION, c.PrincipalKind.PAYOFF,
                     c.PrincipalKind.DECREASE_ADJUSTMENT}
        increases = {c.PrincipalKind.ADVANCE, c.PrincipalKind.INCREASE_ADJUSTMENT}
        if not ((effect < 0 and self.kind in decreases) or
                (effect > 0 and self.kind in increases)):
            raise c.ContractError('signed principal effect contradicts explicit kind')
        magnitude = effect.copy_negate() if effect < 0 else effect
        return c.PrincipalMovement(self.kind,
            c.Money(magnitude, self.signed_effect.currency, self.signed_effect.source),
            self.dated, self.reference)


def _signed_principal(value, doc_id, locale, currency, page_count):
    required = {'signed_effect', 'effect_basis', 'kind', 'kind_source'}
    _object(value, required | {'dated', 'reference'}, required)
    raw, source = _printed(value['signed_effect'], doc_id)
    normalized = parse_amount(raw, locale, currency)
    if not normalized.ok:
        raise c.ContractError('invalid or ambiguous printed signed principal effect')
    kind = decode(value['kind'], c.PrincipalKind, doc_id=doc_id, locale=locale, currency=currency)
    kind_source = decode(value['kind_source'], c.Source, doc_id=doc_id, locale=locale, currency=currency)
    if page_count is not None:
        if type(page_count) is not int or page_count < 1:
            raise c.ContractError('rendered source page count must be positive')
        if source.page > page_count or kind_source.page > page_count:
            raise c.ContractError('source evidence is outside the captured document')
    basis = value['effect_basis']
    if type(basis) is not str:
        raise c.ContractError('unsupported mortgage principal effect basis')
    dated = decode(value.get('dated'), c.SourcedDate | None,
                   doc_id=doc_id, locale=locale, currency=currency)
    reference = decode(value.get('reference'), c.SourcedText | None,
                       doc_id=doc_id, locale=locale, currency=currency)
    return SignedPrincipalSource(raw, c.Money(normalized.decimal(), currency, source),
                                 basis, kind, kind_source, dated, reference)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise c.ContractError("duplicate JSON field")
        value[key] = item
    return value


def load_json(text):
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise c.ContractError("source JSON exceeds its bound")
    try:
        return json.loads(text, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(c.ContractError("nonfinite JSON number")))
    except (json.JSONDecodeError, RecursionError):
        raise c.ContractError("invalid source JSON") from None


def parse_instrument_json(text, kind, doc_id, locale="en-US", currency="USD",
                          *, source_contract=None, page_count=None):
    """Return a typed proposal only; reconciliation and posting are separate."""
    if kind not in FAMILIES:
        raise c.ContractError("unsupported instrument document family")
    if source_contract is not None and (kind != "mortgage_statement" or
            source_contract != "mortgage-principal-source-v2"):
        raise c.ContractError("unsupported instrument source contract")
    c.Source(doc_id, 1)
    if not isinstance(currency, str) or not currency.strip():
        raise c.ContractError("explicit source currency required")
    try:
        facts = decode(load_json(text), FAMILIES[kind], doc_id=doc_id, locale=locale, currency=currency,
                      source_contract=source_contract, page_count=page_count)
    except RecursionError:
        raise c.ContractError("source JSON nesting exceeds its bound") from None
    return facts
