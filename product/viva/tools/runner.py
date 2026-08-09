"""The modality-neutral tool loop, and the mechanism that makes an answer a
structure the machine built rather than a sentence a model wrote.

The runner takes a *planner* — any callable that, shown the question, the tool
schemas and the results so far, returns the next step. A provider adapter doing
native tool-calling is a planner; so is a text-protocol adapter parsing a
model's JSON block; so is a scripted function in a test. The runner neither
knows nor cares which — the contract is data in, data out, and the mechanism
runs identically for all of them.

A turn has three stages, and the order is enforced rather than requested:

1. **The shape.** Before any tool is on the table, the planner commits a shape:
   clauses of literal words with typed holes in them and no digits anywhere.
   Nothing has been read, so no claim can be tailored to a figure that turned
   up, and what the shape declares is what the turn then goes looking for.
2. **The reads.** The tools appear. Everything a read establishes gets an
   identity in this run's own ledger — figures, the accounts and counterparties
   it spoke about, the days its results carry, the spans its documents attest,
   and the caveats it wrote about its own numbers.
3. **The bindings.** The planner says which thing in that ledger fills which
   hole. Every binding is a reference; not one of them is text.

What is then checked is the structure, never the sentence. Every hole has one
binding and every binding names a hole; the thing referred to exists in this
run's ledger; its type is the type the hole declared; a figure filling a hole
that asks for a magnitude measures the quantity that hole asked for; a figure
about money that stands on no record refuses. Nothing reads the words: there is
no scanning, no token matching, no list of what may be said.

Every caveat carried behind a stated figure is then placed by the runner, out
of what it already holds. No hole asks for one and no binding names one: a
shape is authored before anything is read, so whether there will be a caveat to
put in a hole is not knowable when the hole must be declared.

The quantity check is what stops a true number from being spoken as an untrue
claim — a gross sum of postings offered where the sentence says spending, a
count of documents offered where it says a proportion. It is code comparing the
tool's declaration with the shape's, both drawn from one closed list. No model
is asked to check another model's work.

A hole nothing can fill costs its clause and not the turn. The clause is
dropped and a phrase from the persona pack says what could not be established,
so a partial answer with a stated gap is the ordinary way this degrades.

And when there is no answer at all, the ordering holds there too. A refusal is
a reviewed sentence in the pack, one per machine tag, written before the turn
that needed it and chosen by the tag alone. Nothing is composed at the moment
of refusing, so a refused turn costs no model call and binds nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from vivacore import promptstore, versions

from .. import render
from ..persona import moment
from .compute import numbers_said
from .envelope import (ENTITY_ACCOUNT, ENTITY_MARKS, EXACT, HYPOTHETICAL,
                       MONEY_KINDS, ToolResult, weakest)
from .registry import PACKAGE, PROMPTS, Registry
from .shape import Shape

# One tool call per planner step. Past this the run refuses rather than
# looping.
DEFAULT_MAX_CALLS = 8

# What the planner is told the moment its shape is taken. It is text a model
# reads, so it is a file with a version like every other thing a model reads.
COMMITTED_VERSION = versions.active(PACKAGE, "shape_committed")

_ISO_DATE_LENGTH = 10


def _shape_taken() -> str:
    return promptstore.load(PROMPTS, COMMITTED_VERSION)


def _is_iso_date(value) -> bool:
    """A structural YYYY-MM-DD check — lexical, like every date comparison in
    the projection."""
    text = str(value or "")
    return (len(text) == _ISO_DATE_LENGTH and text[4] == "-" and text[7] == "-"
            and text[:4].isdigit() and text[5:7].isdigit()
            and text[8:10].isdigit())


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


@dataclass
class RunResult:
    """How a run ended: an answer that passed the checks, or a refusal."""
    answered: bool
    text: str = ""
    figures: list = field(default_factory=list)
    grade: str = ""
    refusal: str = ""
    # What went wrong, in the machine's own words, naming the hole or the
    # reference. It reaches the log and the tests, never the person.
    detail: str = ""
    transcript: list = field(default_factory=list)   # ToolResult dicts, in order
    calls: int = 0
    # What was said, as the structure it was: the shape that was committed
    # before anything was read, and what each hole was filled from. Kept so a
    # sentence can be shown standing on what it stood on, and so shapes can
    # accumulate.
    shape: dict = field(default_factory=dict)
    bindings: dict = field(default_factory=dict)
    # What each hole was actually written as, by hole name. A surface showing a
    # bound thing again — a footer under the sentence, a review screen — shows
    # the words the sentence used rather than deciding a second time how the
    # thing becomes words.
    written: dict = field(default_factory=dict)
    # The clauses that could not be filled, by hole name and declared type.
    gaps: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"answered": self.answered, "text": self.text,
                "figures": list(self.figures), "grade": self.grade,
                "refusal": self.refusal, "detail": self.detail,
                "transcript": list(self.transcript), "calls": self.calls,
                "shape": dict(self.shape), "bindings": dict(self.bindings),
                "written": dict(self.written), "gaps": list(self.gaps)}


def _same_thing(known: dict, item: dict) -> bool:
    """Whether two entities name the same thing.

    Every attribute is compared except `id`, and nothing per-kind is decided
    here: two entities carrying the same attributes are the same thing."""
    return ({k: v for k, v in known.items() if k != "id"}
            == {k: v for k, v in item.items() if k != "id"})


@dataclass
class _Ground:
    """Everything this run established, and therefore everything an answer may
    refer to.

    Every id space is the run's own and is stamped in emission order across
    every tool, so two tools can never collide and an id from another turn
    means nothing here.

    An identity belongs to a thing, not to an occurrence of one. Several reads
    speaking about the same account, or writing the same sentence about what
    their numbers do not cover, establish one account and one caveat between
    them, and it keeps the id it was first given."""

    question: str = ""                            # what the person typed
    book: dict = field(default_factory=dict)      # figure id -> figure
    entities: dict = field(default_factory=dict)  # entity id -> entity
    periods: dict = field(default_factory=dict)   # period id -> span
    caveats: dict = field(default_factory=dict)   # caveat id -> sentence
    dates: set = field(default_factory=set)       # ISO days some result carries
    # Which caveats stand behind each figure, so an answer that states a
    # number has to state what the number does not cover.
    owed: dict = field(default_factory=dict)      # figure id -> (caveat id, ...)

    def stamp(self, result: ToolResult) -> None:
        """Absorb one ok result: give an identity to every figure, entity,
        attested span and caveat it carries, and note the days it dates."""
        caveat_ids = []
        for index, sentence in enumerate(result.caveats or []):
            item = (sentence if isinstance(sentence, dict)
                    else {"text": str(sentence or "")})
            if not item["text"].strip():
                continue
            # One sentence is one caveat however many results write it, so
            # placing it once answers for every figure that owes it.
            cid = next((k for k, text in self.caveats.items()
                        if text == item["text"]), "")
            if not cid:
                cid = f"c{len(self.caveats) + 1}"
                self.caveats[cid] = item["text"]
            item["id"] = cid
            result.caveats[index] = item
            if cid not in caveat_ids:
                caveat_ids.append(cid)
        for span in result.covers or []:
            if span.get("from") and span.get("to"):
                pid = f"p{len(self.periods) + 1}"
                self.periods[pid] = {"id": pid,
                                     "account": str(span.get("account") or ""),
                                     "from": span["from"], "to": span["to"]}
        if _is_iso_date(result.dated):
            self.dates.add(result.dated)
        for fig in result.figures:
            fig["id"] = f"f{len(self.book) + 1}"
            self.book[fig["id"]] = fig
            self.owed[fig["id"]] = tuple(caveat_ids)
            if _is_iso_date(fig.get("dated")):
                self.dates.add(str(fig["dated"]))
        for index, named in enumerate(result.identifiers or []):
            item = (named if isinstance(named, dict)
                    else {"kind": ENTITY_ACCOUNT, "name": str(named)})
            mark = ENTITY_MARKS.get(item.get("kind"))
            if mark is None:
                continue
            # A thing this run already established keeps the identity it was
            # given, and the result that named it again refers to that one.
            # Every entity of a kind is built by one constructor out of the
            # projection, so equal attributes mean the same thing.
            known = next((e for e in self.entities.values()
                          if _same_thing(e, item)), None)
            if known is not None:
                result.identifiers[index] = known
                continue
            # One id space per kind, so what a thing is travels in the way it
            # is referred to rather than as a field resent on every call.
            seen = sum(1 for e in self.entities.values()
                       if e["kind"] == item["kind"])
            item["id"] = f"{mark}{seen + 1}"
            result.identifiers[index] = item
            self.entities[item["id"]] = item


# Every way a turn can end with nothing to say. The vocabulary is closed and it
# is declared here because a refusal is spoken from a reviewed sentence chosen
# by its tag: a tag with no sentence is a build failure rather than a silence
# discovered by the person it happens to.
REFUSAL_TAGS = (
    # the planner never became a usable turn
    "model_unreachable", "unparseable", "bad_plan",
    # the order was broken
    "unshaped_answer", "unshaped_read", "call_budget_exhausted",
    # the delivery was not a delivery
    "bad_delivery", "unshaped_binding", "bad_binding",
    # a hole was filled from outside this run's ledger
    "unknown_figure", "unknown_entity", "unknown_period", "unfounded_date", "unfounded_stipulation", "ungraded_figure", "wrong_kind",
    # a real figure was offered for a hole asking about something else
    "wrong_quantity",
    # the answer as a whole could not be stood behind
    "nothing_established", "uncited_figure",
)

# How a tag finds its sentence in the pack.
REFUSAL_MOMENT = "refusal_"

# The pseudo-tools a turn proceeds by. Neither is registered; neither executes
# anything. One opens the turn and one ends it.
SHAPE_TOOL = "commit_shape"
FINAL_TOOL = "deliver_answer"


def _refused(reason: str, detail: str, transcript: list, calls: int,
             shape=None) -> RunResult:
    """A turn with nothing to say, and the reviewed sentence that says so.

    The sentence is chosen by the tag, from the pack, and is held to the same
    ordering an answer is: nothing composes words at the moment of refusing.
    `detail` stays in the result for the log and the tests and never reaches
    the person."""
    return RunResult(answered=False, refusal=reason,
                     text=moment(REFUSAL_MOMENT + reason),
                     detail=detail, transcript=transcript, calls=calls,
                     shape=shape.to_dict() if shape is not None else {})


def _noted(tool: str, ok: bool, text: str) -> ToolResult:
    """What the planner is told about a step the runner handled itself."""
    return ToolResult(tool=tool, ok=ok, text=text,
                      refusal="" if ok else "bad_shape")


def run(question: str, planner, registry: Registry,
        max_calls: int = DEFAULT_MAX_CALLS, locale: str = "") -> RunResult:
    """Drive the planner until it delivers or runs out of budget. Deterministic
    given a deterministic planner.

    The reads are not on the table until a shape is committed, so the ordering
    that makes the whole mechanism safe is a property of what the planner is
    offered rather than an instruction it is asked to follow."""
    ground = _Ground(question=question)
    transcript: list[ToolResult] = []
    shape: Shape | None = None
    result = None
    while result is None:
        final_call = len(transcript) >= max_calls
        step = planner({"question": question,
                        # A read is offered only once the shape is committed.
                        "tools": registry.schemas() if shape is not None else [],
                        "descriptions_version": registry.descriptions_version,
                        "results": [t.to_dict() for t in transcript],
                        "calls_remaining": max(0, max_calls - len(transcript)),
                        "shaped": shape is not None,
                        "shape": shape.to_dict() if shape is not None else {},
                        "final_call": final_call})
        if not isinstance(step, dict):
            result = _refused("bad_plan", "The planner returned something other "
                              "than a step.",
                              [t.to_dict() for t in transcript], len(transcript),
                              shape)
        elif "refusal" in step:
            # A planner may refuse the whole run with its own machine tag — a
            # model that never produced a usable step, or one that could not be
            # reached at all. A tag outside the closed vocabulary is not a tag:
            # there are no reviewed words for it, so the turn ends as a planner
            # that could not be followed and the planner's own account of it
            # stays in the record.
            tag = str(step["refusal"])
            result = _refused(tag if tag in REFUSAL_TAGS else "bad_plan",
                              str(step.get("text", "")),
                              [t.to_dict() for t in transcript], len(transcript),
                              shape)
        elif "shape" in step:
            proposed = step["shape"]
            if not isinstance(proposed, Shape):
                result = _refused("bad_plan", "A committed shape must be a "
                                  "shape.", [t.to_dict() for t in transcript],
                                  len(transcript), shape)
                continue
            problem = _committable(shape, proposed, ground)
            transcript.append(_noted(SHAPE_TOOL, not problem,
                                     problem or _shape_taken()))
            if not problem:
                shape = proposed
        elif "bindings" in step:
            if shape is None:
                result = _refused(
                    "unshaped_answer",
                    "The turn delivered with no shape committed; a sentence is "
                    "authored before its data, never after it.",
                    [t.to_dict() for t in transcript], len(transcript))
                continue
            result = _gate(step, transcript, ground, shape, locale)
        elif "tool" in step:
            if shape is None:
                result = _refused(
                    "unshaped_read",
                    f"The planner called {step['tool']!r} before committing a "
                    "shape; nothing is read until the answer's shape is fixed.",
                    [t.to_dict() for t in transcript], len(transcript))
                continue
            if final_call:
                # The planner was shown only the terminator and asked for a
                # read anyway; there is nothing left to spend on it.
                result = _refused(
                    "call_budget_exhausted",
                    f"No answer after {max_calls} tool calls; refusing rather "
                    "than answering without grounds.",
                    [t.to_dict() for t in transcript], len(transcript), shape)
                continue
            called = registry.call(step["tool"], step.get("args"),
                                   figures=ground.book, question=question)
            transcript.append(called)
            if called.ok:
                ground.stamp(called)
        else:
            result = _refused("bad_plan", "The planner's step names neither a "
                              "shape, a tool nor a delivery.",
                              [t.to_dict() for t in transcript], len(transcript),
                              shape)
    return result


def _committable(current, proposed: Shape, ground: _Ground) -> str:
    """Whether this shape may be committed now, and why not when it may not.

    The first shape is committed only while the run holds nothing: that is what
    makes "authored before the data" a property of the machine rather than an
    instruction. A later one may only take claims away from the one in force —
    a re-shape drops a clause results contradicted, and never writes a new one
    around a figure it has now seen."""
    if current is None:
        if ground.book or ground.entities or ground.periods:
            return ("A shape is committed before anything is read, and this "
                    "run has already read. There is nothing to do with a "
                    "sentence authored around figures already in hand.")
        return ""
    from .shape import weakens
    if not weakens(current, proposed):
        return ("A second shape may only drop clauses from the one already "
                "committed, never add or reword one. A claim written after "
                "its data is the thing the order exists to prevent.")
    return ""


# ---------------------------------------------------------------- the binding

# Which reference key each kind of thing is named by. A binding is one of
# these and nothing else, so there is no field a value could arrive in. A
# caveat is not among them: this module places what a stated figure owes, so
# there is no hole for one to fill and nothing to refer to it by.
BINDING_KEYS = ("figure", "entity", "period", "date", "supposed")

# The one kind of reference a hole of each type can hold. Where a type admits
# exactly one, the type has already said what a bare value refers to, and a
# reference that arrived without its key is read as that kind. A magnitude is
# absent: a figure this run read and a value the person supposed both belong in
# a money, count or rate hole, and the key is what tells them apart.
SOLE_BINDING = {render.DATE: "date", render.PERIOD: "period",
                render.GRADE: "figure",
                render.SUPPOSED: "supposed",
                render.ACCOUNT: "entity", render.MERCHANT: "entity",
                render.CATEGORY: "entity", render.DOCUMENT: "entity"}


def _named_reference(slot, reference) -> dict | None:
    """The binding as a named reference, or None when nothing names it.

    A binding is one named reference. Where the hole's own type leaves only one
    kind it could be, a value that arrived without its name is completed with
    it; where the type admits several kinds, nothing is assumed."""
    if isinstance(reference, dict):
        return reference if len(reference) == 1 else None
    key = SOLE_BINDING.get(slot.type)
    if key is None:
        return None
    if isinstance(reference, list):
        # Every hole holds one thing.
        return None
    return {key: reference}


def _bound(slot, reference, ground: _Ground, locale: str):
    """One hole, filled — or the problem with filling it, as
    ``(written, machine tag, sentence)``.

    Every branch resolves a reference into this run's ledger and hands the
    thing to its renderer. Nothing here writes characters: the renderer does,
    once, in one place."""
    named = _named_reference(slot, reference)
    if named is None:
        return None, "bad_binding", (
            f"The hole {slot.name!r} wants {slot.type} and is bound to "
            f"{reference!r}, which names nothing. A binding names what it "
            "refers to — one of " + ", ".join(BINDING_KEYS)
            + " — as {\"figure\": \"f1\"}.")
    key, value = next(iter(named.items()))
    if key not in BINDING_KEYS:
        return None, "bad_binding", (
            f"The hole {slot.name!r} is bound by {key!r}, which refers to "
            "nothing; a binding is one of " + ", ".join(BINDING_KEYS) + ".")

    if key == "figure":
        fig = ground.book.get(str(value))
        if fig is None:
            return None, "unknown_figure", (
                f"The answer refers to a figure {str(value)!r} that no tool "
                "emitted in this run.")
        return _figure_bound(slot, fig, locale)

    if key == "entity":
        item = ground.entities.get(str(value))
        if item is None:
            return None, "unknown_entity", (
                f"The answer refers to {str(value)!r}, which is not something "
                "this run's reads spoke about.")
        if item["kind"] != slot.type:
            return None, "wrong_kind", (
                f"The hole {slot.name!r} wants {slot.type}, and {str(value)!r} "
                f"is {item['kind']}.")
        # A thing is written among the other things of its kind this run
        # established, so a renderer choosing one of several names can see
        # whether that name tells it apart from the rest.
        company = [e for e in ground.entities.values()
                   if e["kind"] == item["kind"]]
        return _ENTITY_RENDERERS[slot.type](item, company), "", ""

    if key == "period":
        span = ground.periods.get(str(value))
        if span is None:
            return None, "unknown_period", (
                f"The answer refers to a period {str(value)!r} no read is "
                "attested for.")
        if slot.type != render.PERIOD:
            return None, "wrong_kind", (
                f"The hole {slot.name!r} wants {slot.type}, and a period is a "
                "span a document answers for, never a magnitude.")
        return render.period(span["from"], span["to"]), "", ""

    if key == "date":
        if slot.type != render.DATE:
            return None, "wrong_kind", (
                f"The hole {slot.name!r} wants {slot.type}, and a day is not a "
                "magnitude.")
        if str(value) not in ground.dates:
            return None, "unfounded_date", (
                f"The answer says {str(value)!r}, a day none of this run's "
                "results carries.")
        return render.date(str(value)), "", ""

    # supposed
    if slot.type != render.SUPPOSED:
        return None, "wrong_kind", (
            f"The hole {slot.name!r} wants {slot.type}, and a value you "
            "supplied rests on your premise rather than on any record.")
    said = numbers_said(value)
    if not said or not said <= numbers_said(ground.question):
        return None, "unfounded_stipulation", (
            f"The answer treats {str(value)!r} as something you said, but this "
            "turn's question does not contain it — whole, as you wrote it.")
    if _decimal(value) is None:
        # The hole holds a figure, and the renderer writes it under this
        # person's conventions. A value carrying a grouping mark of its own has
        # already been written under someone else's, so it is refused rather
        # than read under a guess about which convention it came from.
        return None, "unfounded_stipulation", (
            f"The answer treats {str(value)!r} as a figure you supplied, and it "
            "is not a plain magnitude.")
    # The person made no declaration about what they meant, so there is nothing
    # to compare the shape's against. What the hole says it is decides how the
    # value is written instead, which is why a year and an amount stop looking
    # alike.
    return render.supposed(value, slot.quantity, locale=locale), "", ""


_ENTITY_RENDERERS = {render.ACCOUNT: lambda e, among: render.account(
                         e, among=among),
                     render.MERCHANT: lambda e, among: render.merchant(e),
                     render.CATEGORY: lambda e, among: render.category(
                         e.get("label") or e.get("name") or ""),
                     render.DOCUMENT: lambda e, among: render.document(
                         e.get("doc_type") or e.get("name") or "")}


# The term a value the arithmetic could not write exactly is spoken with: the
# pack's line for each kind of magnitude, the name that line places it by, and
# what the hedged thing still is. One entry per kind of magnitude a hole can
# hold, so a kind with nowhere to say "about" is a build failure rather than a
# figure that reaches a person looking exact.
APPROX_TERMS = {
    render.MONEY: ("approx_amount", "amount", render.Money),
    render.COUNT: ("approx_count", "count", render.Count),
    render.RATE: ("approx_rate", "rate", render.Rate),
}


def _hedged(written, fig: dict, kind: str):
    """A magnitude carrying the term that says its arithmetic did not come out
    exactly, where it did not.

    The term travels with the figure and is placed here, beside it, so nothing
    that writes a sentence has to remember to hedge and no kind of magnitude is
    hedged by a different rule from the others."""
    if fig["exactness"] == EXACT:
        return written
    key, name, produced = APPROX_TERMS[kind]
    return produced(moment(key, **{name: written}))


def _figure_bound(slot, fig: dict, locale: str):
    """A figure into a hole, once its type says the two agree.

    An amount states a currency and a plain number states none — the one
    distinction the emitters already make — so binding a count where an amount
    belongs, or the reverse, is a type error rather than a matter of wording."""
    value = _decimal(fig["value"])
    money_like = bool(fig["currency"]) or fig["kind"] == HYPOTHETICAL

    if slot.type == render.GRADE:
        if not fig["grade"]:
            return None, "ungraded_figure", (
                f"The hole {slot.name!r} asks how well {fig['what']!r} is stood "
                "behind, and it carries no grade — nothing has checked it, and "
                "saying a word here would invent one.")
        return render.grade(fig["grade"]), "", ""

    # Two declarations, compared. The tool that emitted the figure declared what
    # it measured; the shape declared what its sentence is asking for; both are
    # members of one closed list. Nothing here reads the words around the hole
    # and nothing asks a model whether a model was right — this is an equality
    # test between two strings the code itself put there.
    if slot.quantity and fig["quantity"] != slot.quantity:
        return None, "wrong_quantity", (
            f"The hole {slot.name!r} asks for {slot.quantity}, and "
            f"{fig['what']!r} measures {fig['quantity']} — the number is real "
            "and it is not a number about that.")

    if value is None:
        return None, "wrong_kind", (
            f"The hole {slot.name!r} wants {slot.type}, and {fig['what']!r} "
            "holds no magnitude.")

    if slot.type == render.MONEY:
        if not money_like:
            return None, "wrong_kind", (
                f"The hole {slot.name!r} wants an amount, and {fig['what']!r} "
                "states no currency — it is a plain number, not money.")
        written = render.money(value, fig["currency"], locale=locale)
        return _hedged(written, fig, slot.type), "", ""

    if slot.type == render.COUNT:
        # What tells a count from a proportion is the declaration, not the
        # value: a proportion that happens to come out whole is still a
        # proportion, and a count of things is still a count.
        if money_like:
            return None, "wrong_kind", (
                f"The hole {slot.name!r} counts things, and {fig['what']!r} is "
                "an amount of money.")
        return _hedged(render.count(value), fig, slot.type), "", ""

    if slot.type == render.RATE:
        if money_like:
            return None, "wrong_kind", (
                f"The hole {slot.name!r} wants a proportion, and "
                f"{fig['what']!r} is an amount of money.")
        return _hedged(render.rate(value, locale=locale), fig,
                       slot.type), "", ""

    return None, "wrong_kind", (
        f"The hole {slot.name!r} wants {slot.type}, and a figure is a "
        "magnitude.")


# ------------------------------------------------------------------- the gate


def _gate(step: dict, transcript: list, ground: _Ground, shape: Shape,
          locale: str) -> RunResult:
    """The checks on a delivery, over the structure and never the sentence."""
    dicts = [t.to_dict() for t in transcript]
    bindings = step.get("bindings")
    if not isinstance(bindings, dict):
        return _refused("bad_delivery", "The bindings must be an object naming "
                        "each hole in the shape.", dicts, len(transcript), shape)
    slots = shape.slots
    for name in bindings:
        if name not in slots:
            return _refused(
                "unshaped_binding",
                f"The delivery binds {name!r}, which is not a hole in the shape "
                "this turn committed to.", dicts, len(transcript), shape)

    written: dict = {}
    references: dict = {}
    gaps: list = []
    for name, slot in slots.items():
        if name not in bindings:
            gaps.append({"name": name, "type": slot.type})
            continue
        value, tag, detail = _bound(slot, bindings[name], ground, locale)
        if value is None:
            return _refused(tag, detail, dicts, len(transcript), shape)
        written[name] = value
        # What the answer cites and what it places are read from the binding
        # in the form the value was written from, so a reference the hole's
        # type completed answers for its records and its caveats like any
        # other.
        references[name] = _named_reference(slot, bindings[name])

    missing = {g["name"]: g["type"] for g in gaps}
    spoken, dropped = [], []
    for clause in shape.clauses:
        unfilled = [s.type for s in clause.slots if s.name in missing]
        if unfilled:
            dropped.append(unfilled[0])
            continue
        spoken.append(clause)
    if not spoken:
        return _refused("nothing_established",
                        "Every clause of the answer rests on something this "
                        "run could not establish.", dicts, len(transcript),
                        shape)

    # Only what survived asserts anything, so only what survived is answerable
    # for its records and its caveats. The holes are walked in the order the
    # sentence places them, which is the order a person reads it in.
    #
    # One figure can fill more than one hole: an amount in one clause and, in
    # another, how well that same amount is stood behind. It is one figure and
    # it is cited once.
    said = [s.name for c in spoken for s in c.slots]
    cited, seen = [], set()
    for name in said:
        reference = references[name]
        if "figure" in reference:
            fid = str(reference["figure"])
            if fid in seen:
                continue
            seen.add(fid)
            cited.append(ground.book[fid])
        elif "caveat" in reference:
            named = reference["caveat"]
            placed |= {str(c) for c in
                       (named if isinstance(named, list) else [named])}

    for fig in cited:
        # A money figure with no record behind it is refused. The other kinds
        # rest on ledger events or on the person's own premise, and are not
        # checked for records here.
        if fig["kind"] in MONEY_KINDS and not fig["record_ids"]:
            return _refused("uncited_figure",
                            f"The figure {fig['what']!r} cites no record — "
                            "every figure about your money must stand on one.",
                            dicts, len(transcript), shape)

    # What the results said their own numbers do not cover, for every figure
    # the answer stated and did not already place a caveat for. In the order
    # the figures were stated, once each however many results wrote them, and
    # verbatim — a caveat re-worded is a caveat weakened.
    owed: list = []
    for fig in cited:
        for cid in ground.owed.get(fig["id"], ()):
            if cid not in owed:
                owed.append(cid)

    text = " ".join(c.written(written) for c in spoken)
    if owed:
        text += " " + moment("answer_limits", limits=render.caveat(
            " ".join(ground.caveats[cid] for cid in owed)))
    for kind in dropped:
        # A clause nothing could fill is a disclosed gap, never a zero and
        # never a silence. What is missing is named by its kind, in the pack's
        # own words.
        text += " " + moment("answer_gap", what=moment(f"gap_{kind}"))
    return RunResult(
        answered=True, text=text.strip(),
        figures=[dict(f) for f in cited],
        grade=weakest(f["grade"] for f in cited if f["kind"] in MONEY_KINDS),
        transcript=dicts, calls=len(transcript),
        shape=shape.to_dict(),
        bindings={n: references[n] for n in said},
        written={n: str(written[n]) for n in said}, gaps=gaps)


