"""Bounded complete investment views over validated committed observations."""
from dataclasses import asdict,fields as dataclass_fields,is_dataclass,dataclass
from datetime import date,timedelta
from decimal import Decimal,localcontext
from time import monotonic
import json
from .contracts import *
from .events import accepted,all_fields
from .units import units,UnsupportedUnits


def check(deadline):
 if monotonic()>deadline: raise ResourceLimit('investment deadline')


from .identity import row_identity as canonical_row,statement_identity as equivalent,match_copy_rows


def anchor(field):
 return {'document':field.document,'page':field.page,'anchor':field.anchor}


def field_id(field):return digest(anchor(field))


def source_complete(statements,start,end):
 cursor=date.fromisoformat(start);last=date.fromisoformat(end)
 for s in sorted(statements,key=lambda s:s.start.value):
  left,right=date.fromisoformat(s.start.value),date.fromisoformat(s.end.value)
  if left>cursor:return False
  if right>=cursor:cursor=right+timedelta(days=1)
 return cursor>last


@dataclass(frozen=True)
class FieldUse:
 field: Field
 observation: str
 path: str
 required: bool=True


def source_use(field,statement,path,required=True):
 return FieldUse(field,statement.observation_id,path,required)


def source_uses(value,statement,path):
 if type(value) is Field:return [source_use(value,statement,path,required=value.status=="accepted")]
 if is_dataclass(value):return [use for member in dataclass_fields(value) for use in source_uses(getattr(value,member.name),statement,path+'/'+member.name)]
 if type(value) in (tuple,list):return [use for i,item in enumerate(value) for use in source_uses(item,statement,path+'/'+str(i))]
 return []


def read(statements,request,deadline=None):
 deadline=min(deadline,monotonic()+2) if deadline is not None else monotonic()+2
 check(deadline)
 relevant=[s for s in statements if s.account.value==request.account and s.currency.value==request.currency]
 if request.view=='positions':
  relevant=[s for s in relevant if s.snapshot_complete and s.end.value<=request.as_of]
  if not relevant:raise EvidenceError('complete positions unavailable')
  latest=max(s.end.value for s in relevant);relevant=[s for s in relevant if s.end.value==latest]
 else:relevant=[s for s in relevant if s.start.value<=request.end and s.end.value>=request.start]
 if len(relevant)>120: raise ResourceLimit('effective statement limit')
 if sum(len(s.rows) for s in relevant)>1000:raise ResourceLimit('effective activity row limit')
 figures=[];dispositions=[];anchor_pool={};field_pool={};dependency_pool={}
 def emit(claim,value,fields,statement_ids,security=None,start=None,end=None,as_of=None,operands=(),row_ids=(),funding_roles=(),funding_dependency_ids=(),label=None,security_label=None):
  check(deadline)
  uses=tuple(fields)
  if any(type(use) is not FieldUse for use in uses):raise EvidenceError('explicit source field occurrence required')
  fields=tuple(use.field for use in uses)
  supporting=tuple(use.field for use in uses if use.required)
  if not supporting or not accepted(*supporting):raise EvidenceError('requested figure field evidence unavailable')
  for use in uses:
   f=use.field
   if f.page is not None:anchor_pool[field_id(f)]=anchor(f)
   record=field_pool.setdefault(digest(f),{**encode(f),'owners':[]})
   owner=[use.observation,use.path]
   if owner not in record['owners']:record['owners'].append(owner)
  if len({(a['document'],a['page']) for a in anchor_pool.values()})>512:raise ResourceLimit('source document/page anchor limit')
  grade=max((f.grade for f in supporting),key=lambda g:GRADES.index(g))
  f={'id':digest((claim,request.account,security,start,end,as_of,tuple(statement_ids))),
   'claim':claim,'label':label or (('derived disposed cost basis' if claim=='disposed_cost_basis' else claim.replace('_',' '))+((' · '+start+' through '+end) if start else '')),'quantity':claim,'value':str(value),'account':request.account,'currency':None if claim in ('security_units','count') else request.currency,
   'security':security,'security_label':security_label,'from':start,'to':end,'as_of':as_of,'grade':grade,'exact':True,
   'anchor_ids':sorted({field_id(f) for f in fields if f.page is not None}),'source_field_ids':sorted({digest(f) for f in fields}),'source_field_uses':sorted({(digest(use.field),use.observation,use.path) for use in uses}),'observation_ids':list(statement_ids),'operands':list(operands),'row_ids':sorted(set(row_ids)),'funding_roles':sorted(set(funding_roles)),'funding_dependency_ids':sorted(set(funding_dependency_ids))}
  figures.append(f)
  if len(figures)>64:raise ResourceLimit('figure limit')
 if request.view=='positions':
  def positions_key(s):return tuple(sorted((p.security_id,p.identifier.value) for p in s.positions))
  if len({positions_key(s) for s in relevant})!=1:raise EvidenceError('conflicting complete security sets')
  statement=relevant[0];statement_ids=[s.observation_id for s in relevant]
  for p in statement.positions:
   check(deadline)
   copies=[next(pos for pos in s.positions if pos.security_id==p.security_id) for s in relevant]
   if any(not accepted(pos.identifier) for pos in copies):raise EvidenceError('security identity unavailable')
   scopefields=[]
   for s,pos in zip(relevant,copies):
    pi=next(i for i,candidate in enumerate(s.positions) if candidate.security_id==pos.security_id)
    scopefields.append(source_use(pos.identifier,s,'/positions/'+str(pi)+'/identifier'))
    if pos.label is not None and accepted(pos.label):scopefields.append(source_use(pos.label,s,'/positions/'+str(pi)+'/label'))
    scopefields.extend(source_use(getattr(s,name),s,'/'+name) for name in ('account','currency','end','as_of') if getattr(s,name) is not None)
   label=p.label.value if p.label is not None and accepted(p.label) else p.identifier.value
   for claim,attribute in (('security_units','units'),('balance','value'),('holding_cost_basis','basis')):
    source_fields=[getattr(pos,attribute) for pos in copies]
    if any(field is not None and field.status=='conflicted' for field in source_fields):
     dispositions.append({'security':p.security_id,'claim':claim,'status':'conflicted'});continue
    source_fields=[field for field in source_fields if field is not None and accepted(field)]
    if not source_fields:
     dispositions.append({'security':p.security_id,'claim':claim,'status':'unavailable'});continue
    try:
     values=[units(field.value,group_separator="") if claim=='security_units' else str(decimal(field.value)) for field in source_fields]
    except UnsupportedUnits:
     dispositions.append({'security':p.security_id,'claim':claim,'status':'unsupported_units'});continue
    if len({Decimal(value) for value in values})!=1:
     dispositions.append({'security':p.security_id,'claim':claim,'status':'conflicted'});continue
    value_uses=[source_use(getattr(pos,attribute),s,'/positions/'+str(next(i for i,candidate in enumerate(s.positions) if candidate.security_id==pos.security_id))+'/'+attribute) for s,pos in zip(relevant,copies) if getattr(pos,attribute) is not None and accepted(getattr(pos,attribute))]
    emit(claim,values[0],[*value_uses,*scopefields],statement_ids,p.security_id,as_of=statement.end.value,security_label=label,label=label+' · '+claim.replace('_',' ')+' · '+statement.end.value)
  emit('count',len(statement.positions),[source_use(getattr(s,name),s,'/'+name) for s in relevant for name in ('account','end')],statement_ids,as_of=statement.end.value)
 else:
  groups={}
  for statement in relevant:
   check(deadline)
   key=(statement.start.value,statement.end.value)
   groups.setdefault(key,[]).append(statement)
  accepted_statements=[]
  witnesses={};copy_rows={}
  for key,copies in groups.items():
   if len({equivalent(s) for s in copies})!=1:raise EvidenceError('conflicting statement copies')
   selected=copies[0];accepted_statements.append(selected);witnesses[selected.observation_id]=copies
   for copy in copies:
    matched=match_copy_rows(copy,selected)
    for copied in copy.rows:copy_rows[(selected.observation_id,matched[copied.observation_id].observation_id,copy.observation_id)]=copied
  ordered=sorted(accepted_statements,key=lambda s:s.start.value)
  if any(a.end.value>=b.start.value for a,b in zip(ordered,ordered[1:])):raise EvidenceError('overlapping source periods unresolved')
  if not ordered or any(not s.disposition.startswith('accepted_complete') for s in ordered) or not source_complete(ordered,request.start,request.end):raise EvidenceError('activity coverage incomplete')
  years=range(int(request.start[:4]),int(request.end[:4])+1) if request.grouping=='year' else (None,)
  for year in years:
   start=max(request.start,str(year)+'-01-01') if year is not None else request.start
   end=min(request.end,str(year)+'-12-31') if year is not None else request.end
   selected=[s for s in ordered if s.start.value<=end and s.end.value>=start]
   for claim,kind in (('investment_contribution','contribution'),('investment_dividend','dividend'),('sale_proceeds','sell'),('disposed_cost_basis','sell'),('realized_gain','sell')):
    check(deadline);total=Decimal(0);used=[];ids=[];operands=[];row_ids=[];funding_roles=[];dependency_ids=[];unavailable=False
    with localcontext() as ctx:
     ctx.prec=128
     for s in selected:
      ids.extend(copy.observation_id for copy in witnesses[s.observation_id])
      for copy in witnesses[s.observation_id]:used.extend(source_use(getattr(copy,name),copy,'/'+name) for name in ('account','currency','start','end','opening_cash','closing_cash'));used.extend([source_use(copy.explicit_empty,copy,'/explicit_empty')] if copy.explicit_empty else [])
      for r in s.rows:
       # A complete printed statement may contain the requested window.
       # Keep its full coverage witnesses, but count only exact dated rows.
       if not start<=r.date.value<=end or r.kind.value!=kind:continue
       if kind=='contribution' and r.funding_role=='reinvestment':
        if r.funding_status!='accepted' or not accepted(r.funding_role_source) or r.funding_role_source.value!='reinvestment':
         unavailable=True;continue
        row_ids.append(r.observation_id)
        for copy in witnesses[s.observation_id]:
         for copied in (copy_rows[(s.observation_id,r.observation_id,copy.observation_id)],):
          used.extend(source_use(getattr(copied,name),copy,'/rows/'+str(copied.ordinal)+'/'+name) for name in ('date','kind','amount','funding_role_source'));row_ids.append(copied.observation_id)
        continue
       if kind=='contribution' and (r.funding_status!='accepted' or r.funding_role=='unknown' or r.funding_witness is None or not accepted(r.funding_role_source,r.funding_reference,r.counterpart_reference)):
        unavailable=True;continue
       row_ids.append(r.observation_id)
       if kind=='contribution':funding_roles.append(r.funding_role)
       amount=decimal(r.amount.value);rowfields=[source_use(getattr(r,name),s,'/rows/'+str(r.ordinal)+'/'+name) for name in ('date','kind','amount')]
       if kind=='contribution':rowfields.extend(source_use(getattr(r,name),s,'/rows/'+str(r.ordinal)+'/'+name) for name in ('funding_role_source','funding_reference','counterpart_reference'));rowfields.extend(source_use(getattr(r.funding_witness,name),s,'/rows/'+str(r.ordinal)+'/funding_witness/'+name) for name in ('reference','counterpart_reference'))
       if claim in ('realized_gain','disposed_cost_basis'):
        if r.realized_gain is None or not accepted(r.realized_gain):unavailable=True;continue
        gain=decimal(r.realized_gain.value,True);rowfields.append(source_use(r.realized_gain,s,'/rows/'+str(r.ordinal)+'/realized_gain'))
        if amount-gain<0:unavailable=True;continue
        if claim=='realized_gain':amount=gain
        else:
         amount-=gain
         if amount<0:unavailable=True;continue
         operands.append({'row':r.observation_id,'operation':'proceeds_minus_reported_realized_gain','proceeds':r.amount.value,'reported_realized_gain':r.realized_gain.value,'anchor_ids':[field_id(r.amount),field_id(r.realized_gain)]})
       total+=amount
       # Preserve corroborating copies and repeated occurrences, without double counting.
       for copy in witnesses[s.observation_id]:
        for matching in (copy_rows[(s.observation_id,r.observation_id,copy.observation_id)],):
         used.extend(source_uses(matching,copy,'/rows/'+str(matching.ordinal)));row_ids.append(matching.observation_id)
         if kind=='contribution' and matching.funding_witness:
          from .lineage import dependency_scalars
          proof={'observation_id':copy.observation_id,'row_id':matching.observation_id,'scalars':dependency_scalars(matching.funding_witness)}
          proof['scalars'].update({'/plan_cash_event_id':matching.cash_event_id,'/plan_cash_body_digest':matching.cash_body_digest})
          proof_id=digest(proof);dependency_pool[proof_id]=proof;dependency_ids.append(proof_id)
       used.extend(rowfields)
    if unavailable:dispositions.append({'claim':claim,'from':start,'to':end,'status':'incomplete'})
    else:emit(claim,total,used,ids,start=start,end=end,operands=operands,row_ids=row_ids,funding_roles=funding_roles,funding_dependency_ids=dependency_ids)
 result={'view':request.view,'account':request.account,'currency':request.currency,'figures':figures,'anchors':anchor_pool,'source_fields':field_pool,'funding_dependencies':dependency_pool,'dispositions':dispositions,
  'coverage':{'from':request.start,'to':request.end,'as_of':request.as_of,'complete':not dispositions}}
 from .lineage import pool
 result=pool(result)
 if len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode())>32000:raise ResourceLimit('serialized investment result bytes')
 check(deadline);return result
