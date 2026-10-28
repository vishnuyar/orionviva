"""The OpenAI-compatible adapter stitches a truncated (finish_reason=length)
reply by asking the model to continue, without re-sending the images."""

import vivacore.models.openai_compat as oc
from vivacore.models.base import PageImage
from vivacore.models.spec import ModelSpec


class _FakeResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def _payload(content, finish, cost=0.01):
    return {"model": "m",
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "cost": cost}}


def _spec():
    return ModelSpec(name="t", adapter="openai-compatible", model="m",
                     base_url="https://openrouter.ai/api/v1", api_key_env=None,
                     json_mode=True)


def test_continuation_stitches_and_drops_images(monkeypatch):
    seq = [_payload('{"a":1,', "length"), _payload('"b":2}', "stop")]
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, *,
                  trust_env=True):
        # Pinned here rather than merely tolerated: with trust_env left on, an
        # ambient HTTPS_PROXY reroutes the call and a third party holds the API
        # key and every page image.
        assert trust_env is False, "an outbound call must not trust the environment"
        calls.append(json)
        return _FakeResp(seq[len(calls) - 1])

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    r = oc.OpenAICompatAdapter(_spec()).extract(
        [PageImage(1, b"img", "sha")], "PROMPT")

    assert r.text == '{"a":1,"b":2}'          # parts stitched into valid JSON
    assert r.finish_reason == "stop"
    assert len(calls) == 2                     # continued once
    assert abs(r.cost_usd - 0.02) < 1e-9       # cost summed across turns

    # The first turn carries the image; the continuation drops it (text prompt +
    # the assistant partial + a continue instruction).
    assert isinstance(calls[0]["messages"][-1]["content"], list)  # images + text
    assert "response_format" in calls[0]                           # json_mode, turn 1 only
    assert calls[1]["messages"][0]["content"] == "PROMPT"         # no images
    assert calls[1]["messages"][1]["role"] == "assistant"
    assert "response_format" not in calls[1]


def test_no_continuation_when_first_reply_is_complete(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, *,
                  trust_env=True):
        # Pinned here rather than merely tolerated: with trust_env left on, an
        # ambient HTTPS_PROXY reroutes the call and a third party holds the API
        # key and every page image.
        assert trust_env is False, "an outbound call must not trust the environment"
        calls.append(json)
        return _FakeResp(_payload('{"done":true}', "stop"))

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    r = oc.OpenAICompatAdapter(_spec()).extract([PageImage(1, b"i", "s")], "P")
    assert r.text == '{"done":true}' and len(calls) == 1


def test_json_mode_http_contract_adds_instruction_only_to_first_extract_turn(monkeypatch):
    """A JSON response format needs an explicit JSON request even for a plain prompt."""
    import copy
    from dataclasses import replace
    from vivacore.models.base import CONTINUE_INSTRUCTION
    calls=[]
    def fake_post(url,json=None,**kwargs):
        calls.append(copy.deepcopy(json))
        if json.get('response_format')=={'type':'json_object'}:
            assert json['messages'][0]=={'role':'system','content':'Return a valid JSON object.'}
            return _FakeResp(_payload('{"classification":', 'length'))
        return _FakeResp(_payload('"pay_stub"}', 'stop'))
    monkeypatch.setattr(oc.httpx,'post',fake_post)
    prompt='Classify the page. Return the document type.'
    result=oc.OpenAICompatAdapter(_spec()).extract([PageImage(1,b'img','sha')],prompt)
    assert result.text=='{"classification":"pay_stub"}'
    assert calls[0]['messages'][1]['content'][-1]=={'type':'text','text':prompt}
    assert calls[1]['messages']==[{'role':'user','content':prompt},
        {'role':'assistant','content':'{"classification":'},
        {'role':'user','content':CONTINUE_INSTRUCTION}]
    assert 'response_format' not in calls[1]
    calls.clear()
    oc.OpenAICompatAdapter(replace(_spec(),json_mode=False)).extract([],prompt)
    assert calls[0]['messages']==[{'role':'user','content':[{'type':'text','text':prompt}]}]
    assert 'response_format' not in calls[0]
    calls.clear()
    messages=[{'role':'user','content':'Use the supplied structured tool.'}]
    oc.OpenAICompatAdapter(_spec()).converse(messages,[])
    assert calls[0]['messages']==messages and 'response_format' not in calls[0]
