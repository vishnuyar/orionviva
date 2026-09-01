"""Pure, whole-program validation before the first financial read."""

from __future__ import annotations

from dataclasses import dataclass

from .. import render
from ..quantity import MEASURES
from ..tools.shape import SCOPES
from ..tools.registry import _validate, _without_empties
from .schema import (ANSWER_PROGRAM_VERSION, CAPABILITY_MANIFEST_VERSION,
                     REFERENCE_KINDS, AnswerProgram, AnswerResourcePolicy,
                     ProgramNode)

ORDERS = ("", "newest", "oldest", "largest", "smallest")
ENTITY_SLOTS = (render.ACCOUNT, render.MERCHANT, render.CATEGORY, render.DOCUMENT)


@dataclass(frozen=True)
class ValidationDefect:
    tag: str
    path: str
    message: str
    repairable: bool = True

    def to_dict(self) -> dict:
        return {"tag": self.tag, "path": self.path, "message": self.message,
                "repairable": self.repairable}


@dataclass(frozen=True)
class ValidationResult:
    program: AnswerProgram | None
    defects: tuple[ValidationDefect, ...] = ()
    static_cost: dict | None = None

    @property
    def ok(self) -> bool:
        return self.program is not None and not self.defects


class ProgramValidator:
    """Validate structure, capability reachability and resource cost."""

    def __init__(self, manifest, policy: AnswerResourcePolicy):
        self.manifest = manifest
        self.policy = policy

    def validate(self, program: AnswerProgram) -> ValidationResult:
        defects: list[ValidationDefect] = []
        add = lambda tag, path, message, repairable=True: defects.append(
            ValidationDefect(tag, path, message, repairable))

        if program.program_version != ANSWER_PROGRAM_VERSION:
            add("unsupported_program_version", "program_version",
                "the program version is not admitted", False)
        if program.capability_manifest_version != CAPABILITY_MANIFEST_VERSION:
            add("manifest_version_mismatch", "capability_manifest_version",
                "the capability manifest version is not admitted", False)
        if program.capability_manifest_digest != self.manifest.digest:
            add("manifest_digest_mismatch", "capability_manifest_digest",
                "the program was compiled against a different capability manifest",
                False)

        self._validate_mode(program, add)

        node_ids: set[str] = set()
        positions: dict[str, int] = {}
        for index, node in enumerate(program.nodes):
            path = f"nodes[{index}]"
            if not node.id:
                add("missing_node_id", f"{path}.id", "a node needs a stable id")
            elif node.id in node_ids:
                add("duplicate_node_id", f"{path}.id", f"node id {node.id!r} repeats")
            else:
                node_ids.add(node.id)
                positions[node.id] = index
            self._validate_node(node, path, positions, add)

        depths: dict[str, int] = {}
        importance = {node.id: node.importance for node in program.nodes}
        for index, node in enumerate(program.nodes):
            known_depths = [depths.get(dep, 0) for dep in node.depends_on]
            depths[node.id] = 1 + (max(known_depths) if known_depths else 0)
            for dep in node.depends_on:
                if dep not in positions:
                    add("unknown_dependency", f"nodes[{index}].depends_on",
                        f"dependency {dep!r} does not exist")
                elif positions[dep] >= index:
                    add("dependency_not_earlier", f"nodes[{index}].depends_on",
                        f"dependency {dep!r} must precede {node.id!r}")
                elif (node.importance == "required"
                      and importance.get(dep) != "required"):
                    add("required_depends_on_deferred",
                        f"nodes[{index}].depends_on",
                        "required work may depend only on required work")

        self._validate_bindings(program, positions, add)
        cost = self._cost(program, depths)
        self._validate_cost(cost, add)

        return ValidationResult(None if defects else program, tuple(defects), cost)

    def _validate_mode(self, program, add) -> None:
        if program.mode == "answer":
            if program.shape is None:
                add("answer_without_shape", "shape", "answer mode requires a shape")
            if program.clarification is not None:
                add("answer_with_clarification", "clarification",
                    "answer mode cannot also ask a clarification")
        elif program.mode == "clarify":
            if not program.clarification:
                add("clarification_missing", "clarification",
                    "clarify mode requires a structured clarification")
            if program.shape is not None or program.nodes or program.bindings:
                add("clarification_has_execution", "mode",
                    "clarification mode cannot carry an answer or reads")
            self._validate_clarification(program.clarification, add)
        elif program.mode == "needs_assumption":
            if not program.assumptions:
                add("assumption_missing", "assumptions",
                    "needs_assumption mode must name the missing assumption")
            if program.shape is not None or program.nodes or program.bindings:
                add("assumption_has_execution", "mode",
                    "an assumption is requested before an answer or read")
            for index, item in enumerate(program.assumptions):
                if (not isinstance(item, dict)
                        or set(item) - {"tag", "label", "question", "type"}
                        or not item.get("tag") or not item.get("question")):
                    add("invalid_assumption", f"assumptions[{index}]",
                        "an assumption needs a tag and question from its closed schema")
        elif program.mode == "outside_domain":
            if program.shape is not None or program.nodes or program.bindings:
                add("outside_domain_has_execution", "mode",
                    "outside-domain mode cannot carry an answer or reads")

        if program.shape is not None:
            clause_ids = [clause.id for clause in program.shape.clauses]
            if any(not item for item in clause_ids):
                add("missing_clause_id", "shape.clauses",
                    "every answer-program clause needs a stable id")
            if len(clause_ids) != len(set(clause_ids)):
                add("duplicate_clause_id", "shape.clauses",
                    "answer-program clause ids must be unique")
            policy = program.result_policy
            allowed = {"allow_partial", "required_clauses"}
            unknown = sorted(set(policy) - allowed)
            if unknown:
                add("unknown_result_policy", "result_policy",
                    "unknown result policy fields: " + ", ".join(unknown))
            required = policy.get("required_clauses", [])
            if not isinstance(required, list) or any(not isinstance(v, str)
                                                     for v in required):
                add("invalid_required_clauses", "result_policy.required_clauses",
                    "required_clauses must be an array of clause ids")
            else:
                for clause_id in required:
                    if clause_id not in clause_ids:
                        add("unknown_required_clause", "result_policy.required_clauses",
                            f"required clause {clause_id!r} does not exist")
            if not isinstance(policy.get("allow_partial", False), bool):
                add("invalid_partial_policy", "result_policy.allow_partial",
                    "allow_partial must be boolean")

    @staticmethod
    def _validate_clarification(payload, add):
        if not isinstance(payload, dict):
            return
        if set(payload) - {"tag", "question", "options"}:
            add("invalid_clarification", "clarification",
                "clarification has unknown fields")
        if not payload.get("tag") or not payload.get("question"):
            add("invalid_clarification", "clarification",
                "clarification needs a tag and question")
        options = payload.get("options", [])
        if (not isinstance(options, list)
                or any(not isinstance(item, dict)
                       or set(item) != {"id", "label"}
                       or not item.get("id") or not item.get("label")
                       for item in options)):
            add("invalid_clarification", "clarification.options",
                "each clarification option needs exactly id and label")

    def _validate_node(self, node: ProgramNode, path: str, positions, add) -> None:
        for dep in node.depends_on:
            if dep == node.id:
                add("dependency_cycle", f"{path}.depends_on",
                    "a node cannot depend on itself")
        if node.kind in ("tool_read", "compute"):
            if node.kind == "tool_read" and not node.tool:
                add("missing_capability", f"{path}.tool",
                    "a tool_read node must name its capability")
            if node.kind == "compute" and node.tool not in ("", "compute"):
                add("invalid_compute_capability", f"{path}.tool",
                    "a compute node may invoke only compute")
            if node.entity_kind or node.phrase or node.query or node.predicate:
                add("irrelevant_node_fields", path,
                    "a tool or compute node carries fields for another node kind")
            tool = node.tool or ("compute" if node.kind == "compute" else "")
            capability = self.manifest.get(tool)
            if capability is None:
                add("unknown_capability", f"{path}.tool",
                    f"no admitted capability is named {tool!r}")
                return
            if not capability.local_only or not capability.read_only:
                add("unsafe_capability", f"{path}.tool",
                    f"capability {tool!r} is not local and read-only", False)
            checked_args = _without_empties(capability.input_schema, node.args)
            for problem in _validate(capability.input_schema, checked_args):
                add("invalid_capability_arguments", f"{path}.args", problem)
            self._validate_symbolic(node.args, node.depends_on, f"{path}.args", add)
        elif node.kind == "resolve_entity":
            if not node.entity_kind or not node.phrase:
                add("invalid_entity_resolution", path,
                    "entity resolution requires entity_kind and phrase")
            if not node.depends_on:
                add("unscoped_entity_resolution", f"{path}.depends_on",
                    "entity resolution needs an earlier evidence source")
            if node.tool or node.args or node.query or node.predicate:
                add("irrelevant_node_fields", path,
                    "entity resolution carries fields for another node kind")
        elif node.kind == "financial_query":
            if node.tool or node.args or node.entity_kind or node.phrase or node.predicate:
                add("irrelevant_node_fields", path,
                    "financial query carries fields for another node kind")
            if not node.query:
                add("missing_financial_query", f"{path}.query",
                    "a financial_query node requires a typed query")
            else:
                try:
                    from ..query.schema import FinancialQuery
                    query = FinancialQuery.from_dict(node.query)
                except ValueError as error:
                    add("invalid_financial_query", f"{path}.query", str(error))
                else:
                    admitted_operators = {item["name"]
                                          for item in self.manifest.query_operators}
                    source_specs = {item["name"]: item
                                    for item in self.manifest.query_sources}
                    admitted_sources = set(source_specs)
                    for step in query.steps:
                        if step.op not in admitted_operators:
                            add("unknown_query_operator", f"{path}.query",
                                f"query operator {step.op!r} is not admitted")
                        if (step.op == "scan"
                                and step.args.get("source") not in admitted_sources):
                            add("unknown_query_source", f"{path}.query",
                                f"query source {step.args.get('source')!r} is not admitted")
                    self._validate_query_fields(query, source_specs,
                                                f"{path}.query", add)
        elif node.kind == "conditional":
            if not node.predicate:
                add("missing_predicate", f"{path}.predicate",
                    "a conditional requires a closed predicate")
            elif (set(node.predicate) != {"kind", "node"}
                  or node.predicate.get("kind") not in (
                      "result_nonempty", "resolved_unique")
                  or node.predicate.get("node") not in node.depends_on):
                add("invalid_predicate", f"{path}.predicate",
                    "a predicate names an admitted kind and one dependency")
            if node.tool or node.args or node.entity_kind or node.phrase or node.query:
                add("irrelevant_node_fields", path,
                    "conditional carries fields for another node kind")

    def _validate_symbolic(self, value, dependencies, path, add) -> None:
        if isinstance(value, dict):
            if set(value) == {"ref"}:
                ref = value["ref"]
                if not isinstance(ref, dict) or set(ref) != {"node", "value"}:
                    add("invalid_symbolic_reference", path,
                        "a symbolic reference names exactly node and value")
                    return
                if ref["node"] not in dependencies:
                    add("undeclared_symbolic_dependency", path,
                        f"symbolic producer {ref['node']!r} is not a dependency")
                if not isinstance(ref["value"], str) or not ref["value"]:
                    add("invalid_symbolic_value", path,
                        "a symbolic value must use a declared output name")
                return
            for key, child in value.items():
                self._validate_symbolic(child, dependencies, f"{path}.{key}", add)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._validate_symbolic(child, dependencies, f"{path}[{index}]", add)

    @staticmethod
    def _validate_query_fields(query, sources, path, add) -> None:
        """Propagate manifest fields so no bad field discovers itself after scan."""
        tables = {}
        groups = {}
        quantities = {}
        currencies = {}
        boundaries = {}

        def known(step, fields):
            unknown = sorted(set(fields) - set(tables[step.inputs[0]]))
            if unknown:
                add("unknown_query_field", path,
                    f"{step.id!r} names unknown fields: {', '.join(unknown)}")

        for step in query.steps:
            if step.op == "scan":
                spec = sources.get(step.args.get("source"))
                tables[step.id] = dict(spec.get("fields", {})) if spec else {}
                groups[step.id] = ()
                quantities[step.id] = dict(spec.get("quantities", {})) if spec else {}
                currencies[step.id] = dict(spec.get("currency_fields", {})) if spec else {}
                boundaries[step.id] = {field: "boundary" for field in
                                       quantities[step.id]}
                continue
            if not step.inputs:
                tables[step.id] = {
                    "value": "EvidenceMagnitude", "currency": "Enum", "what": "String",
                    "quantity": "Enum", "dated": "Date", "boundary": "Boundary"}
                groups[step.id] = ()
                quantities[step.id] = {}
                currencies[step.id] = {"value": "currency"}
                boundaries[step.id] = {"value": "boundary"}
                continue
            first = dict(tables.get(step.inputs[0], {}))
            group_keys = groups.get(step.inputs[0], ())
            held_quantities = dict(quantities.get(step.inputs[0], {}))
            held_currencies = dict(currencies.get(step.inputs[0], {}))
            held_boundaries = dict(boundaries.get(step.inputs[0], {}))
            if step.op == "filter":
                known(step, [step.args["predicate"]["field"]])
            elif step.op == "select":
                known(step, step.args["fields"])
                first = {name: first[name] for name in step.args["fields"]
                         if name in first}
                held_quantities = {name: value for name, value in
                                   held_quantities.items() if name in first}
                held_currencies = {name: value for name, value in
                                   held_currencies.items()
                                   if name in first and value in first}
                held_boundaries = {name: value for name, value in
                                   held_boundaries.items() if name in first}
                group_keys = tuple(name for name in group_keys if name in first)
            elif step.op == "resolve":
                known(step, [step.args["field"]])
            elif step.op == "group":
                known(step, step.args["keys"])
                group_keys = tuple(step.args["keys"])
            elif step.op == "aggregate":
                selected_groups = list(step.args.get("group_by") or group_keys)
                fields = list(selected_groups)
                if step.args.get("field"):
                    fields.append(step.args["field"])
                if step.args.get("currency_field"):
                    fields.append(step.args["currency_field"])
                known(step, fields)
                source_kind = tables.get(step.inputs[0], {}).get(
                    step.args.get("field"), "")
                if (step.args["function"] != "count"
                        and source_kind not in {"Money", "Decimal", "Count", "Rate"}):
                    add("unsafe_query_arithmetic", path,
                        "aggregate needs a statically typed numeric field")
                first = {name: first[name] for name in selected_groups
                         if name in first}
                currency = step.args.get("currency_field")
                if currency in tables.get(step.inputs[0], {}):
                    first[currency] = tables[step.inputs[0]][currency]
                first[step.args["output"]] = (
                    "Count" if step.args["function"] == "count"
                    else tables.get(step.inputs[0], {}).get(
                        step.args.get("field"), "Decimal"))
                source_field = step.args.get("field")
                output_field = step.args["output"]
                if step.args["function"] == "count":
                    held_quantities = {output_field: "count"}
                    held_currencies = {}
                else:
                    held_quantities = ({output_field:
                                        held_quantities[source_field]}
                                       if source_field in held_quantities else {})
                    currency_field = step.args.get("currency_field")
                    if first[output_field] == "Money" and (
                            not currency_field
                            or held_currencies.get(source_field)
                            != currency_field):
                        add("unsafe_money_query", path,
                            "money aggregation must name its trusted currency field")
                    held_currencies = ({output_field: currency_field}
                                       if first[output_field] == "Money"
                                       and currency_field else {})
                held_boundaries = {output_field: "boundary"}
                group_keys = ()
            elif step.op in ("sort", "rank", "top", "bottom"):
                known(step, step.args["keys"])
                if step.op == "rank":
                    first[step.args.get("field", "rank")] = "Count"
            elif step.op in ("calendar_window", "rolling_window"):
                known(step, [step.args["field"]])
            elif step.op == "join":
                known(step, [step.args["left_key"]])
                right = tables.get(step.inputs[1], {})
                if step.args["right_key"] not in right:
                    add("unknown_query_field", path,
                        f"{step.id!r} names unknown right field "
                        f"{step.args['right_key']!r}")
                prefix = step.args.get("right_prefix", "right_")
                first.update({prefix + name: kind for name, kind in right.items()})
                held_quantities.update({prefix + name: value for name, value in
                                        quantities.get(step.inputs[1], {}).items()})
                held_currencies.update({prefix + name: prefix + value
                                        for name, value in
                                        currencies.get(step.inputs[1], {}).items()})
                held_boundaries.update({prefix + name: prefix + value
                                        for name, value in
                                        boundaries.get(step.inputs[1], {}).items()})
            elif step.op in ("union_compatible", "difference", "intersection"):
                right = tables.get(step.inputs[1], {})
                if first != right:
                    add("incompatible_query_tables", path,
                        f"{step.id!r} requires compatible input tables")
                if (held_quantities != quantities.get(step.inputs[1], {})
                        or held_currencies != currencies.get(step.inputs[1], {})
                        or held_boundaries != boundaries.get(step.inputs[1], {})):
                    add("incompatible_query_tables", path,
                        f"{step.id!r} requires compatible financial types")
                known(step, step.args.get("keys") or list(first))
            elif step.op in ("delta", "percentage_change", "ratio"):
                known(step, [step.args["left"], step.args["right"]])
                left, right = step.args["left"], step.args["right"]
                if first.get(left) not in {"Money", "Decimal", "Count", "Rate"}:
                    add("unsafe_query_arithmetic", path,
                        f"{step.op} needs statically typed numeric operands")
                if left not in held_boundaries or right not in held_boundaries:
                    add("unsafe_query_arithmetic", path,
                        f"{step.op} needs trusted financial boundaries")
                if first.get(left) != first.get(right):
                    add("unsafe_query_arithmetic", path,
                        f"{step.op} needs operands of the same type")
                if (step.op != "ratio" and held_quantities.get(left)
                        and held_quantities.get(right)
                        and held_quantities[left] != held_quantities[right]):
                    add("unsafe_query_arithmetic", path,
                        f"{step.op} cannot combine different quantities")
                first[step.args["output"]] = (
                    first.get(step.args["left"], "Decimal")
                    if step.op == "delta" else "Rate")
                if held_quantities.get(left):
                    held_quantities[step.args["output"]] = (
                        held_quantities[left] if step.op == "delta"
                        else (f"ratio_of_{held_quantities[left]}"
                              if held_quantities.get(left)
                              == held_quantities.get(right) else "ratio"))
                if step.op == "delta" and first.get(left) == "Money":
                    held_currencies[step.args["output"]] = held_currencies.get(left, "")
                if left in held_boundaries:
                    held_boundaries[step.args["output"]] = held_boundaries[left]
            elif step.op == "compute":
                known(step, [step.args["left"]]
                      + ([step.args["right"]] if step.args.get("right") else []))
                operation = step.args["operation"]
                left, right = step.args["left"], step.args.get("right")
                numeric = {"Money", "Decimal", "Count", "Rate"}
                if (first.get(left) not in numeric
                        or (right and first.get(right) not in numeric)):
                    add("unsafe_query_arithmetic", path,
                        f"{operation} needs statically typed numeric operands")
                if (right and (left not in held_boundaries
                               or right not in held_boundaries)):
                    add("unsafe_query_arithmetic", path,
                        f"{operation} needs trusted financial boundaries")
                if operation in ("add", "subtract") and first.get(left) != first.get(right):
                    add("unsafe_query_arithmetic", path,
                        f"{operation} needs operands of the same type")
                first[step.args["output"]] = (
                    "Rate" if operation == "divide"
                    else first.get(left, "Decimal"))
                if held_quantities.get(left):
                    held_quantities[step.args["output"]] = (
                        (f"ratio_of_{held_quantities[left]}"
                         if held_quantities.get(left)
                         == held_quantities.get(right) else "ratio")
                        if operation == "divide" else held_quantities[left])
                if first[step.args["output"]] == "Money":
                    held_currencies[step.args["output"]] = held_currencies.get(left, "")
                source_boundary = left if first.get(left) == "Money" or not right else right
                if source_boundary in held_boundaries:
                    held_boundaries[step.args["output"]] = held_boundaries[source_boundary]
            tables[step.id] = first
            groups[step.id] = group_keys
            quantities[step.id] = held_quantities
            currencies[step.id] = held_currencies
            boundaries[step.id] = held_boundaries
        output = tables.get(query.output, {})
        emitted = [query.emit.get("value_field"), query.emit.get("what_field"),
                   query.emit.get("currency_field"), query.emit.get("dated_field")]
        unknown = sorted({item for item in emitted if item and item not in output})
        if unknown:
            add("unknown_query_emit_field", path,
                "emit names unknown fields: " + ", ".join(unknown))
        value_field = query.emit.get("value_field")
        expected_quantity = quantities.get(query.output, {}).get(value_field)
        if expected_quantity and query.emit.get("quantity") != expected_quantity:
            add("unsafe_query_quantity", path,
                "emit quantity differs from the trusted query quantity")
        if output.get(value_field) == "Money":
            expected_currency = currencies.get(query.output, {}).get(value_field)
            if (not expected_currency
                    or query.emit.get("currency_field") != expected_currency):
                add("unsafe_money_query", path,
                    "money emission must use its trusted currency field")
        if value_field and value_field not in boundaries.get(query.output, {}):
            add("unsafe_query_boundary", path,
                "emitted magnitude needs a trusted financial boundary")

    def _validate_bindings(self, program, positions, add) -> None:
        if program.shape is None:
            if program.bindings:
                add("bindings_without_shape", "bindings",
                    "bindings require an answer shape")
            return
        slots = program.shape.slots
        seen = set()
        for index, binding in enumerate(program.bindings):
            path = f"bindings[{index}]"
            slot = slots.get(binding.hole)
            if slot is None:
                add("unknown_hole", f"{path}.hole",
                    f"hole {binding.hole!r} is not in the shape")
                continue
            if binding.hole in seen:
                add("duplicate_binding", f"{path}.hole",
                    f"hole {binding.hole!r} is bound more than once")
            seen.add(binding.hole)
            if binding.source not in positions:
                add("unknown_binding_source", f"{path}.source",
                    f"source node {binding.source!r} does not exist")
                continue
            if binding.reference_kind not in REFERENCE_KINDS:
                add("unknown_reference_kind", f"{path}.reference_kind",
                    f"unknown reference kind {binding.reference_kind!r}")
                continue
            expected = self._reference_kinds_for(slot.type)
            if binding.reference_kind not in expected:
                add("incompatible_reference_kind", f"{path}.reference_kind",
                    f"{slot.type} holes accept {', '.join(expected)}")
            selector = binding.selector
            if selector.cardinality != "one" and slot.type != render.ROWS:
                add("incompatible_cardinality", f"{path}.selector.cardinality",
                    "one hole binds one thing unless it is a rows block")
            if selector.order not in ORDERS:
                add("unknown_selector_order", f"{path}.selector.order",
                    "selector order is not admitted")
            if selector.quantity and selector.quantity not in MEASURES:
                add("unknown_selector_quantity", f"{path}.selector.quantity",
                    "selector quantity is outside the closed vocabulary")
            if slot.quantity and selector.quantity != slot.quantity:
                add("selector_quantity_mismatch", f"{path}.selector.quantity",
                    f"the hole requires quantity {slot.quantity!r}")
            if slot.scope and set(selector.scope) != set(slot.scope):
                add("selector_scope_mismatch", f"{path}.selector.scope",
                    "selector scope must equal the hole scope")
            if set(selector.scope) - set(SCOPES):
                add("unknown_selector_scope", f"{path}.selector.scope",
                    "selector scope is outside the closed vocabulary")
            if slot.type in ENTITY_SLOTS and selector.entity_kind != slot.type:
                add("selector_entity_mismatch", f"{path}.selector.entity_kind",
                    f"the hole requires entity kind {slot.type!r}")

            node = program.nodes[positions[binding.source]]
            tool = node.tool or ("compute" if node.kind == "compute" else "")
            capability = self.manifest.get(tool) if tool else None
            if capability and binding.reference_kind not in capability.emits.get(
                    "reference_kinds", []):
                add("unreachable_binding", path,
                    f"{tool!r} cannot emit {binding.reference_kind!r}")
            if capability and selector.quantity and selector.quantity not in (
                    capability.emits.get("quantities") or []):
                add("unreachable_quantity", path,
                    f"{tool!r} cannot emit quantity {selector.quantity!r}")

        for name in slots:
            if name not in seen:
                add("unbound_hole", "bindings", f"hole {name!r} has no selector")

    @staticmethod
    def _reference_kinds_for(slot_type: str) -> tuple[str, ...]:
        if slot_type in (render.MONEY, render.COUNT, render.RATE):
            return ("figure",)
        if slot_type == render.SUPPOSED:
            return ("supposed",)
        if slot_type in ENTITY_SLOTS:
            return ("entity",)
        if slot_type == render.DATE:
            return ("date", "date_of")
        if slot_type == render.PERIOD:
            return ("period",)
        if slot_type == render.ROWS:
            return ("read", "read_figures")
        return ()

    def _cost(self, program, depths) -> dict:
        counts = {kind: sum(1 for node in program.nodes
                            if node.importance == kind)
                  for kind in ("required", "supporting", "optional")}
        figures = evidence = 0
        durations: dict[str, int] = {}
        for node in program.nodes:
            tool = node.tool or ("compute" if node.kind == "compute" else "")
            capability = self.manifest.get(tool) if tool else None
            if capability is not None:
                figures += int(capability.bounds.get("max_figures", 0))
                evidence += int(capability.bounds.get("max_payload_bytes", 0))
                own_ms = int(capability.bounds.get("max_execution_ms", 0))
            elif node.kind == "financial_query":
                bound = self._query_output_bound(node.query)
                figures += bound
                evidence += bound * 400
                own_ms = 5000
            else:
                own_ms = 100
            durations[node.id] = own_ms + max(
                (durations.get(dep, 0) for dep in node.depends_on), default=0)
        return {**counts, "dependency_depth": max(depths.values(), default=0),
                "max_figures": figures, "max_evidence_bytes": evidence,
                "max_execution_ms": max(durations.values(), default=0)}

    def _query_output_bound(self, raw_query) -> int:
        """A conservative row/figure bound derived without opening a source."""
        from ..query.schema import FinancialQuery

        try:
            query = FinancialQuery.from_dict(raw_query)
        except ValueError:
            return self.policy.max_figures + 1
        source_bounds = {item["name"]: int(item["max_rows"])
                         for item in self.manifest.query_sources}
        bounds = {}
        for step in query.steps:
            incoming = [bounds[item] for item in step.inputs]
            if step.op == "scan":
                bound = source_bounds.get(step.args.get("source"),
                                          self.policy.max_figures + 1)
            elif not incoming:
                bound = self.policy.max_figures
            elif step.op in ("limit", "top", "bottom"):
                bound = min(incoming[0], int(step.args.get("count", 0)))
            elif step.op == "aggregate":
                bound = incoming[0] if step.args.get("group_by") else 1
            elif step.op == "join":
                bound = incoming[0] * incoming[1]
            elif step.op == "union_compatible":
                bound = sum(incoming)
            else:
                bound = incoming[0]
            bounds[step.id] = max(0, bound)
        return min(bounds[query.output], 1_000_000)

    def _validate_cost(self, cost, add) -> None:
        limits = (("required", self.policy.max_required_nodes),
                  ("supporting", self.policy.max_supporting_nodes),
                  ("optional", self.policy.max_optional_nodes),
                  ("dependency_depth", self.policy.max_dependency_depth),
                  ("max_figures", self.policy.max_figures),
                  ("max_evidence_bytes", self.policy.max_evidence_bytes),
                  ("max_execution_ms", self.policy.max_execution_ms))
        for name, limit in limits:
            if cost[name] > limit:
                add("resource_limit", name,
                    f"{name} cost {cost[name]} exceeds admitted limit {limit}",
                    False)


__all__ = ["ProgramValidator", "ValidationDefect", "ValidationResult"]
