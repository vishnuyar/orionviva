"""Viva speaks: the planners, the session, the capture, and their refusals."""

import hashlib
import json

import pytest

from vivacore import promptstore
from vivacore.models import AdapterError, ChatTurn, ModelSpec
from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)
from viva.ledger.events import document_captured
from viva.speak import (FINAL_TOOL, NativePlanner, Session, TextPlanner,
                        max_calls_from_env, planner_factory, speak_spec)
from viva.tools import default_registry, run
from viva.tools.registry import PROMPTS

# The voice and the step protocol are released prompts: their text may never
# change. To edit one, add a new version file and point the module at it.
FROZEN_SPEAK_PROMPTS = {
    "speak-v1": "8f65a0d62c9f73cb",
    "speak-final-v1": "8e14a31d4ccd20e8",
    "speak-protocol-v1": "93a797d0f010909a",
    "speak-retry-v1": "9224620b7b861c8c",
    "speak-v2": "f2154bf11552432d",
    "speak-final-v2": "d746425703084d91",
    "speak-protocol-v2": "3b7576ececfae486",
    "speak-v3": "c898f122b4069899",
    "speak-final-v3": "19506ea8954a63c5",
    "speak-protocol-v3": "d6c9a16621b13270",
    "speak-v4": "aed70cdb9970d43b",
    "speak-final-v4": "2cac1de408a24750",
    "speak-protocol-v4": "ec83cfb6be5d52eb",
}


def _events():
    p = Provenance("doc-jan", 1, "r")
    return [
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01", institution="Northgate Bank",
                       account_number="XX4417", account_names=["R VANCE"]),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", "1000.00", "2026-01-01", p),
        simple_transaction("chk", "-400.00", "GREENFIELD MARKET",
                           "2026-01-05", provenance=p),
        closing_balance_observed("chk", "600.00", "2026-01-31",
                                 Provenance("doc-jan", 6, "r")),
    ]


@pytest.fixture()
def registry():
    return default_registry(LedgerProjection(_events()))


def _call(name, args, call_id="c1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _turn(tool_calls=None, text="", raw_arguments=None):
    calls = list(tool_calls or [])
    if raw_arguments is not None:
        calls = [{"id": "c1", "type": "function",
                  "function": {"name": "query_ledger",
                               "arguments": raw_arguments}}]
    message = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = calls
    return ChatTurn(message=message, tool_calls=calls, text=text,
                    finish_reason="tool_calls" if calls else "stop",
                    input_tokens=10, output_tokens=5, cost_usd=0.001,
                    latency_s=0.1, resolved_model="scripted-model",
                    request={"messages": "elided"}, response={"scripted": True})


class ChatScript:
    """A converse-speaking adapter that replays scripted turns and keeps every
    message list it was shown."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def converse(self, messages, tools):
        self.seen.append({"messages": [dict(m) for m in messages],
                          "tools": list(tools)})
        if not self.turns:
            raise AssertionError("script exhausted")
        return self.turns.pop(0)


class BrokenChat:
    def converse(self, messages, tools):
        raise AdapterError("no route to model")


class TextScript:
    """An extract-speaking adapter replaying scripted texts, ModelResult-shaped."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.prompts = []

    def extract(self, pages, prompt):
        from vivacore.models.base import ModelResult
        self.prompts.append(prompt)
        return ModelResult(text=self.texts.pop(0),
                           resolved_model="scripted-model", input_tokens=7,
                           output_tokens=3, cost_usd=0.0005, latency_s=0.1,
                           request={"prompt": prompt}, response={"scripted": True})


class BrokenText:
    def extract(self, pages, prompt):
        raise AdapterError("no route to model")


# ------------------------------------------------------------ frozen prompts

def test_speak_prompts_are_frozen_files():
    for version_id, pinned in FROZEN_SPEAK_PROMPTS.items():
        text = promptstore.load(PROMPTS, version_id)
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        assert digest == pinned, (
            f"{version_id}.txt changed — a released prompt file is immutable; "
            "add a new version file instead")


# ------------------------------------------------------------ native planner

def test_native_planner_produces_a_cited_answer(registry):
    script = ChatScript([
        _turn([_call("query_ledger", {"entity": "balances",
                                      "filters": {"account": "chk"}})]),
        _turn([_call(FINAL_TOOL, {
            "answer": "Your checking holds 600.00, and that figure is "
                      "verified against the statement.",
            "figures": [{"value": "600.00", "record_ids": ["doc-jan"],
                         "grade": "verified"}]}, call_id="c2")]),
    ])
    result = run("what is my checking balance?", NativePlanner(script), registry)
    assert result.answered and result.calls == 1
    assert result.grade == "verified"
    # The system prompt opened the conversation and the question followed it.
    first = script.seen[0]["messages"]
    assert first[0]["role"] == "system" and "Viva" in first[0]["content"]
    assert first[-1] == {"role": "user",
                         "content": "what is my checking balance?"}
    # The terminator schema rides beside the registry's verbs, unregistered.
    offered = {t["name"] for t in script.seen[0]["tools"]}
    assert FINAL_TOOL in offered and "query_ledger" in offered
    assert FINAL_TOOL not in registry.names()


def test_both_modalities_carry_a_date_declaration_to_the_gate(registry):
    """The wiring, not the gate: a date declared through each real planner must
    reach the gate and let the answer say the date in words. Neither planner may
    quietly drop the field."""
    answer = "The last movement I hold is from January 5, 2026."
    native = ChatScript([
        _turn([_call("query_ledger", {"entity": "transactions"})]),
        _turn([_call(FINAL_TOOL, {"answer": answer, "figures": [],
                                  "dates": [{"iso": "2026-01-05"}]},
                     call_id="c2")]),
    ])
    from_native = run("when?", NativePlanner(native), registry)
    assert from_native.answered, from_native.text

    text = TextScript([
        '```json\n{"tool": "query_ledger", "args": {"entity": "transactions"}}\n```',
        '```json\n{"answer": "' + answer + '", "figures": [], '
        '"dates": [{"iso": "2026-01-05"}]}\n```',
    ])
    from_text = run("when?", TextPlanner(text), registry)
    assert from_text.answered, from_text.text

    # And the field is offered to a model in both modalities, not just honored
    # when one happens to send it.
    terminator = next(s for s in native.seen[0]["tools"] if s["name"] == FINAL_TOOL)
    assert "dates" in terminator["parameters"]["properties"]
    assert "dates" in text.prompts[0]


def test_a_malformed_dates_field_is_corrected_rather_than_refused(registry):
    """A shape a model can fix costs it a correction, never the whole turn."""
    script = ChatScript([
        _turn([_call("query_ledger", {"entity": "transactions"})]),
        _turn([_call(FINAL_TOOL, {"answer": "Nothing to report.",
                                  "figures": [], "dates": "January"},
                     call_id="c2")]),
        _turn([_call(FINAL_TOOL, {"answer": "Nothing to report.",
                                  "figures": [], "dates": []},
                     call_id="c3")]),
    ])
    result = run("when?", NativePlanner(script), registry)
    assert result.answered, result.text
    correction = script.seen[-1]["messages"][-1]
    assert "dates" in correction["content"]


def test_native_planner_threads_the_result_back_as_a_tool_message(registry):
    script = ChatScript([
        _turn([_call("query_ledger", {"entity": "balances",
                                      "filters": {"account": "chk"}},
                     call_id="call-77")]),
        _turn([_call(FINAL_TOOL, {"answer": "All settled.", "figures": []},
                     call_id="c2")]),
    ])
    run("balance?", NativePlanner(script), registry)
    second = script.seen[1]["messages"]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call-77"
    assert "600.00" in tool_msgs[0]["content"]


def test_native_prose_without_a_step_gets_one_correction_then_refuses(registry):
    script = ChatScript([
        _turn(text="Your balance looks fine to me."),
        _turn(text="Really, it is fine."),
    ])
    planner = NativePlanner(script)
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unparseable"
    # The correction reached the model as the next user message, naming the
    # problem, and both bad replies are captured as such.
    second = script.seen[1]["messages"]
    assert second[-1]["role"] == "user"
    assert "could not be used" in second[-1]["content"]
    assert [e.parse_ok for e in planner.exchanges] == [False, False]


def test_native_malformed_arguments_are_corrected_as_the_calls_result(registry):
    script = ChatScript([
        _turn(raw_arguments="{not json"),
        _turn([_call(FINAL_TOOL, {"answer": "I could not read the ledger "
                                            "this time.",
                                  "figures": []}, call_id="c2")]),
    ])
    result = run("balance?", NativePlanner(script), registry)
    assert result.answered
    # The bad call got the correction as its own tool result, keeping the
    # message protocol well-formed.
    second = script.seen[1]["messages"]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    assert len(tool_msgs) == 1 and "could not be used" in tool_msgs[0]["content"]


def test_native_final_mixed_with_tool_calls_is_corrected(registry):
    script = ChatScript([
        _turn([_call("query_ledger", {"entity": "balances", "filters": {}}),
               _call(FINAL_TOOL, {"answer": "done"}, call_id="c2")]),
        _turn([_call(FINAL_TOOL, {"answer": "Nothing to report.",
                                  "figures": []}, call_id="c3")]),
    ])
    result = run("balance?", NativePlanner(script), registry)
    assert result.answered and result.calls == 0
    second = script.seen[1]["messages"]
    corrections = [m for m in second if m.get("role") == "tool"
                   and "could not be used" in m.get("content", "")]
    assert len(corrections) == 2


def test_native_transport_failure_refuses_model_unreachable(registry):
    result = run("balance?", NativePlanner(BrokenChat()), registry)
    assert not result.answered and result.refusal == "model_unreachable"
    assert "no answer" in result.text


# -------------------------------------------------------------- text planner

def test_text_planner_produces_a_cited_answer(registry):
    steps = [
        '```json\n{"tool": "query_ledger", "args": {"entity": "balances", '
        '"filters": {"account": "chk"}}}\n```',
        '```json\n{"answer": "Your checking holds 600.00, verified.", '
        '"figures": [{"value": "600.00", "record_ids": ["doc-jan"], '
        '"grade": "verified"}]}\n```',
    ]
    script = TextScript(steps)
    result = run("what is my checking balance?", TextPlanner(script), registry)
    assert result.answered and result.grade == "verified"
    # Each step's prompt carries the voice, the schemas and the results so far.
    assert "Viva" in script.prompts[0]
    assert FINAL_TOOL in script.prompts[0]
    assert "600.00" in script.prompts[1]


def test_text_planner_corrects_once_then_refuses(registry):
    script = TextScript(["no json here at all", "still just prose"])
    planner = TextPlanner(script)
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unparseable"
    assert "could not be used" in script.prompts[1]
    assert [e.parse_ok for e in planner.exchanges] == [False, False]


def test_text_transport_failure_refuses_model_unreachable(registry):
    result = run("balance?", TextPlanner(BrokenText()), registry)
    assert not result.answered and result.refusal == "model_unreachable"


# ------------------------------------------------------------------ sessions

def _answer_script():
    return ChatScript([
        _turn([_call("query_ledger", {"entity": "balances",
                                      "filters": {"account": "chk"}})]),
        _turn([_call(FINAL_TOOL, {
            "answer": "Your checking holds 600.00.",
            "figures": [{"value": "600.00", "record_ids": ["doc-jan"],
                         "grade": "verified"}]}, call_id="c2")]),
    ])


def test_a_session_carries_prior_turns_as_context(registry):
    scripts = []

    def factory(prior_turns):
        script = _answer_script()
        scripts.append(script)
        return NativePlanner(script, prior_turns)

    session = Session(registry, factory, session_id="s-test",
                      today=lambda: "2026-02-06")
    session.ask("what is my checking balance?")
    session.ask("and is that figure current?")
    second_first = scripts[1].seen[0]["messages"]
    roles = [m["role"] for m in second_first]
    # system, prior question, prior answer, new question — in that order.
    assert roles == ["system", "user", "assistant", "user"]
    assert second_first[1]["content"] == "what is my checking balance?"
    assert "600.00" in second_first[2]["content"]


def test_a_session_records_every_exchange_in_the_ledger(registry):
    class LedgerLog:
        def __init__(self):
            self.events = []

        def append(self, event):
            self.events.append(event)

    log = LedgerLog()

    def factory(prior_turns):
        return NativePlanner(_answer_script(), prior_turns)

    session = Session(registry, factory, ledger=log, model="pinned-model",
                      session_id="s-test", today=lambda: "2026-02-06")
    turn = session.ask("what is my checking balance?")
    assert turn.result.answered
    assert len(log.events) == 2
    for event in log.events:
        assert event.body["phase"] == "speak"
        assert event.body["model"] == "pinned-model"
        assert event.body["input_mode"] == "native-tools"
        assert event.body["parse_ok"] is True
        payload = json.loads(event.body["response_text"])
        assert payload["request"] and payload["response"]
        assert payload["prompt_versions"]["speak"].startswith("speak-v4@")
        assert payload["prompt_versions"]["tools"].startswith("tools-v1@")
        assert payload["verdict"]["answered"] is True
    assert log.events[0].body["doc_id"] == "speak:s-test:1:1"
    assert log.events[1].body["doc_id"] == "speak:s-test:1:2"


def test_a_turns_cost_is_the_sum_of_its_exchanges(registry):
    def factory(prior_turns):
        return NativePlanner(_answer_script(), prior_turns)

    session = Session(registry, factory, session_id="s-test",
                      today=lambda: "2026-02-06")
    turn = session.ask("what is my checking balance?")
    assert turn.cost_usd == pytest.approx(0.002)
    assert turn.tokens == (20, 10)


def test_text_planner_grants_its_correction_per_step_not_per_run(registry):
    steps = [
        "no json here at all",
        '```json\n{"tool": "query_ledger", "args": {"entity": "balances", '
        '"filters": {"account": "chk"}}}\n```',
        "prose again, later in the turn",
        '```json\n{"answer": "Your checking holds 600.00, verified.", '
        '"figures": [{"value": "600.00", "record_ids": ["doc-jan"], '
        '"grade": "verified"}]}\n```',
    ]
    result = run("balance?", TextPlanner(TextScript(steps)), registry)
    # The second malformed reply gets its own correction: a good step in
    # between resets the budget, matching the native planner.
    assert result.answered


def test_text_planner_corrects_a_reply_with_two_fenced_blocks(registry):
    steps = [
        '```json\n{"tool": "query_ledger", "args": {"entity": "balances", '
        '"filters": {}}}\n```\nfor example, and then really:\n'
        '```json\n{"answer": "All fine.", "figures": []}\n```',
        '```json\n{"answer": "Nothing to report.", "figures": []}\n```',
    ]
    script = TextScript(steps)
    result = run("balance?", TextPlanner(script), registry)
    # Neither block ran — the ambiguous reply was corrected, not guessed at.
    assert result.answered and result.calls == 0
    assert "exactly one" in script.prompts[1]


# --------------------------------------------------- the gate and refusals

def test_a_number_echoed_by_a_refusal_cannot_ground_an_answer(registry):
    """A planner inventing a numeric account id gets a refusal that echoes the
    digits; stating them as bare text must still be refused — a refusal
    asserts nothing, so it grounds nothing."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances",
                             "filters": {"account": "854203"}}}
        assert context["results"][0]["ok"] is False
        return {"answer": "Your savings holds 854203 dollars.", "figures": []}

    result = run("savings balance?", planner, registry)
    assert not result.answered
    assert result.refusal == "unfounded_figure"


def test_a_date_echoed_by_an_ok_result_cannot_ground_an_answer(registry):
    """An ok result restating a planner-chosen `since` is an echo, not an
    assertion — its digits must not become citable spending figures."""
    def planner(context):
        if not context["results"]:
            return {"tool": "get_transparency",
                    "args": {"topic": "calls_spent", "since": "8542-01-01"}}
        assert context["results"][0]["ok"] is True
        return {"answer": "You spent 8542 on that.", "figures": []}

    result = run("what did I spend?", planner, registry)
    assert not result.answered
    assert result.refusal == "unfounded_figure"


def test_compute_cannot_mint_a_cited_figure_from_invented_parts(registry):
    """Caller-supplied inputs, record ids and grades flow through compute's ok
    result; none of them may ground a figure the vault never asserted."""
    def planner(context):
        if not context["results"]:
            return {"tool": "compute",
                    "args": {"expression": "x",
                             "inputs": {"x": "854203.99"},
                             "grades": {"x": "verified"},
                             "record_ids": ["invented-doc"]}}
        return {"answer": "You hold 854203.99 in savings.",
                "figures": [{"value": "854203.99",
                             "record_ids": ["invented-doc"],
                             "grade": "verified"}]}

    result = run("savings?", planner, registry)
    assert not result.answered
    assert result.refusal == "uncited_figure"


def test_an_expression_literal_cannot_ground_an_answer(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "compute", "args": {"expression": "424242 + 0"}}
        return {"answer": "That makes 424242.", "figures": []}

    result = run("how much?", planner, registry)
    assert not result.answered


def test_compute_over_fetched_figures_still_grounds(registry):
    """The legitimate chain — fetch, then compute over what was fetched,
    citing the fetched record — must keep working under the taint rule."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances",
                             "filters": {"account": "chk"}}}
        if len(context["results"]) == 1:
            return {"tool": "compute",
                    "args": {"expression": "x * 2",
                             "inputs": {"x": "600.00"},
                             "grades": {"x": "verified"},
                             "record_ids": ["doc-jan"]}}
        return {"answer": "Twice your checking balance of 600.00 would be "
                          "1200.00.",
                "figures": [{"value": "1200.00", "record_ids": ["doc-jan"],
                             "grade": "verified"}]}

    result = run("what is twice my balance?", planner, registry)
    assert result.answered and result.grade == "verified"


def test_an_answer_may_quote_a_row_date_from_a_windowed_query(registry):
    """A row's own date is declarable and sayable even though the window filter
    that found it shares its year — the filter is scope the read reports, and
    the row date is something the read asserts."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger",
                    "args": {"entity": "transactions",
                             "filters": {"account": "chk",
                                         "window": {"from": "2026-01-01",
                                                    "to": "2026-01-31"}}}}
        rows = context["results"][0]["data"]["transactions"]
        row = rows[0]
        return {"answer": f"On {row['date']} you spent 400.00 at that "
                          "market.",
                "figures": [{"value": row["amount"],
                             "record_ids": [row["provenance"]["doc_id"]],
                             "grade": row["grade"]}],
                "dates": [{"iso": row["date"]}]}

    result = run("what did I spend in January?", planner, registry)
    assert result.answered
    assert "2026-01-05" in result.text


def test_a_refusals_record_ids_do_not_join_the_grounding_pool(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "get_provenance", "args": {"record_id": "999999"}}
        return {"answer": "It rests on 999999.", "figures": []}

    result = run("why?", planner, registry)
    assert not result.answered


# ----------------------------------------------- the adapter, over the wire

class _Response:
    def __init__(self, payload=None, text="", status=200):
        self.status_code = status
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _chat_payload(message):
    return {"model": "resolved-m", "choices": [{"message": message,
                                                "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2}}


def _wire_adapter(monkeypatch, responses):
    import httpx

    from vivacore.models import OpenAICompatAdapter

    sent = []

    def post(url, json=None, headers=None, timeout=None):
        # Snapshot at send time: the caller's message list lives on after the
        # call, and what was on the wire is the fact being asserted.
        import copy
        sent.append(copy.deepcopy(json))
        return responses.pop(0)

    monkeypatch.setattr(httpx, "post", post)
    spec = ModelSpec(name="s", adapter="openai-compatible", model="m",
                     base_url="http://localhost:11434/v1")
    return OpenAICompatAdapter(spec), sent


def test_the_recorded_request_is_what_was_sent_not_what_came_later(
        registry, monkeypatch):
    adapter, sent = _wire_adapter(monkeypatch, [
        _Response(_chat_payload(
            {"role": "assistant", "content": None,
             "tool_calls": [_call("query_ledger",
                                  {"entity": "balances",
                                   "filters": {"account": "chk"}})]})),
        _Response(_chat_payload(
            {"role": "assistant", "content": None,
             "tool_calls": [_call(FINAL_TOOL,
                                  {"answer": "All settled.", "figures": []},
                                  call_id="c2")]})),
    ])
    planner = NativePlanner(adapter)
    result = run("balance?", planner, registry)
    assert result.answered
    # The first exchange's captured request holds the two messages actually
    # sent, untouched by everything the planner appended afterwards.
    first = planner.exchanges[0].request["messages"]
    assert [m["role"] for m in first] == ["system", "user"]
    assert len(sent[0]["messages"]) == 2 and len(sent[1]["messages"]) == 4


def test_a_200_with_a_non_json_body_refuses_model_unreachable(
        registry, monkeypatch):
    adapter, _ = _wire_adapter(monkeypatch,
                               [_Response(None, text="<html>oops</html>")])
    result = run("balance?", NativePlanner(adapter), registry)
    assert not result.answered
    assert result.refusal == "model_unreachable"


# ------------------------------------------------- the runner's refusal step

def test_the_runner_accepts_a_planner_refusal_step(registry):
    def planner(context):
        return {"refusal": "model_unreachable", "text": "no model today"}

    result = run("balance?", planner, registry)
    assert not result.answered
    assert result.refusal == "model_unreachable"
    assert result.text == "no model today"


# ------------------------------------------------------------- transparency

def test_calls_spent_names_what_it_counts(registry):
    result = registry.call("get_transparency", {"topic": "calls_spent"})
    assert result.ok
    assert any("maintenance agent" in c for c in result.caveats)


# ------------------------------------------------------------ configuration

def test_speak_spec_falls_back_to_the_document_readers_model(monkeypatch):
    for var in ("VIVA_SPEAK_MODEL", "VIVA_SPEAK_ADAPTER", "VIVA_SPEAK_BASE_URL",
                "VIVA_SPEAK_KEY_ENV", "VIVA_MODEL", "VIVA_MODEL_ADAPTER",
                "VIVA_MODEL_BASE_URL", "VIVA_MODEL_KEY_ENV"):
        monkeypatch.delenv(var, raising=False)
    assert speak_spec() is None
    monkeypatch.setenv("VIVA_MODEL", "pinned-model")
    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "openai-compatible")
    monkeypatch.setenv("VIVA_MODEL_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("VIVA_MODEL_KEY_ENV", "none")
    spec = speak_spec()
    assert spec.model == "pinned-model"
    assert spec.adapter == "openai-compatible"
    assert spec.api_key_env is None
    monkeypatch.setenv("VIVA_SPEAK_MODEL", "voice-model")
    assert speak_spec().model == "voice-model"


def test_planner_factory_is_native_first_with_text_as_the_fallback(monkeypatch):
    monkeypatch.delenv("VIVA_SPEAK_PROTOCOL", raising=False)
    compat = ModelSpec(name="s", adapter="openai-compatible", model="m",
                       base_url="http://localhost:11434/v1")
    assert isinstance(planner_factory(compat)([]), NativePlanner)
    # Forcing text is the per-model reversibility the contract promised.
    monkeypatch.setenv("VIVA_SPEAK_PROTOCOL", "text")
    assert isinstance(planner_factory(compat)([]), TextPlanner)
    # An adapter with no native conversation degrades to text on its own.
    monkeypatch.delenv("VIVA_SPEAK_PROTOCOL", raising=False)
    anthropic = ModelSpec(name="s", adapter="anthropic", model="m")
    assert isinstance(planner_factory(anthropic)([]), TextPlanner)


def test_the_call_budget_reads_the_environment(monkeypatch):
    monkeypatch.delenv("VIVA_SPEAK_MAX_CALLS", raising=False)
    assert max_calls_from_env() == 8
    monkeypatch.setenv("VIVA_SPEAK_MAX_CALLS", "3")
    assert max_calls_from_env() == 3
    monkeypatch.setenv("VIVA_SPEAK_MAX_CALLS", "not a number")
    assert max_calls_from_env() == 8
