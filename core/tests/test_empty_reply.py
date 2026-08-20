"""A reply whose visible channel is empty ends the continuation loop, and the
reasoning channel it may have answered on instead is carried through."""

import vivacore.models.openai_compat as oc
from vivacore.models.base import MAX_CONTINUATIONS, Turn, run_to_completion
from vivacore.models.spec import ModelSpec


class _FakeResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def _payload(content, finish, message=None, usage=None):
    msg = {"content": content}
    msg.update(message or {})
    return {"model": "m",
            "choices": [{"message": msg, "finish_reason": finish}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 20}}


def _spec():
    return ModelSpec(name="t", adapter="openai-compatible", model="m",
                     base_url="https://openrouter.ai/api/v1", api_key_env=None,
                     json_mode=True)


def _stub(monkeypatch, payloads):
    """Serve `payloads` in order, repeating the last, and record every call."""
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None, *,
                  trust_env=True):
        # Pinned here rather than merely tolerated: with trust_env left on, an
        # ambient HTTPS_PROXY reroutes the call and a third party holds the API
        # key and every page image.
        assert trust_env is False, "an outbound call must not trust the environment"
        calls.append(json)
        return _FakeResp(payloads[min(len(calls) - 1, len(payloads) - 1)])

    monkeypatch.setattr(oc.httpx, "post", fake_post)
    return calls


def test_a_turn_that_adds_no_characters_buys_no_continuation(monkeypatch):
    calls = _stub(monkeypatch, [_payload("", "length")])
    r = oc.OpenAICompatAdapter(_spec()).extract([], "P")

    assert len(calls) == 1                # not one call per allowed continuation
    assert r.text == ""
    assert r.finish_reason == "length"    # the honest outcome, unchanged


def test_a_truncated_turn_that_added_text_still_continues_to_the_bound(monkeypatch):
    calls = _stub(monkeypatch, [_payload("part", "length")])
    r = oc.OpenAICompatAdapter(_spec()).extract([], "P")

    assert len(calls) == MAX_CONTINUATIONS + 1
    assert r.text == "part" * (MAX_CONTINUATIONS + 1)
    assert r.finish_reason == "length"


def test_the_driver_stops_on_an_empty_truncated_turn():
    attempts = []

    def call_once(accumulated, attempt):
        attempts.append(attempt)
        return Turn(text="", finish_reason="length")

    result = run_to_completion(call_once)
    assert attempts == [0] and result.text == ""


def test_a_reasoning_only_reply_is_distinguishable_from_a_short_one(monkeypatch):
    _stub(monkeypatch, [_payload(
        "", "length",
        message={"reasoning": "weighing the options"},
        usage={"prompt_tokens": 10, "completion_tokens": 8192,
               "completion_tokens_details": {"reasoning_tokens": 8192}})])
    silent = oc.OpenAICompatAdapter(_spec()).extract([], "P")

    assert silent.text == ""
    assert silent.reasoning_text == "weighing the options"
    assert silent.reasoning_tokens == 8192

    _stub(monkeypatch, [_payload("{}", "stop")])
    short = oc.OpenAICompatAdapter(_spec()).extract([], "P")

    assert short.text == "{}"
    assert short.reasoning_text == "" and short.reasoning_tokens == 0


def test_the_other_spelling_of_the_reasoning_channel_is_read(monkeypatch):
    _stub(monkeypatch, [_payload("", "length",
                                 message={"reasoning_content": "still thinking"})])
    r = oc.OpenAICompatAdapter(_spec()).extract([], "P")

    assert r.reasoning_text == "still thinking" and r.reasoning_tokens == 0
