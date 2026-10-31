"""Evidence-only nonpayroll bank counterpart arrival through normal ingestion."""
from dataclasses import replace
from weakref import WeakKeyDictionary,ref
from ..ledger.ledger import _stage_capability,_stage_on_invalidation
from .contracts import digest,EvidenceError,Field
from .events import append_from_source,source_index,validate_funding
from .funding import resolver,bind_bank,bind_funding
from .lifecycle import SourceChange


class _HealingBasis:
 def __init__(self,events,*,owned=False):
  self._owned=owned
  self.events=events
  self.resolve=resolver(events)
  self.index=source_index(events,self.resolve)
  self._activity=None
  self._context=None
  self.by_id={event.event_id:event for event in events}
 def _initialize(self,events,resolve,index,runner):
  self._owned=True
  self.events=events
  self.resolve=resolve
  self.index=index
  self._activity=None
  self._context=None
  self._runner=runner
  self.by_id={event.event_id:event for event in events}
 def activity(self):
  if self._activity is None:
   self._activity=self.index.project('activity','9999-12-31',self.resolve)
  return self._activity
 def context(self):
  if hasattr(self,'_runner'):return self._runner()
  if self._context is None:
   from .payroll import FundingValidationContext,_OwnedFundingRunner
   self._context=(_OwnedFundingRunner(self.events,self.resolve) if self._owned else
                  FundingValidationContext(self.events,tuple(self.index.statements.values())))
  return self._context
 def bind(self,fields,**parameters):
  if self._owned:return self.context().bind_funding(fields,**parameters)
  return bind_funding(fields,self.events,_context=self.context(),**parameters)
 def validate(self,statement,row):
  if self._owned:return self.context().validate_funding(statement,row,self.resolve)
  return validate_funding(statement,row,self.by_id,self.resolve,_context=self.context())


_planning = WeakKeyDictionary()


def _stage_noop(ledger,root,*,copy=False):
 # Only this trusted algorithm can inspect the private cached planning state;
 # no caller-supplied callback, projection, index or event tuple crosses here.
 stamp=_stage_capability(ledger)
 if stamp is None:return False
 held=_planning.get(ledger)
 if held is None or held[0]!=stamp:
  from .payroll import _OwnedFundingRunner
  events=tuple(ledger.events())
  basis=_OwnedFundingRunner(events,resolver(events))
  if _stage_capability(ledger)!=stamp:return False
  _planning[ledger]=(stamp,basis)
  weak_stage=ref(ledger)
  def invalidate():
   stage=weak_stage()
   if stage is not None:_planning.pop(stage,None)
  if not _stage_on_invalidation(ledger,invalidate):
   _planning.pop(ledger,None)
   return False
 else:basis=held[1]
 try:planned=basis._healing_plan(root,copy=copy)
 except BaseException:
  _planning.pop(ledger,None)
  raise
 return planned is None and _stage_capability(ledger)==stamp


def _root_plan(basis,root):
 events,resolve,index=basis.events,basis.resolve,basis.index
 context=basis.context()
 selected=next((selection for selection in basis.activity() if selection.root==root),None)
 if selected is None or selected.status!='accepted':return None
 current=selected.statement;rows=[];changed=False;by_id=basis.by_id
 for row in current.rows:
  replacement=row
  if row.kind.value=='contribution':
   unknown=Field('',row.amount.document,None,status='unavailable')
   kwargs=basis.bind({'printed_reference':row.funding_reference or unknown,'counterpart_reference':row.counterpart_reference or unknown,'date':row.date,'amount':row.amount,'funding_role':row.funding_role_source or unknown},destination_account=current.account.value,destination_reference=replace(current.account,value=current.account.raw),currency=current.currency.value,preferred_witness=row.funding_witness)
   if kwargs:
    proposed=replace(row,**kwargs,funding_status='accepted')
    if proposed==row:rows.append(row);continue
    try:basis.validate(current,proposed)
    except EvidenceError:pass
    else:replacement=proposed;changed=True
  rows.append(replacement)
 if not changed:return None
 identifier=digest(('accepted-bank-counterpart',root,current.observation_id,tuple(rows)))
 rows=tuple(replace(row,observation_id=digest((identifier,'row',row.ordinal))) for row in rows)
 statement=replace(current,observation_id=identifier,rows=rows)
 changes=(SourceChange(digest(('accepted-bank-counterpart-change',current.observation_id,identifier)),'activity',current.observation_id,current.account.document,current.end.value,'source_correction',identifier),)
 return statement,changes


def _copy_plan(basis,root):
 from .identity import statement_identity,match_copy_rows
 events,resolve,index=basis.events,basis.resolve,basis.index
 selected=next((item for item in index.select('activity','9999-12-31') if item.root==root),None)
 if selected is None or selected.status!='accepted' or selected.statement.corroborates is None:return None
 current=selected.statement;key=index.root_for.get(('activity',current.corroborates))
 if key is None:return None
 parent=next((item for item in basis.activity() if item.root==key[1] and item.status=='accepted'),None)
 if parent is None or parent.statement.observation_id==current.corroborates:return None
 parent=parent.statement
 if current.account.raw!=parent.account.raw:return None
 # A copy can predate an accepted counterpart. Rebind its own source fields,
 # never substitute the parent's printed role or references.
 context=basis.context()
 rows=[]
 for row in current.rows:
  if row.kind.value=='contribution':
   unknown=Field('',row.amount.document,None,status='unavailable')
   bound=basis.bind({'printed_reference':row.funding_reference or unknown,'counterpart_reference':row.counterpart_reference or unknown,'date':row.date,'amount':row.amount,'funding_role':row.funding_role_source or unknown},destination_account=current.account.value,destination_reference=replace(current.account,value=current.account.raw),currency=current.currency.value,preferred_witness=row.funding_witness)
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
 changes=(SourceChange(digest(('accepted-copy-successor-change',current.observation_id,identifier)),'activity',current.observation_id,current.account.document,effective,'source_correction',identifier),)
 return statement,changes


def heal_root(ledger,root):
 if _stage_noop(ledger,root):return ()
 state={}
 def build(events):
  basis=_HealingBasis(events)
  planned=_root_plan(basis,root)
  if planned is None:return None
  statement,changes=planned
  state.update(resolve=basis.resolve,change=changes)
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
 if copy_changes:
  events=tuple(ledger.events());resolve=resolver(events);index=source_index(events,resolve)
 targets=[]
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
  basis=_HealingBasis(events)
  planned=_copy_plan(basis,root)
  if planned is None:return None
  statement,changes=planned
  state.update(resolve=basis.resolve,changes=changes)
  return statement
 try:
  if _stage_noop(ledger,root,copy=True):return ()
  return append_from_source(ledger,build,lambda field:state['resolve'](field),lambda events,statement:state['changes'])
 except EvidenceError:return ()
