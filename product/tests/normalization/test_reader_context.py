import json
from viva.ingest.reader import read_with_retry
from viva.ingest.instrument_read import parser_for
from vivacore.models.base import ModelResult
from test_instrument_projector_b import mortgage,setup
from viva.ingest.pipeline import capture_and_ingest

def response(text,cost=.123):return ModelResult(text,'resolved',19,7,cost,0,{}, {'usage':{'input_tokens':19,'output_tokens':7}})

def test_real_mortgage_reader_retains_actual_arguments_not_environment():
 payload=mortgage();payload['payments'][0]['fees']=None
 result=read_with_retry(lambda prompt:response(json.dumps(payload)),'prompt','source','en_US','EUR',parse_fn=parser_for('mortgage_statement'),configured_model='configured')
 assert result.facts is not None,result.error
 context=getattr(result.phases[0],'normalization_context',None)
 assert context is not None
 assert context.parser_locale=='en_US' and context.parser_currency=='EUR' and context.normalization_rules_version=='nv1'


def test_completed_parser_exception_keeps_actual_receipt_and_does_not_retry(tmp_path):
 raw,ledger=setup(tmp_path);calls=[]
 def extract(prompt):calls.append(prompt);return response('completed raw reply')
 def explode(*args):raise RuntimeError('parser exploded')
 def reader(data,doc):return read_with_retry(extract,'prompt',doc,'en-GB','EUR',parse_fn=explode,configured_model='configured')
 capture_and_ingest(raw,ledger,b'synthetic-original-source',reader)
 records=[e for e in ledger.events() if e.event_type=='ReadRecorded']
 assert len(calls)==1
 assert len(records)==1 and records[0].body['response_text']=='completed raw reply'
 assert records[0].body['cost_usd']==.123 and records[0].body['model']=='configured'
 assert records[0].body['parse_ok'] is False and 'parser exploded' in records[0].body['parse_error']
 assert records[0].body['resolved_model']=='resolved'
 assert (records[0].body['input_tokens'],records[0].body['output_tokens'],records[0].body['usage_reported'])==(19,7,True)
 assert records[0].body['prompt_version']=='' and records[0].body['input_mode']=='text+image'
 assert records[0].body['normalization_context']=={'schema_version':1,'normalization_rules_version':'nv1','parser_locale':'en-GB','parser_currency':'EUR'}


def test_real_two_phase_reader_attaches_context_only_to_extraction(monkeypatch):
 from types import SimpleNamespace
 from viva.ingest import reader
 calls=[]
 payload=mortgage();payload['payments'][0]['fees']=None
 class Adapter:
  def extract(self,pages,prompt):
   calls.append(prompt)
   return response(json.dumps({'doc_type':'mortgage_statement','doc_type_confidence':1.0}) if len(calls)==1 else json.dumps(payload))
 monkeypatch.setattr(reader,'_render_and_read_text',lambda data:([object()],'synthetic page text'))
 monkeypatch.setattr(reader,'adapter_for',lambda spec:Adapter())
 result=reader.read_statement(b'synthetic render fixture','doc',SimpleNamespace(model='configured',json_mode=True),'en_US','EUR')
 assert result.facts is not None,result.error
 assert len(calls)==len(result.phases)==2
 assert result.phases[0].phase=='classify' and result.phases[0].normalization_context is None
 assert result.phases[1].phase=='extract' and result.phases[1].normalization_context.parser_currency=='EUR'
 assert result.facts.doc_type_confidence==1.0
