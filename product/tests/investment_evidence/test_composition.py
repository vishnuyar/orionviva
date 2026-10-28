"""Registered finite report composition preserves existing resource policy."""
from viva.answer_program.intents import SemanticFamilyRegistry


def test_finite_composed_investment_report_families_are_registered():
 families=SemanticFamilyRegistry()
 assert {'investment_account_report','investment_account_report_first_years','investment_account_report_remaining_years'}<=set(families.ids)


def manifest():
 from viva.ledger.projection import LedgerProjection
 from viva.tools import default_registry
 from viva.answer_program import CapabilityManifest
 return CapabilityManifest.from_registry(default_registry(LedgerProjection([])))


def request(family,**parameters):
 from viva.answer_program.intents import SemanticRequest
 from viva.investment.composition import REPORT_CLAIMS
 return SemanticRequest(family,{'account_phrase':'Assets:BrokerTest','currency':'USD','from':'2021-01-01','to':'2025-12-31','as_of':'2025-12-31',**parameters},('annual_activity',) if family.endswith('remaining_years') else REPORT_CLAIMS,'static-test')


def test_actual_registered_report_bounds_fit_and_all_five_years_in_one_program_refuse():
 from viva.answer_program import ProgramValidator,AnswerResourcePolicy
 from viva.answer_program.schema import AnswerProgram,ProgramNode
 from viva.investment.composition import build
 m=manifest();validator=ProgramValidator(m,AnswerResourcePolicy())
 cases=[('investment_account_report',{},5,214000,308),('investment_account_report_first_years',{'to':'2022-12-31'},6,246000,372),('investment_account_report_remaining_years',{'from':'2023-01-01'},3,96000,192)]
 for name,parameters,count,byte_bound,figure_bound in cases:
  program=build(request(name,**parameters),m);validation=validator.validate(program)
  assert validation.ok,validation.to_dict()
  assert len(program.nodes)==count
  cost=validator._cost(program,{node.id:i+1 for i,node in enumerate(program.nodes)})
  assert cost['max_evidence_bytes']==byte_bound and cost['max_figures']==figure_bound
 nodes=tuple(ProgramNode(id='n'+str(i),kind='tool_read',tool=tool,depends_on=() if i==0 else ('n'+str(i-1),)) for i,tool in enumerate(['read_investment_evidence']*6+['read_account_measurements']*2+['read_instrument_details']))
 combined=AnswerProgram(mode='answer',question_kind='resource-negative',shape=None,nodes=nodes,bindings=())
 cost=validator._cost(combined,{node.id:i+1 for i,node in enumerate(nodes)});defects=[]
 validator._validate_cost(cost,lambda *args:defects.append(args))
 assert cost['max_evidence_bytes']==342000 and cost['max_figures']==564 and cost['max_execution_ms']==18000 and cost['dependency_depth']==9 and defects


def test_year_sets_cannot_expand_first_or_remaining_dispatch():
 import pytest
 from viva.investment.composition import build
 from viva.investment.contracts import EvidenceError
 m=manifest()
 for req in (request('investment_account_report_first_years',to='2023-12-31'),request('investment_account_report_remaining_years',**{'from':'2022-01-01'}),request('investment_account_report_first_years',**{'from':'2021-02-01','to':'2022-12-31'})):
  with pytest.raises(EvidenceError):build(req,m)


def test_genuine_source_default_sync_compiled_report_renders_every_required_section(tmp_path):
 import json
 from test_wire import populate,execute_wire,capture_dir
 from viva.read_store import ReadStore
 from viva.investment.composition import REPORT_CLAIMS
 ledger,packet=populate(tmp_path,annual_report=True)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  reads.synchronize(ledger.store)
  for family in ('investment_account_report','investment_account_report_first_years'):
   wire,result,program,registry=execute_wire(ledger,reads,family,{'account_phrase':'Test account','from':'2025-01-01','to':'2025-12-31','as_of':'2025-12-31'},REPORT_CLAIMS,'Report Test account from 2025-01-01 to 2025-12-31 with holdings at 2025-12-31.')
   assert result.answered and len(program.nodes)==5
   assert {figure['quantity'] for figure in wire['figures']} >= {'security_units','holding_cost_basis','investment_contribution','investment_dividend','sale_proceeds','disposed_cost_basis','realized_gain','balance','ratio_of_balance'}
   assert all(figure['receipt_ids'] for figure in wire['figures'])
   assert len(wire['numerical_receipts'])==5
   assert any(figure['quantity']=='security_units' and figure['grade']=='unverified' for figure in wire['figures'])
   assert 'Recorded cash at its own measured date' in result.text
   assert 'Derived disposed cost basis' in result.text and 'FIFO' not in result.text
   (capture_dir(tmp_path)/('genuine-composed-'+family+'.json')).write_text(json.dumps(wire,indent=2)+'\n')
