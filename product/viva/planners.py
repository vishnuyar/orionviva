"""Viva speaks: a live model plans read-tool calls and composes the answer.

The runner and its citation gate already hold the law — every figure in an
answer must be grounded in this run's tool results. This module supplies the
planners that put a real model behind that contract, a session that carries a
conversation across turns, and the capture that records every exchange in the
vault.

Two planners, one contract:

- ``NativePlanner`` speaks the chat-completions tool-calling protocol through
  an adapter's ``converse`` — the primary path for every OpenAI-compatible
  endpoint, hosted or local.
- ``TextPlanner`` teaches the same steps as a fenced JSON block over a plain
  completion — the degradation path for any model the ``extract`` contract can
  reach.

Both present two schemas beside the registry's verbs, and which of them is on
the table is decided by the runner rather than by either planner:
``commit_shape``, through which a turn's sentence is authored before anything
is read, and ``deliver_answer``, through which each of that sentence's holes is
bound to something the reads established. Neither is registered — neither
executes anything; one opens a turn and one ends it. A malformed reply gets
exactly one correction, naming the defect and the one change that answers it,
then the turn refuses with a machine tag. A transport failure refuses as
``model_unreachable``. Nothing raises to the person.

One shape of last word exists besides an ordinary answer. When the call budget
runs out, the runner asks once more with only the terminator on the table, so a
turn already holding grounded figures can still deliver what its shape asked
for. A refusal is not the model's to write: it is a reviewed sentence in the
persona pack chosen by the machine tag, so no planner is asked to compose one
and a refused turn spends nothing.

A session keeps prior turns as context so follow-ups resolve ("it", "that
account"), but the gate's grounding is per-turn: any figure the model wants to
repeat must be re-fetched by a tool in the current turn.

Every model exchange is appended to the ledger as a ``ReadRecorded`` event,
``phase="speak"``, carrying the verbatim request and response, the prompt
versions in force, the pinned and endpoint-reported model, tokens and cost.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass

from vivacore import promptstore, versions

from .tools.registry import PACKAGE, PROMPTS
from .tools.runner import FINAL_TOOL, SHAPE_TOOL
from .tools.shape import (BIND_EACH_HOLE, BIND_ONE_THING, MAGNITUDE_TYPES,
                          MEASURED_TYPES, PLAIN_TYPES, PROTOCOL, SCOPES,
                          Problem, quantities_of, read_shape)

SPEAK_VERSION = versions.active(PACKAGE, "speak")
FINAL_VERSION = versions.active(PACKAGE, "speak_final")
SHAPE_VERSION = versions.active(PACKAGE, "speak_shape")
PROTOCOL_VERSION = versions.active(PACKAGE, "speak_protocol")
RETRY_VERSION = versions.active(PACKAGE, "speak_retry")
REPAIRS_VERSION = versions.active(PACKAGE, "speak_repairs")
CLOSING_VERSION = versions.active(PACKAGE, "speak_closing")

# The alternatives a hole is described to a model as: one per kind that holds a
# magnitude, each pinned to that kind and requiring a quantity out of the ones
# that kind may be of and a scope out of the sets a figure can be taken over,
# plus one for the kinds that hold no magnitude, which has neither field at
# all. Every enum is read from the check that reads the shape back, so a
# combination the form offers is a combination the check takes.
#
# The scope is required rather than offered: a field a model may leave out is a
# check a model can make disappear, which is instruction where this wants
# structure. It is offered on the kinds that hold a measurement, which is not
# every kind that carries a quantity: a value the person supposed says what it
# is of and was taken over nothing, so the form has no field for a set it was
# measured over and the check refuses one. It takes a set of axes rather than
# one, because a sentence narrows on as many as it names, and each is named at
# most once: an axis given twice is one claim written twice.
#
# `additionalProperties` is what makes a hole match one alternative and not
# two: without it on the plain hole, a hole carrying a quantity satisfies that
# alternative as well as its own, and an alternation satisfied twice is
# satisfied by nothing.
def _magnitude_hole(kind: str) -> dict:
    properties = {"name": {"type": "string"},
                  "type": {"type": "string", "enum": [kind]},
                  "quantity": {"type": "string",
                               "enum": list(quantities_of(kind))}}
    required = ["name", "type", "quantity"]
    if kind in MEASURED_TYPES:
        properties["scope"] = {"type": "array", "minItems": 1,
                               "uniqueItems": True,
                               "items": {"type": "string",
                                         "enum": list(SCOPES)}}
        required.append("scope")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_PLAIN_HOLE = {
    "type": "object",
    "properties": {"name": {"type": "string"},
                   "type": {"type": "string", "enum": list(PLAIN_TYPES)}},
    "required": ["name", "type"],
    "additionalProperties": False,
}

HOLE_ALTERNATIVES = [_magnitude_hole(kind) for kind in MAGNITUDE_TYPES]
HOLE_ALTERNATIVES.append(_PLAIN_HOLE)

# The shape: clauses of words with typed holes, and nothing else. The enums are
# the vocabulary itself, so a hole kind the code does not know cannot be
# described to a model — and the same for what a hole says its number measures,
# which is the other half of a magnitude's declaration. Each clause's holes are
# at least one, as the form: what refuses a clause with none is the constructor
# that builds it, and this describes the same thing where a model can read it.
SHAPE_PARAMS = {
    "type": "object",
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "slots": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"oneOf": HOLE_ALTERNATIVES}},
                },
                "required": ["text", "slots"]}},
    },
    "required": ["clauses"],
}

# The delivery: one reference per hole, and no field a value could arrive in.
# `bindings` is an open object because its keys are the hole names the shape
# chose, which no schema written in advance can enumerate.
FINAL_PARAMS = {
    "type": "object",
    "properties": {"bindings": {"type": "object"}},
    "required": ["bindings"],
}

# One correction per malformed reply, then the turn refuses. Each correction
# spends a model call.
MAX_CORRECTIONS = 1

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _speak_prompt(today: str = "") -> str:
    """The system message: the pinned persona file with today's date filled in.

    The date is a `str.format` field of the template, so the version recorded
    against a turn still resolves to the bytes that were sent. ``today``
    defaults to the day the call is made, and is a parameter so a test does not
    depend on the day it runs."""
    return promptstore.load(PROMPTS, SPEAK_VERSION).format(
        today=today or datetime.date.today().isoformat())


def _final_schema(tool: str = FINAL_TOOL, version: str = "") -> dict:
    return {"name": tool,
            "description": promptstore.load(PROMPTS, version or FINAL_VERSION),
            "parameters": FINAL_PARAMS}


def _shape_schema() -> dict:
    return {"name": SHAPE_TOOL,
            "description": promptstore.load(PROMPTS, SHAPE_VERSION),
            "parameters": SHAPE_PARAMS}


def _table(context: dict) -> list:
    """What may be called at this point in the turn.

    The order is enforced here rather than asked for: until a shape is
    committed, committing one is the only thing on the table, so a read cannot
    precede the sentence it is meant to fill."""
    if not context.get("shaped"):
        return [_shape_schema()]
    if context.get("final_call"):
        return [_final_schema()]
    # A shape stays available so it can be weakened when the reads contradict
    # what it assumed; it can never be widened.
    return list(context.get("tools") or []) + [_shape_schema(), _final_schema()]


def _repairs() -> dict:
    """Each repair a malformed reply can be asked to make, by its tag.

    One line per repair in the versioned file: the tag, then the words. The
    check that finds a defect names the repair; the words for it are reviewed
    here, so the same defect always asks for the same change."""
    found = {}
    for line in promptstore.load(PROMPTS, REPAIRS_VERSION).splitlines():
        tag, mark, words = line.partition(":")
        if mark and words.strip():
            found[tag.strip()] = words.strip()
    return found


def _correction(problem: str) -> str:
    """What the model is told about a reply that could not be used: the defect,
    and the one change that answers it. Advice about the protocol is the repair
    for a reply that broke the protocol, and appears for nothing else."""
    repair = _repairs().get(getattr(problem, "repair", PROTOCOL), "")
    return promptstore.load(PROMPTS, RETRY_VERSION).format(
        problem=problem, repair=repair)


def _shape_step(args: dict) -> tuple[dict | None, str]:
    """The runner step a shape call means, or the problem with it. Where a
    clause writes a digit in its own words, this is where the model is told
    so — before any tool has run."""
    shape, problem = read_shape(args if isinstance(args, dict) else None)
    if shape is None:
        return None, problem
    return {"shape": shape}, ""


def _final_step(args: dict) -> tuple[dict | None, str]:
    """The runner step a delivery means, or the problem with it."""
    if not isinstance(args, dict) or not isinstance(args.get("bindings"), dict):
        return None, Problem(f"{FINAL_TOOL} needs a 'bindings' object naming "
                             "each hole in the shape", BIND_EACH_HOLE)
    for name, reference in args["bindings"].items():
        if not isinstance(reference, dict) or len(reference) != 1:
            return None, Problem(f"the binding for {name!r} must name exactly "
                                 "one thing, as {\"figure\": \"f1\"}",
                                 BIND_ONE_THING)
    return {"bindings": args["bindings"]}, ""


@dataclass
class Exchange:
    """One model round-trip, kept verbatim for capture."""

    modality: str                 # "native-tools" | "text-protocol"
    request: dict
    response: dict
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    resolved_model: str = ""
    parse_ok: bool = True
    parse_error: str = ""
    # Whether this reply tried to author the turn's sentence, and — when a
    # reply could not be used — the machine's name for the change it was asked
    # to make, one of `shape.REPAIRS`. With `parse_ok` they are what a count of
    # shapes authored and refused, and of why, is made of.
    authored_shape: bool = False
    defect: str = ""


class NativePlanner:
    """Drives a tool-calling conversation through ``adapter.converse``.

    Holds the message history for one turn; the runner supplies each tool
    result through its context, and this planner threads it back to the model
    as the protocol's tool message."""

    modality = "native-tools"

    def __init__(self, adapter, prior_turns=()):
        self._adapter = adapter
        self._prior = list(prior_turns)
        self._messages: list[dict] = []
        self._tools: list[dict] = []
        self._queued: list[tuple[str, str, dict]] = []   # (call id, name, args)
        self._awaiting: str | None = None
        self._started = False
        # Whether the reply last read tried to commit a shape, however it went.
        self._authoring = False
        self.exchanges: list[Exchange] = []

    def _start(self, context: dict) -> None:
        self._messages = [{"role": "system", "content": _speak_prompt()}]
        for question, said in self._prior:
            self._messages.append({"role": "user", "content": question})
            self._messages.append({"role": "assistant", "content": said})
        self._messages.append({"role": "user", "content": context["question"]})
        self._started = True

    def __call__(self, context: dict) -> dict:
        if not self._started:
            self._start(context)
        self._tools = _table(context)
        if context.get("final_call"):
            self._close(context)
        else:
            if self._awaiting is not None:
                # The remaining budget rides back with each tool result, so
                # the model reads it rather than counting what it has spent.
                result = dict(context["results"][-1],
                              calls_remaining=context.get("calls_remaining"))
                self._messages.append({"role": "tool",
                                       "tool_call_id": self._awaiting,
                                       "content": json.dumps(result)})
                self._awaiting = None
            if self._queued:
                return self._emit()

        corrections = 0
        while True:
            from vivacore.models import AdapterError
            try:
                turn = self._adapter.converse(self._messages, self._tools)
            except AdapterError as e:
                self.exchanges.append(Exchange(
                    modality=self.modality, request={}, response={},
                    parse_ok=False, parse_error=str(e)))
                return {"refusal": "model_unreachable",
                        "text": "I could not reach the model that speaks for "
                                "me, so I have no answer rather than a "
                                "guessed one."}
            exchange = Exchange(
                modality=self.modality, request=turn.request,
                response=turn.response, input_tokens=turn.input_tokens,
                output_tokens=turn.output_tokens, cost_usd=turn.cost_usd,
                latency_s=turn.latency_s, resolved_model=turn.resolved_model)
            self.exchanges.append(exchange)
            self._messages.append(turn.message)

            step, problem = self._read(turn)
            exchange.authored_shape = self._authoring
            if step is not None:
                return step
            exchange.parse_ok = False
            exchange.parse_error = str(problem)
            exchange.defect = getattr(problem, "repair", PROTOCOL)
            corrections += 1
            if corrections > MAX_CORRECTIONS:
                return {"refusal": "unparseable",
                        "text": "The model's replies never became a usable "
                                "step, so I am refusing rather than "
                                "improvising an answer."}
            self._correct(turn, problem)

    def _read(self, turn) -> tuple[dict | None, str]:
        """The runner step a model reply means, or the problem with it."""
        self._authoring = False
        if not turn.tool_calls:
            return None, Problem("the reply was text, but a turn proceeds only "
                                 "by a tool call or deliver_answer")
        parsed: list[tuple[str, str, dict]] = []
        for call in turn.tool_calls:
            fn = (call or {}).get("function") or {}
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError as e:
                return None, Problem(
                    f"the arguments for '{name}' are not valid JSON ({e})")
            if not isinstance(args, dict):
                return None, Problem(
                    f"the arguments for '{name}' must be an object")
            parsed.append((str((call or {}).get("id") or ""), name, args))
        names = [name for _, name, _ in parsed]
        for terminator in (SHAPE_TOOL, FINAL_TOOL):
            if terminator in names and len(parsed) > 1:
                return None, Problem(f"{terminator} must be the only call in "
                                     "its reply — a turn commits its shape, "
                                     "then reads, then delivers")
        if names == [SHAPE_TOOL]:
            self._authoring = True
            step, problem = _shape_step(parsed[0][2])
            if step is not None:
                # The runner answers a committed shape with whether it took it,
                # and the protocol needs that call answered like any other.
                self._awaiting = parsed[0][0]
            return step, problem
        if names == [FINAL_TOOL]:
            return _final_step(parsed[0][2])
        self._queued = parsed
        return self._emit(), ""

    def _emit(self) -> dict:
        call_id, name, args = self._queued.pop(0)
        self._awaiting = call_id
        return {"tool": name, "args": args}

    def _close(self, context: dict) -> None:
        """The budget is spent: the reads come off the table and only the
        terminator is offered. Every tool call the model has outstanding is
        answered with the closing note, because the protocol needs each one
        answered before another message can follow."""
        closing = promptstore.load(PROMPTS, CLOSING_VERSION)
        outstanding = ([self._awaiting] if self._awaiting is not None else [])
        outstanding += [call_id for call_id, _, _ in self._queued]
        self._awaiting, self._queued = None, []
        for call_id in outstanding:
            self._messages.append({"role": "tool", "tool_call_id": call_id,
                                   "content": closing})
        if not outstanding:
            self._messages.append({"role": "user", "content": closing})

    def _correct(self, turn, problem: str) -> None:
        """Answer the bad reply so the protocol stays well-formed: each of its
        tool calls gets the correction as its result; a plain-text reply gets
        it as the next user message."""
        text = _correction(problem)
        if turn.tool_calls:
            for call in turn.tool_calls:
                self._messages.append({"role": "tool",
                                       "tool_call_id": str((call or {}).get("id")
                                                           or ""),
                                       "content": text})
        else:
            self._messages.append({"role": "user", "content": text})


class TextPlanner:
    """The degradation path: the same steps taught as one fenced JSON block
    over a plain completion, for any model ``extract`` can reach."""

    modality = "text-protocol"

    def __init__(self, adapter, prior_turns=()):
        self._adapter = adapter
        self._prior = list(prior_turns)
        self._problem = None
        self._corrections = 0
        # Whether the reply last read tried to commit a shape, however it went.
        self._authoring = False
        self.exchanges: list[Exchange] = []

    def _prompt(self, context: dict, notes=(), tools=None) -> str:
        template = promptstore.load(PROMPTS, PROTOCOL_VERSION)
        tools = _table(context) if tools is None else list(tools)
        conversation = [{"question": q, "viva": a} for q, a in self._prior]
        notes = list(notes)
        if self._problem is not None:
            notes.append(_correction(self._problem))
        if context.get("final_call"):
            notes.append(promptstore.load(PROMPTS, CLOSING_VERSION))
        problem = ("\n" + "\n".join(notes) + "\n") if notes else ""
        return template.format(
            system=_speak_prompt(), tools=json.dumps(tools, indent=1),
            conversation=json.dumps(conversation),
            results=json.dumps(context.get("results") or []),
            calls_remaining=context.get("calls_remaining", 0),
            question=context["question"], problem=problem)

    def __call__(self, context: dict) -> dict:
        while True:
            prompt = self._prompt(context)
            from vivacore.models import AdapterError
            try:
                result = self._adapter.extract([], prompt)
            except AdapterError as e:
                self.exchanges.append(Exchange(
                    modality=self.modality, request={}, response={},
                    parse_ok=False, parse_error=str(e)))
                return {"refusal": "model_unreachable",
                        "text": "I could not reach the model that speaks for "
                                "me, so I have no answer rather than a "
                                "guessed one."}
            exchange = Exchange(
                modality=self.modality, request=result.request,
                response=result.response, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens, cost_usd=result.cost_usd,
                latency_s=result.latency_s, resolved_model=result.resolved_model)
            self.exchanges.append(exchange)

            step, problem = self._read(result.text)
            exchange.authored_shape = self._authoring
            if step is not None:
                # A usable step ends the malformed streak: the correction
                # budget is per step, exactly as it is for the native path.
                self._problem = None
                self._corrections = 0
                return step
            exchange.parse_ok = False
            exchange.parse_error = str(problem)
            exchange.defect = getattr(problem, "repair", PROTOCOL)
            self._corrections += 1
            if self._corrections > MAX_CORRECTIONS:
                return {"refusal": "unparseable",
                        "text": "The model's replies never became a usable "
                                "step, so I am refusing rather than "
                                "improvising an answer."}
            self._problem = problem

    def _read(self, text: str) -> tuple[dict | None, str]:
        self._authoring = False
        blocks = _FENCED.findall(text or "")
        if len(blocks) > 1:
            # The protocol demands exactly one fenced block; more than one is
            # a malformed step rather than a choice between them.
            return None, Problem(f"the reply carried {len(blocks)} fenced JSON "
                                 "blocks, and it must carry exactly one")
        raw = blocks[0] if blocks else (text or "").strip()
        try:
            step = json.loads(raw)
        except json.JSONDecodeError:
            return None, Problem("the reply carried no parseable JSON block")
        if not isinstance(step, dict):
            return None, Problem("the JSON block must be an object")
        if "tool" not in step:
            return None, Problem("the JSON block names no 'tool'; every reply "
                                 "calls exactly one of the tools you were given")
        args = step.get("args") or {}
        if not isinstance(args, dict):
            return None, Problem("'args' must be an object")
        name = str(step["tool"])
        if name == SHAPE_TOOL:
            self._authoring = True
            return _shape_step(args)
        if name == FINAL_TOOL:
            return _final_step(args)
        return {"tool": name, "args": args}, ""




__all__ = [
    "FINAL_TOOL", "SHAPE_TOOL",
    "SPEAK_VERSION", "FINAL_VERSION", "SHAPE_VERSION", "PROTOCOL_VERSION",
    "RETRY_VERSION", "REPAIRS_VERSION", "CLOSING_VERSION", "FINAL_PARAMS",
    "SHAPE_PARAMS", "MAX_CORRECTIONS", "Exchange", "NativePlanner",
    "TextPlanner", "_magnitude_hole", "_speak_prompt", "_final_schema",
    "_shape_schema", "_table", "_repairs", "_correction", "_shape_step",
    "_final_step",
]
