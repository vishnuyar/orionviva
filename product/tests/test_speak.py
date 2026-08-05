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
#
# A version earns a pin by being named somewhere that must still resolve — the
# module points at it, or a stored reading was recorded under it. A version no
# artifact names is not pinned: freezing it protects nothing and reads as a
# guarantee about text nobody can reach.
FROZEN_SPEAK_PROMPTS = {
    "speak-v1": "8f65a0d62c9f73cb",
    "speak-final-v1": "8e14a31d4ccd20e8",
    "speak-protocol-v1": "93a797d0f010909a",
    "speak-retry-v1": "9224620b7b861c8c",
    "speak-v4": "aed70cdb9970d43b",
    "speak-final-v4": "2cac1de408a24750",
    "speak-protocol-v4": "ec83cfb6be5d52eb",
    "speak-v5": "4afee4d00b859020",
    "speak-final-v5": "2e4f9493f790ea3f",
    "speak-protocol-v5": "d3b32dd56e5eb658",
    "speak-closing-v1": "cb35be62c4daf926",
    "speak-refusal-v1": "126880ba51c64e1f",
    "speak-refusal-schema-v1": "8bf922a9911e3a45",
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


# Every refusal now buys one more model call, to say what happened in Viva's
# voice. A script ending in a refusal has to answer that call; these are the
# replies that compose nothing, so the deterministic sentence stands.
def _declines_to_compose():
    return _turn(text="")


NO_COMPOSITION = "not a JSON block"


# ------------------------------------------------------------ frozen prompts

def test_speak_prompts_are_frozen_files():
    for version_id, pinned in FROZEN_SPEAK_PROMPTS.items():
        text = promptstore.load(PROMPTS, version_id)
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        assert digest == pinned, (
            f"{version_id}.txt changed — a released prompt file is immutable; "
            "add a new version file instead")


def test_every_version_the_module_speaks_under_is_pinned():
    """A version bump that forgets its pin leaves the new text editable in
    place, and nothing else would notice."""
    import viva.speak as speak_module
    live = {getattr(speak_module, name)
            for name in dir(speak_module) if name.endswith("_VERSION")}
    unpinned = sorted(live - set(FROZEN_SPEAK_PROMPTS))
    assert not unpinned, (
        f"{unpinned} are in force and unpinned — add each digest to "
        "FROZEN_SPEAK_PROMPTS in the same commit that releases the text")


# ------------------------------------------------------------ native planner

def test_native_planner_produces_a_cited_answer(registry):
    script = ChatScript([
        _turn([_call("query_ledger", {"entity": "balances",
                                      "filters": {"account": "chk"}})]),
        _turn([_call(FINAL_TOOL, {
            "answer": "Your checking holds 600.00, and that figure is "
                      "verified against the statement.",
            "figures": [{"id": "f1"}]}, call_id="c2")]),
    ])
    result = run("what is my checking balance?", NativePlanner(script), registry)
    assert result.answered and result.calls == 1
    # The grade is the ledger's, not the model's: the answer cited an id, and
    # the grade travelled with the figure the tool emitted.
    assert result.grade == "corroborated"
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
        _turn([_call("list_movements", {"filters": {"account": "chk"}})]),
        _turn([_call(FINAL_TOOL, {"answer": answer, "figures": [],
                                  "dates": [{"iso": "2026-01-05"}]},
                     call_id="c2")]),
    ])
    from_native = run("when?", NativePlanner(native), registry)
    assert from_native.answered, from_native.text

    text = TextScript([
        '```json\n{"tool": "list_movements", '
        '"args": {"filters": {"account": "chk"}}}\n```',
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
        _declines_to_compose(),
    ])
    planner = NativePlanner(script)
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unparseable"
    # The correction reached the model as the next user message, naming the
    # problem, and both bad replies are captured as such.
    second = script.seen[1]["messages"]
    assert second[-1]["role"] == "user"
    assert "could not be used" in second[-1]["content"]
    # The two bad replies, then the call that composes the refusal.
    assert [e.parse_ok for e in planner.exchanges][:2] == [False, False]


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
    assert "no answer" in result.detail


# -------------------------------------------------------------- text planner

def test_text_planner_produces_a_cited_answer(registry):
    steps = [
        '```json\n{"tool": "query_ledger", "args": {"entity": "balances", '
        '"filters": {"account": "chk"}}}\n```',
        '```json\n{"answer": "Your checking holds 600.00, verified.", '
        '"figures": [{"id": "f1"}]}\n```',
    ]
    script = TextScript(steps)
    result = run("what is my checking balance?", TextPlanner(script), registry)
    assert result.answered and result.grade == "corroborated"
    # Each step's prompt carries the voice, the schemas and the results so far.
    assert "Viva" in script.prompts[0]
    assert FINAL_TOOL in script.prompts[0]
    assert "600.00" in script.prompts[1]


def test_text_planner_corrects_once_then_refuses(registry):
    script = TextScript(["no json here at all", "still just prose",
                         NO_COMPOSITION])
    planner = TextPlanner(script)
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unparseable"
    assert "could not be used" in script.prompts[1]
    # The two bad replies, then the call that composes the refusal.
    assert [e.parse_ok for e in planner.exchanges][:2] == [False, False]


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
            "figures": [{"id": "f1"}]}, call_id="c2")]),
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
        assert payload["prompt_versions"]["speak"].startswith("speak-v5@")
        assert payload["prompt_versions"]["tools"].startswith("tools-v5@")
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
        '"figures": [{"id": "f1"}]}\n```',
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


def test_a_number_the_caller_typed_cannot_become_a_computed_figure(registry):
    """This replaces the check that compute's caller-supplied record ids and
    grades could not mint a figure. Those fields are gone: an operand is a
    figure id, so there is nothing left to plant. The refusal now lands on the
    first call, and it names what could have been used instead."""
    seen = {}

    def planner(context):
        if not context["results"]:
            return {"tool": "compute",
                    "args": {"expression": "x", "inputs": {"x": "854203.99"}}}
        seen["refusal"] = context["results"][0]["refusal"]
        return {"answer": "You hold 854203.99 in savings.", "figures": []}

    result = run("savings?", planner, registry)
    assert seen["refusal"] == "bad_input"
    assert not result.answered and result.refusal == "unfounded_figure"


def test_compute_over_a_fetched_figure_still_grounds(registry):
    """The legitimate chain — fetch, then compute over what was fetched, citing
    the result — must keep working, and its provenance is inherited rather than
    asserted by the caller."""
    def planner(context):
        if not context["results"]:
            return {"tool": "query_ledger",
                    "args": {"entity": "balances",
                             "filters": {"account": "chk"}}}
        if len(context["results"]) == 1:
            balance = context["results"][0]["figures"][0]["id"]
            return {"tool": "compute",
                    "args": {"expression": "x * 2", "inputs": {"x": balance}}}
        doubled = context["results"][1]["figures"][0]
        return {"answer": f"Twice your checking balance would be "
                          f"{doubled['value']}.",
                "figures": [{"id": doubled["id"]}]}

    result = run("what is twice my balance?", planner, registry)
    assert result.answered and result.grade == "corroborated"
    assert result.figures[0]["record_ids"] == ["chk", "doc-jan"]


def test_an_answer_may_quote_a_row_date_from_a_windowed_read(registry):
    """A row's own date is declarable and sayable even though the window filter
    that found it shares its year — the filter is scope the read reports, and
    the row's date is something the read asserts, carried on the figure for
    that row's amount."""
    def planner(context):
        if not context["results"]:
            return {"tool": "list_movements",
                    "args": {"filters": {"account": "chk",
                                         "window": {"from": "2026-01-01",
                                                    "to": "2026-01-31"}}}}
        fig = context["results"][0]["figures"][0]
        return {"answer": f"On {fig['dated']} you spent 400.00 at that market.",
                "figures": [{"id": fig["id"]}],
                "dates": [{"iso": fig["dated"]}]}

    result = run("what did I spend in January?", planner, registry)
    assert result.answered, result.text
    assert "2026-01-05" in result.text


def test_a_refusals_record_ids_do_not_join_the_grounding_pool(registry):
    def planner(context):
        if not context["results"]:
            return {"tool": "get_provenance", "args": {"record_id": "999999"}}
        return {"answer": "It rests on 999999.", "figures": []}

    result = run("why?", planner, registry)
    assert not result.answered


# ------------------------------------------ the closing call and the refusal

def test_the_closing_call_takes_the_reads_off_the_table(registry):
    """At exhaustion the model is not asked nicely to stop reading — the reads
    are gone, and the only thing it can do is speak."""
    script = ChatScript([
        _turn([_call("check_completeness", {})]),
        _turn([_call(FINAL_TOOL, {"answer": "I could not finish that.",
                                  "figures": []}, call_id="c2")]),
    ])
    result = run("balance?", NativePlanner(script), registry, max_calls=1)
    assert result.answered and result.text == "I could not finish that."
    offered = {t["name"] for t in script.seen[-1]["tools"]}
    assert offered == {FINAL_TOOL}
    # The call it made and could not be given is answered, not left dangling —
    # and reaching this step cost no extra model call: the budget was spent the
    # moment the transcript filled, so the terminator-only ask came at once.
    last = script.seen[-1]["messages"][-1]
    assert last["role"] == "tool" and last["tool_call_id"] == "c1"
    assert "no tool calls left" in last["content"]
    assert len(script.seen) == 2


def test_the_model_is_told_how_many_calls_it_has_left(registry):
    """The runner computing a budget nobody is shown is not a budget. Both
    modalities must put it where the model actually reads."""
    script = ChatScript([
        _turn([_call("check_completeness", {})]),
        _turn([_call(FINAL_TOOL, {"answer": "All settled.", "figures": []},
                     call_id="c2")]),
    ])
    run("balance?", NativePlanner(script), registry, max_calls=4)
    threaded = [m for m in script.seen[-1]["messages"] if m["role"] == "tool"]
    assert json.loads(threaded[-1]["content"])["calls_remaining"] == 3

    text = TextScript([
        '```json\n{"tool": "check_completeness", "args": {}}\n```',
        '```json\n{"answer": "All settled.", "figures": []}\n```',
    ])
    run("balance?", TextPlanner(text), registry, max_calls=4)
    assert "Tool calls left in this turn: 4" in text.prompts[0]
    assert "Tool calls left in this turn: 3" in text.prompts[1]


def test_the_text_protocol_teaches_the_shape_the_code_actually_accepts(registry):
    """A protocol prompt that teaches a superseded terminator costs every text
    answer its one correction before it can succeed."""
    text = TextScript(['```json\n{"answer": "All settled.", "figures": []}\n```'])
    run("balance?", TextPlanner(text), registry)
    taught = text.prompts[0]
    assert '"figures": [{"id": "f1"}]' in taught
    # ...and says so as an example, not as a value to state.
    assert "examples, not values you may state" in taught
    assert '"record_ids"' not in taught and '"grade": ""' not in taught
    assert '"stipulated"' in taught


def test_a_refusal_request_answers_every_call_the_model_left_open(registry):
    """A protocol needs each of its tool calls answered before another message
    can follow. The turn ends in exactly the state where one is not: the model
    called the terminator, and a terminator returns no result. An endpoint
    rejects that shape, so the composed refusal would never arrive at all."""
    script = ChatScript([
        _turn([_call(FINAL_TOOL, {"answer": "It is 9999.99.", "figures": []},
                     call_id="open-1")]),
        _declines_to_compose(),
    ])
    run("balance?", NativePlanner(script), registry)
    messages = script.seen[-1]["messages"]
    called = [str(c["id"]) for m in messages if m["role"] == "assistant"
              for c in m.get("tool_calls") or []]
    answered = [str(m["tool_call_id"]) for m in messages if m["role"] == "tool"]
    assert called and set(called) <= set(answered), (
        f"{sorted(set(called) - set(answered))} were left unanswered")


def test_a_composed_refusal_is_shown_standing_on_what_it_cited(registry):
    """A refusal that states a figure is a claim like any other, and the
    surface prints its grade and its records off the result."""
    script = ChatScript([
        _turn([_call("query_ledger", {"entity": "balances",
                                      "filters": {"account": "chk"}})]),
        _turn([_call(FINAL_TOOL, {"answer": "It is 9999.99.", "figures": []},
                     call_id="c2")]),
        _turn([_call("deliver_refusal",
                     {"answer": "I can only stand behind the 600.00 I read.",
                      "figures": [{"id": "f1"}]}, call_id="c3")]),
    ])
    result = run("balance?", NativePlanner(script), registry)
    assert not result.answered and result.refusal == "unfounded_figure"
    assert result.figures and result.figures[0]["record_ids"]
    assert result.grade == "corroborated"


def test_the_refusal_terminators_description_is_not_a_raw_template(registry):
    """Its description is sent to the model as the tool's contract. A prompt
    with unfilled slots in it is model-facing garbage at exactly the moment
    careful prose is being asked for — so this checks what actually goes on the
    wire, not what a helper would build if asked nicely."""
    script = ChatScript([
        _turn([_call(FINAL_TOOL, {"answer": "It is 9999.99.", "figures": []})]),
        _declines_to_compose(),
    ])
    run("balance?", NativePlanner(script), registry)
    offered = script.seen[-1]["tools"]
    assert [t["name"] for t in offered] == ["deliver_refusal"]
    described = offered[0]["description"]
    assert "{explanation}" not in described and "{established}" not in described
    assert set(offered[0]["parameters"]["properties"]) == {
        "answer", "figures", "stipulated", "dates"}
    # And the instruction reaches the model once, as the answer to the open
    # call — not once there and again as a message after it.
    sent = [m for m in script.seen[-1]["messages"]
            if "cannot be answered" in str(m.get("content") or "")]
    assert len(sent) == 1 and sent[0]["role"] == "tool"


def test_a_refusal_is_spoken_in_vivas_voice_with_the_tag_kept_for_the_log(registry):
    spoken = ("I could not stand that answer on anything I hold, so I would "
              "rather say nothing than guess.")
    script = ChatScript([
        _turn([_call(FINAL_TOOL, {"answer": "It is 9999.99.", "figures": []})]),
        _turn([_call("deliver_refusal", {"answer": spoken, "figures": []},
                     call_id="c2")]),
    ])
    result = run("balance?", NativePlanner(script), registry)
    assert not result.answered
    assert result.refusal == "unfounded_figure"      # the tag, for the log
    assert result.text == spoken                     # the prose, for the person
    assert "unfounded_figure" not in result.text


def test_a_composed_refusal_reaching_for_a_number_is_itself_refused(registry):
    """The guardrail that makes composing safe: the same check runs on what the
    model wrote, and one failure falls back to the machine's own sentence
    rather than trying again."""
    script = ChatScript([
        _turn([_call(FINAL_TOOL, {"answer": "It is 9999.99.", "figures": []})]),
        _turn([_call("deliver_refusal",
                     {"answer": "I cannot confirm the 12345.67 you asked "
                                "about.", "figures": []}, call_id="c2")]),
    ])
    result = run("balance?", NativePlanner(script), registry)
    assert not result.answered and result.refusal == "unfounded_figure"
    assert "12345.67" not in result.text
    assert "no figure in this run carries" in result.detail
    assert not script.turns          # exactly one attempt, then the fallback


def test_an_unreachable_model_is_never_asked_to_compose_its_own_silence(registry):
    planner = NativePlanner(BrokenChat())
    result = run("balance?", planner, registry)
    assert result.refusal == "model_unreachable"
    assert len(planner.exchanges) == 1


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
    assert result.detail == "no model today"


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
