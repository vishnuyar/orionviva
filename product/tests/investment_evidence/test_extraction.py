import copy,json
import pytest
from viva.investment.extraction import *
from viva.ingest.brokerage import from_brokerage_json,BrokerageFacts

def fixture():
 def f(raw,page=1):return {'raw':raw,'page':page}
 headers={k:None for k in HEADERS}
 headers.update(account_reference=f('BROKER-REF'),currency=f('USD'),period_start=f('01/01/2025'),period_end=f('01/31/2025'),as_of=f('01/31/2025'),opening_cash=f('0.00'),closing_cash=f('0.00'))
 p={k:None for k in POSITION};p.update(identifier=f('TEST-SEC'),label=f('Test security'),units=f('1.25000000'),market_value=f('25.00'),cost_basis=f('20.00',None))
 r={k:None for k in ROW};r.update(date=f('01/25/2025'),kind=f('buy'),amount=f('25.00'),security_identifier=f('TEST-SEC'))
 return {'schema':'investment-source-v1','headers':headers,'positions':[p],'rows':[r]}

def legacy():return {'cash_raw':'0.00','total_raw':'25.00','as_of_raw':'01/31/2025','positions':[{'instrument':'TEST-SEC','units_raw':'1.25000000','market_value_raw':'25.00','cost_basis_raw':'20.00','page':1}], 'activity':[]}

def test_actual_brokerage_parser_preserves_closed_source_extension_and_missing_page():
 data=legacy();data['investment_source']=fixture()
 facts,error=from_brokerage_json(json.dumps(data),'source','en-US','USD')
 assert error is None
 assert facts.investment_source.to_dict()==data['investment_source']
 assert BrokerageFacts.from_dict(facts.to_dict()).to_dict()==facts.to_dict()
 assert dict(facts.investment_source.positions[0])['cost_basis'].page is None
 assert dict(facts.investment_source.positions[0])['units'].raw=='1.25000000'
 assert not hasattr(dict(facts.investment_source.positions[0])['units'],'grade')

def test_legacy_brokerage_serialization_stays_readable_without_investment_evidence():
 facts,error=from_brokerage_json(json.dumps(legacy()),'source','en-US','USD')
 assert error is None and facts.investment_source is None
 saved=facts.to_dict();saved.pop('investment_source')
 assert BrokerageFacts.from_dict(saved).investment_source is None

@pytest.mark.parametrize('extra',['grade','status','canonical_account','cash_event_id','event_digest'])
def test_extraction_cannot_grant_local_authority(extra):
 data=fixture();data['rows'][0]['amount'][extra]='verified'
 with pytest.raises(EvidenceError):parse(data)
 data=legacy();data['investment_source']=fixture();data['investment_source']['headers'][extra]=None
 facts,error=from_brokerage_json(json.dumps(data),'source','en-US','USD')
 assert facts is None and error.startswith('investment source:')

@pytest.mark.parametrize('bad',[True,0,-1,201,1.0,'1'])
def test_invalid_page_never_becomes_source_page(bad):
 data=fixture();data['rows'][0]['amount']['page']=bad
 with pytest.raises(EvidenceError):parse(data)

def test_no_activity_array_is_not_explicit_source_no_activity():
 data=fixture();data['rows']=[]
 source=parse(data)
 assert dict(source.headers)['no_activity'] is None
 assert source.rows==()

def test_multiplicity_and_unreadable_raw_values_are_preserved_not_repaired():
 data=fixture();data['rows']*=2;data['positions'][0]['units']['raw']='unreadable'
 source=parse(data)
 assert len(source.rows)==2
 assert dict(source.positions[0])['units'].raw=='unreadable'
