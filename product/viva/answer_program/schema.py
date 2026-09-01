"""Immutable public-internal contracts for the answer-program runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import json
import pathlib
from typing import Any

from vivacore import versions

from ..query.schema import financial_query_json_schema
from ..tools.shape import (MAGNITUDE_TYPES, MEASURED_TYPES, PLAIN_TYPES, SCOPES,
                           Shape, quantities_of, read_shape)

QUESTION_CONTEXT_VERSION = "question-context-v1"
# The program schema and compiler prompt are separately versioned release
# artifacts. Improving model instructions must not silently mint a new wire
# contract.
ANSWER_PROGRAM_VERSION = versions.active(
    pathlib.Path(__file__).resolve().parent.parent, "answer_program_schema")
RESOURCE_POLICY_VERSION = "answer-resource-policy-v1"
CAPABILITY_MANIFEST_VERSION = "capability-manifest-v1"

PROGRAM_MODES = ("answer", "clarify", "needs_assumption", "outside_domain")
NODE_KINDS = ("tool_read", "resolve_entity", "compute", "financial_query",
              "conditional")
IMPORTANCE = ("required", "supporting", "optional")
CARDINALITIES = ("one", "all")
REFERENCE_KINDS = ("figure", "entity", "period", "date", "date_of", "read",
                   "read_figures", "supposed")


class ContractError(ValueError):
    """A versioned object that cannot enter the answer runtime."""


def _strict(data: dict, allowed, required, where: str) -> None:
    if not isinstance(data, dict):
        raise ContractError(f"{where} must be an object")
    unknown = sorted(set(data) - set(allowed))
    missing = sorted(set(required) - set(data))
    if unknown:
        raise ContractError(f"{where} has unknown fields: {', '.join(unknown)}")
    if missing:
        raise ContractError(f"{where} is missing: {', '.join(missing)}")


def _strings(value, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ContractError(f"{where} must be an array of strings")
    return tuple(value)


@dataclass(frozen=True)
class QuestionContext:
    question: str
    prior_turns: tuple[tuple[str, str], ...] = ()
    today: str = ""
    locale: str = ""
    currency_convention: str = ""
    capability_manifest_version: str = CAPABILITY_MANIFEST_VERSION
    capability_manifest_digest: str = ""
    program_version: str = ANSWER_PROGRAM_VERSION
    shape_version: str = ""
    resource_policy_version: str = RESOURCE_POLICY_VERSION
    context_version: str = QUESTION_CONTEXT_VERSION

    def to_dict(self) -> dict:
        return {
            "context_version": self.context_version,
            "question": self.question,
            "prior_turns": [{"question": q, "answer": a}
                            for q, a in self.prior_turns],
            "today": self.today,
            "locale": self.locale,
            "currency_convention": self.currency_convention,
            "capability_manifest_version": self.capability_manifest_version,
            "capability_manifest_digest": self.capability_manifest_digest,
            "program_version": self.program_version,
            "shape_version": self.shape_version,
            "resource_policy_version": self.resource_policy_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuestionContext":
        fields = ("context_version", "question", "prior_turns", "today", "locale",
                  "currency_convention", "capability_manifest_version",
                  "capability_manifest_digest", "program_version", "shape_version",
                  "resource_policy_version")
        _strict(data, fields, fields, "QuestionContext")
        if data["context_version"] != QUESTION_CONTEXT_VERSION:
            raise ContractError("unsupported QuestionContext version")
        prior = data["prior_turns"]
        if not isinstance(prior, list):
            raise ContractError("QuestionContext.prior_turns must be an array")
        turns = []
        for item in prior:
            _strict(item, ("question", "answer"), ("question", "answer"),
                    "QuestionContext.prior_turn")
            turns.append((str(item["question"]), str(item["answer"])))
        return cls(question=str(data["question"]), prior_turns=tuple(turns),
                   today=str(data["today"]), locale=str(data["locale"]),
                   currency_convention=str(data["currency_convention"]),
                   capability_manifest_version=str(data["capability_manifest_version"]),
                   capability_manifest_digest=str(data["capability_manifest_digest"]),
                   program_version=str(data["program_version"]),
                   shape_version=str(data["shape_version"]),
                   resource_policy_version=str(data["resource_policy_version"]),
                   context_version=str(data["context_version"]))


@dataclass(frozen=True)
class AnswerResourcePolicy:
    max_model_attempts: int = 2
    max_required_nodes: int = 16
    max_supporting_nodes: int = 8
    max_optional_nodes: int = 8
    max_dependency_depth: int = 8
    max_evidence_bytes: int = 250_000
    max_execution_ms: int = 15_000
    max_figures: int = 500
    policy_version: str = RESOURCE_POLICY_VERSION

    def __post_init__(self):
        values = self.to_dict()
        for name, value in values.items():
            if name == "policy_version":
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ContractError(f"{name} must be a positive integer")
        if self.max_model_attempts > 2:
            raise ContractError("max_model_attempts cannot exceed two")

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in (
            "policy_version", "max_model_attempts", "max_required_nodes",
            "max_supporting_nodes", "max_optional_nodes", "max_dependency_depth",
            "max_evidence_bytes", "max_execution_ms", "max_figures")}

    @classmethod
    def from_dict(cls, data: dict) -> "AnswerResourcePolicy":
        fields = ("policy_version", "max_model_attempts", "max_required_nodes",
                  "max_supporting_nodes", "max_optional_nodes",
                  "max_dependency_depth", "max_evidence_bytes",
                  "max_execution_ms", "max_figures")
        _strict(data, fields, fields, "AnswerResourcePolicy")
        if data["policy_version"] != RESOURCE_POLICY_VERSION:
            raise ContractError("unsupported AnswerResourcePolicy version")
        return cls(**data)


@dataclass(frozen=True)
class ProgramNode:
    id: str
    kind: str
    depends_on: tuple[str, ...] = ()
    importance: str = "required"
    tool: str = ""
    args: dict = field(default_factory=dict)
    entity_kind: str = ""
    phrase: str = ""
    query: dict = field(default_factory=dict)
    predicate: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {"id": self.id, "kind": self.kind,
               "depends_on": list(self.depends_on),
               "importance": self.importance}
        for name in ("tool", "entity_kind", "phrase"):
            if getattr(self, name):
                out[name] = getattr(self, name)
        for name in ("args", "query", "predicate"):
            if getattr(self, name):
                out[name] = dict(getattr(self, name))
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "ProgramNode":
        allowed = ("id", "kind", "depends_on", "importance", "tool", "args",
                   "entity_kind", "phrase", "query", "predicate")
        _strict(data, allowed, ("id", "kind", "depends_on", "importance"),
                "AnswerProgram.node")
        if data["kind"] not in NODE_KINDS:
            raise ContractError(f"unknown node kind {data['kind']!r}")
        if data["importance"] not in IMPORTANCE:
            raise ContractError(f"unknown node importance {data['importance']!r}")
        for name in ("args", "query", "predicate"):
            if name in data and not isinstance(data[name], dict):
                raise ContractError(f"node.{name} must be an object")
        return cls(id=str(data["id"]), kind=str(data["kind"]),
                   depends_on=_strings(data["depends_on"], "node.depends_on"),
                   importance=str(data["importance"]),
                   tool=str(data.get("tool", "")), args=dict(data.get("args") or {}),
                   entity_kind=str(data.get("entity_kind", "")),
                   phrase=str(data.get("phrase", "")),
                   query=dict(data.get("query") or {}),
                   predicate=dict(data.get("predicate") or {}))


@dataclass(frozen=True)
class BindingSelector:
    quantity: str = ""
    scope: tuple[str, ...] = ()
    entity_kind: str = ""
    entity_ref: dict = field(default_factory=dict)
    currency: str = ""
    order: str = ""
    limit: int | None = None
    cardinality: str = "one"

    def to_dict(self) -> dict:
        out = {"cardinality": self.cardinality}
        for name in ("quantity", "entity_kind", "currency", "order"):
            if getattr(self, name):
                out[name] = getattr(self, name)
        if self.scope:
            out["scope"] = list(self.scope)
        if self.entity_ref:
            out["entity_ref"] = dict(self.entity_ref)
        if self.limit is not None:
            out["limit"] = self.limit
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "BindingSelector":
        fields = ("quantity", "scope", "entity_kind", "entity_ref", "currency",
                  "order", "limit", "cardinality")
        _strict(data, fields, ("cardinality",), "binding.selector")
        if data["cardinality"] not in CARDINALITIES:
            raise ContractError("selector.cardinality must be one or all")
        scope = _strings(data.get("scope", []), "selector.scope")
        entity_ref = data.get("entity_ref") or {}
        if not isinstance(entity_ref, dict):
            raise ContractError("selector.entity_ref must be an object")
        limit = data.get("limit")
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool)
                                  or limit <= 0):
            raise ContractError("selector.limit must be a positive integer")
        return cls(quantity=str(data.get("quantity", "")), scope=scope,
                   entity_kind=str(data.get("entity_kind", "")),
                   entity_ref=dict(entity_ref), currency=str(data.get("currency", "")),
                   order=str(data.get("order", "")), limit=limit,
                   cardinality=str(data["cardinality"]))


@dataclass(frozen=True)
class Binding:
    hole: str
    source: str
    reference_kind: str
    selector: BindingSelector

    def to_dict(self) -> dict:
        return {"hole": self.hole, "source": self.source,
                "reference_kind": self.reference_kind,
                "selector": self.selector.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> "Binding":
        fields = ("hole", "source", "reference_kind", "selector")
        _strict(data, fields, fields, "AnswerProgram.binding")
        return cls(hole=str(data["hole"]), source=str(data["source"]),
                   reference_kind=str(data["reference_kind"]),
                   selector=BindingSelector.from_dict(data["selector"]))


@dataclass(frozen=True)
class AnswerProgram:
    mode: str
    question_kind: str
    shape: Shape | None
    nodes: tuple[ProgramNode, ...]
    bindings: tuple[Binding, ...]
    assumptions: tuple[dict, ...] = ()
    clarification: dict | None = None
    result_policy: dict = field(default_factory=dict)
    capability_manifest_version: str = CAPABILITY_MANIFEST_VERSION
    capability_manifest_digest: str = ""
    program_version: str = ANSWER_PROGRAM_VERSION

    def to_dict(self) -> dict:
        return {
            "program_version": self.program_version,
            "capability_manifest_version": self.capability_manifest_version,
            "capability_manifest_digest": self.capability_manifest_digest,
            "mode": self.mode,
            "question_kind": self.question_kind,
            "shape": self.shape.to_dict() if self.shape is not None else None,
            "nodes": [node.to_dict() for node in self.nodes],
            "bindings": [binding.to_dict() for binding in self.bindings],
            "assumptions": [dict(item) for item in self.assumptions],
            "clarification": (dict(self.clarification)
                              if self.clarification is not None else None),
            "result_policy": dict(self.result_policy),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnswerProgram":
        fields = ("program_version", "capability_manifest_version",
                  "capability_manifest_digest", "mode", "question_kind", "shape",
                  "nodes", "bindings", "assumptions", "clarification",
                  "result_policy")
        _strict(data, fields, fields, "AnswerProgram")
        if data["program_version"] != ANSWER_PROGRAM_VERSION:
            raise ContractError("unsupported AnswerProgram version")
        if data["mode"] not in PROGRAM_MODES:
            raise ContractError(f"unknown AnswerProgram mode {data['mode']!r}")
        shape = None
        if data["shape"] is not None:
            shape, problem = read_shape(data["shape"])
            if shape is None:
                raise ContractError(f"invalid answer shape: {problem}")
        for name in ("nodes", "bindings", "assumptions"):
            if not isinstance(data[name], list):
                raise ContractError(f"AnswerProgram.{name} must be an array")
        if data["clarification"] is not None and not isinstance(data["clarification"], dict):
            raise ContractError("AnswerProgram.clarification must be an object or null")
        if not isinstance(data["result_policy"], dict):
            raise ContractError("AnswerProgram.result_policy must be an object")
        return cls(mode=str(data["mode"]), question_kind=str(data["question_kind"]),
                   shape=shape,
                   nodes=tuple(ProgramNode.from_dict(n) for n in data["nodes"]),
                   bindings=tuple(Binding.from_dict(b) for b in data["bindings"]),
                   assumptions=tuple(dict(a) for a in data["assumptions"]),
                   clarification=(dict(data["clarification"])
                                  if data["clarification"] is not None else None),
                   result_policy=dict(data["result_policy"]),
                   capability_manifest_version=str(data["capability_manifest_version"]),
                   capability_manifest_digest=str(data["capability_manifest_digest"]),
                   program_version=str(data["program_version"]))


def _generated_program_json_schema() -> dict[str, Any]:
    """Build the expected artifact for parity tests and version minting."""
    slots = []
    for kind in MAGNITUDE_TYPES:
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
        slots.append({"type": "object", "additionalProperties": False,
                      "properties": properties, "required": required})
    slots.append({"type": "object", "additionalProperties": False,
                  "properties": {"name": {"type": "string"},
                                 "type": {"type": "string",
                                          "enum": list(PLAIN_TYPES)}},
                  "required": ["name", "type"]})

    shape = {"type": "object", "additionalProperties": False,
             "properties": {"clauses": {"type": "array", "minItems": 1,
                 "items": {"type": "object", "additionalProperties": False,
                           "properties": {"id": {"type": "string"},
                                          "text": {"type": "string"},
                                          "slots": {"type": "array",
                                                    "minItems": 1,
                                                    "items": {"oneOf": slots}}},
                           "required": ["id", "text", "slots"]}}},
             "required": ["clauses"]}
    node = {"type": "object", "additionalProperties": False,
            "properties": {"id": {"type": "string"},
                           "kind": {"type": "string", "enum": list(NODE_KINDS)},
                           "depends_on": {"type": "array",
                                          "items": {"type": "string"}},
                           "importance": {"type": "string",
                                          "enum": list(IMPORTANCE)},
                           "tool": {"type": "string"},
                           "args": {"type": "object"},
                           "entity_kind": {"type": "string"},
                           "phrase": {"type": "string"},
                           "query": financial_query_json_schema(),
                           "predicate": {"type": "object"}},
            "required": ["id", "kind", "depends_on", "importance"]}
    selector = {"type": "object", "additionalProperties": False,
                "properties": {"quantity": {"type": "string"},
                               "scope": {"type": "array",
                                         "items": {"type": "string"}},
                               "entity_kind": {"type": "string"},
                               "entity_ref": {"type": "object"},
                               "currency": {"type": "string"},
                               "order": {"type": "string"},
                               "limit": {"type": "integer", "minimum": 1},
                               "cardinality": {"type": "string",
                                               "enum": list(CARDINALITIES)}},
                "required": ["cardinality"]}
    binding = {"type": "object", "additionalProperties": False,
               "properties": {"hole": {"type": "string"},
                              "source": {"type": "string"},
                              "reference_kind": {"type": "string",
                                                 "enum": list(REFERENCE_KINDS)},
                              "selector": selector},
               "required": ["hole", "source", "reference_kind", "selector"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["program_version", "capability_manifest_version",
                     "capability_manifest_digest", "mode", "question_kind", "shape",
                     "nodes", "bindings", "assumptions", "clarification",
                     "result_policy"],
        "properties": {
            "program_version": {"type": "string", "enum": [ANSWER_PROGRAM_VERSION]},
            "capability_manifest_version": {"type": "string",
                                             "enum": [CAPABILITY_MANIFEST_VERSION]},
            "capability_manifest_digest": {"type": "string"},
            "mode": {"type": "string", "enum": list(PROGRAM_MODES)},
            "question_kind": {"type": "string"},
            "shape": {"oneOf": [shape, {"type": "null"}]},
            "nodes": {"type": "array", "items": node},
            "bindings": {"type": "array", "items": binding},
            "assumptions": {"type": "array", "items": {"type": "object"}},
            "clarification": {"oneOf": [{"type": "object"},
                                            {"type": "null"}]},
            "result_policy": {"type": "object"},
        },
    }


def program_json_schema() -> dict[str, Any]:
    """Load the immutable transport contract named by the active version."""
    path = versions.path_of(pathlib.Path(__file__).resolve().parent.parent,
                            ANSWER_PROGRAM_VERSION)
    return copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
