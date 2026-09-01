"""One-call semantic compilation, with one pre-read structural repair."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from vivacore import promptstore, versions

from ..tools.registry import PACKAGE, PROMPTS
from .intents import (KNOWN_INTENT_REQUEST_VERSION, KnownIntentRegistry,
                      intent_request_json_schema)
from .schema import AnswerProgram, ContractError, QuestionContext, program_json_schema
from .validate import ValidationDefect, ValidationResult

COMPILER_VERSION = versions.active(PACKAGE, "answer_program")
REPAIR_VERSION = versions.active(PACKAGE, "answer_program_retry")
COMPILE_TOOL = "compile_answer_program"
INTENT_TOOL_PREFIX = "compile_intent_"
_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class CompileExchange:
    modality: str
    request: object
    response: object
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    resolved_model: str = ""
    parse_ok: bool = True
    parse_error: str = ""
    defect: dict = field(default_factory=dict)
    usage_reported: bool = False


@dataclass(frozen=True)
class CompilationResult:
    program: AnswerProgram | None
    validation: ValidationResult | None
    exchanges: tuple[CompileExchange, ...]
    failure_tag: str = ""
    failure_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.program is not None and self.validation is not None


class _ReplyError(ContractError):
    def __init__(self, message: str, exchange: CompileExchange, raw=None):
        super().__init__(message)
        self.exchange = exchange
        self.raw = raw


def _usage_reported(response: object) -> bool:
    if not isinstance(response, dict):
        return False
    usage = response.get("usage")
    return isinstance(usage, dict) and any(key in usage for key in (
        "prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"))


def _exchange(modality: str, result) -> CompileExchange:
    return CompileExchange(
        modality=modality, request=getattr(result, "request", {}),
        response=getattr(result, "response", {}),
        input_tokens=getattr(result, "input_tokens", 0),
        output_tokens=getattr(result, "output_tokens", 0),
        cost_usd=getattr(result, "cost_usd", 0.0),
        latency_s=getattr(result, "latency_s", 0.0),
        resolved_model=getattr(result, "resolved_model", ""),
        usage_reported=_usage_reported(getattr(result, "response", {})))


class AnswerProgramCompiler:
    """Compile against one manifest; never holds a registry or projection."""

    def __init__(self, adapter, validator, manifest, policy, *, modality="",
                 expected_resolved_model=""):
        self._adapter = adapter
        self._validator = validator
        self._manifest = manifest
        self._policy = policy
        self.modality = modality or (
            "native-structured" if hasattr(adapter, "converse") else "text-json")
        self.expected_resolved_model = str(expected_resolved_model or "")
        self.exchanges: list[CompileExchange] = []
        self._intents = KnownIntentRegistry()

    def compile(self, context: QuestionContext) -> CompilationResult:
        self.exchanges = []
        defect = None
        previous = None
        last_validation = None
        for attempt in range(self._policy.max_model_attempts):
            try:
                raw, exchange = self._call(context, defect, previous)
            except _ReplyError as error:
                self.exchanges.append(error.exchange)
                previous = error.raw
                defect = ValidationDefect("invalid_contract", "$", str(error))
                error.exchange.parse_ok = False
                error.exchange.parse_error = str(error)
                error.exchange.defect = defect.to_dict()
                continue
            except Exception as error:
                from vivacore.models import AdapterError
                if not isinstance(error, AdapterError):
                    raise
                self.exchanges.append(CompileExchange(
                    modality=self.modality, request={}, response={},
                    parse_ok=False, parse_error=str(error),
                    defect={"tag": "model_unreachable", "path": "$",
                            "message": str(error), "repairable": False}))
                return CompilationResult(None, None, tuple(self.exchanges),
                                         "model_unreachable", str(error))
            if (self.expected_resolved_model
                    and exchange.resolved_model != self.expected_resolved_model):
                exchange.parse_ok = False
                exchange.parse_error = "provider returned a different model profile"
                exchange.defect = {
                    "tag": "model_profile_mismatch", "path": "$",
                    "message": exchange.parse_error, "repairable": False}
                self.exchanges.append(exchange)
                return CompilationResult(None, None, tuple(self.exchanges),
                                         "model_profile_mismatch",
                                         exchange.parse_error)
            self.exchanges.append(exchange)
            previous = raw
            try:
                program = self._program(raw)
            except (ContractError, TypeError, ValueError) as error:
                defect = ValidationDefect("invalid_contract", "$", str(error))
                exchange.parse_ok = False
                exchange.parse_error = str(error)
                exchange.defect = defect.to_dict()
                continue
            checked = self._validator.validate(program)
            last_validation = checked
            if checked.ok:
                return CompilationResult(program, checked, tuple(self.exchanges))
            defect = next((item for item in checked.defects if item.repairable),
                          checked.defects[0] if checked.defects else None)
            exchange.parse_ok = False
            exchange.parse_error = defect.message if defect else ""
            exchange.defect = defect.to_dict() if defect else {}
            if defect is None or not defect.repairable:
                return CompilationResult(None, checked, tuple(self.exchanges),
                                         "invalid_program",
                                         defect.message if defect else "")
        return CompilationResult(None, last_validation, tuple(self.exchanges),
                                 "invalid_program",
                                 defect.message if defect else "")

    def _call(self, context, defect, previous):
        if self.modality == "native-structured":
            return self._native(context, defect, previous)
        return self._text(context, defect, previous)

    def _inputs(self, context) -> dict:
        return {"context": context.to_dict(),
                "manifest": self._manifest.to_dict(),
                "policy": self._policy.to_dict(),
                "schema": compiler_output_json_schema(self._intents)}

    def _prompt(self, context) -> str:
        inputs = self._inputs(context)
        return promptstore.load(PROMPTS, COMPILER_VERSION).format(
            **{key: json.dumps(value, sort_keys=True, separators=(",", ":"))
               for key, value in inputs.items()})

    @staticmethod
    def _repair(defect) -> str:
        return promptstore.load(PROMPTS, REPAIR_VERSION).format(
            tag=defect.tag, path=defect.path, message=defect.message,
            accepted=json.dumps(compiler_output_json_schema(), sort_keys=True,
                                separators=(",", ":")))

    def _native(self, context, defect, previous):
        messages = [{"role": "system", "content": self._prompt(context)},
                    {"role": "user", "content": json.dumps(context.to_dict(),
                                                             sort_keys=True)}]
        if defect is not None:
            messages.extend([
                {"role": "assistant", "content": json.dumps(previous,
                                                               sort_keys=True)},
                {"role": "user", "content": self._repair(defect)},
            ])
        tools = [{"name": COMPILE_TOOL,
                  "description": "Compile one complete open-ended AnswerProgram.",
                  "parameters": program_json_schema()}]
        tools.extend({"name": INTENT_TOOL_PREFIX + intent_id,
                      "description": self._intents.get(intent_id).description,
                      "parameters": self._intents.get(intent_id).parameter_schema}
                     for intent_id in self._intents.ids)
        turn = self._adapter.converse(messages, tools)
        exchange = _exchange(self.modality, turn)
        calls = list(getattr(turn, "tool_calls", ()) or ())
        if len(calls) != 1:
            raise _ReplyError(
                "compiler reply must call compile_answer_program once", exchange)
        fn = (calls[0] or {}).get("function") or {}
        name = str(fn.get("name") or "")
        if name != COMPILE_TOOL and not name.startswith(INTENT_TOOL_PREFIX):
            raise _ReplyError("compiler reply called an unknown function", exchange)
        try:
            raw = json.loads(fn.get("arguments") or "")
        except json.JSONDecodeError as error:
            raise _ReplyError(f"compiler arguments are not JSON: {error}",
                              exchange) from None
        if not isinstance(raw, dict):
            raise _ReplyError("compiled AnswerProgram must be an object", exchange,
                              raw)
        if name.startswith(INTENT_TOOL_PREFIX):
            intent_id = name[len(INTENT_TOOL_PREFIX):]
            if intent_id not in self._intents.ids:
                raise _ReplyError("compiler reply called an unknown intent", exchange,
                                  raw)
            raw = {"request_version": KNOWN_INTENT_REQUEST_VERSION,
                   "capability_manifest_digest": self._manifest.digest,
                   "intent_id": intent_id, "parameters": raw}
        return raw, exchange

    def _program(self, raw):
        if raw.get("request_version") != KNOWN_INTENT_REQUEST_VERSION:
            return AnswerProgram.from_dict(raw)
        if set(raw) != {"request_version", "capability_manifest_digest",
                       "intent_id", "parameters"}:
            raise ContractError("known intent request has unknown or missing fields")
        if raw["capability_manifest_digest"] != self._manifest.digest:
            raise ContractError("known intent request used a different manifest")
        return self._intents.instantiate(str(raw["intent_id"]),
                                         raw["parameters"], self._manifest)

    def _text(self, context, defect, previous):
        prompt = self._prompt(context)
        if defect is not None:
            prompt += "\n\n" + self._repair(defect)
            prompt += "\n\nRejected program:\n" + json.dumps(previous,
                                                                  sort_keys=True)
        result = self._adapter.extract([], prompt)
        exchange = _exchange(self.modality, result)
        text = str(getattr(result, "text", "") or "").strip()
        blocks = _FENCED.findall(text)
        if len(blocks) > 1:
            raise _ReplyError("compiler reply carried more than one JSON block",
                              exchange, text)
        try:
            raw = json.loads(blocks[0] if blocks else text)
        except json.JSONDecodeError as error:
            raise _ReplyError(f"compiler reply is not JSON: {error}", exchange,
                              text) from None
        if not isinstance(raw, dict):
            raise _ReplyError("compiled AnswerProgram must be an object", exchange,
                              raw)
        return raw, exchange


def compiler_output_json_schema(registry=None):
    return {"oneOf": [program_json_schema(),
                      intent_request_json_schema(registry)]}


__all__ = ["AnswerProgramCompiler", "CompilationResult", "CompileExchange",
           "COMPILER_VERSION", "REPAIR_VERSION", "COMPILE_TOOL",
           "INTENT_TOOL_PREFIX"]
