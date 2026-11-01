"""Offline fixture: real parser/post/default-sync/registered annual read sizing."""
import json,calendar,hashlib
import pytest
from decimal import Decimal
from pathlib import Path
from test_payroll_counterpart import payroll_data,sf
from test_extraction import legacy
from viva.ingest.paystub import from_paystub_json
from viva.ingest.paystub_projector import post_paystub
from viva.ingest.brokerage import from_brokerage_json
from viva.ingest.brokerage_projector import post_brokerage
from viva.ledger import Ledger
from viva.ledger.events import account_opened,Provenance
from viva.ledger.postings import simple_transaction
from viva.read_store import ReadStore
from viva.tools import default_registry
from contextlib import contextmanager
from viva.investment.lineage import expand_dependencies,expand_fields


def populate(temporary,document_sha=False):
 ledger=Ledger.open(temporary/'events.jsonl','synthetic-only')
 ledger.append(account_opened('checking','depository','Test checking','USD','2021-01-01'))
 for month in range(1,13):
  start=f'2021-{month:02}-01';end=f'2021-{month:02}-{calendar.monthrange(2021,month)[1]}';pay=f'2021-{month:02}-25';ref=f'CONTRIBUTION-{month:02}'
  data=payroll_data();data.update(pay_date_raw=pay,period_start_raw=start,period_end_raw=end)
  data['payroll_source']['headers']['pay_date']=sf(pay)
  data['payroll_source']['deductions'][2]['contribution_reference']=sf(ref)
  packet=json.dumps(data)
  payroll_doc=hashlib.sha256(packet.encode()).hexdigest() if document_sha else f'payroll-month-{month:02}'
  p,error=from_paystub_json(packet,payroll_doc,'en-US','USD');assert error is None
  bank_packet=json.dumps({'account':'checking','date':pay,'amount':'12450.00','description':'Test employer deposit'})
  bank_doc=hashlib.sha256(bank_packet.encode()).hexdigest() if document_sha else f'bank-month-{month:02}'
  ledger.append(simple_transaction('checking','12450.00','Test employer deposit',pay,provenance=Provenance(doc_id=bank_doc,page=1)))
  assert post_paystub(ledger,p).action=='posted'
  data=legacy();data.update(institution='Test broker',account_number='TEST-1234',account_ref='Test account',as_of_raw=end,opening_cash_raw=str(975*(month-1)),cash_raw=str(975*month),total_raw=str(1000*month),positions=[{'instrument':'TEST-SEC','units_raw':str(Decimal('1.25')*month),'market_value_raw':str(25*month),'cost_basis_raw':str(20*month),'page':1}],activity=[{'date_raw':pay,'kind':'contribution','amount_raw':'1000','description':'Employee contribution'},{'date_raw':pay,'kind':'buy','amount_raw':'25','instrument':'TEST-SEC','description':'Investment'}])
  from test_payroll_counterpart import plan_facts
  source=plan_facts().investment_source.to_dict();h=source['headers'];h.update(period_start=sf(start),period_end=sf(end),as_of=sf(end),opening_cash=sf(data['opening_cash_raw']),closing_cash=sf(data['cash_raw']))
  for row in source['rows']:row['date']=sf(pay)
  source['rows'][0]['printed_reference']=sf(ref)
  source['positions'][0].update(units=sf(data['positions'][0]['units_raw']),market_value=sf(data['positions'][0]['market_value_raw']),cost_basis=sf(data['positions'][0]['cost_basis_raw']))
  data['investment_source']=source
  packet=json.dumps(data)
  plan_doc=hashlib.sha256(packet.encode()).hexdigest() if document_sha else f'plan-month-{month:02}'
  f,error=from_brokerage_json(packet,plan_doc,'en-US','USD');assert error is None
  f.validated_source_page_count=1
  posted=post_brokerage(ledger,f);assert posted.action=='posted',posted
  # Same evidence-only hook invoked by normal ingest.pipeline after source append.
  from viva.investment.healing import heal_after_source
  heal_after_source(ledger,f.doc_id)
 return ledger,posted.account


@pytest.mark.parametrize('document_sha',[False,True],ids=['labels','sha256-json-packets'])
def test_complete_annual_payroll_dependency_payload_default_authenticated_registered_read(tmp_path,document_sha):
 # SHA variant uses actual synthetic JSON packet SHA, not a fabricated PDF identity.
 ledger,account=populate(tmp_path,document_sha)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  reads.synchronize(ledger.store)
  @contextmanager
  def supplier():
   with reads.open_reader() as revision:yield revision
  registry=default_registry(ledger.projection(),today='2026-01-01',instrument_scope=supplier)
  # Registered tool entry owns the authenticated held revision/run seal.
  from test_wire import execute_wire
  wire,bound,program,registry=execute_wire(ledger,reads,'investment_activity_totals',{'account_phrase':'Test account','from':'2021-01-01','to':'2021-12-31','grouping':'year'},('investment_contribution',),'Show Test account contributions from 2021-01-01 to 2021-12-31 with year grouping.')
  assert len(wire['figures'])==1 and Decimal(wire['figures'][0]['value'])==Decimal('12000')
