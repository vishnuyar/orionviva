"""A sentence is a structure before it is a sentence.

The properties here are the ones the answer direction now rests on, and they
are properties of a *structure the machine built* rather than of a sentence
anybody read. Nothing below inspects prose. Between them they say: the words
carry no digits, the shape is fixed before any data exists, a second shape can
only take claims away, every hole is filled by a reference into what the run
established, a hole nothing can fill costs its clause and not the turn, and a
caveat a result wrote about its own number cannot be quietly dropped.
"""

import string
from decimal import Decimal

import pytest
from vivacore.verify.normalize import parse_amount, parse_date

from viva import quantity, render
from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)
from viva.ledger.events import document_captured
from viva.persona import (INTENT_FIELDS, ROWS_STOOD_BEHIND_MOMENT,
                          STOOD_BEHIND_MOMENT, moment)
from viva.tools import default_registry
from _legacy_answer_harness import run
from viva.tools import shape as shape_module
from viva.tools.shape import (CHOOSE_THE_QUANTITY, DROP_THE_QUANTITY,
                              FEWER_CLAUSES, HOLE_THE_CLAUSE, HOLE_THE_NUMBER,
                              MAGNITUDE_TYPES, MAX_CLAUSES, NAME_THE_QUANTITY,
                              PLAIN_TYPES, REPAIRS, SLOT_TYPES, BadShape,
                              Clause, Shape, Slot, read_shape, weakens)


def _events():
    p = Provenance("doc-jan", 1, "r")
    return [
        account_opened("chk", "depository", "Everyday Checking", "USD",
                       "2026-01-01", institution="Northgate Bank",
                       account_number="XX4417", account_names=["R VANCE"]),
        document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                          "2026-02-01"),
        opening_balance_observed("chk", "1000.00", "2026-01-01", p),
        simple_transaction("chk", "-400.00", "GREENFIELD MARKET",
                           "2026-01-05", provenance=p),
        closing_balance_observed("chk", "600.00", "2026-01-31",
                                 Provenance("doc-jan", 6, "r")),
    ]


@pytest.fixture()
def registry():
    return default_registry(LedgerProjection(_events()))


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
    """A shape as a planner commits one. Each hole is `(name, type)`, or
    `(name, type, what its number measures, what sets it is over)` where it
    holds one."""
    return Shape(clauses=tuple(
        Clause(text=text, slots=tuple(_slot_of(slot) for slot in slots))
        for text, slots in clauses))


def _script(shape, *calls, bind=None):
    def planner(context):
        if not context["shaped"]:
            return {"shape": shape}
        done = [r for r in context["results"] if r["tool"] != "commit_shape"]
        if len(done) < len(calls):
            tool, args = calls[len(done)]
            return {"tool": tool, "args": args}
        return {"bindings": {} if bind is None else bind(context["results"])}
    return planner


BALANCES = ("query_ledger", {"entity": "balances", "filters": {"account": "chk"}})

# A spending read narrowed to one counterparty and nothing else: one filter
# leaves one slice, so what comes back is the whole of that slice.
_AT_ONE_COUNTERPARTY = ("query_ledger",
                        {"entity": "aggregate", "metric": "spending",
                         "filters": {"merchant": "greenfield market"}})

# A turn that answers having read nothing. Every clause rests on something the
# run established, and a run that made no read has established one thing only:
# the value the person put into their own question.
_ASKED = "was it 40?"
_ASKED_SHAPE = (("You asked about {yours}.",
                 [("yours", "supposed", "spending")]),)
_ASKED_BINDING = {"yours": {"supposed": "40"}}


def _wide(groups: int):
    """A vault with a requested number of synthetic spending groups."""
    from viva.ledger.events import merchant_enriched
    p = Provenance("doc-jan", 1, "r")
    evs = [account_opened("chk", "depository", "Everyday Checking", "USD",
                          "2026-01-01"),
           document_captured("doc-jan", "jan.pdf", 100, "bank_statement", 0.9,
                             "2026-02-01"),
           opening_balance_observed("chk", "10000.00", "2026-01-01", p)]
    for n in range(groups):
        who = f"COUNTERPARTY {n:02d}"
        evs.append(simple_transaction("chk", f"-{10 + n}.00", who,
                                      f"2026-01-{5 + n:02d}", provenance=p))
        evs.append(merchant_enriched(who.lower(), "everything",
                                     subcategory=f"slice {n:02d}",
                                     occurred_at="2026-02-02"))
    evs.append(closing_balance_observed(
        "chk", "9000.00", "2026-01-31", Provenance("doc-jan", 6, "r")))
    return default_registry(LedgerProjection(evs))


BY_SUBCATEGORY = ("query_ledger", {"entity": "aggregate",
                                   "metric": "spending",
                                   "group_by": "subcategory"})




__all__ = [name for name in globals() if not name.startswith('__')]
