"""Closed reconciliation of named printed components to existing cash."""
from dataclasses import dataclass
from hashlib import sha256
import json
from . import instrument_contracts as c
from ..ledger.instruments import encode, decode
from ..ledger.events import Event, Provenance
from decimal import Decimal

OPERATION = 'total_minus_principal_interest_escrow'


def _bounded(value):
    if type(value) is not int or value.bit_length()>512:
        raise c.ContractError('known allocation integer resource limit')
    return value


def cents(value):
    if type(value) is not Decimal or not value.is_finite():
        raise c.ContractError('finite exact Decimal required')
    sign,digits,exponent=value.as_tuple()
    if (sign or len(digits)>30 or not -12<=exponent<=18
            or max(len(digits)+exponent,0)>18 or max(-exponent,0)>12):
        raise c.ContractError('known allocation decimal representation resource limit')
    coefficient=0
    for digit in digits:
        coefficient=_bounded(coefficient*10+digit)
    scale=exponent+2
    if scale>=0:
        return _bounded(coefficient*10**scale)
    divisor=10**(-scale)
    if coefficient%divisor:
        raise c.ContractError('known allocation requires exact cents')
    return _bounded(coefficient//divisor)


def residual(payment):
    if type(payment) is not c.PaymentComponents or payment.fees is not None:
        raise c.ContractError('known allocation is distinct from printed fees')
    values = tuple(getattr(payment, field) for field in ('total','principal','interest','escrow'))
    if (any(type(value) is not c.Money for value in values)
            or payment.dated is None or payment.reference is None
            or payment.funding_account_reference is None
            or len({value.currency for value in values}) != 1):
        raise c.ContractError('complete same-occurrence components required')
    docs = {value.source.doc_id for value in values}
    docs.update(value.source.doc_id for value in (payment.dated,payment.reference,payment.funding_account_reference))
    if len(docs) != 1:
        raise c.ContractError('payment components belong to different source occurrences')
    total, principal, interest, escrow = (cents(value.value) for value in values)
    if total <= 0:
        raise c.ContractError('positive total required')
    result = _bounded(total-principal-interest-escrow)
    if result:
        raise c.ContractError('printed components leave a nonzero net unallocated amount')
    return result


def body_digest(body):
    return sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class KnownAllocationReceipt(c.ClosedFact):
    schema: str
    operation: str
    observation_id: str
    occurrence_id: str
    loan_account: str
    escrow_account: str
    funding_account: str
    payment: c.PaymentComponents
    operand_ids: tuple[str,...]
    residual_cents: int
    source_read_event_id: str
    source_read_digest: str
    cash_event_id: str
    cash_body_digest: str
    bank_source: c.Source
    grade: str

    def __post_init__(self):
        super().__post_init__()
        if (self.schema != 'mortgage_known_payment_allocation_v1' or self.operation != OPERATION
                or self.residual_cents != residual(self.payment)
                or self.grade != 'unverified'
                or any(not value.strip() for value in (self.observation_id,self.occurrence_id,self.loan_account,self.funding_account,self.source_read_event_id,self.cash_event_id))
                or len(self.source_read_digest)!=64 or any(ch not in '0123456789abcdef' for ch in self.source_read_digest)
                or len(self.cash_body_digest) != 64 or any(ch not in '0123456789abcdef' for ch in self.cash_body_digest)
                or len(self.operand_ids) != 4 or len(set(self.operand_ids)) != 4):
            raise c.ContractError('invalid closed known-allocation receipt')
        if self.payment.escrow.value and not self.escrow_account.strip():
            raise c.ContractError('restricted escrow identity required')
        expected=tuple(body_digest({'observation':self.observation_id,'occurrence':self.occurrence_id,'field':field,
            'money':encode(getattr(self.payment,field))}) for field in ('total','principal','interest','escrow'))
        if self.operand_ids != expected:
            raise c.ContractError('known allocation operand identities mismatch')


@dataclass(frozen=True)
class KnownPaymentAllocation(c.ClosedFact):
    movement_key: str
    receipt: KnownAllocationReceipt

    def __post_init__(self):
        super().__post_init__()
        if not self.movement_key.strip():
            raise c.ContractError('canonical cash movement required')

    @property
    def payment(self): return self.receipt.payment
    @property
    def loan_account(self): return self.receipt.loan_account
    @property
    def escrow_account(self): return self.receipt.escrow_account
    @property
    def bank_source(self): return self.receipt.bank_source
    @property
    def spending(self): return self.payment.interest.value
    @property
    def component_names(self): return ('principal','interest','escrow')


def create_allocation(projection, change, payment, occurrence, loan, escrow, key, line):
    residual(payment)
    event=next((event for event in projection._source_events if event.event_id==line.transaction_id),None)
    if event is None or event.event_type != 'TransactionRecorded' or line.provenance.doc_id not in projection.captured_docs():
        raise c.ContractError('retained actual cash event required')
    accounts=[account for account,state in projection.core._acct.items() if any(row.transaction_id==line.transaction_id for row in state.lines)
              and state.kind=='depository' and state.currency==payment.total.currency]
    if len(accounts)!=1:
        raise c.ContractError('unique funding cash account required')
    reads=[event for event in projection._source_events if event.event_type=='ReadRecorded'
        and event.body.get('doc_id')==change.source.doc_id and event.body.get('phase','extract')=='extract']
    if not reads:
        raise c.ContractError('retained payment source reading required')
    reading=reads[-1]
    validate_reading(reading,change,payment,occurrence)
    grade='unverified'
    operands=tuple(body_digest({'observation':change.observation_id,'occurrence':occurrence,'field':field,
        'money':encode(getattr(payment,field))}) for field in ('total','principal','interest','escrow'))
    receipt=KnownAllocationReceipt('mortgage_known_payment_allocation_v1',OPERATION,change.observation_id,occurrence,
        loan,escrow,accounts[0],payment,operands,0,reading.event_id,body_digest(reading.body),event.event_id,body_digest(event.body),
        c.Source(line.provenance.doc_id,line.provenance.page),grade)
    allocation=KnownPaymentAllocation(key,receipt)
    validate_core_binding(allocation,projection.core)
    return allocation


def known_allocation_event(allocation):
    if type(allocation) is not KnownPaymentAllocation:
        raise c.ContractError('typed known allocation required')
    source=allocation.payment.reference.source
    return Event('InstrumentKnownPaymentAllocated',allocation.payment.dated.value,
        {'allocation':encode(allocation)},Provenance(source.doc_id,source.page))


def known_allocation_from_event(event):
    if set(event.body)-{'allocation','instrument_observation_id','instrument_effect_key'}:
        raise c.ContractError('unknown known-allocation fields')
    result=decode(event.body.get('allocation'),KnownPaymentAllocation)
    if (event.occurred_at!=result.payment.dated.value or event.provenance.doc_id!=result.payment.reference.source.doc_id
            or event.provenance.page!=result.payment.reference.source.page
            or event.body.get('instrument_observation_id')!=result.receipt.observation_id):
        raise c.ContractError('known-allocation source envelope mismatch')
    return result


def decode_allocation(value):
    from .instrument_effects import PaymentAllocation
    return decode(value,KnownPaymentAllocation if type(value) is dict and set(value)=={'movement_key','receipt'} else PaymentAllocation)



def validate_source_binding(allocation, history, cash, reading=None, readings=None):
    receipt=allocation.receipt
    row=history.get(receipt.observation_id)
    if row is None or row['superseded'] or row['change'].payload is None:
        raise c.ContractError('known allocation source is not live')
    change=row['change']
    if source_conflicted(receipt,history,readings):
        raise c.ContractError('conflicting same-occurrence printed components')
    try:
        index=int(receipt.occurrence_id)
    except ValueError:
        raise c.ContractError('invalid payment occurrence') from None
    if (str(index)!=receipt.occurrence_id or index<0 or type(change.payload) is not c.MortgageFacts
            or index>=len(change.payload.payments or ()) or change.payload.payments[index]!=receipt.payment
            or change.subject_id!=receipt.loan_account):
        raise c.ContractError('known allocation does not bind original source occurrence')
    if (reading is None or reading.event_id!=receipt.source_read_event_id
            or body_digest(reading.body)!=receipt.source_read_digest):
        raise c.ContractError('known allocation source reading dependency changed')
    validate_reading(reading,change,receipt.payment,receipt.occurrence_id)
    if cash != (receipt.cash_body_digest, receipt.bank_source):
        raise c.ContractError('known allocation cash dependency changed or is unavailable')


def validate_reading(reading, change, payment, occurrence):
    from .instrument_parser import parse_instrument_json
    if (reading.event_type!='ReadRecorded' or reading.body.get('doc_id')!=change.source.doc_id
            or reading.body.get('phase','extract')!='extract' or reading.body.get('parse_ok') is not True
            or reading.body.get('parse_error')):
        raise c.ContractError('accepted retained source reading required')
    text, locale, currency = _retained_parser_input(reading)
    parsed=parse_instrument_json(text,'mortgage_statement',change.source.doc_id,locale,currency)
    if encode(parsed)!=encode(change.payload) or parsed.payments[int(occurrence)]!=payment:
        raise c.ContractError('retained reading does not support the complete payment source interpretation')


def validate_identities(receipt, change, references, kinds):
    if not any(reference==receipt.payment.funding_account_reference.value and scope=='account'
            for reference,scope in references.get(receipt.funding_account,())):
        raise c.ContractError('funding identity is not source bound')
    if kinds.get(receipt.funding_account)!=('depository',receipt.payment.total.currency):
        raise c.ContractError('funding account currency or kind mismatch')
    if not any(reference==change.payload.identity.account_reference.value and scope=='account'
            for reference,scope in references.get(receipt.loan_account,())):
        raise c.ContractError('loan identity is not source bound')
    if receipt.payment.escrow.value:
        escrow=change.payload.escrow
        if escrow is None or escrow.identity is None:
            raise c.ContractError('escrow identity unavailable')
        candidates={(escrow.identity.account_reference.value,'account')}
        if escrow.continuity_reference is not None:
            candidates.add((escrow.continuity_reference.value,'continuous_escrow'))
        if not candidates.intersection(references.get(receipt.escrow_account,())):
            raise c.ContractError('escrow identity is not source bound')
        if kinds.get(receipt.escrow_account)!=('depository',receipt.payment.total.currency):
            raise c.ContractError('escrow account currency or kind mismatch')
    for movement in change.payload.principal_movements or ():
        if (movement.reference is not None and movement.reference.value==receipt.payment.reference.value
                and movement.kind in {c.PrincipalKind.INCREASE_ADJUSTMENT}):
            raise c.ContractError('known same-payment principal adjustment')
    for movement in change.payload.escrow.movements if change.payload.escrow else ():
        if (movement.reference is not None and movement.reference.value==receipt.payment.reference.value
                and movement.kind in {c.EscrowKind.INCREASE_ADJUSTMENT,c.EscrowKind.DECREASE_ADJUSTMENT}):
            raise c.ContractError('known same-payment escrow adjustment')


def validate_core_binding(allocation,core):
    from datetime import date
    from ..ledger.projection.movements import _enumerated
    receipt=allocation.receipt
    if receipt.bank_source.doc_id not in core._captured:
        raise c.ContractError('retained cash source document required')
    validate_source_binding(allocation,core._instrument_observations,
        core._instrument_cash_dependencies.get(receipt.cash_event_id),
        core._instrument_source_reads.get(allocation.payment.reference.source.doc_id),core._instrument_source_reads)
    change=core._instrument_observations[receipt.observation_id]['change']
    references={account:tuple((row['reference'],row['scope']) for row in rows)
        for account,rows in core._instrument_account_refs.items()}
    kinds={account:(state.kind,state.currency) for account,state in core._acct.items()}
    validate_identities(receipt,change,references,kinds)
    matches=[]
    for key,account,state,line in _enumerated(core):
        if (account==receipt.funding_account and state.currency==receipt.payment.total.currency
                and line.amount==receipt.payment.total.value.copy_negate()
                and core._instrument_bank_references.get(line.transaction_id)==(
                    receipt.payment.reference.value,change.payload.identity.account_reference.value)
                and abs((date.fromisoformat(line.date)-date.fromisoformat(receipt.payment.dated.value)).days)<=10
                and line.provenance.page is not None):
            matches.append((key,line.transaction_id))
    if matches!=[(allocation.movement_key,receipt.cash_event_id)]:
        raise c.ContractError('known allocation cash match is not unique and exact')


def source_conflicted(receipt,history,readings=None):
    expected=tuple((getattr(receipt.payment,field).value,getattr(receipt.payment,field).currency) for field in ('total','principal','interest','escrow'))
    own=history.get(receipt.observation_id)
    if own is None or type(own['change'].payload) is not c.MortgageFacts:
        return True
    source=own['change'].payload
    def escrow_reference(facts):
        escrow=facts.escrow
        if escrow is None or escrow.identity is None:
            return None
        return (escrow.identity.account_reference.value,
            None if escrow.continuity_reference is None else escrow.continuity_reference.value)
    expected_escrow=escrow_reference(source)
    for candidate in history.values():
        other=candidate['change']
        if candidate['superseded'] or other.subject_id!=receipt.loan_account or type(other.payload) is not c.MortgageFacts:
            continue
        for occurrence,payment in enumerate(other.payload.payments or ()):
            if (payment.reference is not None and payment.dated is not None
                    and payment.reference.value==receipt.payment.reference.value
                    and payment.dated.value==receipt.payment.dated.value):
                values=tuple(None if getattr(payment,field) is None else (getattr(payment,field).value,getattr(payment,field).currency)
                    for field in ('total','principal','interest','escrow'))
                if (values!=expected or payment.fees is not None
                        or payment.funding_account_reference is None
                        or payment.funding_account_reference.value!=receipt.payment.funding_account_reference.value
                        or other.payload.identity.account_reference.value!=source.identity.account_reference.value
                        or (receipt.payment.escrow.value and escrow_reference(other.payload)!=expected_escrow)):
                    return True
                rows=tuple(other.payload.principal_movements or ()) + tuple(other.payload.escrow.movements or () if other.payload.escrow else ())
                for movement in rows:
                    if (movement.reference is not None and movement.reference.value==payment.reference.value
                            and movement.kind in {c.PrincipalKind.INCREASE_ADJUSTMENT,c.PrincipalKind.DECREASE_ADJUSTMENT,
                                c.EscrowKind.INCREASE_ADJUSTMENT,c.EscrowKind.DECREASE_ADJUSTMENT}):
                        return True
                if readings is not None:
                    reading=readings.get(other.source.doc_id)
                    if reading is not None and raw_payment_conflicted(reading,occurrence,payment):
                        return True
    return False


def raw_payment_conflicted(reading,occurrence,payment):
    """Unknown or present-invalid fields cannot become an absent component."""
    from dataclasses import fields
    from .instrument_parser import load_json
    if reading.body.get('parse_ok') is not True or reading.body.get('parse_error'):
        return True
    try:
        text, _locale, _currency = _retained_parser_input(reading)
        data=load_json(text)
    except (ValueError,TypeError):
        return True
    if type(data) is not dict or set(data)-{field.name for field in fields(c.MortgageFacts)}:
        return True
    payments=data.get('payments')
    if type(payments) is not list or len(payments)>1000 or occurrence>=len(payments):
        return True
    raw=payments[occurrence]
    if type(raw) is not dict or set(raw)-{field.name for field in fields(c.PaymentComponents)}:
        return True
    return raw.get('fees') is not None


def _retained_parser_input(reading):
    """One authenticated acquisition kind, one recorded interpretation."""
    body = reading.body
    if 'acquisition' in body:
        from ..sample.curation import decode_retained_input
        # Full closed local envelope; metadata alone is never a decoder.
        text = decode_retained_input(body)
        return text, body['normalization_locale'], body['source_currency']
    from ..normalization_context import decode_context
    if 'normalization_context' not in body:
        raise c.ContractError('recorded model extraction normalization context required')
    context = decode_context(body['normalization_context'])
    text = body.get('response_text')
    if type(text) is not str:raise c.ContractError('retained ordinary response unavailable')
    return text, context.parser_locale, context.parser_currency
