"""Local-only source revision decisions, effective dates and recorded frontiers."""
from dataclasses import dataclass,replace,fields
from datetime import date,timedelta
from copy import deepcopy
from .contracts import *

CHANGE='InvestmentEvidenceChanged'

@dataclass(frozen=True)
class SourceChange:
 change_id: str
 facet: str
 prior_id: str
 prior_document: str
 effective: str
 cause: str
 replacement_id: str | None=None
 def __post_init__(self):
  for value in (self.change_id,self.prior_id,self.prior_document):text(value)
  day(self.effective)
  if self.facet not in ('activity','positions') or self.cause not in ('source_correction','source_retraction'):raise EvidenceError('invalid local source change')
  if (self.cause=='source_retraction')!=(self.replacement_id is None):raise EvidenceError('invalid source replacement identity')
  if self.replacement_id is not None:text(self.replacement_id)


def decode_change(data):
 if type(data) is not dict or set(data)!={f.name for f in fields(SourceChange)}:raise EvidenceError('invalid stored source change')
 return SourceChange(**data)

@dataclass(frozen=True)
class Selection:
 root: str
 facet: str
 statement: object
 status: str
 changes: tuple[str,...]=()

class SourceIndex:
 """Validate recorded predecessor choices before resolving financial dates."""
 def __init__(self,events,statements):
  self._initialize(deepcopy(tuple(events)),deepcopy(tuple(statements)))
 def _initialize(self,events,statements,owned=None):
  from .prefix_proofs import PrefixProofIndex
  proofs=owned
  self.__owned=owned
  self.__events=events
  self.statements={s.observation_id:s for s in statements};self.roots={};self.root_for={};self.heads={};self.changes=[];self._changes_by_root={};seen=set()
  event_map={e.event_id:e for e in events}
  for ordinal,event in enumerate(events):
   if event.event_type=='InvestmentActivityStatementObserved':
    identifier=event.body['observation_id'];source=self.statements[identifier]
    if not event.body.get('source_change_event_ids'):
     for facet in ('activity','positions'):
      key=(facet,identifier);self.roots[key]=identifier;self.root_for[key]=key;self.heads[key]=identifier
   elif event.event_type==CHANGE:
    change=decode_change(event.body['change'])
    if event.occurred_at!=change.effective:raise EvidenceError('source change date mismatch')
    if change.change_id in seen:raise EvidenceError('duplicate source change identity')
    seen.add(change.change_id)
    key=self.root_for.get((change.facet,change.prior_id))
    if key is None or self.heads[key]!=change.prior_id:raise EvidenceError('source predecessor is not current')
    prior=self.statements[change.prior_id]
    if prior.account.document!=change.prior_document:raise EvidenceError('source predecessor document mismatch')
    if change.replacement_id is not None:
     replacement=self.statements.get(change.replacement_id)
     if replacement is None or replacement.account.value!=prior.account.value or replacement.currency.value!=prior.currency.value or replacement.account.document!=prior.account.document:
      raise EvidenceError('source replacement account/document mismatch')
     replacement_event=event_map.get(event.body.get('statement_event_id'))
     if replacement_event is None or replacement_event.event_type!='InvestmentActivityStatementObserved' or replacement_event.body['observation_id']!=change.replacement_id or event.event_id not in replacement_event.body.get('source_change_event_ids',()):raise EvidenceError('source change not atomically attached')
     accepted=self.accepts(replacement,change.facet)
     self.root_for[(change.facet,change.replacement_id)]=key
    else:
     if proofs is None:proofs=PrefixProofIndex(events)
     proof=event.body.get('prefix',{});count=proof.get('event_count')
     if type(count) is not int or count!=ordinal or encode(proofs.proof(count))!=proof:raise EvidenceError('source retraction prefix mismatch')
     accepted=True
    if accepted:self.heads[key]=change.replacement_id
    self.changes.append((key,change,accepted));self._changes_by_root.setdefault(key,[]).append((change,accepted))
 @property
 def events(self):
  return deepcopy(self.__events)
 @staticmethod
 def accepts(statement,facet):
  return statement.snapshot_complete if facet=='positions' else statement.disposition.startswith('accepted_complete')
 def validate_new(self,change,replacement=None):
  key=self.root_for.get((change.facet,change.prior_id))
  if key is None or self.heads[key]!=change.prior_id:raise EvidenceError('source predecessor is not current')
  prior=self.statements[change.prior_id]
  if change.prior_document!=prior.account.document:raise EvidenceError('source predecessor document mismatch')
  if replacement is not None and (change.replacement_id!=replacement.observation_id or replacement.account.value!=prior.account.value or replacement.currency.value!=prior.currency.value or replacement.account.document!=prior.account.document):raise EvidenceError('source replacement account/document mismatch')
  if any(c.change_id==change.change_id for _,c,_ in self.changes):raise EvidenceError('source change ID collision')
 def select(self,facet,as_of):
  day(as_of);selections=[]
  for key,original in self.roots.items():
   if key[0]!=facet:continue
   chosen=original;pending=[]
   for change,accepted in self._changes_by_root.get(key,()):
    if change.effective>as_of:continue
    if accepted:chosen=change.replacement_id;pending=[]
    else:pending.append(change.change_id)
   if chosen is not None:
    statement=self.statements[chosen]
    status='pending' if pending else 'accepted' if self.accepts(statement,facet) else 'incomplete'
    selections.append(Selection(key[1],facet,statement,status,tuple(pending)))
  return tuple(selections)
 def copy_supported(self,statement,selections,active):
  if statement.corroborates in active:return True
  from .identity import statement_identity
  key=self.root_for.get(('activity',statement.corroborates))
  parent=next((item.statement for item in selections if item.root==key[1] and item.status=='accepted'),None) if key else None
  return parent is not None and parent.observation_id in active and statement_identity(statement)==statement_identity(parent) and statement.account.raw==parent.account.raw
 def project(self,facet,as_of,resolve_reference):
  from .payroll import _OwnedFundingRunner
  if not hasattr(self,'_funding_runner'):
   self._funding_runner=(_OwnedFundingRunner(self.__events,resolve_reference) if self.__owned is None else
                         _OwnedFundingRunner._from_owned(self.__owned,resolve_reference))
  activity=self.select('activity',as_of);active={s.statement.observation_id for s in activity if s.status=='accepted'}
  while True:
   invalid={s.statement.observation_id for s in activity if s.statement.observation_id in active and s.statement.corroborates is not None and not self.copy_supported(s.statement,activity,active)}
   if not invalid:break
   active-=invalid
  out=[]
  for selected in self.select(facet,as_of):
   statement=selected.statement;status=selected.status
   if facet=='activity':
    if statement.corroborates is not None and not self.copy_supported(statement,activity,active):status='dependency_unavailable'
    rows=[]
    for row in statement.rows:
     if row.kind.value=='contribution' and row.funding_role!='reinvestment':
      valid=row.funding_status=='accepted'
      try:self._funding_runner.validate_funding(statement,row,resolve_reference,effective_as_of=as_of)
      except EvidenceError:valid=False
      witness=row.funding_witness
      if witness is not None and witness.source_row_event_id and witness.role not in ('other_broker','retirement_rollover'):
       source=self._funding_runner.source_row_statement_id(witness.source_row_event_id)
       if source not in active:valid=False
      if not valid:row=replace(row,funding_status='conflicted' if row.funding_role!='unknown' else 'unavailable')
     rows.append(row)
    statement=replace(statement,rows=tuple(rows))
   out.append(replace(selected,statement=statement,status=status))
  return tuple(out)
 def segments(self,resolve_reference):
  from .payroll import change_dates
  points=['0001-01-01',*sorted(({c.effective for _,c,_ in self.changes}|set(change_dates(self.__events)))-{'0001-01-01'})];out=[]
  for facet in ('activity','positions'):
   prior={}
   for index,left in enumerate(points):
    right=(date.fromisoformat(points[index+1])-timedelta(days=1)).isoformat() if index+1<len(points) else '9999-12-31'
    for selected in self.project(facet,left,resolve_reference):
     key=(facet,selected.root);identity=(encode(selected.statement),selected.status,selected.changes)
     if key in prior and prior[key][1]==identity and out[prior[key][0]]['to']==(date.fromisoformat(left)-timedelta(days=1)).isoformat():
      out[prior[key][0]]['to']=right
     else:
      out.append({'facet':facet,'root':selected.root,'from':left,'to':right,'statement':selected.statement,'status':selected.status,'changes':selected.changes});prior[key]=(len(out)-1,identity)
  return tuple(out)
