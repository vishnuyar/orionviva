"""Pre-data selectors bound deterministically to one source node's evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..tools.runner_delivery import _gate
from ..instrument_claims import selected_subject,CLAIM_RELATIONSHIPS


@dataclass(frozen=True)
class UnboundSelector:
    hole: str
    source: str
    reason: str

    def to_dict(self) -> dict:
        return {"hole": self.hole, "source": self.source, "reason": self.reason}


@dataclass(frozen=True)
class BindingResult:
    result: object
    bindings: dict
    unbound: tuple[UnboundSelector, ...]


class DeterministicBinder:
    def __init__(self, registry, locale: str = ""):
        self.registry = registry
        self.locale = locale

    def bind(self, program, execution) -> BindingResult:
        bound = {}
        unbound = []
        graph = execution.graph
        for binding in program.bindings:
            reference, reason = self._select(binding, graph)
            if reference is None:
                unbound.append(UnboundSelector(binding.hole, binding.source, reason))
            else:
                bound[binding.hole] = reference
        for binding in program.bindings:
            if binding.reference_kind != "measurement_date_of" or binding.hole not in bound:
                continue
            node = next(item for item in program.nodes if item.id == binding.source)
            refs = graph.references(binding.source, "read")
            if (node.kind == "tool_read" and node.tool == "query_ledger"
                    and node.args.get("entity") == "balances" and len(refs) == 1):
                fid = bound[binding.hole]["measurement_date_of"]
                graph.ground.measurement_dates[fid] = {
                    "read": refs[0], "account": node.args.get("filters", {}).get("account"),
                    "quantity": binding.selector.quantity}
        result = _gate({"bindings": bound}, execution.transcript, graph.ground,
                       program.shape, self.locale, tools=self.registry.names(),
                       result_policy=program.result_policy)
        return BindingResult(result, bound, tuple(unbound))

    def _select(self, binding, graph):
        kind = binding.reference_kind
        ids = list(graph.references(binding.source, kind))
        selector = binding.selector
        if kind=="allocation_target":
            if selector.claim!="allocation_target" or selector.quantity!="ratio":return None,"target_role_proof_required"
            values=[graph.ground.instrument_premises[i] for i in ids if i in graph.ground.instrument_premises]
            values=[p for p in values if p.get('account')==selector.entity_ref.get('id')]
            chosen,reason=self._one(values,selector)
            return ({kind:chosen['id']},"") if chosen else (None,reason)
        if kind in ("instrument_date", "instrument_text", "instrument_normalized"):
            from ..instrument_claims import CLAIMS
            contract=CLAIMS.get(selector.claim)
            if contract is None or contract.reference_kind != kind:
                return None,"instrument_claim_required"
            assertions=[graph.ground.instrument_assertions[item] for item in ids if item in graph.ground.instrument_assertions]
            assertions=[a for a in assertions if a.get("claim")==selector.claim]
            if selector.entity_ref:
                assertions=[a for a in assertions if (a.get("account")==selector.entity_ref.get("account_set_id") if set(selector.entity_ref)=={"account_set_id","set_type","member_ids"} else a.get("account")==selector.entity_ref.get("id")
                        if set(selector.entity_ref)=={"id"} else CLAIM_RELATIONSHIPS.get(a.get("claim"))==selector.entity_ref.get("role")==a.get("instrument_relationship"))]
            if selector.cardinality=="all":
                from ..instrument_evidence import SourceAssertionGroup
                if selector.order or selector.limit is not None or selector.currency or selector.quantity or selector.scope:return None,"invalid_source_assertion_group_selector"
                if not assertions:return None,"no_compatible_evidence"
                if len(assertions)>80 or len({a["account"] for a in assertions})!=1:return None,"source_assertion_group_resource_limit"
                key="source-group:"+binding.source+":"+binding.hole
                group=SourceAssertionGroup(tuple(a["id"] for a in assertions),selector.claim,assertions[0]["account"],kind,graph.ground.instrument_token)
                graph.ground.instrument_assertion_groups[key]=group
                return {kind:key},""
            chosen,reason=self._one(assertions,selector)
            return ({kind:chosen["id"]},"") if chosen else (None,reason)
        if kind in ("figure", "date_of", "measurement_date_of"):
            figures = [graph.ground.book[item] for item in ids
                       if item in graph.ground.book]
            if any(fig.get("claim") for fig in figures):
                if not selector.claim:
                    return None,"instrument_claim_required"
                figures=[fig for fig in figures if fig.get("claim")==selector.claim]
                if selector.entity_ref:
                    figures=[fig for fig in figures if selected_subject(fig,selector.entity_ref)]
            elif selector.claim:
                return None,"instrument_claim_unreachable"
            if selector.quantity:
                figures = [fig for fig in figures
                           if fig.get("quantity") == selector.quantity]
            if selector.currency:
                figures = [fig for fig in figures
                           if fig.get("currency") == selector.currency]
            if selector.scope:
                figures = [fig for fig in figures
                           if self._scope(fig) == set(selector.scope)]
            figures = self._ordered(figures, selector.order)
            chosen, reason = self._one(figures, selector)
            if chosen is None:
                return None, reason
            return ({"figure": chosen["id"]} if kind == "figure"
                    else {kind: chosen["id"]}), ""
        if kind == "entity":
            entities = [graph.ground.entities[item] for item in ids
                        if item in graph.ground.entities]
            if selector.entity_kind:
                entities = [item for item in entities
                            if item.get("kind") == selector.entity_kind]
            if selector.entity_ref:
                wanted = str(selector.entity_ref.get("id") or "")
                entities = [item for item in entities if item.get("id") == wanted]
            chosen, reason = self._one(entities, selector)
            return ({"entity": chosen["id"]}, "") if chosen else (None, reason)
        if kind == "period":
            periods = [graph.ground.periods[item] for item in ids
                       if item in graph.ground.periods]
            periods = sorted(periods, key=lambda item: (item["to"], item["id"]),
                             reverse=selector.order == "newest")
            chosen, reason = self._one(periods, selector)
            return ({"period": chosen["id"]}, "") if chosen else (None, reason)
        if kind == "date":
            dates = sorted(ids, reverse=selector.order == "newest")
            chosen, reason = self._one(dates, selector)
            return ({"date": chosen}, "") if chosen else (None, reason)
        if kind in ("read", "read_figures", "read_labels"):
            chosen, reason = self._one(ids, selector)
            if not chosen:
                return None, reason
            if kind == "read":
                return {"read": chosen}, ""
            figures = [graph.ground.book[item]
                       for item in graph.ground.readings.get(chosen, ())
                       if item in graph.ground.book]
            if any(item.get("claim") for item in figures):
                if not selector.claim:
                    return None,"instrument_claim_required"
                figures=[item for item in figures if item.get("claim")==selector.claim]
                if selector.entity_ref:
                    figures=[item for item in figures if selected_subject(item,selector.entity_ref)]
            elif selector.claim:
                return None,"instrument_claim_unreachable"
            if selector.quantity:
                figures = [item for item in figures
                           if item.get("quantity") == selector.quantity]
            if selector.currency:
                figures = [item for item in figures
                           if item.get("currency") == selector.currency]
            if selector.scope:
                figures = [item for item in figures
                           if self._scope(item) == set(selector.scope)]
            figures = self._ordered(figures, selector.order)
            if selector.limit is not None:
                figures = figures[:selector.limit]
            if not figures:
                return None, "no_compatible_evidence"
            virtual = (f"{chosen}:figures:{binding.hole}"
                       if kind == "read_figures"
                       else f"{chosen}:labels:{binding.hole}")
            graph.ground.readings[virtual] = [item["id"] for item in figures]
            return {kind: virtual}, ""
        return None, "unsupported_reference_kind"

    @staticmethod
    def _scope(fig) -> set[str]:
        boundary = fig.get("boundary") or {}
        cut = {str(item.get("kind")) for item in boundary.get("cut") or []}
        if cut:
            return cut
        return {"whole"} if boundary.get("whole") else set()

    @staticmethod
    def _ordered(figures, order):
        if order in ("largest", "smallest"):
            def magnitude(fig):
                try:
                    value = abs(Decimal(str(fig.get("value"))))
                except (InvalidOperation, ValueError):
                    value = Decimal(0)
                return value, str(fig.get("id"))
            return sorted(figures, key=magnitude, reverse=order == "largest")
        if order in ("newest", "oldest"):
            return sorted(figures,
                          key=lambda fig: (str(fig.get("dated") or ""),
                                           str(fig.get("id"))),
                          reverse=order == "newest")
        return sorted(figures, key=lambda fig: str(fig.get("id")))

    @staticmethod
    def _one(items, selector):
        if selector.limit is not None:
            items = items[:selector.limit]
        if not items:
            return None, "no_compatible_evidence"
        if len(items) > 1:
            if selector.order and (selector.limit in (None, 1)):
                return items[0], ""
            return None, "selector_not_unique"
        return items[0], ""


__all__ = ["DeterministicBinder", "BindingResult", "UnboundSelector"]
