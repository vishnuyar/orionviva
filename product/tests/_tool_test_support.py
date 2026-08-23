"""The tool registry: validated calls, vault-vocabulary refusals, the cited
envelope, and the runner's composition gate."""

import hashlib
from decimal import Decimal

import pytest

from viva import quantity, render
from viva.ledger import (LedgerProjection, Posting, Provenance,
                         account_opened, closing_balance_observed,
                         merchant_categorized, opening_balance_observed,
                         simple_transaction, transaction_recorded,
                         transfer_linked)
from viva.ledger.events import (CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED,
                                agent_acted, category_assigned,
                                document_captured, merchant_enriched,
                                movement_tagged, position_observed,
                                question_declined, read_recorded,
                                statement_held)
from viva.ledger.projection import movement_key
from viva.persona import STOOD_BEHIND_MOMENT, moment
from viva.tools import default_registry, ledger_tools, run, weakest
from viva.tools.envelope import ToolResult, bounded, figure
from viva.tools.registry import (PACKAGE as _PACKAGE, PROMPTS, Registry,
                                 ToolSpec, descriptions)
from viva.tools.shape import (HOLE_THE_NUMBER, BadShape, Clause, Shape,
                              Slot)
from vivacore import promptstore
from vivacore import versions as _manifest

# The registry's description file is a released prompt: its text may never
# change. To edit a description, add a new version file and point the registry
# at it.
FROZEN_DESCRIPTIONS = {
    v: d for v, d in _manifest.manifest(_PACKAGE)["released"].items()
    if v.startswith("tools-")}


def _p(doc, page=1):
    return Provenance(doc, page, "r")


def _figure(results, what):
    """The figure whose description contains `what`. A planner reads numbers
    from here, not out of a payload — that is the whole contract."""
    for result in results:
        for f in result.get("figures") or []:
            if what in f["what"]:
                return f
    raise AssertionError(f"no figure described as {what!r} was emitted")


def _fig(results, what):
    """Its id — the only handle an answer is given for a number."""
    return _figure(results, what)["id"]


def _slot_of(declared) -> "Slot":
    """One hole from `(name, type)`, `(name, type, quantity)` or
    `(name, type, quantity, scope)`.

    A scope is the set of axes the sentence narrows on. One axis may be written
    as the bare word, several as a sequence of them, so a fixture says what its
    sentence is about and nothing else."""
    name, kind, *rest = declared
    measures = rest[0] if rest else ""
    over = rest[1] if len(rest) > 1 else ()
    return Slot(name=name, type=kind, quantity=measures,
                scope=frozenset([over] if isinstance(over, str) and over
                                else over))


def _shape(*clauses):
    """A shape as a planner commits one: words with typed holes, no digits.

    Each clause is `(text, [(hole name, what it holds), ...])`, where a hole
    holding a magnitude adds what that magnitude is of and what sets it is
    over. Written this way because every test below has to author its sentence
    before it has read anything, which is the property the whole mechanism
    rests on."""
    return Shape(clauses=tuple(
        Clause(text=text, slots=tuple(_slot_of(slot) for slot in slots))
        for text, slots in clauses))


def _script(shape, *calls, bind=None):
    """A planner that commits `shape`, makes `calls` in order, then binds.

    `bind` is handed the results so far and returns the bindings map, so a test
    says which established thing fills which hole and never writes a value."""
    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if len(done) < len(calls):
            tool, args = calls[len(done)]
            return {"tool": tool, "args": args}
        return {"bindings": {} if bind is None else bind(context["results"])}
    return planner


def _entity(results, label):
    """The id of a thing a read spoke about, by the handle its figures use."""
    for result in results:
        for item in result.get("identifiers") or []:
            if label in item["label"]:
                return item["id"]
    raise AssertionError(f"no thing labelled {label!r} was established")


def _statement_reply(opening, opening_date, closing, closing_date):
    """What a model returned for a statement, in the shape the parser reads.
    Coverage is derived from this, so a fixture without it holds no period —
    which is the honest outcome, not a gap in the fixture."""
    import json
    return json.dumps({"opening": {"amount_raw": opening, "date_raw": opening_date},
                       "closing": {"amount_raw": closing, "date_raw": closing_date},
                       "transactions": []})


def _events():
    evs = [
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01", institution="Northgate Bank",
                       account_number="XX4417", account_names=["R VANCE"]),
        account_opened("card", "liability", "Signature Card", "USD",
                       "2026-01-01", institution="Meridian Cards",
                       account_number="XX2291", account_names=["R VANCE"]),
        account_opened("brk", "investment", "Brokerage", "USD",
                       "2026-01-01", institution="Vantage Invest",
                       account_number="XX7734", account_names=["R VANCE"]),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        document_captured("doc-held", "held.pdf", 90, "bank_statement", 0.5,
                          "2026-02-01"),
        statement_held("doc-held", {}, None, "gap", "2026-02-01"),
        document_captured("doc-limbo", "limbo.pdf", 80, "bank_statement", 0.4,
                          "2026-02-01"),
        read_recorded("doc-jan", "model", "extract-v1", "text",
                      _statement_reply("1000.00", "2026-01-01",
                                       "600.00", "2026-01-31"),
                      0.0, 1, 1, True, None, "2026-02-01"),
        opening_balance_observed("chk", "1000.00", "2026-01-01", _p("doc-jan")),
        simple_transaction("chk", "-40.00", "GREENFIELD MARKET",
                           "2026-01-05", provenance=_p("doc-jan")),
        simple_transaction("chk", "-60.00", "GREENFIELD MARKET",
                           "2026-01-20", provenance=_p("doc-jan")),
        simple_transaction("chk", "-300.00", "CARD PAYMENT XX2291",
                           "2026-01-15", provenance=_p("doc-jan")),
        closing_balance_observed("chk", "600.00", "2026-01-31", _p("doc-jan", 6)),
        simple_transaction("card", "-300.00", "PAYMENT RECEIVED",
                           "2026-01-15", provenance=_p("doc-card")),
        position_observed("brk", "ALPHA FUND", "10", "1500.00", "USD",
                          "2026-01-31", cost_basis="1200.00",
                          provenance=_p("doc-brk")),
        merchant_enriched("greenfield market", "groceries",
                          subcategory="supermarket", occurred_at="2026-02-02"),
        agent_acted("enrich_unknown", "enrich", "brands", "done",
                    "2026-02-03", calls=2),
        question_declined("q-1", "nature", "2026-02-03", amount="300.00"),
    ]
    a = movement_key("doc-jan", "chk", "2026-01-15", Decimal("-300.00"),
                     "CARD PAYMENT XX2291", 0)
    b = movement_key("doc-card", "card", "2026-01-15", Decimal("-300.00"),
                     "PAYMENT RECEIVED", 0)
    evs.append(transfer_linked(a, b, VERIFIED, {"decided_by": "test"},
                               "2026-02-04", by="human"))
    key = movement_key("doc-jan", "chk", "2026-01-20", Decimal("-60.00"),
                       "GREENFIELD MARKET", 0)
    evs.append(movement_tagged(key, ["pantry"], "2026-02-05"))
    return evs


@pytest.fixture()
def proj():
    return LedgerProjection(_events())


@pytest.fixture()
def registry(proj):
    return default_registry(proj)


def _one_figure(registry, tool, args):
    """The figure book after one call, as the runner would stamp it."""
    result = registry.call(tool, args)
    assert result.ok, result.text
    for i, fig in enumerate(result.figures, 1):
        fig["id"] = f"f{i}"
    return {f["id"]: f for f in result.figures}




__all__ = [name for name in globals() if not name.startswith('__')]
