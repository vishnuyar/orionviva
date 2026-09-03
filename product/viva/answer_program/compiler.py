"""One-call meaning selection, then deterministic pre-read program lowering."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from vivacore import promptstore, versions

from ..tools.registry import PACKAGE, PROMPTS
from .intents import (SEMANTIC_REQUEST_VERSION, SemanticFamilyRegistry,
                      SemanticOutcome)
from .schema import AnswerProgram, ContractError, QuestionContext
from .validate import ValidationDefect, ValidationResult

COMPILER_VERSION = versions.active(PACKAGE, "semantic_request")
REPAIR_VERSION = versions.active(PACKAGE, "semantic_request_retry")
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
    failure_code: str = ""
    defect: dict = field(default_factory=dict)
    usage_reported: bool = False
    provider_adapter: str = ""
    live_provider: bool = False


@dataclass(frozen=True)
class CompilationResult:
    program: AnswerProgram | None
    validation: ValidationResult | None
    exchanges: tuple[CompileExchange, ...]
    semantic_outcome: SemanticOutcome | None = None
    failure_tag: str = ""
    failure_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.program is not None and self.validation is not None


class _ReplyError(ContractError):
    def __init__(self, message: str, exchange: CompileExchange, raw=None, *,
                 failure_code="semantic_reply_invalid"):
        super().__init__(message)
        self.exchange = exchange
        self.raw = raw
        self.failure_code = failure_code


def _contract_failure_code(error: Exception) -> str:
    """Classify a rejected semantic object without retaining its contents."""
    message = str(error)
    rules = (
        ("unsupported semantic request version", "request_version_mismatch"),
        ("semantic request fields differ", "request_field_set_mismatch"),
        ("semantic output fields differ", "outcome_field_set_mismatch"),
        ("semantic output has an unknown outcome", "unknown_outcome"),
        ("semantic request used a different entity catalog",
         "entity_catalog_digest_mismatch"),
        ("semantic request used a different catalog",
         "semantic_catalog_digest_mismatch"),
        ("semantic parameters differ", "parameter_field_set_mismatch"),
        ("semantic parameters must be an object", "parameters_not_object"),
        ("parameter_sources must prove", "parameter_source_set_mismatch"),
        ("has invalid source", "invalid_parameter_source"),
        ("quotes text not in its source", "ungrounded_parameter_quote"),
        ("was not selected from its catalog", "unknown_catalog_selection"),
        ("differs from its source quote", "parameter_quote_mismatch"),
        ("must select a catalog id or a grounded phrase",
         "entity_reference_shape_mismatch"),
        ("without catalog_selection grounding",
         "entity_reference_grounding_mismatch"),
        ("without verbatim grounding", "entity_reference_grounding_mismatch"),
        ("requested_claims must be", "invalid_answer_effects"),
        ("invalid semantic clarification", "invalid_clarification"),
        ("invalid semantic assumption", "invalid_assumption"),
    )
    return next((code for fragment, code in rules if fragment in message),
                "semantic_contract_invalid")


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
    """Select meaning once and lower it against one data-blind manifest."""

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
        self._families = SemanticFamilyRegistry()

    def set_entity_catalog(self, catalog: dict) -> None:
        """Bind this turn's bounded vault-label catalog before interpretation."""
        self._families = SemanticFamilyRegistry(catalog)

    def _provider_exchange(self, exchange):
        from vivacore.models import AnthropicAdapter, OpenAICompatAdapter
        adapter_type = type(self._adapter)
        exchange.provider_adapter = (
            f"{adapter_type.__module__}.{adapter_type.__qualname__}")
        exchange.live_provider = adapter_type in {
            AnthropicAdapter, OpenAICompatAdapter}
        return exchange

    def compile(self, context: QuestionContext) -> CompilationResult:
        self.exchanges = []
        defects = ()
        previous = None
        last_validation = None
        semantic = None
        for attempt in range(self._policy.max_model_attempts):
            try:
                provider_raw, exchange = self._call(context, defects, previous)
            except _ReplyError as error:
                self.exchanges.append(error.exchange)
                previous = error.raw
                defects = (ValidationDefect("invalid_semantic_contract", "$",
                                            str(error)),)
                error.exchange.parse_ok = False
                error.exchange.parse_error = str(error)
                error.exchange.failure_code = error.failure_code
                error.exchange.defect = defects[0].to_dict()
                continue
            except Exception as error:
                from vivacore.models import AdapterError
                if not isinstance(error, AdapterError):
                    raise
                self.exchanges.append(CompileExchange(
                    modality=self.modality, request={}, response={},
                    parse_ok=False, parse_error=str(error),
                    failure_code="model_unreachable",
                    defect={"tag": "model_unreachable", "path": "$",
                            "message": str(error), "repairable": False}))
                return CompilationResult(
                    None, None, tuple(self.exchanges), None,
                    "model_unreachable", str(error))
            if (self.expected_resolved_model
                    and exchange.resolved_model != self.expected_resolved_model):
                exchange.parse_ok = False
                exchange.parse_error = "provider returned a different model profile"
                exchange.failure_code = "model_profile_mismatch"
                exchange.defect = {
                    "tag": "model_profile_mismatch", "path": "$",
                    "message": exchange.parse_error, "repairable": False}
                self.exchanges.append(exchange)
                return CompilationResult(
                    None, None, tuple(self.exchanges), None,
                    "model_profile_mismatch", exchange.parse_error)
            self.exchanges.append(exchange)
            previous = provider_raw
            try:
                raw = self._families.materialize_model_output(provider_raw)
                semantic = self._families.parse(raw, context)
            except (ContractError, TypeError, ValueError) as error:
                defects = (ValidationDefect("invalid_semantic_contract", "$",
                                            str(error)),)
                exchange.parse_ok = False
                exchange.parse_error = str(error)
                exchange.failure_code = _contract_failure_code(error)
                exchange.defect = defects[0].to_dict()
                continue
            if semantic.kind == "unsupported":
                return CompilationResult(
                    None, None, tuple(self.exchanges), semantic,
                    "unsupported_family",
                    str((semantic.detail or {}).get("requested_family") or ""))
            program = self._families.lower(semantic, self._manifest)
            checked = self._validator.validate(program)
            last_validation = checked
            if checked.ok:
                return CompilationResult(program, checked, tuple(self.exchanges),
                                         semantic)
            defects = tuple(checked.defects)
            exchange.parse_ok = False
            exchange.parse_error = "; ".join(item.message for item in defects)
            exchange.failure_code = "invalid_lowered_program"
            exchange.defect = {"tag": "invalid_lowered_program",
                               "defects": [item.to_dict() for item in defects]}
            return CompilationResult(
                None, checked, tuple(self.exchanges), semantic,
                "invalid_lowered_program", exchange.parse_error)
        detail = "; ".join(item.message for item in defects)
        return CompilationResult(
            None, last_validation, tuple(self.exchanges), semantic,
            "invalid_semantic_request", detail)

    def _call(self, context, defects, previous):
        if self.modality == "native-structured":
            return self._native(context, defects, previous)
        return self._text(context, defects, previous)

    def _inputs(self, context) -> dict:
        sent = {name: getattr(context, name) for name in
                ("question", "prior_turns", "today", "locale",
                 "currency_convention")}
        sent["prior_turns"] = [{"question": q, "answer": a}
                               for q, a in context.prior_turns]
        return {"context": sent,
                "catalog": self._families.model_catalog(),
                "catalog_digest": self._families.catalog_digest,
                "entity_catalog": self._families.entity_catalog,
                "entity_catalog_digest": self._families.entity_catalog_digest,
                "schema": self._families.model_output_schema()}

    def _prompt(self, context) -> str:
        inputs = self._inputs(context)
        return promptstore.load(PROMPTS, COMPILER_VERSION).format(
            **{key: json.dumps(value, sort_keys=True, separators=(",", ":"))
               for key, value in inputs.items()})

    def _repair(self, defects) -> str:
        return promptstore.load(PROMPTS, REPAIR_VERSION).format(
            defects=json.dumps([item.to_dict() for item in defects], sort_keys=True,
                               separators=(",", ":")),
            accepted=json.dumps(self._families.model_output_schema(), sort_keys=True,
                                separators=(",", ":")))

    def interpretations(self, outcome):
        return self._families.interpretations(outcome)

    def clarification_candidates(self, outcome):
        return self._families.clarification_candidates(outcome)

    def _native(self, context, defects, previous):
        messages = [{"role": "system", "content": self._prompt(context)},
                    {"role": "user", "content": json.dumps(
                        self._inputs(context)["context"],
                                                             sort_keys=True)}]
        if defects:
            messages.extend([
                {"role": "assistant", "content": json.dumps(previous,
                                                               sort_keys=True)},
                {"role": "user", "content": self._repair(defects)},
            ])
        tools = list(self._families.model_tools())
        turn = self._adapter.converse(messages, tools)
        exchange = self._provider_exchange(_exchange(self.modality, turn))
        calls = list(getattr(turn, "tool_calls", ()) or ())
        if len(calls) != 1:
            raise _ReplyError("semantic reply must call one selection tool",
                              exchange, failure_code="selection_tool_count")
        fn = (calls[0] or {}).get("function") or {}
        name = str(fn.get("name") or "")
        known = {tool["name"] for tool in tools}
        if name not in known:
            raise _ReplyError("compiler reply called an unknown function", exchange,
                              failure_code="unknown_selection_tool")
        try:
            raw = json.loads(fn.get("arguments") or "")
        except json.JSONDecodeError as error:
            raise _ReplyError(f"compiler arguments are not JSON: {error}",
                              exchange,
                              failure_code="selection_arguments_not_json") from None
        if not isinstance(raw, dict):
            raise _ReplyError("semantic selection must be an object", exchange,
                              raw, failure_code="selection_arguments_not_object")
        if name.startswith("select_"):
            family_id = name[len("select_"):]
            raw = {"request_version": SEMANTIC_REQUEST_VERSION,
                   "catalog_digest": self._families.catalog_digest,
                   "entity_catalog_digest":
                       self._families.entity_catalog_digest,
                   "outcome": "request", "family": family_id, **raw}
        else:
            outcome = {"semantic_clarification": "clarify",
                       "semantic_assumption": "needs_assumption",
                       "semantic_outside_domain": "outside_domain",
                       "semantic_unsupported": "unsupported"}[name]
            raw = {"request_version": SEMANTIC_REQUEST_VERSION,
                   "outcome": outcome, **raw}
        return raw, exchange

    def _text(self, context, defects, previous):
        prompt = self._prompt(context)
        if defects:
            prompt += "\n\n" + self._repair(defects)
            prompt += "\n\nRejected semantic output:\n" + json.dumps(
                previous, sort_keys=True)
        result = self._adapter.extract([], prompt)
        exchange = self._provider_exchange(_exchange(self.modality, result))
        text = str(getattr(result, "text", "") or "").strip()
        blocks = _FENCED.findall(text)
        if len(blocks) > 1:
            raise _ReplyError("compiler reply carried more than one JSON block",
                              exchange, text,
                              failure_code="multiple_json_blocks")
        try:
            raw = json.loads(blocks[0] if blocks else text)
        except json.JSONDecodeError as error:
            raise _ReplyError(f"compiler reply is not JSON: {error}", exchange,
                              text, failure_code="reply_not_json") from None
        if not isinstance(raw, dict):
            raise _ReplyError("semantic selection must be an object", exchange,
                              raw, failure_code="selection_arguments_not_object")
        return raw, exchange


def compiler_output_json_schema(registry=None):
    return (registry or SemanticFamilyRegistry()).output_schema()


__all__ = ["AnswerProgramCompiler", "CompilationResult", "CompileExchange",
           "COMPILER_VERSION", "REPAIR_VERSION",
           "compiler_output_json_schema"]
