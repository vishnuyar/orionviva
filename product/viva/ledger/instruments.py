"""Closed instrument observations, source restrictions and revision visibility.

The append-only source remains canonical. Superseded document interpretations
stop contributing derived effects; family declarations remain fail-closed.
"""
from __future__ import annotations

import types
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Union, get_args, get_origin, get_type_hints

from .events import Event, Provenance


@dataclass(frozen=True)
class AccountRestriction:
    family: str
    restriction: str
    status: str
    record_ids: tuple[str, ...]
    doc_ids: tuple[str, ...]
    effective: str

    def __post_init__(self):
        if (any(type(value) is not str for value in (self.family, self.restriction, self.status))
                or self.family not in {"term_deposit", "escrow"}
                or self.restriction not in {"", "restricted_term_deposit", "restricted_escrow"}
                or self.status not in {"accepted", "missing", "conflicted"}
                or type(self.record_ids) is not tuple or type(self.doc_ids) is not tuple
                or any(type(v) is not str or not v for v in (*self.record_ids, *self.doc_ids))
                or type(self.effective) is not str):
            raise ValueError("invalid closed account restriction")


def encode(value):
    """Canonical storage data from a typed value, never a model JSON bag."""
    if is_dataclass(value):
        return {field.name: encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite instrument value")
        return str(value)
    if type(value) is tuple:
        return [encode(item) for item in value]
    if value is None or type(value) in {str, int, bool}:
        return value
    raise ValueError("value is outside the instrument storage contract")


def decode(value, target):
    """Closed typed-storage decoder; model proposals use instrument_parser."""
    from ..ingest.instrument_contracts import ContractError
    origin, args = get_origin(target), get_args(target)
    if origin in (Union, types.UnionType):
        options = [option for option in args if (value is None) == (option is type(None))]
        if value is None and type(None) in options:
            return None
        if len(options) != 1:
            raise ContractError("ambiguous storage union")
        return decode(value, options[0])
    if origin is tuple:
        if type(value) is not list or len(value) > 1000:
            raise ContractError("invalid stored instrument rows")
        return tuple(decode(item, args[0]) for item in value)
    if target is Decimal:
        if type(value) is not str:
            raise ContractError("stored Decimal must be text")
        try:
            result = Decimal(value)
        except Exception:
            raise ContractError("invalid stored Decimal") from None
        if not result.is_finite():
            raise ContractError("stored Decimal must be finite")
        return result
    if isinstance(target, type) and issubclass(target, Enum):
        if type(value) is not str:
            raise ContractError("invalid stored enum")
        try:
            return target(value)
        except ValueError:
            raise ContractError("unknown stored enum") from None
    if is_dataclass(target):
        fs, hints = fields(target), get_type_hints(target)
        if type(value) is not dict or set(value) != {field.name for field in fs}:
            raise ContractError("stored object has missing or extra fields")
        return target(**{name: decode(item, hints[name]) for name, item in value.items()})
    if type(value) is not target:
        raise ContractError("stored scalar has the wrong type")
    return value


def encode_change(change):
    from ..ingest.instrument_observations import ObservationChange
    if type(change) is not ObservationChange:
        raise ValueError("typed observation change required")
    return encode(change)


def decode_change(value):
    from ..ingest.instrument_observations import ObservationChange, ObservationKind, PAYLOADS
    from ..ingest.instrument_contracts import ContractError
    if type(value) is not dict:
        raise ContractError("stored observation must be an object")
    expected = {field.name for field in fields(ObservationChange)}
    if set(value) != expected:
        raise ContractError("stored observation has missing or unknown fields")
    try:
        kind = ObservationKind(value["kind"])
    except (ValueError, TypeError):
        raise ContractError("unknown stored observation kind") from None
    hints = get_type_hints(ObservationChange)
    kwargs = {name: decode(item, hints[name]) for name, item in value.items() if name != "payload"}
    kwargs["payload"] = None if value["payload"] is None else decode(value["payload"], PAYLOADS[kind])
    return ObservationChange(**kwargs)


def observation_event(change):
    return Event("InstrumentObservationRecorded", change.effective.value,
        {"record": encode_change(change)},
        Provenance(change.source.doc_id, change.source.page))


def family_event(account_id, family, dated, source):
    from ..ingest.instrument_contracts import Source
    if (type(account_id) is not str or not account_id.strip()
            or family not in {"term_deposit", "escrow"} or type(source) is not Source):
        raise ValueError("explicit sourced instrument family required")
    from ..ingest.instrument_contracts import SourcedDate
    SourcedDate(dated, source)
    return Event("InstrumentFamilyDeclared", dated,
                 {"account_id": account_id, "family": family}, Provenance(source.doc_id, source.page))


def fold_change(history, event):
    from ..ingest.instrument_observations import Operation, validate_transition
    change = decode_change(event.body.get("record"))
    if (event.provenance.doc_id != change.source.doc_id or event.provenance.page != change.source.page
            or event.occurred_at != change.effective.value or set(event.body) != {"record"}):
        raise ValueError("observation source envelope mismatch")
    if change.observation_id in history:
        raise ValueError("observation IDs cannot be reused")
    if change.operation == Operation.CREATE:
        validate_transition(change, None)
    else:
        prior = history.get(change.prior_id)
        if prior is None or prior["superseded"]:
            raise ValueError("observation correction is not at its live frontier")
        validate_transition(change, prior["change"])
        prior["superseded"] = True
    history[change.observation_id] = {"change": change, "event_id": event.event_id, "superseded": False}
    return change


def current_observations(history):
    from ..ingest.instrument_observations import Operation
    return {key: value for key, value in history.items()
            if not value["superseded"] and value["change"].operation != Operation.RETRACT}


def visible_events(events, as_of=None):
    """As-of is value time over current knowledge; retired interpretations stay retired."""
    events = tuple(events)
    history = {}
    for event in events:
        if event.event_type == "InstrumentObservationRecorded":
            fold_change(history, event)
    active = current_observations(history)
    reads={event.body.get('doc_id'):event for event in events if event.event_type=='ReadRecorded'
        and event.body.get('phase','extract')=='extract'}
    cash={event.event_id:event for event in events if event.event_type=='TransactionRecorded'}
    for event in events:
        if event.event_type=='InstrumentKnownPaymentAllocated':
            from ..ingest.mortgage_known_allocation import known_allocation_from_event, body_digest, source_conflicted
            allocation=known_allocation_from_event(event)
            receipt=allocation.receipt
            reading=reads.get(allocation.payment.reference.source.doc_id)
            movement=cash.get(receipt.cash_event_id)
            if source_conflicted(receipt,history,reads):
                continue
            if (reading is None or reading.event_id!=receipt.source_read_event_id or body_digest(reading.body)!=receipt.source_read_digest
                    or movement is None or body_digest(movement.body)!=receipt.cash_body_digest):
                continue
        origin = event.body.get("instrument_observation_id")
        dependencies = event.body.get("instrument_dependencies", [])
        if (type(dependencies) is not list or len(dependencies) > 1000
                or any(type(value) is not str or value not in history for value in dependencies)):
            raise ValueError("invalid closed financial effect dependencies")
        if (origin is None or origin in active) and all(identifier in active for identifier in dependencies):
            yield event


def account_restrictions(core):
    """An explicit instrument family remains restricted even without valid terms."""
    from ..ingest.instrument_observations import ObservationKind
    out = {}
    observations = current_observations(getattr(core, "_instrument_observations", {}))
    families = getattr(core, "_instrument_families", {})
    accounts = set(families)
    accounts.update(row["change"].subject_id for row in observations.values()
                    if row["change"].kind == ObservationKind.AVAILABILITY)
    for account in accounts:
        declarations = families.get(account, ())
        records = [row for row in observations.values()
                   if row["change"].subject_id == account and row["change"].kind == ObservationKind.AVAILABILITY]
        kinds = {row["family"] for row in declarations}
        kinds.update(row["change"].payload.family.value for row in records
                     if row["change"].payload.family.value != "ordinary")
        if not kinds:
            continue
        family = sorted(kinds)[0]
        expected = "restricted_term_deposit" if family == "term_deposit" else "restricted_escrow"
        restriction = records[-1]["change"].payload.restriction.value if records and records[-1]["change"].payload.restriction else ""
        status = ("conflicted" if len(kinds) != 1 or len(records) > 1 or (records and restriction != expected)
                  else "accepted" if records else "missing")
        source_ids = {row["event_id"] for row in declarations} | {row["event_id"] for row in records}
        docs = {row["doc_id"] for row in declarations} | {row["change"].source.doc_id for row in records}
        effective = max([row["effective"] for row in declarations] + [row["change"].effective.value for row in records], default="")
        out[account] = AccountRestriction(family, restriction, status, tuple(sorted(source_ids)), tuple(sorted(docs)), effective)
    return out


def _sources(value):
    from ..ingest.instrument_contracts import Source
    if type(value) is Source:
        return {value.doc_id}
    if is_dataclass(value):
        return set().union(*(_sources(getattr(value, field.name)) for field in fields(value)))
    if type(value) is tuple:
        return set().union(*(_sources(item) for item in value)) if value else set()
    return set()


def append_change(ledger, change, effects=()):
    """Validate against the locked canonical frontier, never a caller cache."""
    from ..ingest.instrument_observations import validate_transition
    from .events import postings_of
    from .postings import transaction_balances
    if type(effects) is not tuple:
        raise ValueError("instrument effects must be an immutable event tuple")
    def choose(projection):
        captured = projection.captured_docs()
        if not _sources(change) <= set(captured):
            raise ValueError("instrument observations require retained source documents")
        history = projection.core._instrument_observations
        if change.observation_id in history:
            raise ValueError("instrument observation ID already exists")
        prior = history.get(change.prior_id) if change.prior_id else None
        if prior is not None and prior["superseded"]:
            raise ValueError("observation correction is not at its locked frontier")
        validate_transition(change, prior["change"] if prior else None)
        records = [observation_event(change)]
        for effect in effects:
            if (type(effect) is not Event or effect.event_type not in {
                    "OpeningBalanceObserved", "ClosingBalanceObserved", "TransactionRecorded",
                    "PositionObserved", "TransferLinked", "CategoryAssigned"}
                    or effect.provenance.doc_id not in captured):
                raise ValueError("invalid sourced instrument financial effect")
            if effect.event_type == "TransactionRecorded" and not transaction_balances(list(postings_of(effect))).passed:
                raise ValueError("instrument effect postings do not balance")
            encoded = effect.to_dict()
            encoded["body"] = {**encoded["body"], "instrument_observation_id": change.observation_id}
            records.append(Event.from_dict(encoded))
        return records
    return ledger.append_atomically(choose)


def observations_as_of(history, as_of):
    """Select value-time metadata after validating its complete source frontier."""
    eligible = {key: {**row, "superseded": False} for key, row in history.items()
                if as_of is None or row["change"].effective.value <= as_of}
    for row in eligible.values():
        prior = row["change"].prior_id
        if prior in eligible:
            eligible[prior]["superseded"] = True
    return eligible


def reference_event(account_id, reference, dated, source, *, scope="account", identity_page_count=None):
    from ..ingest.instrument_contracts import Source, SourcedDate
    if (type(account_id) is not str or not account_id.strip()
            or type(reference) is not str or not reference.strip()
            or scope not in {"account", "continuous_escrow"} or type(source) is not Source):
        raise ValueError("explicit source account reference required")
    SourcedDate(dated, source)
    body = {"account_id": account_id, "reference": reference, "scope": scope}
    if identity_page_count is not None:
        from .identity import SourceAccountIdentity
        if not SourceAccountIdentity(reference, source.doc_id, source.page, identity_page_count).eligible():
            raise ValueError("eligible source account identity required")
        body["identity_page_count"] = identity_page_count
    return Event("FinancialAccountReferenceObserved", dated, body, Provenance(source.doc_id, source.page))


def reference_accounts(projection, reference, scope="account"):
    return tuple(sorted(account for account, rows in projection.core._instrument_account_refs.items()
                        if any(row["reference"] == reference and row["scope"] == scope for row in rows)))


def planned_effects(projection, observation_id, plan):
    """Plan one bounded closed effect batch against a locked fresh prefix."""
    chosen = []
    row = projection.core._instrument_observations.get(observation_id)
    if row is None or row["superseded"]:
        raise ValueError("instrument observation is no longer live")
    for key, effect in plan(projection, row["change"]):
        if key in projection.core._instrument_effect_keys:
            continue
        if (type(key) is not str or not key or type(effect) is not Event
                or effect.provenance.doc_id not in projection.captured_docs()
                or effect.event_type not in {"AccountOpened", "InstrumentFamilyDeclared", "FinancialAccountReferenceObserved",
                    "InstrumentObservationRecorded", "OpeningBalanceObserved", "ClosingBalanceObserved", "TransactionRecorded",
                    "InstrumentPaymentAllocated", "InstrumentKnownPaymentAllocated", "InstrumentComponentStateRecorded", "TransferLinked"}):
            raise ValueError("instrument effect must satisfy its finite sourced event vocabulary")
        dependencies = effect.body.get("instrument_dependencies", [])
        if (type(dependencies) is not list or len(dependencies) > 1000
                or any(type(value) is not str or value not in current_observations(projection.core._instrument_observations)
                       for value in dependencies)):
            raise ValueError("invalid financial effect dependencies")
        if effect.event_type == "TransactionRecorded":
            from .events import postings_of
            from .postings import transaction_balances
            if not transaction_balances(list(postings_of(effect))).passed:
                raise ValueError("instrument effect postings do not balance")
        if effect.event_type == "InstrumentObservationRecorded":
            change = decode_change(effect.body.get("record"))
            if not _sources(change) <= set(projection.captured_docs()):
                raise ValueError("child observation source is not retained")
            fold_change({key: dict(value) for key, value in projection.core._instrument_observations.items()}, effect)
        elif effect.event_type not in {"AccountOpened", "InstrumentFamilyDeclared", "FinancialAccountReferenceObserved"}:
            effect.body = {**effect.body, "instrument_observation_id": observation_id,
                           "instrument_effect_key": key}
        else:
            effect.body = {**effect.body, "instrument_declaration_key": key}
        chosen.append(effect)
        projection.apply(effect)
        if len(chosen) > 10000:
            raise ValueError("instrument effect batch exceeds its bound")
    return chosen


def append_effects(ledger, observation_id, plan):
    """Heal only a live observation, with idempotence checked under the writer lock."""
    chosen = []
    def decide(projection):
        chosen.extend(planned_effects(projection, observation_id, plan))
        return chosen
    ledger.append_atomically(decide)
    return len(chosen)


INSTRUMENT_ROLES = frozenset({"principal", "escrow_deposit", "escrow_tax", "escrow_insurance", "escrow_adjustment",
                              "term_funding", "term_interest", "term_redemption", "term_fee", "refinance_fee"})


def apply_cash_role(movement, role):
    if role not in INSTRUMENT_ROLES:
        raise ValueError("unknown financial instrument movement role")
    movement.nature = ("settlement" if role == "principal" else "transfer"
                       if role in {"escrow_deposit", "escrow_adjustment", "term_funding", "term_redemption"} else "spending")
    movement.nature_reason, movement.provisional = "document_components", False
