"""Capture genuine backend receipts; positive wire is never hand-constructed."""
import json
import os
from pathlib import Path
from contextlib import contextmanager
from dataclasses import replace
import pytest
from viva.ledger.ledger import Ledger
from viva.ledger.events import account_opened,Provenance,document_captured,read_recorded
from viva.ledger.postings import simple_transaction
from viva.ledger.instruments import reference_event
from viva.ingest.instrument_contracts import Source
from viva.ingest.brokerage import from_brokerage_json
from viva.ingest.raw_store import RawStore
from viva.ingest.brokerage_projector import post_brokerage
from viva.read_store import ReadStore
from viva.tools import default_registry
from viva.answer_program import CapabilityManifest,ProgramValidator,ProgramExecutor,DeterministicBinder,AnswerResourcePolicy
from viva.answer_program.intents import SemanticFamilyRegistry,SEMANTIC_REQUEST_VERSION
from viva.answer_program.schema import QuestionContext
from viva.session import Turn
from viva.surface.conversation import conversation
from viva.speak import _shown
from viva.investment.authenticated import synchronize
from test_extraction import fixture,legacy,ROW

def capture_dir(tmp_path):
 path=Path(os.environ['ORIONVIVA_INVESTMENT_EVIDENCE_DIR']) if os.environ.get('ORIONVIVA_INVESTMENT_EVIDENCE_DIR') else tmp_path/'evidence'
 path.mkdir(parents=True,exist_ok=True)
 return path

def source_packet(unknown_basis=False):
 data=legacy();data.update(institution='Test broker',account_number='TEST-1234',account_ref='Test account',opening_cash_raw='0.00',cash_raw='108.00',total_raw='133.00')
 data['activity']=[{'date_raw':'01/25/2025','kind':'contribution','amount_raw':'100.00','description':'Contribution source'},{'date_raw':'01/25/2025','kind':'buy','amount_raw':'25.00','instrument':'TEST-SEC','description':'Test security purchase'},{'date_raw':'01/25/2025','kind':'sell','amount_raw':'30.00','realized_gain_raw':'-5.00','instrument':'TEST-SEC','description':'Test sale with reported loss'},{'date_raw':'01/25/2025','kind':'dividend','amount_raw':'3.00','instrument':'TEST-SEC','description':'Test dividend'}]
 source=fixture();source['headers']['closing_cash']={'raw':'108.00','page':1};source['positions'][0]['cost_basis']={'raw':'20.00','page':None if unknown_basis else 1};rows=[]
 for i,activity in enumerate(data['activity']):
  row={key:None for key in ROW}
  row.update(printed_row_reference={'raw':'SOURCE-ROW-'+str(i),'page':1},date={'raw':activity['date_raw'],'page':1},kind={'raw':activity['kind'],'page':1},amount={'raw':activity['amount_raw'],'page':1})
  if activity.get('instrument'):row['security_identifier']={'raw':activity['instrument'],'page':1}
  if activity.get('realized_gain_raw'):row['reported_realized_gain']={'raw':activity['realized_gain_raw'],'page':1}
  if activity['kind']=='contribution':row.update(printed_reference={'raw':'PRINTED-X','page':1},counterpart_reference={'raw':'BANK-REF','page':1})
  rows.append(row)
 source['rows']=rows;data['investment_source']=source
 return data


def execute_wire(ledger,reads,family,parameters,claims,question):
 @contextmanager
 def supplier():
  with reads.open_reader() as revision:yield revision
 registry=default_registry(ledger.projection(),today='2026-01-01',instrument_scope=supplier)
 families=SemanticFamilyRegistry(registry.semantic_entities(),currency_resolver=registry.instrument_currency)
 raw={'request_version':SEMANTIC_REQUEST_VERSION,'outcome':'request','catalog_digest':families.catalog_digest,'entity_catalog_digest':families.entity_catalog_digest,'family':family,'parameters':parameters,'parameter_sources':{key:{'source':'question','quote':value,'derivation':'verbatim'} for key,value in parameters.items()},'requested_claims':list(claims)}
 outcome=families.parse(raw,QuestionContext(question=question,today='2026-01-01'))
 manifest=CapabilityManifest.from_registry(registry);program=families.lower(outcome,manifest)
 checked=ProgramValidator(manifest,AnswerResourcePolicy()).validate(program);assert checked.ok,checked.to_dict()
 execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,question)
 bound=DeterministicBinder(registry,'en-US').bind(program,execution);assert bound.result.answered,(bound.unbound,bound.result.detail)
 turn=Turn(question,bound.result,program=program.to_dict(),validation={"ok":checked.ok})
 wire=conversation(turn,_shown(turn.result),projection=ledger.projection(),turn_id='synthetic-wire-'+family)
 return wire,bound.result,program,registry


def populate(tmp_path,unknown_basis=False,max_fractional=False,annual_report=False):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');raw=RawStore.open(tmp_path/'raw','synthetic-only')
 fixtures=Path(__file__).resolve().parent/'fixtures/investment'
 investment_name='synthetic-investment-annual-report-source.pdf' if annual_report else 'synthetic-investment-max-fractional-source.pdf' if max_fractional else 'synthetic-investment-source.pdf'
 investment_bytes=(fixtures/investment_name).read_bytes();bank_bytes=(fixtures/'synthetic-bank-source.pdf').read_bytes()
 investment_doc=raw.put(investment_bytes);bank_doc=raw.put(bank_bytes)
 for doc,name,data,kind in ((investment_doc,investment_name,investment_bytes,'brokerage_statement'),(bank_doc,'synthetic-bank-source.pdf',bank_bytes,'bank_statement')):
  assert raw.get(doc)==data
  ledger.append(document_captured(doc,name,len(data),kind,1.0,'2025-12-31' if annual_report and doc==investment_doc else '2025-01-31',Provenance(doc_id=doc)))
 ledger.append(account_opened('Assets:BankTest','depository','Test bank','USD','2025-01-01'))
 ledger.append(reference_event('Assets:BankTest','BANK-REF','2025-01-01',Source(bank_doc,1)))
 ledger.append(simple_transaction('Assets:BankTest','-100.00','Bank funding','2025-01-25',provenance=Provenance(doc_id=bank_doc,page=1),source_reference='PRINTED-X',counterparty_reference='BROKER-REF'))
 packet=source_packet(unknown_basis)
 if annual_report:
  packet['as_of_raw']='12/31/2025'
  packet['investment_source']['headers']['period_end']={'raw':'12/31/2025','page':1}
  packet['investment_source']['headers']['as_of']={'raw':'12/31/2025','page':1}
  packet['positions'][0]['classification']={'exposure':'equity','vehicle':'individual_security','exposure_page':1,'vehicle_page':1}
 if max_fractional:
  packet['positions'][0]['units_raw']='123456789012345678.123456789012'
  packet['investment_source']['positions'][0]['units']['raw']='123456789012345678.123456789012'
 reply=json.dumps(packet)
 facts,error=from_brokerage_json(reply,investment_doc,'en-US','USD');assert error is None
 ledger.append(read_recorded(investment_doc,'offline-source-reader-fixture','unreleased-test-source-contract','document',reply,0.0,0,0,True,None,facts.as_of,Provenance(doc_id=investment_doc),usage_reported=False))
 result=post_brokerage(ledger,facts);assert result.action=='posted'
 return ledger,packet


def test_genuine_reader_post_sql_binder_surface_receipts_keep_all_seven_quantities(tmp_path):
 evidence=capture_dir(tmp_path)
 ledger,packet=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  positions,result,program,registry=execute_wire(ledger,reads,'investment_positions',{'account_phrase':'Test account','as_of':'2025-01-31'},('security_units','holding_cost_basis'),'Show Test account holdings and cost basis at 2025-01-31.')
  (evidence/'wire-positions-current.json').write_text(json.dumps(positions,indent=2)+'\n')
  assert {f.get('quantity') for f in positions['figures']}=={'security_units','holding_cost_basis'}
  assert all(f['receipt_ids'] and f['value'] and f['subject']['security_id'] for f in positions['figures'])
  assert all(f['grade']=='unverified' for f in positions['figures'])
  activity,result,program,registry=execute_wire(ledger,reads,'investment_activity_totals',{'account_phrase':'Test account','from':'2025-01-01','to':'2025-01-31','grouping':'none'},('investment_contribution','investment_dividend','sale_proceeds','disposed_cost_basis','realized_gain'),'Show Test account activity from 2025-01-01 to 2025-01-31 with none grouping.')
  (evidence/'wire-activity-current.json').write_text(json.dumps(activity,indent=2)+'\n');(evidence/'wire-reader-source-packet.json').write_text(json.dumps(packet,indent=2)+'\n')
  assert {f['quantity']:f['value'] for f in activity['figures']}=={'investment_contribution':'100.00','investment_dividend':'3.00','sale_proceeds':'30.00','disposed_cost_basis':'35.00','realized_gain':'-5.00'}
  assert all(f['receipt_ids'] and f['currency']=='USD' and f['kind']=='financial' and f['grade']=='unverified' for f in activity['figures'])

@pytest.mark.parametrize('mutation',['account','security','currency','unknown_subject','source_page','source_record','source_field_raw','source_owner','source_row_identity','source_field_group'])
def test_actual_surface_rejects_mutated_subject_currency_and_provenance(tmp_path,mutation):
 import copy
 ledger,packet=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  wire,result,program,registry=execute_wire(ledger,reads,'investment_positions',{'account_phrase':'Test account','as_of':'2025-01-31'},('security_units','holding_cost_basis'),'Show Test account holdings and cost basis at 2025-01-31.')
  assert all(f['evidence_links'][0]['page']=='1' and f['receipt_ids'] for f in wire['figures'])
  changed=copy.deepcopy(result)
  if mutation=='account':changed.figures[0]['subject']['account_id']='acct:wrong'
  elif mutation=='security':changed.figures[0]['subject']['security_id']='wrong-security'
  elif mutation=='currency':changed.figures[0]['currency']='EUR'
  elif mutation=='unknown_subject':changed.figures[0]['subject']['injected']='value'
  elif mutation=='source_page':
   next(iter(changed.transcript[0]['data']['anchors'].values()))['page']=0
  elif mutation=='source_record':changed.figures[0]['record_ids']=['wrong-source-record']
  elif mutation=='source_field_raw':changed.transcript[0]['data']['source_fields']['strings'][0]='changed raw field'
  elif mutation=='source_owner':changed.transcript[0]['data']['source_fields']['owner_shapes'][changed.transcript[0]['data']['source_fields']['records'][0][1]][0]={'multiple':[]}
  elif mutation=='source_row_identity':changed.transcript[0]['data']['source_identities']['observations']['o0']='changed-observation'
  else:changed.transcript[0]['data']['source_field_groups']['g0']=[]
  bad=conversation(Turn('Source mutation',changed),_shown(changed),projection=ledger.projection(),turn_id='mutated-source')
  assert not bad['figures'][0]['receipt_ids']
  assert all(not receipt.get('figure_provenance',{}).get(changed.figures[0]['id']) for receipt in bad['numerical_receipts'])


def test_genuine_unknown_basis_and_saved_page_receipts(tmp_path):
 from viva.surface.conversation import _timeline_turn
 evidence=capture_dir(tmp_path)
 ledger,packet=populate(tmp_path,unknown_basis=True)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  wire,result,program,registry=execute_wire(ledger,reads,'investment_positions',{'account_phrase':'Test account','as_of':'2025-01-31'},('security_units','investment_market_value'),'Show Test account holdings and market value at 2025-01-31.')
  assert {f['quantity'] for f in wire['figures']}=={'security_units','balance'}
  assert any(row['label']=='Investment evidence limit' and 'holding cost basis: unavailable' in row['value'] for receipt in wire['numerical_receipts'] for row in receipt['context'])
  (evidence/'wire-basis-unavailable-current.json').write_text(json.dumps(wire,indent=2)+'\n')
  restored=_timeline_turn({'turn_id':'synthetic-wire-investment_positions','kind':'ask','answer':wire},{},{},ledger.projection())['answer']
  assert restored['figures']==wire['figures']
  assert all(f['evidence_links'][0]['page']=='1' for f in restored['figures'])


def test_genuine_max_fractional_source_units_survive_all_layers(tmp_path):
 evidence=capture_dir(tmp_path)
 ledger,packet=populate(tmp_path,max_fractional=True)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  wire,result,program,registry=execute_wire(ledger,reads,'investment_positions',{'account_phrase':'Test account','as_of':'2025-01-31'},('security_units','holding_cost_basis'),'Show Test account holdings and cost basis at 2025-01-31.')
  units=next(f for f in wire['figures'] if f['quantity']=='security_units')
  assert units['value']=='123456789012345678.123456789012'
  assert units['written']=='123,456,789,012,345,678.123456789012'
  assert units['currency']=='' and units['receipt_ids'] and units['subject']['security_id']
  assert units['evidence_links'][0]['page']=='1'
  (evidence/'wire-max-fractional-current.json').write_text(json.dumps(wire,indent=2)+'\n')
  (evidence/'wire-max-fractional-source-packet.json').write_text(json.dumps(packet,indent=2)+'\n')


def test_default_read_store_synchronization_publishes_investment_evidence(tmp_path):
 ledger,packet=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  first=reads.synchronize(ledger.store)
  assert first.state=='rebuilt'
  wire,result,program,registry=execute_wire(ledger,reads,'investment_positions',{'account_phrase':'Test account','as_of':'2025-01-31'},('security_units','holding_cost_basis'),'Show Test account holdings and cost basis at 2025-01-31.')
  assert {f['quantity'] for f in wire['figures']}=={'security_units','holding_cost_basis'}


@pytest.mark.parametrize('fail_at',['before_metadata_advance','after_metadata_advance','after_database_commit'])
def test_native_investment_publication_failure_preserves_generation_and_recovers(tmp_path,fail_at):
 from viva.ledger.events import Event
 from viva.read_store.store import ReadStoreDegraded,ReadStoreError
 ledger,packet=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  reads.synchronize(ledger.store)
  with reads.open_reader() as old:
   identity=reads.authenticated_source_identity(old)
   ledger.append(Event('TestUnrelatedEvent','2025-02-01',{}))
   with pytest.raises(ReadStoreDegraded):reads.synchronize(ledger.store,fail_at=fail_at)
   assert reads.authenticated_source_identity(old)==identity
  assert reads.synchronize(ledger.store).state=='caught_up'
  wire,_,_,_=execute_wire(ledger,reads,'investment_positions',{'account_phrase':'Test account','as_of':'2025-01-31'},('security_units','holding_cost_basis'),'Show Test account holdings and cost basis at 2025-01-31.')
  assert len(wire['figures'])==2
 with ReadStore.open(tmp_path/'reads','synthetic-only') as reopened:
  assert reopened.synchronize(ledger.store).state=='equal'
  wire,_,_,_=execute_wire(ledger,reopened,'investment_positions',{'account_phrase':'Test account','as_of':'2025-01-31'},('security_units','holding_cost_basis'),'Show Test account holdings and cost basis at 2025-01-31.')
  assert len(wire['figures'])==2


def test_native_equal_and_tool_read_do_not_capture_source_history(tmp_path,monkeypatch):
 ledger,packet=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  reads.synchronize(ledger.store)
  def forbidden():raise AssertionError('unexpected source history capture')
  monkeypatch.setattr(ledger.store,'committed_snapshot',forbidden)
  assert reads.synchronize(ledger.store).state=='equal'
  wire,_,_,_=execute_wire(ledger,reads,'investment_positions',{'account_phrase':'Test account','as_of':'2025-01-31'},('security_units','holding_cost_basis'),'Show Test account holdings and cost basis at 2025-01-31.')
  assert len(wire['figures'])==2


def test_native_capture_cannot_publish_different_frontiers(tmp_path,monkeypatch):
 from viva.ledger.events import Event
 from viva.read_store.store import ReadStoreDegraded
 ledger,packet=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  reads.synchronize(ledger.store)
  ledger.append(Event('TestUnrelatedEvent','2025-02-01',{}))
  native=ledger.store.committed_snapshot
  def raced():
   ledger.append(Event('TestConcurrentEvent','2025-02-01',{}))
   return native()
  monkeypatch.setattr(ledger.store,'committed_snapshot',raced)
  generation=reads.current_generation
  with pytest.raises(ReadStoreDegraded):reads.synchronize(ledger.store)
  assert reads.current_generation==generation
  monkeypatch.setattr(ledger.store,'committed_snapshot',native)
  assert reads.synchronize(ledger.store).state=='caught_up'


def test_genuine_legacy_holdings_count_retains_account_subject_and_source_page(tmp_path):
 evidence=capture_dir(tmp_path)
 ledger,packet=populate(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  reads.synchronize(ledger.store)
  wire,_,_,_=execute_wire(ledger,reads,'investment_positions',{'account_phrase':'Test account','as_of':'2025-01-31'},('investment_holdings_count',),'Show Test account holdings count at 2025-01-31.')
  assert len(wire['figures'])==1
  figure=wire['figures'][0]
  assert figure['quantity']=='count' and figure['value']=='1' and figure['written']=='1'
  assert set(figure['subject'])=={'account_id'} and figure['receipt_ids']
  assert figure['evidence_links'][0]['page']=='1'
  (evidence/'wire-legacy-count-current.json').write_text(json.dumps(wire,indent=2)+'\n')
