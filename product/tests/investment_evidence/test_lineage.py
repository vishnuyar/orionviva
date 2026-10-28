"""Lossless source pooling, complete wire bounds and tamper refusal."""
import copy,json
from dataclasses import replace
import pytest
from viva.investment import lineage
from viva.investment.authority import read
from viva.investment.contracts import Request,digest,EvidenceError
from viva.investment.tool import result as tool_result
from test_draft import fixture,ACCOUNT


def request():return Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='none')


def test_pool_roundtrip_preserves_every_field_owner_identity_and_operand(monkeypatch):
 _,statement=fixture()
 pooled=read((statement,),request())
 expanded=lineage.validate_result(pooled)
 with monkeypatch.context() as patch:
  patch.setattr(lineage,'pool',lambda result:result)
  original=read((statement,),request())
 assert {digest({key:value for key,value in record.items() if key!='owners'}):record for record in expanded.values()}==original['source_fields']
 for after,before in zip(pooled['figures'],original['figures']):
  assert [pooled['source_identities']['observations'][key] for key in after['observation_ids']]==before['observation_ids']
  assert [pooled['source_identities']['rows'][key] for key in after['row_ids']]==before['row_ids']
  assert {digest({key:value for key,value in expanded[field].items() if key!='owners'}) for field in lineage.figure_field_ids(pooled,after)}==set(before['source_field_ids'])
  assert {digest(lineage.expand_anchors(pooled)[key]) for key in after['anchor_ids']}==set(before['anchor_ids'])
  for actual,prior in zip(after['operands'],before['operands']):
   assert pooled['source_identities']['rows'][actual['row']]==prior['row']
   assert {digest(lineage.expand_anchors(pooled)[key]) for key in actual['anchor_ids']}==set(prior['anchor_ids'])
   assert actual['operation']==prior['operation'] and actual['proceeds']==prior['proceeds'] and actual['reported_realized_gain']==prior['reported_realized_gain']

@pytest.mark.parametrize('mutation',['field_index','owner_index','source_page','source_grade','source_group','source_row'])
def test_closed_lineage_reference_mutations_fail(mutation):
 _,statement=fixture();value=read((statement,),request())
 if mutation=='field_index':value['source_fields']['records'][0][2][0][0]=True
 elif mutation=='owner_index':value['source_fields']['owner_shapes'][value['source_fields']['records'][0][1]][0]=[999,0]
 elif mutation=='source_page':next(iter(value['anchors'].values()))['page']=0
 elif mutation=='source_grade':value['source_fields']['records'][0][2][0].extend([0,'invented','accepted'])
 elif mutation=='source_group':value['figures'][0]['source_field_groups']=['missing']
 else:value['figures'][0]['row_ids']=['missing']
 with pytest.raises((EvidenceError,ValueError,TypeError,KeyError)):lineage.validate_result(value)


def test_complete_emitted_tool_wire_retains_figure_relationships_and_refuses_byte_overrun():
 _,statement=fixture();value=read((statement,),request())
 arguments={'view':'activity_totals','account':ACCOUNT,'currency':'USD','from':'2025-01-01','to':'2025-12-31','grouping':'none'}
 result=tool_result(None,None,arguments,object(),'2026-01-01',read_evidence=lambda request,deadline:value)
 assert result.ok
 wire=result.to_dict();assert len(json.dumps(wire,separators=(',',':'),ensure_ascii=False).encode())<=32000
 assert set(wire['data']['figure_sources'])=={figure['authority_record_id'] for figure in wire['figures']}
 for figure in result.figures:
  assert figure['source_lineage_digest']==lineage.lineage_digest(wire['data'])
  for key in ('anchor_ids','source_field_groups','observation_ids','row_ids','funding_roles','operands'):
   assert lineage.expand_figure_sources(wire['data'])[figure['authority_record_id']][key]==figure[key]
 inflated=copy.deepcopy(value);inflated['dispositions']=[{'claim':'realized_gain','status':'incomplete','detail':'x'*32000}]
 refused=tool_result(None,None,arguments,object(),'2026-01-01',read_evidence=lambda request,deadline:inflated)
 assert not refused.ok and refused.refusal=='resource_limit' and not refused.figures


def selected_owners(result,figure):
 records=lineage.expand_fields(result)
 return {(records[identity]['value'],*records[identity]['owners'][owner]) for identity,owner in lineage.figure_field_uses(result,figure)}


def test_equal_source_value_across_gain_dividend_and_dates_keeps_exact_figure_owners():
 _,statement=fixture(gain='3')
 result=read((statement,),request());figures={figure['claim']:figure for figure in result['figures']}
 dividend=selected_owners(result,figures['investment_dividend'])
 gain=selected_owners(result,figures['realized_gain'])
 proceeds=selected_owners(result,figures['sale_proceeds'])
 assert ('3','statement','/rows/1/amount') in dividend
 assert ('3','statement','/rows/2/realized_gain') in gain
 assert ('3','statement','/rows/2/realized_gain') in proceeds
 assert ('3','statement','/rows/2/realized_gain') not in dividend
 assert ('3','statement','/rows/1/amount') not in gain|proceeds
 assert ('2025-12-31','statement','/rows/1/date') in dividend
 assert ('2025-12-31','statement','/rows/2/date') not in dividend
 assert ('2025-12-31','statement','/end') in dividend&gain&proceeds
 # One exact source value record remains shared; figure ownership is explicit.
 common=set(lineage.figure_field_ids(result,figures['investment_dividend']))&set(lineage.figure_field_ids(result,figures['realized_gain']))
 records=lineage.expand_fields(result)
 assert any(records[key]['value']=='3' for key in common)


def test_equal_units_basis_fields_share_data_without_borrowing_eachothers_role():
 from test_draft import f
 _,statement=fixture();position=statement.positions[0];same=f('25')
 statement=replace(statement,positions=(replace(position,units=same,basis=same),))
 result=read((statement,),Request('positions',ACCOUNT,'USD',as_of='2025-12-31'))
 figures={figure['claim']:figure for figure in result['figures']}
 units=selected_owners(result,figures['security_units']);basis=selected_owners(result,figures['holding_cost_basis'])
 assert ('25','statement','/positions/0/units') in units and ('25','statement','/positions/0/basis') not in units
 assert ('25','statement','/positions/0/basis') in basis and ('25','statement','/positions/0/units') not in basis


def test_real_committed_repeated_dividend_occurrences_keep_multiplicity_and_exact_owners(tmp_path):
 from test_draft import resolve,f
 from viva.ledger.ledger import Ledger
 from viva.ledger.events import Provenance
 from viva.ledger.postings import brokerage_activity_transaction
 from viva.investment.events import append_statement,committed_statements
 events,statement=fixture()
 cash=brokerage_activity_transaction(ACCOUNT,'dividend','3','second equal dividend','2025-12-31',provenance=Provenance(doc_id='source',page=2));events.append(cash)
 row=replace(statement.rows[1],observation_id='distinct-second-dividend',local_id='3',ordinal=3,cash_event_id=cash.event_id,cash_body_digest=digest(cash.body))
 statement=replace(statement,rows=(*statement.rows,row),closing_cash=f('136'))
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for event in events:ledger.append(event)
 append_statement(ledger,statement,resolve)
 result=read(committed_statements(tuple(ledger.events()),resolve),request())
 figure=next(figure for figure in result['figures'] if figure['claim']=='investment_dividend')
 assert figure['value']=='6'
 assert {result['source_identities']['rows'][key] for key in figure['row_ids']}=={statement.rows[1].observation_id,row.observation_id}
 owners=selected_owners(result,figure)
 assert ('3','statement','/rows/1/amount') in owners and ('3','statement','/rows/3/amount') in owners
 assert ('3','statement','/rows/2/amount') not in owners


def test_actual_pre_payroll_source_events_replay_without_canonical_body_change(tmp_path):
 from pathlib import Path
 from viva.ledger.events import Event
 from viva.ledger.ledger import Ledger
 from viva.investment.events import committed_statements
 from test_draft import resolve
 old=json.loads((Path(__file__).parent/'fixtures/investment/pre-payroll-investment-v1-events.json').read_text())
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
 for item in old:ledger.append(Event.from_dict(item))
 statements=committed_statements(tuple(ledger.events()),resolve)
 assert len(statements)==1 and statements[0].rows[0].funding_status=='accepted'
 result=read(statements,request())
 assert {figure['claim']:figure['value'] for figure in result['figures']}=={'investment_contribution':'100','investment_dividend':'3','sale_proceeds':'30','disposed_cost_basis':'35','realized_gain':'-5'}


def test_investment_public_provenance_reference_is_complete_and_closed():
 from viva.tools.envelope import ToolResult
 _,statement=fixture();value=read((statement,),request())
 args={'view':'activity_totals','account':ACCOUNT,'currency':'USD','from':'2025-01-01','to':'2025-12-31','grouping':'none'}
 actual=tool_result(None,None,args,object(),'2026-01-01',read_evidence=lambda *args:value)
 assert actual.ok
 wire=actual.to_dict()
 assert lineage.expand_public_provenance(wire)==actual.provenance
 # Generic/C ToolResult wire stays exactly its full ordinary provenance list.
 generic=ToolResult('ordinary',True,provenance=[{'doc_id':'source','page':2}])
 assert generic.to_dict()['provenance']==generic.provenance
 for bad in ([{'source_anchor_pool':'other'}],[{'source_anchor_pool':'data.anchors','extra':True}],[],{}):
  changed=copy.deepcopy(wire);changed['provenance']=bad
  with pytest.raises(EvidenceError):lineage.expand_public_provenance(changed)
