"""Opt-in raw-response callbacks leave ordinary adapter requests unchanged."""
import httpx
import pytest
from vivacore.models import OpenAICompatAdapter,AnthropicAdapter,ModelSpec,PageImage
from vivacore.models.base import extraction_transport_scope


@pytest.mark.parametrize('kind',['openai-compatible','anthropic'])
def test_opt_in_callbacks_preserve_actual_request_body_and_unwind(monkeypatch,kind):
    calls=[];seen=[]
    data=({'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}],
           'usage':{'prompt_tokens':1,'completion_tokens':2}} if kind=='openai-compatible'
          else {'content':[{'type':'text','text':'{}'}],'stop_reason':'end_turn',
                'usage':{'input_tokens':1,'output_tokens':2}})
    def post(body):calls.append(body);return httpx.Response(200,json=data)
    if kind=='openai-compatible':
        monkeypatch.setattr(OpenAICompatAdapter,'_post',lambda self,body,headers:post(body))
        adapter=OpenAICompatAdapter(ModelSpec('synthetic',kind,'configured','https://example.invalid',api_key_env=None))
    else:
        monkeypatch.setattr('vivacore.models.anthropic_adapter.httpx.post',lambda *a,**k:post(k['json']))
        adapter=AnthropicAdapter(ModelSpec('synthetic',kind,'configured',api_key_env=None))
    pages=[PageImage(1,b'synthetic image','synthetic-sha')]
    ordinary=adapter.extract(pages,'synthetic prompt')
    with extraction_transport_scope(lambda *a:seen.append(('admit',a)),
                                     lambda *a:seen.append(('response',a))) as scope:
        scoped=adapter.extract(pages,'synthetic prompt')
    adapter.extract(pages,'synthetic prompt')
    assert calls[0]==calls[1]==calls[2]
    assert ordinary.text==scoped.text and ordinary.request==scoped.request
    assert ordinary.cost_usd==scoped.cost_usd
    assert [entry[0] for entry in seen]==['admit','response'] and len(scope.turns)==1


def test_converse_does_not_invoke_extraction_scope(monkeypatch):
    calls=[]
    def post(self,body,headers):
        calls.append(body)
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'synthetic'},
                                                   'finish_reason':'stop'}]})
    monkeypatch.setattr(OpenAICompatAdapter,'_post',post)
    adapter=OpenAICompatAdapter(ModelSpec('synthetic','openai-compatible','configured',
                                         'https://example.invalid',api_key_env=None))
    def forbidden(*args):pytest.fail('converse entered extraction scope')
    before=adapter.converse([{'role':'user','content':'synthetic'}],[])
    with extraction_transport_scope(forbidden,forbidden):
        after=adapter.converse([{'role':'user','content':'synthetic'}],[])
    assert calls[0]==calls[1] and before.text==after.text


def test_admission_denial_occurs_before_network_and_outside_http_failure_label(monkeypatch):
    calls=[]
    monkeypatch.setattr(OpenAICompatAdapter,'_post',lambda *a:calls.append(a))
    adapter=OpenAICompatAdapter(ModelSpec('synthetic','openai-compatible','configured',
                                         'https://example.invalid',api_key_env=None))
    error=RuntimeError('synthetic stop')
    def deny(*args):raise error
    with pytest.raises(RuntimeError) as caught,extraction_transport_scope(deny,lambda *a:None):
        adapter.extract([PageImage(1,b'img','sha')],'synthetic prompt')
    assert caught.value is error and not calls
