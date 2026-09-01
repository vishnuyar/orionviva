"""Finite syntax and static validation for the Financial Query IR."""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import json
import pathlib

from vivacore import versions

FINANCIAL_QUERY_VERSION = "financial-query-v1"
FINANCIAL_QUERY_SCHEMA_VERSION = versions.active(
    pathlib.Path(__file__).resolve().parent.parent, "financial_query_schema")
GENERIC_OPERATORS = (
    "scan", "filter", "select", "resolve", "group", "aggregate", "sort",
    "limit", "rank", "top", "bottom", "calendar_window", "rolling_window",
    "join", "union_compatible", "difference", "intersection", "delta",
    "percentage_change", "ratio", "compute", "require_coverage",
    "require_grade")
DOMAIN_OPERATORS = (
    "spending", "attributed_income", "unexplained_inflows", "surplus",
    "net_worth", "held_balance", "amount_owed", "recurring_spending",
    "statement_completeness", "evidence_staleness", "transfer_excluded_flow")
OPERATORS = GENERIC_OPERATORS + DOMAIN_OPERATORS
# The manifest exposes both halves of every admitted operator.  Registration
# without either law is impossible because the executable vocabulary is
# derived from this table.
OPERATOR_RULES = {
    "scan": ("read one typed bounded source", "retain source evidence"),
    "filter": ("retain rows matching a closed predicate", "retain row evidence"),
    "select": ("project declared fields", "retain row evidence"),
    "resolve": ("exact normalized unique entity resolution", "retain resolved row evidence"),
    "group": ("declare grouping keys", "retain row evidence for later aggregation"),
    "aggregate": ("exact grouped aggregate", "union records, weakest grade, intersect coverage"),
    "sort": ("stable typed ordering", "retain row evidence"),
    "limit": ("stable bounded prefix", "retain selected row evidence"),
    "rank": ("stable one-based rank", "retain ranked row evidence"),
    "top": ("stable largest bounded rows", "retain selected row evidence"),
    "bottom": ("stable smallest bounded rows", "retain selected row evidence"),
    "calendar_window": ("inclusive date filter", "retain selected row evidence"),
    "rolling_window": ("bounded trailing date filter with edge policy", "retain selected row evidence and require declared coverage when requested"),
    "join": ("typed-key inner or left join", "union records, weakest grade, intersect coverage"),
    "union_compatible": ("stable compatible union", "retain contributing row evidence"),
    "difference": ("compatible keyed difference", "retain left-row evidence"),
    "intersection": ("compatible keyed intersection", "retain left-row evidence"),
    "delta": ("exact subtraction", "retain operand evidence"),
    "percentage_change": ("exact baseline-relative change", "retain operand evidence"),
    "ratio": ("exact nonzero-denominator ratio", "retain operand evidence"),
    "compute": ("closed exact row arithmetic", "retain operand evidence"),
    "require_coverage": ("retain rows covering a declared span", "coverage proves admission"),
    "require_grade": ("retain rows meeting a declared minimum", "grade proves admission"),
}
for _domain in DOMAIN_OPERATORS:
    OPERATOR_RULES[_domain] = (
        "invoke the existing projection authority for " + _domain,
        "retain the authority's figures, records, grade, boundary and coverage")
if set(OPERATOR_RULES) != set(OPERATORS):
    raise RuntimeError("every Financial Query operator needs value and evidence laws")


def operator_manifest(names=None):
    names = tuple(names or OPERATORS)
    unknown = set(names) - set(OPERATORS)
    if unknown:
        raise ValueError("unknown Financial Query operators: "
                         + ", ".join(sorted(unknown)))
    return tuple({"name": name, "value_rule": OPERATOR_RULES[name][0],
                  "evidence_rule": OPERATOR_RULES[name][1]}
                 for name in names)
MAX_STEPS = 32

_ARGUMENTS = {
    "scan": ({"source"}, {"source"}),
    "filter": ({"predicate"}, {"predicate"}),
    "select": ({"fields"}, {"fields"}),
    "resolve": ({"field", "phrase"}, {"field", "phrase"}),
    "group": ({"keys"}, {"keys"}),
    "aggregate": ({"function", "output"},
                  {"function", "field", "output", "group_by", "currency_field"}),
    "sort": ({"keys"}, {"keys", "direction"}),
    "limit": ({"count"}, {"count"}),
    "rank": ({"keys"}, {"keys", "direction", "field"}),
    "top": ({"keys", "count"}, {"keys", "count"}),
    "bottom": ({"keys", "count"}, {"keys", "count"}),
    "calendar_window": ({"field", "from", "to"}, {"field", "from", "to"}),
    "rolling_window": ({"field", "width", "unit", "edge_policy"},
                       {"field", "width", "unit", "edge_policy", "anchor"}),
    "join": ({"left_key", "right_key", "join_kind"},
             {"left_key", "right_key", "join_kind", "right_prefix"}),
    "union_compatible": (set(), {"keys"}),
    "difference": (set(), {"keys"}),
    "intersection": (set(), {"keys"}),
    "delta": ({"left", "right", "output"}, {"left", "right", "output"}),
    "percentage_change": ({"left", "right", "output"},
                          {"left", "right", "output"}),
    "ratio": ({"left", "right", "output"}, {"left", "right", "output"}),
    "compute": ({"operation", "left", "output"},
                {"operation", "left", "right", "output"}),
    "require_coverage": ({"from", "to"}, {"from", "to"}),
    "require_grade": ({"minimum"}, {"minimum"}),
}
for _domain in DOMAIN_OPERATORS:
    _ARGUMENTS[_domain] = (set(), {"filters"})


def _argument_json_schema(name):
    strings = {"source", "field", "phrase", "output", "left", "right",
               "from", "to", "anchor", "left_key", "right_key",
               "right_prefix", "currency_field"}
    if name in strings:
        return {"type": "string"}
    if name in {"fields", "keys", "group_by"}:
        return {"type": "array", "items": {"type": "string"}}
    if name in {"count", "width"}:
        return {"type": "integer", "minimum": 1}
    enums = {
        "function": ("sum", "count", "min", "max", "average"),
        "direction": ("asc", "desc"),
        "unit": ("day", "week", "month"),
        "edge_policy": ("partial", "require_full_coverage"),
        "join_kind": ("inner", "left"),
        "operation": ("add", "subtract", "multiply", "divide", "absolute"),
        "minimum": ("verified", "corroborated", "unverified", "conflicted"),
    }
    if name in enums:
        return {"type": "string", "enum": list(enums[name])}
    if name == "predicate":
        return {"type": "object", "additionalProperties": False,
                "required": ["field", "op", "value"],
                "properties": {
                    "field": {"type": "string"},
                    "op": {"type": "string",
                           "enum": ["eq", "neq", "in", "lt", "lte", "gt", "gte"]},
                    "value": {"oneOf": [
                        {"type": "string"}, {"type": "integer"},
                        {"type": "boolean"},
                        {"type": "array", "items": {"oneOf": [
                            {"type": "string"}, {"type": "integer"},
                            {"type": "boolean"}]}}]}}}
    return {"type": "object"}


def financial_query_json_schema():
    """Self-contained immutable wire schema for the executable FQIR grammar."""
    steps = []
    for op in OPERATORS:
        required, allowed = _ARGUMENTS[op]
        args = {"type": "object", "additionalProperties": False,
                "properties": {name: _argument_json_schema(name)
                               for name in sorted(allowed)},
                "required": sorted(required)}
        steps.append({"type": "object", "additionalProperties": False,
                      "required": ["id", "op", "inputs", "args"],
                      "properties": {
                          "id": {"type": "string", "minLength": 1},
                          "op": {"type": "string", "enum": [op]},
                          "inputs": {"type": "array",
                                     "items": {"type": "string"}},
                          "args": args}})
    return {"type": "object", "additionalProperties": False,
            "required": ["query_version", "steps", "output", "emit"],
            "properties": {
                "query_version": {"type": "string",
                                  "enum": [FINANCIAL_QUERY_VERSION]},
                "steps": {"type": "array", "minItems": 1,
                          "maxItems": MAX_STEPS, "items": {"oneOf": steps}},
                "output": {"type": "string", "minLength": 1},
                "emit": {"type": "object", "additionalProperties": False,
                         "required": ["value_field", "quantity"],
                         "properties": {
                             "value_field": {"type": "string"},
                             "what_field": {"type": "string"},
                             "what": {"type": "string"},
                             "quantity": {"type": "string"},
                             "currency_field": {"type": "string"},
                             "dated_field": {"type": "string"}}}}}


def packaged_financial_query_json_schema():
    path = versions.path_of(pathlib.Path(__file__).resolve().parent.parent,
                            FINANCIAL_QUERY_SCHEMA_VERSION)
    return copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))


def _string_list(value, where):
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item for item in value)):
        raise ValueError(f"{where} must be a non-empty array of strings")


def _validate_step(step):
    required, allowed = _ARGUMENTS[step.op]
    unknown, missing = set(step.args) - allowed, required - set(step.args)
    if unknown or missing:
        raise ValueError(f"{step.op} arguments differ: unknown={sorted(unknown)}, "
                         f"missing={sorted(missing)}")
    if step.op in ("select", "sort", "rank", "group", "top", "bottom"):
        _string_list(step.args.get("fields") if step.op == "select"
                     else step.args.get("keys"), f"{step.op} fields")
    if "group_by" in step.args:
        value = step.args["group_by"]
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise ValueError("aggregate group_by must be an array of strings")
    if "keys" in step.args and step.op in (
            "union_compatible", "difference", "intersection"):
        _string_list(step.args["keys"], f"{step.op} keys")
    if step.op == "filter":
        predicate = step.args["predicate"]
        if (not isinstance(predicate, dict)
                or set(predicate) != {"field", "op", "value"}
                or predicate["op"] not in ("eq", "neq", "in", "lt", "lte", "gt", "gte")):
            raise ValueError("filter predicate must name field, admitted op and value")
    if step.op == "aggregate":
        if step.args["function"] not in ("sum", "count", "min", "max", "average"):
            raise ValueError("unknown aggregate function")
        if step.args["function"] != "count" and not step.args.get("field"):
            raise ValueError("non-count aggregate requires a field")
    if step.op in ("limit", "top", "bottom"):
        count = step.args["count"]
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError("limit count must be a positive integer")
    if step.op in ("sort", "rank") and step.args.get("direction", "asc") not in (
            "asc", "desc"):
        raise ValueError("sort direction must be asc or desc")
    if step.op == "join" and step.args["join_kind"] not in ("inner", "left"):
        raise ValueError("join kind must be inner or left")
    if step.op == "require_grade" and step.args["minimum"] not in (
            "verified", "corroborated", "unverified", "conflicted"):
        raise ValueError("unknown evidence grade")
    if step.op == "rolling_window":
        width = step.args["width"]
        if (not isinstance(width, int) or isinstance(width, bool) or width <= 0
                or step.args["unit"] not in ("day", "week", "month")
                or step.args["edge_policy"] not in ("partial", "require_full_coverage")):
            raise ValueError("rolling window needs positive width, admitted unit and edge policy")
    if step.op == "compute" and step.args["operation"] not in (
            "add", "subtract", "multiply", "divide", "absolute"):
        raise ValueError("compute operation is not admitted")
    if (step.op == "compute" and step.args["operation"] != "absolute"
            and not step.args.get("right")):
        raise ValueError("binary compute operation requires right")
    if step.op in DOMAIN_OPERATORS and "filters" in step.args \
            and not isinstance(step.args["filters"], dict):
        raise ValueError("domain operator filters must be an object")


def _no_floats(value, path="$:"):
    if isinstance(value, float):
        raise ValueError(f"{path} contains a float")
    if isinstance(value, dict):
        for key, child in value.items():
            _no_floats(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _no_floats(child, f"{path}[{index}]")


@dataclass(frozen=True)
class QueryStep:
    id: str
    op: str
    inputs: tuple[str, ...] = ()
    args: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict) or set(raw) != {"id", "op", "inputs", "args"}:
            raise ValueError("each financial query step names id, op, inputs and args")
        if raw["op"] not in OPERATORS:
            raise ValueError(f"unknown financial query operator {raw['op']!r}")
        if (not isinstance(raw["inputs"], list)
                or any(not isinstance(item, str) for item in raw["inputs"])):
            raise ValueError("query step inputs must be an array of ids")
        if not isinstance(raw["args"], dict):
            raise ValueError("query step args must be an object")
        _no_floats(raw["args"])
        return cls(str(raw["id"]), str(raw["op"]), tuple(raw["inputs"]),
                   dict(raw["args"]))

    def to_dict(self):
        return {"id": self.id, "op": self.op, "inputs": list(self.inputs),
                "args": dict(self.args)}


@dataclass(frozen=True)
class FinancialQuery:
    steps: tuple[QueryStep, ...]
    output: str
    emit: dict
    query_version: str = FINANCIAL_QUERY_VERSION

    @classmethod
    def from_dict(cls, raw):
        fields = {"query_version", "steps", "output", "emit"}
        if not isinstance(raw, dict) or set(raw) != fields:
            raise ValueError("FinancialQuery names query_version, steps, output and emit")
        if raw["query_version"] != FINANCIAL_QUERY_VERSION:
            raise ValueError("unsupported FinancialQuery version")
        if not isinstance(raw["steps"], list) or not raw["steps"]:
            raise ValueError("FinancialQuery needs at least one step")
        if len(raw["steps"]) > MAX_STEPS:
            raise ValueError(f"FinancialQuery exceeds {MAX_STEPS} steps")
        steps = tuple(QueryStep.from_dict(item) for item in raw["steps"])
        seen = set()
        for step in steps:
            if not step.id or step.id in seen:
                raise ValueError("FinancialQuery step ids must be present and unique")
            if any(source not in seen for source in step.inputs):
                raise ValueError("FinancialQuery inputs must name earlier steps")
            if step.op == "scan" and step.inputs:
                raise ValueError("scan takes no input step")
            if step.op not in (("scan",) + DOMAIN_OPERATORS) and not step.inputs:
                raise ValueError(f"{step.op} needs at least one input step")
            expected_inputs = 0 if step.op == "scan" or step.op in DOMAIN_OPERATORS else (2 if step.op in (
                "join", "union_compatible", "difference", "intersection") else 1)
            if len(step.inputs) != expected_inputs:
                raise ValueError(f"{step.op} needs {expected_inputs} input step(s)")
            _validate_step(step)
            seen.add(step.id)
        if raw["output"] not in seen:
            raise ValueError("FinancialQuery output must name one step")
        if not isinstance(raw["emit"], dict):
            raise ValueError("FinancialQuery emit must be an object")
        emit_allowed = {"value_field", "what_field", "what", "quantity",
                        "currency_field", "dated_field"}
        if (set(raw["emit"]) - emit_allowed
                or not {"value_field", "quantity"} <= set(raw["emit"])):
            raise ValueError("FinancialQuery emit needs value_field and quantity only from its schema")
        _no_floats(raw["emit"], "$.emit")
        return cls(steps, str(raw["output"]), dict(raw["emit"]),
                   str(raw["query_version"]))

    def to_dict(self):
        return {"query_version": self.query_version,
                "steps": [step.to_dict() for step in self.steps],
                "output": self.output, "emit": dict(self.emit)}
