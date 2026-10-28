import json, sqlite3
from dataclasses import replace
from decimal import Decimal
from calendar import monthrange
import pytest
from test_payroll_counterpart import payroll_data, plan_facts, facts, sf
from viva.ledger import Ledger
from viva.ledger.events import account_opened, Provenance, document_captured, read_recorded
from viva.ledger.postings import simple_transaction
from viva.ingest.paystub_projector import post_paystub
from viva.ingest.brokerage_projector import post_brokerage
from viva.investment.extraction import parse
from viva.investment.healing import heal_after_source
from viva.investment.contracts import digest, EvidenceError
from viva.investment.sql import materialize
from viva.investment.funding import resolver
from viva.retirement_funding.contracts import Request
from viva.retirement_funding.tool import result, spec
from viva.retirement_funding.semantic import lower


def recorded(ledger, data, document):
    ledger.append(document_captured(document, 'synthetic.pdf', 1, 'pay_stub', 1.0, '2024-01-01'))
    ledger.append(read_recorded(document, 'offline-fixture', 'extract:paystub-base-v2+paystub-v2', 'text', json.dumps(data), 0, 0, 0, True, None, '2024-01-01'))


def annual_ledger(tmp_path,*,repeated_source=False):
    ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
    ledger.append(account_opened('bank','depository','Synthetic bank','USD','2024-01-01'))
    accounts=[]
    for index,(reference,when,start,end) in enumerate([('PLAN-B','2024-06-25','2024-01-01','2024-06-30'),('PLAN-C','2024-12-25','2024-07-01','2024-12-31')]):
        ledger.append(simple_transaction('bank','7450','Synthetic pay',when,provenance=Provenance(doc_id='bank-'+str(index),page=1)))
        data=payroll_data();data.update(pay_date_raw=when,period_start_raw=start,period_end_raw=end,net_raw='7450');data['deductions'][2]['amount_raw']='6000'
        source=data['payroll_source'];source['schema']='payroll-source-v2';source['headers'].update(source_reference=sf('PAY-EMPLOYER' if repeated_source else 'PAY-'+reference),pay_date=sf(when),net=sf('7450'),period_start=sf(start),period_end=sf(end));source['deductions'][2].update(amount=sf('6000'),destination_reference=sf(reference),contribution_reference=sf('CONTRIB-'+reference))
        recorded(ledger,data,'payroll-'+reference)
        assert post_paystub(ledger,facts(data,doc='payroll-'+reference)).action=='posted'
        plan=plan_facts();raw=plan.investment_source.to_dict();raw['headers'].update(account_reference=sf(reference),period_start=sf(start),period_end=sf(end),as_of=sf(end),closing_cash=sf('5975'));raw['rows'][0].update(date=sf(when),amount=sf('6000'),printed_reference=sf('CONTRIB-'+reference),counterpart_reference=sf('PAY-EMPLOYER' if repeated_source else 'PAY-'+reference));raw['rows'][1]['date']=sf(when)
        plan=replace(plan,doc_id='plan-'+reference,account_number=reference,account_ref=reference,cash=Decimal('5975'),total=Decimal('6000'),as_of=end,activity=[replace(plan.activity[0],date=when,amount=Decimal('6000')),replace(plan.activity[1],date=when)],investment_source=parse(raw))
        posted=post_brokerage(ledger,plan);assert posted.action=='posted',posted
        heal_after_source(ledger,plan.doc_id);accounts.append(posted.account)
    return ledger,accounts


def test_actual_two_plans_employee_annual_scalar(tmp_path):
    ledger,accounts=annual_ledger(tmp_path)
    events=tuple(ledger.events());connection=sqlite3.connect(':memory:');frontier=materialize(connection,events,resolver(events))
    args={'view':'annual_employee_contributions','plans':accounts,'currency':'USD','year':2024}
    output=result(connection,frontier,args,object(),'2025-01-01')
    assert output.ok,output.to_dict()
    assert len(output.figures)==1 and Decimal(output.figures[0]['value'])==12000
    assert output.figures[0]['subject']['member_ids']==sorted(accounts)
    assert len(output.data['payroll_population'])==2


def test_registered_program_binds_annual_set_without_generic_add(tmp_path):
    from viva.tools import default_registry
    from viva.answer_program import CapabilityManifest, ProgramValidator, ProgramExecutor, DeterministicBinder, AnswerResourcePolicy
    ledger,accounts=annual_ledger(tmp_path);events=tuple(ledger.events());connection=sqlite3.connect(':memory:',check_same_thread=False);frontier=materialize(connection,events,resolver(events))
    registry=default_registry(ledger.projection(),today='2025-01-01')
    registry.register(spec(connection,frontier,registry.instrument_runtime.run_token,'2025-01-01'))
    manifest=CapabilityManifest.from_registry(registry)
    args={'view':'annual_employee_contributions','plans':accounts,'currency':'USD','year':2024}
    program=lower(manifest,args,('employee_retirement_contributions',))
    assert ProgramValidator(manifest,AnswerResourcePolicy()).validate(program).ok
    execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,'Show accepted recorded annual employee retirement deductions across these selected plans.')
    bound=DeterministicBinder(registry,'en-US').bind(program,execution)
    assert bound.result.answered,(bound.unbound,bound.result.detail)
    assert len(bound.result.figures)==1 and Decimal(bound.result.figures[0]['value'])==12000


def monthly_ledger(tmp_path):
    ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');ledger.append(account_opened('bank','depository','Synthetic bank','USD','2024-01-01'))
    balances={};accounts={}
    for month in range(1,13):
        reference='PLAN-B' if month<=6 else 'PLAN-C';when=f'2024-{month:02d}-25';start=f'2024-{month:02d}-01';end=f'2024-{month:02d}-{monthrange(2024,month)[1]}'
        ledger.append(simple_transaction('bank','12450','Synthetic pay',when,provenance=Provenance(doc_id='bank-'+str(month),page=1)))
        data=payroll_data();data.update(pay_date_raw=when,period_start_raw=start,period_end_raw=end)
        source=data['payroll_source'];source['schema']='payroll-source-v2';source['headers'].update(source_reference=sf('PAY-'+str(month)),pay_date=sf(when),period_start=sf(start),period_end=sf(end));source['deductions'][2].update(destination_reference=sf(reference),contribution_reference=sf('CONTRIB-'+str(month)))
        recorded(ledger,data,'payroll-'+str(month));assert post_paystub(ledger,facts(data,doc='payroll-'+str(month))).action=='posted'
        opening=balances.get(reference,Decimal(0));closing=opening+975;balances[reference]=closing
        plan=plan_facts();raw=plan.investment_source.to_dict();raw['headers'].update(account_reference=sf(reference),period_start=sf(start),period_end=sf(end),as_of=sf(end),opening_cash=sf(str(opening)),closing_cash=sf(str(closing)));raw['rows'][0].update(date=sf(when),printed_reference=sf('CONTRIB-'+str(month)),counterpart_reference=sf('PAY-'+str(month)));raw['rows'][1]['date']=sf(when)
        plan=replace(plan,doc_id='plan-'+str(month),account_number=reference,account_ref=reference,cash=closing,total=closing+25,opening_cash=opening,as_of=end,activity=[replace(row,date=when) for row in plan.activity],investment_source=parse(raw))
        posted=post_brokerage(ledger,plan);assert posted.action=='posted',posted;heal_after_source(ledger,plan.doc_id);accounts[reference]=posted.account
    return ledger,list(accounts.values())


def test_complete_twelve_period_annual_payload_is_bounded(tmp_path):
    ledger,accounts=monthly_ledger(tmp_path);events=tuple(ledger.events());connection=sqlite3.connect(':memory:');frontier=materialize(connection,events,resolver(events))
    output=result(connection,frontier,{'view':'annual_employee_contributions','plans':accounts,'currency':'USD','year':2024},object(),'2025-01-01')
    assert output.ok,output.to_dict()
    assert Decimal(output.figures[0]['value'])==12000
    assert len(output.data['payroll_population'])==12
    assert len(json.dumps(output.to_dict(),separators=(',',':'),ensure_ascii=False).encode())<=32000


def add_rollover(ledger,source_ref,destination_ref,amount,when,opening_source,opening_destination,reference):
    from test_nonbank_funding import source_packet,post_packet
    from datetime import date
    start=when[:7]+'-01';end=when[:7]+'-'+str(monthrange(int(when[:4]),int(when[5:7]))[1])
    outputs=[]
    for incoming,account,counterpart,opening,closing in [(False,source_ref,destination_ref,Decimal(opening_source),Decimal(opening_source)-Decimal(amount)),(True,destination_ref,source_ref,Decimal(opening_destination),Decimal(opening_destination)+Decimal(amount))]:
        packet=source_packet(incoming,reference=reference,counterpart=counterpart)
        packet.update(institution=plan_facts().institution,account_ref=account,account_number=account,cash_raw=str(closing),total_raw=str(closing),opening_cash_raw=str(opening),as_of_raw=end)
        packet['activity'][0].update(date_raw=when,amount_raw=str(amount))
        headers=packet['investment_source']['headers'];headers.update(account_reference=sf(account),period_start=sf(start),period_end=sf(end),as_of=sf(end),opening_cash=sf(str(opening)),closing_cash=sf(str(closing)))
        packet['investment_source']['rows'][0].update(date=sf(when),amount=sf(str(amount)))
        _,posted=post_packet(ledger,packet,reference+('-in' if incoming else '-out'));outputs.append(posted.account)
    heal_after_source(ledger,reference+'-in')
    return outputs


def test_real_paired_rollover_registered_receipts(tmp_path):
    ledger,accounts=annual_ledger(tmp_path)
    add_rollover(ledger,'PLAN-B','PLAN-C','100','2025-01-25','5975','5975','ROLLOVER-PAIR')
    events=tuple(ledger.events());connection=sqlite3.connect(':memory:',check_same_thread=False);frontier=materialize(connection,events,resolver(events))
    output=result(connection,frontier,{'view':'direct_rollovers','plans':accounts,'currency':'USD','from':'2025-01-01','to':'2025-01-31'},object(),'2025-02-01')
    assert output.ok,output.to_dict()
    values={item['claim']:Decimal(item['value']) for item in output.figures}
    assert values['direct_rollover_amount']==100
    assert values['rollover_checking_receipts']==values['rollover_attributed_income']==0
    assert len({item['association_id'] for item in output.figures})==1
    assert {a['claim'] for a in output.instrument_assertions}=={'rollover_date','rollover_reference','rollover_source_account','rollover_destination_account'}


def test_rollover_all_claims_strictly_bind_from_registered_read(tmp_path):
    from viva.tools import default_registry
    from viva.answer_program import CapabilityManifest,ProgramValidator,ProgramExecutor,DeterministicBinder,AnswerResourcePolicy
    from viva.retirement_funding.contracts import NUMERIC_CLAIMS,ASSERTION_CLAIMS
    ledger,accounts=annual_ledger(tmp_path);add_rollover(ledger,'PLAN-B','PLAN-C','100','2025-01-25','5975','5975','ROLLOVER-PAIR')
    e=tuple(ledger.events());c=sqlite3.connect(':memory:',check_same_thread=False);frontier=materialize(c,e,resolver(e));registry=default_registry(ledger.projection(),today='2025-02-01');registry.register(spec(c,frontier,registry.instrument_runtime.run_token,'2025-02-01'))
    manifest=CapabilityManifest.from_registry(registry);args={'view':'direct_rollovers','plans':accounts,'currency':'USD','from':'2025-01-01','to':'2025-01-31'}
    program=lower(manifest,args,tuple(claim for claim in (*NUMERIC_CLAIMS,*ASSERTION_CLAIMS) if claim!='employee_retirement_contributions'))
    valid=ProgramValidator(manifest,AnswerResourcePolicy()).validate(program);assert valid.ok,valid.to_dict()
    execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,'Show all source-backed direct rollover details and its complete accepted source-scoped checking and income effects.')
    bound=DeterministicBinder(registry,'en-US').bind(program,execution)
    assert bound.result.answered,(bound.unbound,bound.result.detail)
    assert 'ROLLOVER-PAIR' in bound.result.text


def test_later_accepted_income_classification_exposes_nonzero_not_label_zero(tmp_path):
    from viva.ledger.events import ruling_recorded
    ledger,accounts=annual_ledger(tmp_path);add_rollover(ledger,'PLAN-B','PLAN-C','100','2025-01-25','5975','5975','ROLLOVER-PAIR')
    movement=next(m for m in ledger.projection().movements() if m.account==accounts[1] and m.date=='2025-01-25' and m.amount==100)
    ledger.append(ruling_recorded('movement',movement.key,'2025-01-26',legs=[{'major':'income','account':'Income:Salary','share':'1'}],said='Synthetic test income classification'))
    e=tuple(ledger.events());c=sqlite3.connect(':memory:');f=materialize(c,e,resolver(e));o=result(c,f,{'view':'direct_rollovers','plans':accounts,'currency':'USD','from':'2025-01-01','to':'2025-01-31'},object(),'2025-02-01')
    assert o.ok,o.to_dict()
    assert next(Decimal(i['value']) for i in o.figures if i['claim']=='rollover_attributed_income')==100


def test_explicit_narrower_plan_set_discloses_known_other_destination(tmp_path):
    ledger,accounts=annual_ledger(tmp_path);e=tuple(ledger.events());c=sqlite3.connect(':memory:');f=materialize(c,e,resolver(e));o=result(c,f,{'view':'annual_employee_contributions','plans':accounts[:1],'currency':'USD','year':2024},object(),'2025-01-01')
    assert o.ok,o.to_dict()
    assert Decimal(o.figures[0]['value'])==6000
    assert [item['destination_account'] for item in o.data['excluded']]==accounts[1:]


@pytest.mark.parametrize('args',[
 {'view':'annual_employee_contributions','plans':['x','x'],'currency':'USD','year':2024},
 {'view':'annual_employee_contributions','plans':['x'],'currency':'USD','year':True},
 {'view':'annual_employee_contributions','plans':['x'],'currency':'USD','year':2024,'role':'retirement'},
 {'view':'direct_rollovers','plans':['x'],'currency':'USD','from':'2000-01-01','to':'2025-01-01'},
])
def test_closed_retirement_selection_rejects_unreviewed_shapes(args):
    with pytest.raises(EvidenceError):Request.from_dict(args)


def test_population_retraction_and_effective_frontier_do_not_repost_cash(tmp_path):
    from viva.retirement_funding.population import records,retract,OBSERVED,append
    ledger,accounts=annual_ledger(tmp_path);before=[(e.event_id,digest(e.body)) for e in ledger.events() if e.event_type=='TransactionRecorded']
    original=next(e for e in ledger.events() if e.event_type==OBSERVED)
    retract(ledger,original.provenance.doc_id,original.event_id,'2025-01-01')
    assert all(r['population'] is not None for r in records(tuple(ledger.events()),'2024-12-31'))
    assert any(r['population'] is None for r in records(tuple(ledger.events()),'2025-01-01'))
    assert before==[(e.event_id,digest(e.body)) for e in ledger.events() if e.event_type=='TransactionRecorded']


def test_actual_pdf_period_page_failure_keeps_cash_and_retained_raw_bytes(tmp_path,monkeypatch):
    from io import BytesIO
    from reportlab.pdfgen.canvas import Canvas
    from viva.ingest import reader
    from viva.ingest.pipeline import capture_and_ingest
    from viva.ingest.raw_store import RawStore
    from viva.investment.payroll_extraction import parse as parse_source
    from viva.retirement_funding.population import records
    from vivacore.models.base import ModelResult
    from vivacore.models import ModelSpec
    from retirement_wire_fixture import pdf_bytes
    original=payroll_data();original['payroll_source']['schema']='payroll-source-v2';original['payroll_source']['headers'].update(period_start=sf('2021-01-01'),period_end=sf('2021-01-31'))
    data=pdf_bytes(original)
    cash=[]
    for bad in (False,True):
        folder=tmp_path/str(bad);ledger=Ledger.open(folder/'events.jsonl','synthetic-only');raw=RawStore.open(folder/'raw','synthetic-only')
        ledger.append(account_opened('bank','depository','Synthetic bank','USD','2021-01-01'))
        ledger.append(simple_transaction('bank','12450','Synthetic pay','2021-01-25',provenance=Provenance(doc_id='bank-source',page=1)))
        packet=payroll_data();source=packet['payroll_source'];source['schema']='payroll-source-v2';source['headers'].update(period_start=sf('2021-01-01',2 if bad else 1),period_end=sf('2021-01-31'))
        response=json.dumps(packet);calls=[]
        class Adapter:
            def extract(self,pages,prompt):
                calls.append(prompt)
                value=json.dumps({'doc_type':'pay_stub','doc_type_confidence':1}) if len(calls)==1 else response
                return ModelResult(value,'offline-fixture',0,0,0,0,{}, {})
        monkeypatch.setattr(reader,'adapter_for',lambda spec:Adapter())
        spec=ModelSpec('fixture','openai-compatible','offline-fixture',base_url='http://127.0.0.1',api_key_env=None)
        posted=capture_and_ingest(raw,ledger,data,lambda body,doc:reader.read_statement(body,doc,spec,'en-US','USD'),filename='synthetic-payroll.pdf',captured_at='2021-01-31')
        assert posted.action=='posted',posted
        events=tuple(ledger.events());extract=next(e for e in events if e.event_type=='ReadRecorded' and e.body.get('phase')=='extract')
        assert extract.body['response_text']==response
        assert extract.body['prompt_version'].startswith('extract:paystub-base-v2+paystub-v2')
        before=digest(extract.body)
        population=records(events)
        assert (population[0]['population'] is None)==bad
        assert before==digest(next(e for e in Ledger.open(folder/'events.jsonl','synthetic-only').events() if e.event_id==extract.event_id).body)
        cash.append([e.body for e in events if e.event_type=='TransactionRecorded'])
    assert cash[0]==cash[1]


@pytest.mark.parametrize('empty_list',[False,True])
def test_complete_nonretirement_population_zero_is_distinct_from_empty_parser_list(tmp_path,empty_list):
    ledger,accounts=annual_ledger(tmp_path);when='2025-12-25'
    data={'employer':'Synthetic employer','pay_date_raw':when,'period_start_raw':'2025-01-01','period_end_raw':'2025-12-31','gross_raw':'100','net_raw':'100' if empty_list else '90','deductions':[] if empty_list else [{'label':'Printed tax','amount_raw':'10','category':'tax'}]}
    deduction=[] if empty_list else [{'label':sf('Printed tax'),'category':sf('tax'),'amount':sf('10'),'destination_reference':None,'contribution_reference':None}]
    data['payroll_source']={'schema':'payroll-source-v2','headers':{'source_reference':sf('PAY-ZERO'),'currency':sf('USD'),'pay_date':sf(when),'gross':sf('100'),'net':sf(data['net_raw']),'period_start':sf('2025-01-01'),'period_end':sf('2025-12-31')},'deductions':deduction}
    ledger.append(simple_transaction('bank',data['net_raw'],'Synthetic net',when,provenance=Provenance(doc_id='zero-bank',page=1)))
    recorded(ledger,data,'pay-zero');assert post_paystub(ledger,facts(data,doc='pay-zero')).action=='posted'
    e=tuple(ledger.events());c=sqlite3.connect(':memory:');f=materialize(c,e,resolver(e));o=result(c,f,{'view':'annual_employee_contributions','plans':accounts,'currency':'USD','year':2025},object(),'2026-01-01')
    assert o.ok is not empty_list
    if o.ok:assert Decimal(o.figures[0]['value'])==0


def test_repeated_printed_employer_source_reference_does_not_merge_pay_dates(tmp_path):
    ledger,accounts=annual_ledger(tmp_path,repeated_source=True)
    events=tuple(ledger.events());connection=sqlite3.connect(':memory:');frontier=materialize(connection,events,resolver(events))
    output=result(connection,frontier,{'view':'annual_employee_contributions','plans':accounts,'currency':'USD','year':2024},object(),'2025-01-01')
    assert output.ok,output.to_dict()
    assert Decimal(output.figures[0]['value'])==12000 and len(output.data['payroll_population'])==2


def test_lossless_pool_roundtrip_includes_exact_owners_raws_and_nested_dependencies():
    from viva.retirement_funding.lineage import Pool,decode_pool,index_ranges,expand_ranges
    from viva.investment.contracts import Field,encode
    pool=Pool()
    values=[Field('1.25','document-a',2,raw='1.2500'),Field('','document-b',None,status='unavailable',raw='original proposed raw'),Field('same','document-a',1,grade='corroborated',raw='Same')]
    for owner in ('population-owner','plan-owner'):
        for i,field in enumerate(values):pool.add(field,owner,f'/rows/{i}/amount')
    detail={'reading_digest':'c'*64,'reading_id':'d'*32}
    pool.dependency('id','a'*64,'payroll_population',detail)
    nested={'event_type':'TransactionRecorded','body':{'i':1,'j':[],'d':{'nested':[None,True,False,1,'1',0.875,1.0,-0.0]},'net_movement_key':'d|account|date|1|description|0'},'source':{'doc_id':'document-a','page':2}}
    pool.dependency('nested','b'*64,'ledger_event',nested)
    table=pool.to_dict();occurrences,dependencies=decode_pool(table)
    expected=[{'field':field,'source_identity':owner,'contract_path':f'/rows/{i}/amount'} for owner in ('population-owner','plan-owner') for i,field in enumerate(values)]
    assert encode(occurrences)==encode(expected)
    assert dependencies==pool.dependencies
    def same_types(left,right):
        assert type(left) is type(right)
        if type(left) is dict:
            assert set(left)==set(right)
            for key in left:same_types(left[key],right[key])
        elif type(left) is list:
            assert len(left)==len(right)
            for a,b in zip(left,right):same_types(a,b)
        elif type(left) is float:assert left.hex()==right.hex()
        else:assert left==right
    same_types(dependencies,pool.dependencies)
    def replace_float(value,replacement):
        if type(value) is float:return replacement
        if type(value) is list:return [replace_float(v,replacement) for v in value]
        if type(value) is dict:return {k:replace_float(v,replacement) for k,v in value.items()}
        return value
    for hostile in (float('nan'),float('inf'),float('-inf')):
        import copy
        changed=copy.deepcopy(table);changed['dependencies']=replace_float(changed['dependencies'],hostile)
        with pytest.raises(EvidenceError):decode_pool(changed)
    assert expand_ranges(index_ranges([0,1,2,5,9,10]))==[0,1,2,5,9,10]
    import copy
    for tamper in ('unknown','defaults','negative-index','kind','columns','range'):
        changed=copy.deepcopy(table)
        if tamper=='unknown':changed['new_authority']=True
        elif tamper=='defaults':changed['field_defaults']['status']='accepted_complete'
        elif tamper=='negative-index':changed['fields'][0][0]=-1
        elif tamper=='kind':changed['dependency_kinds'][0]='unknown_kind'
        elif tamper=='columns':changed['field_columns'].append('invented')
        else:
            with pytest.raises(EvidenceError):expand_ranges([[0,1],[2,3]])
            continue
        with pytest.raises(EvidenceError):decode_pool(changed)


@pytest.mark.parametrize('claim,kind',[('rollover_source_outflow','gross_flow'),('rollover_destination_inflow','gross_flow'),('rollover_checking_receipts','gross_flow'),('rollover_attributed_income','income')])
def test_relationship_effect_cannot_be_laundered_through_generic_math_query_or_scalar_hole(claim,kind):
    from types import SimpleNamespace
    from viva.tools.compute import compute
    from viva.tools.runner_binding import _figure_bound
    from viva.query.execute import FinancialQueryExecutor,QueryRow,QueryTable,QueryError
    from viva.instrument_evidence import _attest_figure
    from viva.tools.envelope import figure,bounded
    subject=Request('annual_employee_contributions',('plan-a','plan-b'),'USD',year=2024).subject
    subject.update(relationship_id='retirement-rollover:'+'a'*64,source_account_id='plan-a',destination_account_id='plan-b')
    f=_attest_figure(figure('0','Sourced relationship effect',quantity=kind,currency='USD',grade='unverified',record_ids=['doc'],boundary=bounded(whole=False,selected=[{'kind':'account_set','value':'["plan-a","plan-b"]'}]),subject=subject),claim,run_token=object())
    for expression in ('a','a+a','a-a','a*1','a/a','-a'):
        o=compute({'expression':expression,'inputs':{'a':f['id']}},{f['id']:f});assert not o.ok and o.refusal=='dedicated_authority_required'
    table=QueryTable((QueryRow({'value':Decimal(0),'claim':claim,'currency':'USD'},('doc',),'unverified'),),{'value':'Money','claim':'String','currency':'Currency'},quantities={'value':kind},currency_fields={'value':'currency'})
    with pytest.raises(QueryError,match='retirement'):
        FinancialQueryExecutor(None)._apply('select',[table],{'fields':['value','currency']})
    with pytest.raises(QueryError,match='retirement'):
        FinancialQueryExecutor(None)._emit(table,{'value_field':'value','quantity':kind,'currency_field':'currency'})
    written,reason,detail=_figure_bound(SimpleNamespace(name='household_income',type='money',quantity=kind,scope=()),f,'en-US')
    assert written is None and reason=='retirement_claim_scope_required'


def test_unknown_recorded_payroll_is_not_hidden_by_requested_year_or_known_good_population(tmp_path):
    ledger,accounts=annual_ledger(tmp_path)
    # No accepted source period exists; its proposed future pay date cannot prove
    # it is outside the selected year. The complete enumeration must expose it.
    recorded(ledger,{'employer':'Unknown','pay_date_raw':'2026-12-25','gross_raw':'1','net_raw':'1','deductions':[]},'unknown-payroll')
    e=tuple(ledger.events());c=sqlite3.connect(':memory:');f=materialize(c,e,resolver(e));o=result(c,f,{'view':'annual_employee_contributions','plans':accounts,'currency':'USD','year':2024},object(),'2025-01-01')
    assert not o.ok and o.refusal=='retirement_funding_unavailable'


def test_account_kind_or_label_never_grants_retirement_membership(tmp_path):
    ledger,accounts=annual_ledger(tmp_path)
    ledger.append(account_opened('pretend-retirement','investment','Retirement401k','USD','2024-01-01'))
    e=tuple(ledger.events());c=sqlite3.connect(':memory:');f=materialize(c,e,resolver(e));o=result(c,f,{'view':'annual_employee_contributions','plans':['pretend-retirement'],'currency':'USD','year':2024},object(),'2025-01-01')
    assert not o.ok and o.refusal=='retirement_funding_unavailable'


def test_uninitialized_native_projection_is_unavailable_without_sql_exception():
    from viva.retirement_funding.catalog import entries
    c=sqlite3.connect(':memory:')
    assert entries(c,[])==([],False)
    o=result(c,None,{'view':'annual_employee_contributions','plans':['plan'],'currency':'USD','year':2024},object(),'2025-01-01')
    assert not o.ok and o.refusal=='retirement_funding_unavailable'


def test_captured_payroll_without_any_extraction_is_explicit_unknown_population(tmp_path):
    from viva.retirement_funding.population import records
    ledger,accounts=annual_ledger(tmp_path)
    ledger.append(document_captured('captured-unread','unread.pdf',1,'pay_stub',1.0,'2026-01-01'))
    population=records(tuple(ledger.events()))
    assert next(r for r in population if r['document']=='captured-unread')['population'] is None
    events=tuple(ledger.events());c=sqlite3.connect(':memory:');frontier=materialize(c,events,resolver(events));output=result(c,frontier,{'view':'annual_employee_contributions','plans':accounts,'currency':'USD','year':2024},object(),'2025-01-01')
    assert not output.ok and output.refusal=='retirement_funding_unavailable'


def test_period_correction_is_effective_dated_current_reading_bound_and_cash_immutable(tmp_path):
    from viva.retirement_funding.population import append,records
    ledger,accounts=annual_ledger(tmp_path)
    before=[(e.event_id,digest(e.body)) for e in ledger.events() if e.event_type=='TransactionRecorded']
    original=next(e for e in ledger.events() if e.event_type=='ReadRecorded')
    changed=json.loads(original.body['response_text']);changed['period_start_raw']='2024-02-01';changed['payroll_source']['headers']['period_start']=sf('2024-02-01')
    ledger.append(read_recorded(original.body['doc_id'],'offline-fixture','extract:paystub-base-v2+paystub-v2','text',json.dumps(changed),0,0,0,True,None,'2025-01-01'))
    # A new unpaired reading is unknown even if its amounts match the old source.
    assert any(r['population'] is None for r in records(tuple(ledger.events())))
    append(ledger,facts(changed,doc=original.body['doc_id']),effective='2025-01-01')
    historic=next(r for r in records(tuple(ledger.events()),'2024-12-31') if r['document']==original.body['doc_id'])
    current=next(r for r in records(tuple(ledger.events()),'2025-01-01') if r['document']==original.body['doc_id'])
    assert historic['population']['period_start']['value']=='2024-01-01'
    assert current['population']['period_start']['value']=='2024-02-01'
    assert before==[(e.event_id,digest(e.body)) for e in ledger.events() if e.event_type=='TransactionRecorded']
    stale=list(ledger.events());stale[-1].body['prefix']['event_count']+=1
    with pytest.raises(EvidenceError,match='prefix'):records(tuple(stale))


def test_actual_bad_period_pdf_reader_rebuild_and_reopen_keep_numeric_cash_and_raw_claim(tmp_path,monkeypatch):
    from viva.vault import Vault
    from viva.ingest import reader
    from viva.ingest.pipeline import capture_and_ingest
    from viva.retirement_funding.population import records
    from viva.rebuild import rebuild
    from retirement_wire_fixture import pdf_bytes
    from vivacore.models.base import ModelResult
    from vivacore.models import ModelSpec
    source=tmp_path/'source';destination=tmp_path/'destination';vault=Vault.open(source,'synthetic-only')
    bank={'doc_type':'checking_statement','doc_type_confidence':1,'institution':'Synthetic bank','account_number':'BANK','opening':{'amount_raw':'0','date_raw':'2021-01-01'},'closing':{'amount_raw':'12450','date_raw':'2021-01-31'},'transactions':[{'date_raw':'2021-01-25','amount_raw':'12450','balance_effect':'increase','description':'Synthetic employer net pay','page':1}]}
    pay=payroll_data();pay.update(doc_type='pay_stub',doc_type_confidence=1);pay['payroll_source']['schema']='payroll-source-v2';pay['payroll_source']['headers'].update(period_start=sf('2021-01-01',2),period_end=sf('2021-01-31'))
    model=ModelSpec('fixture','openai-compatible','offline-fixture',base_url='http://127.0.0.1',api_key_env=None)
    for packet in (bank,pay):
        calls=[]
        class Adapter:
            def extract(self,pages,prompt):
                calls.append(prompt);value=json.dumps({'doc_type':packet['doc_type'],'doc_type_confidence':1}) if len(calls)==1 else json.dumps(packet)
                return ModelResult(value,'offline-fixture',0,0,0,0,{}, {})
        monkeypatch.setattr(reader,'adapter_for',lambda spec:Adapter())
        posted=capture_and_ingest(vault.raw,vault.ledger,pdf_bytes(packet),lambda data,doc:reader.read_statement(data,doc,model,'en-US','USD'),filename=packet['doc_type']+'.pdf',captured_at='2021-01-31')
        assert posted.action=='posted',posted
    before=[e.body for e in vault.ledger.events() if e.event_type=='TransactionRecorded']
    claims={e.body['doc_id']:e.body['response_text'] for e in vault.ledger.events() if e.event_type=='ReadRecorded' and e.body.get('phase')=='extract'}
    assert len(before)==2 and any(r['population'] is None for r in records(tuple(vault.ledger.events())))
    vault.close()
    rebuild(source,destination,'synthetic-only',locale='en-US',log=lambda text:None)
    rebuilt=Vault.open(destination,'synthetic-only',create=False)
    try:
        assert before==[e.body for e in rebuilt.ledger.events() if e.event_type=='TransactionRecorded']
        assert claims=={e.body['doc_id']:e.body['response_text'] for e in rebuilt.ledger.events() if e.event_type=='ReadRecorded' and e.body.get('phase')=='extract'}
        assert any(r['population'] is None for r in records(tuple(rebuilt.ledger.events())))
    finally:rebuilt.close()


def test_active_authenticated_bank_link_makes_unknown_checking_unavailable_and_unlink_restores_selected_scope(tmp_path):
    from viva.ledger.events import transfer_linked,transfer_unlinked
    ledger,accounts=annual_ledger(tmp_path);add_rollover(ledger,'PLAN-B','PLAN-C','100','2025-01-25','5975','5975','ROLLOVER-PAIR')
    ledger.append(simple_transaction('bank','100','Explicit linked source receipt','2025-01-25',provenance=Provenance(doc_id='bank-linked-receipt',page=1)))
    movements=ledger.projection().movements();outgoing=next(m for m in movements if m.account==accounts[0] and m.date=='2025-01-25' and m.amount==-100);bank=next(m for m in movements if m.account=='bank' and m.provenance.doc_id=='bank-linked-receipt')
    ledger.append(transfer_linked(outgoing.key,bank.key,'verified',{'decided_by':'human explicit source counterpart'},'2025-01-26',by='human'))
    def read_current():
        events=tuple(ledger.events());c=sqlite3.connect(':memory:');f=materialize(c,events,resolver(events));return result(c,f,{'view':'direct_rollovers','plans':accounts,'currency':'USD','from':'2025-01-01','to':'2025-01-31'},object(),'2025-02-01')
    output=read_current();assert output.ok,output.to_dict()
    assert not any(f['claim']=='rollover_checking_receipts' for f in output.figures)
    assert next(Decimal(f['value']) for f in output.figures if f['claim']=='rollover_attributed_income')==0
    ledger.append(transfer_unlinked(outgoing.key,bank.key,'2025-01-27'))
    unlinked=read_current();assert unlinked.ok,unlinked.to_dict()
    assert next(Decimal(f['value']) for f in unlinked.figures if f['claim']=='rollover_checking_receipts')==0


def test_rollover_association_uses_exact_cash_preimage_and_survives_reopen_permutation_and_copy(tmp_path):
    from time import monotonic
    from viva.investment.events import committed_statements
    from viva.retirement_funding.authority import read
    from viva.retirement_funding.posting_closure import materialize_closures
    from viva.investment.events import decode_statement
    ledger,accounts=annual_ledger(tmp_path);add_rollover(ledger,'PLAN-B','PLAN-C','100','2025-01-25','5975','5975','ROLLOVER-PAIR')
    events=tuple(ledger.events());c=sqlite3.connect(':memory:');frontier=materialize(c,events,resolver(events));request=Request.from_dict({'view':'direct_rollovers','plans':accounts,'currency':'USD','from':'2025-01-01','to':'2025-01-31'})
    statements=tuple(committed_statements(events,resolver(events)));membership=tuple(decode_statement(json.loads(row[0])) for row in c.execute('SELECT source_json FROM retirement_plan_members ORDER BY account'))
    def authority(values,event_prefix=events):return read(values,(),{},materialize_closures(event_prefix),request,monotonic()+2,membership=membership)
    original=authority(statements);relationships={f['association_id'] for f in original['figures']};assert len(relationships)==1
    incoming=next((s,r) for s in statements for r in s.rows if r.kind.value=='contribution' and r.funding_role=='retirement_rollover');destination,row=incoming;source,opposing=next((s,r) for s in statements for r in s.rows if r.cash_event_id==row.funding_witness.transaction_id)
    expected='retirement-rollover:'+digest((source.account.value,destination.account.value,row.funding_role_source.value,row.funding_reference.value,opposing.cash_event_id,row.cash_event_id))
    assert relationships=={expected}
    reordered=tuple(replace(s,rows=tuple(reversed(s.rows))) for s in reversed(statements))
    assert {f['association_id'] for f in authority(reordered)['figures']}==relationships
    # Pure association/copy control: equivalent immutable source observations
    # reuse the same accepted cash identity; they cannot create a second rollover.
    copied=(*reordered,replace(destination,observation_id='equivalent-observation-copy'))
    assert {f['association_id'] for f in authority(copied)['figures']}==relationships
    reopened=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
    assert {f['association_id'] for f in authority(statements,tuple(reopened.events()))['figures']}==relationships


def test_claim_seals_refuse_raw_copy_scalar_mutation_and_foreign_set():
    from viva.instrument_evidence import _attest_figure,authenticated_figure
    from viva.tools.envelope import figure,bounded
    from viva.retirement_funding.contracts import valid_subject
    subject=Request('annual_employee_contributions',('plan-a','plan-b'),'USD',year=2024).subject
    original=_attest_figure(figure('12000','Recorded employee contributions',quantity='investment_contribution',currency='USD',grade='unverified',record_ids=['doc'],boundary=bounded(whole=False),subject=subject),'employee_retirement_contributions',run_token=object())
    assert authenticated_figure(original)
    assert not authenticated_figure(dict(original))
    original['value']='12001';assert not authenticated_figure(original)
    with pytest.raises(EvidenceError):valid_subject({**subject,'member_ids':['plan-a']})
    with pytest.raises(EvidenceError):valid_subject({**subject,'foreign_key':True})


def test_report_lowering_stays_bounded_and_cannot_bind_set_total_as_one_plan(tmp_path):
    from types import SimpleNamespace
    from viva.tools import default_registry
    from viva.answer_program import CapabilityManifest,ProgramValidator,AnswerResourcePolicy,AnswerProgram
    from viva.retirement_funding.semantic import build_report
    from viva.retirement_funding.contracts import NUMERIC_CLAIMS,ASSERTION_CLAIMS
    ledger,accounts=annual_ledger(tmp_path);registry=default_registry(ledger.projection(),today='2026-01-01');manifest=CapabilityManifest.from_registry(registry)
    request=SimpleNamespace(parameters={'plans':accounts,'currency':'USD','from_year':'2021','to_year':'2025'},requested_claims=tuple((*NUMERIC_CLAIMS,*ASSERTION_CLAIMS)))
    program=build_report(request,manifest);validation=ProgramValidator(manifest,AnswerResourcePolicy()).validate(program);assert validation.ok,validation.to_dict()
    assert len(program.nodes)==6 and all(node.tool=='read_retirement_funding' for node in program.nodes)
    changed=program.to_dict();changed['bindings'][0]['selector']['entity_ref']=Request('annual_employee_contributions',tuple(accounts[:1]),'USD',year=2021).subject
    invalid=ProgramValidator(manifest,AnswerResourcePolicy()).validate(AnswerProgram.from_dict(changed));assert not invalid.ok
    for first,last in [('2020','2025'),('2025','2021'),('2021.0','2025')]:
        request.parameters.update(from_year=first,to_year=last)
        with pytest.raises(EvidenceError):build_report(request,manifest)


def test_recorded_population_is_bounded_before_unknown_year_filter(tmp_path):
    ledger,accounts=annual_ledger(tmp_path)
    for index in range(119):ledger.append(document_captured('unknown-'+str(index),'unread.pdf',1,'pay_stub',1.0,'2026-01-01'))
    events=tuple(ledger.events());c=sqlite3.connect(':memory:');frontier=materialize(c,events,resolver(events));output=result(c,frontier,{'view':'annual_employee_contributions','plans':accounts,'currency':'USD','year':2024},object(),'2025-01-01')
    assert not output.ok and output.refusal=='resource_limit'


def test_source_anchor_limit_counts_distinct_document_pages_and_expired_deadline_refuses():
    from viva.retirement_funding.lineage import Pool
    from viva.investment.contracts import Field,ResourceLimit
    from time import monotonic
    pool=Pool()
    for index in range(512):pool.add(Field(str(index),'doc-'+str(index//200),index%200+1,raw=str(index)),'owner',str(index))
    for index in range(100):pool.add(Field('0','doc-0',1,raw='0'),'same-owner',str(index))
    with pytest.raises(ResourceLimit):pool.add(Field('512','doc-2',113,raw='512'),'owner','512')
    output=result(None,None,{'view':'annual_employee_contributions','plans':['plan'],'currency':'USD','year':2024},object(),'2025-01-01',deadline=monotonic()-1)
    assert not output.ok and output.refusal=='resource_limit'


def test_model_catalog_is_source_proven_finite_and_rejects_foreign_set_year_and_frontier(tmp_path):
    from contextlib import contextmanager
    from viva.read_store import ReadStore
    from viva.tools import default_registry
    from viva.answer_program.intents import SemanticFamilyRegistry,SEMANTIC_REQUEST_VERSION
    from viva.answer_program.schema import ContractError
    from viva.retirement_funding.catalog import entries
    ledger,accounts=annual_ledger(tmp_path)
    with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
        reads.synchronize(ledger.store)
        @contextmanager
        def supplier():
            with reads.open_reader() as revision:yield revision
        registry=default_registry(ledger.projection(),today='2026-01-01',instrument_scope=supplier);catalog=registry.semantic_entities();sets=catalog['retirement_plan_sets']
        assert len(sets)==3 and all(set(row)=={'id','set_type','member_ids','label'} for row in sets)
        assert {tuple(row['member_ids']) for row in sets}=={(accounts[0],),(accounts[1],),tuple(sorted(accounts))}
        families=SemanticFamilyRegistry(catalog,currency_resolver=registry.instrument_currency);subject=Request('annual_employee_contributions',tuple(accounts),'USD',year=2024).subject
        raw={'request_version':SEMANTIC_REQUEST_VERSION,'outcome':'request','catalog_digest':families.catalog_digest,'entity_catalog_digest':families.entity_catalog_digest,'family':'retirement_annual_employee_contributions','parameters':{'plans_phrase':subject['account_set_id'],'year':'2024'},'parameter_sources':{'plans_phrase':{'source':'question','quote':'known retirement plans','derivation':'catalog_selection'},'year':{'source':'question','quote':'2024','derivation':'verbatim'}},'requested_claims':['employee_retirement_contributions']}
        assert families.parse(raw,require_grounding=False).kind=='request'
        import copy
        for change in ('foreign_set','stale_catalog','invalid_year','unknown_key'):
            changed=copy.deepcopy(raw)
            if change=='foreign_set':changed['parameters']['plans_phrase']='retirement-set:'+'f'*64
            elif change=='stale_catalog':changed['entity_catalog_digest']='stale'
            elif change=='invalid_year':changed['parameters']['year']='2024.0'
            else:changed['parameters']['raw_payroll']='secret'
            try:outcome=families.parse(changed,require_grounding=False)
            except ContractError:continue
            assert outcome.kind!='request',change
    # Explicit bound control: four authenticated plan rows never become an
    # apparently complete three-plan catalog. This is the normalized catalog
    # boundary, not a fabricated source acceptance fixture.
    c=sqlite3.connect(':memory:');c.execute('CREATE TABLE retirement_plan_members(account TEXT,currency TEXT)')
    c.executemany('INSERT INTO retirement_plan_members VALUES(?,?)',[(str(i),'USD') for i in range(4)])
    assert entries(c,[{'id':str(i),'name':'Retirement'} for i in range(4)])==([],False)


def test_paired_linked_effects_are_counted_once_and_later_classification_correction_is_current(tmp_path):
    from viva.ledger.events import transfer_linked,transfer_unlinked,ruling_recorded
    ledger,accounts=annual_ledger(tmp_path);add_rollover(ledger,'PLAN-B','PLAN-C','100','2025-01-25','5975','5975','ROLLOVER-PAIR')
    moves=ledger.projection().movements();outgoing=next(m for m in moves if m.account==accounts[0] and m.date=='2025-01-25' and m.amount==-100);incoming=next(m for m in moves if m.account==accounts[1] and m.date=='2025-01-25' and m.amount==100)
    ledger.append(transfer_linked(outgoing.key,incoming.key,'verified',{'decided_by':'human exact paired source'},'2025-01-26',by='human'))
    ledger.append(ruling_recorded('movement',incoming.key,'2025-01-27',legs=[{'major':'income','account':'Income:Salary','share':'1'}],said='Synthetic current income classification'))
    def current_income():
        events=tuple(ledger.events());c=sqlite3.connect(':memory:');frontier=materialize(c,events,resolver(events));out=result(c,frontier,{'view':'direct_rollovers','plans':accounts,'currency':'USD','from':'2025-01-01','to':'2025-01-31'},object(),'2025-02-01');assert out.ok,out.to_dict();return next(Decimal(f['value']) for f in out.figures if f['claim']=='rollover_attributed_income')
    # Ordinary accounting gives an active accepted transfer link precedence
    # over the inconsistent income classification; revoking the link exposes it.
    assert current_income()==0
    ledger.append(transfer_unlinked(outgoing.key,incoming.key,'2025-01-27'))
    assert current_income()==100
    ledger.append(ruling_recorded('movement',incoming.key,'2025-01-28',legs=[],said='Retract the preceding source-scoped classification'))
    assert current_income()==0
