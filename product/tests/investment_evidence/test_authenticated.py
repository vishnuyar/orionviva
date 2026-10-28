from dataclasses import replace
import pytest
from viva.ledger.ledger import Ledger
from viva.ledger.events import Event
from viva.read_store import ReadStore
from viva.read_store.store import ReadStoreError,ReadStoreDegraded
from viva.investment.events import append_statement
from viva.investment.contracts import Request,EvidenceError
from viva.investment.authenticated import synchronize,read
from test_draft import fixture,resolve,ACCOUNT

def populate(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 events,s=fixture()
 for e in events:ledger.append(e)
 append_statement(ledger,s,resolve)
 return ledger

def request():return Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none')

def test_real_authenticated_encrypted_store_reads_and_suffix_publication(tmp_path):
 ledger=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  first=synchronize(reads,ledger.store,resolve)
  with reads.open_reader() as old:
   result=read(reads,old,request())
   assert next(f['value'] for f in result['figures'] if f['claim']=='disposed_cost_basis')=='35'
   ledger.append(Event('TestUnrelatedEvent','2025-12-31',{}))
   second=synchronize(reads,ledger.store,resolve)
   assert second.source_count==first.source_count+1
   with pytest.raises(ReadStoreError):read(reads,old,request())
  with reads.open_reader() as current:
   refreshed=read(reads,current,request())
   assert refreshed['authenticated_revision']==current.generation!=result['authenticated_revision']
   assert {k:v for k,v in refreshed.items() if k!='authenticated_revision'}=={k:v for k,v in result.items() if k!='authenticated_revision'}
   assert reads.authenticated_source_identity(current)['count']==len(tuple(ledger.events()))
 with ReadStore.open(tmp_path/'reads','synthetic-only') as reopened:
  with reopened.open_reader() as revision:
   restored=read(reopened,revision,request())
   assert restored['authenticated_revision']==revision.generation==refreshed['authenticated_revision']
   assert restored==refreshed


def test_real_publication_failure_preserves_old_authenticated_generation_and_retry(tmp_path):
 ledger=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store,resolve)
  with reads.open_reader() as previous:
   before=read(reads,previous,request());identity=reads.authenticated_source_identity(previous)
   ledger.append(Event('TestUnrelatedEvent','2025-12-31',{}))
   with pytest.raises(ReadStoreDegraded):synchronize(reads,ledger.store,resolve,fail_at='before_metadata_advance')
   assert reads.authenticated_source_identity(previous)==identity
   assert read(reads,previous,request())==before
  synchronize(reads,ledger.store,resolve)
  with reads.open_reader() as current:
   refreshed=read(reads,current,request())
   assert refreshed['authenticated_revision']==current.generation!=before['authenticated_revision']
   assert {k:v for k,v in refreshed.items() if k!='authenticated_revision'}=={k:v for k,v in before.items() if k!='authenticated_revision'}


def test_capture_advance_never_publishes_mixed_investment_and_readstore_frontier(tmp_path):
 ledger=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store,resolve)
  ledger.append(Event('TestUnrelatedEvent','2025-12-31',{}))
  native=ledger.store.committed_snapshot
  def raced():
   snapshot=native();ledger.append(Event('TestConcurrentEvent','2025-12-31',{}));return snapshot
  ledger.store.committed_snapshot=raced
  with pytest.raises(ReadStoreDegraded):synchronize(reads,ledger.store,resolve)
  ledger.store.committed_snapshot=native
  synchronize(reads,ledger.store,resolve)
  with reads.open_reader() as current:
   assert read(reads,current,request())['coverage']['complete']
