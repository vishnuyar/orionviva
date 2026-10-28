"""Approved source-only normalized role and exact opposing cash witness controls."""
import copy,json
from decimal import Decimal
import pytest
from viva.investment.extraction import parse
from viva.investment.payroll_extraction import validate_pages
from viva.investment.contracts import EvidenceError,Request
from viva.ingest.brokerage import from_brokerage_json
from viva.ingest.brokerage_projector import post_brokerage
from viva.ledger import Ledger
from viva.investment.events import committed_statements
from viva.investment.funding import resolver
from viva.investment.healing import heal_after_source
from viva.investment.authority import read
from test_extraction import ROW


def source_packet(incoming,role='retirement_rollover',reference='TRANSFER-1',counterpart=None):
 def f(raw):return {'raw':raw,'page':1}
 account='DEST-REF' if incoming else 'ORIGIN-REF';counterpart=counterpart or ('ORIGIN-REF' if incoming else 'DEST-REF')
 amount='100';kind='contribution' if incoming else 'withdrawal'
 raw_role='Direct rollover from origin' if incoming else 'Direct rollover to destination'
 if role=='other_broker':raw_role='Investment account transfer'
 row={key:None for key in ROW};row.update(date=f('2025-01-25'),kind=f(kind),amount=f(amount),printed_reference=f(reference),counterpart_reference=f(counterpart),funding_role={**f(raw_role),'role':role})
 source={'schema':'investment-source-v2','headers':{'account_reference':f(account),'currency':f('USD'),'period_start':f('2025-01-01'),'period_end':f('2025-01-31'),'as_of':f('2025-01-31'),'opening_cash':f('0' if incoming else '100'),'closing_cash':f('100' if incoming else '0'),'activity_complete':None,'no_activity':None},'positions':[],'rows':[row]}
 return {'institution':'Destination broker' if incoming else 'Origin broker','account_ref':'Destination account' if incoming else 'Origin account','account_number':'DEST-1' if incoming else 'ORIGIN-1','cash_raw':'100' if incoming else '0','total_raw':'100' if incoming else '0','opening_cash_raw':'0' if incoming else '100','as_of_raw':'2025-01-31','positions':[],'activity':[{'date_raw':'2025-01-25','kind':kind,'amount_raw':amount,'description':raw_role}],'investment_source':source}


def facts(incoming,**kwargs):
 packet=source_packet(incoming,**kwargs)
 value,error=from_brokerage_json(json.dumps(packet),'destination-source' if incoming else 'origin-source','en-US','USD')
 assert error is None,error
 return value


def test_new_normalized_role_preserves_exact_raw_and_v1_stays_closed():
 source=source_packet(True)['investment_source'];actual=parse(source)
 assert actual.to_dict()==source
 role=dict(actual.rows[0])['funding_role'];assert role.raw=='Direct rollover from origin' and role.role=='retirement_rollover'
 changed=copy.deepcopy(source);changed['schema']='investment-source-v1'
 with pytest.raises(EvidenceError):parse(changed)
 changed=copy.deepcopy(source);changed['rows'][0]['funding_role']['grade']='verified'
 with pytest.raises(EvidenceError):parse(changed)
 changed=copy.deepcopy(source);changed['rows'][0]['funding_role']['page']=2
 with pytest.raises(EvidenceError):validate_pages(parse(changed),1)

@pytest.mark.parametrize('role',['other_broker','retirement_rollover'])
def test_actual_two_broker_posting_binds_exact_opposing_source_without_reposting(tmp_path,role):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 outgoing=facts(False,role=role);assert post_brokerage(ledger,outgoing).action=='posted'
 incoming=facts(True,role=role);posted=post_brokerage(ledger,incoming);assert posted.action=='posted'
 financial=[(event.event_id,event.body) for event in ledger.events() if event.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]
 heal_after_source(ledger,incoming.doc_id)
 events=tuple(ledger.events());actual=read(committed_statements(events,resolver(events)),Request('activity_totals',posted.account,'USD',start='2025-01-01',end='2025-01-31',grouping='none'))
 contribution=next(figure for figure in actual['figures'] if figure['claim']=='investment_contribution')
 assert Decimal(contribution['value'])==100 and contribution['funding_roles']==[role]
 assert [(event.event_id,event.body) for event in ledger.events() if event.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]==financial


def post_packet(ledger,packet,doc):
 currency=packet['investment_source']['headers']['currency']['raw']
 value,error=from_brokerage_json(json.dumps(packet),doc,'en-US',currency);assert error is None,error
 result=post_brokerage(ledger,value);assert result.action in ('posted','duplicate'),result
 return value,result


def activity(ledger,account):
 events=tuple(ledger.events())
 return read(committed_statements(events,resolver(events)),Request('activity_totals',account,'USD',start='2025-01-01',end='2025-01-31',grouping='none'))


def test_actual_opposing_source_arrival_heals_without_reposting(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 incoming,posted=post_packet(ledger,source_packet(True),'destination-source')
 assert not any(f['claim']=='investment_contribution' for f in activity(ledger,posted.account)['figures'])
 outgoing,_=post_packet(ledger,source_packet(False),'origin-source')
 before=[(e.event_id,e.body) for e in ledger.events() if e.event_type=='TransactionRecorded']
 assert heal_after_source(ledger,outgoing.doc_id)==1
 assert next(f['value'] for f in activity(ledger,posted.account)['figures'] if f['claim']=='investment_contribution')=='100'
 assert heal_after_source(ledger,outgoing.doc_id)==0
 assert [(e.event_id,e.body) for e in ledger.events() if e.event_type=='TransactionRecorded']==before

@pytest.mark.parametrize('mutation',['date','cent','destination','role','reference','unknown_role','currency','missing_page'])
def test_printed_reference_never_overrides_incompatible_source_components(tmp_path,mutation):
 source=source_packet(False)
 row=source['investment_source']['rows'][0]
 if mutation=='date':row['date']['raw']='2025-01-24';source['activity'][0]['date_raw']='2025-01-24'
 elif mutation=='cent':row['amount']['raw']='100.01';source['activity'][0]['amount_raw']='100.01';source['opening_cash_raw']='100.01';source['investment_source']['headers']['opening_cash']['raw']='100.01'
 elif mutation=='destination':row['counterpart_reference']['raw']='OTHER-DESTINATION'
 elif mutation=='role':row['funding_role']['role']='other_broker'
 elif mutation=='reference':row['printed_reference']=None
 elif mutation=='unknown_role':row['funding_role']['role']='unknown'
 elif mutation=='currency':source['investment_source']['headers']['currency']['raw']='EUR'
 else:row['printed_reference']['page']=None
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 outgoing,_=post_packet(ledger,source,'origin-source');incoming,posted=post_packet(ledger,source_packet(True),'destination-source')
 before=[(e.event_id,e.body) for e in ledger.events() if e.event_type=='TransactionRecorded']
 heal_after_source(ledger,outgoing.doc_id)
 actual=activity(ledger,posted.account)
 assert not any(f['claim']=='investment_contribution' for f in actual['figures'])
 assert {f['claim'] for f in actual['figures']}=={'investment_dividend','sale_proceeds','disposed_cost_basis','realized_gain'}
 assert [(e.event_id,e.body) for e in ledger.events() if e.event_type=='TransactionRecorded']==before


def test_distinct_repeated_opposing_occurrences_hold_instead_of_collapsing(tmp_path):
 source=source_packet(False);source['activity']*=2;source['investment_source']['rows']*=2
 source['opening_cash_raw']='200';source['investment_source']['headers']['opening_cash']['raw']='200'
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 outgoing,_=post_packet(ledger,source,'origin-source');incoming,posted=post_packet(ledger,source_packet(True),'destination-source')
 heal_after_source(ledger,outgoing.doc_id)
 assert not any(f['claim']=='investment_contribution' for f in activity(ledger,posted.account)['figures'])


def test_equivalent_opposing_copy_and_source_correction_retraction_follow_dependency_only(tmp_path):
 from viva.investment.events import retract_source
 from viva.investment.lifecycle import SourceChange
 from viva.investment.contracts import digest
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 source=source_packet(False);outgoing,_=post_packet(ledger,source,'origin-source');incoming,posted=post_packet(ledger,source_packet(True),'destination-source')
 before=[(e.event_id,e.body) for e in ledger.events() if e.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]
 copied,_=post_packet(ledger,source,'opposing-copy');heal_after_source(ledger,copied.doc_id)
 assert next(f['value'] for f in activity(ledger,posted.account)['figures'] if f['claim']=='investment_contribution')=='100'
 bad=copy.deepcopy(source);bad['investment_source']['rows'][0]['funding_role']['role']='other_broker'
 changed,_=post_packet(ledger,bad,'origin-source');heal_after_source(ledger,changed.doc_id)
 assert not any(f['claim']=='investment_contribution' for f in activity(ledger,posted.account)['figures'])
 restored,_=post_packet(ledger,source,'origin-source');heal_after_source(ledger,restored.doc_id)
 assert next(f['value'] for f in activity(ledger,posted.account)['figures'] if f['claim']=='investment_contribution')=='100'
 assert [(e.event_id,e.body) for e in ledger.events() if e.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]==before


def test_two_way_source_cash_is_stable_without_witness_churn_or_new_wealth(tmp_path):
 from viva.ledger.accounting import financial_statements
 from viva.read_store import ReadStore
 from viva.investment.authenticated import read as native_read
 origin=source_packet(False,role='other_broker');destination=source_packet(True,role='other_broker')
 a_out=origin['investment_source']['rows'][0];a_out['date']['raw']='2025-01-10';a_out['printed_reference']['raw']='A-TO-B'
 origin['activity'][0]['date_raw']='2025-01-10'
 a_in=copy.deepcopy(a_out);a_in['date']['raw']='2025-01-20';a_in['kind']['raw']='contribution';a_in['printed_reference']['raw']='B-TO-A'
 origin['investment_source']['rows'].append(a_in);origin['activity'].append({'date_raw':'2025-01-20','kind':'contribution','amount_raw':'100','description':'Investment account transfer'})
 origin['cash_raw']='100';origin['total_raw']='100';origin['investment_source']['headers']['closing_cash']['raw']='100'
 b_in=destination['investment_source']['rows'][0];b_in['date']['raw']='2025-01-10';b_in['printed_reference']['raw']='A-TO-B'
 destination['activity'][0]['date_raw']='2025-01-10'
 b_out=copy.deepcopy(b_in);b_out['date']['raw']='2025-01-20';b_out['kind']['raw']='withdrawal';b_out['printed_reference']['raw']='B-TO-A'
 destination['investment_source']['rows'].append(b_out);destination['activity'].append({'date_raw':'2025-01-20','kind':'withdrawal','amount_raw':'100','description':'Investment account transfer'})
 destination['cash_raw']='0';destination['total_raw']='0';destination['investment_source']['headers']['closing_cash']['raw']='0'
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 a,a_posted=post_packet(ledger,origin,'origin-source');b,b_posted=post_packet(ledger,destination,'destination-source')
 before=[(event.event_id,event.body) for event in ledger.events() if event.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]
 heal_after_source(ledger,b.doc_id)
 for account in (a_posted.account,b_posted.account):
  assert next(f['value'] for f in activity(ledger,account)['figures'] if f['claim']=='investment_contribution')=='100'
 count=len(tuple(ledger.events()))
 assert heal_after_source(ledger,a.doc_id)==0 and heal_after_source(ledger,b.doc_id)==0
 assert len(tuple(ledger.events()))==count
 assert [(event.event_id,event.body) for event in ledger.events() if event.event_type in ('TransactionRecorded','PositionObserved','ClosingBalanceObserved')]==before
 statement=financial_statements(ledger.projection())
 assert Decimal(statement['balance_sheet']['by_currency']['USD']['net'])==100
 assert sum(Decimal(value['income']) for value in statement['profit_loss']['by_currency'].values())==0
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  reads.synchronize(ledger.store)
  with reads.open_reader() as revision:
   for account in (a_posted.account,b_posted.account):
    actual=native_read(reads,revision,Request('activity_totals',account,'USD',start='2025-01-01',end='2025-01-31',grouping='none'))
    assert next(f['value'] for f in actual['figures'] if f['claim']=='investment_contribution')=='100'
