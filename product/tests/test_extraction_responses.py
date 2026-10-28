"""Real adapter transports with synthetic HTTP; no provider calls or private vaults."""
import base64
import copy
import json
from decimal import Decimal
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from vivacore.models import ModelSpec,PageImage,OpenAICompatAdapter,AnthropicAdapter
from vivacore.models.base import extraction_transport_scope,observe_extractions
from viva.extraction_responses import RESPONSE_EVENT,response_body,summary,validate_links
from viva.ingest.reader import read_prepared_statement
from viva.ledger.events import Event,model_extraction_response_recorded,read_recorded


def spec(kind='openai-compatible'):
    return ModelSpec('synthetic',kind,'configured',base_url='https://example.invalid/v1',
                     api_key_env=None,max_continuations=1)


def wire(kind,text='{"doc_type":"unknown"}',truncated=False,usage=True):
    if kind=='anthropic':
        data={'content':[{'type':'text','text':text}],
              'stop_reason':'max_tokens' if truncated else 'end_turn'}
        if usage:data['usage']={'input_tokens':0,'output_tokens':2,'cost':'0.01230'}
    else:
        data={'choices':[{'message':{'content':text},'finish_reason':'length' if truncated else 'stop'}]}
        if usage:data['usage']={'prompt_tokens':0,'completion_tokens':2,'cost':'0.01230'}
    data['model']='resolved'
    return httpx.Response(200,content=json.dumps(data).encode())


def install(monkeypatch,kind,post):
    if kind=='anthropic':monkeypatch.setattr('vivacore.models.anthropic_adapter.httpx.post',lambda *a,**k:post(k['json']))
    else:monkeypatch.setattr(OpenAICompatAdapter,'_post',lambda self,body,headers:post(body))


def run(monkeypatch,kind,post,permit=lambda:True,sink=None,phases=None):
    install(monkeypatch,kind,post)
    retained=[] if sink is None else sink
    def receive(body):
        retained.append(copy.deepcopy(body));return 'receipt-'+str(len(retained))
    phases=[] if phases is None else phases
    result=read_prepared_statement((PageImage(1,b'public image','public-sha'),),
        'public text','public-document',spec(kind),'en-US','USD',
        phase_sink=lambda p,*_:phases.append(copy.deepcopy(p)),permit=permit,response_sink=receive)
    return result,retained,phases


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
def test_stop_prevents_continuation_after_durable_raw_ack(monkeypatch,kind):
    stopped=False;calls=[];retained=[]
    def post(body):
        nonlocal stopped
        calls.append(body);stopped=True;return wire(kind,'{"doc_type":',True)
    result,raw,phases=run(monkeypatch,kind,post,lambda:not stopped,retained)
    assert len(calls)==len(raw)==len(phases)==1
    assert result.facts is None and result.error
    assert phases[0].raw_text=='{"doc_type":' and not phases[0].parse_ok
    assert phases[0].transport_complete is False
    assert phases[0].transport_receipt_ids==['receipt-1']
    assert json.loads(base64.b64decode(raw[0]['response_bytes_base64']))['usage']['cost']=='0.01230'


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
def test_genuinely_admitted_second_transport_failure_keeps_prefix(monkeypatch,kind):
    calls=[];retained=[]
    def post(body):
        calls.append(body)
        if len(calls)==2:
            assert len(retained)==1
            raise OSError('synthetic second transport failed')
        return wire(kind,'{"doc_type":',True)
    result,raw,phases=run(monkeypatch,kind,post,sink=retained)
    assert len(calls)==2 and len(raw)==1 and len(phases)==1
    assert not phases[0].parse_ok and phases[0].raw_text=='{"doc_type":'
    assert result.phases==phases and result.facts is None


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
@pytest.mark.parametrize('status,raw',[(503,b'upstream unavailable'),(200,b'{malformed'),(200,b'[]')])
def test_raw_retained_before_status_json_shape_decoding(monkeypatch,kind,status,raw):
    retained=[]
    response=httpx.Response(status,content=raw)
    real_json=response.json
    def decode(*args,**kwargs):
        assert len(retained)==1
        return real_json(*args,**kwargs)
    response.json=decode
    result,records,phases=run(monkeypatch,kind,lambda _:response,sink=retained)
    assert len(records)==1 and not phases and result.facts is None
    assert base64.b64decode(records[0]['response_bytes_base64'])==raw
    assert records[0]['response_status']==status


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
def test_raw_ack_is_before_decoder_process_exit(monkeypatch,kind):
    captured=[];response=wire(kind)
    def decode():
        assert captured==[response.content]
        raise SystemExit('synthetic decoder exit')
    response.json=decode
    install(monkeypatch,kind,lambda _:response)
    adapter=AnthropicAdapter(spec(kind)) if kind=='anthropic' else OpenAICompatAdapter(spec(kind))
    with pytest.raises(SystemExit),extraction_transport_scope(lambda *a:None,
            lambda kind,model,ordinal,status,raw:captured.append(raw)):
        adapter.extract([PageImage(1,b'img','sha')],'synthetic prompt')
    assert captured==[response.content]


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
def test_ack_failure_never_decodes_or_continues_and_context_restores(monkeypatch,kind):
    calls=[];response=wire(kind,'prefix',True)
    response.json=lambda:pytest.fail('decode before durable acknowledgement')
    install(monkeypatch,kind,lambda body:(calls.append(body) or response))
    adapter=AnthropicAdapter(spec(kind)) if kind=='anthropic' else OpenAICompatAdapter(spec(kind))
    def fail(*args):raise OSError('synthetic append failure')
    with pytest.raises(OSError),extraction_transport_scope(lambda *a:None,fail):
        adapter.extract([PageImage(1,b'img','sha')],'synthetic prompt')
    assert len(calls)==1
    # A following unscoped call does not inherit either callback.
    install(monkeypatch,kind,lambda _:wire(kind))
    assert adapter.extract([PageImage(1,b'img','sha')],'synthetic prompt').text=='{"doc_type":"unknown"}'


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
def test_observer_keeps_its_original_turn_and_error_order(monkeypatch,kind):
    events=[];calls=[]
    def post(body):
        calls.append(body)
        if len(calls)==2:raise OSError('synthetic transport')
        return wire(kind,'prefix',True)
    install(monkeypatch,kind,post)
    adapter=AnthropicAdapter(spec(kind)) if kind=='anthropic' else OpenAICompatAdapter(spec(kind))
    with pytest.raises(OSError),observe_extractions(lambda turn,error,ordinal:events.append((turn,error,ordinal))),extraction_transport_scope(lambda *a:None,lambda *a:None):
        adapter.extract([PageImage(1,b'img','sha')],'synthetic prompt')
    assert len(events)==2 and events[0][0].text=='prefix' and events[0][1] is None
    assert events[1][0] is None and type(events[1][1]) is OSError
    assert [entry[2] for entry in events]==[0,1]


def make_response(raw,ordinal=0,**changes):
    body=response_body('public-document','operation','extract',0,ordinal,'openai_compatible',
                       'configured','prompt-v1','text+image',200,raw)
    body.update(changes)
    return model_extraction_response_recorded(body,'2026-01-01')


@pytest.mark.parametrize('usage,expected',[
    ({},(None,None,None)),
    ({'prompt_tokens':0,'completion_tokens':0,'cost':0},(0,0,'0')),
    ({'prompt_tokens':1,'completion_tokens':2,'cost':'0.0001200'},(1,2,'0.0001200')),
    ({'prompt_tokens':False,'completion_tokens':1,'cost':True},(None,1,None)),
    ({'prompt_tokens':1,'cost':'NaN'},(1,None,None)),
])
def test_summary_preserves_absence_zero_and_reported_decimal(usage,expected):
    event=make_response(json.dumps({'usage':usage}).encode())
    result=summary(event)
    assert tuple(result[name] for name in ('input_tokens','output_tokens','cost_usd'))==expected
    assert 'response_bytes_base64' not in result
    assert 'request' not in result


def test_response_links_reject_missing_foreign_reordered_duplicate():
    a=make_response(b'{}');b=make_response(b'{}',1)
    body=dict(doc_id='public-document',extraction_id='operation',phase='extract',phase_attempt=0,
              model='configured',prompt_version='prompt-v1',transport_complete=True,
              transport_receipt_ids=[a.event_id,b.event_id])
    validate_links(body,[a,b])
    for bad in ([b.event_id,a.event_id],[a.event_id],[a.event_id,a.event_id],['foreign']):
        with pytest.raises(ValueError):validate_links(dict(body,transport_receipt_ids=bad),[a,b])
    with pytest.raises(ValueError):validate_links(dict(body,doc_id='foreign'),[a,b])


def test_latest_failed_scoped_prefix_is_never_reparsed():
    from viva.rebuild import _parse_claim
    facts,error,context=_parse_claim('credit_card_statement',
        {'transport_complete':False,'response_text':'{"would":"otherwise parse"}'},
        'public-document','en-US','USD')
    assert facts is None and error=='incomplete extraction transport' and context is None


def test_legacy_read_constructor_bytes_omit_new_fields():
    body=read_recorded('public-document','configured','prompt-v1','text+image','{}',0,0,0,
                       False,None,'2026-01-01').body
    assert not {'transport_complete','transport_receipt_ids','extraction_id','phase_attempt'} & set(body)

from test_bulk_upload import setup_bulk


def test_real_bulk_http_receipts_are_durable_before_any_decode_and_financial_post(setup_bulk,monkeypatch):
    from viva.ingest import reader
    from viva.desktop_bridge.bulk_documents import BulkDocuments
    from viva.desktop_bridge.jobs import JobRegistry
    from test_reader_two_phase import _EXTRACT_JSON
    from threading import get_ident
    sample=setup_bulk;parent=get_ident();decoded=[];calls=[]
    monkeypatch.setattr(reader,'adapter_for',lambda _:OpenAICompatAdapter(spec()))
    def post(adapter,body,headers):
        assert get_ident()!=parent
        calls.append(body)
        if len(calls)==1:
            text='{"doc_type":"credit_card_statement","doc_type_confidence":0.97}'
        else:
            packet=json.loads(_EXTRACT_JSON)
            packet.update(account_ref='synthetic',account_number='synthetic',institution='synthetic',account_names=['synthetic'])
            text=json.dumps(packet)
        response=wire('openai-compatible',text)
        decode=response.json
        def checked():
            events=list(sample.vault.ledger.events())
            recorded=[event for event in events if event.event_type==RESPONSE_EVENT]
            assert len(recorded)==len(calls)
            assert base64.b64decode(recorded[-1].body['response_bytes_base64'])==response.content
            assert not sample.vault.ledger.projection().posted_doc_ids()
            decoded.append(len(calls))
            return decode()
        response.json=checked
        return response
    monkeypatch.setattr(OpenAICompatAdapter,'_post',post)
    coordinator=BulkDocuments(sample.vault,JobRegistry())
    outcome=coordinator.run({'paths':sample.paths[:1]})
    assert outcome['rows'][0]['action']=='posted',(outcome,repr(coordinator.fatal))
    assert decoded==[1,2]
    events=list(sample.vault.ledger.events())
    reads=[event for event in events if event.event_type=='ReadRecorded']
    assert len(reads)==2
    preceding=[]
    for event in events:
        if event.event_type=='ReadRecorded':validate_links(event.body,preceding)
        preceding.append(event)
    assert all(event.body['transport_complete'] for event in reads)


def test_orphan_capture_and_failed_prefix_replay_preserve_original_ids_and_bodies(tmp_path):
    from viva.vault import Vault
    from viva.ingest.pipeline import (_begin_bulk_read,_retain_bulk_response,_retain_bulk_phase,
        _capture_authenticated_replay,_retain_authenticated_replay)
    from viva.ingest.pipeline_models import ModelPhase
    source=Vault.open(tmp_path/'source','synthetic-only')
    target=Vault.open(tmp_path/'target','synthetic-only')
    try:
        # One orphan-only document, one document ending in an explicitly failed prefix.
        originals=[]
        for index in range(2):
            owner=_begin_bulk_read(source.raw,source.ledger,('synthetic'+str(index)).encode(),
                                   'synthetic.pdf','2026-01-01')
            body=response_body(owner.document,'operation-'+str(index),'extract',0,0,
                'openai_compatible','configured','prompt-v1','text+image',200,
                b'{"usage":{"cost":0.01230,"prompt_tokens":0,"completion_tokens":2}}')
            identity=_retain_bulk_response(owner,body)
            if index:
                _retain_bulk_phase(owner,ModelPhase('extract','configured','prompt-v1','prefix',
                    parse_ok=False,error='incomplete extraction transport',
                    transport_receipt_ids=[identity],transport_complete=False,
                    extraction_id='operation-'+str(index)),'unknown',0)
            owner.close()
        before=list(source.ledger.events())
        capture=_capture_authenticated_replay(source.ledger,source.raw)
        _retain_authenticated_replay(capture,target.raw,target.ledger)
        _retain_authenticated_replay(capture,target.raw,target.ledger)
        failed_docs={event.body['doc_id'] for event in before if event.event_type=='ReadRecorded'}
        wanted=[event.to_dict() for event in before if event.event_type in (RESPONSE_EVENT,'ReadRecorded')
                or event.event_type=='DocumentCaptured' and event.body['doc_id'] not in failed_docs]
        assert [event.to_dict() for event in target.ledger.events()]==wanted
        assert len(list(target.raw.doc_ids()))==2
        assert not target.ledger.projection().posted_doc_ids()
        from viva.vault_transfer import export_vault,restore_vault
        archive=tmp_path/'synthetic.orionvault'
        export_vault(source.directory,archive)
        restore_vault(archive,tmp_path/'restored','synthetic-only')
        restored=Vault.open(tmp_path/'restored','synthetic-only')
        try:
            assert [event.to_dict() for event in restored.ledger.events()]==[event.to_dict() for event in before]
            assert set(restored.raw.doc_ids())==set(source.raw.doc_ids())
        finally:restored.close()
        from viva.rebuild import rebuild
        rebuild(source.directory,tmp_path/'rebuilt','synthetic-only',locale='en-US',log=lambda *a:None)
        rebuilt=Vault.open(tmp_path/'rebuilt','synthetic-only')
        try:
            audit=[event.to_dict() for event in rebuilt.ledger.events() if event.event_type in (RESPONSE_EVENT,'ReadRecorded')]
            expected=[event.to_dict() for event in before if event.event_type in (RESPONSE_EVENT,'ReadRecorded')]
            assert audit==expected
            assert len(rebuilt.ledger.projection().captured_docs())==2
            assert not rebuilt.ledger.projection().posted_doc_ids()
        finally:rebuilt.close()
    finally:source.close();target.close()

@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
def test_successful_continuation_retains_every_response_and_aggregate_parity(monkeypatch,kind):
    calls=[];raw=[]
    def post(body):
        calls.append(body)
        assert len(raw)==len(calls)-1
        return wire(kind,'{"doc_type":' if len(calls)==1 else '"unknown"}',len(calls)==1)
    result,records,phases=run(monkeypatch,kind,post,sink=raw)
    assert len(calls)==len(records)==2 and len(phases)==1
    assert phases[0].raw_text=='{"doc_type":"unknown"}'
    assert phases[0].transport_complete is True
    assert phases[0].transport_receipt_ids==['receipt-1','receipt-2']
    assert [item['transport_attempt'] for item in records]==[0,1]
    assert phases[0].input_tokens==0 and phases[0].output_tokens==4
    assert phases[0].usage_reported


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
def test_parser_retry_has_fresh_admission_and_exact_phase_attempt_prompt(monkeypatch,kind):
    from test_reader_two_phase import _EXTRACT_JSON
    calls=[];permits=[]
    def post(body):
        calls.append(body)
        assert len(permits)==len(calls)
        text=('{"doc_type":"credit_card_statement","doc_type_confidence":0.97}'
              if len(calls)==1 else 'invalid JSON' if len(calls)==2 else _EXTRACT_JSON)
        return wire(kind,text)
    def permit():permits.append(True);return True
    result,raw,phases=run(monkeypatch,kind,post,permit)
    assert len(calls)==len(permits)==len(raw)==3
    assert [(row['phase'],row['phase_attempt'],row['transport_attempt']) for row in raw]==[
        ('classify',0,0),('extract',0,0),('extract',1,0)]
    assert 'retry-syntax-v1' not in raw[1]['prompt_version']
    assert 'retry-syntax-v1' in raw[2]['prompt_version']
    assert [phase.prompt_version for phase in phases]==[row['prompt_version'] for row in raw]
    assert result.facts is not None


def test_durable_append_failure_stops_without_decode_or_retry(setup_bulk,monkeypatch):
    from viva.ingest import reader
    from viva.desktop_bridge.bulk_documents import BulkDocuments
    from viva.desktop_bridge.jobs import JobRegistry
    sample=setup_bulk;calls=[];real_append=sample.vault.ledger.append
    monkeypatch.setattr(reader,'adapter_for',lambda _:OpenAICompatAdapter(spec()))
    def append(event):
        if event.event_type==RESPONSE_EVENT:raise OSError('synthetic persistence failure')
        return real_append(event)
    monkeypatch.setattr(sample.vault.ledger,'append',append)
    def post(*args):
        calls.append(1);response=wire('openai-compatible','prefix',True)
        response.json=lambda:pytest.fail('decoded response without durable ack')
        return response
    monkeypatch.setattr(OpenAICompatAdapter,'_post',post)
    coordinator=BulkDocuments(sample.vault,JobRegistry())
    outcome=coordinator.run({'paths':sample.paths[:1]})
    assert calls==[1] and coordinator.fatal is not None
    assert outcome['rows'][0]['reason']=='outcome_unknown'
    assert not [event for event in sample.vault.ledger.events() if event.event_type==RESPONSE_EVENT]
    assert not sample.vault.ledger.projection().posted_doc_ids()


def test_source_replay_rejects_foreign_missing_or_reordered_links_before_destination_write(tmp_path):
    from viva.vault import Vault
    from viva.ingest.pipeline import _capture_authenticated_replay
    from viva.ledger.events import document_captured
    source=Vault.open(tmp_path/'source','synthetic-only')
    try:
        data=b'synthetic original';doc=source.raw.put(data)
        source.ledger.append(document_captured(doc,'synthetic.pdf',len(data),'unknown',0,'2026-01-01'))
        event=make_response(b'{}');event.body['doc_id']=doc;event.provenance=replace(event.provenance,doc_id=doc)
        source.ledger.append(event)
        receipt=read_recorded(doc,'configured','prompt-v1','text+image','prefix',0,0,0,False,None,
            '2026-01-01',transport_receipt_ids=['foreign'],transport_complete=False,
            extraction_id='operation',phase_attempt=0)
        source.ledger.append(receipt)
        with pytest.raises(ValueError,match='missing or foreign'):
            _capture_authenticated_replay(source.ledger,source.raw)
    finally:source.close()


def test_failed_transport_marker_is_not_a_financial_phase_capability(tmp_path):
    from viva.vault import Vault
    from viva.ingest.pipeline import _begin_bulk_read,_retain_bulk_phase
    from viva.ingest.pipeline_models import ModelPhase
    vault=Vault.open(tmp_path/'synthetic','synthetic-only')
    owner=_begin_bulk_read(vault.raw,vault.ledger,b'synthetic','synthetic.pdf','2026-01-01')
    try:
        phase=ModelPhase('extract','configured','prompt-v1','prefix',parse_ok=True,
            transport_complete=False,transport_receipt_ids=[],extraction_id='operation')
        with pytest.raises(ValueError,match='incomplete transport'):
            _retain_bulk_phase(owner,phase,'unknown',0)
        assert not list(vault.ledger.events())
    finally:owner.close();vault.close()


def test_numeric_json_cost_digits_survive_without_float_roundtrip():
    raw=b'{"usage":{"cost":0.000000000000012300,"prompt_tokens":0,"completion_tokens":0}}'
    event=make_response(raw)
    assert base64.b64decode(event.body['response_bytes_base64'])==raw
    assert summary(event)['cost_usd']=='1.2300E-14'


_SCOPED_MARKERS=('transport_receipt_ids','transport_complete','extraction_id','phase_attempt')


@pytest.mark.parametrize('present',range(1,15))
def test_every_partial_scoped_marker_population_is_refused(present):
    body=dict(doc_id='public-document',model='configured',phase='extract')
    scoped=dict(transport_receipt_ids=[],transport_complete=True,
                extraction_id='operation',phase_attempt=0)
    body.update({name:scoped[name] for index,name in enumerate(_SCOPED_MARKERS)
                 if present & (1 << index)})
    with pytest.raises(ValueError,match='incomplete scoped'):
        validate_links(body,[])


@pytest.mark.parametrize('name,value',[
    ('transport_receipt_ids',[{}]),('transport_receipt_ids',[[]]),
    ('transport_receipt_ids','receipt'),('transport_receipt_ids',[True]),
    ('transport_complete',1),('transport_complete',None),
    ('extraction_id',True),('extraction_id',{}),('extraction_id',''),
    ('phase_attempt',True),('phase_attempt',-1),('phase_attempt','0'),
])
def test_full_scoped_marker_population_has_closed_types(name,value):
    body=dict(transport_receipt_ids=[],transport_complete=True,
              extraction_id='operation',phase_attempt=0)
    body[name]=value
    with pytest.raises(ValueError,match='invalid extraction response links'):
        validate_links(body,[])


@pytest.mark.parametrize('marker',[
    {'transport_complete':True},{'transport_complete':False},
    {'extraction_id':'operation'},{'phase_attempt':1},
    {'phase_attempt':False},{'phase_attempt':0.0},
])
def test_constructor_refuses_scoped_arguments_without_links(marker):
    with pytest.raises(ValueError,match='incomplete scoped'):
        read_recorded('public-document','configured','prompt-v1','text+image',
                      '{}',0,0,0,False,None,'2026-01-01',**marker)


def test_fully_legacy_aggregate_retains_ordinary_validation_and_bytes():
    legacy=read_recorded('public-document','configured','prompt-v1','text+image',
                         '{}',0,0,0,False,None,'2026-01-01')
    before=copy.deepcopy(legacy.to_dict())
    validate_links(legacy.body,[])
    assert legacy.to_dict()==before
    assert not set(_SCOPED_MARKERS).intersection(legacy.body)

@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
@pytest.mark.parametrize('invalid',[True,-1,7.5,'7'])
def test_scoped_usage_requires_reported_integer_counters_not_adapter_coercions(monkeypatch,kind,invalid):
    keys=('input_tokens','output_tokens') if kind=='anthropic' else ('prompt_tokens','completion_tokens')
    response=wire(kind)
    packet=json.loads(response.content);packet['usage']={keys[0]:invalid,keys[1]:0}
    result,raw,phases=run(monkeypatch,kind,lambda _:httpx.Response(200,json=packet))
    assert len(raw)==len(phases)==1 and result.facts is None
    phase=phases[0]
    assert phase.transport_complete is True and phase.usage_reported is False
    assert phase.input_tokens==phase.output_tokens==0
    assert summary(model_extraction_response_recorded(raw[0],'2026-01-01'))['input_tokens'] is None


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
@pytest.mark.parametrize('partial_position',[0,1])
@pytest.mark.parametrize('reported',['input','output'])
def test_scoped_continuation_any_partial_turn_omits_aggregate_usage_and_keeps_raw_counter(monkeypatch,kind,partial_position,reported):
    calls=[];keys=('input_tokens','output_tokens') if kind=='anthropic' else ('prompt_tokens','completion_tokens')
    def post(body):
        index=len(calls);calls.append(body)
        packet=json.loads(wire(kind,'{"doc_type":' if index==0 else '"unknown"}',index==0).content)
        packet['usage']=({keys[0 if reported=='input' else 1]:7} if index==partial_position
                         else {keys[0]:0,keys[1]:0})
        return httpx.Response(200,json=packet)
    result,raw,phases=run(monkeypatch,kind,post)
    assert len(calls)==len(raw)==2 and len(phases)==1
    phase=phases[0]
    assert phase.transport_complete is True and phase.usage_reported is False
    aggregate=read_recorded('public-document',phase.model,phase.prompt_version,phase.input_mode,
        phase.raw_text,phase.cost_usd,phase.input_tokens,phase.output_tokens,phase.parse_ok,phase.error,
        '2026-01-01',usage_reported=phase.usage_reported)
    assert 'input_tokens' not in aggregate.body and 'output_tokens' not in aggregate.body
    metadata=summary(model_extraction_response_recorded(raw[partial_position],'2026-01-01'))
    assert metadata[reported+'_tokens']==7
    assert metadata[('output' if reported=='input' else 'input')+'_tokens'] is None


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
def test_scoped_extract_phase_does_not_copy_classification_or_normalized_usage(monkeypatch,kind):
    from test_reader_two_phase import _EXTRACT_JSON
    calls=[];keys=('input_tokens','output_tokens') if kind=='anthropic' else ('prompt_tokens','completion_tokens')
    def post(body):
        calls.append(body)
        text=('{"doc_type":"credit_card_statement","doc_type_confidence":0.97}'
              if len(calls)==1 else _EXTRACT_JSON)
        packet=json.loads(wire(kind,text).content)
        packet['usage']=({keys[0]:0,keys[1]:0} if len(calls)==1 else {keys[1]:7})
        return httpx.Response(200,json=packet)
    result,raw,phases=run(monkeypatch,kind,post)
    assert result.facts is not None and len(phases)==len(raw)==2
    assert phases[0].usage_reported is True
    assert phases[0].input_tokens==phases[0].output_tokens==0
    assert phases[1].phase=='extract' and phases[1].transport_complete is True
    assert phases[1].usage_reported is False
    assert phases[1].input_tokens==phases[1].output_tokens==0
