"""The agent's read tools: a typed registry over the ledger projection.

Registered verbs are deterministic and local: ``query_ledger`` (the workhorse, which
answers in totals), ``list_movements`` (the individual rows, for a narrow ask),
``check_completeness``, ``get_provenance``, ``get_transparency`` and
``compute``. ``read_financial_analysis`` supplies fixed views over those reads. The measurement,
statement-coverage and projection verbs expose sourced local reads.
Verbs whose machinery does not exist yet are not registered at
all.

``default_registry(proj)`` builds the registry over one live projection;
The answer-program runtime executes admitted calls and gates every delivered
answer on current-turn evidence.
"""

from __future__ import annotations

import json

from . import ledger_tools
from .compute import COMPUTE_PARAMS, compute
from .envelope import ToolResult, refusal, weakest
from .registry import Registry, ToolSpec
from .runner import RunResult
from ..quantity import MEASURES

__all__ = ["Registry", "ToolSpec", "ToolResult", "RunResult",
           "default_registry", "refusal", "weakest"]

_NO_PARAMS = {"type": "object", "properties": {}}
_SEMANTIC_ENTITY_LIMITS = {"accounts": 128, "categories": 128,
                           "counterparties": 256}


def _semantic_entities(proj) -> dict:
    """Bounded labels the language model may use to select a canonical id.

    No balance, amount, movement row, document, or evidence field enters this
    catalog. Counts and completeness flags make truncation explicit.
    """
    accounts = sorted(({
        "id": str(info.account), "name": str(info.name or ""),
        "institution": str(info.institution or ""), "kind": str(info.kind or "")}
        for info in proj.account_infos() if info.kind), key=lambda row: row["id"])
    categories = [{"id": str(label), "label": str(label)}
                  for label in sorted(set(proj.known_categories()))]
    held_counterparties = ({str(proj.merchant_key_of(m) or "")
                            for m in proj.movements()}
                           | {str(item or "")
                              for item in proj.merchant_categories()}) - {""}
    counterparties = [{"id": str(label), "label": str(label)}
                      for label in sorted(held_counterparties)]
    groups = {"accounts": accounts, "categories": categories,
              "counterparties": counterparties}
    catalog = {
        "version": "semantic-entity-catalog-v1",
        **{name: rows[:_SEMANTIC_ENTITY_LIMITS[name]]
           for name, rows in groups.items()},
        "coverage": {name: {"count": len(rows),
                             "complete": len(rows) <= _SEMANTIC_ENTITY_LIMITS[name]}
                     for name, rows in groups.items()},
    }
    while len(json.dumps(catalog, sort_keys=True,
                         separators=(",", ":")).encode()) > 60_000:
        removable = next((name for name in
                          ("counterparties", "categories", "accounts")
                          if catalog[name]), "")
        if not removable:
            break
        catalog[removable].pop()
        catalog["coverage"][removable]["complete"] = False
    return catalog


def default_registry(proj, locale: str = "", today: str = "") -> Registry:
    """The registered read tools, bound to one projection.

    The locale travels with them because a read writes amounts of its own — a
    caveat saying how much of a total is not yet settled is a sentence with an
    amount in it — and this person's conventions decide how those are written,
    exactly as they decide it for the answer the caveat sits under.

    ``today`` bounds how far forward a read may be asked to answer; it defaults
    to the day the call is made, and is a parameter so a test does not depend
    on the day it runs."""
    registry = Registry()
    registry.set_semantic_entity_provider(lambda: _semantic_entities(proj))
    from ..answer_program.capabilities import ANALYSIS_PARAMS, read_financial_analysis
    registry.register(ToolSpec(
        name="read_financial_analysis", params=ANALYSIS_PARAMS,
        fn=lambda args: read_financial_analysis(proj, args, locale, today),
        emits={"reference_kinds": ["figure", "read", "read_figures", "date_of", "period"],
               "figure_types": ["money", "count", "rate"],
               "quantities": list(MEASURES), "entity_kinds": ["account", "merchant", "category"]},
        bounds={"max_figures": 80, "max_payload_bytes": 5000,
                "max_execution_ms": 2000}))
    from .measurements import (MEASUREMENT_PARAMS, COVERAGE_PARAMS,
                               read_account_measurements, read_statement_coverage)
    from .projections import PROJECTION_PARAMS, read_financial_projections
    for name, params, fn in (
        ("read_account_measurements", MEASUREMENT_PARAMS, read_account_measurements),
        ("read_statement_coverage", COVERAGE_PARAMS, read_statement_coverage),
        ("read_financial_projections", PROJECTION_PARAMS, read_financial_projections),
    ):
        registry.register(ToolSpec(name=name, params=params,
            fn=lambda args, fn=fn: fn(proj, args, locale, today),
            emits={"reference_kinds": ["figure", "read", "read_figures", "date_of", "period"],
                   "figure_types": ["money", "count"], "quantities": list(MEASURES),
                   "entity_kinds": ["account", "document", "merchant"]},
            bounds={"max_figures": 50, "max_payload_bytes": (50_000 if name == "read_account_measurements" else
                                                          10_000 if name == "read_financial_projections" else 5000),
                    "max_execution_ms": 2000}))
    from .scenarios import SCENARIO_PARAMS, simulate_scenario
    def resolve_scenario_account(quote):
        # Reuse the bounded held-name policy; incomplete catalogs cannot prove
        # name uniqueness. Exact held canonical identity remains checkable.
        from ..answer_program.intents import SemanticFamilyRegistry
        catalog = registry.semantic_entities()
        policy = SemanticFamilyRegistry(catalog)
        identities = {row['id'] for row in catalog.get('accounts', ())}
        if quote not in identities and catalog.get('coverage', {}).get('accounts', {}).get('complete') is False:
            return []
        return policy._account_role_candidates(quote)
    registry.register(ToolSpec(
        name="simulate_scenario", params=SCENARIO_PARAMS,
        fn=lambda args, figures, question: simulate_scenario(
            args, figures, question, account_resolver=resolve_scenario_account),
        needs_figures=True,
        emits={"reference_kinds":["figure","read","read_figures","date_of"],
               "figure_types":["money","count"], "quantities":list(MEASURES), "entity_kinds":[]},
        bounds={"max_figures":4,"max_payload_bytes":10_000,"max_execution_ms":2000}))
    registry.register(ToolSpec(
        name="query_ledger", params=ledger_tools.QUERY_LEDGER_PARAMS,
        fn=lambda args: ledger_tools.query_ledger(proj, args, locale, today),
        emits={"reference_kinds": ["figure", "entity", "read", "read_figures", "date", "date_of", "period"],
               "figure_types": ["money", "count", "rate"],
               "quantities": list(MEASURES),
               "entity_kinds": ["account", "merchant", "category", "document"]},
        bounds={"max_figures": 80, "max_payload_bytes": 5000,
                "max_execution_ms": 1000}))
    registry.register(ToolSpec(
        name="list_movements", params=ledger_tools.LIST_MOVEMENTS_PARAMS,
        fn=lambda args: ledger_tools.list_movements(proj, args, today),
        emits={"reference_kinds": ["figure", "entity", "read", "read_figures", "date", "date_of", "period"],
               "figure_types": ["money", "count"],
               "quantities": ["movement", "count"],
               "entity_kinds": ["account", "merchant", "category"]},
        bounds={"max_figures": 80, "max_payload_bytes": 5000,
                "max_execution_ms": 1000}))
    registry.register(ToolSpec(
        name="check_completeness", params=ledger_tools.COMPLETENESS_PARAMS,
        fn=lambda args: ledger_tools.check_completeness(proj, args),
        emits={"reference_kinds": ["figure", "entity", "read", "read_figures", "read_labels", "date", "date_of", "period"],
               "figure_types": ["count"], "quantities": ["count"],
               "entity_kinds": ["account", "document"]},
        bounds={"max_figures": 80, "max_payload_bytes": 5000,
                "max_execution_ms": 1000}))
    registry.register(ToolSpec(
        name="get_provenance", params=ledger_tools.PROVENANCE_PARAMS,
        fn=lambda args: ledger_tools.get_provenance(proj, args),
        emits={"reference_kinds": ["figure", "entity", "read", "read_figures", "date", "date_of", "period"],
               "figure_types": ["count", "money"],
               "quantities": ["count", "movement"],
               "entity_kinds": ["account", "document"]},
        bounds={"max_figures": 80, "max_payload_bytes": 5000,
                "max_execution_ms": 1000}))
    registry.register(ToolSpec(
        name="get_transparency", params=ledger_tools.TRANSPARENCY_PARAMS,
        fn=lambda args: ledger_tools.get_transparency(proj, args),
        emits={"reference_kinds": ["figure", "entity", "read", "read_figures", "date", "period"],
               "figure_types": ["count", "money"],
               "quantities": ["count", "gross_flow"],
               "entity_kinds": ["account", "document"]},
        bounds={"max_figures": 80, "max_payload_bytes": 5000,
                "max_execution_ms": 1000}))
    registry.register(ToolSpec(
        name="compute", params=COMPUTE_PARAMS,
        fn=compute,
        # Arithmetic reasons over the run rather than the vault: its operands
        # are figures this turn emitted and values the person supposed, so it
        # is handed both.
        needs_figures=True,
        emits={"reference_kinds": ["figure", "read", "read_figures"],
               "figure_types": ["money", "count", "rate"],
               "quantities": list(MEASURES), "entity_kinds": []},
        bounds={"max_figures": 1, "max_payload_bytes": 5000,
                "max_execution_ms": 250}))
    from ..query import FinancialQueryExecutor, default_sources
    registry.query_executor = FinancialQueryExecutor(default_sources(proj, today))
    return registry
