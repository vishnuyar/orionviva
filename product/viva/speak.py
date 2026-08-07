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
exactly one correction naming the problem, then the turn refuses with a machine
tag. A transport failure refuses as ``model_unreachable``. Nothing raises to
the person.

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
import uuid
from dataclasses import dataclass, field, replace

from vivacore import promptstore, versions

from .tools.registry import PACKAGE, PROMPTS
from .tools.runner import (DEFAULT_MAX_CALLS, FINAL_TOOL, SHAPE_TOOL,
                           RunResult, run)
from .quantity import KINDS as QUANTITY_KINDS
from .tools.shape import SLOT_TYPES, read_shape

SPEAK_VERSION = versions.active(PACKAGE, "speak")
FINAL_VERSION = versions.active(PACKAGE, "speak_final")
SHAPE_VERSION = versions.active(PACKAGE, "speak_shape")
PROTOCOL_VERSION = versions.active(PACKAGE, "speak_protocol")
RETRY_VERSION = versions.active(PACKAGE, "speak_retry")
CLOSING_VERSION = versions.active(PACKAGE, "speak_closing")

# The shape: clauses of words with typed holes, and nothing else. The type
# enum is the vocabulary itself, so a hole kind the code does not know cannot
# be described to a model — and the same for what a hole says its number
# measures, which is the other half of a magnitude's declaration.
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
                        "items": {"type": "object",
                                  "properties": {
                                      "name": {"type": "string"},
                                      "type": {"type": "string",
                                               "enum": list(SLOT_TYPES)},
                                      "quantity": {
                                          "type": "string",
                                          "enum": list(QUANTITY_KINDS)}},
                                  "required": ["name", "type"]}},
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


def _speak_prompt() -> str:
    return promptstore.load(PROMPTS, SPEAK_VERSION)


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


def _correction(problem: str) -> str:
    return promptstore.load(PROMPTS, RETRY_VERSION).format(problem=problem)


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
        return None, (f"{FINAL_TOOL} needs a 'bindings' object naming each hole "
                      "in the shape")
    for name, reference in args["bindings"].items():
        if not isinstance(reference, dict) or len(reference) != 1:
            return None, (f"the binding for {name!r} must name exactly one "
                          "thing, as {\"figure\": \"f1\"}")
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
            if step is not None:
                return step
            exchange.parse_ok = False
            exchange.parse_error = problem
            corrections += 1
            if corrections > MAX_CORRECTIONS:
                return {"refusal": "unparseable",
                        "text": "The model's replies never became a usable "
                                "step, so I am refusing rather than "
                                "improvising an answer."}
            self._correct(turn, problem)

    def _read(self, turn) -> tuple[dict | None, str]:
        """The runner step a model reply means, or the problem with it."""
        if not turn.tool_calls:
            return None, ("the reply was text, but a turn proceeds only by a "
                          "tool call or deliver_answer")
        parsed: list[tuple[str, str, dict]] = []
        for call in turn.tool_calls:
            fn = (call or {}).get("function") or {}
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError as e:
                return None, f"the arguments for '{name}' are not valid JSON ({e})"
            if not isinstance(args, dict):
                return None, f"the arguments for '{name}' must be an object"
            parsed.append((str((call or {}).get("id") or ""), name, args))
        names = [name for _, name, _ in parsed]
        for terminator in (SHAPE_TOOL, FINAL_TOOL):
            if terminator in names and len(parsed) > 1:
                return None, (f"{terminator} must be the only call in its "
                              "reply — a turn commits its shape, then reads, "
                              "then delivers")
        if names == [SHAPE_TOOL]:
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
        self._problem = ""
        self._corrections = 0
        self.exchanges: list[Exchange] = []

    def _prompt(self, context: dict, notes=(), tools=None) -> str:
        template = promptstore.load(PROMPTS, PROTOCOL_VERSION)
        tools = _table(context) if tools is None else list(tools)
        conversation = [{"question": q, "viva": a} for q, a in self._prior]
        notes = list(notes)
        if self._problem:
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
            if step is not None:
                # A usable step ends the malformed streak: the correction
                # budget is per step, exactly as it is for the native path.
                self._problem = ""
                self._corrections = 0
                return step
            exchange.parse_ok = False
            exchange.parse_error = problem
            self._corrections += 1
            if self._corrections > MAX_CORRECTIONS:
                return {"refusal": "unparseable",
                        "text": "The model's replies never became a usable "
                                "step, so I am refusing rather than "
                                "improvising an answer."}
            self._problem = problem

    def _read(self, text: str) -> tuple[dict | None, str]:
        blocks = _FENCED.findall(text or "")
        if len(blocks) > 1:
            # The protocol demands exactly one fenced block; more than one is
            # a malformed step rather than a choice between them.
            return None, (f"the reply carried {len(blocks)} fenced JSON "
                          "blocks, and it must carry exactly one")
        raw = blocks[0] if blocks else (text or "").strip()
        try:
            step = json.loads(raw)
        except json.JSONDecodeError:
            return None, "the reply carried no parseable JSON block"
        if not isinstance(step, dict):
            return None, "the JSON block must be an object"
        if "tool" not in step:
            return None, ("the JSON block names no 'tool'; every reply calls "
                          "exactly one of the tools you were given")
        args = step.get("args") or {}
        if not isinstance(args, dict):
            return None, "'args' must be an object"
        name = str(step["tool"])
        if name == SHAPE_TOOL:
            return _shape_step(args)
        if name == FINAL_TOOL:
            return _final_step(args)
        return {"tool": name, "args": args}, ""


@dataclass
class Turn:
    """One question and how it went: the gated result plus the turn's cost."""

    question: str
    result: RunResult
    exchanges: list = field(default_factory=list)

    @property
    def said(self) -> str:
        return self.result.text if self.result.answered else (
            self.result.text or self.result.refusal)

    @property
    def cost_usd(self) -> float:
        return sum(e.cost_usd for e in self.exchanges)

    @property
    def tokens(self) -> tuple[int, int]:
        return (sum(e.input_tokens for e in self.exchanges),
                sum(e.output_tokens for e in self.exchanges))


class Session:
    """A conversation: turns share context, figures never carry over.

    Each turn is a fresh gated run whose planner receives the prior questions
    and answers as context. When a ledger is supplied, every model exchange is
    appended as a ``ReadRecorded`` event, ``phase="speak"``, so the vault holds
    what left the machine and what came back, verbatim."""

    def __init__(self, registry, planner_factory, ledger=None, model: str = "",
                 max_calls: int = DEFAULT_MAX_CALLS,
                 session_id: str = "", today=None, locale: str = ""):
        self._registry = registry
        self._planner_factory = planner_factory
        self._ledger = ledger
        self._model = model
        self._max_calls = max_calls
        # How a figure is written is a property of this person's paperwork, and
        # it reaches the renderer the same way it reaches the question queue.
        self._locale = locale
        self._session_id = session_id or uuid.uuid4().hex[:12]
        self._today = today or (lambda: datetime.date.today().isoformat())
        self.turns: list[Turn] = []

    def ask(self, question: str) -> Turn:
        prior = [(t.question, t.said) for t in self.turns]
        planner = self._planner_factory(prior)
        result = run(question, planner, self._registry,
                     max_calls=self._max_calls, locale=self._locale)
        turn = Turn(question=question, result=result,
                    exchanges=list(getattr(planner, "exchanges", [])))
        self.turns.append(turn)
        if self._ledger is not None:
            self._record(turn, planner)
        return turn

    def _record(self, turn: Turn, planner) -> None:
        from .ledger.events import read_recorded
        stamps = {"speak": f"{SPEAK_VERSION}@"
                           f"{promptstore.digest(PROMPTS, SPEAK_VERSION)}",
                  "tools": f"{self._registry.descriptions_version}@"
                           f"{promptstore.digest(PROMPTS, self._registry.descriptions_version)}"}
        n = len(self.turns)
        for i, ex in enumerate(turn.exchanges, 1):
            payload = {"prompt_versions": stamps,
                       "modality": ex.modality,
                       "resolved_model": ex.resolved_model,
                       "question": turn.question,
                       "request": ex.request, "response": ex.response,
                       # What was said, as the structure it was. A sentence can
                       # then be shown standing on what it stood on, and the
                       # shapes a real conversation actually needs accumulate.
                       "shape": turn.result.shape,
                       "bindings": turn.result.bindings,
                       "verdict": {"answered": turn.result.answered,
                                   "refusal": turn.result.refusal,
                                   "calls": turn.result.calls}}
            self._ledger.append(read_recorded(
                doc_id=f"speak:{self._session_id}:{n}:{i}",
                model=self._model, prompt_version=SPEAK_VERSION,
                input_mode=ex.modality,
                response_text=json.dumps(payload),
                cost_usd=ex.cost_usd, input_tokens=ex.input_tokens,
                output_tokens=ex.output_tokens, parse_ok=ex.parse_ok,
                parse_error=ex.parse_error or None,
                occurred_at=self._today(), phase="speak"))


def speak_spec():
    """The pinned model the conversation speaks through, or None when no model
    is configured.

    Configured per field: ``VIVA_SPEAK_<FIELD>`` if set, else the matching
    ``VIVA_MODEL_<FIELD>``, so the voice and the document reader can be
    different models. Pointing ``VIVA_SPEAK_BASE_URL`` at a local server
    (Ollama, LM Studio) with ``VIVA_SPEAK_KEY_ENV=none`` keeps the whole
    conversation on the machine."""
    import os

    def cfg(fld, default=None):
        return (os.environ.get(f"VIVA_SPEAK_{fld}")
                or os.environ.get(f"VIVA_MODEL_{fld}" if fld != "MODEL"
                                  else "VIVA_MODEL")
                or default)

    model = cfg("MODEL")
    if not model:
        return None
    from vivacore.models import ModelSpec
    key_env = cfg("KEY_ENV", "OPENROUTER_API_KEY")
    return ModelSpec(
        name="viva-speak", adapter=cfg("ADAPTER", "openai-compatible"),
        model=model, base_url=cfg("BASE_URL"),
        api_key_env=None if (key_env or "").lower() in ("", "none") else key_env)


def planner_factory(spec):
    """Planner constructor for one spec: native tool-calling where the adapter
    speaks it, the text protocol otherwise or when ``VIVA_SPEAK_PROTOCOL=text``
    forces it — the per-model reversibility the modality contract promised."""
    import os

    from vivacore.models import adapter_for

    forced_text = os.environ.get("VIVA_SPEAK_PROTOCOL", "").strip() == "text"
    # A truncated reply is a malformed step to correct, never a fragment to
    # stitch, so continuation stays off for both modalities.
    adapter = adapter_for(replace(spec, max_continuations=0))
    native = hasattr(adapter, "converse") and not forced_text

    def make(prior_turns):
        if native:
            return NativePlanner(adapter, prior_turns)
        return TextPlanner(adapter, prior_turns)

    return make


def max_calls_from_env() -> int:
    import os

    raw = os.environ.get("VIVA_SPEAK_MAX_CALLS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_MAX_CALLS


def _shown(result: RunResult) -> dict:
    """Figure id -> the words that figure was written as in the sentence.

    The footer does not decide a second time how a figure becomes words. It
    shows what the hole this figure filled was written as, so the number under
    the sentence is the number in the sentence — its hedge, its currency, its
    conventions and its kind all the same, because they are the same string."""
    return {str(reference["figure"]): result.written.get(name, "")
            for name, reference in result.bindings.items()
            if "figure" in reference}


def _print_turn(turn: Turn) -> None:
    result = turn.result
    print()
    if result.answered:
        print(f"Viva: {result.text}")
        if result.grade:
            print(f"  grade: {result.grade}")
        elif result.figures:
            print("  grade: none — " + ", ".join(
                sorted({f.get("kind", "") for f in result.figures})))
        shown = _shown(result)
        for figure in result.figures:
            ids = ", ".join(map(str, figure.get("record_ids", [])))
            grade = figure.get("grade", "") or figure.get("kind", "")
            parts = [str(figure.get("id"))]
            if shown.get(str(figure.get("id"))):
                parts.append(shown[str(figure.get("id"))])
            if grade:
                parts.append(f"({grade})")
            print("  " + " ".join(parts)
                  + f"  {figure.get('what', '')}  <- {ids}")
        for gap in result.gaps:
            print(f"  gap: {gap['name']} ({gap['type']}) — nothing bound")
    else:
        print(f"Viva: {result.text or 'I have no answer.'}")
        print(f"  refused: {result.refusal}")
    tokens_in, tokens_out = turn.tokens
    print(f"  [{result.calls} tool call(s), {len(turn.exchanges)} model "
          f"call(s), {tokens_in}/{tokens_out} tokens, "
          f"${turn.cost_usd:.4f}]")


def main() -> None:
    import os
    import pathlib
    import sys

    from .env import load_dotenv
    from .logs import configure as configure_logging

    load_dotenv()
    configure_logging()

    spec = speak_spec()
    if spec is None:
        raise SystemExit("No model configured. Set VIVA_SPEAK_MODEL or "
                         "VIVA_MODEL (with ADAPTER / BASE_URL / KEY_ENV as "
                         "needed), or put them in ./.env.")

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR",
                               os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")

    from .tools import default_registry
    from .vault import Vault

    from .env import locale_from_env

    locale = locale_from_env()
    vault = Vault.open(vault_dir, passphrase)
    registry = default_registry(vault.ledger.projection(), locale)
    session = Session(registry, planner_factory(spec), ledger=vault.ledger,
                      model=spec.model, max_calls=max_calls_from_env(),
                      locale=locale)

    questions = list(sys.argv[1:])
    if questions:
        for question in questions:
            print(f"you: {question}")
            _print_turn(session.ask(question))
        return

    print("Ask about your money; a blank line ends the conversation.")
    while True:
        try:
            question = input("you: ").strip()
        except EOFError:
            break
        if not question:
            break
        _print_turn(session.ask(question))


if __name__ == "__main__":
    main()
