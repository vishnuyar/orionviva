"""Actual Session/bridge source stability, including its own recorded exchange."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from viva.vault import Vault
from viva.session import Session
from viva.tools import default_registry
from viva.instrument_runtime import vault_revision_supplier
from viva.answer_program.intents import SemanticFamilyRegistry,SEMANTIC_REQUEST_VERSION
from viva.answer_program.compiler import CompilationResult,CompileExchange
from viva.desktop_bridge.conversation_actions import ConversationActions
from viva.ledger.events import Event,Provenance
from viva.ledger.postings import simple_transaction
from test_wire import populate,source_packet

QUESTION='Show Test account holdings and cost basis at 2025-01-31.'

class SourceCompiler:
 def __init__(self,validator,manifest,before=None):self.validator=validator;self.manifest=manifest;self.before=before
 def set_entity_catalog(self,catalog):self.families=SemanticFamilyRegistry(catalog)
 def set_instrument_currency_resolver(self,resolver):self.families._currency_resolver=resolver
 def set_instrument_context(self,context):self.families.instrument_context=context
 def compile(self,context):
  params={'account_phrase':'Test account','as_of':'2025-01-31'}
  raw={'request_version':SEMANTIC_REQUEST_VERSION,'outcome':'request','catalog_digest':self.families.catalog_digest,'entity_catalog_digest':self.families.entity_catalog_digest,'family':'investment_positions','parameters':params,'parameter_sources':{key:{'source':'question','quote':value,'derivation':'verbatim'} for key,value in params.items()},'requested_claims':['security_units','holding_cost_basis']}
  out=self.families.parse(raw,context);program=self.families.lower(out,self.manifest)
  if self.before:self.before()
  return CompilationResult(program,self.validator.validate(program),(CompileExchange('synthetic-local',{'question':context.question},{'family':'investment_positions'}),),out)

@pytest.fixture
def opened(tmp_path,monkeypatch):
 from viva import env
 monkeypatch.setattr(env,'CONFIG_HOME',tmp_path/'config')
 for key,name in [('MERCHANTCORE_HOME','merchant'),('VIVA_PROFILES','profiles')]:
  p=tmp_path/name;p.mkdir();monkeypatch.setenv(key,str(p))
 empty=tmp_path/'empty.env';empty.write_text('');monkeypatch.setenv('VIVA_ENV_FILE',str(empty));monkeypatch.setenv('VIVA_CATALOG',str(tmp_path/'merchant/catalog.json'))
 template,packet=populate(tmp_path/'source')
 vault=Vault.open(tmp_path/'vault','synthetic-only',start_read_store_worker=False)
 events=tuple(template.events());vault.ledger.append_atomically(lambda projection:events)
 fixture=Path(__file__).parents[1]/'investment_evidence/fixtures/investment'
 for name in ('synthetic-investment-source.pdf','synthetic-bank-source.pdf'):vault.raw.put((fixture/name).read_bytes())
 assert vault.wait_for_read_store(timeout=2)
 yield vault
 vault.close()


def session(vault,before=None):
 return Session(default_registry(vault.ledger.projection(),'en-US',instrument_scope=vault_revision_supplier(vault)),lambda validator,manifest,policy:SourceCompiler(validator,manifest,before),ledger=vault.ledger,locale='en-US')


def change(vault,kind):
 if kind=='cash':vault.ledger.append(simple_transaction('Assets:BankTest','-0.01','Independent source cash append','2025-01-26',provenance=Provenance('cash-source-change',1)))
 elif kind=='correction':
  from viva.ingest.brokerage import from_brokerage_json
  from viva.ingest.brokerage_projector import post_brokerage
  packet=source_packet();packet['investment_source']['positions'][0]['cost_basis']['page']=None
  doc=next(event.provenance.doc_id for event in vault.ledger.events() if event.event_type=='PositionObserved')
  facts,error=from_brokerage_json(json.dumps(packet),doc,'en-US','USD');assert error is None
  assert post_brokerage(vault.ledger,facts).action=='duplicate'
 else:raise AssertionError(kind)


def test_actual_session_classifies_investment_and_preserves_own_read_recorded_advance(opened):
 turn=session(opened).ask(QUESTION)
 assert turn.result.answered
 assert turn.instrument_read
 assert turn.delivery_identity==opened.ledger.store.authenticated_identity()[:2]
 assert any(event.event_type=='ReadRecorded' and event.body.get('phase')=='speak' for event in opened.ledger.events())

@pytest.mark.parametrize('kind',['cash','correction'])
def test_actual_session_source_change_before_read_refuses(opened,kind):
 turn=session(opened,lambda:change(opened,kind)).ask(QUESTION)
 assert not turn.result.answered and not turn.result.figures

@pytest.mark.parametrize('kind',['cash','correction'])
def test_actual_session_source_change_during_read_refuses(opened,kind,monkeypatch):
 from viva.investment import authenticated
 original=authenticated.read;ran=[]
 def changed(*args,**kwargs):
  result=original(*args,**kwargs)
  if not ran:ran.append(True);change(opened,kind)
  return result
 monkeypatch.setattr(authenticated,'read',changed)
 turn=session(opened).ask(QUESTION)
 assert ran and not turn.result.answered and not turn.result.figures

@pytest.mark.parametrize('kind',['cash','correction'])
def test_actual_bridge_change_after_answer_before_settlement_refuses_delivery(opened,kind,monkeypatch):
 import importlib
 conversation_actions=importlib.import_module('viva.surface.conversation')
 bridge=ConversationActions(opened);bridge._opened=lambda mode,turn_id:session(opened)
 original=conversation_actions.conversation;ran=[]
 def changed(*args,**kwargs):
  result=original(*args,**kwargs)
  if not ran:ran.append(True);change(opened,kind)
  return result
 monkeypatch.setattr(conversation_actions,'conversation',changed)
 result=bridge.ask({'question':QUESTION,'context_mode':'new_question'})
 assert ran and result['kind']=='refused' and result['reason']=='current_data_unavailable',result
 assert not result['state']['figures'] and not result['state']['numerical_receipts']
