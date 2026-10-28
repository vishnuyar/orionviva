import sqlite3
from dataclasses import replace
from viva.tools import default_registry
from viva.ledger import LedgerProjection
from viva.ledger.ledger import Ledger
from viva.answer_program import CapabilityManifest,ProgramValidator,ProgramExecutor,DeterministicBinder,AnswerResourcePolicy
from viva.investment.events import append_statement
from viva.investment.sql import materialize
from viva.investment.tool import spec
from viva.investment.semantic import lower
from test_draft import fixture,resolve,ACCOUNT


def test_faithful_units_and_basis_compile_through_real_binder(tmp_path):
 events,s=fixture();ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for e in events:ledger.append(e)
 append_statement(ledger,s,resolve);connection=sqlite3.connect(':memory:',check_same_thread=False);frontier=materialize(connection,tuple(ledger.events()),resolve)
 registry=default_registry(ledger.projection());token=registry.instrument_runtime.run_token
 registry.register(spec(connection,frontier,token,'2026-01-01'))
 manifest=CapabilityManifest.from_registry(registry)
 program=lower(manifest,{'view':'positions','account':ACCOUNT,'currency':'USD','as_of':'2025-12-31'},('security_units','holding_cost_basis'))
 validation=ProgramValidator(manifest,AnswerResourcePolicy()).validate(program)
 assert validation.ok,validation.to_dict()
 execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,'Show the selected account holdings and basis at the stated snapshot date.')
 bound=DeterministicBinder(registry,'en-US').bind(program,execution)
 assert bound.result.answered,(bound.unbound,bound.result.detail)
 assert '1.25' in bound.result.text and '20.00' in bound.result.text
 assert {f['quantity'] for f in bound.result.figures}=={'security_units','holding_cost_basis'}


def test_two_brokers_distinct_activity_totals_compile_without_global_income(tmp_path):
 from decimal import Decimal
 from viva.ledger.postings import brokerage_activity_transaction,simple_transaction
 from viva.ledger.events import Provenance
 from viva.investment.contracts import digest
 from test_draft import f
 first,a=fixture();other='Assets:BrokerOther';second,b=fixture(account=other,doc='other-source',sid='other-statement')
 updated=[];rows=[]
 for row in b.rows:
  amount='200' if row.kind.value=='contribution' else '7' if row.kind.value=='dividend' else '40'
  gain='5' if row.kind.value=='sell' else None
  cash=brokerage_activity_transaction(other,row.kind.value,amount,row.description,row.date.value,instrument=row.instrument.value if row.instrument else '',realized_gain=gain,provenance=Provenance(doc_id='other-source',page=2))
  updated.append(cash);extra={}
  if row.kind.value=='contribution':
   transfer=simple_transaction('Assets:BankTest','-200','source funding','2025-12-31',provenance=Provenance(doc_id='other-funding',page=1),source_reference='PRINTED-Y');updated.append(transfer)
   witness=replace(row.funding_witness,reference=f('PRINTED-Y','other-funding',1),counterpart_reference=f('BANK-REF','other-funding',1),transaction_id=transfer.event_id,transaction_digest=digest(transfer.body))
   extra={'funding_reference':f('PRINTED-Y','other-source'),'funding_witness':witness}
  rows.append(replace(row,amount=f(amount,'other-source'),realized_gain=f(gain,'other-source') if gain else None,cash_event_id=cash.event_id,cash_body_digest=digest(cash.body),**extra))
 b=replace(b,closing_cash=f('247','other-source'),rows=tuple(rows))
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for e in first+[e for e in second if e.event_type in ('AccountOpened','PositionObserved')]+updated:ledger.append(e)
 append_statement(ledger,a,resolve);append_statement(ledger,b,resolve)
 connection=sqlite3.connect(':memory:',check_same_thread=False);frontier=materialize(connection,tuple(ledger.events()),resolve)
 for account,expected in [(ACCOUNT,{'investment_contribution':'100','investment_dividend':'3','sale_proceeds':'30','disposed_cost_basis':'35','realized_gain':'-5'}),(other,{'investment_contribution':'200','investment_dividend':'7','sale_proceeds':'40','disposed_cost_basis':'35','realized_gain':'5'})]:
  registry=default_registry(ledger.projection());registry.register(spec(connection,frontier,registry.instrument_runtime.run_token,'2026-01-01'))
  manifest=CapabilityManifest.from_registry(registry)
  p=lower(manifest,{'view':'activity_totals','account':account,'currency':'USD','from':'2025-01-01','to':'2025-12-31','grouping':'year'},tuple(expected))
  validation=ProgramValidator(manifest,AnswerResourcePolicy()).validate(p);assert validation.ok,validation.to_dict()
  ex=ProgramExecutor(registry,AnswerResourcePolicy()).execute(p,'Show the selected brokerage annual activity totals for the stated year.')
  bound=DeterministicBinder(registry,'en-US').bind(p,ex)
  assert bound.result.answered,(bound.unbound,bound.result.detail)
  assert {f['quantity']:f['value'] for f in bound.result.figures}==expected
  assert all(f['subject']=={'account_id':account} for f in bound.result.figures)
  assert '2025' in bound.result.text


def test_equal_value_security_selector_cannot_cross_holding_or_account(tmp_path):
 from viva.investment.contracts import Position,security_identity,digest
 from test_draft import f
 from viva.answer_program.schema import AnswerProgram
 events,s=fixture();other=replace(s.positions[0],security_id=security_identity(ACCOUNT,'OTHER-SEC'),identifier=f('OTHER-SEC'))
 from viva.ledger.events import position_observed,Provenance
 observed=position_observed(ACCOUNT,'OTHER-SEC','1.25','25','USD','2025-12-31',cost_basis='20',provenance=Provenance(doc_id='source',page=2))
 events.append(observed);other=replace(other,position_event_id=observed.event_id,position_body_digest=digest(observed.body))
 s=replace(s,positions=(*s.positions,other));ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for e in events:ledger.append(e)
 append_statement(ledger,s,resolve);connection=sqlite3.connect(':memory:',check_same_thread=False);frontier=materialize(connection,tuple(ledger.events()),resolve)
 registry=default_registry(ledger.projection());registry.register(spec(connection,frontier,registry.instrument_runtime.run_token,'2026-01-01'))
 manifest=CapabilityManifest.from_registry(registry)
 p=lower(manifest,{'view':'positions','account':ACCOUNT,'currency':'USD','as_of':'2025-12-31'},('security_units',))
 data=p.to_dict();clause=data['shape']['clauses'][0];clause['slots'][0].update(type='security_units',quantity='security_units',scope=['account','security'])
 binding=data['bindings'][0];binding['reference_kind']='figure';binding['selector'].update(cardinality='one',entity_ref={'id':ACCOUNT,'security_id':s.positions[0].security_id})
 p=AnswerProgram.from_dict(data);validation=ProgramValidator(manifest,AnswerResourcePolicy()).validate(p);assert validation.ok,validation.to_dict()
 ex=ProgramExecutor(registry,AnswerResourcePolicy()).execute(p,'Show the selected source security units.')
 bound=DeterministicBinder(registry,'en-US').bind(p,ex)
 assert bound.result.answered,(bound.unbound,bound.result.detail)
 assert len(bound.result.figures)==1 and bound.result.figures[0]['subject']['security_id']==s.positions[0].security_id
 data['bindings'][0]['selector']['entity_ref']['security_id']=security_identity('Assets:Other', 'TEST-SEC')
 swapped=AnswerProgram.from_dict(data);refused=DeterministicBinder(registry,'en-US').bind(swapped,ex)
 assert not refused.result.answered


def test_security_name_correction_preserves_account_local_identity(tmp_path):
 from viva.investment.lifecycle import SourceChange
 from test_lifecycle import successor
 from test_draft import f
 events,s=fixture();s=replace(s,positions=(replace(s.positions[0],label=f('Old source label')),))
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for e in events:ledger.append(e)
 append_statement(ledger,s,resolve);new=successor(s);new=replace(new,positions=(replace(new.positions[0],label=f('Corrected source label')),))
 change=SourceChange('label','positions',s.observation_id,'source','2025-12-31','source_correction',new.observation_id)
 append_statement(ledger,new,resolve,(change,));connection=sqlite3.connect(':memory:',check_same_thread=False);frontier=materialize(connection,tuple(ledger.events()),resolve)
 registry=default_registry(ledger.projection());registry.register(spec(connection,frontier,registry.instrument_runtime.run_token,'2026-01-01'))
 manifest=CapabilityManifest.from_registry(registry);p=lower(manifest,{'view':'positions','account':ACCOUNT,'currency':'USD','as_of':'2025-12-31'},('security_units',))
 validation=ProgramValidator(manifest,AnswerResourcePolicy()).validate(p);assert validation.ok,validation.to_dict()
 ex=ProgramExecutor(registry,AnswerResourcePolicy()).execute(p,'Show the selected source units.');answer=DeterministicBinder(registry,'en-US').bind(p,ex)
 assert answer.result.answered and 'Corrected source label' in answer.result.text
 assert answer.result.figures[0]['subject']['security_id']==s.positions[0].security_id
 entities=[e for e in ex.graph.ground.entities.values() if e['kind']=='security']
 assert len(entities)==1 and entities[0]['security_id']==s.positions[0].security_id and entities[0]['name']=='Corrected source label'
