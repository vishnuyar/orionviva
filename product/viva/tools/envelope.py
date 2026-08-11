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

Every figure also declares **what it measures** — a balance, spending, a count
of things — from the closed vocabulary in `viva.quantity`. A grade says how
well a number is stood behind and says nothing about what the number is of, and
a real number correctly graded is still a false sentence when it is put where
something else belongs. The tool that measured it is the one that knows, so the
declaration is made here, at the emitter, and code compares it against what the
sentence asked for.

A number is not the only thing a read puts on the record. The things it spoke
about travel too, as ``identifiers`` — an account, a counterparty, a category,
a kind of document — each an **entity** with its attributes rather than a
string. An answer refers to one of them; which of its attributes a person is
shown is the renderer's decision, made in one place. So an account with a name,
a path and a masked number is one thing that can be named several ways, rather
than several names that each have to be allowed for separately.

What a figure rests on and how its arithmetic came out are two different
questions, and a figure answers both separately. ``grade`` and ``record_ids``
say what stands behind the value; ``exactness`` says whether the derivation
terminated and, when it did not, what was done to write it down. Exactness is
not a grade: it carries no evidentiary meaning and never moves one, and a
number known perfectly well can still be one no pair of decimals holds.

How much of what it claims to measure a figure was actually taken over is a
third question, and ``boundary`` answers it. A grade says how well a number is
stood behind and exactness says how its arithmetic came out; neither says how
much of the question the number answers, so a well-graded exact figure taken
over one account of six is a false sentence when it is spoken as a total. The
read that took the figure is the one that knows what set it was taken over, so
the declaration is made at the emitter, structured rather than written out — a
number's boundary has to be checkable, comparable between two answers, and
usable as the scope clause of a claim, and a sentence appended to prose is none
of those.

A refusal is a first-class result: ``ok`` is False, ``refusal`` carries a
machine tag, and ``text`` says honestly what is and is not held.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ledger import CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED
from ..quantity import MEASURES

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
#
# A result now carries an identity for every thing it spoke about, not only for
# every number it asserts, because an answer refers to a thing rather than
# spelling its name. That is one short entry per account or counterparty in
# scope — bounded by what the person holds, never by how much has moved — and
# the budget names what it pays for.
#
# It also carries, on every figure, what that figure measures. That is one word
# per number, on every remaining call of the turn, and it buys the check that
# stops a real figure being spoken as a claim about something else. Like the
# identities, it is bounded by how many numbers a read asserts rather than by
# how much the ledger holds.
PAYLOAD_TARGET = 5000

# The figure fields the model is shown. `record_ids` is not among them: an
# answer cites a figure by id and the runner resolves its records, so only their
# count travels. Neither is `boundary`: a figure's boundary is placed by the run
# beside the figure it belongs to, the same way what a figure does not cover is
# placed, so it is a property of the machine rather than something a planner is
# asked to read and remember.
MODEL_FACING_FIGURE = ("id", "value", "currency", "quantity", "kind", "grade",
                       "dated", "exactness", "what")

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


def figure(value, what: str, *, quantity: str, kind: str = FINANCIAL,
           grade: str = "", dated: str = "", currency: str = "", record_ids=(),
           exactness: str = EXACT, boundary=None) -> dict:
    """One number this result asserts, ready for the runner to stamp with an id.

    ``what`` is a short noun phrase naming the number, so an answer or a
    refusal can refer to it without restating its value. The id is assigned by
    the runner, not here: tools stay stateless and ids belong to the run.

    ``quantity`` is what the tool measured, from the closed vocabulary in
    `viva.quantity`, and it has no default. The author of the tool is the one
    who knows, and a number whose meaning nobody stated is exactly the number
    that gets put into a sentence claiming it means something else. Leaving it
    out is an error where the emitter is written rather than a surprise where
    the figure is spoken.

    A grade outside the ladder is an error here rather than a label nobody
    checks: `weakest` ignores what it does not recognise, so an unknown grade
    would travel to the person as a strength claim while counting for nothing
    in composition. An exactness nothing recognises is refused for the same
    reason, in the same place, and so is a quantity outside the vocabulary.

    ``boundary`` is what `bounded` built, or nothing. Only what that
    constructor produced is accepted, because its checks are the whole of what
    makes a boundary true and a dict assembled beside it would carry none of
    them. Nothing means no read has said what set this was taken over, which is
    not the same as saying the set is everything — a default of "whole" would
    put a coverage claim on every figure nobody made one about."""
    if boundary is not None and not isinstance(boundary, Boundary):
        raise TypeError("a figure's boundary is what `bounded` returned; a "
                        "mapping built anywhere else has passed none of the "
                        "checks that make one true")
    if grade and grade not in _STRENGTH:
        raise ValueError(f"grade {grade!r} is not on the ladder: "
                         + ", ".join(_STRENGTH))
    if exactness not in _EXACTNESS:
        raise ValueError(f"exactness {exactness!r} says nothing about how the "
                         "arithmetic came out: " + ", ".join(_EXACTNESS))
    if quantity not in MEASURES:
        raise ValueError(f"quantity {quantity!r} is not something this measures: "
                         + ", ".join(MEASURES))
    return {"id": "", "value": str(value), "currency": currency,
            "quantity": quantity, "kind": kind,
            "grade": grade if kind in GRADED_KINDS else "",
            "dated": dated, "record_ids": [str(r) for r in record_ids],
            "exactness": exactness, "boundary": dict(boundary or {}),
            "what": what}


# The kinds of thing a read can put on the record besides a number. Each is a
# type a hole in a sentence can declare, so what a read establishes and what an
# answer may refer to are one vocabulary.
ENTITY_ACCOUNT = "account"
ENTITY_MERCHANT = "merchant"
ENTITY_CATEGORY = "category"
ENTITY_DOCUMENT = "document"

ENTITY_KINDS = (ENTITY_ACCOUNT, ENTITY_MERCHANT, ENTITY_CATEGORY,
                ENTITY_DOCUMENT)

# The letter each kind's ids are stamped with, so what a thing IS travels in
# its identity rather than as a field repeated on every remaining call of the
# turn. The same economy figure ids already make.
ENTITY_MARKS = {ENTITY_ACCOUNT: "a", ENTITY_MERCHANT: "m",
                ENTITY_CATEGORY: "k", ENTITY_DOCUMENT: "d"}


def entity(kind: str, **attrs) -> dict:
    """One thing this result spoke about, ready for the runner to stamp with an
    id.

    An entity carries its attributes and never a chosen form: an account
    carries its path, the name someone gave it and the masked form of its
    number, and which of those a person reads is settled once, by the renderer,
    rather than by whichever sentence got there first."""
    if kind not in ENTITY_KINDS:
        raise ValueError(f"{kind!r} is not a kind of thing a read establishes: "
                         + ", ".join(ENTITY_KINDS))
    return {"id": "", "kind": kind,
            **{k: v for k, v in attrs.items() if v not in ("", None)}}


# How a set may be narrowed. Each member is a thing this product already has
# one way of writing — an entity a read establishes, a span, a day — and each
# has exactly one reviewed sentence that says it. The list is closed and it
# grows by editing it here; a filter with no member is a set this cannot name,
# and it says so by naming nothing rather than by naming something else.
BY_ACCOUNT = ENTITY_ACCOUNT
BY_CATEGORY = ENTITY_CATEGORY
BY_MERCHANT = ENTITY_MERCHANT
BY_PERIOD = "period"          # both edges of a span, as two days
BY_SINCE = "since"            # one edge: the day it runs from
BY_UNTIL = "until"            # one edge: the day it runs to

SELECTED_KINDS = (BY_ACCOUNT, BY_CATEGORY, BY_MERCHANT, BY_PERIOD, BY_SINCE,
                  BY_UNTIL)

# The one member that takes two days rather than one.
_TWO_ENDED = (BY_PERIOD,)

# Why something a figure claims to measure is not in it. The two differ in
# whether anything can be named that would close the gap, which is why they are
# told apart rather than merged: a figure that was refused a number knows what
# it was refused for, and one nothing ever observed has nothing to point at.
GAP_REFUSED = "refused"        # a figure was refused, and a remedy is named
GAP_UNOBSERVED = "unobserved"  # nothing has measured it, and nothing is named

GAP_REASONS = (GAP_REFUSED, GAP_UNOBSERVED)

# The reasons that must name what would close the gap. A gap nothing can close
# is honest; a gap that could name its remedy and did not is a disclosure with
# the useful half left out.
_MUST_NAME_A_REMEDY = (GAP_REFUSED,)


class Boundary(dict):
    """What `bounded` produced. A field a sentence is placed from can then be
    asked for by type, so a dict assembled anywhere else cannot pass as one."""

    __slots__ = ()


def bounded(*, whole: bool, counted: int = 0, held: int = 0, selected=(),
            unmeasured=(), unposted: int = 0) -> Boundary:
    """What one figure was taken over, and whether that set is everything the
    quantity it declares would range over.

    ``whole`` is the load-bearing word: True says the set and the quantity are
    the same thing, and there is nothing further to say. False says they are
    not, and the rest says how they differ. A total of one category is a real
    figure and it is not every movement its quantity names, so it is not whole
    however exactly it was arrived at.

    ``counted`` of ``held`` accounts is one of N: a per-account balance stated
    where a total was asked for is a true figure over the wrong set.
    ``selected`` names how the set was narrowed, each entry a member of
    ``SELECTED_KINDS`` with the thing it was narrowed to — ``value``, plus
    ``to`` for the members that take two days. ``unmeasured`` names what the
    figure claims to measure and does not include, each with why it is out and
    the document that would settle it — which a gap of a reason that has one
    must carry, and a gap of a reason that has none may not be asked for.
    ``unposted`` counts documents read and not posted: they are a gap of the
    same standing that no account can name, because such a document may be
    about an account that does not exist yet, so it is counted rather than
    listed and is said as a number of documents.

    A whole set excludes nothing, so a figure declaring one and also naming
    what it leaves out is a contradiction, and it is refused where the emitter
    is written rather than read as a disclosure by whoever places it."""
    counts = {"counted": int(counted), "held": int(held)}
    if counts["counted"] < 0 or counts["counted"] > counts["held"]:
        raise ValueError(f"a figure covering {counts['counted']} of "
                         f"{counts['held']} covers more than there is")
    chosen = [{"kind": str(item["kind"]), "value": str(item["value"]),
               "to": str(item.get("to", ""))}
              for item in selected]
    for item in chosen:
        if item["kind"] not in SELECTED_KINDS:
            raise ValueError(f"a set is not narrowed by {item['kind']!r}: "
                             + ", ".join(SELECTED_KINDS))
        if not item["value"]:
            raise ValueError("a set narrowed to something unnamed says nothing "
                             "about what it was narrowed to")
        if bool(item["to"]) != (item["kind"] in _TWO_ENDED):
            raise ValueError(f"a set narrowed by {item['kind']!r} is written "
                             "from " + ("two days" if item["kind"] in _TWO_ENDED
                                        else "one thing")
                             + ", and it carries the other number of them")
        if not item["to"]:
            del item["to"]
    left_out = [{"account": str(item["account"]),
                 "reason": str(item.get("reason", "")),
                 "settled_by": str(item.get("settled_by", ""))}
                for item in unmeasured]
    for item in left_out:
        if not item["account"]:
            raise ValueError("something left out of a figure is named; an "
                             "unnamed gap is one nobody can close")
        if item["reason"] not in GAP_REASONS:
            raise ValueError(f"{item['reason']!r} is not why something is out "
                             "of a figure: " + ", ".join(GAP_REASONS))
        if bool(item["settled_by"]) != (item["reason"] in _MUST_NAME_A_REMEDY):
            raise ValueError(
                f"a gap of reason {item['reason']!r} "
                + ("names what would close it, and this one does not"
                   if item["reason"] in _MUST_NAME_A_REMEDY
                   else "has nothing to name, and this one names something"))
    if int(unposted) < 0:
        raise ValueError("a figure cannot be short of a negative number of "
                         "documents")
    if whole and (chosen or left_out or int(unposted)
                  or counts["counted"] != counts["held"]):
        raise ValueError("a figure whose set is everything it claims to "
                         "measure cannot also name what it leaves out")
    out = Boundary(whole=bool(whole))
    if counts["held"]:
        out["accounts"] = counts
    if chosen:
        out["selected"] = chosen
    if left_out:
        out["unmeasured"] = left_out
    if int(unposted):
        out["unposted"] = int(unposted)
    return out


# What a model-facing field says when it has nothing to add. Every result is
# resent on every remaining call of the turn, so a field carrying the ordinary
# case on every figure is paid for many times over and tells the model nothing.
UNSAID = {"exactness": EXACT}


def _named(item) -> dict:
    """One entity as the model sees it: which thing it is, and one label to
    tell it from another. What kind of thing it is travels in its id.

    The label is the handle the figures use — an account's ledger path, a
    counterparty's descriptor — so a result's numbers and the things they are
    about can be matched up. It is not what a person reads: the rest of what an
    entity carries, and the choice among those forms, belongs to the renderer,
    and sending it would be paying on every remaining call of the turn for a
    choice the model does not make."""
    if not isinstance(item, dict):
        return {"id": "", "label": str(item)}
    return {"id": item.get("id", ""),
            "label": str(item.get("account") or item.get("example")
                         or item.get("label") or item.get("doc_type")
                         or item.get("name") or "")}


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
    # The things this result spoke about, each an entity with its attributes.
    # An answer refers to one of them and the renderer chooses which attribute
    # a person reads, so an entity's several names are one thing rather than
    # several strings each needing to be allowed for.
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
                "identifiers": [_named(i) for i in self.identifiers],
                "grade": self.grade, "dated": self.dated,
                "covers": [dict(c) for c in self.covers],
                "records": len(self.record_ids),
                "provenance": list(self.provenance),
                "coverage": self.coverage,
                # The sentence only. An answer cannot refer to a caveat — the
                # run places what a stated figure owes — so the identity it
                # carries internally is not a handle anything may bind.
                "caveats": [{"text": (c.get("text", "") if isinstance(c, dict)
                                      else str(c))}
                            for c in self.caveats],
                "refusal": self.refusal, "text": self.text}


def refusal(tool: str, reason: str, text: str, **extra) -> ToolResult:
    """A refusal envelope: the machine tag plus the honest sentence, and any
    context (known values, accepted shapes) the caller can act on."""
    result = ToolResult(tool=tool, ok=False, refusal=reason, text=text)
    if extra:
        result.data = dict(extra)
    return result
