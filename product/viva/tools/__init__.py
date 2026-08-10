"""The agent's read tools: a typed registry over the ledger projection.

Six verbs, all deterministic, all local: ``query_ledger`` (the workhorse, which
answers in totals), ``list_movements`` (the individual rows, for a narrow ask),
``check_completeness``, ``get_provenance``, ``get_transparency`` and
``compute``. Verbs whose machinery does not exist yet are not registered at
all.

``default_registry(proj)`` builds the registry over one live projection;
``runner.run`` drives any planner over it, native or text, and gates every
answer on citation.
"""

from __future__ import annotations

from . import ledger_tools
from .compute import COMPUTE_PARAMS, compute
from .envelope import ToolResult, refusal, weakest
from .registry import Registry, ToolSpec
from .runner import RunResult, run

__all__ = ["Registry", "ToolSpec", "ToolResult", "RunResult",
           "default_registry", "refusal", "run", "weakest"]

_NO_PARAMS = {"type": "object", "properties": {}}


def default_registry(proj, locale: str = "", today: str = "") -> Registry:
    """The six read tools, bound to one projection.

    The locale travels with them because a read writes amounts of its own — a
    caveat saying how much of a total is not yet settled is a sentence with an
    amount in it — and this person's conventions decide how those are written,
    exactly as they decide it for the answer the caveat sits under.

    ``today`` bounds how far forward a read may be asked to answer; it defaults
    to the day the call is made, and is a parameter so a test does not depend
    on the day it runs."""
    registry = Registry()
    registry.register(ToolSpec(
        name="query_ledger", params=ledger_tools.QUERY_LEDGER_PARAMS,
        fn=lambda args: ledger_tools.query_ledger(proj, args, locale, today)))
    registry.register(ToolSpec(
        name="list_movements", params=ledger_tools.LIST_MOVEMENTS_PARAMS,
        fn=lambda args: ledger_tools.list_movements(proj, args)))
    registry.register(ToolSpec(
        name="check_completeness", params=_NO_PARAMS,
        fn=lambda args: ledger_tools.check_completeness(proj, args)))
    registry.register(ToolSpec(
        name="get_provenance", params=ledger_tools.PROVENANCE_PARAMS,
        fn=lambda args: ledger_tools.get_provenance(proj, args)))
    registry.register(ToolSpec(
        name="get_transparency", params=ledger_tools.TRANSPARENCY_PARAMS,
        fn=lambda args: ledger_tools.get_transparency(proj, args)))
    registry.register(ToolSpec(
        name="compute", params=COMPUTE_PARAMS,
        fn=compute,
        # Arithmetic reasons over the run rather than the vault: its operands
        # are figures this turn emitted and values the person supposed, so it
        # is handed both.
        needs_figures=True))
    return registry
