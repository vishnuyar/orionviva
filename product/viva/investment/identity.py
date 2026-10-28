"""Source identity and conservative full-copy equivalence without lot inference."""
from dataclasses import replace
from collections import defaultdict,deque
from .contracts import *


def number(value,signed=False):
 value=decimal(value,signed)
 if value.is_zero():return '0'
 raw=format(value,'f')
 return raw.rstrip('0').rstrip('.') if '.' in raw else raw


def field(field,numeric=False,signed=False):
 if field is None:return None
 if field.status!='accepted':return (field.status,None)
 return ('accepted',number(field.value,signed) if numeric else field.value)


def row_identity(row):
 return (field(row.date),field(row.kind),field(row.amount,True),field(row.instrument),field(row.realized_gain,True,True),row.funding_role,field(row.funding_role_source),field(row.funding_reference),field(row.counterpart_reference),field(row.printed_reference),field(row.namespace))


def statement_identity(statement):
 return (statement.account.value,statement.currency.value,statement.start.value,statement.end.value,number(statement.opening_cash.value),number(statement.closing_cash.value),statement.disposition,field(statement.explicit_empty),field(statement.printed_reference),tuple(sorted((row_identity(r) for r in statement.rows),key=repr)))


def match_copy_rows(statement,prior):
 """Pair occurrences, preserving repeated equal source rows as separate rows."""
 if statement_identity(statement)!=statement_identity(prior):raise EvidenceError('source copies are not completely equivalent')
 buckets=defaultdict(deque)
 for row in sorted(prior.rows,key=lambda r:r.ordinal):buckets[row_identity(row)].append(row)
 pairs=[]
 for row in sorted(statement.rows,key=lambda r:r.ordinal):
  bucket=buckets[row_identity(row)]
  if not bucket:raise EvidenceError('source copy multiplicity mismatch')
  pairs.append((row,bucket.popleft()))
 if any(buckets.values()):raise EvidenceError('source copy rows incomplete')
 return dict((new.observation_id,old) for new,old in pairs)


def bind_corroborating_copy(statement,known,events):
 if not statement.disposition.startswith('accepted_complete') or statement.corroborates is not None:return statement
 matches=[s for s in known if s.observation_id!=statement.observation_id and s.account.document!=statement.account.document and statement_identity(s)==statement_identity(statement)]
 if not matches:return statement
 choices=[match_copy_rows(statement,s) for s in matches]
 closures={tuple(sorted((new_id,old.cash_event_id,old.cash_body_digest) for new_id,old in choice.items())) for choice in choices}
 if len(closures)!=1:raise EvidenceError('equivalent copies name different accepted cash events')
 old=matches[0];pairs=choices[0];by_id={e.event_id:e for e in events}
 rows=[]
 for row in statement.rows:
  previous=pairs[row.observation_id]
  if row.cash_event_id in by_id and row.cash_event_id!=previous.cash_event_id:raise EvidenceError('copy already has a different cash posting')
  rows.append(replace(row,cash_event_id=previous.cash_event_id,cash_body_digest=previous.cash_body_digest,funding_witness=previous.funding_witness))
 positions=[]
 for position in statement.positions:
  previous=next((candidate for candidate in old.positions if candidate.security_id==position.security_id),None)
  if previous is None:raise EvidenceError('copy security position dependency missing')
  if position.position_event_id not in by_id:
   changes={}
   for name in ('units','value','basis'):
    current=getattr(position,name);prior=getattr(previous,name)
    if current is not None and prior is not None and current.status=='accepted' and prior.status=='accepted' and decimal(current.value,True)!=decimal(prior.value,True):changes[name]=replace(current,status='conflicted',grade='conflicted')
   position=replace(position,position_event_id=previous.position_event_id,position_body_digest=previous.position_body_digest,**changes)
  positions.append(position)
 return replace(statement,rows=tuple(rows),positions=tuple(positions),corroborates=old.observation_id)


def cash_source_document(statement,row,known):
 """Follow only previously accepted full-copy occurrence bindings."""
 by_id={source.observation_id:source for source in known};seen=set()
 while statement.corroborates is not None:
  if statement.observation_id in seen or len(seen)>=120:raise ResourceLimit('copy source dependency limit')
  seen.add(statement.observation_id);prior=by_id.get(statement.corroborates)
  if prior is None:raise EvidenceError('copy ancestor source unavailable')
  previous=match_copy_rows(statement,prior)[row.observation_id]
  if row.cash_event_id!=previous.cash_event_id or row.cash_body_digest!=previous.cash_body_digest:raise EvidenceError('copy ancestor cash mismatch')
  statement,row=prior,previous
 return row.amount.document
