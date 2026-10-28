"""Sourced mortgage allocations are monetary components, never rounded shares."""
from __future__ import annotations

from dataclasses import dataclass

from . import instrument_contracts as c
from ..ledger.events import Event, Provenance
from ..ledger.instruments import decode, encode


@dataclass(frozen=True)
class PaymentAllocation(c.ClosedFact):
    movement_key: str
    loan_account: str
    escrow_account: str
    payment: c.PaymentComponents
    bank_source: c.Source

    def __post_init__(self):
        super().__post_init__()
        if not self.movement_key.strip() or not self.loan_account.strip():
            raise c.ContractError("allocation needs canonical movement and loan identities")
        if c.check_payment(self.payment).disposition != c.Disposition.ACCEPTED:
            raise c.ContractError("allocation requires every reconciled printed payment component")
        if self.payment.total.value <= 0:
            raise c.ContractError("allocation requires a positive cash payment")
        if self.payment.escrow.value and not self.escrow_account.strip():
            raise c.ContractError("escrow allocation requires a canonical escrow identity")

    @property
    def component_names(self):
        return ("principal", "interest", "escrow", "fees")

    @property
    def spending(self):
        return self.payment.interest.value + self.payment.fees.value


def allocation_event(allocation):
    if type(allocation) is not PaymentAllocation:
        raise c.ContractError("typed mortgage allocation required")
    source = allocation.payment.reference.source
    return Event("InstrumentPaymentAllocated", allocation.payment.dated.value,
                 {"allocation": encode(allocation)}, Provenance(source.doc_id, source.page))


def allocation_from_event(event):
    if set(event.body) - {"allocation", "instrument_observation_id", "instrument_effect_key"}:
        raise c.ContractError("unknown allocation event fields")
    allocation = decode(event.body.get("allocation"), PaymentAllocation)
    if (event.occurred_at != allocation.payment.dated.value
            or event.provenance.doc_id != allocation.payment.reference.source.doc_id
            or event.provenance.page != allocation.payment.reference.source.page):
        raise c.ContractError("allocation event source envelope mismatch")
    return allocation


@dataclass(frozen=True)
class InstrumentComponentState(c.ClosedFact):
    observation_id: str
    doc_id: str
    components: tuple[c.ComponentResult, ...]
    source: c.Source
    effective: c.SourcedDate

    def __post_init__(self):
        super().__post_init__()
        if not self.observation_id.strip() or self.doc_id != self.source.doc_id:
            raise c.ContractError("component state needs its source observation")


def component_state_event(state):
    if type(state) is not InstrumentComponentState:
        raise c.ContractError("typed component dispositions required")
    return Event("InstrumentComponentStateRecorded", state.effective.value,
        {"state": encode(state)}, Provenance(state.source.doc_id, state.source.page))


def component_state_from_event(event):
    if set(event.body) - {"state", "instrument_observation_id", "instrument_effect_key"}:
        raise c.ContractError("unknown instrument component-state fields")
    state = decode(event.body.get("state"), InstrumentComponentState)
    if event.provenance.doc_id != state.source.doc_id or event.provenance.page != state.source.page:
        raise c.ContractError("component-state source envelope mismatch")
    return state
