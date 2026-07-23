"""The OpenAI-compatible adapter stitches a truncated (finish_reason=length)
response by asking the model to continue — without re-sending the images."""

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

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return _FakeResp(seq[len(calls) - 1])

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    r = oc.OpenAICompatAdapter(_spec()).extract(
        [PageImage(1, b"img", "sha")], "PROMPT")

    assert r.text == '{"a":1,"b":2}'          # parts stitched into valid JSON
    assert r.finish_reason == "stop"
    assert len(calls) == 2                     # continued once
    assert abs(r.cost_usd - 0.02) < 1e-9       # cost summed across turns

    # First turn carried the image; the continuation dropped it (text prompt +
    # the assistant partial + a continue instruction).
    assert isinstance(calls[0]["messages"][0]["content"], list)   # images + text
    assert "response_format" in calls[0]                           # json_mode, turn 1 only
    assert calls[1]["messages"][0]["content"] == "PROMPT"         # no images
    assert calls[1]["messages"][1]["role"] == "assistant"
    assert "response_format" not in calls[1]


def test_no_continuation_when_first_reply_is_complete(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return _FakeResp(_payload('{"done":true}', "stop"))

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    r = oc.OpenAICompatAdapter(_spec()).extract([PageImage(1, b"i", "s")], "P")
    assert r.text == '{"done":true}' and len(calls) == 1
