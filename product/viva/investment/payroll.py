"""Source-only payroll occurrence witnesses bound to existing committed money."""
from collections import Counter
from dataclasses import dataclass,fields,replace
from decimal import Decimal,localcontext
from .contracts import Field,EvidenceError,FundingWitness,text,day,decimal,encode,canonical,digest
from .events import accepted,prefix,LockedEventPrefix
from viva.ledger.events import Event,Provenance
from viva.ledger.projection import LedgerProjection
from viva.ledger.postings import paystub_decomposition

OBSERVED='PayrollDeductionSourceObserved'
CHANGED='PayrollDeductionSourceChanged'
CATEGORIES=('tax','retirement','insurance','other')

@dataclass(frozen=True)
class PayrollDeductionOccurrence:
    local_id: str
    ordinal: int
    label: Field
    category: Field
    amount: Field
    destination_reference: Field
    contribution_reference: Field
    def __post_init__(self):
        text(self.local_id)
        if type(self.ordinal) is not int or not 0<=self.ordinal<1000:raise EvidenceError('invalid payroll occurrence ordinal')
        for name in ('label','category','amount','destination_reference','contribution_reference'):
            if type(getattr(self,name)) is not Field:raise EvidenceError('typed payroll occurrence field required')
        if self.category.value not in CATEGORIES:raise EvidenceError('unknown payroll category')
        if self.amount.status=='accepted' and decimal(self.amount.value)<=0:raise EvidenceError('payroll deduction must be positive')

@dataclass(frozen=True)
class PayrollSource:
    document: str
    source_reference: Field
    currency: Field
    pay_date: Field
    gross: Field
    net: Field
    deductions: tuple[PayrollDeductionOccurrence,...]
    def __post_init__(self):
        text(self.document)
        for name in ('source_reference','currency','pay_date','gross','net'):
            if type(getattr(self,name)) is not Field:raise EvidenceError('typed payroll header required')
        if type(self.deductions) is not tuple or len(self.deductions)>1000 or any(type(row) is not PayrollDeductionOccurrence for row in self.deductions):raise EvidenceError('immutable payroll occurrences required')
        if tuple(row.ordinal for row in self.deductions)!=tuple(range(len(self.deductions))) or len({r.local_id for r in self.deductions})!=len(self.deductions):raise EvidenceError('payroll occurrence sequence differs')
        if any(field.document!=self.document for field in source_fields(self)):raise EvidenceError('payroll field foreign document')
        if self.pay_date.status=='accepted':day(self.pay_date.value)
        if self.currency.status=='accepted' and (len(self.currency.value)!=3 or not self.currency.value.isascii() or not self.currency.value.isupper()):raise EvidenceError('invalid payroll currency')

@dataclass(frozen=True)
class PayrollCorroboration:
    source: PayrollSource
    source_event_id: str
    source_body_digest: str
    occurrence_id: str
    ordinal: int
    def __post_init__(self):
        if type(self.source) is not PayrollSource or type(self.ordinal) is not int or not 0<=self.ordinal<len(self.source.deductions) or self.source.deductions[self.ordinal].local_id!=self.occurrence_id:raise EvidenceError('invalid payroll corroborating occurrence')
        text(self.source_event_id);text(self.occurrence_id)
        if type(self.source_body_digest) is not str or len(self.source_body_digest)!=64 or any(c not in '0123456789abcdef' for c in self.source_body_digest):raise EvidenceError('invalid payroll corroboration digest')

@dataclass(frozen=True)
class PayrollDependency:
    source: PayrollSource
    source_event_id: str
    source_body_digest: str
    occurrence_id: str
    ordinal: int
    payroll_identity: str
    decomposition_event_id: str
    decomposition_body_digest: str
    net_deposit_event_id: str
    net_deposit_body_digest: str
    net_movement_key: str
    currency: str
    corroborating_sources: tuple[PayrollCorroboration,...]=()
    net_deposit_date: Field | None=None
    def __post_init__(self):
        if type(self.source) is not PayrollSource:raise EvidenceError('typed payroll source dependency required')
        if self.net_deposit_date is not None and type(self.net_deposit_date) is not Field:raise EvidenceError('typed net deposit source date required')
        if type(self.ordinal) is not int or not 0<=self.ordinal<len(self.source.deductions):raise EvidenceError('payroll dependency ordinal unavailable')
        if self.source.deductions[self.ordinal].local_id!=self.occurrence_id:raise EvidenceError('payroll dependency occurrence differs')
        for name in ('source_event_id','occurrence_id','payroll_identity','decomposition_event_id','net_deposit_event_id','net_movement_key','currency'):text(getattr(self,name),2048)
        for name in ('source_body_digest','decomposition_body_digest','net_deposit_body_digest'):
            value=getattr(self,name)
            if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise EvidenceError('invalid payroll dependency digest')
        if self.payroll_identity!=payroll_identity(self.source.source_reference.value):raise EvidenceError('payroll source identity differs')
        if self.currency!=self.source.currency.value:raise EvidenceError('payroll dependency currency differs')
        if type(self.corroborating_sources) is not tuple or len(self.corroborating_sources)>120 or any(type(copy) is not PayrollCorroboration for copy in self.corroborating_sources):raise EvidenceError('bounded immutable payroll corroboration required')
        ids=[self.source_event_id,*[copy.source_event_id for copy in self.corroborating_sources]]
        if len(set(ids))!=len(ids):raise EvidenceError('duplicate payroll corroboration id')

@dataclass(frozen=True)
class PayrollSourceChange:
    change_id: str
    prior_id: str
    prior_document: str
    effective: str
    cause: str
    replacement_id: str | None=None
    def __post_init__(self):
        for value in (self.change_id,self.prior_id,self.prior_document):text(value)
        day(self.effective)
        if self.cause not in ('source_correction','source_retraction') or (self.cause=='source_retraction')!=(self.replacement_id is None):raise EvidenceError('invalid payroll source change')
        if self.replacement_id is not None:text(self.replacement_id)


def payroll_identity(reference):
    text(reference)
    return 'payroll:'+digest(reference)


def source_fields(source):
    return (source.source_reference,source.currency,source.pay_date,source.gross,source.net,*tuple(f for row in source.deductions for f in (row.label,row.category,row.amount,row.destination_reference,row.contribution_reference)))


def decode_source(data):
    if type(data) is not dict or set(data)!={f.name for f in fields(PayrollSource)}:raise EvidenceError('closed stored payroll source required')
    from .events import decode_field
    data=dict(data)
    for name in ('source_reference','currency','pay_date','gross','net'):data[name]=decode_field(data[name])
    if type(data['deductions']) is not list:raise EvidenceError('stored payroll deduction list required')
    rows=[]
    for item in data['deductions']:
        if type(item) is not dict or set(item)!={f.name for f in fields(PayrollDeductionOccurrence)}:raise EvidenceError('closed stored payroll occurrence required')
        item=dict(item)
        for name in ('label','category','amount','destination_reference','contribution_reference'):item[name]=decode_field(item[name])
        rows.append(PayrollDeductionOccurrence(**item))
    data['deductions']=tuple(rows)
    return PayrollSource(**data)


def decode_dependency(data):
    if type(data) is dict and 'net_deposit_date' not in data:data={**data,'net_deposit_date':None}
    if type(data) is not dict or set(data)!={f.name for f in fields(PayrollDependency)}:raise EvidenceError('closed stored payroll dependency required')
    data=dict(data);data['source']=decode_source(data['source'])
    if data['net_deposit_date'] is not None:
        from .events import decode_field
        data['net_deposit_date']=decode_field(data['net_deposit_date'])
    if type(data['corroborating_sources']) is not list:raise EvidenceError('stored payroll corroboration list required')
    copies=[]
    for value in data['corroborating_sources']:
        if type(value) is not dict or set(value)!={f.name for f in fields(PayrollCorroboration)}:raise EvidenceError('closed payroll corroboration required')
        value=dict(value);value['source']=decode_source(value['source']);copies.append(PayrollCorroboration(**value))
    data['corroborating_sources']=tuple(copies)
    return PayrollDependency(**data)


def build_source(facts,locale='en-US'):
    from .payroll_extraction import PayrollSourceExtraction
    from vivacore.verify.normalize import parse_amount,parse_date
    from viva.retirement_funding.payroll_v2 import PayrollSourceExtractionV2,economic_facts
    if type(facts.payroll_source) is PayrollSourceExtractionV2:facts=economic_facts(facts)
    extraction=facts.payroll_source
    if type(extraction) is not PayrollSourceExtraction:raise EvidenceError('payroll source extension unavailable')
    if len(extraction.deductions)!=len(facts.deductions):raise EvidenceError('payroll source occurrence count differs')
    def field(raw,expected,kind='text'):
        value=str(expected);status='unavailable'
        if raw is not None:
            actual=raw.raw.strip()
            if kind=='money':
                normalized=parse_amount(actual,locale,facts.currency)
                actual=str(normalized.decimal().copy_abs()) if normalized.ok else None
            elif kind=='date':
                normalized=parse_date(actual,locale)
                actual=normalized.value if normalized.ok else None
            elif kind=='category':actual=actual.lower()
            elif kind=='currency':actual=actual.upper()
            if actual is not None and raw.page is not None:status='accepted' if (decimal(actual)==decimal(value) if kind=='money' else actual==value) else 'conflicted'
            return Field(value,facts.doc_id,raw.page,status=status,raw=raw.raw)
        return Field(value,facts.doc_id,None,status=status)
    headers=dict(extraction.headers)
    source_ref=headers['source_reference']
    ref=field(source_ref,source_ref.raw.strip() if source_ref else '')
    rows=[]
    for ordinal,(raw,deduction) in enumerate(zip(extraction.deductions,facts.deductions)):
        raw=dict(raw)
        def reference(name):return field(raw[name],raw[name].raw.strip() if raw[name] else '')
        rows.append(PayrollDeductionOccurrence(digest((facts.doc_id,'payroll-deduction',ordinal)),ordinal,
            field(raw['label'],deduction.label),field(raw['category'],deduction.category,'category'),field(raw['amount'],deduction.amount,'money'),reference('destination_reference'),reference('contribution_reference')))
    result=PayrollSource(facts.doc_id,ref,field(headers['currency'],facts.currency,'currency'),field(headers['pay_date'],facts.pay_date,'date'),field(headers['gross'],facts.gross,'money'),field(headers['net'],facts.net,'money'),tuple(rows))
    if len(canonical(result))>262144:raise EvidenceError('payroll source byte bound')
    return result


def _financial_identity(source):
    # Complete multiplicity is retained; this key is only cross-copy corroboration.
    return (source.source_reference.value,source.currency.value,source.pay_date.value,decimal(source.gross.value),decimal(source.net.value),
        tuple(sorted((r.label.value,r.category.value,decimal(r.amount.value),r.destination_reference.value,r.contribution_reference.value) for r in source.deductions)))


def _accounting_identity(source):
    # A printed payroll identity plus its accepted complete accounting body
    # permits retaining a contradictory copy; it does not resolve funding.
    return (source.source_reference.value,source.currency.value,source.pay_date.value,
            decimal(source.gross.value),decimal(source.net.value),
            tuple(sorted((r.category.value,decimal(r.amount.value)) for r in source.deductions)))


def _complete(source):
    if not accepted(source.source_reference,source.currency,source.pay_date,source.gross,source.net) or not source.source_reference.value:return False
    for row in source.deductions:
        if not accepted(row.label,row.category,row.amount):return False
        if row.category.value=='retirement' and (not accepted(row.label,row.category,row.destination_reference,row.contribution_reference) or not row.destination_reference.value or not row.contribution_reference.value):return False
    return True


def _net_event(events,key,currency):
    from viva.ledger.projection.movements import _enumerated
    projection=LedgerProjection(events)
    candidates=[(account,line) for held,account,state,line in _enumerated(projection.core) if held==key and state.kind=='depository' and state.currency==currency]
    if len(candidates)!=1:raise EvidenceError('matched payroll net deposit unavailable or ambiguous')
    account,line=candidates[0]
    event=next((event for event in events if event.event_id==line.transaction_id),None)
    if event is None or event.event_type!='TransactionRecorded':raise EvidenceError('net deposit transaction unavailable')
    return event,line


def _decomposition(source,events,event_id=None):
    if not accepted(source.currency,source.pay_date,source.gross,source.net) or any(not accepted(row.amount) for row in source.deductions):raise EvidenceError('payroll numeric source unavailable')
    with localcontext() as context:
        context.prec=128
        if decimal(source.gross.value)-sum((decimal(row.amount.value) for row in source.deductions),Decimal(0))!=decimal(source.net.value):raise EvidenceError('payroll source decomposition does not reconcile')
    rows=[type('PostedDeduction',(),{'amount':decimal(r.amount.value),'category':r.category.value}) for r in source.deductions]
    expected=paystub_decomposition(source.gross.value,source.net.value,rows,'',source.pay_date.value).body['postings']
    def legs(body):return Counter((p.get('account'),str(decimal(p['amount'],True)),p.get('grade')) for p in body.get('postings',()))
    choices=[event for event in events if event.event_type=='TransactionRecorded' and event.occurred_at==source.pay_date.value and event.body.get('matched_movement_key') and event.body.get('matched_currency')==source.currency.value and legs(event.body)==legs({'postings':expected}) and (event_id is None or event.event_id==event_id)]
    if len(choices)!=1:raise EvidenceError('accepted payroll decomposition unavailable or ambiguous')
    event=choices[0];net,line=_net_event(events,event.body['matched_movement_key'],source.currency.value)
    if line.amount!=decimal(source.net.value):raise EvidenceError('matched payroll net amount differs')
    if line.date!=source.pay_date.value:
        from datetime import date
        if abs((date.fromisoformat(line.date)-date.fromisoformat(source.pay_date.value)).days)>10:raise EvidenceError('matched payroll net date differs')
    return event,net,line


def _records(events,as_of='9999-12-31'):
    day(as_of);known={};roots={};heads={};pending=set();changes=[];by_id={e.event_id:e for e in events}
    if len(by_id)!=len(events):raise EvidenceError('duplicate committed payroll dependency id')
    for ordinal,event in enumerate(events):
        if event.event_type==OBSERVED:
            body=event.body
            required={'schema_version','source','decomposition_event_id','decomposition_body_digest','net_deposit_event_id','net_deposit_body_digest','net_movement_key','currency','prefix','prior_id','change_event_id'}
            if set(body)!=required or body['schema_version']!='payroll-deduction-source-v1':raise EvidenceError('invalid stored payroll source envelope')
            proof=body['prefix'];count=proof.get('event_count')
            if type(count) is not int or count!=ordinal or encode(prefix(events[:count]))!=proof:raise EvidenceError('payroll source committed prefix differs')
            source=decode_source(body['source']);decomp,net,line=_decomposition(source,events[:count],body['decomposition_event_id'])
            if digest(decomp.body)!=body['decomposition_body_digest'] or digest(net.body)!=body['net_deposit_body_digest'] or net.event_id!=body['net_deposit_event_id'] or decomp.body['matched_movement_key']!=body['net_movement_key'] or body['currency']!=source.currency.value:raise EvidenceError('payroll source money dependency differs')
            if event.provenance.doc_id!=source.document or event.occurred_at!=source.pay_date.value:raise EvidenceError('payroll source provenance differs')
            known[event.event_id]=(event,source)
            if body['prior_id'] is None:
                if body['change_event_id'] is not None:raise EvidenceError('unexpected payroll source revision')
                roots[event.event_id]=event.event_id;heads[event.event_id]=event.event_id
            else:
                change=by_id.get(body['change_event_id'])
                if change is None or ordinal+1>=len(events) or events[ordinal+1].event_id!=change.event_id or change.event_type!=CHANGED:raise EvidenceError('incomplete payroll source revision')
        elif event.event_type==CHANGED:
            body=event.body
            if set(body)!={'change','prefix'}:raise EvidenceError('invalid payroll change envelope')
            proof=body['prefix'];count=proof.get('event_count')
            if type(count) is not int or count!=ordinal or encode(prefix(events[:count]))!=proof:raise EvidenceError('payroll change committed prefix differs')
            value=body['change']
            if type(value) is not dict or set(value)!={f.name for f in fields(PayrollSourceChange)}:raise EvidenceError('invalid payroll change')
            change=PayrollSourceChange(**value)
            prior=known.get(change.prior_id);root=roots.get(change.prior_id)
            if prior is None or root is None or prior[1].document!=change.prior_document or heads[root]!=change.prior_id:raise EvidenceError('payroll source predecessor is not current')
            if change.effective!=event.occurred_at:raise EvidenceError('payroll change effective date differs')
            replacement=known.get(change.replacement_id) if change.replacement_id is not None else None
            if change.replacement_id is not None:
                if replacement is None or replacement[1].document!=change.prior_document or replacement[0].body['prior_id']!=change.prior_id or replacement[0].body['change_event_id']!=event.event_id:raise EvidenceError('payroll replacement closure differs')
                roots[change.replacement_id]=root
            changes.append((root,change,replacement))
            if replacement is None or _complete(replacement[1]):heads[root]=change.replacement_id
    chosen={root:root for root in set(roots.values())}
    for root,change,replacement in changes:
        if change.effective>as_of:continue
        if replacement is None or _complete(replacement[1]):chosen[root]=change.replacement_id;pending.discard(root)
        else:pending.add(root)
    return tuple((known[identifier][0],known[identifier][1],root in pending) for root,identifier in chosen.items() if identifier is not None)


def change_dates(events):
    return tuple(e.occurred_at for e in events if e.event_type==CHANGED)


def append_source(ledger,facts,*,locale='en-US',effective=None):
    if facts.payroll_source is None:return []
    with ledger._lock:
        complete=[]
        def decide(events):
            source=build_source(facts,locale);decomp,net,line=_decomposition(source,events)
            records=_records(events);same_doc=[(e,s,pending) for e,s,pending in records if s.document==source.document]
            prior=same_doc[0][0] if len(same_doc)==1 else None
            if len(same_doc)>1:raise EvidenceError('ambiguous payroll source predecessor')
            copies=[(e,s) for e,s,pending in records if not pending and _accounting_identity(s)==_accounting_identity(source)]
            if decomp.provenance.doc_id!=source.document and not copies:raise EvidenceError('historical payroll reference attribution unavailable')
            binding={'schema_version':'payroll-deduction-source-v1','source':encode(source),'decomposition_event_id':decomp.event_id,'decomposition_body_digest':digest(decomp.body),'net_deposit_event_id':net.event_id,'net_deposit_body_digest':digest(net.body),'net_movement_key':decomp.body['matched_movement_key'],'currency':source.currency.value}
            identifier='payroll-source:'+digest(binding)
            existing=next((e for e in events if e.event_id==identifier),None)
            if existing is not None:complete.extend(events);return ()
            change_id='payroll-change:'+digest((prior.event_id,identifier)) if prior is not None else None
            body={**binding,'prefix':encode(prefix(events)),'prior_id':prior.event_id if prior is not None else None,'change_event_id':change_id}
            event=Event(OBSERVED,source.pay_date.value,body,Provenance(doc_id=source.document,page=source.pay_date.page),event_id=identifier)
            additions=(event,)
            if prior is not None:
                change=PayrollSourceChange(change_id,prior.event_id,source.document,effective or source.pay_date.value,'source_correction',identifier)
                additions+=(Event(CHANGED,change.effective,{'change':encode(change),'prefix':encode(prefix((*events,event)))},Provenance(doc_id=source.document),event_id=change_id),)
            complete.extend(events);complete.extend(additions);return additions
        result=ledger.store.append_atomically(decide)
        ledger._proj=LedgerProjection(complete,resolve_keys=ledger._resolve_keys);ledger._projection_identity=ledger.store._cached_identity()
        return result


def retract_source(ledger,change):
    if type(change) is not PayrollSourceChange or change.cause!='source_retraction':raise EvidenceError('typed payroll retraction required')
    with ledger._lock:
        complete=[]
        def decide(events):
            current=[(e,s) for e,s,pending in _records(events) if e.event_id==change.prior_id and s.document==change.prior_document]
            if len(current)!=1:raise EvidenceError('payroll retraction predecessor is not current')
            if any(e.event_id==change.change_id for e in events):raise EvidenceError('payroll change id collision')
            event=Event(CHANGED,change.effective,{'change':encode(change),'prefix':encode(prefix(events))},Provenance(doc_id=change.prior_document),event_id=change.change_id)
            complete.extend(events);complete.append(event);return (event,)
        result=ledger.store.append_atomically(decide)
        ledger._proj=LedgerProjection(complete,resolve_keys=ledger._resolve_keys);ledger._projection_identity=ledger.store._cached_identity()
        return result


class FundingValidationContext:
    """Ephemeral exact-prefix work reuse; never persisted or used by tool reads."""
    def __init__(self,events,validated_sources):
        self.events=tuple(events);self.frontier=prefix(self.events)
        self.sources=tuple(validated_sources);self._records={};self._destinations={};self._source_index=None
    def check(self,events):
        if prefix(tuple(events))!=self.frontier:raise EvidenceError('funding context prefix changed')
    def source_index(self,events):
        self.check(events)
        if self._source_index is None:
            from .lifecycle import SourceIndex
            self._source_index=SourceIndex(self.events,self.sources)
        return self._source_index
    def records(self,events,as_of):
        self.check(events)
        if as_of not in self._records:self._records[as_of]=_records(self.events,as_of)
        return self._records[as_of]
    def destinations(self,events,as_of):
        self.check(events)
        if as_of not in self._destinations:self._destinations[as_of]=destination_resolver(self.events,as_of,_validated_sources=self.sources)
        return self._destinations[as_of]


def destination_resolver(events,as_of='9999-12-31',*,_validated_sources=None):
    # Only a validated, committed accepted snapshot header can establish this
    # source-only reference. Never promote a raw extracted label to an alias.
    from .events import _validated_statements
    from .lifecycle import SourceIndex
    sources=_validated_statements(events,lambda _:None) if _validated_sources is None else _validated_sources
    index=SourceIndex(events,sources)
    mapping={}
    for selection in index.select('positions',as_of):
        source=selection.statement
        if selection.status!='accepted' or not source.snapshot_complete or not accepted(source.account,source.currency,source.closing_cash) or not source.account.raw:continue
        if any(not position.position_event_id or not position.position_body_digest for position in source.positions):continue
        closing=[e for e in events if e.event_type=='ClosingBalanceObserved' and e.body.get('account_id')==source.account.value and e.occurred_at==source.end.value and e.provenance.doc_id==source.account.document and decimal(e.body['amount'],True)==decimal(source.closing_cash.value)]
        if not closing:continue
        mapping.setdefault(source.account.raw,set()).add((source.account.value,source.currency.value))
    def resolve(field):
        if not accepted(field):return None
        matches=mapping.get(field.value,set())
        return next(iter(matches)) if len(matches)==1 else None
    return resolve


def bind_payroll(fields,events,*,destination_account,destination_reference,currency,effective_as_of="9999-12-31",_context=None):
    reference=fields['printed_reference'];counterpart=fields['counterpart_reference'];date=fields['date'];amount=fields['amount'];role=fields.get('funding_role')
    if not accepted(reference,counterpart,date,amount,role) or role.value!='external_party' or not reference.value or not counterpart.value:return {}
    resolve=destination_resolver(events,effective_as_of) if _context is None else _context.destinations(events,effective_as_of)
    if not accepted(destination_reference) or resolve(destination_reference)!=(destination_account,currency):return {}
    candidates=[]
    for event,source,pending in (_records(events,effective_as_of) if _context is None else _context.records(events,effective_as_of)):
        if source.source_reference.value!=counterpart.value:continue
        for occurrence in source.deductions:
            if occurrence.contribution_reference.value!=reference.value:continue
            if pending or not _complete(source) or occurrence.category.value!='retirement' or not accepted(occurrence.label,occurrence.category,occurrence.amount,occurrence.destination_reference,occurrence.contribution_reference):return {}
            if occurrence.destination_reference.value not in {destination_reference.value,destination_reference.raw} or resolve(occurrence.destination_reference)!=(destination_account,currency):return {}
            if source.currency.value!=currency or source.pay_date.value!=date.value or decimal(occurrence.amount.value)!=decimal(amount.value):return {}
            candidates.append((event,source,occurrence))
    if not candidates:return {}
    # Equivalent full source copies corroborate. Multiple equal occurrences in
    # any single source remain ambiguous rather than being collapsed.
    documents={e.provenance.doc_id for e,s,row in candidates}
    if any(sum(e.provenance.doc_id==doc for e,s,row in candidates)!=1 for doc in documents):return {}
    if len({_financial_identity(source) for event,source,row in candidates})!=1:return {}
    event,source,occurrence=candidates[0];body=event.body
    dependency=PayrollDependency(source,event.event_id,digest(body),occurrence.local_id,occurrence.ordinal,payroll_identity(source.source_reference.value),body['decomposition_event_id'],body['decomposition_body_digest'],body['net_deposit_event_id'],body['net_deposit_body_digest'],body['net_movement_key'],currency)
    copies=tuple(PayrollCorroboration(other,copy.event_id,digest(copy.body),deduction.local_id,deduction.ordinal) for copy,other,deduction in candidates[1:])
    net=next((candidate for candidate in events if candidate.event_id==body['net_deposit_event_id']),None)
    if net is None or not net.provenance.doc_id or type(net.provenance.page) is not int or not 1<=net.provenance.page<=200:return {}
    net_date=Field(net.occurred_at,net.provenance.doc_id,net.provenance.page,raw='')
    dependency=replace(dependency,corroborating_sources=copies,net_deposit_date=net_date)
    witness=FundingWitness(occurrence.contribution_reference,source.source_reference,dependency.payroll_identity,'external_party',body['decomposition_event_id'],body['decomposition_body_digest'],payroll_dependency=dependency)
    return {'funding_role':'external_party','funding_role_source':role,'funding_witness':witness}


def validate_payroll_funding(statement,row,by_id,as_of='9999-12-31',*,_context=None):
    witness=row.funding_witness;dependency=witness.payroll_dependency
    if type(dependency) is not PayrollDependency or witness.role!='external_party' or witness.source_row_event_id:raise EvidenceError('invalid payroll funding branch')
    if witness.counterpart_account!=dependency.payroll_identity or witness.transaction_id!=dependency.decomposition_event_id or witness.transaction_digest!=dependency.decomposition_body_digest:raise EvidenceError('payroll witness dependency differs')
    events=tuple(by_id.values());records=_records(events,as_of) if _context is None else _context.records(events,as_of)
    record=next(((event,source,pending) for event,source,pending in records if event.event_id==dependency.source_event_id),None)
    if record is None or record[2]:raise EvidenceError('payroll source is retired or unresolved')
    event,source,pending=record
    net=by_id.get(dependency.net_deposit_event_id)
    if net is None or dependency.net_deposit_date is None or not accepted(dependency.net_deposit_date) or dependency.net_deposit_date!=Field(net.occurred_at,net.provenance.doc_id,net.provenance.page,raw=''):raise EvidenceError('net deposit source provenance differs or unavailable')
    if digest(event.body)!=dependency.source_body_digest or source!=dependency.source:raise EvidenceError('payroll source body dependency differs')
    body=event.body
    for name in ('decomposition_event_id','decomposition_body_digest','net_deposit_event_id','net_deposit_body_digest','net_movement_key','currency'):
        if getattr(dependency,name)!=body[name]:raise EvidenceError('payroll money dependency differs')
    occurrence=source.deductions[dependency.ordinal]
    if occurrence.local_id!=dependency.occurrence_id or occurrence.category.value!='retirement' or not accepted(occurrence.label,occurrence.category,occurrence.amount,occurrence.destination_reference,occurrence.contribution_reference):raise EvidenceError('payroll occurrence unavailable')
    resolve=destination_resolver(events,as_of) if _context is None else _context.destinations(events,as_of)
    if resolve(occurrence.destination_reference)!=(statement.account.value,statement.currency.value) or source.source_reference.value!=row.counterpart_reference.value or source.currency.value!=statement.currency.value or source.pay_date.value!=row.date.value or decimal(occurrence.amount.value)!=decimal(row.amount.value) or occurrence.contribution_reference.value!=row.funding_reference.value:raise EvidenceError('payroll reference identity components differ')
    if witness.reference!=occurrence.contribution_reference or witness.counterpart_reference!=source.source_reference:raise EvidenceError('payroll witness field source differs')
    candidate_rows=tuple(r for r in statement.rows if r.observation_id!=row.observation_id)+(row,)
    matching=[r for r in candidate_rows if r.kind.value=='contribution' and r.funding_witness is not None and getattr(r.funding_witness,'payroll_dependency',None) is not None and r.funding_witness.payroll_dependency.source_event_id==dependency.source_event_id and r.funding_witness.payroll_dependency.occurrence_id==dependency.occurrence_id]
    if len(matching)!=1:raise EvidenceError('payroll occurrence reused by selected plan contributions')
    current={event.event_id:(event,source,pending) for event,source,pending in records}
    for copy in dependency.corroborating_sources:
        candidate=current.get(copy.source_event_id)
        if candidate is None or candidate[2] or digest(candidate[0].body)!=copy.source_body_digest or candidate[1]!=copy.source or _financial_identity(candidate[1])!=_financial_identity(source):raise EvidenceError('payroll corroborating dependency unavailable')
    # Recheck negative coverage: a newly accepted conflicting printed witness
    # must invalidate an old match rather than being ignored by its amount.
    fields={'printed_reference':row.funding_reference,'counterpart_reference':row.counterpart_reference,'date':row.date,'amount':row.amount,'funding_role':row.funding_role_source}
    rebound=bind_payroll(fields,events,destination_account=statement.account.value,destination_reference=replace(statement.account,value=statement.account.raw),currency=statement.currency.value,effective_as_of=as_of,_context=_context)
    if not rebound or rebound['funding_witness']!=witness:raise EvidenceError('payroll reference witness set is changed or ambiguous')
