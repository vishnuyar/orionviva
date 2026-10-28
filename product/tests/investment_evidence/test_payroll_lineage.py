"""Actual parser/post payroll witnesses retain unavailable source metadata."""
from test_payroll_counterpart import setup,result
from decimal import Decimal
from viva.investment.lineage import expand_fields,figure_field_uses,validate_result,expand_anchors

def test_actual_payroll_witness_retains_all_ordered_source_fields_including_unknowns(tmp_path):
 ledger,f,account=setup(tmp_path)
 value=result(ledger,account);expanded=validate_result(value)
 contribution=next(item for item in value['figures'] if item['claim']=='investment_contribution')
 selected={(record['owners'][owner][1],record['value'],record['raw'],record['page'],record['status']) for identity,owner in figure_field_uses(value,contribution) for record in (expanded[identity],)}
 for ordinal in (0,1,3):
  for name in ('destination_reference','contribution_reference'):
   assert any(path.endswith('/payroll_dependency/source/deductions/'+str(ordinal)+'/'+name) and (v,r,page,status)==('','',None,'unavailable') for path,v,r,page,status in selected)
 assert Decimal(contribution['value'])==Decimal('1000.00') and contribution['grade']=='unverified'
 assert all(anchor['page'] is not None for anchor in expand_anchors(value).values())

def test_actual_payroll_witness_retains_all_authenticated_dependency_scalars(tmp_path):
 from viva.investment.events import committed_statements
 from viva.investment.funding import resolver
 from viva.investment.contracts import encode
 ledger,f,account=setup(tmp_path);events=tuple(ledger.events())
 statements=committed_statements(events,resolver(events))
 dependency=next(row.funding_witness.payroll_dependency for statement in statements for row in statement.rows if row.funding_witness and row.funding_witness.payroll_dependency)
 value=result(ledger,account)
 assert 'funding_dependencies' in value
 from viva.investment.lineage import expand_dependencies
 decoded=expand_dependencies(value)
 actual=next(iter(decoded.values()))
 for name in ('source_event_id','source_body_digest','occurrence_id','ordinal','payroll_identity','decomposition_event_id','decomposition_body_digest','net_deposit_event_id','net_deposit_body_digest','net_movement_key','currency'):
  assert actual['scalars']['/payroll_dependency/'+name]==getattr(dependency,name)
 assert actual['scalars']['/payroll_dependency/source/deductions/2/local_id']==dependency.source.deductions[2].local_id
 assert actual['scalars']['/payroll_dependency/source/deductions/2/ordinal']==2
 contribution=next(item for item in value['figures'] if item['claim']=='investment_contribution')
 assert set(contribution['funding_dependency_ids'])==set(decoded)
 assert all(not item['funding_dependency_ids'] for item in value['figures'] if item['claim']!='investment_contribution')

def test_actual_payroll_all_fields_proof_and_exact_owners_roundtrip(monkeypatch,tmp_path):
 from viva.investment import lineage
 from viva.investment.contracts import digest
 ledger,f,account=setup(tmp_path)
 pooled=result(ledger,account)
 import copy
 captured={};original_pool=lineage.pool
 def capture(value):
  captured['value']=copy.deepcopy(value)
  return original_pool(value)
 with monkeypatch.context() as patch:
  patch.setattr(lineage,'pool',capture)
  result(ledger,account)
 original=captured['value']
 expanded=lineage.validate_result(pooled)
 assert {digest({k:v for k,v in record.items() if k!='owners'}):record for record in expanded.values()}==original['source_fields']
 proofs=lineage.expand_dependencies(pooled)
 assert {digest(proof):proof for proof in proofs.values()}==original['funding_dependencies']
 for actual,before in zip(pooled['figures'],original['figures']):
  actual_uses={(digest({k:v for k,v in expanded[i].items() if k!='owners'}),*expanded[i]['owners'][j]) for i,j in lineage.figure_field_uses(pooled,actual)}
  assert actual_uses==set(before['source_field_uses'])
  assert {digest(proofs[key]) for key in actual['funding_dependency_ids']}==set(before['funding_dependency_ids'])

def test_actual_payroll_includes_matched_bank_deposit_source_page(tmp_path):
 ledger,f,account=setup(tmp_path)
 value=result(ledger,account);expanded=validate_result(value)
 contribution=next(item for item in value['figures'] if item['claim']=='investment_contribution')
 selected={value['anchors'][key]['document'] for key in contribution['anchor_ids']}
 assert 'bank-source' in selected
 bank_fields=[record for record in expanded.values() if record['document']=='bank-source']
 assert len(bank_fields)==1 and bank_fields[0]['page']==1 and bank_fields[0]['value']=='2021-01-25' and bank_fields[0]['raw']==''

def test_missing_net_bank_page_holds_attribution_without_financial_change(tmp_path):
 from test_payroll_counterpart import facts,plan_facts,WHEN
 from viva.ledger import Ledger
 from viva.ledger.events import account_opened,Provenance
 from viva.ledger.postings import simple_transaction
 from viva.ingest.paystub_projector import post_paystub
 from viva.ingest.brokerage_projector import post_brokerage
 from viva.investment.healing import heal_after_source
 from viva.ledger.accounting import financial_statements
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 ledger.append(account_opened('checking','depository','Test checking','USD','2021-01-01'))
 ledger.append(simple_transaction('checking','12450.00','Test employer deposit',WHEN,provenance=Provenance(doc_id='bank-source',page=None)))
 from viva.ledger.events import closing_balance_observed
 ledger.append(closing_balance_observed('checking','12450.00','2021-01-31',provenance=Provenance(doc_id='bank-source',page=1)))
 assert post_paystub(ledger,facts()).action=='posted'
 f=plan_facts();posted=post_brokerage(ledger,f);assert posted.action=='posted'
 before=[(e.event_id,e.body) for e in ledger.events() if e.event_type=='TransactionRecorded']
 heal_after_source(ledger,f.doc_id)
 actual=result(ledger,posted.account)
 assert not any(item['claim']=='investment_contribution' for item in actual['figures'])
 assert {'claim':'investment_contribution','from':'2021-01-01','to':'2021-01-31','status':'incomplete'} in actual['dispositions']
 assert [(e.event_id,e.body) for e in ledger.events() if e.event_type=='TransactionRecorded']==before
 report=financial_statements(ledger.projection())
 assert report['balance_sheet']['by_currency']['USD']['net']=='13450.00'
 assert report['profit_loss']['by_currency']['USD']['income']=='18333.33'
