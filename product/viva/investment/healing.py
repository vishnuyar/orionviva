"""Evidence-only nonpayroll bank counterpart arrival through normal ingestion."""
from dataclasses import replace
from .contracts import digest,EvidenceError,Field
from .events import append_from_source,source_index,validate_funding
from .funding import resolver,bind_bank,bind_funding
from .lifecycle import SourceChange


def heal_root(ledger,root):
 state={}
 def build(events):
  resolve=resolver(events);state['resolve']=resolve
  index=source_index(events,resolve)
  from .payroll import FundingValidationContext
  context=FundingValidationContext(events,tuple(index.statements.values()))
  selected=next((selection for selection in index.project('activity','9999-12-31',resolve) if selection.root==root),None)
  if selected is None or selected.status!='accepted':return None
  current=selected.statement;rows=[];changed=False;by_id={e.event_id:e for e in events}
  for row in current.rows:
   replacement=row
   if row.kind.value=='contribution':
    unknown=Field('',row.amount.document,None,status='unavailable')
    kwargs=bind_funding({'printed_reference':row.funding_reference or unknown,'counterpart_reference':row.counterpart_reference or unknown,'date':row.date,'amount':row.amount,'funding_role':row.funding_role_source or unknown},events,destination_account=current.account.value,destination_reference=replace(current.account,value=current.account.raw),currency=current.currency.value,_context=context,preferred_witness=row.funding_witness)
    if kwargs:
     proposed=replace(row,**kwargs,funding_status='accepted')
     if proposed==row:rows.append(row);continue
     try:validate_funding(current,proposed,by_id,resolve,_context=context)
     except EvidenceError:pass
     else:replacement=proposed;changed=True
   rows.append(replacement)
  if not changed:return None
  identifier=digest(('accepted-bank-counterpart',root,current.observation_id,tuple(rows)))
  rows=tuple(replace(row,observation_id=digest((identifier,'row',row.ordinal))) for row in rows)
  statement=replace(current,observation_id=identifier,rows=rows)
  state['change']=(SourceChange(digest(('accepted-bank-counterpart-change',current.observation_id,identifier)),'activity',current.observation_id,current.account.document,current.end.value,'source_correction',identifier),)
  return statement
 return append_from_source(ledger,build,lambda field:state['resolve'](field),lambda events,statement:state['change'])


def heal_after_source(ledger,source_doc_id):
 """Discover relevant roots; each actual mutation rechecks its locked prefix."""
 events=tuple(ledger.events());resolve=resolver(events)
 new_transfers={e.body.get('source_reference') for e in events if e.event_type=='TransactionRecorded' and e.provenance.doc_id==source_doc_id and e.body.get('source_reference')}
 new_accounts={e.body.get('reference') for e in events if e.event_type=='FinancialAccountReferenceObserved' and e.provenance.doc_id==source_doc_id and e.body.get('scope')=='account'}
 from .payroll import OBSERVED,decode_source
 payroll_refs={row.contribution_reference.value for e in events if e.event_type==OBSERVED and e.provenance.doc_id==source_doc_id for row in decode_source(e.body['source']).deductions}
 new_transfers|=payroll_refs
 new_transfers|={row['funding_reference']['value'] for event in events if event.event_type=='InvestmentActivityStatementObserved' and event.provenance.doc_id==source_doc_id for row in event.body['statement']['rows'] if row.get('funding_reference') is not None}
 plan_sources={e.body['statement']['account']['value'] for e in events if e.event_type=='InvestmentActivityStatementObserved' and e.provenance.doc_id==source_doc_id}
 if not new_transfers and not new_accounts and not plan_sources:return 0
 index=source_index(events,resolve)
 copy_roots=[item.root for item in index.select('activity','9999-12-31') if item.statement.corroborates is not None]
 copy_changes=0
 for root in copy_roots:
  if heal_copy_root(ledger,root):copy_changes+=1
 if copy_changes:events=tuple(ledger.events());resolve=resolver(events)
 index=source_index(events,resolve);targets=[]
 for selected in index.project('activity','9999-12-31',resolve):
  if selected.status!='accepted':continue
  if any(row.kind.value=='contribution' and ((row.funding_reference is not None and row.funding_reference.value in new_transfers) or (row.counterpart_reference is not None and row.counterpart_reference.value in new_accounts) or (selected.statement.account.value in plan_sources and row.funding_status!='accepted')) for row in selected.statement.rows):targets.append(selected.root)
 count=copy_changes
 for root in sorted(set(targets)):
  if heal_root(ledger,root):count+=1
 # One bounded copy pass after originals advance covers either arrival order;
 # this is not a historical query-time replay or an unbounded fixpoint.
 if count>copy_changes:
  for root in copy_roots:
   if heal_copy_root(ledger,root):count+=1
 return count


def heal_copy_root(ledger,root):
 """Rebind equivalent accepted copy proof to its parent's current successor."""
 state={}
 def build(events):
  from .identity import statement_identity,match_copy_rows
  resolve=resolver(events);state['resolve']=resolve;index=source_index(events,resolve)
  selected=next((item for item in index.select('activity','9999-12-31') if item.root==root),None)
  if selected is None or selected.status!='accepted' or selected.statement.corroborates is None:return None
  current=selected.statement;key=index.root_for.get(('activity',current.corroborates))
  if key is None:return None
  parent=next((item for item in index.project('activity','9999-12-31',resolve) if item.root==key[1] and item.status=='accepted'),None)
  if parent is None or parent.statement.observation_id==current.corroborates:return None
  parent=parent.statement
  if current.account.raw!=parent.account.raw:return None
  # A copy can predate an accepted counterpart. Rebind its own source fields,
  # never substitute the parent's printed role or references.
  from .payroll import FundingValidationContext
  context=FundingValidationContext(events,tuple(index.statements.values()))
  rows=[]
  for row in current.rows:
   if row.kind.value=='contribution':
    unknown=Field('',row.amount.document,None,status='unavailable')
    bound=bind_funding({'printed_reference':row.funding_reference or unknown,'counterpart_reference':row.counterpart_reference or unknown,'date':row.date,'amount':row.amount,'funding_role':row.funding_role_source or unknown},events,destination_account=current.account.value,destination_reference=replace(current.account,value=current.account.raw),currency=current.currency.value,_context=context,preferred_witness=row.funding_witness)
    if bound:row=replace(row,**bound,funding_status='accepted')
   rows.append(row)
  candidate=replace(current,rows=tuple(rows))
  if statement_identity(candidate)!=statement_identity(parent):return None
  pairs=match_copy_rows(candidate,parent)
  if any((row.cash_event_id,row.cash_body_digest)!=(pairs[row.observation_id].cash_event_id,pairs[row.observation_id].cash_body_digest) for row in current.rows):return None
  if {(p.security_id,p.position_event_id,p.position_body_digest) for p in current.positions}!={(p.security_id,p.position_event_id,p.position_body_digest) for p in parent.positions}:return None
  identifier=digest(('accepted-copy-successor',root,current.observation_id,parent.observation_id))
  rows=tuple(replace(row,observation_id=digest((identifier,'row',row.ordinal))) for row in candidate.rows)
  statement=replace(current,observation_id=identifier,rows=rows,corroborates=parent.observation_id)
  relevant={parent.observation_id};effective=current.end.value
  for _,change,_ in reversed(index.changes):
   if change.replacement_id in relevant:relevant.add(change.prior_id);effective=max(effective,change.effective)
  state['changes']=(SourceChange(digest(('accepted-copy-successor-change',current.observation_id,identifier)),'activity',current.observation_id,current.account.document,effective,'source_correction',identifier),)
  return statement
 try:return append_from_source(ledger,build,lambda field:state['resolve'](field),lambda events,statement:state['changes'])
 except EvidenceError:return ()
