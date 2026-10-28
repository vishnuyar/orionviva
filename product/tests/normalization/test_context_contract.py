import json
from decimal import Decimal
import pytest
from viva.normalization_context import ExtractionNormalizationContext as Context, encode_context, decode_context
from viva.ingest import reader
from viva.ledger.events import read_recorded
from test_reader_context import response


def test_context_roundtrip_preserves_actual_input_spellings_and_nulls():
    for locale,currency in [('en_US','usd'),('', ''),(None,None),('é'*32,'€'*5)]:
        context=Context(1,'nv1',locale,currency)
        assert decode_context(encode_context(context))==context
        assert encode_context(context)['parser_locale']==locale
        assert encode_context(context)['parser_currency']==currency


@pytest.mark.parametrize('delta',[
    {'schema_version':True},{'schema_version':2},{'normalization_rules_version':'nv2'},
    {'parser_locale':False},{'parser_locale':{}},{'parser_locale':'é'*33},
    {'parser_currency':1},{'parser_currency':'€'*6},{'provider_context':{}},
])
def test_context_is_closed_exact_typed_and_utf8_bounded(delta):
    body=encode_context(Context(1,'nv1','en-US','USD'));body.update(delta)
    with pytest.raises(ValueError):decode_context(body)


@pytest.mark.parametrize('locale,currency',[(False,'USD'),('en-US',{}),('x'*65,'USD'),('en-US','x'*17)])
def test_bad_backend_context_cannot_render_classify_or_request(monkeypatch,locale,currency):
    calls=[]
    monkeypatch.setattr(reader,'_render_and_read_text',lambda *a:calls.append('render'))
    monkeypatch.setattr(reader,'adapter_for',lambda *a:calls.append('adapter'))
    with pytest.raises(ValueError):reader.read_statement(b'pdf','doc',None,locale,currency)
    with pytest.raises(ValueError):reader.read_with_retry(lambda *a:calls.append('extract'),'p','doc',locale,currency)
    assert calls==[]


def test_constructor_absent_context_preserves_exact_legacy_body_and_usage_presence():
    for cost in [Decimal('0.0100'),Decimal('-0'),0.0]:
        for measured in [None,False,True]:
            event=read_recorded('doc','configured','prompt','text+image','raw',cost,0,0,
                                parse_ok=False,parse_error='returned error',occurred_at='2025-01-01',usage_reported=measured)
            expected={'doc_id':'doc','phase':'extract','model':'configured','prompt_version':'prompt',
                      'response_text':'raw','cost_usd':cost,'model_role':'configured_route',
                      'input_mode':'text+image','parse_ok':False,'parse_error':'returned error'}
            if measured is True:expected.update(usage_reported=True,input_tokens=0,output_tokens=0)
            assert event.body==expected
            assert 'normalization_context' not in event.body
    with pytest.raises(ValueError):
        read_recorded('doc','m','p','text+image','raw',0,0,0,False,None,'2025-01-01',phase='classify',
                      normalization_context=Context(1,'nv1','en-US','USD'))


def test_returned_error_retry_retains_both_real_attempts_and_context(monkeypatch):
    calls=[];parses=[]
    monkeypatch.setattr(reader.prompt_library,'fragment',lambda key:'retry {err}')
    def extract(prompt):calls.append(prompt);return response('raw-'+str(len(calls)),Decimal('0.0100'))
    def parse(text,doc,locale,currency):
        parses.append((text,doc,locale,currency))
        if len(parses)==1:return None,'invalid field'
        from types import SimpleNamespace
        return SimpleNamespace(doc_type='unknown',doc_type_confidence=0),None
    result=reader.read_with_retry(extract,'p','doc','en_US','eur',parse_fn=parse)
    assert len(calls)==len(parses)==len(result.phases)==2
    assert [p.parse_ok for p in result.phases]==[False,True]
    assert [p.raw_text for p in result.phases]==['raw-1','raw-2']
    assert [p.cost_usd for p in result.phases]==[Decimal('0.0100')]*2
    assert result.cost_usd==Decimal('0.0200')
    assert all(p.normalization_context==Context(1,'nv1','en_US','eur') for p in result.phases)


def test_parser_raise_after_failed_attempt_terminates_without_third_call(monkeypatch):
    calls=[]
    monkeypatch.setattr(reader.prompt_library,'fragment',lambda key:'retry {err}')
    def extract(prompt):calls.append(prompt);return response('raw-'+str(len(calls)))
    def parse(*args):
        if len(calls)==1:return None,'invalid field'
        raise RuntimeError('completed second response')
    result=reader.read_with_retry(extract,'p','doc','en-US','USD',max_retries=5,parse_fn=parse)
    assert len(calls)==len(result.phases)==2
    assert [p.parse_ok for p in result.phases]==[False,False]
    assert 'completed second response' in result.phases[-1].error


def test_provider_json_cannot_supply_or_override_backend_context():
    calls=[]
    def parse(text,doc,locale,currency):
        calls.append((locale,currency))
        return None,'provider payload is not a supported financial shape'
    result=reader.read_with_retry(lambda prompt:response(json.dumps({'normalization_context':{
        'parser_locale':'de-DE','parser_currency':'EUR'}})),'p','doc','en_US','USD',
        parse_fn=parse,max_retries=0)
    assert calls==[('en_US','USD')]
    assert result.phases[0].normalization_context==Context(1,'nv1','en_US','USD')


def test_reparse_consumes_recorded_inputs_once_and_never_host_defaults(monkeypatch):
    from viva import rebuild
    calls=[]
    monkeypatch.setattr(rebuild,'_parse',lambda *args:(calls.append(args) or ('facts',None)))
    body={'response_text':'unchanged raw','normalization_context':encode_context(Context(1,'nv1','en_US','eur'))}
    facts,error,context=rebuild._parse_claim('mortgage_statement',body,'source','HOST','JPY')
    assert (facts,error)==('facts',None)
    assert calls==[('mortgage_statement','unchanged raw','source','en_US','eur')]
    assert context==Context(1,'nv1','en_US','eur')


def test_real_instrument_parser_printed_currency_conflict_is_not_retried_or_reinterpreted():
    from test_instrument_projector_b import mortgage
    from viva.ingest.instrument_read import parser_for
    payload=mortgage();payload['payments'][0]['total']['raw']='$600'
    calls=[]
    result=reader.read_with_retry(lambda prompt:(calls.append(prompt) or response(json.dumps(payload))),
        'p','doc','en-US','EUR',parse_fn=parser_for('mortgage_statement'),max_retries=0)
    assert result.facts is None and 'amount' in result.error
    assert len(calls)==1 and result.phases[0].normalization_context.parser_currency=='EUR'


def test_real_instrument_currency_comes_from_parser_input_not_a_target_inference():
    from test_instrument_projector_b import mortgage
    from viva.ingest.instrument_parser import parse_instrument_json
    from viva.ledger.instruments import encode
    text=json.dumps(mortgage())
    usd=parse_instrument_json(text,'mortgage_statement','doc','en-US','USD')
    eur=parse_instrument_json(text,'mortgage_statement','doc','en-US','EUR')
    assert usd.payments[0].total.currency=='USD' and eur.payments[0].total.currency=='EUR'
    assert encode(usd)!=encode(eur)


def test_actual_locale_changes_ambiguous_printed_amount_full_facts():
    from test_instrument_projector_b import mortgage
    from viva.ingest.instrument_parser import parse_instrument_json
    from viva.ledger.instruments import encode
    payload=mortgage();payload['opening_principal']['raw']='1,000'
    text=json.dumps(payload)
    english=parse_instrument_json(text,'mortgage_statement','doc','en-US','USD')
    german=parse_instrument_json(text,'mortgage_statement','doc','de-DE','USD')
    assert english.opening_principal.value==Decimal('1000')
    assert german.opening_principal.value==Decimal('1.000')
    assert encode(english)!=encode(german)


def test_absent_context_constructor_actual_frozen_preimage_bytes_and_errors():
    import ast
    from pathlib import Path
    from viva.ledger.events import Event,Provenance
    baseline=Path(__file__).parents[1]/'normalization_inputs/baseline-events.py'
    tree=ast.parse(baseline.read_text())
    node=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='read_recorded')
    namespace={'Event':Event,'Provenance':Provenance}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(baseline),'exec'),namespace)
    legacy=namespace['read_recorded']
    for cost in ['0.0100',0.0100,-0.0,Decimal('0.0100'),Decimal('-0')]:
        for usage in [None,False,True]:
            args=('doc','configured','prompt','text+image','raw',cost,0,0,False,'error','2025-01-01')
            old=legacy(*args,usage_reported=usage);new=read_recorded(*args,usage_reported=usage)
            old.event_id=new.event_id='fixed-golden-identity'
            assert old.to_dict()==new.to_dict()
            assert type(old.body['cost_usd']) is type(new.body['cost_usd'])
            if isinstance(cost,Decimal):
                assert old.body['cost_usd'].as_tuple()==new.body['cost_usd'].as_tuple()==cost.as_tuple()
                with pytest.raises(TypeError):json.dumps(old.to_dict())
                with pytest.raises(TypeError):json.dumps(new.to_dict())
            else:
                assert json.dumps(old.to_dict(),sort_keys=True,separators=(',',':'))==json.dumps(new.to_dict(),sort_keys=True,separators=(',',':'))
