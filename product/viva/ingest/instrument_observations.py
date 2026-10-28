"""Proposed closed observation envelopes; not registered ledger events yet.

Slice A supplies validation only. A future append boundary must validate a
transition atomically against its actual current observation, never a cache.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from . import instrument_contracts as c
from .apr_context_contracts import AprContextPayload
from .instrument_parser import decode, load_json, _object


class ObservationKind(str, Enum):
    APR_CONTEXT = "apr_context_v1"
    DEPOSIT_TERMS = "deposit_terms"
    MORTGAGE_TERMS = "mortgage_terms"
    AVAILABILITY = "availability"
    DEPOSIT_COMPONENTS = "deposit_components"
    MORTGAGE_COMPONENTS = "mortgage_components"
    REFINANCE = "refinance"
    TAX_RECEIPT = "tax_receipt"
    POSITION_CLASSIFICATION = "position_classification"


PAYLOADS = {
    ObservationKind.APR_CONTEXT: AprContextPayload,
    ObservationKind.DEPOSIT_TERMS: c.DepositTerms,
    ObservationKind.MORTGAGE_TERMS: c.MortgageTerms,
    ObservationKind.AVAILABILITY: c.Availability,
    ObservationKind.DEPOSIT_COMPONENTS: c.DepositFacts,
    ObservationKind.MORTGAGE_COMPONENTS: c.MortgageFacts,
    ObservationKind.REFINANCE: c.RefinanceFacts,
    ObservationKind.TAX_RECEIPT: c.TaxReceiptFacts,
    ObservationKind.POSITION_CLASSIFICATION: c.PositionClassification,
}


class Operation(str, Enum):
    CREATE = "create"
    CORRECT = "correct"
    RETRACT = "retract"


@dataclass(frozen=True)
class ObservationChange(c.ClosedFact):
    observation_id: str
    subject_id: str
    kind: ObservationKind
    effective: c.SourcedDate
    operation: Operation
    source: c.Source
    payload: (c.DepositTerms | c.MortgageTerms | c.Availability | c.DepositFacts |
              c.MortgageFacts | c.RefinanceFacts | c.TaxReceiptFacts |
              c.PositionClassification | AprContextPayload | None)
    prior_id: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if (type(self.schema_version) is not int or self.schema_version != 1
                or not isinstance(self.observation_id, str) or not self.observation_id.strip()
                or not isinstance(self.subject_id, str) or not self.subject_id.strip()
                or not isinstance(self.kind, ObservationKind)
                or not isinstance(self.operation, Operation)
                or not isinstance(self.source, c.Source)
                or not isinstance(self.effective, c.SourcedDate)):
            raise c.ContractError("invalid observation envelope")
        if self.operation == Operation.CREATE:
            if self.prior_id is not None:
                raise c.ContractError("create has no prior observation")
        elif not isinstance(self.prior_id, str) or not self.prior_id.strip():
            raise c.ContractError("correction and retraction require prior ID")
        if self.operation == Operation.RETRACT:
            if self.payload is not None:
                raise c.ContractError("retraction has no replacement payload")
            if self.kind == ObservationKind.AVAILABILITY:
                raise c.ContractError("instrument restrictions cannot be retracted into availability")
        elif type(self.payload) is not PAYLOADS[self.kind]:
            raise c.ContractError("observation payload has wrong closed type")


def validate_transition(change: ObservationChange, current: ObservationChange | None):
    """Validate one stream frontier; retaining history is the append owner's job."""
    if change.operation == Operation.CREATE:
        if current is not None:
            raise c.ContractError("observation stream already exists")
    else:
        if (current is None or current.operation == Operation.RETRACT
                or change.prior_id != current.observation_id
                or change.observation_id == current.observation_id
                or change.subject_id != current.subject_id or change.kind != current.kind):
            raise c.ContractError("stale, forked or incompatible observation transition")
        if change.kind == ObservationKind.AVAILABILITY and change.payload.family != current.payload.family:
            raise c.ContractError("correction cannot release an instrument restriction")
    return change


def parse_observation_json(text, doc_id, locale="en-US", currency="USD"):
    data = load_json(text)
    names = {"observation_id", "subject_id", "kind", "effective", "operation", "source", "payload", "prior_id", "schema_version"}
    _object(data, names, names - {"prior_id", "schema_version"})
    try:
        kind = ObservationKind(data["kind"])
        operation = Operation(data["operation"])
    except (ValueError, TypeError):
        raise c.ContractError("unknown observation kind or operation") from None
    if kind == ObservationKind.APR_CONTEXT:
        raise c.ContractError("APR context proposals require measured source grounding")
    context = {"doc_id": doc_id, "locale": locale, "currency": currency}
    payload = None if data["payload"] is None else decode(data["payload"], PAYLOADS[kind], **context)
    prior = data.get("prior_id")
    if prior is not None:
        prior = decode(prior, str, **context)
    return ObservationChange(
        decode(data["observation_id"], str, **context), decode(data["subject_id"], str, **context), kind,
        decode(data["effective"], c.SourcedDate, **context), operation,
        decode(data["source"], c.Source, **context), payload, prior,
        decode(data.get("schema_version", 1), int, **context))
