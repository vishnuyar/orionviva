import json
from contextlib import contextmanager
import pytest
from viva.ledger.ledger import Ledger
from viva.ingest.brokerage_projector import post_brokerage
from viva.read_store import ReadStore
from viva.tools import default_registry
from viva.answer_program import CapabilityManifest,ProgramValidator,ProgramExecutor,DeterministicBinder,AnswerResourcePolicy
from viva.answer_program.intents import SemanticFamilyRegistry,SEMANTIC_REQUEST_VERSION
from viva.answer_program.schema import QuestionContext,ContractError
from viva.investment.projector import append
from viva.investment.authenticated import synchronize
from test_source_projector import facts


def request(families,parameters):
 return {'request_version':SEMANTIC_REQUEST_VERSION,'outcome':'request','catalog_digest':families.catalog_digest,'entity_catalog_digest':families.entity_catalog_digest,'family':'investment_positions','parameters':parameters,'parameter_sources':{key:{'source':'question','quote':value,'derivation':'verbatim'} for key,value in parameters.items()},'requested_claims':['security_units','investment_market_value','investment_holdings_count']}


def test_registered_semantic_family_default_tool_private_currency_authenticated_delivery(tmp_path):
 ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');f=facts();posted=post_brokerage(ledger,f);append(ledger,f,posted.account)
 with ReadStore.create(tmp_path/'reads','synthetic-only') as reads:
  synchronize(reads,ledger.store)
  @contextmanager
  def supplier():
   with reads.open_reader() as revision:yield revision
  registry=default_registry(ledger.projection(),today='2026-01-01',instrument_scope=supplier)
  assert 'read_investment_evidence' in registry.names()
  catalog=registry.semantic_entities()
  assert all('currency' not in row for row in catalog['accounts'])
  families=SemanticFamilyRegistry(catalog,currency_resolver=registry.instrument_currency)
  assert 'investment_positions' in families.ids and 'investment_activity_totals' in families.ids
  raw=request(families,{'account_phrase':'Test account','as_of':'2025-01-31'})
  question='Show Test account holdings at 2025-01-31.'
  parsed=families.parse(raw,QuestionContext(question=question,today='2026-01-01'))
  manifest=CapabilityManifest.from_registry(registry);program=families.lower(parsed,manifest)
  assert program.nodes[0].args['account']==posted.account and program.nodes[0].args['currency']=='USD'
  validation=ProgramValidator(manifest,AnswerResourcePolicy()).validate(program)
  assert validation.ok,validation.to_dict()
  execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,question)
  bound=DeterministicBinder(registry,'en-US').bind(program,execution)
  assert bound.result.answered,(bound.unbound,bound.result.detail)
  assert {figure['quantity'] for figure in bound.result.figures}=={'security_units','balance','count'}
  assert '1.25' in bound.result.text and '25.00' in bound.result.text
  assert registry.instrument_runtime.revision is None
  assert all(figure['grade']=='unverified' for figure in bound.result.figures)
  with pytest.raises(ContractError):families.parse(request(families,{**raw['parameters'],'currency':'EUR'}),require_grounding=False)
  no_currency=SemanticFamilyRegistry(catalog,currency_resolver=lambda account:None)
  with pytest.raises(ContractError):no_currency.lower(no_currency.parse(request(no_currency,raw['parameters']),require_grounding=False),manifest)
