"""The Anthropic adapter continues a reply truncated at stop_reason 'max_tokens'
via an assistant prefill, and stitches the parts into one result."""

import vivacore.models.anthropic_adapter as an
from vivacore.models.base import PageImage
from vivacore.models.spec import ModelSpec


class _FakeResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def _payload(text, stop_reason):
    return {"model": "claude-x", "stop_reason": stop_reason,
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 10, "output_tokens": 20}}


def _spec():
    return ModelSpec(name="t", adapter="anthropic", model="claude-x",
                     api_key_env=None, cost_per_mtok_in=1.0, cost_per_mtok_out=1.0)


def test_continuation_stitches_via_assistant_prefill(monkeypatch):
    seq = [_payload('{"a":1,', "max_tokens"), _payload('"b":2}', "end_turn")]
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return _FakeResp(seq[len(calls) - 1])

    monkeypatch.setattr(an.httpx, "post", fake_post)
    r = an.AnthropicAdapter(_spec()).extract([PageImage(1, b"img", "sha")], "PROMPT")

    assert r.text == '{"a":1,"b":2}'          # parts stitched into valid JSON
    assert r.finish_reason == "end_turn"      # normalized stop from the last turn
    assert len(calls) == 2                     # continued once
    assert abs(r.cost_usd - 0.00006) < 1e-9    # (10+20)/1e6 summed across 2 turns

    # The first turn carries the image; the continuation drops it and hands the
    # partial back as an assistant prefill.
    assert any(b.get("type") == "image"
               for b in calls[0]["messages"][0]["content"])
    assert calls[1]["messages"][0]["content"] == [{"type": "text", "text": "PROMPT"}]
    assert calls[1]["messages"][1] == {"role": "assistant", "content": '{"a":1,'}


def test_no_continuation_when_first_reply_ends_the_turn(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return _FakeResp(_payload('{"done":true}', "end_turn"))

    monkeypatch.setattr(an.httpx, "post", fake_post)
    r = an.AnthropicAdapter(_spec()).extract([PageImage(1, b"i", "s")], "P")
    assert r.text == '{"done":true}' and len(calls) == 1
