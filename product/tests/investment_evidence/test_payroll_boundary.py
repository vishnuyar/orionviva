"""Current-product characterization; no investment/payroll semantics repair."""
from decimal import Decimal
import json
import os
from pathlib import Path
from viva.ledger.ledger import Ledger
from viva.ledger.events import account_opened,closing_balance_observed,Provenance
from viva.ledger.postings import simple_transaction,brokerage_activity_transaction
from viva.ledger.accounting import financial_statements
from viva.read_store import ReadStore
from viva.ingest.paystub import PayStubFacts,Deduction
from viva.ingest.paystub_projector import post_paystub


def test_current_payroll_and_plan_accounting_boundary(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 bank='Assets:CheckingTest';plan='Assets:PlanTest';when='2021-01-25'
 ledger.append(account_opened(bank,'depository','Test bank','USD','2021-01-01'))
 ledger.append(account_opened(plan,'investment','Test retirement plan','USD','2021-01-01'))
 ledger.append(simple_transaction(bank,'12450.00','Test employer payroll',when,provenance=Provenance(doc_id='bank-source',page=1)))
 facts=PayStubFacts('payroll-source','pay_stub',1.0,'Test employer','USD',when,'2021-01-01','2021-01-31',Decimal('18333.33'),Decimal('12450.00'),[Deduction('Tax',Decimal('3483.33'),'tax'),Deduction('Payroll tax',Decimal('1100.00'),'tax'),Deduction('Employee retirement',Decimal('1000.00'),'retirement'),Deduction('Insurance',Decimal('300.00'),'insurance')],gross_page=1,net_page=1)
 assert post_paystub(ledger,facts).action=='posted'
 # Existing projection posts the named plan contribution independently.
 ledger.append(brokerage_activity_transaction(plan,'contribution','1000.00','Employee payroll contribution',when,provenance=Provenance(doc_id='plan-source',page=1)))
 ledger.append(closing_balance_observed(bank,'12450.00','2021-01-31',provenance=Provenance(doc_id='bank-source',page=1)))
 ledger.append(closing_balance_observed(plan,'1000.00','2021-01-31',provenance=Provenance(doc_id='plan-source',page=1)))
 events=tuple(ledger.events());replay=ledger.projection()
 def aggregate(events):
  totals={}
  for event in events:
   if event.event_type=='TransactionRecorded':
    for p in event.body['postings']:totals[p['account']]=totals.get(p['account'],Decimal(0))+Decimal(p['amount'])
  return {k:str(v) for k,v in sorted(totals.items())}
 replay_totals=aggregate(events)
 assert Decimal(replay_totals['Income:Salary'])==Decimal('-18333.33')
 assert Decimal(replay_totals['Income:Uncategorized'])==0
 assert Decimal(replay_totals['Assets:Retirement'])==1000
 assert Decimal(replay_totals[plan])==1000
 assert sum(Decimal(v) for k,v in replay_totals.items() if k in ('Assets:Retirement',plan))==2000
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  reads.synchronize(ledger.store)
  with reads.open_reader() as revision:
   identity=reads.authenticated_source_identity(revision)
   rows=revision.connection.execute('SELECT account_id,amount_text FROM postings ORDER BY source_sequence,posting_index').fetchall()
   sql_totals={}
   for account,amount in rows:sql_totals[account]=sql_totals.get(account,Decimal(0))+Decimal(amount)
   sql_totals={k:str(v) for k,v in sorted(sql_totals.items())}
   assert sql_totals==replay_totals
   actual=financial_statements(revision.overview_projection(today='2021-02-01'))
   assert actual==financial_statements(replay)
   assert actual['balance_sheet']['by_currency']['USD']['net']=='13450.00'
   assert {line['account'] for line in actual['balance_sheet']['lines']}=={bank,plan}
   assert actual['profit_loss']['by_currency']['USD']['income']=='18333.33'
   assert actual['profit_loss']['by_currency']['USD']['net']=='13450.00'
 reopened=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 assert aggregate(reopened.events())==replay_totals
 report={'classification':'missing_typed_payroll_plan_attribution_no_networth_doublecount_reproduced','authenticated_source_identity':identity,'replay_and_authenticated_read_store_aggregate':sql_totals,'report':actual,'observed':{'salary_counted_once':True,'net_placeholder_cancelled':True,'raw_two_account_posting_sum_not_household_networth':'2000.00','actual_household_networth':'13450.00','networth_doublecounts_retirement':False,'expected_economic_retirement_contribution':'1000.00'},'notes':['Current PayStubFacts/Deduction discard printed plan and contribution references.','Plan contribution cash posting balances against Transfers:Uncategorized; payroll deduction posts Assets:Retirement.','No ownership or payroll semantics repair applied.']}
 evidence=Path(os.environ['ORIONVIVA_INVESTMENT_EVIDENCE_DIR']) if os.environ.get('ORIONVIVA_INVESTMENT_EVIDENCE_DIR') else tmp_path/'evidence'
 evidence.mkdir(parents=True,exist_ok=True)
 (evidence/'payroll-current-product-repro.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
