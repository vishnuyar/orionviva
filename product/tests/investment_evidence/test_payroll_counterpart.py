import copy,json
from decimal import Decimal
from dataclasses import replace
import pytest
from viva.ingest.paystub import from_paystub_json
from viva.ingest.paystub_projector import post_paystub
from viva.ingest.brokerage import from_brokerage_json
from viva.ingest.brokerage_projector import post_brokerage
from viva.ledger import Ledger
from viva.ledger.events import account_opened,Provenance,closing_balance_observed
from viva.ledger.postings import simple_transaction
from viva.ledger.accounting import financial_statements
from viva.investment.contracts import Request
from viva.investment.events import committed_statements
from viva.investment.funding import resolver
from viva.investment.authority import read
from test_source_projector import contribution_facts

WHEN='2021-01-25'
def sf(raw,page=1):return {'raw':raw,'page':page}
def payroll_data():
 rows=[{'label':'Tax','amount_raw':'3483.33','category':'tax'},{'label':'Payroll tax','amount_raw':'1100.00','category':'tax'},{'label':'Employee retirement','amount_raw':'1000.00','category':'retirement'},{'label':'Insurance','amount_raw':'300.00','category':'insurance'}]
 source=[]
 for row in rows:
  source.append({'label':sf(row['label']),'category':sf(row['category']),'amount':sf(row['amount_raw']),'destination_reference':sf('BROKER-REF') if row['category']=='retirement' else None,'contribution_reference':sf('CONTRIBUTION-A') if row['category']=='retirement' else None})
 return {'employer':'Test employer','pay_date_raw':WHEN,'period_start_raw':'2021-01-01','period_end_raw':'2021-01-31','gross_raw':'18333.33','net_raw':'12450.00','gross_page':1,'net_page':1,'deductions':rows,'payroll_source':{'schema':'payroll-source-v1','headers':{'source_reference':sf('PAYROLL-SOURCE'),'currency':sf('USD'),'pay_date':sf(WHEN),'gross':sf('18333.33'),'net':sf('12450.00')},'deductions':source}}

def facts(data=None,doc='payroll-source'):
 value,error=from_paystub_json(json.dumps(data or payroll_data()),doc,'en-US','USD');assert error is None,error
 return value

def plan_facts():
 f=contribution_facts();raw=f.to_dict();f=replace(f,doc_id='plan-source',cash=Decimal('975'),total=Decimal('1000'),as_of='2021-01-31',opening_cash=Decimal(0),activity=[replace(f.activity[0],date=WHEN,amount=Decimal('1000')),replace(f.activity[1],date=WHEN)])
 s=f.investment_source.to_dict();h=s['headers'];h.update(period_start=sf('2021-01-01'),period_end=sf('2021-01-31'),as_of=sf('2021-01-31'),closing_cash=sf('975'))
 for row in s['rows']:row['date']=sf(WHEN)
 s['rows'][0].update(amount=sf('1000'),printed_reference=sf('CONTRIBUTION-A'),counterpart_reference=sf('PAYROLL-SOURCE'),funding_role=sf('external_party'))
 from viva.investment.extraction import parse
 return replace(f,investment_source=parse(s))

def setup(temporary,*,payroll_first=True):
 ledger=Ledger.open(temporary/'events.jsonl','synthetic-only')
 ledger.append(account_opened('checking','depository','Test checking','USD','2021-01-01'))
 ledger.append(simple_transaction('checking','12450.00','Test employer deposit',WHEN,provenance=Provenance(doc_id='bank-source',page=1)))
 ledger.append(closing_balance_observed('checking','12450.00','2021-01-31',provenance=Provenance(doc_id='bank-source',page=1)))
 if payroll_first:assert post_paystub(ledger,facts()).action=='posted'
 f=plan_facts();result=post_brokerage(ledger,f);assert result.action=='posted'
 from viva.investment.healing import heal_after_source
 heal_after_source(ledger,f.doc_id)
 return ledger,f,result.account

def result(ledger,account):
 events=tuple(ledger.events());resolve=resolver(events)
 return read(committed_statements(events,resolve),Request('activity_totals',account,'USD',start='2021-01-01',end='2021-01-31',grouping='none'))

def test_source_parser_retains_every_deduction_occurrence_raw_and_page():
 data=payroll_data();value=facts(data)
 source=getattr(value,'payroll_source',None)
 assert source is not None
 assert source.to_dict()==data['payroll_source'] and len(source.deductions)==4
 assert type(source.deductions) is tuple
 assert dict(source.deductions[2])['contribution_reference'].raw=='CONTRIBUTION-A'


def test_real_payroll_plan_missing_attribution_preserves_existing_financial_results(tmp_path):
 ledger,f,account=setup(tmp_path)
 report=financial_statements(ledger.projection())
 assert report['balance_sheet']['by_currency']['USD']['net']=='13450.00'
 assert report['profit_loss']['by_currency']['USD']['income']=='18333.33'
 actual=result(ledger,account)
 contribution=[f for f in actual['figures'] if f['claim']=='investment_contribution']
 assert len(contribution)==1 and Decimal(contribution[0]['value'])==Decimal('1000.00'),actual
 assert contribution[0]['funding_roles']==['external_party']


def contributions(ledger,account):
 return [item for item in result(ledger,account)['figures'] if item['claim']=='investment_contribution']


def cash_digest(ledger):
 from viva.investment.contracts import digest
 return digest(tuple((e.event_id,e.body) for e in ledger.events() if e.event_type=='TransactionRecorded'))


@pytest.mark.parametrize('mutation',['missing_reference','wrong_reference','wrong_destination','missing_role','different_currency','different_amount','missing_page','legacy'])
def test_unproven_payroll_cannot_acquire_funding_by_amount_date(tmp_path,mutation):
 ledger,plan,account=setup(tmp_path,payroll_first=False)
 data=payroll_data();source=data['payroll_source'];row=source['deductions'][2]
 if mutation=='missing_reference':row['contribution_reference']=None
 if mutation=='wrong_reference':row['contribution_reference']=sf('OTHER')
 if mutation=='wrong_destination':row['destination_reference']=sf('OTHER')
 if mutation=='missing_role':row['category']=None
 if mutation=='different_currency':source['headers']['currency']=sf('EUR')
 if mutation=='different_amount':row['amount']=sf('999.99')
 if mutation=='missing_page':row['contribution_reference']['page']=None
 if mutation=='legacy':del data['payroll_source']
 before=cash_digest(ledger)
 assert post_paystub(ledger,facts(data)).action=='posted'
 # The only new cash posting is the unchanged existing payroll decomposition.
 after=cash_digest(ledger)
 from viva.investment.healing import heal_after_source
 heal_after_source(ledger,'payroll-source')
 assert after==cash_digest(ledger) and not contributions(ledger,account)
 assert financial_statements(ledger.projection())['balance_sheet']['by_currency']['USD']['net']=='13450.00'


def test_arrival_plan_first_then_payroll_heals_once_without_cash_mutation(tmp_path):
 ledger,plan,account=setup(tmp_path,payroll_first=False)
 assert not contributions(ledger,account)
 assert post_paystub(ledger,facts()).action=='posted'
 assert len(contributions(ledger,account))==1
 from viva.investment.healing import heal_after_source
 before=cash_digest(ledger);count=len(tuple(ledger.events()))
 for _ in range(2):heal_after_source(ledger,'payroll-source');heal_after_source(ledger,'plan-source')
 assert cash_digest(ledger)==before and len(tuple(ledger.events()))==count


def test_duplicate_payroll_copy_pools_every_source_without_posting_again(tmp_path):
 ledger,plan,account=setup(tmp_path);before=cash_digest(ledger)
 assert post_paystub(ledger,facts(doc='payroll-copy')).action=='duplicate'
 assert cash_digest(ledger)==before and len(contributions(ledger,account))==1
 from viva.investment.payroll import _records
 assert len(_records(tuple(ledger.events())))==2
 source=committed_statements(tuple(ledger.events()),resolver(tuple(ledger.events())))
 witnesses=[r.funding_witness for s in source for r in s.rows if r.kind.value=='contribution' and r.funding_witness]
 assert witnesses and any(len(w.payroll_dependency.corroborating_sources)==1 for w in witnesses)


def test_missing_and_conflicting_source_correction_holds_only_funding(tmp_path):
 from viva.investment.payroll import append_source
 ledger,plan,account=setup(tmp_path);before=cash_digest(ledger)
 data=payroll_data();data['payroll_source']['deductions'][2]['contribution_reference']=None
 append_source(ledger,facts(data),effective='2021-02-01')
 assert not contributions(ledger,account) and cash_digest(ledger)==before
 assert financial_statements(ledger.projection())['balance_sheet']['by_currency']['USD']['net']=='13450.00'


def test_retraction_is_temporal_and_never_changes_cash(tmp_path):
 from viva.investment.payroll import retract_source,PayrollSourceChange,_records
 ledger,plan,account=setup(tmp_path);before=cash_digest(ledger)
 event,source,pending=_records(tuple(ledger.events()))[0]
 retract_source(ledger,PayrollSourceChange('retract-one',event.event_id,source.document,'2021-02-01','source_retraction'))
 assert len(_records(tuple(ledger.events()),'2021-01-31'))==1
 assert _records(tuple(ledger.events()),'2021-02-01')==()
 assert not contributions(ledger,account) and cash_digest(ledger)==before


@pytest.mark.parametrize('mutation',['source_digest','decomposition_digest','net_digest','ordinal','payroll_identity','source_raw'])
def test_payroll_dependency_mutations_fail_at_authenticated_boundary(tmp_path,mutation):
 from viva.investment.payroll import validate_payroll_funding
 from viva.investment.contracts import EvidenceError
 ledger,plan,account=setup(tmp_path);events=tuple(ledger.events());statements=committed_statements(events,resolver(events))
 statement=next(s for s in reversed(statements) if any(r.funding_witness and r.funding_witness.payroll_dependency for r in s.rows))
 row=next(r for r in statement.rows if r.funding_witness and r.funding_witness.payroll_dependency);w=row.funding_witness;dep=w.payroll_dependency
 with pytest.raises((EvidenceError,ValueError)):
  if mutation=='source_digest':dep=replace(dep,source_body_digest='0'*64)
  if mutation=='decomposition_digest':dep=replace(dep,decomposition_body_digest='0'*64)
  if mutation=='net_digest':dep=replace(dep,net_deposit_body_digest='0'*64)
  if mutation=='ordinal':dep=replace(dep,ordinal=0)
  if mutation=='payroll_identity':dep=replace(dep,payroll_identity='payroll:forged')
  if mutation=='source_raw':dep=replace(dep,source=replace(dep.source,source_reference=replace(dep.source.source_reference,raw='forged')))
  forged=replace(row,funding_witness=replace(w,payroll_dependency=dep))
  validate_payroll_funding(statement,forged,{e.event_id:e for e in events})


def test_conflicting_copy_same_printed_reference_is_not_silently_ignored(tmp_path):
 ledger,plan,account=setup(tmp_path);before=cash_digest(ledger)
 data=payroll_data();data['payroll_source']['deductions'][2]['destination_reference']=sf('WRONG-PLAN')
 assert post_paystub(ledger,facts(data,doc='conflicting-copy')).action=='duplicate'
 assert not contributions(ledger,account)
 assert cash_digest(ledger)==before


def test_repeated_equal_deductions_keep_occurrences_and_ambiguous_ref_holds(tmp_path):
 ledger,plan,account=setup(tmp_path,payroll_first=False)
 data=payroll_data();data['deductions'][0]['amount_raw']='2483.33';data['payroll_source']['deductions'][0]['amount']=sf('2483.33')
 data['deductions'].append(copy.deepcopy(data['deductions'][2]));data['payroll_source']['deductions'].append(copy.deepcopy(data['payroll_source']['deductions'][2]))
 assert post_paystub(ledger,facts(data)).action=='posted'
 from viva.investment.payroll import _records
 source=_records(tuple(ledger.events()))[0][1]
 assert len(source.deductions)==5 and source.deductions[2].amount.value==source.deductions[4].amount.value
 assert source.deductions[2].local_id!=source.deductions[4].local_id and not contributions(ledger,account)


def test_legacy_original_never_accepts_new_copy_invented_reference(tmp_path):
 ledger,plan,account=setup(tmp_path,payroll_first=False)
 data=payroll_data();del data['payroll_source']
 assert post_paystub(ledger,facts(data)).action=='posted'
 assert post_paystub(ledger,facts(doc='new-copy')).action=='duplicate'
 assert not contributions(ledger,account)


def test_destination_raw_header_is_insufficient_without_committed_snapshot(tmp_path):
 from viva.investment.payroll import destination_resolver
 from viva.investment.contracts import Field
 ledger,plan,account=setup(tmp_path)
 events=tuple(ledger.events());field=Field('BROKER-REF','plan-source',1,raw='BROKER-REF')
 assert destination_resolver(events)(field)==(account,'USD')
 first=next(i for i,e in enumerate(events) if e.event_type=='InvestmentActivityStatementObserved')
 assert destination_resolver(events[:first])(field) is None


def single_pdf():
 from io import BytesIO
 from reportlab.pdfgen import canvas
 out=BytesIO();page=canvas.Canvas(out);page.drawString(30,750,'Synthetic payroll source');page.save();return out.getvalue()


@pytest.mark.parametrize('family',['pay_stub','brokerage_statement'])
@pytest.mark.parametrize('page',[1,2])
def test_actual_reader_bounds_new_source_fields_to_rendered_pages(monkeypatch,family,page):
 from test_instrument_reader_b import _read
 if family=='pay_stub':
  proposal=payroll_data();proposal['payroll_source']['deductions'][2]['contribution_reference']['page']=page
 else:
  proposal=plan_facts().to_dict();proposal['investment_source']['rows'][0]['printed_reference']['page']=page
  # parser expects the ordinary source raw shape, not stored facts.
  from test_extraction import legacy
  raw=legacy();raw['investment_source']=proposal['investment_source'];proposal=raw
 result,adapter=_read(monkeypatch,single_pdf(),family,proposal=proposal)
 if page==1:assert result.facts is not None and len(adapter.calls)==2,result.error
 else:assert result.facts is None and len(adapter.calls)==3 and 'outside' in result.error,result.error


def test_actual_rebuild_rejects_out_of_document_payroll_source(monkeypatch,tmp_path):
 from types import SimpleNamespace
 from viva.vault import Vault
 from viva.ingest import capture_and_ingest,reader
 from viva.rebuild import rebuild
 from test_instrument_reader_b import _Adapter
 from viva import env
 empty=tmp_path/'empty.env';empty.write_text('');monkeypatch.setenv('VIVA_ENV_FILE',str(empty));monkeypatch.setenv('VIVA_CATALOG',str(tmp_path/'missing.json'));monkeypatch.setattr(env,'CONFIG_HOME',tmp_path/'config')
 proposal=payroll_data();proposal['payroll_source']['deductions'][2]['contribution_reference']['page']=2
 adapter=_Adapter('pay_stub',proposal);monkeypatch.setattr(reader,'adapter_for',lambda _:adapter)
 source=Vault.open(tmp_path/'source','synthetic-only')
 try:
  capture_and_ingest(source.raw,source.ledger,single_pdf(),lambda data,doc:reader.read_statement(data,doc,SimpleNamespace(model='synthetic-model',json_mode=True),'en-US','USD'),filename='unit.pdf',captured_at='2021-01-31')
  assert len(adapter.calls)==3
 finally:source.close()
 monkeypatch.setattr(reader,'adapter_for',lambda _:pytest.fail('rebuild must not call model'))
 rebuild(tmp_path/'source',tmp_path/'restored','synthetic-only',locale='en-US',currency='USD',log=lambda _:None)
 target=Vault.open(tmp_path/'restored','synthetic-only',create=False)
 try:assert not any(e.event_type=='PayrollDeductionSourceObserved' for e in target.ledger.events())
 finally:target.close()


def test_source_roundtrip_and_runtime_containers_are_closed(tmp_path):
 from viva.investment.payroll import _records,decode_source,decode_dependency
 from viva.investment.contracts import encode,EvidenceError
 ledger,plan,account=setup(tmp_path);event,source,pending=_records(tuple(ledger.events()))[0]
 assert decode_source(encode(source))==source
 with pytest.raises(EvidenceError):replace(source,deductions=list(source.deductions))
 statements=committed_statements(tuple(ledger.events()),resolver(tuple(ledger.events())))
 dep=next(r.funding_witness.payroll_dependency for s in reversed(statements) for r in s.rows if r.funding_witness and r.funding_witness.payroll_dependency)
 assert decode_dependency(encode(dep))==dep
 with pytest.raises(EvidenceError):replace(dep,corroborating_sources=[])


def test_authenticated_sql_reopen_matches_source_and_financial_characterization(tmp_path):
 from viva.read_store import ReadStore
 from viva.investment.authenticated import synchronize,read as sql_read
 ledger,plan,account=setup(tmp_path)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as store:
  synchronize(store,ledger.store)
  with store.open_reader() as revision:
   actual=sql_read(store,revision,Request('activity_totals',account,'USD',start='2021-01-01',end='2021-01-31',grouping='none'))
   assert any(f['claim']=='investment_contribution' and Decimal(f['value'])==1000 for f in actual['figures'])
 reopened=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 assert contributions(reopened,account)==contributions(ledger,account)
 assert financial_statements(reopened.projection())['balance_sheet']['by_currency']['USD']['net']=='13450.00'


def test_distinct_equal_retirement_occurrences_bind_separately_without_collapsing(tmp_path):
 from viva.investment.extraction import parse
 from viva.investment.healing import heal_after_source
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 ledger.append(account_opened('checking','depository','Test checking','USD','2021-01-01'))
 ledger.append(simple_transaction('checking','12450.00','Test employer deposit',WHEN,provenance=Provenance(doc_id='bank-source',page=1)))
 data=payroll_data();data['deductions'][2]['amount_raw']='500';data['payroll_source']['deductions'][2]['amount']=sf('500')
 second=copy.deepcopy(data['deductions'][2]);second['label']='Second retirement deduction';data['deductions'].append(second)
 source=copy.deepcopy(data['payroll_source']['deductions'][2]);source['label']=sf(second['label']);source['contribution_reference']=sf('CONTRIBUTION-B');data['payroll_source']['deductions'].append(source)
 assert post_paystub(ledger,facts(data)).action=='posted'
 plan=plan_facts();rows=[replace(plan.activity[0],amount=Decimal(500)),replace(plan.activity[0],amount=Decimal(500)),plan.activity[1]]
 raw=plan.investment_source.to_dict();a=raw['rows'][0];a['amount']=sf('500');b=copy.deepcopy(a);b['printed_reference']=sf('CONTRIBUTION-B');raw['rows'].insert(1,b)
 plan=replace(plan,activity=rows,investment_source=parse(raw));posted=post_brokerage(ledger,plan);assert posted.action=='posted';heal_after_source(ledger,plan.doc_id)
 actual=contributions(ledger,posted.account);assert len(actual)==1 and Decimal(actual[0]['value'])==1000
 statements=committed_statements(tuple(ledger.events()),resolver(tuple(ledger.events())))
 latest=statements[-1];deps=[r.funding_witness.payroll_dependency for r in latest.rows if r.kind.value=='contribution']
 assert len(deps)==2 and {d.ordinal for d in deps}=={2,4} and len({d.occurrence_id for d in deps})==2


def test_net_deposit_arrival_does_not_preaccept_payroll_witness(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');ledger.append(account_opened('checking','depository','Test checking','USD','2021-01-01'))
 assert post_paystub(ledger,facts()).action=='awaiting'
 assert not any(e.event_type=='PayrollDeductionSourceObserved' for e in ledger.events())
 ledger.append(simple_transaction('checking','12450.00','Test employer deposit',WHEN,provenance=Provenance(doc_id='bank-source',page=1)))
 assert post_paystub(ledger,facts()).action=='posted'
 assert sum(e.event_type=='PayrollDeductionSourceObserved' for e in ledger.events())==1


@pytest.mark.parametrize('target',['decomposition','net_cash'])
def test_committed_money_body_mutations_refuse_not_grade_promote(tmp_path,target):
 from viva.investment.payroll import _records
 from viva.investment.contracts import EvidenceError
 ledger,plan,account=setup(tmp_path);events=tuple(ledger.events());event,source,pending=_records(events)[0]
 event_id=event.body['decomposition_event_id' if target=='decomposition' else 'net_deposit_event_id']
 altered=tuple(replace(e,body={**e.body,'description':'tampered body'}) if e.event_id==event_id else e for e in events)
 with pytest.raises(EvidenceError):_records(altered)


def test_source_correction_atomic_closure_refuses_missing_change_event(tmp_path):
 from viva.investment.payroll import append_source,_records,OBSERVED
 from viva.investment.contracts import EvidenceError
 ledger,plan,account=setup(tmp_path);data=payroll_data();data['payroll_source']['deductions'][2]['contribution_reference']=sf('OTHER')
 added=append_source(ledger,facts(data),effective='2021-02-01');assert len(added)==2
 events=tuple(ledger.events())
 with pytest.raises(EvidenceError):_records(events[:-1])
 assert _records(events,'2021-01-31')[0][1].deductions[2].contribution_reference.value=='CONTRIBUTION-A'
 assert _records(events,'2021-02-01')[0][1].deductions[2].contribution_reference.value=='OTHER'


def test_ambiguous_committed_plan_headers_do_not_resolve_by_amount(tmp_path):
 from viva.investment.payroll import destination_resolver
 from viva.investment.contracts import Field
 ledger,plan,account=setup(tmp_path)
 other=replace(plan,doc_id='other-plan-source',institution='Other broker',account_number='OTHER-4567')
 posted=post_brokerage(ledger,other);assert posted.action=='posted' and posted.account!=account
 assert destination_resolver(tuple(ledger.events()))(Field('BROKER-REF','payroll-source',1,raw='BROKER-REF')) is None
 assert not contributions(ledger,account)


def test_all_payroll_fields_remain_ungraded_not_promoted_by_balanced_decomposition(tmp_path):
 from viva.investment.payroll import _records,source_fields
 ledger,plan,account=setup(tmp_path)
 source=_records(tuple(ledger.events()))[0][1]
 assert all(field.grade=='unverified' for field in source_fields(source))


def test_reopen_after_retraction_retains_income_but_not_funding(tmp_path):
 from viva.investment.payroll import _records,retract_source,PayrollSourceChange
 from viva.read_store import ReadStore
 from viva.investment.authenticated import synchronize,read as sql_read
 ledger,plan,account=setup(tmp_path);event,source,pending=_records(tuple(ledger.events()))[0]
 retract_source(ledger,PayrollSourceChange('remove-payroll',event.event_id,source.document,'2021-01-26','source_retraction'))
 reopened=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 assert not contributions(reopened,account)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as store:
  synchronize(store,reopened.store)
  with store.open_reader() as revision:
   actual=sql_read(store,revision,Request('activity_totals',account,'USD',start='2021-01-01',end='2021-01-31',grouping='none'))
   assert not any(f['claim']=='investment_contribution' for f in actual['figures'])
 assert financial_statements(reopened.projection())['profit_loss']['by_currency']['USD']['income']=='18333.33'


def test_rebuild_revalidates_previously_accepted_source_page_claim(monkeypatch,tmp_path):
 from types import SimpleNamespace
 from viva.vault import Vault
 from viva.ingest import capture_and_ingest,reader
 from viva.rebuild import rebuild,claims_by_doc
 from viva.investment import payroll_extraction
 from test_instrument_reader_b import _Adapter
 from viva import env
 empty=tmp_path/'empty.env';empty.write_text('');monkeypatch.setenv('VIVA_ENV_FILE',str(empty));monkeypatch.setenv('VIVA_CATALOG',str(tmp_path/'missing.json'));monkeypatch.setattr(env,'CONFIG_HOME',tmp_path/'config')
 proposal=payroll_data();proposal['payroll_source']['deductions'][2]['contribution_reference']['page']=2
 adapter=_Adapter('pay_stub',proposal);monkeypatch.setattr(reader,'adapter_for',lambda _:adapter)
 source=Vault.open(tmp_path/'source','synthetic-only')
 actual=payroll_extraction.validate_pages
 try:
  # Counterfactual old reader admission: the stored claim is syntactically valid
  # but page2 does not exist. Recovery must independently check the original PDF.
  with monkeypatch.context() as legacy:
   legacy.setattr(payroll_extraction,'validate_pages',lambda *args:None)
   captured=capture_and_ingest(source.raw,source.ledger,single_pdf(),lambda data,doc:reader.read_statement(data,doc,SimpleNamespace(model='synthetic-model',json_mode=True),'en-US','USD'),filename='unit.pdf',captured_at='2021-01-31')
  assert len(adapter.calls)==2
  assert claims_by_doc(tuple(source.ledger.events()))[captured.doc_id]['extract']['parse_ok'] is True
  recorded_reads=tuple((event.event_id,event.body) for event in source.ledger.events()
   if event.event_type=='ReadRecorded')
 finally:source.close()
 monkeypatch.setattr(reader,'adapter_for',lambda _:pytest.fail('rebuild must not call model'))
 rebuild(tmp_path/'source',tmp_path/'restored','synthetic-only',locale='en-US',currency='USD',log=lambda _:None)
 target=Vault.open(tmp_path/'restored','synthetic-only',create=False)
 try:
  claims=claims_by_doc(tuple(target.ledger.events()))
  # The historical reader's verdict is audit evidence, not a new admission.
  # Rebuild preserves it exactly while independently rejecting its bad page.
  assert len(claims)==1 and next(iter(claims.values()))['extract']['parse_ok'] is True
  assert tuple((event.event_id,event.body) for event in target.ledger.events()
   if event.event_type=='ReadRecorded')==recorded_reads
  assert captured.doc_id not in target.ledger.projection().posted_doc_ids()
  assert not any(event.event_type=='PayrollSourceObserved' for event in target.ledger.events())
 finally:target.close()


@pytest.mark.parametrize('field',['label','category','amount'])
def test_incomplete_other_deduction_source_cannot_certify_full_payroll(tmp_path,field):
 ledger,plan,account=setup(tmp_path,payroll_first=False);data=payroll_data();data['payroll_source']['deductions'][0][field]=None
 assert post_paystub(ledger,facts(data)).action=='posted'
 assert not contributions(ledger,account)


def test_one_payroll_occurrence_cannot_fund_two_selected_plan_rows(tmp_path):
 from viva.investment.payroll import validate_payroll_funding
 from viva.investment.contracts import EvidenceError
 ledger,plan,account=setup(tmp_path);events=tuple(ledger.events());statements=committed_statements(events,resolver(events));statement=statements[-1]
 row=next(r for r in statement.rows if r.kind.value=='contribution')
 copied=replace(row,observation_id='second-plan-contribution',local_id='second-local',ordinal=2)
 with pytest.raises(EvidenceError,match='reused'):
  validate_payroll_funding(replace(statement,rows=statement.rows+(copied,)),row,{e.event_id:e for e in events})


def test_payroll_locked_prefix_cannot_be_replayed_on_different_committed_history(tmp_path):
 from viva.investment.payroll import _records,OBSERVED
 from viva.investment.contracts import EvidenceError
 ledger,plan,account=setup(tmp_path);events=tuple(ledger.events())
 changed=tuple(replace(e,body={**e.body,'prefix':{**e.body['prefix'],'event_count':0}}) if e.event_type==OBSERVED else e for e in events)
 with pytest.raises(EvidenceError,match='prefix'):_records(changed)
