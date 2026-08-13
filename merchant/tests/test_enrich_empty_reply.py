"""What enrichment says when a reply carries nothing to parse: an empty visible
channel beside a reasoning channel is named as such, and an unreadable reply is
still reported as unreadable."""

import logging

import merchantcore.enrich as enrich
import vivacore.models as models
from merchantcore import Enricher
from vivacore.models.base import ModelResult


class _OneReply:
    """An adapter that hands back the same prepared result for every call."""

    def __init__(self, result):
        self._result = result

    def extract(self, pages, prompt):
        return self._result


def _result(text, **kw):
    return ModelResult(text=text, resolved_model="m", input_tokens=1,
                       output_tokens=1, cost_usd=0.0, latency_s=0.0,
                       request={}, response={}, **kw)


def _extractor(monkeypatch, result):
    monkeypatch.setattr(models, "adapter_for", lambda spec: _OneReply(result))
    return enrich.model_extractor(object())


def test_an_empty_reply_beside_a_reasoning_channel_names_the_reasoning(
        monkeypatch, caplog):
    extract = _extractor(monkeypatch, _result(
        "", finish_reason="length", reasoning_text="weighing the options",
        reasoning_tokens=8192))
    with caplog.at_level(logging.WARNING, logger="merchantcore.enrich"):
        assert extract("PROMPT") == ""
    said = " ".join(r.getMessage() for r in caplog.records)

    assert "reasoning" in said
    assert "8192" in said                          # the budget it went to
    assert "smaller chunk_size" not in said        # not sent after chunk size


def test_an_unreadable_reply_is_not_blamed_on_reasoning(monkeypatch, caplog):
    extract = _extractor(monkeypatch, _result("no object here", finish_reason="stop"))
    with caplog.at_level(logging.WARNING, logger="merchantcore.enrich"):
        records = Enricher(extract).enrich({"k": "EXAMPLE"})
    said = " ".join(r.getMessage() for r in caplog.records)

    assert records == {}
    assert "no JSON object found in the reply" in said
    assert "reasoning" not in said
