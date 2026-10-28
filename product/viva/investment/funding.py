"""Ordinary accepted account-reference and bank cash witness binding.

Payroll and investment-to-investment source role witnesses remain separate.
"""
from dataclasses import replace
from .contracts import Field,FundingWitness,digest,decimal
from .events import accepted


def resolver(events):
 def resolve(field):
  if not accepted(field):return None
  matches={e.body['account_id'] for e in events if e.event_type=='FinancialAccountReferenceObserved' and e.body.get('scope')=='account' and e.body.get('reference')==field.value and type(e.provenance.page) is int and e.provenance.page>0}
  return next(iter(matches)) if len(matches)==1 else None
 return resolve


def bind_bank(fields,events):
 reference=fields['printed_reference'];counterpart=fields['counterpart_reference'];date=fields['date'];amount=fields['amount']
 if not accepted(reference,counterpart,date,amount):return {}
 role=fields.get('funding_role')
 if accepted(role) and role.value!='own_bank':return {}
 account=resolver(events)(counterpart)
 accounts=[e for e in events if e.event_type=='AccountOpened' and e.body.get('account_id')==account]
 if len(accounts)!=1 or accounts[0].body.get('kind')!='depository':return {}
 candidates=[]
 for event in events:
  if event.event_type!='TransactionRecorded' or event.body.get('source_reference')!=reference.value or event.occurred_at!=date.value or type(event.provenance.page) is not int or event.provenance.page<1:continue
  legs=[p for p in event.body.get('postings',()) if p.get('account')==account]
  if len(legs)==1 and decimal(legs[0]['amount'],True)==-decimal(amount.value):candidates.append(event)
 if len(candidates)!=1:return {}
 event=candidates[0]
 source_refs=[e for e in events if e.event_type=='FinancialAccountReferenceObserved' and e.body.get('account_id')==account and e.body.get('reference')==counterpart.value and e.body.get('scope')=='account' and type(e.provenance.page) is int and e.provenance.page>0]
 if not source_refs:return {}
 source=source_refs[-1]
 witness=FundingWitness(Field(reference.value,event.provenance.doc_id,event.provenance.page,raw=reference.value),Field(counterpart.value,source.provenance.doc_id,source.provenance.page,raw=counterpart.value),account,'own_bank',event.event_id,digest(event.body))
 return {'funding_role':'own_bank','funding_role_source':role if accepted(role) else replace(counterpart,value='own_bank'),'funding_witness':witness}


def bind_funding(fields,events,*,destination_account,destination_reference,currency,effective_as_of='9999-12-31',_context=None,preferred_witness=None):
    role=fields.get('funding_role')
    if accepted(role) and role.value=='reinvestment':return {'funding_role':'reinvestment','funding_role_source':role}
    bank=bind_bank(fields,events)
    if bank:return bank
    other=bind_investment(fields,events,destination_account=destination_account,destination_reference=destination_reference,currency=currency,effective_as_of=effective_as_of,_context=_context,preferred_witness=preferred_witness)
    if other:return other
    from .payroll import bind_payroll
    try:return bind_payroll(fields,events,destination_account=destination_account,destination_reference=destination_reference,currency=currency,effective_as_of=effective_as_of,_context=_context)
    except ValueError:return {}


def bind_investment(fields,events,*,destination_account,destination_reference,currency,effective_as_of='9999-12-31',_context=None,preferred_witness=None):
 """Bind a printed opposing withdrawal; date/magnitude alone never join it."""
 role=fields.get('funding_role');reference=fields['printed_reference'];counterpart=fields['counterpart_reference'];when=fields['date'];amount=fields['amount']
 if not accepted(role,reference,counterpart,when,amount,destination_reference) or role.value not in ('other_broker','retirement_rollover') or not reference.value or not counterpart.value:return {}
 from .payroll import destination_resolver
 header_resolve=destination_resolver(events,effective_as_of) if _context is None else _context.destinations(events,effective_as_of)
 header=header_resolve(counterpart)
 matches={e.body['account_id'] for e in events if e.event_type=='FinancialAccountReferenceObserved' and e.body.get('scope')=='account' and e.body.get('reference')==counterpart.value and type(e.provenance.page) is int and 1<=e.provenance.page<=200}
 if header is not None:matches.add(header[0])
 if len(matches)!=1 or header is None or header[1]!=currency:return {}
 account=next(iter(matches))
 if account==destination_account:return {}
 opened=[e for e in events if e.event_type=='AccountOpened' and e.body.get('account_id')==account]
 if len(opened)!=1 or opened[0].body.get('kind')!='investment' or opened[0].body.get('currency')!=currency:return {}
 from .events import source_index,ROW
 from .identity import statement_identity
 index=source_index(events,resolver(events)) if _context is None else _context.source_index(events)
 selections=index.select('activity',effective_as_of)
 active={selection.statement.observation_id for selection in selections if selection.status=='accepted'}
 while True:
  invalid={selection.statement.observation_id for selection in selections if selection.statement.observation_id in active and selection.statement.corroborates is not None and not index.copy_supported(selection.statement,selections,active)}
  if not invalid:break
  active-=invalid
 periods={}
 for selection in selections:
  source=selection.statement
  if source.account.value!=account or source.currency.value!=currency or not source.start.value<=when.value<=source.end.value:continue
  if selection.status!='accepted' or source.observation_id not in active:return {}
  periods.setdefault((source.start.value,source.end.value),[]).append(source)
 if len(periods)!=1:return {}
 sources=next(iter(periods.values()))
 if len({statement_identity(source) for source in sources})!=1:return {}
 by_id={event.event_id:event for event in events};candidates=[]
 for source in sources:
  if not source.disposition.startswith('accepted_complete') or source.account.raw!=counterpart.value:return {}
  for opposing in source.rows:
   if opposing.kind.value!='withdrawal' or not accepted(opposing.date,opposing.amount,opposing.funding_reference,opposing.counterpart_reference,opposing.funding_role_source):continue
   if opposing.funding_reference.value!=reference.value:continue
   # A matching printed transfer reference with incompatible components holds
   # the relationship; it cannot be ignored in favor of a convenient amount.
   if opposing.date.value!=when.value or decimal(opposing.amount.value)!=decimal(amount.value) or opposing.counterpart_reference.value not in {destination_reference.value,destination_reference.raw} or opposing.funding_role_source.value!=role.value:return {}
   cash=by_id.get(opposing.cash_event_id)
   if cash is None or digest(cash.body)!=opposing.cash_body_digest:return {}
   row_events=[event for event in events if event.event_type==ROW and event.body.get('statement_id')==source.observation_id and event.body.get('row',{}).get('observation_id')==opposing.observation_id]
   if len(row_events)!=1:return {}
   candidates.append((source,opposing,cash,row_events[0]))
 if not candidates:return {}
 economic={(opposing.cash_event_id,opposing.cash_body_digest) for source,opposing,cash,row_event in candidates}
 if len(economic)!=1:return {}
 candidates=[item for item in candidates if item[2].provenance.doc_id==item[1].funding_reference.document]
 if not candidates:return {}
 source,opposing,cash,row_event=candidates[0]
 witness=FundingWitness(opposing.funding_reference,replace(source.account,value=source.account.raw),account,role.value,cash.event_id,digest(cash.body),row_event.event_id)
 if preferred_witness is not None and preferred_witness.role==witness.role and preferred_witness.counterpart_account==witness.counterpart_account and preferred_witness.transaction_id==witness.transaction_id and preferred_witness.transaction_digest==witness.transaction_digest and preferred_witness.reference==witness.reference and preferred_witness.counterpart_reference==witness.counterpart_reference and preserved_opposing_witness(preferred_witness,source,opposing,index,events):witness=preferred_witness
 return {'funding_role':role.value,'funding_role_source':role,'funding_witness':witness}


def cash_coverage_content(statement):
 """Cash proof excludes attribution metadata that cannot alter settled cash."""
 from .contracts import encode
 header={name:encode(getattr(statement,name)) for name in ('account','currency','start','end','opening_cash','closing_cash','explicit_empty')}
 rows=[{name:encode(getattr(row,name)) for name in ('date','kind','amount','instrument','realized_gain','cash_event_id','cash_body_digest')} for row in statement.rows]
 return (header,statement.disposition,sorted(rows,key=lambda item:item['cash_event_id']))


def preserved_opposing_witness(witness,current_source,current_row,index,events):
 """An unrelated attribution revision does not retire an unchanged cash proof."""
 from .events import ROW,decode_row
 event=next((event for event in events if event.event_id==witness.source_row_event_id),None)
 if event is None or event.event_type!=ROW:return False
 source=index.statements.get(event.body.get('statement_id'))
 if source is None or index.root_for.get(('activity',source.observation_id))!=index.root_for.get(('activity',current_source.observation_id)):return False
 original=decode_row(event.body['row'])
 names=('date','kind','amount','instrument','realized_gain','funding_reference','counterpart_reference','funding_role_source','cash_event_id','cash_body_digest')
 return cash_coverage_content(source)==cash_coverage_content(current_source) and all(getattr(original,name)==getattr(current_row,name) for name in names)
