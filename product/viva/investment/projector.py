"""Draft source adapter after ordinary brokerage posting; never posts cash."""
from dataclasses import replace
from decimal import Decimal
from vivacore.verify.normalize import parse_amount,parse_date
from viva.ledger.projection import LedgerProjection
from viva.ledger.postings import brokerage_activity_transaction
from .contracts import *
from .events import accepted,append_from_source,source_index,STATEMENT
from .funding import bind_bank,bind_funding,resolver


def build(facts,account,events,*,locale='en-US',funding=None):
 source=facts.investment_source
 if source is None:raise EvidenceError('investment source extension unavailable')
 from viva.ingest.statement_projector import _resolve
 identity=_resolve(LedgerProjection(events),facts)
 if identity.verdict!='same' or identity.account_id!=account:raise EvidenceError('locked canonical source account differs')
 headers=dict(source.headers)
 def field(raw,path,kind='text'):
  if raw is None:return Field('',facts.doc_id,None,status='unavailable')
  value=raw.raw;status='accepted' if raw.page is not None and value else 'unavailable'
  if kind=='role':value=getattr(raw,'role',raw.raw)
  if kind in ('money','units'):
   parsed=parse_amount(value,locale,facts.currency)
   if parsed.ok:value=str(parsed.decimal())
   else:value='';status='unavailable'
  elif kind=='date':
   parsed=parse_date(value,locale)
   if parsed.ok:value=parsed.value
   else:value='';status='unavailable'
  return Field(value,facts.doc_id,raw.page,status=status,raw=raw.raw)
 account_source=field(headers['account_reference'],'account_reference')
 currency=field(headers['currency'],'currency');start=field(headers['period_start'],'period_start','date');end=field(headers['period_end'],'period_end','date')
 as_of=field(headers['as_of'],'as_of','date')
 if not accepted(account_source,currency,start,end,as_of) or currency.value!=facts.currency or end.value!=facts.as_of or as_of.value!=facts.as_of:raise EvidenceError('source header does not bind accepted statement')
 canonical_account=replace(account_source,value=account)
 opening=field(headers['opening_cash'],'opening_cash','money');closing=field(headers['closing_cash'],'closing_cash','money')
 if accepted(closing) and decimal(closing.value)!=facts.cash:raise EvidenceError('source closing differs from accepted snapshot')
 copy_source=None
 native_closing=[e for e in events if e.event_type=='ClosingBalanceObserved' and e.body.get('account_id')==account and e.provenance.doc_id==facts.doc_id and e.occurred_at==facts.as_of]
 if not native_closing:
  candidates=[selection.statement for selection in source_index(events,resolver(events)).project('activity',facts.as_of,resolver(events)) if selection.status=='accepted' and selection.statement.account.document!=facts.doc_id and selection.statement.account.value==account and selection.statement.currency.value==facts.currency and selection.statement.start.value==start.value and selection.statement.end.value==end.value and selection.statement.snapshot_complete and all(pos.position_event_id for pos in selection.statement.positions)]
  closures={tuple(sorted((row.cash_event_id,row.cash_body_digest) for row in candidate.rows)) for candidate in candidates}
  if len(closures)>1:raise EvidenceError('source copies depend on different cash events')
  if candidates:copy_source=candidates[0]
 by_id={e.event_id:e for e in events}
 source_doc=facts.doc_id
 if copy_source is not None:
  source_doc=copy_source.account.document
  known=source_index(events,resolver(events)).statements
  ancestor=copy_source;seen=set()
  while ancestor.corroborates is not None:
   if ancestor.observation_id in seen:raise EvidenceError('copy dependency cycle')
   seen.add(ancestor.observation_id);ancestor=known[ancestor.corroborates];source_doc=ancestor.account.document
 observed_closing=[e for e in events if e.event_type=='ClosingBalanceObserved' and e.body.get('account_id')==account and e.provenance.doc_id==source_doc and e.occurred_at==facts.as_of]
 if not observed_closing or any(decimal(e.body['amount'],True)!=facts.cash for e in observed_closing):raise EvidenceError('source closing has no compatible committed snapshot')
 positions=[];observed_positions=([by_id[p.position_event_id] for p in copy_source.positions] if copy_source is not None else [e for e in events if e.event_type=='PositionObserved' and e.provenance.doc_id==facts.doc_id and e.body.get('account_id')==account and e.occurred_at==facts.as_of])
 if len(source.positions)!=len(facts.positions) or len(observed_positions)!=len(facts.positions):raise EvidenceError('complete source position multiplicity differs')
 used=set()
 for i,record in enumerate(source.positions):
  fields_by_name={name:field(raw,f'positions/{i}/{name}','units' if name=='units' else 'money' if name in ('market_value','cost_basis') else 'text') for name,raw in record}
  identifier=fields_by_name['identifier'];label=fields_by_name['label']
  if not accepted(identifier):raise EvidenceError('position source identifier unavailable')
  candidates=[e for e in observed_positions if e.event_id not in used and e.body['instrument'] in (identifier.value,label.value if accepted(label) else '')]
  if len(candidates)!=1:raise EvidenceError('position source identifier/label ambiguous')
  event=candidates[0];used.add(event.event_id)
  fact_positions=[p for p in facts.positions if p.instrument==event.body['instrument']]
  if len(fact_positions)!=1:raise EvidenceError('accepted position identity multiplicity differs')
  fact=fact_positions[0]
  if copy_source is None:
   if decimal(event.body['units'],True)!=fact.units or decimal(event.body['market_value'])!=fact.market_value or (None if event.body.get('cost_basis') in (None,'') else decimal(event.body['cost_basis']))!=fact.cost_basis:raise EvidenceError('accepted facts differ from committed position measurement')
  else:
   # A corroborating capture never rewrites the original accepted measurement.
   # Retain each contradictory copied source field as its own local conflict,
   # so unrelated market-value/basis/units claims keep independent status.
   for name,key in (('units','units'),('market_value','market_value'),('cost_basis','cost_basis')):
    value=fields_by_name[name];observed=event.body.get(key)
    if accepted(value) and (observed in (None,'') or decimal(value.value,True)!=decimal(observed,True)):
     fields_by_name[name]=replace(value,status='conflicted',grade='conflicted')
  basis=fields_by_name['cost_basis']
  positions.append(Position(security_identity(account,identifier.value),identifier,fields_by_name['units'],fields_by_name['market_value'],basis,label if accepted(label) else None,event.event_id,digest(event.body)))
 rows=[];cash=([by_id[row.cash_event_id] for row in copy_source.rows] if copy_source is not None else [e for e in events if e.event_type=='TransactionRecorded' and e.provenance.doc_id==facts.doc_id]);used_cash=set();cash_complete=len(source.rows)==len(facts.activity)
 def cash_identity(body):
  from .identity import number
  return {**{key:value for key,value in body.items() if key not in ('description','postings')},'postings':[{**p,'amount':number(p['amount'],True)} for p in body['postings']]}
 for i,(record,activity) in enumerate(zip(source.rows,facts.activity)):
  fields_by_name={name:field(raw,f'rows/{i}/{name}','money' if name in ('amount','reported_realized_gain') else 'date' if name=='date' else 'role' if name=='funding_role' else 'text') for name,raw in record}
  date=fields_by_name['date'];kind=fields_by_name['kind'];amount=fields_by_name['amount'];security=fields_by_name['security_identifier'];gain=fields_by_name['reported_realized_gain']
  if accepted(amount):amount=replace(amount,value=str(decimal(amount.value,True).copy_abs()));fields_by_name['amount']=amount
  if not accepted(date,kind,amount) or date.value!=(activity.date or facts.as_of) or kind.value!=activity.kind or decimal(amount.value)!=activity.amount or (accepted(security) and security.value!=activity.instrument):cash_complete=False;break
  if accepted(gain) and (activity.realized_gain is None or decimal(gain.value,True)!=activity.realized_gain):cash_complete=False;break
  expected=brokerage_activity_transaction(account,activity.kind,activity.amount,activity.description,activity.date or facts.as_of,instrument=activity.instrument,realized_gain=activity.realized_gain)
  candidates=[e for e in cash if e.event_id not in used_cash and e.occurred_at==expected.occurred_at and cash_identity(e.body)==cash_identity(expected.body)]
  if not candidates:cash_complete=False;break
  event=candidates[0];used_cash.add(event.event_id)
  kwargs=(funding(fields_by_name,events) if funding is not None else bind_funding(fields_by_name,events,destination_account=account,destination_reference=account_source,currency=facts.currency)) if kind.value=='contribution' else {}
  kwargs.setdefault('funding_role_source',fields_by_name['funding_role'] if accepted(fields_by_name['funding_role']) else None)
  printed_row=fields_by_name['printed_row_reference']
  kwargs.update(printed_reference=printed_row if accepted(printed_row) else None,namespace=canonical_account if accepted(printed_row) else None,funding_reference=fields_by_name['printed_reference'] if accepted(fields_by_name['printed_reference']) else None,counterpart_reference=fields_by_name['counterpart_reference'] if accepted(fields_by_name['counterpart_reference']) else None)
  rows.append(Row(digest((facts.doc_id,'row',i)),str(i),i,date,kind,amount,security if accepted(security) else None,gain if accepted(gain) else None,event.event_id,digest(event.body),activity.description,**kwargs))
 disposition='held';explicit_empty=None
 if cash_complete and rows and accepted(opening,closing):disposition='accepted_complete_nonempty'
 elif not source.rows and not facts.activity and headers['no_activity'] is not None and accepted(opening,closing):
  assertion=field(headers['no_activity'],'no_activity')
  if accepted(assertion):explicit_empty=replace(assertion,value='true');disposition='accepted_complete_empty'
 if disposition=='held':rows=[]
 observation_id=digest((facts.doc_id,source.schema,source.to_dict(),tuple(encode(row) for row in rows)))
 rows=[replace(row,observation_id=digest((observation_id,'row',row.ordinal))) for row in rows]
 return Statement(observation_id,canonical_account,currency,start,end,opening,closing,tuple(rows),disposition,explicit_empty=explicit_empty,positions=tuple(positions),snapshot_complete=True,as_of=as_of,corroborates=copy_source.observation_id if copy_source is not None else None)


def facet_content(statement,facet):
 """Accepted source meaning per facet, excluding derived observation aliases."""
 record=encode(statement)
 if facet=='activity':
  names=('account','currency','start','end','opening_cash','closing_cash','rows','disposition','explicit_empty','printed_reference','corroborates')
  for row in record['rows']:row.pop('observation_id');row.pop('funding_status')
 else:names=('account','currency','end','positions','snapshot_complete','as_of','corroborates')
 return {name:record[name] for name in names}


def append(ledger,facts,account,*,locale='en-US',funding=None,resolve_reference=None,changes=()):
 state={}
 def builder(events):
  state['events']=events
  statement=build(facts,account,events,locale=locale,funding=funding)
  # Restoring previously seen content is a new append-only successor of the
  # current source, never a duplicate of its retired historical observation.
  index=source_index(events,resolver(events))
  current={}
  for facet in ('activity','positions'):
   selected=[item.statement for item in index.select(facet,'9999-12-31') if item.statement.account.document==facts.doc_id and item.statement.account.value==account]
   if len(selected)>1:raise EvidenceError('ambiguous current source revision')
   if selected:current[facet]=selected[0]
  for facet in ('activity','positions'):
   if facet not in current and any(key[0]==facet and index.statements[original].account.document==facts.doc_id and index.statements[original].account.value==account for key,original in index.roots.items()):raise EvidenceError('retired source facet requires explicit supported revision')
  if len(current)==2 and all(facet_content(current[facet],facet)==facet_content(statement,facet) for facet in current):return current['activity']
  prior=[event for event in events if event.event_type==STATEMENT and event.body.get('observation_id')==statement.observation_id]
  if prior:
   if not current:raise EvidenceError('retired source requires explicit supported revision')
   identifier=digest(('investment-source-content-successor',tuple((facet,value.observation_id) for facet,value in sorted(current.items())),statement.observation_id,tuple((facet,facet_content(statement,facet)) for facet in ('activity','positions'))))
   statement=replace(statement,observation_id=identifier,rows=tuple(replace(row,observation_id=digest((identifier,'row',row.ordinal))) for row in statement.rows))
  return statement
 def resolve(field):return resolve_reference(field) if resolve_reference is not None else resolver(state['events'])(field)
 return append_from_source(ledger,builder,resolve,changes)


def heal(ledger,facts,account,*,locale='en-US',funding=None):
 """Evidence-only accepted counterpart arrival; no cash or payroll mutation."""
 from .events import source_index,STATEMENT,CHANGE
 from .lifecycle import SourceChange,decode_change
 def changes(events,statement):
  prior_event=next((e for e in events if e.event_type==STATEMENT and e.body['observation_id']==statement.observation_id),None)
  if prior_event is not None:
   by_id={e.event_id:e for e in events}
   return tuple(decode_change(by_id[event_id].body['change']) for event_id in prior_event.body.get('source_change_event_ids',()))
  index=source_index(events,resolver(events));changes=[]
  for facet in ('activity','positions'):
   selected=[selection.statement for selection in index.select(facet,'9999-12-31') if selection.statement.account.document==facts.doc_id and selection.statement.account.value==account]
   if len(selected)>1:raise EvidenceError('ambiguous current source predecessor')
   if not selected:continue
   prior=selected[0]
   if facet_content(prior,facet)==facet_content(statement,facet):continue
   changes.append(SourceChange(digest(('counterpart-heal',facet,prior.observation_id,statement.observation_id)),facet,prior.observation_id,facts.doc_id,facts.as_of,'source_correction',statement.observation_id))
  return tuple(changes)
 return append(ledger,facts,account,locale=locale,funding=funding,changes=changes)
