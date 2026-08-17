"""Viva speaks: the planners, the session, the capture, and their refusals."""

import hashlib
import json

import pytest

from vivacore import promptstore
from vivacore.models import AdapterError, ChatTurn, ModelSpec
from viva import persona
from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)
from viva.ledger.events import document_captured
from viva.speak import (FINAL_TOOL, SHAPE_TOOL, SPEAK_VERSION, NativePlanner,
                        Session, TextPlanner, max_calls_from_env,
                        planner_factory, speak_spec)
from viva.tools import default_registry, run
from viva.tools.registry import DESCRIPTIONS_VERSION, PROMPTS

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
    "speak-v6": "87741100169f1700",
    "speak-final-v6": "5f98748162cd1a98",
    "speak-protocol-v6": "73b744eb3eced798",
    "speak-closing-v1": "cb35be62c4daf926",
    "speak-refusal-v1": "126880ba51c64e1f",
    "speak-refusal-schema-v1": "8bf922a9911e3a45",
    "speak-v7": "b09527b1ae744da3",
    "speak-final-v7": "4751e1115b0dc891",
    "speak-shape-v1": "6dc9f1a9279a5a76",
    "speak-protocol-v7": "efaf6d468d05d664",
    "speak-retry-v2": "fc0ed5d5b85f4e4f",
    "speak-closing-v2": "d14b9e242a758691",
    "speak-refusal-v2": "0936b83589585cdf",
    "speak-refusal-schema-v2": "2df04a260ba9f79f",
    "speak-v8": "7110996ff9f3dfc1",
    "speak-shape-v2": "c1eb515f0f44f510",
    "speak-shape-v3": "86cdfecaf82680e9",
    "speak-final-v8": "a696da8dc4063975",
    "speak-v9": "31e8d77c14ed1fab",
    "speak-shape-v4": "b1414ddd20442800",
    "speak-final-v9": "73dde76b1444a822",
    "speak-v10": "7bbe5d04dda5875f",
    "speak-shape-v5": "9f6ca8be25194302",
    "speak-final-v10": "0c7373aad33dd23e",
    "speak-shape-v6": "8727443fdd90f027",
    "speak-retry-v3": "ec6b6369a6c02300",
    "speak-repairs-v1": "40e6f50289ce7171",
    "speak-shape-v7": "e3f7b55e22261a12",
    "speak-final-v11": "4f3b44d44b932585",
    "speak-shape-v8": "834245339f59345e",
    "speak-repairs-v2": "0cbfcb3aa63a0739",
}


def _slot(name, type_, quantity=""):
    """One hole as a model sends it: what it is called, what shape of thing it
    holds, and — where it holds a magnitude — what that magnitude is of."""
    out = {"name": name, "type": type_}
    if quantity:
        out["quantity"] = quantity
    return out


def _shape_of(*clauses):
    """A shape as the runner takes one, for a scripted planner."""
    from viva.tools.shape import Clause, Shape, Slot
    return Shape(clauses=tuple(
        Clause(text=text, slots=tuple(Slot(*slot) for slot in slots))
        for text, slots in clauses))


def _shape_call(*clauses, call_id="c0"):
    """The commit_shape call every turn opens with: words with typed holes."""
    return _call(SHAPE_TOOL, {"clauses": [
        {"text": text, "slots": [_slot(*slot) for slot in slots]}
        for text, slots in clauses]}, call_id=call_id)


def _shape_block(*clauses):
    """The same, as the fenced block the text protocol speaks."""
    return "```json\n" + json.dumps({
        "tool": SHAPE_TOOL,
        "args": {"clauses": [
            {"text": text, "slots": [_slot(*slot) for slot in slots]}
            for text, slots in clauses]}}) + "\n```"


# What a turn says when it has read nothing. Every clause rests on something
# the run established, and a run that made no read has established one thing:
# the value the person put into their own question.
ASKED = "was it 40?"
ASKED_CLAUSE = ("You asked about {yours}.", [("yours", "supposed", "spending")])
ASKED_BINDINGS = {"yours": {"supposed": "40"}}


def _bind_block(bindings):
    return "```json\n" + json.dumps({"tool": FINAL_TOOL,
                                     "args": {"bindings": bindings}}) + "\n```"


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


def test_every_repair_a_check_can_name_has_reviewed_words():
    """Every tag in `REPAIRS` has non-empty words in the repairs file and the
    file names no tag that is not in `REPAIRS`; the retry template carries both
    fields it is formatted with."""
    from viva.speak import RETRY_VERSION, _repairs
    from viva.tools.shape import REPAIRS

    words = _repairs()
    assert set(words) == set(REPAIRS)
    assert all(phrase.strip() for phrase in words.values())
    # The correction is the defect and the repair, and nothing is appended to
    # either: what a model is told about a reply it must send again is one
    # reviewed template with two fields.
    template = promptstore.load(PROMPTS, RETRY_VERSION)
    assert "{problem}" in template and "{repair}" in template


# ------------------------------------------------------------ native planner

def test_native_planner_produces_a_cited_answer(registry):
    script = ChatScript([
        _turn([_shape_call(("Your checking holds {balance}, and that figure is "
                            "{trust} against the statement.",
                            [("balance", "money", "balance"),
                             ("trust", "grade")]))]),
        _turn([_call("query_ledger", {"entity": "balances",
                                      "filters": {"account": "chk"}},
                     call_id="c1")]),
        _turn([_call(FINAL_TOOL, {"bindings": {"balance": {"figure": "f1"},
                                               "trust": {"figure": "f1"}}},
                     call_id="c2")]),
    ])
    result = run("what is my checking balance?", NativePlanner(script), registry)
    assert result.answered and result.calls == 2
    # The grade is the ledger's, not the model's: the answer referred to an id,
    # and the grade travelled with the figure the tool emitted.
    assert result.grade == "corroborated"
    assert result.text == ("Your checking holds USD 600.00, and that figure is "
                           "corroborated against the statement.")
    # The system prompt opened the conversation and the question followed it.
    first = script.seen[0]["messages"]
    assert first[0]["role"] == "system" and "Viva" in first[0]["content"]
    assert first[-1] == {"role": "user",
                         "content": "what is my checking balance?"}
    # Before the shape is committed there is nothing else on the table: the
    # order the whole mechanism rests on is what the model is offered, not an
    # instruction it is asked to follow.
    assert [t["name"] for t in script.seen[0]["tools"]] == [SHAPE_TOOL]
    offered = {t["name"] for t in script.seen[1]["tools"]}
    assert {SHAPE_TOOL, FINAL_TOOL, "query_ledger"} <= offered
    assert FINAL_TOOL not in registry.names()
    assert SHAPE_TOOL not in registry.names()


def test_native_planner_threads_the_result_back_as_a_tool_message(registry):
    script = ChatScript([
        _turn([_shape_call(("Your balance is {total}.",
                            [("total", "money", "balance")]))]),
        _turn([_call("query_ledger", {"entity": "balances",
                                      "filters": {"account": "chk"}},
                     call_id="call-77")]),
        _turn([_call(FINAL_TOOL, {"bindings": {"total": {"figure": "f1"}}},
                     call_id="c2")]),
    ])
    run("balance?", NativePlanner(script), registry)
    second = script.seen[2]["messages"]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    # One per call the model made, in order: what the runner said about the
    # shape, then the read's own result.
    assert [m["tool_call_id"] for m in tool_msgs] == ["c0", "call-77"]
    assert "600.00" in tool_msgs[-1]["content"]


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
    # Two bad replies, and nothing after them: the refusal is not asked for.
    assert [e.parse_ok for e in planner.exchanges] == [False, False]


def test_native_malformed_arguments_are_corrected_as_the_calls_result(registry):
    script = ChatScript([
        _turn([_shape_call(ASKED_CLAUSE)]),
        _turn(raw_arguments="{not json"),
        _turn([_call(FINAL_TOOL, {"bindings": ASKED_BINDINGS}, call_id="c2")]),
    ])
    result = run(ASKED, NativePlanner(script), registry)
    assert result.answered
    # The bad call got the correction as its own tool result, keeping the
    # message protocol well-formed.
    second = script.seen[2]["messages"]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    assert "could not be used" in tool_msgs[-1]["content"]


def test_native_final_mixed_with_tool_calls_is_corrected(registry):
    """A turn commits its shape, then reads, then delivers. A reply that mixes
    a read with the delivery is not a choice between them; it is a step that
    cannot be run, and it costs a correction."""
    script = ChatScript([
        _turn([_shape_call(ASKED_CLAUSE)]),
        _turn([_call("query_ledger", {"entity": "balances", "filters": {}}),
               _call(FINAL_TOOL, {"bindings": {}}, call_id="c2")]),
        _turn([_call(FINAL_TOOL, {"bindings": ASKED_BINDINGS}, call_id="c3")]),
    ])
    result = run(ASKED, NativePlanner(script), registry)
    assert result.answered and result.calls == 1
    second = script.seen[2]["messages"]
    corrections = [m for m in second if m.get("role") == "tool"
                   and "could not be used" in m.get("content", "")]
    assert len(corrections) == 2


def _grade_hole_shape_call(call_id="c0"):
    """A shape a model plausibly sends and the check refuses: a hole holding a
    grade, declaring that the grade measures a count."""
    return _shape_call(("You have {many}, and that count is {trust}.",
                        [("many", "count", "count"),
                         ("trust", "grade", "count")]), call_id=call_id)


def _corrections_seen(messages):
    return [m.get("content") or "" for m in messages
            if "could not be used" in (m.get("content") or "")]


def test_a_refused_shape_is_told_which_field_to_take_out(registry):
    """A shape refused for a stray quantity is corrected with the words for
    `drop_the_quantity` and not with the protocol advice, and the exchange is
    recorded as a sentence authored and refused."""
    from viva.speak import _repairs
    from viva.tools.shape import DROP_THE_QUANTITY, PROTOCOL

    script = ChatScript([
        _turn([_grade_hole_shape_call()]),
        _turn([_shape_call(ASKED_CLAUSE, call_id="c1")]),
        _turn([_call(FINAL_TOOL, {"bindings": ASKED_BINDINGS}, call_id="c2")]),
    ])
    planner = NativePlanner(script)
    result = run(ASKED, planner, registry)
    assert result.answered, result.detail

    said = _corrections_seen(script.seen[1]["messages"])
    assert len(said) == 1
    assert _repairs()[DROP_THE_QUANTITY] in said[0]
    assert _repairs()[PROTOCOL] not in said[0]
    # And the exchange is on the record as a sentence authored and refused.
    assert [(e.authored_shape, e.parse_ok) for e in planner.exchanges] == [
        (True, False), (True, True), (False, True)]
    assert planner.exchanges[0].defect == DROP_THE_QUANTITY


def _denial_beside_a_figure_call(call_id="c0"):
    """A two-clause shape: one clause carrying a figure, and beside it a clause
    saying in the model's own words that the figure could not be established.
    The second declares no hole, so nothing could ever have dropped it."""
    return _shape_call(("You spent {total}.", [("total", "money", "spending")]),
                       ("I could not establish that figure from the records "
                        "available to me here.", []),
                       call_id=call_id)


def test_a_shape_whose_clause_rests_on_nothing_is_told_to_put_a_hole_in_it(
        registry):
    """The correction a model gets for a clause that rests on nothing. A clause
    declaring no hole draws the words for `hole_the_clause` and not the
    protocol advice, and the exchange is recorded as a sentence authored and
    refused — so the defect is countable, not merely absent."""
    from viva.speak import _repairs
    from viva.tools.shape import HOLE_THE_CLAUSE, PROTOCOL

    script = ChatScript([
        _turn([_denial_beside_a_figure_call()]),
        _turn([_shape_call(ASKED_CLAUSE, call_id="c1")]),
        _turn([_call(FINAL_TOOL, {"bindings": ASKED_BINDINGS}, call_id="c2")]),
    ])
    planner = NativePlanner(script)
    result = run(ASKED, planner, registry)
    assert result.answered, result.detail

    said = _corrections_seen(script.seen[1]["messages"])
    assert len(said) == 1
    assert _repairs()[HOLE_THE_CLAUSE] in said[0]
    assert _repairs()[PROTOCOL] not in said[0]
    # And the exchange is on the record as a sentence authored and refused.
    assert [(e.authored_shape, e.parse_ok) for e in planner.exchanges] == [
        (True, False), (True, True), (False, True)]
    assert planner.exchanges[0].defect == HOLE_THE_CLAUSE


def test_a_reply_that_broke_the_protocol_is_told_about_the_protocol(registry):
    """A reply that was not a tool call at all is corrected with the protocol
    words, and authors no shape."""
    from viva.speak import _repairs
    from viva.tools.shape import PROTOCOL

    script = ChatScript([_turn(text="Your balance looks fine to me."),
                         _turn(text="Really, it is fine.")])
    planner = NativePlanner(script)
    run("balance?", planner, registry)

    said = _corrections_seen(script.seen[1]["messages"])
    assert said and _repairs()[PROTOCOL] in said[0]
    assert [e.defect for e in planner.exchanges] == [PROTOCOL, PROTOCOL]
    assert not any(e.authored_shape for e in planner.exchanges)


def test_the_text_protocol_names_the_same_repair(registry):
    """The text protocol corrects the same defect with the same repair as the
    native path, and records the same defect tag."""
    from viva.speak import _repairs
    from viva.tools.shape import DROP_THE_QUANTITY, PROTOCOL

    steps = [
        _shape_block(("You have {many}, and that count is {trust}.",
                      [("many", "count", "count"), ("trust", "grade", "count")])),
        _shape_block(ASKED_CLAUSE),
        _bind_block(ASKED_BINDINGS),
    ]
    script = TextScript(steps)
    planner = TextPlanner(script)
    assert run(ASKED, planner, registry).answered
    assert _repairs()[DROP_THE_QUANTITY] in script.prompts[1]
    assert _repairs()[PROTOCOL] not in script.prompts[1]
    assert planner.exchanges[0].authored_shape
    assert planner.exchanges[0].defect == DROP_THE_QUANTITY


def test_a_delivery_the_gate_could_not_read_is_told_about_the_delivery(
        registry):
    """A delivery whose bindings are missing, or name more than one thing, is
    corrected with the repair for that defect rather than with the protocol
    words."""
    from viva.speak import _repairs
    from viva.tools.shape import BIND_EACH_HOLE, BIND_ONE_THING, PROTOCOL

    for defect, args in ((BIND_EACH_HOLE, {}),
                         (BIND_ONE_THING,
                          {"bindings": {"total": {"figure": "f1",
                                                  "entity": "chk"}}})):
        script = ChatScript([
            _turn([_shape_call(("Your balance is {total}.",
                                [("total", "money", "balance")]))]),
            _turn([_call(FINAL_TOOL, args, call_id="c1")]),
            _turn([_call(FINAL_TOOL, args, call_id="c2")]),
        ])
        planner = NativePlanner(script)
        run("balance?", planner, registry)
        said = _corrections_seen(script.seen[2]["messages"])
        assert said and _repairs()[defect] in said[-1], defect
        assert _repairs()[PROTOCOL] not in said[-1], defect
        assert planner.exchanges[1].defect == defect


def test_a_hole_that_named_the_wrong_quantity_is_told_to_change_it(registry):
    """A hole whose quantity its kind cannot be of is corrected with
    `choose_the_quantity`, never with `name_the_quantity`. The form makes this
    rarer and cannot make it impossible: nothing at the provider holds a model
    to the form."""
    from viva.speak import _repairs
    from viva.tools.shape import CHOOSE_THE_QUANTITY, NAME_THE_QUANTITY

    script = ChatScript([
        _turn([_shape_call(("You have {many}.", [("many", "count", "spending")]),
                           call_id="c0")]),
        _turn([_shape_call(ASKED_CLAUSE, call_id="c1")]),
        _turn([_call(FINAL_TOOL, {"bindings": ASKED_BINDINGS}, call_id="c2")]),
    ])
    planner = NativePlanner(script)
    assert run(ASKED, planner, registry).answered
    said = _corrections_seen(script.seen[1]["messages"])
    assert _repairs()[CHOOSE_THE_QUANTITY] in said[0]
    assert _repairs()[NAME_THE_QUANTITY] not in said[0]
    assert planner.exchanges[0].defect == CHOOSE_THE_QUANTITY


def test_native_transport_failure_refuses_model_unreachable(registry):
    result = run("balance?", NativePlanner(BrokenChat()), registry)
    assert not result.answered and result.refusal == "model_unreachable"
    assert "no answer" in result.detail


# -------------------------------------------------------------- text planner

def test_text_planner_produces_a_cited_answer(registry):
    steps = [
        _shape_block(("Your checking holds {balance}, {trust}.",
                      [("balance", "money", "balance"), ("trust", "grade")])),
        '```json\n{"tool": "query_ledger", "args": {"entity": "balances", '
        '"filters": {"account": "chk"}}}\n```',
        _bind_block({"balance": {"figure": "f1"}, "trust": {"figure": "f1"}}),
    ]
    script = TextScript(steps)
    result = run("what is my checking balance?", TextPlanner(script), registry)
    assert result.answered and result.grade == "corroborated"
    assert result.text == "Your checking holds USD 600.00, corroborated."
    # Each step's prompt carries the voice, the schemas on the table at that
    # point, and the results so far.
    assert "Viva" in script.prompts[0]
    named = [f'"name": "{t}"' for t in (SHAPE_TOOL, FINAL_TOOL)]
    assert named[0] in script.prompts[0] and named[1] not in script.prompts[0]
    assert named[1] in script.prompts[1]
    assert "600.00" in script.prompts[2]


def test_text_planner_corrects_once_then_refuses(registry):
    script = TextScript(["no json here at all", "still just prose"])

    planner = TextPlanner(script)
    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "unparseable"
    assert "could not be used" in script.prompts[1]
    # Two bad replies, and nothing after them: the refusal is not asked for.
    assert [e.parse_ok for e in planner.exchanges] == [False, False]


def test_text_transport_failure_refuses_model_unreachable(registry):
    result = run("balance?", TextPlanner(BrokenText()), registry)
    assert not result.answered and result.refusal == "model_unreachable"


# ------------------------------------------------------------------ sessions

def _answer_script():
    return ChatScript([
        _turn([_shape_call(("Your checking holds {balance}.",
                            [("balance", "money", "balance")]))]),
        _turn([_call("query_ledger", {"entity": "balances",
                                      "filters": {"account": "chk"}},
                     call_id="c1")]),
        _turn([_call(FINAL_TOOL, {"bindings": {"balance": {"figure": "f1"}}},
                     call_id="c2")]),
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
    assert len(log.events) == 3
    for event in log.events:
        assert event.body["phase"] == "speak"
        assert event.body["model"] == "pinned-model"
        assert event.body["input_mode"] == "native-tools"
        assert event.body["parse_ok"] is True
        payload = json.loads(event.body["response_text"])
        assert payload["request"] and payload["response"]
        assert payload["prompt_versions"]["speak"].startswith(f"{SPEAK_VERSION}@")
        assert payload["prompt_versions"]["tools"].startswith(
            f"{DESCRIPTIONS_VERSION}@")
        assert payload["verdict"]["answered"] is True
    assert log.events[0].body["doc_id"] == "speak:s-test:1:1"
    assert log.events[-1].body["doc_id"] == "speak:s-test:1:3"
    # What was said is kept as the structure it was, so a sentence can be shown
    # standing on what it stood on.
    kept = json.loads(log.events[-1].body["response_text"])
    assert kept["shape"]["clauses"][0]["slots"] == [{"name": "balance",
                                                     "type": "money",
                                                     "quantity": "balance"}]
    assert kept["bindings"] == {"balance": {"figure": "f1"}}


def test_the_capture_says_which_exchange_authored_a_sentence_and_what_broke(
        registry):
    """Each recorded exchange carries whether it was authoring the turn's
    sentence and, when it could not be used, the repair it was asked for —
    beside the `parse_ok` the capture already held."""
    from viva.tools.shape import DROP_THE_QUANTITY

    class LedgerLog:
        def __init__(self):
            self.events = []

        def append(self, event):
            self.events.append(event)

    log = LedgerLog()
    script = ChatScript([
        _turn([_grade_hole_shape_call()]),
        _turn([_shape_call(ASKED_CLAUSE, call_id="c1")]),
        _turn([_call(FINAL_TOOL, {"bindings": ASKED_BINDINGS}, call_id="c2")]),
    ])
    session = Session(registry, lambda prior: NativePlanner(script, prior),
                      ledger=log, model="pinned-model", session_id="s-test",
                      today=lambda: "2026-02-06")
    assert session.ask(ASKED).result.answered

    kept = [json.loads(e.body["response_text"]) for e in log.events]
    assert [k["authored_shape"] for k in kept] == [True, True, False]
    assert [k["defect"] for k in kept] == [DROP_THE_QUANTITY, "", ""]
    assert [e.body["parse_ok"] for e in log.events] == [False, True, True]


def test_a_turns_cost_is_the_sum_of_its_exchanges(registry):
    def factory(prior_turns):
        return NativePlanner(_answer_script(), prior_turns)

    session = Session(registry, factory, session_id="s-test",
                      today=lambda: "2026-02-06")
    turn = session.ask("what is my checking balance?")
    assert turn.cost_usd == pytest.approx(0.003)
    assert turn.tokens == (30, 15)


def test_text_planner_grants_its_correction_per_step_not_per_run(registry):
    steps = [
        "no json here at all",
        _shape_block(("Your checking holds {balance}.",
                      [("balance", "money", "balance")])),
        '```json\n{"tool": "query_ledger", "args": {"entity": "balances", '
        '"filters": {"account": "chk"}}}\n```',
        "prose again, later in the turn",
        _bind_block({"balance": {"figure": "f1"}}),
    ]
    result = run("balance?", TextPlanner(TextScript(steps)), registry)
    # The second malformed reply gets its own correction: a good step in
    # between resets the budget, matching the native planner.
    assert result.answered


def test_text_planner_corrects_a_reply_with_two_fenced_blocks(registry):
    steps = [
        _shape_block(ASKED_CLAUSE),
        '```json\n{"tool": "query_ledger", "args": {"entity": "balances", '
        '"filters": {}}}\n```\nfor example, and then really:\n'
        + _bind_block(ASKED_BINDINGS),
        _bind_block(ASKED_BINDINGS),
    ]
    script = TextScript(steps)
    result = run(ASKED, TextPlanner(script), registry)
    # Neither block ran — the ambiguous reply was corrected, not guessed at.
    assert result.answered and result.calls == 1
    assert "exactly one" in script.prompts[2]


# --------------------------------------------------- the gate and refusals

def _step_planner(shape, steps):
    """A planner that commits `shape`, then walks `steps` in order.

    Each step is either a runner step or a callable handed the results so far.
    """
    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        step = steps[min(len(done), len(steps) - 1)]
        return step(context["results"]) if callable(step) else step
    return planner


def test_a_number_echoed_by_a_refusal_cannot_ground_an_answer(registry):
    """A planner inventing a numeric account id gets a refusal that echoes the
    digits back. Nothing an answer can say is built from those digits: a
    refusal emits no figure, so there is no reference to bind, and the clause
    that wanted one is dropped."""
    shape = _shape_of(("Your savings holds {total}.",
                       [("total", "money", "balance")]))
    result = run("savings balance?",
                 _step_planner(shape, [
                     {"tool": "query_ledger",
                      "args": {"entity": "balances",
                               "filters": {"account": "854203"}}},
                     {"bindings": {"total": {"figure": "f1"}}}]),
                 registry)
    assert not result.answered
    assert result.refusal == "unknown_figure"


def test_a_date_echoed_by_an_ok_result_cannot_ground_an_answer(registry):
    """An ok result restating a planner-chosen `since` is an echo, not an
    assertion — the day it names is not one the run's results carry, so it
    cannot be said."""
    shape = _shape_of(("You have spent nothing since {when}.",
                       [("when", "date")]))
    result = run("what did I spend?",
                 _step_planner(shape, [
                     {"tool": "get_transparency",
                      "args": {"topic": "calls_spent", "since": "8542-01-01"}},
                     {"bindings": {"when": {"date": "8542-01-01"}}}]),
                 registry)
    assert not result.answered
    assert result.refusal == "unfounded_date"


def test_a_number_the_caller_typed_cannot_become_a_computed_figure(registry):
    """This replaces the check that compute's caller-supplied record ids and
    grades could not mint a figure. Those fields are gone: an operand is a
    figure id, so there is nothing left to plant. The refusal now lands on the
    first call, and it names what could have been used instead."""
    seen = {}
    shape = _shape_of(("You hold {total} in savings.",
                       [("total", "money", "balance")]))

    def note(results):
        seen["refusal"] = [r for r in results
                           if r["tool"] == "compute"][0]["refusal"]
        return {"bindings": {"total": {"figure": "f1"}}}

    result = run("savings?",
                 _step_planner(shape, [
                     {"tool": "compute",
                      "args": {"expression": "x",
                               "inputs": {"x": "854203.99"}}}, note]),
                 registry)
    assert seen["refusal"] == "bad_input"
    assert not result.answered and result.refusal == "unknown_figure"


def test_compute_over_a_fetched_figure_still_grounds(registry):
    """The legitimate chain — fetch, then compute over what was fetched, citing
    the result — must keep working, and its provenance is inherited rather than
    asserted by the caller."""
    shape = _shape_of(("Twice your checking balance would be {doubled}.",
                       [("doubled", "money", "balance")]))

    def compute_over(results):
        return {"tool": "compute",
                "args": {"expression": "x * 2",
                         "inputs": {"x": results[-1]["figures"][0]["id"]}}}

    def bind(results):
        return {"bindings": {"doubled": {"figure":
                                         results[-1]["figures"][0]["id"]}}}

    result = run("what is twice my balance?",
                 _step_planner(shape, [
                     {"tool": "query_ledger",
                      "args": {"entity": "balances",
                               "filters": {"account": "chk"}}},
                     compute_over, bind]),
                 registry)
    assert result.answered and result.grade == "corroborated"
    assert result.figures[0]["record_ids"] == ["chk", "doc-jan"]


def test_an_answer_may_quote_a_row_date_from_a_windowed_read(registry):
    """A row's own date is declarable and sayable even though the window filter
    that found it shares its year — the filter is scope the read reports, and
    the row's date is something the read asserts, carried on the figure for
    that row's amount."""
    shape = _shape_of(("On {when} you spent {amount} at {who}.",
                       [("when", "date"), ("amount", "money", "movement"),
                        ("who", "merchant")]))

    def bind(results):
        fig = results[-1]["figures"][0]
        return {"bindings": {"when": {"date": fig["dated"]},
                             "amount": {"figure": fig["id"]},
                             "who": {"entity": "m1"}}}

    result = run("what did I spend in January?",
                 _step_planner(shape, [
                     {"tool": "list_movements",
                      "args": {"filters": {"account": "chk",
                                           "window": {"from": "2026-01-01",
                                                      "to": "2026-01-31"}}}},
                     bind]),
                 registry)
    assert result.answered, result.detail
    assert "2026-01-05" in result.text


def test_a_refusals_record_ids_do_not_join_the_grounding_pool(registry):
    shape = _shape_of(("It rests on {which}.", [("which", "account")]))
    result = run("why?",
                 _step_planner(shape, [
                     {"tool": "get_provenance", "args": {"record_id": "999999"}},
                     {"bindings": {"which": {"entity": "a1"}}}]),
                 registry)
    assert not result.answered and result.refusal == "unknown_entity"


# ------------------------------------------ the closing call and the refusal

def test_the_closing_call_takes_the_reads_off_the_table(registry):
    """At exhaustion the model is not asked nicely to stop reading — the reads
    are gone, and the only thing it can do is speak."""
    script = ChatScript([
        _turn([_shape_call(ASKED_CLAUSE)]),
        _turn([_call("check_completeness", {})]),
        _turn([_call(FINAL_TOOL, {"bindings": ASKED_BINDINGS}, call_id="c2")]),
    ])
    result = run(ASKED, NativePlanner(script), registry, max_calls=2)
    assert result.answered
    assert result.text == "You asked about 40.00 (your figure)."
    offered = {t["name"] for t in script.seen[-1]["tools"]}
    assert offered == {FINAL_TOOL}
    # The call it made and could not be given is answered, not left dangling —
    # and reaching this step cost no extra model call: the budget was spent the
    # moment the transcript filled, so the terminator-only ask came at once.
    last = script.seen[-1]["messages"][-1]
    assert last["role"] == "tool" and last["tool_call_id"] == "c1"
    assert "no tool calls left" in last["content"]
    assert len(script.seen) == 3


def test_the_model_is_told_how_many_calls_it_has_left(registry):
    """The runner computing a budget nobody is shown is not a budget. Both
    modalities must put it where the model actually reads."""
    script = ChatScript([
        _turn([_shape_call(ASKED_CLAUSE)]),
        _turn([_call("check_completeness", {})]),
        _turn([_call(FINAL_TOOL, {"bindings": ASKED_BINDINGS}, call_id="c2")]),
    ])
    run(ASKED, NativePlanner(script), registry, max_calls=4)
    threaded = [m for m in script.seen[-1]["messages"] if m["role"] == "tool"]
    assert json.loads(threaded[-1]["content"])["calls_remaining"] == 2

    text = TextScript([
        _shape_block(ASKED_CLAUSE),
        '```json\n{"tool": "check_completeness", "args": {}}\n```',
        _bind_block(ASKED_BINDINGS),
    ])
    run(ASKED, TextPlanner(text), registry, max_calls=4)
    assert "Tool calls left in this turn: 4" in text.prompts[0]
    assert "Tool calls left in this turn: 3" in text.prompts[1]
    assert "Tool calls left in this turn: 2" in text.prompts[2]


def test_the_voice_does_not_promise_a_field_that_is_not_always_there(registry):
    """The remaining budget rides back with each result, so on the native path
    the first ask carries none. A prompt naming `calls_remaining` as something
    every context holds tells the model to read a field that is not there, and
    an instruction that is false where it is first read is worse than absent."""
    script = ChatScript([
        _turn([_shape_call(ASKED_CLAUSE)]),
        _turn([_call(FINAL_TOOL, {"bindings": ASKED_BINDINGS}, call_id="c2")]),
    ])
    run(ASKED, NativePlanner(script), registry)
    assert "calls_remaining" not in json.dumps(script.seen[0]["messages"])
    assert "calls_remaining" not in promptstore.load(PROMPTS, SPEAK_VERSION)


def test_the_text_protocol_teaches_the_shape_the_code_actually_accepts(registry):
    """A protocol prompt that teaches a superseded terminator costs every text
    answer its one correction before it can succeed.

    The old mismatch was that the protocol taught one reply shape while
    rendering the terminator into its tools list as another. There is now one
    reply shape — a named call with its arguments — so what the list says and
    what the protocol asks for cannot drift apart."""
    text = TextScript([_shape_block(ASKED_CLAUSE),
                       _bind_block(ASKED_BINDINGS)])
    run(ASKED, TextPlanner(text), registry)
    for taught in text.prompts:
        assert '{{"tool": "<tool name>", "args": {{}}}}' not in taught
        assert '{"tool": "<tool name>", "args": {}}' in taught
        assert "an example, never a value you may" in taught
    # The shape schema is what is on the table first, and it is described by
    # the file rather than by a template nobody filled.
    assert f'"name": "{SHAPE_TOOL}"' in text.prompts[0]
    assert '"clauses"' in text.prompts[0]
    assert '"bindings"' in text.prompts[1]
    assert '"stipulated"' not in text.prompts[1]


def test_a_refusal_is_the_packs_reviewed_sentence_for_its_tag(registry):
    """A refusal is spoken from words written long before the turn that needed
    them, chosen by the machine's own tag. Nothing composes a sentence at the
    moment of refusing, so the one moment a model can see exactly why it fell
    short is not the moment it is asked to write about it."""
    script = ChatScript([
        _turn([_shape_call(("It is {total}.", [("total", "money", "balance")]))]),
        _turn([_call(FINAL_TOOL, {"bindings": {"total": {"figure": "f9"}}})]),
    ])
    planner = NativePlanner(script)
    result = run("balance?", planner, registry)
    assert not result.answered
    assert result.refusal == "unknown_figure"        # the tag, for the log
    assert result.text == persona.moment("refusal_unknown_figure")
    assert "unknown_figure" not in result.text       # the prose, for the person
    # And it cost nothing: two model calls made the turn, and refusing bought
    # no third.
    assert len(planner.exchanges) == 2


def test_a_planner_is_never_asked_to_speak_a_refusal(registry):
    """No planner offers a way to compose one, so a refused turn cannot spend a
    call on prose however a planner is written."""
    for planner in (NativePlanner(BrokenChat()), TextPlanner(BrokenText())):
        assert not hasattr(planner, "compose_refusal")
        result = run("balance?", planner, registry)
        assert result.refusal == "model_unreachable"
        assert result.text == persona.moment("refusal_model_unreachable")
        assert len(planner.exchanges) == 1


def test_a_tag_the_machine_does_not_know_is_not_spoken_as_one(registry):
    """A planner inventing a tag has no reviewed words behind it, and inventing
    some at that moment is the thing this closes. The turn ends as a planner
    that could not be followed, and what the planner said stays in the record
    rather than reaching the person."""
    def planner(context):
        return {"refusal": "a_tag_nobody_declared", "text": "my own words"}

    result = run("balance?", planner, registry)
    assert not result.answered and result.refusal == "bad_plan"
    assert result.text == persona.moment("refusal_bad_plan")
    assert result.detail == "my own words"


# ------------------------------------------------------------- the footer

def test_the_footer_shows_each_figure_the_way_the_sentence_showed_it(
        registry, capsys):
    """The footer is read by the same person as the sentence one line above it.
    A figure written twice under two decisions is two conventions on one
    screen — an amount hedged in the sentence and bare underneath it, a count
    written as money, a proportion without its sign. There is only one
    decision: the footer prints the words the hole was filled with."""
    from viva.speak import Turn, _print_turn
    from viva.tools.shape import Clause, Shape, Slot

    shape = Shape(clauses=(
        Clause(text="Your balance is {total}.",
               slots=(Slot("total", "money", "balance"),)),
        Clause(text="I hold this many: {many}.",
               slots=(Slot("many", "count", "count"),)),
        Clause(text="A seventh of it is {part}, a share of {share}.",
               slots=(Slot("part", "money", "balance"),
                      Slot("share", "rate", "ratio_of_balance"))),
    ))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != SHAPE_TOOL]
        if not done:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        if len(done) == 1:
            return {"tool": "compute",
                    "args": {"expression": "a / 7", "inputs": {"a": "f1"}}}
        if len(done) == 2:
            return {"tool": "compute",
                    "args": {"expression": "a / b",
                             "inputs": {"a": "f3", "b": "f1"}}}
        return {"bindings": {"total": {"figure": "f1"},
                             "many": {"figure": "f2"},
                             "part": {"figure": "f3"},
                             "share": {"figure": "f4"}}}

    result = run("what is my balance?", planner, registry, locale="en-US")
    assert result.answered, result.detail
    _print_turn(Turn(question="what is my balance?", result=result))
    footer = [line for line in capsys.readouterr().out.splitlines()
              if line.startswith("  f")]
    for figure in result.figures:
        line = next(ln for ln in footer if ln.startswith(f"  {figure['id']} "))
        assert result.written[
            next(n for n, r in result.bindings.items()
                 if r.get("figure") == figure["id"])] in line
    # Which is to say: the hedge travels — whatever kind of magnitude it is
    # about — a count is a count, and a proportion keeps the sign that says what
    # it is.
    said = {line.split()[0]: line.split(maxsplit=2)[1:] for line in footer}
    assert said["f3"][0] == "about", "a rounded amount is bare under a hedged one"
    assert said["f2"][0] == "1", "a count is written as an amount"
    assert said["f4"][0] == "about", (
        "a rounded proportion is bare under a hedged amount")
    assert said["f4"][1].split()[0].endswith("%"), (
        "a proportion loses what makes it one")


def test_a_figure_two_holes_refer_to_stands_under_the_sentence_once(
        registry, capsys):
    """A sentence that states an amount and then says how well that same amount
    is stood behind refers to one figure twice. It is one figure: it is cited
    once, and the footer shows both the words it was written as — an amount and
    a grade — rather than whichever hole happened to be read last."""
    from viva.speak import Turn, _print_turn
    from viva.tools.shape import Clause, Shape, Slot

    shape = Shape(clauses=(
        Clause(text="Your balance is {total}.",
               slots=(Slot("total", "money", "balance"),)),
        Clause(text="That figure is {how_well}.",
               slots=(Slot("how_well", "grade"),)),
    ))

    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        if not [r for r in context["results"] if r["tool"] != SHAPE_TOOL]:
            return {"tool": "query_ledger", "args": {"entity": "balances"}}
        return {"bindings": {"total": {"figure": "f1"},
                             "how_well": {"figure": "f1"}}}

    result = run("what is my balance?", planner, registry, locale="en-US")
    assert result.answered, result.detail
    assert [f["id"] for f in result.figures] == ["f1"], (
        "one figure filling two holes is cited once, not once per hole")

    _print_turn(Turn(question="what is my balance?", result=result))
    footer = [line for line in capsys.readouterr().out.splitlines()
              if line.startswith("  f1 ")]
    assert len(footer) == 1, "one figure, one line under the sentence"
    assert result.written["total"] in footer[0], (
        "the amount the sentence stated is missing from the line that is "
        "supposed to make it checkable")
    assert result.written["how_well"] in footer[0]


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
             "tool_calls": [_shape_call(("Your balance is {total}.",
                                         [("total", "money", "balance")]))]})),
        _Response(_chat_payload(
            {"role": "assistant", "content": None,
             "tool_calls": [_call("query_ledger",
                                  {"entity": "balances",
                                   "filters": {"account": "chk"}},
                                  call_id="c1")]})),
        _Response(_chat_payload(
            {"role": "assistant", "content": None,
             "tool_calls": [_call(FINAL_TOOL,
                                  {"bindings": {"total": {"figure": "f1"}}},
                                  call_id="c2")]})),
    ])
    planner = NativePlanner(adapter)
    result = run("balance?", planner, registry)
    assert result.answered
    # The first exchange's captured request holds the two messages actually
    # sent, untouched by everything the planner appended afterwards.
    first = planner.exchanges[0].request["messages"]
    assert [m["role"] for m in first] == ["system", "user"]
    assert len(sent[0]["messages"]) == 2 and len(sent[-1]["messages"]) == 6


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
