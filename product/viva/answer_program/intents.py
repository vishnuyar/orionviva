"""Reviewed, data-blind programs for stable financial question families."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .schema import (ANSWER_PROGRAM_VERSION, CAPABILITY_MANIFEST_VERSION,
                     AnswerProgram)

KNOWN_INTENT_REQUEST_VERSION = "known-intent-request-v1"


@dataclass(frozen=True)
class KnownIntent:
    id: str
    description: str
    parameter_schema: dict
    nodes: tuple[dict, ...]
    semantic_claims: tuple[str, ...]
    scopes: tuple[str, ...]
    subject: str
    period: str

    def manifest(self) -> dict:
        return {"id": self.id, "description": self.description,
                "parameter_schema": dict(self.parameter_schema),
                "semantic_claims": list(self.semantic_claims),
                "scopes": list(self.scopes), "subject": self.subject,
                "period": self.period}


def _object(properties=None, required=()):
    return {"type": "object", "properties": dict(properties or {}),
            "required": list(required), "additionalProperties": False}


def _read(node_id, tool, args):
    return {"id": node_id, "kind": "tool_read", "depends_on": [],
            "importance": "required", "tool": tool, "args": args}


def _movement_query(start, end):
    return {"id": "spending_query", "kind": "financial_query",
            "depends_on": [], "importance": "required", "query": {
        "query_version": "financial-query-v1", "steps": [
            {"id": "movements", "op": "scan", "inputs": [],
             "args": {"source": "movements"}},
            {"id": "spending_only", "op": "filter", "inputs": ["movements"],
             "args": {"predicate": {"field": "nature", "op": "eq",
                                     "value": "spending"}}},
            {"id": "period", "op": "calendar_window",
             "inputs": ["spending_only"],
             "args": {"field": "date", "from": start, "to": end}},
            {"id": "magnitude", "op": "compute", "inputs": ["period"],
             "args": {"operation": "absolute", "left": "amount",
                      "output": "magnitude"}},
            {"id": "largest", "op": "sort", "inputs": ["magnitude"],
             "args": {"keys": ["magnitude"], "direction": "desc"}},
            {"id": "top", "op": "limit", "inputs": ["largest"],
             "args": {"count": 3}},
        ], "output": "top",
        "emit": {"value_field": "amount", "what_field": "description",
                 "currency_field": "currency", "dated_field": "date",
                 "quantity": "movement"}}}


def _query(metric, *, filters=None, group_by="", as_of=""):
    args = {"entity": "aggregate", "metric": metric}
    if filters:
        args["filters"] = filters
    if group_by:
        args["group_by"] = group_by
    if as_of:
        args["as_of"] = as_of
    return args


_WINDOW_PRESET = {"window": {"preset": "latest_complete_calendar_month"}}
_DATE = {"type": "string"}
_STRING = {"type": "string"}


def _definitions(parameters):
    start, end = parameters.get("from", ""), parameters.get("to", "")
    movement_filters = ({"window": {"from": start, "to": end}}
                        if start and end else _WINDOW_PRESET)
    as_of = parameters.get("as_of", "")
    return {
        "net_worth": (_object(), (
            _read("net_worth", "query_ledger",
                  _query("net_worth")),
            _read("staleness", "query_ledger",
                  _query("stalest_balance")))),
        "account_balances": (_object(), (
            _read("balances", "query_ledger", {"entity": "balances"}),
            _read("completeness", "check_completeness", {}))),
        "monthly_spending_by_category": (_object(), (
            _read("spending", "query_ledger",
                  _query("spending", filters=_WINDOW_PRESET,
                         group_by="category")),)),
        "largest_spending_movements": (_object(
            {"from": _DATE, "to": _DATE}, ("from", "to")), (
            _read("movements", "list_movements",
                  {"filters": movement_filters}),
            _movement_query(start, end))),
        "monthly_income": (_object(), (
            _read("income", "query_ledger",
                  _query("income", filters=_WINDOW_PRESET)),)),
        "monthly_surplus": (_object(), (
            _read("surplus", "query_ledger",
                  _query("surplus", filters=_WINDOW_PRESET)),
            _read("completeness", "check_completeness", {}))),
        "stalest_balance": (_object(), (
            _read("staleness", "query_ledger",
                  _query("stalest_balance")),)),
        "weakest_evidence": (_object(), (
            _read("weakest", "query_ledger",
                  _query("weakest_evidence")),)),
        "recurring_spending": (_object(), (
            _read("recurring", "query_ledger",
                  _query("recurring_spending")),)),
        "financial_health_summary": (_object(), (
            _read("balances", "query_ledger", {"entity": "balances"}),
            _read("surplus", "query_ledger",
                  _query("surplus", filters=_WINDOW_PRESET)),
            _read("weakest", "query_ledger", _query("weakest_evidence")),
            _read("completeness", "check_completeness", {}))),
    }


def _claims(intent_id):
    """Reviewed selectors; read_figures renders the selected cited figures."""
    return {
        "net_worth": (("net_worth", "net_worth", "largest", None),
                      ("staleness", "balance", "largest", None),
                      ("staleness", "count", "largest", None)),
        "account_balances": (("balances", "balance", "", None),
                             ("balances", "owed", "", None),
                             ("completeness", "count", "", 3)),
        "monthly_spending_by_category": (("spending", "spending", "largest", 4),),
        "largest_spending_movements": (("spending_query", "movement", "largest", 3),),
        "monthly_income": (("income", "income", "largest", None),
                           ("income", "gross_flow", "largest", None)),
        "monthly_surplus": (("surplus", "income", "largest", None),
                            ("surplus", "spending", "largest", None),
                            ("surplus", "net_movement", "largest", None),
                            ("completeness", "count", "", 3)),
        "stalest_balance": (("staleness", "balance", "largest", None),
                            ("staleness", "count", "largest", None)),
        "weakest_evidence": (("weakest", "balance", "largest", 3),
                             ("weakest", "owed", "largest", 3),
                             ("weakest", "movement", "largest", 3)),
        "recurring_spending": (("recurring", "spending", "largest", 3),),
        "financial_health_summary": (("balances", "balance", "largest", None),
                                     ("balances", "owed", "largest", None),
                                     ("surplus", "net_movement", "largest", None),
                                     ("weakest", "balance", "largest", 3),
                                     ("weakest", "owed", "largest", 3),
                                     ("completeness", "count", "largest", 3)),
}[intent_id]


_CLAIM_TEXT = {
    "net_worth": (
        "Current supported net worth by currency: {hole}.",
        "The stalest included balance evidence: {hole}.",
        "Accounts represented in that staleness check: {hole}."),
    "account_balances": (
        "Supported asset balances by account: {hole}.",
        "Supported amounts owed by account: {hole}.",
        "Completeness gaps found in the account inventory: {hole}."),
    "monthly_spending_by_category": (
        "Latest complete month spending by category: {hole}.",),
    "largest_spending_movements": (
        "Largest supported spending movements in the requested period: {hole}.",),
    "monthly_income": (
        "Attributed income in the latest complete month: {hole}.",
        "Unexplained inflows reported separately when present: {hole}."),
    "monthly_surplus": (
        "Attributed income used in the latest complete month comparison: {hole}.",
        "Counted spending used in that comparison: {hole}.",
        "Resulting supported surplus or shortfall: {hole}.",
        "Completeness gaps affecting the comparison: {hole}."),
    "stalest_balance": (
        "The stalest supported balance evidence: {hole}.",
        "Accounts represented in the staleness check: {hole}."),
    "weakest_evidence": (
        "Supported balances with the weakest evidence: {hole}.",
        "Supported debts with the weakest evidence: {hole}.",
        "Supported movements with the weakest evidence: {hole}."),
    "recurring_spending": (
        "Supported recurring spending patterns: {hole}.",),
    "financial_health_summary": (
        "Supported liquid balances: {hole}.",
        "Supported debts: {hole}.",
        "Latest complete month cash flow: {hole}.",
        "Balances with the weakest evidence: {hole}.",
        "Debts with the weakest evidence: {hole}.",
        "Completeness gaps found in the financial inventory: {hole}."),
}


_SEMANTIC_CONTRACTS = {
    "net_worth": (("net_worth", "not_counted", "staleness"),
                  ("whole",), "vault", "current"),
    "account_balances": (("balance", "owed", "evidence_date", "grade",
                           "completeness"), ("account",), "each_account", "latest"),
    "monthly_spending_by_category": (("spending", "ranked_categories", "period",
                                       "exclusions"), ("category", "period"),
                                      "spending", "latest_complete_calendar_month"),
    "largest_spending_movements": (("movement", "date", "merchant", "account",
                                     "grade"), ("merchant", "account", "period"),
                                    "spending_movements", "explicit"),
    "monthly_income": (("income", "unexplained_inflows", "sources", "period"),
                       ("period",), "income", "latest_complete_calendar_month"),
    "monthly_surplus": (("income", "spending", "surplus", "completeness"),
                        ("period",), "surplus", "latest_complete_calendar_month"),
    "stalest_balance": (("balance", "evidence_date", "age", "account"),
                        ("account",), "stalest_account", "current"),
    "weakest_evidence": (("ranked_financial_facts", "grade", "limitation"),
                         ("account",), "weakest_evidence", "current"),
    "recurring_spending": (("recurring_spending", "ranked_merchants", "period"),
                           ("merchant", "period"), "recurring_spending", "supported"),
    "financial_health_summary": (("liquidity", "debt", "cash_flow", "gaps"),
                                 ("whole", "period"), "financial_health",
                                 "latest_complete_calendar_month"),
}


class KnownIntentRegistry:
    """Finite registry; instantiation never observes current-turn data."""

    def __init__(self):
        empty = _definitions({})
        descriptions = {
            "net_worth": "Current net worth, separated honestly by currency and evidence.",
            "account_balances": "Account inventory with supported balances, dates, grades and completeness.",
            "monthly_spending_by_category": "Latest complete month spending and category breakdown.",
            "largest_spending_movements": "Largest individual spending movements in an explicit date range.",
            "monthly_income": "Latest complete month supported income and unexplained inflows.",
            "monthly_surplus": "Use for the latest complete month comparison of supported income and spending, its surplus or shortfall, and completeness limitations.",
            "stalest_balance": "The stalest supported account balance, its age, and the honest statement that records cannot bound its current financial impact.",
            "weakest_evidence": "Financially significant balances or movements with the weakest evidence.",
            "recurring_spending": "Supported recurring spending patterns, the largest recurring counterparties, their period, or a structured insufficient-history outcome.",
            "financial_health_summary": "Concise liquidity, debt, recent cash flow and evidence-gap summary.",
        }
        self._intents = {
            name: KnownIntent(name, descriptions[name], schema, tuple(nodes),
                              *_SEMANTIC_CONTRACTS[name])
            for name, (schema, nodes) in empty.items()}

    @property
    def ids(self):
        return tuple(self._intents)

    def manifest(self):
        return tuple(self._intents[name].manifest() for name in self.ids)

    def get(self, intent_id):
        return self._intents.get(intent_id)

    def semantic_contract(self, intent_id):
        intent = self.get(intent_id)
        if intent is None:
            return None
        return {"semantic_claims": intent.semantic_claims,
                "scopes": intent.scopes, "subject": intent.subject,
                "period": intent.period}

    def instantiate(self, intent_id: str, parameters: dict, manifest) -> AnswerProgram:
        if intent_id not in self._intents:
            raise ValueError(f"unknown known intent {intent_id!r}")
        if not isinstance(parameters, dict):
            raise ValueError("known intent parameters must be an object")
        definition = _definitions(parameters).get(intent_id)
        schema, nodes = definition
        self._validate_parameters(schema, parameters)
        clauses, bindings, required = [], [], []
        names = ("primary", "secondary", "supporting", "additional",
                 "further", "final")
        for index, (source, quantity, order, limit) in enumerate(
                _claims(intent_id), 1):
            clause_id = f"claim_{index}"
            hole = f"records_{names[index - 1]}"
            text = _CLAIM_TEXT[intent_id][index - 1].format(hole="{" + hole + "}")
            clauses.append({"id": clause_id,
                            "text": text,
                            "slots": [{"name": hole, "type": "rows"}]})
            selector = {"cardinality": "one", "quantity": quantity}
            if order:
                selector["order"] = order
            if limit is not None:
                selector["limit"] = limit
            bindings.append({"hole": hole, "source": source,
                             "reference_kind": "read_figures",
                             "selector": selector})
            optional_unexplained = (intent_id == "monthly_income"
                                    and quantity == "gross_flow")
            if not optional_unexplained:
                required.append(clause_id)
        raw = {
            "program_version": ANSWER_PROGRAM_VERSION,
            "capability_manifest_version": CAPABILITY_MANIFEST_VERSION,
            "capability_manifest_digest": manifest.digest,
            "mode": "answer", "question_kind": intent_id,
            "shape": {"clauses": clauses}, "nodes": list(nodes),
            "bindings": bindings, "assumptions": [], "clarification": None,
            "result_policy": {"allow_partial": intent_id == "monthly_income",
                              "required_clauses": required},
        }
        return AnswerProgram.from_dict(raw)

    @staticmethod
    def _validate_parameters(schema, parameters):
        allowed = set(schema.get("properties", {}))
        unknown = set(parameters) - allowed
        missing = set(schema.get("required", ())) - set(parameters)
        if unknown or missing:
            raise ValueError("known intent parameters differ: unknown="
                             f"{sorted(unknown)}, missing={sorted(missing)}")
        for name, value in parameters.items():
            if schema["properties"][name].get("type") == "string" \
                    and not isinstance(value, str):
                raise ValueError(f"known intent parameter {name!r} must be a string")


def intent_request_json_schema(registry=None):
    registry = registry or KnownIntentRegistry()
    return {
        "type": "object", "additionalProperties": False,
        "required": ["request_version", "capability_manifest_digest",
                     "intent_id", "parameters"],
        "properties": {
            "request_version": {"type": "string",
                                "enum": [KNOWN_INTENT_REQUEST_VERSION]},
            "capability_manifest_digest": {"type": "string"},
            "intent_id": {"type": "string", "enum": list(registry.ids)},
            "parameters": {"type": "object"},
        },
    }


def reviewed_intents_digest(manifest) -> str:
    """Digest every executable reviewed shape, node, binding and policy."""
    registry = KnownIntentRegistry()
    programs = []
    for intent_id in registry.ids:
        parameters = ({"from": "2000-01-01", "to": "2000-01-31"}
                      if intent_id == "largest_spending_movements" else {})
        programs.append(registry.instantiate(
            intent_id, parameters, manifest).to_dict())
    raw = json.dumps(programs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


__all__ = ["KNOWN_INTENT_REQUEST_VERSION", "KnownIntent",
           "KnownIntentRegistry", "intent_request_json_schema",
           "reviewed_intents_digest"]
