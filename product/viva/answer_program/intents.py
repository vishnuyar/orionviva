"""Reviewed semantic families lowered to data-blind AnswerPrograms.

Model-visible requested claims are canonical answer effects.  Two labels may
not describe the same deterministic clause: if lowering cannot distinguish
them, they are one effect here and safety disclosures remain code-owned.
"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import datetime
import calendar
import hashlib
import inspect
import json
import pathlib
import re

from vivacore import versions

from .schema import (ANSWER_PROGRAM_VERSION, CAPABILITY_MANIFEST_VERSION,
                     AnswerProgram, ContractError)

SEMANTIC_REQUEST_VERSION = versions.active(
    pathlib.Path(__file__).resolve().parent.parent, "semantic_request")
SEMANTIC_OUTCOMES = ("request", "clarify", "needs_assumption",
                     "outside_domain", "unsupported")
CLARIFICATION_TAGS = ("ambiguous_account", "ambiguous_movement",
                      "ambiguous_period")
_ENTITY_PARAMETER_GROUPS = {
    "account_phrase": "accounts",
    "category": "categories",
    "movement_phrase": "counterparties",
}


def _object(properties=None, required=()):
    return {"type": "object", "properties": dict(properties or {}),
            "required": list(required), "additionalProperties": False}


_STRING = {"type": "string", "minLength": 1}
_DATE = {"type": "string", "format": "date"}


@dataclass(frozen=True)
class SemanticRequest:
    family: str
    parameters: dict
    requested_claims: tuple[str, ...]
    catalog_digest: str
    request_version: str = SEMANTIC_REQUEST_VERSION
    parameter_sources: dict = None
    entity_catalog_digest: str = ""

    def to_dict(self) -> dict:
        return {"request_version": self.request_version,
                "catalog_digest": self.catalog_digest,
                "entity_catalog_digest": self.entity_catalog_digest,
                "outcome": "request", "family": self.family,
                "parameters": dict(self.parameters),
                "parameter_sources": dict(self.parameter_sources or {}),
                "requested_claims": list(self.requested_claims)}


@dataclass(frozen=True)
class SemanticOutcome:
    kind: str
    request: SemanticRequest | None = None
    detail: dict | None = None

    def to_dict(self) -> dict:
        if self.request is not None:
            return self.request.to_dict()
        return {"request_version": SEMANTIC_REQUEST_VERSION,
                "outcome": self.kind, **dict(self.detail or {})}


@dataclass(frozen=True)
class SemanticFamily:
    id: str
    parameter_schema: dict
    claims: tuple[str, ...]
    builder: object
    runtime_selectable: bool = True
    user_label: str = ""
    user_example: str = ""

    def catalog_entry(self) -> dict:
        return {"id": self.id,
                "user_label": self.user_label,
                "user_example": self.user_example,
                "parameter_schema": dict(self.parameter_schema),
                "requested_claims": list(self.claims)}

    def report_entry(self) -> dict:
        return {**self.catalog_entry(),
                "runtime_selectable": self.runtime_selectable}


def _read(node_id, tool, args):
    return {"id": node_id, "kind": "tool_read", "depends_on": [],
            "importance": "required", "tool": tool, "args": args}


def _program(manifest, family, clauses, nodes, bindings, *, required,
             allow_partial=False):
    return AnswerProgram.from_dict({
        "program_version": ANSWER_PROGRAM_VERSION,
        "capability_manifest_version": CAPABILITY_MANIFEST_VERSION,
        "capability_manifest_digest": manifest.digest,
        "mode": "answer", "question_kind": family,
        "shape": {"clauses": clauses}, "nodes": nodes,
        "bindings": bindings, "assumptions": [], "clarification": None,
        "result_policy": {"allow_partial": allow_partial,
                          "required_clauses": required},
    })


def _rows_clause(clause_id, text, hole):
    return {"id": clause_id, "text": text,
            "slots": [{"name": hole, "type": "rows"}]}


def _rows_binding(hole, source, *, quantity="", kind="read_figures"):
    selector = {"cardinality": "one"}
    if quantity:
        selector["quantity"] = quantity
    return {"hole": hole, "source": source, "reference_kind": kind,
            "selector": selector}


def _required(request, claim_clauses):
    return list(dict.fromkeys(
        claim_clauses[claim]
        for claim in request.requested_claims))


def _named_account(request, manifest):
    wants_date = "measurement_date" in request.requested_claims
    clauses = [{
        "id": "balance_and_date" if wants_date else "balance",
        "text": ("The supported balance is {balance}, measured on {date}."
                 if wants_date else "The supported balance is {balance}."),
        "slots": ([{"name": "balance", "type": "money",
                    "quantity": "balance", "scope": ["account"]},
                   {"name": "date", "type": "date"}]
                  if wants_date else
                  [{"name": "balance", "type": "money",
                    "quantity": "balance", "scope": ["account"]}])}]
    node = _read("account_balance", "query_ledger", {
        "entity": "balances",
        "filters": {"account": request.parameters["account_phrase"]}})
    selector = {"quantity": "balance", "scope": ["account"],
                "cardinality": "one"}
    bindings = [{"hole": "balance", "source": "account_balance",
                 "reference_kind": "figure", "selector": selector}]
    if wants_date:
        bindings.append({"hole": "date", "source": "account_balance",
                         "reference_kind": "date_of", "selector": selector})
    return _program(manifest, request.family, clauses, [node], bindings,
                    required=[clauses[0]["id"]])


def _attention(request, manifest):
    clauses = [_rows_clause(
        "attention_summary",
        "These are the kinds of open questions needing attention: {items}.",
        "items")]
    nodes = [_read("attention", "check_completeness", {"view": "attention"})]
    return _program(
        manifest, request.family, clauses, nodes,
        [_rows_binding("items", "attention", quantity="count")],
        required=_required(request, {"attention_items": "attention_summary"}))


def _category_period(request, manifest):
    parameters = request.parameters
    node = _read("category_spending", "query_ledger", {
        "entity": "aggregate", "metric": "spending", "group_by": "category",
        "filters": {"category": parameters["category"],
                    "window": {"from": parameters["from"],
                               "to": parameters["to"]}}})
    clauses = [{"id": "category_total",
                "text": "Supported spending for that category and period is {total}.",
                "slots": [{"name": "total", "type": "money",
                           "quantity": "spending",
                           "scope": ["category", "period"]}]}]
    binding = {"hole": "total", "source": "category_spending",
               "reference_kind": "figure",
               "selector": {"quantity": "spending",
                            "scope": ["category", "period"],
                            "order": "largest", "cardinality": "one"}}
    return _program(manifest, request.family, clauses, [node], [binding],
                    required=_required(request, {
                        "spending": "category_total"}))


def _net_worth(request, manifest):
    clauses = [_rows_clause(
        "net_worth", "Current supported net worth by currency: {totals}.",
        "totals")]
    nodes = [_read("net_worth", "query_ledger", {
        "entity": "aggregate", "metric": "net_worth",
        "view": "net_by_currency"})]
    return _program(
        manifest, request.family, clauses, nodes,
        [_rows_binding("totals", "net_worth", quantity="net_worth")],
        required=_required(request, {"net_worth": "net_worth"}))


def _card_debt(request, manifest):
    clauses = [_rows_clause(
        "card_debt",
        "Supported card-debt totals by currency and every measured card row "
        "from that same population are {debt}.", "debt")]
    nodes = [_read("card_debt", "query_ledger", {
        "entity": "balances", "filters": {"kind": "card_account"}})]
    bindings = [_rows_binding("debt", "card_debt", quantity="owed")]
    return _program(manifest, request.family, clauses, nodes, bindings,
                    required=_required(request, {"card_debt": "card_debt"}))


def _classification(request, manifest):
    parameters = request.parameters
    args = {"movement_phrase": parameters["movement_phrase"]}
    if parameters.get("from"):
        args["from"] = parameters["from"]
    if parameters.get("to"):
        args["to"] = parameters["to"]
    clauses = [_rows_clause(
        "treatment", "The matching movement treatment and its reason are {rows}.",
        "rows")]
    nodes = [_read("treatment", "get_provenance", args)]
    return _program(
        manifest, request.family, clauses, nodes,
        [_rows_binding("rows", "treatment", quantity="movement")],
        required=_required(request, {"explanation": "treatment"}))


def _account_inventory(request, manifest):
    clauses = [
        _rows_clause("balances", "Supported asset balances by account: {assets}.",
                     "assets"),
        _rows_clause("debts", "Supported amounts owed by account: {debts}.",
                     "debts"),
        _rows_clause("completeness",
                     "Completeness gaps found in the account inventory: {gaps}.",
                     "gaps"),
    ]
    nodes = [_read("balances", "query_ledger", {"entity": "balances"}),
             _read("completeness", "check_completeness", {})]
    bindings = [_rows_binding("assets", "balances", quantity="balance"),
                _rows_binding("debts", "balances", quantity="owed"),
                _rows_binding("gaps", "completeness", quantity="count")]
    return _program(manifest, request.family, clauses, nodes, bindings,
                    required=["balances", "debts", "completeness"])


class SemanticFamilyRegistry:
    """One authority for the model catalog, schemas, builders and digests."""

    def __init__(self, entity_catalog=None, *, entity_catalog_digest=""):
        self.entity_catalog = copy.deepcopy(dict(entity_catalog or {}))
        encoded_entities = json.dumps(
            self.entity_catalog, sort_keys=True, separators=(",", ":"))
        self.entity_catalog_digest = str(entity_catalog_digest or
            hashlib.sha256(encoded_entities.encode()).hexdigest()[:16])
        self._entity_values = {
            "account_phrase": {str(item.get("id") or "") for item in
                               self.entity_catalog.get("accounts", ())},
            "category": {str(item.get("id") or "") for item in
                         self.entity_catalog.get("categories", ())},
            "movement_phrase": {str(item.get("id") or "") for item in
                                self.entity_catalog.get("counterparties", ())},
        }
        self._entity_rows = {
            name: {str(item.get("id") or ""): dict(item)
                   for item in self.entity_catalog.get(group, ())
                   if str(item.get("id") or "")}
            for name, group in _ENTITY_PARAMETER_GROUPS.items()
        }
        self._families = {
            "named_account_balance": SemanticFamily(
                "named_account_balance",
                _object({"account_phrase": _STRING}, ("account_phrase",)),
                ("balance", "measurement_date"), _named_account,
                user_label="one account's balance",
                user_example="the balance and date for one named account"),
            "needs_attention": SemanticFamily(
                "needs_attention", _object(), ("attention_items",), _attention,
                user_label="records that need attention",
                user_example="accounts or documents that need a decision"),
            "category_spending_period": SemanticFamily(
                "category_spending_period",
                _object({"category": _STRING, "from": _DATE, "to": _DATE},
                        ("category", "from", "to")),
                ("spending",), _category_period,
                user_label="spending for a category and date range",
                user_example="grocery spending in one calendar month"),
            "net_worth": SemanticFamily(
                "net_worth", _object(), ("net_worth",), _net_worth,
                user_label="net worth and exclusions",
                user_example="net worth by currency and what is excluded"),
            "credit_card_debt": SemanticFamily(
                "credit_card_debt", _object(),
                ("card_debt",), _card_debt,
                user_label="credit-card debt by card",
                user_example="card totals and the amount on every card"),
            "classification_explanation": SemanticFamily(
                "classification_explanation",
                _object({"movement_phrase": _STRING, "from": _DATE, "to": _DATE},
                        ("movement_phrase",)),
                ("explanation",), _classification,
                user_label="transaction classification explanations",
                user_example="why a purchase was treated a certain way"),
            "account_inventory": SemanticFamily(
                "account_inventory", _object(),
                ("balance", "owed", "measurement_date", "evidence_grade",
                 "completeness"), _account_inventory, runtime_selectable=False,
                user_label="a full account inventory",
                user_example="every account with its evidence status"),
        }

    @property
    def ids(self):
        return tuple(self._families)

    @property
    def supported_ids(self):
        return tuple(family.id for family in self._families.values()
                     if family.runtime_selectable)

    def get(self, family_id):
        return self._families.get(family_id)

    def supported_family_report(self):
        return tuple(self._families[name].report_entry() for name in self.ids)

    def manifest(self):
        return self.supported_family_report()

    def model_catalog(self):
        return tuple(self._families[name].catalog_entry()
                     for name in self.supported_ids)

    @property
    def catalog_digest(self):
        raw = json.dumps(self.model_catalog(), sort_keys=True,
                         separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def model_tools(self):
        tools = []
        for family_id in self.supported_ids:
            family = self._families[family_id]
            parameter_schema = self._model_parameter_schema(family)
            schema = _object({
                "parameters": parameter_schema,
                "parameter_sources": self._parameter_sources_schema(family),
                "requested_claims": {
                    "type": "array", "items": {"type": "string",
                                                   "enum": list(family.claims)},
                    "uniqueItems": True, "minItems": 1,
                    "maxItems": len(family.claims)},
            }, ("parameters", "parameter_sources", "requested_claims"))
            tools.append({"name": "select_" + family_id,
                          "description": family.user_example,
                          "parameters": schema})
        tools.extend([
            {"name": "semantic_clarification", "description": "clarify",
             "parameters": _object({"tag": {"type": "string",
                                               "enum": list(CLARIFICATION_TAGS)},
                 "question": _STRING,
                 "options": {"type": "array", "items": _object(
                     {"id": _STRING, "label": _STRING}, ("id", "label"))}},
                 ("tag", "question", "options"))},
            {"name": "semantic_assumption", "description": "assumption",
             "parameters": _object({"tag": _STRING, "label": _STRING,
                                    "question": _STRING,
                                    "type": {"type": "string",
                                             "enum": ["user_stipulation"]}},
                                   ("tag", "label", "question", "type"))},
            {"name": "semantic_outside_domain", "description": "outside_domain",
             "parameters": _object()},
            {"name": "semantic_unsupported", "description": "unsupported",
             "parameters": _object({"requested_family": _STRING},
                                   ("requested_family",))},
        ])
        return tuple(tools)

    def model_output_schema(self):
        branches = []
        for tool in self.model_tools():
            name = tool["name"]
            if not name.startswith("select_"):
                continue
            family = name[len("select_"):]
            branches.append(_object({
                "request_version": {"type": "string",
                                    "enum": [SEMANTIC_REQUEST_VERSION]},
                "catalog_digest": {"type": "string",
                                   "enum": [self.catalog_digest]},
                "entity_catalog_digest": {"type": "string",
                                           "enum": [self.entity_catalog_digest]},
                "outcome": {"type": "string", "enum": ["request"]},
                "family": {"type": "string", "enum": [family]},
                **tool["parameters"]["properties"],
            }, ("request_version", "catalog_digest", "entity_catalog_digest",
                "outcome", "family", "parameters", "parameter_sources",
                "requested_claims")))
        for branch in self.output_schema()["oneOf"]:
            if branch["properties"]["outcome"]["enum"][0] != "request":
                branches.append(copy.deepcopy(branch))
        return {"oneOf": branches}

    def output_schema(self):
        branches = []
        for family in self.supported_ids:
            definition = self._families[family]
            branches.append(_object({
                "request_version": {"type": "string",
                                    "enum": [SEMANTIC_REQUEST_VERSION]},
                "catalog_digest": {"type": "string",
                                   "enum": [self.catalog_digest]},
                "entity_catalog_digest": {"type": "string",
                                           "enum": [self.entity_catalog_digest]},
                "outcome": {"type": "string", "enum": ["request"]},
                "family": {"type": "string", "enum": [family]},
                "parameters": copy.deepcopy(definition.parameter_schema),
                "parameter_sources": self._parameter_sources_schema(definition),
                "requested_claims": {
                    "type": "array", "items": {"type": "string",
                                                  "enum": list(definition.claims)},
                    "uniqueItems": True, "minItems": 1,
                    "maxItems": len(definition.claims)},
            }, ("request_version", "catalog_digest", "entity_catalog_digest",
                "outcome", "family",
                "parameters", "parameter_sources", "requested_claims")))
        for outcome, fields, required in (
                ("clarify", {"tag": {"type": "string",
                                       "enum": list(CLARIFICATION_TAGS)},
                             "question": _STRING,
                             "options": {"type": "array", "items": _object(
                                 {"id": _STRING, "label": _STRING},
                                 ("id", "label"))}},
                 ("tag", "question", "options")),
                ("needs_assumption", {"tag": _STRING, "label": _STRING,
                                      "question": _STRING,
                                      "type": {"type": "string",
                                               "enum": ["user_stipulation"]}},
                 ("tag", "label", "question", "type")),
                ("outside_domain", {}, ()),
                ("unsupported", {"requested_family": _STRING},
                 ("requested_family",))):
            branches.append(_object({
                "request_version": {"type": "string",
                                    "enum": [SEMANTIC_REQUEST_VERSION]},
                "outcome": {"type": "string", "enum": [outcome]},
                **fields}, ("request_version", "outcome", *required)))
        return {"oneOf": branches}

    def materialize_model_output(self, raw):
        """Turn an explicit model entity reference into the canonical request."""
        held = copy.deepcopy(raw)
        if not isinstance(held, dict) or held.get("outcome") != "request":
            return held
        parameters = held.get("parameters")
        sources = held.get("parameter_sources")
        if not isinstance(parameters, dict) or not isinstance(sources, dict):
            return held
        for name, selection in tuple(parameters.items()):
            if name not in _ENTITY_PARAMETER_GROUPS:
                continue
            proof = sources.get(name)
            if not isinstance(selection, dict) or not isinstance(proof, dict):
                raise ContractError(
                    f"model entity parameter {name!r} must select a catalog id "
                    "or a grounded phrase")
            if set(selection) == {"catalog_id"}:
                if (not isinstance(selection["catalog_id"], str)
                        or not selection["catalog_id"].strip()):
                    raise ContractError(
                        f"model entity parameter {name!r} catalog_id must be "
                        "a non-empty string")
                if proof.get("derivation") != "catalog_selection":
                    raise ContractError(
                        f"model entity parameter {name!r} selected a catalog id "
                        "without catalog_selection grounding")
                parameters[name] = selection["catalog_id"]
                continue
            if (set(selection) == {"grounded_phrase"}
                    and selection.get("grounded_phrase") is True):
                if proof.get("derivation") != "verbatim":
                    raise ContractError(
                        f"model entity parameter {name!r} selected a grounded "
                        "phrase without verbatim grounding")
                quote = str(proof.get("quote") or "")
                candidates = self._catalog_candidates(name, quote)
                if len(candidates) == 1:
                    parameters[name] = candidates[0]["id"]
                    proof["derivation"] = "catalog_selection"
                else:
                    parameters[name] = quote
                continue
            raise ContractError(
                f"model entity parameter {name!r} must select a catalog id "
                "or a grounded phrase")
        return held

    def interpretations(self, outcome: SemanticOutcome) -> tuple[dict, ...]:
        request = outcome.request if outcome is not None else None
        if request is None:
            return ()
        found = []
        for name, value in request.parameters.items():
            proof = dict((request.parameter_sources or {}).get(name) or {})
            if proof.get("derivation") != "catalog_selection":
                continue
            row = self._entity_rows.get(name, {}).get(str(value))
            if row is None:
                continue
            label = self._display_label(name, row)
            quote = " ".join(str(proof.get("quote") or "").split())
            if quote and label and self._normalized(quote) != self._normalized(label):
                found.append({"parameter": name, "asked": quote[:160],
                              "matched": label[:160]})
        return tuple(found)

    def clarification_candidates(self, outcome: SemanticOutcome) -> tuple[dict, ...]:
        request = outcome.request if outcome is not None else None
        if request is None:
            return ()
        for name, value in request.parameters.items():
            proof = dict((request.parameter_sources or {}).get(name) or {})
            if (name in _ENTITY_PARAMETER_GROUPS
                    and proof.get("derivation") == "verbatim"):
                return tuple(self._catalog_candidates(name, str(value))[:3])
        return ()

    def parse(self, raw, context=None, *, require_grounding=True) -> SemanticOutcome:
        if not isinstance(raw, dict):
            raise ContractError("semantic output must be an object")
        if raw.get("request_version") != SEMANTIC_REQUEST_VERSION:
            raise ContractError("unsupported semantic request version")
        kind = str(raw.get("outcome") or "")
        if kind not in SEMANTIC_OUTCOMES:
            raise ContractError("semantic output has an unknown outcome")
        if kind == "request":
            allowed = {"request_version", "catalog_digest",
                       "entity_catalog_digest", "outcome", "family",
                       "parameters", "parameter_sources", "requested_claims"}
            self._fields(raw, allowed, allowed, "semantic request")
            if raw["catalog_digest"] != self.catalog_digest:
                raise ContractError("semantic request used a different catalog")
            if raw["entity_catalog_digest"] != self.entity_catalog_digest:
                raise ContractError(
                    "semantic request used a different entity catalog")
            family_id = str(raw["family"])
            family = self.get(family_id)
            if family is None or not family.runtime_selectable:
                return SemanticOutcome("unsupported",
                                       detail={"requested_family": family_id})
            self._validate_parameters(family.parameter_schema, raw["parameters"])
            self._validate_parameter_sources(
                raw["parameters"], raw["parameter_sources"], context,
                require_grounding=require_grounding)
            claims = raw["requested_claims"]
            if (not isinstance(claims, list) or not claims
                    or any(not isinstance(item, str) for item in claims)
                    or len(claims) != len(set(claims))
                    or not set(claims) <= set(family.claims)):
                raise ContractError(
                    "requested_claims must be a non-empty subset of the family's reviewed claims")
            request = SemanticRequest(
                family_id, dict(raw["parameters"]), tuple(claims),
                self.catalog_digest,
                parameter_sources=dict(raw["parameter_sources"]),
                entity_catalog_digest=self.entity_catalog_digest)
            return SemanticOutcome("request", request)
        required = {
            "clarify": {"request_version", "outcome", "tag", "question", "options"},
            "needs_assumption": {"request_version", "outcome", "tag", "label",
                                 "question", "type"},
            "outside_domain": {"request_version", "outcome"},
            "unsupported": {"request_version", "outcome", "requested_family"},
        }[kind]
        self._fields(raw, required, required, "semantic outcome")
        detail = {key: raw[key] for key in raw
                  if key not in {"request_version", "outcome"}}
        self._validate_non_answer(kind, detail)
        return SemanticOutcome(kind, detail=detail)

    def lower(self, outcome: SemanticOutcome, manifest) -> AnswerProgram:
        if outcome.request is not None:
            family = self._families[outcome.request.family]
            return family.builder(outcome.request, manifest)
        if outcome.kind == "clarify":
            return self._non_answer_program(
                manifest, "clarify", "semantic_clarification",
                clarification=dict(outcome.detail or {}))
        if outcome.kind == "needs_assumption":
            return self._non_answer_program(
                manifest, "needs_assumption", "semantic_assumption",
                assumptions=[dict(outcome.detail or {})])
        if outcome.kind == "outside_domain":
            return self._non_answer_program(
                manifest, "outside_domain", "outside_domain")
        raise ValueError("an unsupported semantic outcome has no executable program")

    def admission_digest(self, manifest) -> str:
        samples = {
            "named_account_balance": {"account_phrase": "Everyday account"},
            "needs_attention": {},
            "category_spending_period": {
                "category": "food", "from": "2000-01-01", "to": "2000-01-31"},
            "net_worth": {}, "credit_card_debt": {},
            "classification_explanation": {"movement_phrase": "Example shop"},
            "account_inventory": {},
        }
        programs = []
        for family_id in self.ids:
            family = self._families[family_id]
            request = SemanticRequest(family_id, samples[family_id], family.claims,
                                      self.catalog_digest)
            programs.append(self.lower(SemanticOutcome("request", request),
                                       manifest).to_dict())
        payload = {
            "catalog": self.supported_family_report(),
            "output_schema": self.output_schema(),
            "model_reference_contract": self._model_reference_contract(),
            "implementation": self._admitted_implementation_digests(),
            "programs": programs,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @classmethod
    def _model_reference_contract(cls):
        """Stable probes bind provider schema and entity matching to admission."""
        probe = cls({
            "accounts": [{"id": "account-alpha", "name": "Primary Reserve",
                          "institution": "Example Bank", "kind": "checking"}],
            "categories": [{"id": "daily-goods", "label": "Daily Goods"}],
            "counterparties": [
                {"id": "alpha", "label": "Alpha"},
                {"id": "alpha-beta", "label": "Alpha Beta"},
                {"id": "beta", "label": "Beta"},
            ],
        })

        def materialized(selection, quote, derivation):
            raw = {
                "request_version": SEMANTIC_REQUEST_VERSION,
                "catalog_digest": probe.catalog_digest,
                "entity_catalog_digest": probe.entity_catalog_digest,
                "outcome": "request",
                "family": "classification_explanation",
                "parameters": {"movement_phrase": selection},
                "parameter_sources": {"movement_phrase": {
                    "source": "question", "quote": quote,
                    "derivation": derivation}},
                "requested_claims": ["explanation"],
            }
            try:
                held = probe.materialize_model_output(raw)
            except ContractError as error:
                return {"error": str(error)}
            return {
                "parameter": held["parameters"]["movement_phrase"],
                "derivation": held["parameter_sources"]["movement_phrase"][
                    "derivation"],
            }

        phrases = (
            "Alpha Beta purchase",
            "Alpha-Beta purchase",
            "Beta near Alpha purchase",
            "Alpha nearby Beta purchase",
            "Alpha Beta",
            "unlisted merchant",
        )
        return {
            "model_output_schema": probe.model_output_schema(),
            "candidates": {
                phrase: probe._catalog_candidates("movement_phrase", phrase)
                for phrase in phrases
            },
            "materialized": {
                "catalog": materialized(
                    {"catalog_id": "alpha-beta"}, "warehouse purchase",
                    "catalog_selection"),
                "grounded_contiguous": materialized(
                    {"grounded_phrase": True}, "Alpha Beta purchase", "verbatim"),
                "grounded_reordered": materialized(
                    {"grounded_phrase": True}, "Beta near Alpha purchase", "verbatim"),
                "wrong_type": materialized(
                    {"catalog_id": 123}, "Alpha Beta", "catalog_selection"),
            },
        }

    @staticmethod
    def _admitted_implementation_digests():
        """Bind executable selection, materialization and disclosure code."""
        from vivacore.models import openai_compat
        from . import compiler, runtime

        modules = {
            "intents": inspect.getmodule(SemanticFamilyRegistry),
            "compiler": compiler,
            "runtime": runtime,
            "openai_compat": openai_compat,
        }
        return {
            name: hashlib.sha256(inspect.getsource(module).encode()).hexdigest()[:16]
            for name, module in modules.items()
        }

    @staticmethod
    def _fields(raw, allowed, required, where):
        unknown = sorted(set(raw) - set(allowed))
        missing = sorted(set(required) - set(raw))
        if unknown or missing:
            raise ContractError(f"{where} fields differ: unknown={unknown}, "
                                f"missing={missing}")

    def _model_parameter_schema(self, family):
        schema = copy.deepcopy(family.parameter_schema)
        properties = schema.get("properties", {})
        for name in set(properties) & set(_ENTITY_PARAMETER_GROUPS):
            ids = sorted(self._entity_rows.get(name, {}))
            choices = []
            if ids:
                choices.append(_object({
                    "catalog_id": {"type": "string", "enum": ids}},
                    ("catalog_id",)))
            choices.append(_object({
                "grounded_phrase": {"type": "boolean", "enum": [True]}},
                ("grounded_phrase",)))
            properties[name] = {"oneOf": choices}
        return schema

    def _catalog_candidates(self, name, phrase):
        wanted = self._normalized(phrase)
        wanted_tokens = self._tokens(phrase)
        candidates = []
        for identity, row in self._entity_rows.get(name, {}).items():
            surfaces = self._row_surfaces(name, row)
            exact = any(self._normalized(surface) == wanted for surface in surfaces)
            contained = any(
                tokens and self._contains_token_sequence(wanted_tokens, tokens)
                for tokens in (self._tokens(surface) for surface in surfaces))
            if wanted and (exact or contained):
                candidates.append({"id": identity,
                                   "label": self._display_label(name, row)})
        return sorted(candidates, key=lambda item: (item["label"], item["id"]))

    @staticmethod
    def _contains_token_sequence(haystack, needle):
        """Require catalog words to occur contiguously and in catalog order."""
        width = len(needle)
        return any(haystack[index:index + width] == needle
                   for index in range(len(haystack) - width + 1))

    @staticmethod
    def _normalized(value):
        return " ".join(str(value).casefold().split())

    @staticmethod
    def _tokens(value):
        return tuple(re.findall(r"[^\W_]+", str(value).casefold()))

    @staticmethod
    def _row_surfaces(name, row):
        if name == "account_phrase":
            return tuple(value for value in (
                row.get("id"), row.get("name"), row.get("institution")) if value)
        return tuple(value for value in (row.get("id"), row.get("label")) if value)

    @staticmethod
    def _display_label(name, row):
        if name == "account_phrase":
            return str(row.get("name") or row.get("institution") or row.get("id") or "")
        return str(row.get("label") or row.get("id") or "")

    @staticmethod
    def _validate_parameters(schema, parameters):
        if not isinstance(parameters, dict):
            raise ContractError("semantic parameters must be an object")
        properties = schema.get("properties", {})
        unknown = sorted(set(parameters) - set(properties))
        missing = sorted(set(schema.get("required", ())) - set(parameters))
        if unknown or missing:
            raise ContractError("semantic parameters differ: unknown="
                                f"{unknown}, missing={missing}")
        for name, value in parameters.items():
            if not isinstance(value, str) or not value.strip():
                raise ContractError(
                    f"semantic parameter {name!r} must be a non-empty string")
            allowed = properties.get(name, {}).get("enum")
            if allowed and value not in allowed:
                raise ContractError(
                    f"semantic parameter {name!r} is not in the supplied entity catalog")
        start, end = parameters.get("from"), parameters.get("to")
        if bool(start) != bool(end):
            raise ContractError("a semantic period needs both from and to")
        for name in ("from", "to"):
            if parameters.get(name):
                try:
                    datetime.date.fromisoformat(parameters[name])
                except ValueError as exc:
                    raise ContractError(
                        f"semantic parameter {name!r} must be an ISO date"
                    ) from exc
        if start and start > end:
            raise ContractError("semantic period starts after it ends")

    @staticmethod
    def _parameter_sources_schema(family):
        evidence = _object({
            "source": {"type": "string", "enum": ["question", "prior_turn"]},
            "turn": {"type": "integer", "minimum": 0},
            "quote": _STRING,
            "derivation": {"type": "string", "enum": [
                "verbatim", "catalog_selection", "calendar_month_start",
                "calendar_month_end"]},
        }, ("source", "quote", "derivation"))
        names = family.parameter_schema.get("properties", {})
        required = tuple(family.parameter_schema.get("required", ()))
        return _object({name: evidence for name in names}, required)

    def _validate_parameter_sources(self, parameters, sources, context,
                                    *, require_grounding):
        if not isinstance(sources, dict) or set(sources) != set(parameters):
            raise ContractError(
                "parameter_sources must prove every semantic parameter exactly")
        for name, value in parameters.items():
            proof = sources.get(name)
            if (not isinstance(proof, dict)
                    or set(proof) - {"source", "turn", "quote", "derivation"}
                    or not all(proof.get(field)
                               for field in ("source", "quote", "derivation"))):
                raise ContractError(f"semantic parameter {name!r} has invalid source")
            source = proof["source"]
            if source not in ("question", "prior_turn"):
                raise ContractError(f"semantic parameter {name!r} has unknown source")
            if source == "question" and "turn" in proof:
                raise ContractError("a question source cannot name a prior turn")
            if source == "prior_turn" and not isinstance(proof.get("turn"), int):
                raise ContractError("a prior-turn source needs its zero-based turn")
            if not require_grounding:
                continue
            if context is None:
                raise ContractError("semantic parameter grounding needs question context")
            if source == "question":
                origin = str(context.question)
            else:
                prior = tuple(context.prior_turns)
                turn = proof["turn"]
                if turn < 0 or turn >= len(prior):
                    raise ContractError("semantic parameter source names no prior turn")
                origin = " ".join(map(str, prior[turn]))
            normalize = lambda text: " ".join(str(text).casefold().split())
            quote = str(proof["quote"])
            if normalize(quote) not in normalize(origin):
                raise ContractError(
                    f"semantic parameter {name!r} quotes text not in its source")
            derivation = proof["derivation"]
            if derivation == "catalog_selection":
                if value not in self._entity_values.get(name, set()):
                    raise ContractError(
                        f"semantic parameter {name!r} was not selected from its catalog")
                continue
            if derivation == "verbatim":
                if normalize(value) != normalize(quote):
                    raise ContractError(
                        f"semantic parameter {name!r} differs from its source quote")
                continue
            if name not in ("from", "to"):
                raise ContractError("only date edges may be derived")
            parsed = None
            for pattern in ("%B %Y", "%b %Y", "%Y-%m"):
                try:
                    parsed = datetime.datetime.strptime(quote.strip(), pattern).date()
                    break
                except ValueError:
                    pass
            if parsed is None:
                raise ContractError("a derived calendar month needs a month and year")
            if derivation == "calendar_month_start":
                expected = parsed.replace(day=1)
            elif derivation == "calendar_month_end":
                expected = parsed.replace(
                    day=calendar.monthrange(parsed.year, parsed.month)[1])
            else:
                raise ContractError("unknown semantic parameter derivation")
            if value != expected.isoformat():
                raise ContractError(
                    f"semantic parameter {name!r} does not match its derived month")

    @staticmethod
    def _validate_non_answer(kind, detail):
        if kind == "clarify":
            options = detail.get("options")
            if (detail.get("tag") not in CLARIFICATION_TAGS
                    or not detail.get("question")
                    or not isinstance(options, list)
                    or any(not isinstance(item, dict)
                           or set(item) != {"id", "label"}
                           or not item["id"] or not item["label"]
                           for item in options)):
                raise ContractError("invalid semantic clarification")
        elif kind == "needs_assumption":
            if (not detail.get("tag") or not detail.get("label")
                    or not detail.get("question")
                    or detail.get("type") != "user_stipulation"):
                raise ContractError("invalid semantic assumption")
        elif kind == "unsupported" and not detail.get("requested_family"):
            raise ContractError("unsupported meaning needs a requested_family")

    @staticmethod
    def _non_answer_program(manifest, mode, question_kind, *, clarification=None,
                            assumptions=()):
        return AnswerProgram.from_dict({
            "program_version": ANSWER_PROGRAM_VERSION,
            "capability_manifest_version": CAPABILITY_MANIFEST_VERSION,
            "capability_manifest_digest": manifest.digest,
            "mode": mode, "question_kind": question_kind, "shape": None,
            "nodes": [], "bindings": [], "assumptions": list(assumptions),
            "clarification": clarification, "result_policy": {},
        })


__all__ = ["SEMANTIC_REQUEST_VERSION", "CLARIFICATION_TAGS",
           "SemanticFamily", "SemanticRequest", "SemanticOutcome",
           "SemanticFamilyRegistry"]
