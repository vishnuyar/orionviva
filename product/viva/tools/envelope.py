"""The one shape every tool returns: figures with their grades and their
sources, or a refusal that says why — never an exception across the boundary
and never a bare number.

A number a tool asserts is a *figure*: a thing with an identity, a value, what
it is, and what it rests on. An answer cites figures by id, so a number nothing
emitted has no id to cite and cannot be said at all. Four kinds of figure
exist, and the tool that emits one decides which it is:

- ``financial`` — a claim about the person's money. It stands on documents and
  accounts, it carries a grade, and it is the only kind a counterparty could
  ever be asked to rely on.
- ``activity`` — a number about the agent's own behaviour, standing on the
  ledger events that recorded it. Being wrong about it costs nothing but
  candour, so it carries no grade.
- ``computed`` — arithmetic over other figures. It stands on the records of the
  operands that actually determined it and carries the weakest grade among
  them, and being a claim about money it is refused outright when it stands on
  nothing.
- ``hypothetical`` — a value derived from something the person supposed. It
  rests on their premise, not on evidence, so it carries no grade.

Composition inherits the weakest grade among its parts, so a total built from
one unverified balance is itself unverified, and a conflicted part makes the
whole conflicted.

A number is not the only thing a read puts on the record. The *names* it used
for the things it spoke about travel too, as ``identifiers`` — an account's id,
and the masked form of its number. A name identifies rather than measures, and
it is asserted whole: what an answer may write is the form the read wrote, not
the digits inside it.

What a figure rests on and how its arithmetic came out are two different
questions, and a figure answers both separately. ``grade`` and ``record_ids``
say what stands behind the value; ``exactness`` says whether the derivation
terminated and, when it did not, what was done to write it down. Exactness is
not a grade: it carries no evidentiary meaning and never moves one, and a
number known perfectly well can still be one no pair of decimals holds.

A refusal is a first-class result: ``ok`` is False, ``refusal`` carries a
machine tag, and ``text`` says honestly what is and is not held.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ledger import CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED

FINANCIAL = "financial"
ACTIVITY = "activity"
COMPUTED = "computed"
HYPOTHETICAL = "hypothetical"

# The kinds that carry a grade. `figure` clears the grade of any other kind, so
# a figure resting on ledger events or on the person's own premise cannot pick
# one up through composition.
GRADED_KINDS = (FINANCIAL, COMPUTED)

# The kinds that make a claim about the person's money, and therefore the ones
# an answer's grade is drawn from.
MONEY_KINDS = (FINANCIAL, COMPUTED)

# The character budget one tool result aims to stay inside. Every result is
# resent in full on every model call for the rest of the turn, so a result's
# size is paid once per call the turn has left.
PAYLOAD_TARGET = 4000

# The figure fields the model is shown. `record_ids` is not among them: an
# answer cites a figure by id and the runner resolves its records, so only their
# count travels.
MODEL_FACING_FIGURE = ("id", "value", "currency", "kind", "grade", "dated",
                       "exactness", "what")

# Weakest-last, so composition takes the maximum index present. `conflicted`
# sits below `unverified`: a figure that disagrees with its own evidence is
# worse than one nothing has checked.
_STRENGTH = (VERIFIED, CORROBORATED, UNVERIFIED, CONFLICTED)

# How the arithmetic behind a figure came out. A number read off a record
# terminated by construction, so `EXACT` is what a figure carries unless a
# derivation says otherwise.
EXACT = "exact"
ROUNDED = "rounded"

_EXACTNESS = (EXACT, ROUNDED)


def weakest(grades) -> str:
    """The weakest grade present, by the ladder's order; "" when none given."""
    present = [g for g in grades if g in _STRENGTH]
    if not present:
        return ""
    return _STRENGTH[max(_STRENGTH.index(g) for g in present)]


def figure(value, what: str, kind: str = FINANCIAL, grade: str = "",
           dated: str = "", currency: str = "", record_ids=(),
           exactness: str = EXACT) -> dict:
    """One number this result asserts, ready for the runner to stamp with an id.

    ``what`` is a short noun phrase naming the number, so an answer or a
    refusal can refer to it without restating its value. The id is assigned by
    the runner, not here: tools stay stateless and ids belong to the run.

    A grade outside the ladder is an error here rather than a label nobody
    checks: `weakest` ignores what it does not recognise, so an unknown grade
    would travel to the person as a strength claim while counting for nothing
    in composition. An exactness nothing recognises is refused for the same
    reason, in the same place."""
    if grade and grade not in _STRENGTH:
        raise ValueError(f"grade {grade!r} is not on the ladder: "
                         + ", ".join(_STRENGTH))
    if exactness not in _EXACTNESS:
        raise ValueError(f"exactness {exactness!r} says nothing about how the "
                         "arithmetic came out: " + ", ".join(_EXACTNESS))
    return {"id": "", "value": str(value), "currency": currency, "kind": kind,
            "grade": grade if kind in GRADED_KINDS else "",
            "dated": dated, "record_ids": [str(r) for r in record_ids],
            "exactness": exactness, "what": what}


# What a model-facing field says when it has nothing to add. Every result is
# resent on every remaining call of the turn, so a field carrying the ordinary
# case on every figure is paid for many times over and tells the model nothing.
UNSAID = {"exactness": EXACT}


def _stated(fig: dict) -> dict:
    """One figure as the model sees it: what it asserts, and how many records
    stand behind it. A field the tool left empty, or holding nothing worth
    saying, is omitted rather than sent."""
    out = {}
    for key in MODEL_FACING_FIGURE:
        value = fig[key]
        if value != "" and value != UNSAID.get(key, ""):
            out[key] = value
    out["records"] = len(fig["record_ids"])
    return out


@dataclass
class ToolResult:
    """What a tool call returns, whichever tool ran and however it went."""

    tool: str                                   # the verb that produced this
    ok: bool                                    # False is a refusal, not an error
    data: object = None                         # JSON-safe payload
    # Every number this result asserts, each addressable by id. A number the
    # model may say is a number some tool emitted here; anything living only in
    # `data` is machinery, not a claim.
    figures: list = field(default_factory=list)
    # The names this result used for the things it spoke about, each in the
    # whole form it wrote — an account's id, and the masked form a person
    # reads. A name identifies rather than measures, and it is asserted whole:
    # a run of digits lifted out of one is a number again.
    identifiers: list = field(default_factory=list)
    grade: str = ""                             # weakest grade the data rests on
    dated: str = ""                             # the value-time the data is good as of
    # What this read is attested for, one entry per account it ranged over, as
    # {"account": id, "from": iso, "to": iso}. Coverage is a per-account fact
    # because a statement is: an answer may be complete for one account and
    # hold nothing for another, and one merged span cannot say so. A read that
    # measures a moment carries `dated` and no entries; one that ranges over
    # time carries entries and no `dated`. Empty when nothing is attested.
    covers: list = field(default_factory=list)
    record_ids: list = field(default_factory=list)   # the documents behind it
    provenance: list = field(default_factory=list)   # provenance dicts, when few
    coverage: str = ""                          # what is included and what is not
    caveats: list = field(default_factory=list)
    refusal: str = ""                           # machine tag when ok is False
    text: str = ""                              # one honest sentence

    def to_dict(self) -> dict:
        """What the model is shown, which is less than this result holds. A
        figure's `record_ids` stay behind — an answer cites the figure by id and
        the runner resolves the records — and only their count travels."""
        return {"tool": self.tool, "ok": self.ok, "data": self.data,
                "figures": [_stated(f) for f in self.figures],
                "identifiers": list(self.identifiers),
                "grade": self.grade, "dated": self.dated,
                "covers": [dict(c) for c in self.covers],
                "records": len(self.record_ids),
                "provenance": list(self.provenance),
                "coverage": self.coverage, "caveats": list(self.caveats),
                "refusal": self.refusal, "text": self.text}


def refusal(tool: str, reason: str, text: str, **extra) -> ToolResult:
    """A refusal envelope: the machine tag plus the honest sentence, and any
    context (known values, accepted shapes) the caller can act on."""
    result = ToolResult(tool=tool, ok=False, refusal=reason, text=text)
    if extra:
        result.data = dict(extra)
    return result
