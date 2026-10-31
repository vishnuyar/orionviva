"""Scratch integration against real authenticated encrypted ReadStore publication.

The extra authenticated snapshot scan is explicit and needs final review/timing;
no raw event mirror or alternate cryptographic identity is persisted.
"""
from viva.ledger.events import Event
from viva.ledger.work_cache import publication_memo_scope
from .contracts import EvidenceError
from .events import LockedEventPrefix
from .sql import materialize,read_sql

PROJECTOR='investment-evidence-scratch-v1'

def synchronize(read_store,event_store,resolve_reference=None,*,fail_at=None):
 snapshot=event_store.committed_snapshot()
 events=tuple(Event.from_dict(entry.event.to_dict()) for entry in snapshot.events)
 if resolve_reference is None:
  from .funding import resolver
  resolve_reference=resolver(events)
 def project(connection,entry):
  if entry.sequence>=len(snapshot.events):raise EvidenceError('canonical prefix advanced during capture')
  captured=snapshot.events[entry.sequence]
  if captured.event_id!=entry.event_id or captured.record_hash!=entry.record_hash:raise EvidenceError('authenticated captured prefix differs')
  if entry.sequence!=len(snapshot.events)-1:return
  with publication_memo_scope():
   materialize(connection,events,resolve_reference)
   connection.execute('CREATE TABLE IF NOT EXISTS investment_evidence_authenticated_source(singleton INTEGER PRIMARY KEY CHECK(singleton=1),source_count INTEGER NOT NULL,source_head TEXT NOT NULL)')
   connection.execute('INSERT OR REPLACE INTO investment_evidence_authenticated_source VALUES(1,?,?)',(snapshot.identity.count,snapshot.identity.head_hash))
 return read_store.synchronize(event_store,apply_event=project,projector_version=PROJECTOR,fail_at=fail_at)

def read(read_store,revision,request,*,deadline=None):
 identity=read_store.authenticated_source_identity(revision)
 source=revision.connection.execute('SELECT source_count,source_head FROM investment_evidence_authenticated_source WHERE singleton=1').fetchone()
 if source!=(identity['count'],identity['head']):raise EvidenceError('investment projection does not belong to authenticated revision')
 frontier=revision.connection.execute('SELECT event_count,last_event_id,prefix_digest FROM investment_evidence_frontier WHERE singleton=1').fetchone()
 if frontier is None or frontier[0]!=identity['count']:raise EvidenceError('investment source frontier missing')
 result=read_sql(revision.connection,request,LockedEventPrefix(*frontier),deadline)
 result['authenticated_revision']=revision.generation
 return result


def materialize_authenticated_snapshot(connection,snapshot):
 """Publish source projections in the native authenticated generation transaction."""
 events=tuple(Event.from_dict(entry.event.to_dict()) for entry in snapshot.events)
 from .funding import resolver
 with publication_memo_scope():
  materialize(connection,events,resolver(events))
  connection.execute('CREATE TABLE IF NOT EXISTS investment_evidence_authenticated_source(singleton INTEGER PRIMARY KEY CHECK(singleton=1),source_count INTEGER NOT NULL,source_head TEXT NOT NULL)')
  connection.execute('INSERT OR REPLACE INTO investment_evidence_authenticated_source VALUES(1,?,?)',(snapshot.identity.count,snapshot.identity.head_hash))
