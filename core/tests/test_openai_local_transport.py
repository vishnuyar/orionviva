"""Synthetic local HTTP exchanges preserve the ordinary adapter contract."""

import hashlib
import json
from pathlib import Path
import shutil
import socketserver
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler

import httpx
import pytest

from vivacore.errors import ConfigError
from vivacore.models.base import AdapterError, PageImage
from vivacore.models.openai_compat import OpenAICompatAdapter
from vivacore.models.spec import ModelSpec


def spec(**kwargs):
    kwargs.setdefault("max_continuations", 0)
    return ModelSpec(name="synthetic", adapter="openai-compatible", model="fixture-v1",
                     base_url="http://openrouter.ai/api/v1", **kwargs)


@contextmanager
def scratch():
    directory = Path(tempfile.mkdtemp(prefix="ux-", dir=Path(tempfile.gettempdir()).resolve()))
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def payload():
    return {"model": "resolved-v1", "choices": [{"message": {"content": "{}"},
            "finish_reason": "stop"}], "usage": {"prompt_tokens": 3,
            "completion_tokens": 5, "cost": 0.012}}


@contextmanager
def gateway(status=200, response=None, headers=None):
    calls = []
    raw_reply = json.dumps(payload()).encode() if response is None else response

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append((self.path, dict(self.headers),
                          self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(status)
            reply = raw_reply[len(calls) - 1] if isinstance(raw_reply, list) else raw_reply
            self.send_header("Content-Length", str(len(reply)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(reply)

    with scratch() as directory:
        path = directory / "s"
        with socketserver.UnixStreamServer(str(path), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield str(path), calls, raw_reply
            finally:
                server.shutdown()
                thread.join(timeout=2)
                assert not thread.is_alive()


def invoke(adapter, method):
    if method == "extract":
        return adapter.extract([PageImage(1, b"image", "synthetic-sha")], "FIXTURE")
    return adapter.converse([{"role": "user", "content": "FIXTURE"}],
                            [{"name": "fixture", "description": "fixture",
                              "parameters": {"type": "object"}}])


def expected_body(method):
    body = {"model": "fixture-v1", "max_tokens": 8192, "temperature": 0.2,
            "messages": [{"role": "user", "content": "FIXTURE"}]}
    if method == "extract":
        body["messages"][0]["content"] = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,aW1hZ2U="}},
            {"type": "text", "text": "FIXTURE"}]
    else:
        body["tools"] = [{"type": "function", "function": {"name": "fixture",
                         "description": "fixture", "parameters": {"type": "object"}}}]
        body["tool_choice"] = "required"
        body["parallel_tool_calls"] = False
    body["usage"] = {"include": True}
    return body


@pytest.mark.parametrize("method", ["extract", "converse"])
def test_unix_uses_fresh_ordinary_transport_preserving_exact_bytes(monkeypatch, method):
    transports, clients = [], []
    real_transport, real_client = httpx.HTTPTransport, httpx.Client

    def transport(**kwargs):
        transports.append(kwargs)
        return real_transport(**kwargs)

    def client(**kwargs):
        clients.append(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "HTTPTransport", transport)
    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("TCP fallback"))
    monkeypatch.setenv("HTTP_PROXY", "http://unreachable.invalid:1")
    monkeypatch.setenv("ALL_PROXY", "http://unreachable.invalid:1")
    with gateway() as (path, calls, reply):
        adapter = OpenAICompatAdapter(spec(unix_socket_path=path))
        first = invoke(adapter, method)
        second = invoke(adapter, method)
        assert len(calls) == len(transports) == len(clients) == 2
        assert transports == [{"uds": path, "retries": 0, "trust_env": False}] * 2
        assert clients[0]["transport"] is not clients[1]["transport"]
        assert all(c["timeout"] == 300 and c["trust_env"] is False
                   and c["follow_redirects"] is False for c in clients)
        expected = json.dumps(expected_body(method), ensure_ascii=False,
                              separators=(",", ":"), allow_nan=False).encode()
        assert [call[0] for call in calls] == ["/api/v1/chat/completions"] * 2
        assert [call[2] for call in calls] == [expected, expected]
        assert calls[0][1]["HTTP-Referer"] == "https://orionviva.com"
        assert calls[0][1]["X-Title"] == ("viva-bench" if method == "extract" else "viva-speak")
        assert first.response == second.response == json.loads(reply)
        assert first.resolved_model == "resolved-v1"
        assert first.input_tokens == 3 and first.output_tokens == 5
        assert first.cost_usd == 0.012


@pytest.mark.parametrize("method", ["extract", "converse"])
def test_default_tcp_retains_top_level_post_contract(monkeypatch, method):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json=payload())

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "HTTPTransport", lambda **k: pytest.fail("unexpected UDS transport"))
    result = invoke(OpenAICompatAdapter(spec()), method)
    assert calls[0][0] == "http://openrouter.ai/api/v1/chat/completions"
    assert calls[0][1]["json"] == expected_body(method)
    assert calls[0][1]["trust_env"] is False
    assert calls[0][1]["timeout"] == 300
    assert result.cost_usd == 0.012


@pytest.mark.parametrize("path", ["", "relative/s", "/", "//s", "/x//s", "/x/./s",
                                  "/x/../s", "/x/s/", "/x/\x00s", "/x/\ns", "/" + "x" * 103,
                                  "/" + "é" * 52])
def test_rejects_noncanonical_or_overlong_paths(path):
    with pytest.raises(ConfigError):
        spec(unix_socket_path=path)


@pytest.mark.parametrize("url", [None, 1, "", "http:///v1", "https://gateway.invalid/v1",
                                 "http://u:p@gateway.invalid/v1", "http://gateway.invalid/v1?",
                                 "http://gateway.invalid/v1#", "http://gateway.invalid:bad/v1",
                                 "http://gateway.invalid/\nv1", "http://gateway.invalid\\x/v1"])
def test_rejects_ambiguous_logical_urls(url):
    with pytest.raises(ConfigError):
        ModelSpec(name="s", adapter="openai-compatible", model="m", base_url=url,
                  unix_socket_path="/synthetic-absent/socket")


def test_rejects_other_adapter():
    with pytest.raises(ConfigError):
        ModelSpec(name="s", adapter="anthropic", model="m", base_url="http://fixture.invalid",
                  unix_socket_path="/synthetic-absent/socket")


def test_rejects_symlink_components_and_nonsocket_leaf():
    with scratch() as directory:
        leaf = directory / "s"
        leaf.write_text("synthetic")
        with pytest.raises(ConfigError):
            spec(unix_socket_path=str(leaf))
        alias = directory / "a"
        alias.symlink_to(directory, target_is_directory=True)
        with pytest.raises(ConfigError):
            spec(unix_socket_path=str(alias / "missing"))
        leaf.unlink()
        leaf.symlink_to(directory / "missing")
        with pytest.raises(ConfigError):
            spec(unix_socket_path=str(leaf))


@pytest.mark.parametrize("method", ["extract", "converse"])
def test_revalidates_before_dispatch(monkeypatch, method):
    with scratch() as directory:
        path = directory / "s"
        adapter = OpenAICompatAdapter(spec(unix_socket_path=str(path)))
        path.symlink_to(directory / "missing")
        monkeypatch.setattr(httpx, "Client", lambda **k: pytest.fail("dispatch before validation"))
        with pytest.raises(ConfigError):
            invoke(adapter, method)


@pytest.mark.parametrize("method", ["extract", "converse"])
def test_missing_socket_is_adapter_error_without_tcp_fallback(monkeypatch, method):
    with scratch() as directory:
        monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("TCP fallback"))
        with pytest.raises(AdapterError, match="HTTP failure"):
            invoke(OpenAICompatAdapter(spec(unix_socket_path=str(directory / "missing"))), method)


@pytest.mark.parametrize("method", ["extract", "converse"])
@pytest.mark.parametrize("status", [307, 503])
def test_error_and_redirect_preserve_one_request_without_following(method, status):
    with gateway(status, b"synthetic refusal", {"Location": "http://unreachable.invalid/v1"}) as (path, calls, _):
        with pytest.raises(AdapterError, match=f"returned {status}: synthetic refusal"):
            invoke(OpenAICompatAdapter(spec(unix_socket_path=path)), method)
        assert len(calls) == 1


def test_endpoint_identity_is_versioned_full_digest_and_exact_tuple():
    original = spec()
    for candidate in (original, replace(original, unix_socket_path="/synthetic-absent/s")):
        expected = ["model-endpoint-v1", "unix" if candidate.unix_socket_path else "tcp",
                    candidate.unix_socket_path, candidate.base_url, candidate.adapter]
        assert candidate.endpoint_identity() == "model-endpoint-v1:" + hashlib.sha256(
            json.dumps(expected, separators=(",", ":")).encode()).hexdigest()
    identities = {candidate.endpoint_identity() for candidate in (
        original, replace(original, base_url=original.base_url + "/"),
        replace(original, adapter="anthropic"),
        replace(original, unix_socket_path="/synthetic-absent/a"),
        replace(original, unix_socket_path="/synthetic-absent/b"))}
    assert len(identities) == 5
    assert len(original.endpoint_identity().split(":")[1]) == 64


def test_unix_extraction_continuations_use_fresh_requests_and_sum_cost():
    first, second = payload(), payload()
    first["choices"][0]["message"]["content"] = '{"fixture":'
    first["choices"][0]["finish_reason"] = "length"
    second["choices"][0]["message"]["content"] = 'true}'
    with gateway(response=[json.dumps(first).encode(), json.dumps(second).encode()]) as (path, calls, _):
        adapter = OpenAICompatAdapter(spec(unix_socket_path=path, max_continuations=1))
        result = invoke(adapter, "extract")
        assert result.text == '{"fixture":true}'
        assert result.cost_usd == 0.024
        assert result.input_tokens == 6 and result.output_tokens == 10
        assert len(calls) == 2
        assert isinstance(json.loads(calls[0][2])["messages"][0]["content"], list)
        assert json.loads(calls[1][2])["messages"][0]["content"] == "FIXTURE"


def test_unix_conversation_preserves_tool_calls_and_recorded_body():
    reply = payload()
    reply["choices"][0]["message"] = {"content": None, "tool_calls": [
        {"id": "synthetic-call", "type": "function", "function": {
            "name": "fixture", "arguments": '{"value":true}'}}]}
    with gateway(response=json.dumps(reply).encode()) as (path, calls, _):
        result = invoke(OpenAICompatAdapter(spec(unix_socket_path=path)), "converse")
        assert result.text == ""
        assert result.tool_calls == reply["choices"][0]["message"]["tool_calls"]
        assert result.request == json.loads(calls[0][2])
        assert result.response == reply


@pytest.mark.parametrize("method", ["extract", "converse"])
def test_unix_cost_fallback_preserves_configured_prices(method):
    reply = payload()
    reply["usage"]["cost"] = "not-a-price"
    with gateway(response=json.dumps(reply).encode()) as (path, _, _):
        model = spec(unix_socket_path=path, cost_per_mtok_in=2, cost_per_mtok_out=4)
        result = invoke(OpenAICompatAdapter(model), method)
        assert result.cost_usd == (3 * 2 + 5 * 4) / 1_000_000
