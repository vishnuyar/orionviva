import json
from dataclasses import replace
import pytest
from viva.ledger.ledger import Ledger
from viva.ingest.brokerage import from_brokerage_json
from viva.ingest.brokerage_projector import post_brokerage
from viva.read_store import ReadStore
from viva.investment.contracts import EvidenceError,Request
from viva.investment.events import committed_statements,validate_statement
from viva.investment.projector import append
from viva.investment.authenticated import synchronize,read
from test_extraction import fixture,legacy


def facts():
 data=legacy();data.update(institution='Test broker',account_number='TEST-1234',account_ref='Test account',opening_cash_raw='25.00',activity=[{'date_raw':'01/25/2025','kind':'buy','amount_raw':'25.00','instrument':'TEST-SEC','description':'Test security purchase'}])
 source=fixture();source['headers']['opening_cash']={'raw':'25.00','page':1};data['investment_source']=source
 parsed,error=from_brokerage_json(json.dumps(data),'source','en-US','USD');assert error is None
 return parsed


def test_actual_post_source_adapter_position_dependencies_and_authenticated_replay(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=facts()
 result=post_brokerage(ledger,f);assert result.action=='posted'
 cash_before=sum(e.event_type=='TransactionRecorded' for e in ledger.events())
 append(ledger,f,result.account)
 statements=committed_statements(tuple(ledger.events()))
 assert len(statements)==1 and statements[0].positions[0].position_event_id
 assert statements[0].positions[0].position_body_digest
 assert statements[0].positions[0].units.grade=='unverified' # snapshot arithmetic does not prove units
 assert statements[0].positions[0].basis.status=='unavailable' # missing field page stays missing
 assert append(ledger,f,result.account)==[]
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==cash_before
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  with reads.open_reader() as revision:
   actual=read(reads,revision,Request('positions',result.account,'USD',as_of='2025-01-31'))
   assert next(x['value'] for x in actual['figures'] if x['claim']=='security_units')=='1.25'
   assert not any(x['claim']=='holding_cost_basis' for x in actual['figures'])
 reopened=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 assert committed_statements(tuple(reopened.events()))==statements


def test_cash_and_position_body_dependency_mutations_refuse(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=facts();result=post_brokerage(ledger,f)
 append(ledger,f,result.account);events=tuple(ledger.events());statement=committed_statements(events)[0]
 for event_type,key,value in [('PositionObserved','market_value','25.01'),('PositionObserved','units','2'),('PositionObserved','cost_basis','20.01')]:
  altered=tuple(replace(e,body={**e.body,key:value}) if e.event_type==event_type else e for e in events)
  with pytest.raises(EvidenceError):validate_statement(statement,altered)
 changed=replace(statement,positions=(replace(statement.positions[0],position_event_id='missing'),))
 with pytest.raises(EvidenceError):validate_statement(changed,events)


def test_source_identity_is_resolved_inside_append_locked_prefix(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=facts();result=post_brokerage(ledger,f)
 before=tuple(ledger.events())
 with pytest.raises(EvidenceError):append(ledger,f,'Assets:WrongAccount')
 assert tuple(ledger.events())==before


def contribution_facts():
 from test_extraction import ROW
 data=legacy();data.update(institution='Test broker',account_number='TEST-1234',account_ref='Test account',opening_cash_raw='0.00',cash_raw='75.00',total_raw='100.00',activity=[{'date_raw':'01/25/2025','kind':'contribution','amount_raw':'100.00','description':'Contribution source'},{'date_raw':'01/25/2025','kind':'buy','amount_raw':'25.00','instrument':'TEST-SEC','description':'Test security purchase'}])
 source=fixture();source['headers']['closing_cash']={'raw':'75.00','page':1}
 row={key:None for key in ROW};row.update(date={'raw':'01/25/2025','page':1},kind={'raw':'contribution','page':1},amount={'raw':'100.00','page':1},printed_reference={'raw':'PRINTED-X','page':1},counterpart_reference={'raw':'BANK-REF','page':1})
 source['rows'].insert(0,row);data['investment_source']=source
 parsed,error=from_brokerage_json(json.dumps(data),'source','en-US','USD');assert error is None
 return parsed


def test_nonpayroll_bank_counterpart_arrival_heals_only_evidence_no_cash_reposting(tmp_path):
 from viva.ledger.events import account_opened,Provenance
 from viva.ledger.postings import simple_transaction
 from viva.ledger.instruments import reference_event
 from viva.ingest.instrument_contracts import Source
 from viva.investment.projector import heal
 from viva.investment.authority import read as authority_read
 from viva.investment.funding import resolver
 from viva.investment.events import source_index
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=contribution_facts();posted=post_brokerage(ledger,f);append(ledger,f,posted.account)
 req=Request('activity_totals',posted.account,'USD',start='2025-01-01',end='2025-01-31',grouping='none')
 before=authority_read(committed_statements(tuple(ledger.events())),req)
 assert not any(f['claim']=='investment_contribution' for f in before['figures'])
 ledger.append(account_opened('Assets:BankTest','depository','Test bank','USD','2025-01-01'))
 ledger.append(reference_event('Assets:BankTest','BANK-REF','2025-01-01',Source('bank-source',1)))
 ledger.append(simple_transaction('Assets:BankTest','-100.00','Bank funding','2025-01-25',provenance=Provenance(doc_id='bank-source',page=1),source_reference='PRINTED-X',counterparty_reference='BROKER-REF'))
 cash_before=sum(e.event_type=='TransactionRecorded' for e in ledger.events())
 heal(ledger,f,posted.account)
 assert heal(ledger,f,posted.account)==[]
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==cash_before
 events=tuple(ledger.events());index=source_index(events,resolver(events))
 assert len(index.select('activity','2025-01-31'))==1 and len(index.select('positions','2025-01-31'))==1
 assert index.select('activity','2025-01-31')[0].statement.observation_id!=index.select('positions','2025-01-31')[0].statement.observation_id
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  with reads.open_reader() as revision:
   result=read(reads,revision,req)
   figure=next(f for f in result['figures'] if f['claim']=='investment_contribution')
   assert figure['value']=='100.00' and figure['funding_roles']==['own_bank']
   assert any(anchor['document']=='bank-source' for anchor in result['anchors'].values())
 reopened=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 assert len(tuple(reopened.events()))==len(events)
 assert heal(reopened,f,posted.account)==[]


def test_real_post_brokerage_installs_source_without_manual_adapter_and_recovers(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=facts();result=post_brokerage(ledger,f)
 assert len(committed_statements(tuple(ledger.events())))==1
 before=tuple(ledger.events())
 again=post_brokerage(ledger,f)
 assert again.action=='duplicate'
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==sum(e.event_type=='TransactionRecorded' for e in before)
 assert len(committed_statements(tuple(ledger.events())))==1


def test_real_held_activity_correction_installs_non_cash_successor_without_position_repost(tmp_path):
 from decimal import Decimal
 from viva.ingest.brokerage_projector import apply_brokerage_activity_correction
 from viva.investment.events import source_index
 from viva.investment.funding import resolver
 from viva.investment.authority import read as authority_read
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=facts()
 correct=f.activity[0];f=replace(f,activity=[replace(correct,amount=Decimal('24.00'))])
 posted=post_brokerage(ledger,f)
 assert posted.action=='posted'
 initial=tuple(ledger.events());index=source_index(initial,resolver(initial))
 assert index.select('activity','2025-01-31')[0].status=='incomplete'
 position_source=index.select('positions','2025-01-31')[0].statement.observation_id
 assert sum(e.event_type=='TransactionRecorded' for e in initial)==0
 assert len(authority_read(committed_statements(initial,facet='positions'),Request('positions',posted.account,'USD',as_of='2025-01-31'))['figures'])==3
 result=apply_brokerage_activity_correction(ledger,f.doc_id,[correct])
 assert result.action=='posted'
 events=tuple(ledger.events());index=source_index(events,resolver(events))
 assert index.select('activity','2025-01-31')[0].status=='accepted'
 assert index.select('positions','2025-01-31')[0].statement.observation_id==position_source
 assert sum(e.event_type=='PositionObserved' for e in events)==sum(e.event_type=='PositionObserved' for e in initial)
 assert sum(e.event_type=='TransactionRecorded' for e in events)==1
 with pytest.raises(ValueError):apply_brokerage_activity_correction(ledger,f.doc_id,[correct])
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==1
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  with reads.open_reader() as revision:
   actual=read(reads,revision,Request('activity_totals',posted.account,'USD',start='2025-01-01',end='2025-01-31',grouping='none'))
   assert actual['coverage']['complete'] and len(actual['figures'])==5


def test_real_post_cash_commit_before_source_failure_recovers_without_cash_retry(tmp_path,monkeypatch):
 from viva.investment import projector
 from viva.ledger.store import CryptoError
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=facts();native=projector.heal
 def unavailable(*args,**kwargs):raise CryptoError('synthetic evidence append unavailable')
 monkeypatch.setattr(projector,'heal',unavailable)
 with pytest.raises(CryptoError):post_brokerage(ledger,f)
 before=tuple(ledger.events());assert not committed_statements(before)
 cash_count=sum(e.event_type=='TransactionRecorded' for e in before);assert cash_count==1
 monkeypatch.setattr(projector,'heal',native)
 result=post_brokerage(ledger,f);assert result.action=='duplicate'
 assert len(committed_statements(tuple(ledger.events())))==1
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==cash_count


def test_actual_new_capture_full_copy_uses_original_position_and_cash_sources(tmp_path):
 from viva.investment.funding import resolver
 from viva.investment.events import source_index
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=facts();original=post_brokerage(ledger,f)
 before=tuple(ledger.events());copy=replace(f,doc_id='copy-source')
 result=post_brokerage(ledger,copy)
 assert result.action=='duplicate'
 events=tuple(ledger.events());statements=committed_statements(events,resolver(events))
 assert len(statements)==2
 first=next(s for s in statements if s.account.document=='source');second=next(s for s in statements if s.account.document=='copy-source')
 assert second.corroborates==first.observation_id
 assert second.positions[0].position_event_id==first.positions[0].position_event_id
 assert second.rows[0].cash_event_id==first.rows[0].cash_event_id
 assert sum(e.event_type=='TransactionRecorded' for e in events)==sum(e.event_type=='TransactionRecorded' for e in before)
 assert sum(e.event_type=='PositionObserved' for e in events)==sum(e.event_type=='PositionObserved' for e in before)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  with reads.open_reader() as revision:
   actual=read(reads,revision,Request('positions',original.account,'USD',as_of='2025-01-31'))
   assert next(f['value'] for f in actual['figures'] if f['claim']=='security_units')=='1.25'
   assert {anchor['document'] for anchor in actual['anchors'].values()}=={'source','copy-source'}


def test_post_ingest_bank_healer_uses_retained_observation_without_original_facts(tmp_path):
 from viva.ledger.events import account_opened,Provenance
 from viva.ledger.postings import simple_transaction
 from viva.ledger.instruments import reference_event
 from viva.ingest.instrument_contracts import Source
 from viva.investment.healing import heal_after_source
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=contribution_facts();posted=post_brokerage(ledger,f)
 ledger.append(account_opened('Assets:BankTest','depository','Test bank','USD','2025-01-01'))
 ledger.append(reference_event('Assets:BankTest','BANK-REF','2025-01-01',Source('bank-source',1)))
 ledger.append(simple_transaction('Assets:BankTest','-100.00','Bank funding','2025-01-25',provenance=Provenance(doc_id='bank-source',page=1),source_reference='PRINTED-X',counterparty_reference='BROKER-REF'))
 before=sum(e.event_type=='TransactionRecorded' for e in ledger.events())
 assert heal_after_source(ledger,'unrelated-source')==0
 assert heal_after_source(ledger,'bank-source')==1
 assert heal_after_source(ledger,'bank-source')==0
 assert sum(e.event_type=='TransactionRecorded' for e in ledger.events())==before
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  with reads.open_reader() as revision:
   actual=read(reads,revision,Request('activity_totals',posted.account,'USD',start='2025-01-01',end='2025-01-31',grouping='none'))
   assert next(figure['value'] for figure in actual['figures'] if figure['claim']=='investment_contribution')=='100.00'


def test_actual_copy_conflicting_units_hold_only_units_without_reposting(tmp_path):
 from decimal import Decimal
 from viva.investment.extraction import parse
 from viva.investment.authority import read as authority_read
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');original=facts()
 posted=post_brokerage(ledger,original);assert posted.action=='posted'
 before=[(event.event_id,event.body) for event in ledger.events() if event.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]
 source=original.investment_source.to_dict();source['positions'][0]['units']={'raw':'2.00000000','page':1}
 copied=replace(original,doc_id='copy-with-unit-conflict',positions=[replace(original.positions[0],units=Decimal('2'))],investment_source=parse(source))
 result=post_brokerage(ledger,copied);assert result.action=='duplicate'
 statements=committed_statements(tuple(ledger.events()))
 assert len(statements)==2
 assert [(event.event_id,event.body) for event in ledger.events() if event.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]==before
 actual=authority_read(statements,Request('positions',posted.account,'USD',as_of='2025-01-31'))
 assert not any(figure['claim']=='security_units' for figure in actual['figures'])
 assert next(figure['value'] for figure in actual['figures'] if figure['claim']=='balance')=='25.00'
 assert {'security':statements[0].positions[0].security_id,'claim':'security_units','status':'conflicted'} in actual['dispositions']


def test_actual_label_correction_updates_only_positions_and_keeps_entity_and_retries_idempotent(tmp_path):
 from viva.investment.extraction import parse
 from viva.investment.authority import read as authority_read
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');original=facts()
 posted=post_brokerage(ledger,original);assert posted.action=='posted'
 before=[(event.event_id,event.body) for event in ledger.events() if event.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]
 events=tuple(ledger.events());old_activity=committed_statements(events,facet='activity')[0]
 old_position=committed_statements(events,facet='positions')[0]
 source=original.investment_source.to_dict();source['positions'][0]['label']={'raw':'Corrected source label','page':1}
 corrected=replace(original,investment_source=parse(source))
 assert post_brokerage(ledger,corrected).action=='duplicate'
 events=tuple(ledger.events());position=committed_statements(events,facet='positions')[0]
 assert position.positions[0].label.value=='Corrected source label'
 assert position.positions[0].security_id==old_position.positions[0].security_id
 assert committed_statements(events,facet='activity')[0].observation_id==old_activity.observation_id
 length=len(events);assert post_brokerage(ledger,corrected).action=='duplicate';assert len(tuple(ledger.events()))==length
 assert [(event.event_id,event.body) for event in ledger.events() if event.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]==before
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  reads.synchronize(ledger.store)
  from viva.investment.authenticated import read as native_read
  with reads.open_reader() as revision:
   actual=native_read(reads,revision,Request('positions',posted.account,'USD',as_of='2025-01-31'))
   assert next(f['security_label'] for f in actual['figures'] if f['claim']=='security_units')=='Corrected source label'


def test_copy_before_bank_arrival_heals_after_parent_first_without_reposting(tmp_path):
 from viva.ledger.events import account_opened,Provenance
 from viva.ledger.postings import simple_transaction
 from viva.ledger.instruments import reference_event
 from viva.ingest.instrument_contracts import Source
 from viva.investment.events import source_index
 from viva.investment.funding import resolver
 from viva.investment.healing import heal_root,heal_after_source
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=contribution_facts()
 posted=post_brokerage(ledger,f);post_brokerage(ledger,replace(f,doc_id='copy-source'))
 events=tuple(ledger.events());index=source_index(events,resolver(events))
 parent=next(item.root for item in index.select('activity','9999-12-31') if item.statement.account.document=='source')
 ledger.append(account_opened('Assets:BankTest','depository','Test bank','USD','2025-01-01'))
 ledger.append(reference_event('Assets:BankTest','BANK-REF','2025-01-01',Source('bank-source',1)))
 ledger.append(simple_transaction('Assets:BankTest','-100.00','Bank funding','2025-01-25',provenance=Provenance(doc_id='bank-source',page=1),source_reference='PRINTED-X',counterparty_reference='BROKER-REF'))
 financial=[(e.event_id,e.body) for e in ledger.events() if e.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]
 assert heal_root(ledger,parent)
 heal_after_source(ledger,'bank-source')
 events=tuple(ledger.events());index=source_index(events,resolver(events))
 chosen=index.project('activity','9999-12-31',resolver(events))
 assert len(chosen)==2 and all(item.status=='accepted' for item in chosen)
 for item in chosen:
  assert item.statement.rows[0].funding_status=='accepted'
 result=__import__('viva.investment.authority',fromlist=['read']).read(committed_statements(events,resolver(events)),Request('activity_totals',posted.account,'USD',start='2025-01-01',end='2025-01-31',grouping='none'))
 assert next(x['value'] for x in result['figures'] if x['claim']=='investment_contribution')=='100.00'
 assert [(e.event_id,e.body) for e in ledger.events() if e.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]==financial
 count=len(events);assert heal_after_source(ledger,'bank-source')==0;assert len(tuple(ledger.events()))==count
