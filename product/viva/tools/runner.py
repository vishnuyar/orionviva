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
that asks for a magnitude measures the quantity that hole asked for and was
taken over the set that hole declared; a figure is of the thing its own clause
names; a day and a span come from a figure the same clause states;
a figure about money that stands on no record refuses. Nothing reads the words:
there is no scanning, no token matching, no list of what may be said.

Every caveat carried behind a stated figure is then placed by the runner, out
of what it already holds. No hole asks for one and no binding names one: a
shape is authored before anything is read, so whether there will be a caveat to
put in a hole is not knowable when the hole must be declared.

A stated figure's boundary is placed the same way, and for the same reason. A
figure carries the set it was taken over and whether that set is everything it
claims to measure; where it is not, the run says so beside the number, out of
the reads' own declarations. A boundary is a property of the claim, so it is
placed by the machine rather than left to whoever wrote the sentence around it —
and beside the thing it is a property of, which is the clause that bound the
figure. Each of those sentences begins with a word pointing at what was just
read, so a pool of them at the end points at nothing, and two clauses making the
identical claim make it twice rather than once: collapsed into one, a claim
about two figures reads as a claim about whichever the person takes it for.

How many of the accounts a person holds an answer covers is the one such
statement that is not a figure's. It is a claim about the answer, computed over
what every stated figure declares, said once, and worded as being about the
answer — because a count true of one figure and placed at answer level is a
number about something else, and two of them in one answer are two counts of
one thing.

How well what was said is stood behind is placed the same way, third of the
three. One reviewed sentence states the weakest grade among every money figure
the answer stated, lines of a block included, and it is a whole sentence per
word on the ladder rather than a frame with the word dropped in, so nowhere
does a model's prose wrap a machine's word. It is said only where the answer
stated a money figure as a number in a sentence: an answer whose money figures
are all lines of one block has heard this already, above the block, and a
second sentence under it would be the same claim twice. Where both are present
the block's set sits inside the answer's, so the sentence beneath a block is
never stronger than the line above it. It lands after the boundaries and before
the limits: a word about strength heard before the extent of a claim has been
stated invites reading it as covering more than it does. Where nothing stated
carries a grade, nothing is said.

The quantity check is what stops a true number from being spoken as an untrue
claim — a gross sum of postings offered where the sentence says spending, a
count of documents offered where it says a proportion. It is code comparing the
tool's declaration with the shape's, both drawn from one closed list. No model
is asked to check another model's work.

Two further comparisons run off that same vocabulary. A quotient of two unlike
kinds carries the name the vocabulary gives to having no name, and every hole
that could hold one writes a proportion in a unit: a number no name is true of
has no unit, so picking one would invent the claim the sentence is read as
making, and the binding is refused. And a quantity whose own name asserts which
way the money goes says so where the vocabulary is declared; a value denying
that name fills no hole asking for it, so a card paid past its balance is not
spoken as a debt of that size. Neither reads a word of the sentence.

The scope check is that move made a second time, over what a number is a number
OF. A figure declares every axis it was cut by and a hole declares every axis
its sentence narrows on, and the two sets are equal or the figure is not what
the sentence is about; a hole asking for the whole takes only a figure that says
it is the whole. Equality both ways is the whole of it, so one counterparty's
total for one month fills neither a hole about that counterparty nor a hole
about that month, and a figure that states no set at all fills none of them.

The subject check is the same comparison one step in, and the clause is its
unit, because every hole above was resolved on its own against everything the
run established. Where a clause states a figure and names a thing of a kind that
figure was cut by, the figure's own boundary must name what the clause names, on
every axis it was cut by. An entity belongs to a figure when the figure's own
boundary names it; both halves are strings the code wrote, and the words around
them are read by nothing.

A day and a span belong to the figure beside them. A date hole is filled from
the `dated` of a figure its own clause states, and a period hole from a span
such a figure was taken over — never from the days or the spans the turn as a
whole happens to carry. A day one read stamped on its own totals is a real day
and it answers a different question when it is put beside a balance months
older; a clause that states no dated figure therefore has no day to say, so the
hole is left unbound and costs its clause, and a day reached for from elsewhere
refuses the turn as any other binding fault does.

A hole nothing can fill costs its clause and not the turn. The clause is
dropped and a phrase from the persona pack says what could not be established,
so a partial answer with a stated gap is the ordinary way this degrades.

And when there is no answer at all, the ordering holds there too. A refusal is
a reviewed sentence in the pack, one per machine tag, written before the turn
that needed it and chosen by the tag alone. Nothing is composed at the moment
of refusing, so a refused turn costs no model call and binds nothing.

A turn that ends with nothing says the cause as well as the verdict, where a
read can account for it. The read that stopped last says why in its own machine
tag, and where that tag is one whose cause may be spoken the pack holds a second
reviewed sentence for it, placed after the verdict. It is the same rule one call
frame lower down: the words are chosen by a tag and exist in the repo before the
turn begins, and no value a read was called with is ever in them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from vivacore import promptstore, versions

from .. import quantity, render
from ..persona import STOOD_BEHIND_MOMENT, moment
from .compute import numbers_said
from .envelope import (BY_ACCOUNT, BY_CATEGORY, BY_CURRENCY, BY_MERCHANT,
                       BY_PERIOD, BY_SINCE, BY_SUBCATEGORY, BY_TAG, BY_UNTIL,
                       ENTITY_ACCOUNT, ENTITY_MARKS, EXACT, HYPOTHETICAL,
                       MONEY_KINDS, SPEAKABLE_REFUSALS, ToolResult, _named,
                       weakest)
from .registry import PACKAGE, PROMPTS, Registry
from .shape import WHOLE, Shape

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
    # The tag of the read whose own account of stopping was spoken, empty when
    # none was. Machine words for the log, the debug reader and the tests, never
    # for the person, exactly as `detail` is. Empty means no cause was spoken —
    # not that no read refused.
    diagnosis: str = ""
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
                "refusal": self.refusal, "diagnosis": self.diagnosis,
                "detail": self.detail,
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
    # Each read this run made, in call order, as the figures it emitted. A read
    # is a thing in its own right and not only a bag of things, because how many
    # figures it will hold is not knowable when a sentence is authored. Unlike
    # the others this is an occurrence rather than a thing: two identical reads
    # are two readings, since a person shown a block of rows is being shown one
    # particular reading of their ledger.
    readings: dict = field(default_factory=dict)  # reading id -> figure ids
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
        result.id = f"r{len(self.readings) + 1}"
        for fig in result.figures:
            fig["id"] = f"f{len(self.book) + 1}"
            self.book[fig["id"]] = fig
            self.owed[fig["id"]] = tuple(caveat_ids)
            if _is_iso_date(fig.get("dated")):
                self.dates.add(str(fig["dated"]))
        self.readings[result.id] = [fig["id"] for fig in result.figures]
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
    "unknown_figure", "unknown_entity", "unknown_period", "unknown_reading",
    "unfounded_date", "unfounded_stipulation", "wrong_kind",
    # a real figure was offered for a hole asking about something else
    "wrong_quantity", "wrong_scope", "wrong_subject",
    # the answer as a whole could not be stood behind
    "nothing_established", "uncited_figure",
)

# How a tag finds its sentence in the pack. A turn's own tag finds the verdict;
# a read's tag finds the cause, in a namespace of its own so that neither set of
# sentences can be reached by the other's tag.
REFUSAL_MOMENT = "refusal_"
DIAGNOSIS_MOMENT = "diagnosis_"

# The pseudo-tools a turn proceeds by. Neither is registered; neither executes
# anything. One opens the turn and one ends it.
SHAPE_TOOL = "commit_shape"
FINAL_TOOL = "deliver_answer"


def _refused(reason: str, detail: str, transcript: list, calls: int,
             shape=None, diagnosis: str = "") -> RunResult:
    """A turn with nothing to say, and the reviewed sentence that says so.

    The sentence is chosen by the tag, from the pack, and is held to the same
    ordering an answer is: nothing composes words at the moment of refusing.
    `detail` stays in the result for the log and the tests and never reaches
    the person.

    `diagnosis` is a read's own tag, from `_diagnosed`, and it adds a second
    reviewed sentence saying why that read stopped. It is chosen the same way
    the first one is, one call frame lower down; the verdict is said first and
    is unchanged by it."""
    said = [moment(REFUSAL_MOMENT + reason)]
    if diagnosis:
        said.append(moment(DIAGNOSIS_MOMENT + diagnosis))
    return RunResult(answered=False, refusal=reason, text=" ".join(said),
                     diagnosis=diagnosis,
                     detail=detail, transcript=transcript, calls=calls,
                     shape=shape.to_dict() if shape is not None else {})


def _diagnosed(transcript: list, tools) -> str:
    """The tag of the read that accounts for this turn having nothing, or "".

    The candidate is the last entry in the transcript a registered tool
    produced: the runner's own notes to the planner are not tool results and
    are passed over, and a turn whose last read succeeded has no read refusal
    that is still the reason. It is spoken only where that candidate is itself a
    refusal and its tag is one whose cause may be spoken. Nothing here reads a
    result's words, its payload or what constructed it."""
    for result in reversed(transcript):
        if result.tool not in tools:
            continue
        if result.ok or result.refusal not in SPEAKABLE_REFUSALS:
            return ""
        return result.refusal
    return ""


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
            result = _gate(step, transcript, ground, shape, locale,
                           tools=registry.names())
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
                    [t.to_dict() for t in transcript], len(transcript), shape,
                    diagnosis=_diagnosed(transcript, registry.names()))
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
BINDING_KEYS = ("figure", "entity", "period", "date", "supposed", "read")

# The one kind of reference a hole of each type can hold. Where a type admits
# exactly one, the type has already said what a bare value refers to, and a
# reference that arrived without its key is read as that kind. A magnitude is
# absent: a figure this run read and a value the person supposed both belong in
# a money, count or rate hole, and the key is what tells them apart.
SOLE_BINDING = {render.DATE: "date", render.PERIOD: "period",
                render.ROWS: "read", render.SUPPOSED: "supposed",
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


def _stated_figures(clause, bindings: dict, ground: _Ground) -> tuple:
    """The figures one clause states, as the figures themselves.

    What a clause holds is read from the bindings it was given rather than from
    what has been resolved so far, so which figures a hole stands beside does
    not depend on the order the holes are walked in. A binding naming a figure
    this run never emitted is skipped here and refuses where it is resolved.

    A block of rows states figures too, and they are not among these: a block
    is many figures at once, so which of them a day or a span said beside it
    belongs to is the sentence's own order, and reading that would be reading
    the sentence."""
    out = []
    for slot in clause.slots:
        reference = bindings.get(slot.name)
        named = (_named_reference(slot, reference) if reference is not None
                 else None)
        fig = (ground.book.get(str(named["figure"]))
               if named and "figure" in named else None)
        if fig is not None:
            out.append(fig)
    return tuple(out)


def _bound(slot, reference, ground: _Ground, locale: str, *, alongside=()):
    """One hole, filled — or the problem with filling it, as
    ``(written, machine tag, sentence)``.

    Every branch resolves a reference into this run's ledger and hands the
    thing to its renderer. Nothing here writes characters: the renderer does,
    once, in one place.

    ``alongside`` is the figures the hole's own clause states. A day and a span
    are properties of a number rather than of a turn, so the two holes that
    hold one are answered out of what the sentence they are in states, and not
    out of everything the run happens to carry."""
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
        # And the span a figure the same clause states was taken over, read off
        # the slices that figure declares itself to be. A span this run's
        # documents answer for and a span a number was measured across are two
        # different things, and a number said under a span it was not measured
        # across claims days it never saw.
        measured = {(item["value"], item["to"]) for fig in alongside
                    for item in (fig.get("boundary") or {}).get("cut") or []
                    if item["kind"] == BY_PERIOD}
        if (span["from"], span["to"]) not in measured:
            return None, "unknown_period", (
                f"The answer refers to a period {str(value)!r}, and no figure "
                f"the clause holding {slot.name!r} states was taken over that "
                "span.")
        return render.period(span["from"], span["to"]), "", ""

    if key == "read":
        rows = ground.readings.get(str(value))
        if rows is None:
            return None, "unknown_reading", (
                f"The answer refers to a read {str(value)!r} this turn never "
                "made.")
        if slot.type != render.ROWS:
            return None, "wrong_kind", (
                f"The hole {slot.name!r} wants {slot.type}, and a read is every "
                "figure of one reading at once.")
        return _rows_bound(slot, rows, ground, locale)

    if key == "date":
        if slot.type != render.DATE:
            return None, "wrong_kind", (
                f"The hole {slot.name!r} wants {slot.type}, and a day is not a "
                "magnitude.")
        # The day of a figure the same clause states. Every figure says which
        # day its value is good for, so a sentence saying how current its own
        # number is has that day beside it — and a day taken from anywhere else
        # in the turn is a real day belonging to a different number, which is
        # the reading a person cannot tell from the true one.
        if str(value) not in {str(fig["dated"]) for fig in alongside
                              if _is_iso_date(fig.get("dated"))}:
            return None, "unfounded_date", (
                f"The answer says {str(value)!r}, and no figure the clause "
                f"holding {slot.name!r} states carries that day.")
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

    # One name in that list is the name for having no name: what the vocabulary
    # calls a quotient of two unlike kinds, where no kind is true of the
    # result. Every hole that could hold one writes a proportion in a unit, and
    # a number no name is true of has no unit to be written in, so choosing one
    # would be inventing the claim the sentence is then read as making. The
    # two declarations compared are the figure's own and what the kind of hole
    # writes; the words around the hole are read by nothing.
    if fig["quantity"] == quantity.RATIO:
        return None, "wrong_kind", (
            f"The hole {slot.name!r} wants a proportion, and {fig['what']!r} "
            "compares two unlike kinds — no kind is true of the result, so "
            "there is no unit it can be written in.")

    # Direction, read the same way and out of the same module. The vocabulary
    # says which quantities assert which way the money goes by their own name,
    # and each of those is carried positive where its name is true of the
    # value. A hole asking for one of them is a sentence asserting that
    # direction, so a value denying it fills no such hole — a sign written in
    # front of a number whose sentence says the opposite is a claim nothing
    # here could check and a person has no way to read as anything but the
    # sentence.
    if (slot.quantity in quantity.ASSERTS_DIRECTION and value is not None
            and value < 0):
        return None, "wrong_quantity", (
            f"The hole {slot.name!r} asks for {slot.quantity}, and "
            f"{fig['what']!r} carries a value running the other way — the "
            "number is real and the sentence asserting that direction is not "
            "true of it.")

    # And the second pair, the same way. The tool declared every slice the
    # figure is the intersection of; the shape declared every axis its sentence
    # narrows on; the two sets are equal or the figure is not what the sentence
    # is about. A hole asking for the whole is filled by a figure that says it
    # is the whole.
    #
    # Equality in both directions is the whole of it. A sentence about one
    # counterparty is refused a figure cut by that counterparty and a span,
    # because that figure is not the counterparty's total; a sentence about a
    # counterparty inside a span is refused the counterparty's whole-history
    # total for the same reason read the other way. Nothing here works out what
    # a figure covers — it reads what the emitter wrote down and compares it.
    #
    # A figure that states no boundary fills neither. Nothing has said what set
    # it was taken over, and that is not the same as saying the set was
    # everything.
    if slot.scope:
        bound = fig.get("boundary") or {}
        asked = set(slot.scope)
        cut_by = {item["kind"] for item in bound.get("cut") or []}
        asked_for = (bound.get("whole", False) if asked == {WHOLE}
                     else asked == cut_by)
        if not asked_for:
            return None, "wrong_scope", (
                f"The hole {slot.name!r} asks for a number over "
                + ", ".join(sorted(asked))
                + f", and {fig['what']!r} was taken over a different set — the "
                "number is real and it is not a number about that.")

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


# -------------------------------------------------------- where a claim ends

# How each way of narrowing a set is said: the pack's line for it, the name
# that line places it by, and how the thing becomes words. One entry per member
# of the vocabulary, so a way of narrowing with nowhere to say what it selected
# is a build failure rather than a figure that reaches a person looking like a
# total.
SELECTED_TERMS = {
    BY_ACCOUNT: ("boundary_selected_account", "account",
                 lambda item, ground: _account_written(item["value"], ground)),
    BY_CATEGORY: ("boundary_selected_category", "category",
                  lambda item, ground: render.category(item["value"])),
    BY_MERCHANT: ("boundary_selected_merchant", "merchant",
                  lambda item, ground: render.merchant({"key": item["value"]})),
    BY_PERIOD: ("boundary_selected_period", "period",
                lambda item, ground: render.period(item["value"], item["to"])),
    BY_SINCE: ("boundary_selected_since", "day",
               lambda item, ground: render.date(item["value"])),
    BY_UNTIL: ("boundary_selected_until", "day",
               lambda item, ground: render.date(item["value"])),
    # The three the vault holds no thing for. Each is written as the label it is
    # held under, which says what a figure's scope is and offers nothing to ask
    # a follow-up with.
    BY_SUBCATEGORY: ("boundary_selected_subcategory", "subcategory",
                     lambda item, ground: render.label(item["value"])),
    BY_TAG: ("boundary_selected_tag", "tag",
             lambda item, ground: render.label(item["value"])),
    BY_CURRENCY: ("boundary_selected_currency", "currency",
                  lambda item, ground: render.label(item["value"])),
}


def _named_slice(item: dict, ground: _Ground):
    """What one cut of a set is written as: the thing it was cut to, in
    whichever form that kind of thing is written in. The same writer the
    sentence about a boundary uses, so a slice named beside a number and a
    slice named in a scope clause are never written two ways."""
    return SELECTED_TERMS[item["kind"]][2](item, ground)


def _line_of(fig: dict):
    """The slice this figure is a line of its read for, or None.

    A figure is a line of its read where the axes it is cut by are the read's
    own narrowing and exactly one axis more. That one axis is what the line is
    named by, and it is what makes the figure a part of what came back rather
    than the whole of it.

    So a read narrowed to one counterparty has no line for that counterparty —
    neither its own total, cut by the narrowing and nothing further, nor a
    group over the axis the read was filtered on, which is that same set again
    and would stand beside the other groups as though it were one more of them.
    A read narrowed to one account still has a line per month, because a month
    is an axis the narrowing did not name. And a figure cut two axes past the
    narrowing is a cell rather than a line: the lines beside it would each be
    true of a different set.

    Two declarations compared, both written by the read: which slices this
    figure is, and what narrowed the read it came from. Nothing here reads a
    value or asks what sort of thing a payload holds."""
    bound = fig.get("boundary") or {}
    cut = bound.get("cut") or []
    narrowing = {item["kind"] for item in bound.get("selected") or []}
    axes = {item["kind"] for item in cut}
    if not narrowing <= axes or len(axes - narrowing) != 1:
        return None
    (axis,) = axes - narrowing
    return next(item for item in cut if item["kind"] == axis)


def _rows_bound(slot, rows, ground: _Ground, locale: str):
    """One read's figures as a block, each beside the slice it covers.

    Generic on purpose, and the whole point of the hole. Nothing here knows
    what spending is: a row is any figure whose boundary names the cut it was
    taken over, its name is that cut written by its own kind, and its magnitude
    is written by the shape its declared quantity takes. So the day a read
    returns patterns or bills instead of totals, they are speakable without
    this being touched.

    The grade is the weakest among the figures that make a claim about money,
    stated once above the block. It is one grade computed over the whole read
    and stamped on each of its figures, so per-row it would read as a claim
    about that row when it is a claim about the read.

    A read that names no slice fills nothing. That is a binding naming the
    wrong sort of read rather than a gap: the hole was bound, and to something
    that has no rows in it.

    A read whose figures name slices of more than one kind fills nothing
    either. One read may cut the same set several ways at once — a figure per
    account and a figure per month over the same movements — and a line per
    slice would state the same money once for each way it cuts. The refusal is
    on the declared kinds, not on which read or tool produced them.

    A read whose figures name one slice more than once fills nothing, for the
    same reason. Several figures over the same slice are several measurements
    of one thing, and a line apiece would state that thing's money once per
    figure while reading as one line per slice.

    The two refusals are in that order and the order decides which a read hears
    about: a read that cuts several ways is settled by the first, so the second
    is never reached for it however its slices repeat within a kind."""
    cuts = [cut for cut in (_line_of(ground.book[fid]) for fid in rows) if cut]
    kinds = {cut["kind"] for cut in cuts}
    if len(kinds) > 1:
        return None, "wrong_kind", (
            f"The hole {slot.name!r} wants rows, and that read cuts the same "
            "set more than one way at once — by " + ", by ".join(sorted(kinds))
            + ". A line per slice would state the same money once for each of "
            "them.")
    named = [cut["value"] for cut in cuts]
    if len(set(named)) < len(named):
        return None, "wrong_kind", (
            f"The hole {slot.name!r} wants rows, and that read has more than "
            "one figure over the same slice of what it cuts. A line per slice "
            "would state one slice's money once for each figure taken over "
            "it.")
    lines, cited = [], []
    for fid in rows:
        fig = ground.book[fid]
        cut = _line_of(fig)
        if not cut:
            continue
        kind = render.TYPE_OF_QUANTITY.get(fig["quantity"], "")
        value = _decimal(fig["value"])
        if not kind or value is None:
            # A block is every figure of this read that named a slice, and a
            # line quietly left out would make it a false claim about its own
            # completeness. So a figure that cannot be written costs the block
            # rather than itself.
            return None, "wrong_kind", (
                f"The hole {slot.name!r} wants rows, and {fig['what']!r} is a "
                "slice of that read holding no magnitude anything can write.")
        written = _MAGNITUDE_WRITERS[kind](value, fig, locale)
        lines.append((_named_slice(cut, ground), _hedged(written, fig, kind)))
        cited.append(fig)
    if not lines:
        return None, "wrong_kind", (
            f"The hole {slot.name!r} wants rows, and that read named no slice "
            "of anything — there is nothing in it to write one line per.")
    return render.rows(lines, grade=weakest(
        f["grade"] for f in cited if f["kind"] in MONEY_KINDS)), "", ""


# How a magnitude is written where no hole above it said which shape to take.
# One entry per kind that holds one, keyed the same way `APPROX_TERMS` is, so a
# new shape of magnitude arriving with nowhere to be written is a build failure
# rather than a row silently dropped.
_MAGNITUDE_WRITERS = {
    render.MONEY: lambda value, fig, locale: render.money(
        value, fig["currency"], locale=locale),
    render.COUNT: lambda value, fig, locale: render.count(value),
    render.RATE: lambda value, fig, locale: render.rate(value, locale=locale),
}


def _known_account(path: str, ground: _Ground) -> dict:
    """One account as this run established it, or as its path alone gives it.

    An account the reads already spoke about carries the name a person is shown
    everywhere else, so the name in a boundary is the name in the sentence."""
    return next((e for e in ground.entities.values()
                 if e["kind"] == ENTITY_ACCOUNT and e.get("account") == path),
                {"account": path})


def _account_written(path: str, ground: _Ground) -> render.Account:
    """One account, written among the others of its kind this run
    established, so two accounts are never written identically."""
    company = [e for e in ground.entities.values()
               if e["kind"] == ENTITY_ACCOUNT]
    known = _known_account(path, ground)
    return render.account(known, among=company or [known])


def _accounts_written(paths, ground: _Ground) -> render.Account:
    """Several accounts in one place, each told apart from the others beside
    it."""
    return render.accounts([_known_account(path, ground) for path in paths])


def _boundary(fig: dict, *, cut: bool = True) -> tuple[list, list]:
    """Where one figure's claim ends, as ``(statements, accounts left out)``.

    The two halves merge differently. A statement about how a set was narrowed
    is compared whole; accounts left out are returned as a list for the caller
    to gather across every figure the answer stated.

    Both empty where the set is everything the figure claims to measure, and
    where a figure declares it is not whole without naming anything it was
    narrowed to. A figure carrying no boundary has nothing to say here either,
    and says nothing for the other reason: no read has stated what set it was
    taken over, which is not the same as a read stating that the set was
    everything.

    ``cut`` is whether the slices THIS figure alone was taken over are among
    the statements. They are said wherever the figure is stated as a number in
    a sentence, and not where the figure is a line of a block, because there
    the slice is already written beside the number as the line's own name.

    What the read as a whole was narrowed to is said either way, because that
    is a fact about the call rather than about one line of it.

    How many of the accounts a person holds are covered is not here. It is one
    claim about the whole answer, computed over every figure the answer stated,
    because a count said once for one figure reads as being about the answer —
    and where the answer states two such figures, it is.

    What would settle a gap stays on the figure and is not said."""
    bound = fig.get("boundary") or {}
    if bound.get("whole", False):
        return [], []
    said = []

    def say(statement):
        # A figure's cuts include what narrowed its read, so the two halves
        # name some of the same slices. One slice is one sentence.
        if statement not in said:
            said.append(statement)

    for item in bound.get("selected") or []:
        say((SELECTED_TERMS[item["kind"]][0], dict(item)))
    if cut:
        for item in bound.get("cut") or []:
            say((SELECTED_TERMS[item["kind"]][0], dict(item)))
    if bound.get("unposted"):
        # A gap no account names is still said. It is a number of documents,
        # because a document read and not posted may be about an account that
        # does not exist yet and there is nothing else to call it.
        say(("boundary_unposted", {"count": bound["unposted"]}))
    return said, [item["account"] for item in bound.get("unmeasured") or []]


def _said(statement, ground: _Ground) -> str:
    """One statement about how a set was narrowed, in the pack's words."""
    key, fields = statement
    if key == "boundary_unposted":
        return moment(key, count=render.count(fields["count"]))
    _key, name, written = SELECTED_TERMS[fields["kind"]]
    return moment(key, **{name: written(fields, ground)})


def _boundaries(stated, ground: _Ground) -> list:
    """Where the claims of ONE clause end, once each within it.

    ``stated`` is what that clause said, in the order it said it: each figure
    with whether the clause stated it as a line of a block rather than as a
    number in a sentence.

    The clause is the unit because the word these sentences begin with points
    at what was just read: a statement gathered from every figure in the answer
    and placed at the end refers to nothing in particular, and two figures
    making the identical statement about different clauses are two claims
    rather than one.

    So a statement is said once within a clause, where two figures in one
    sentence genuinely make one claim, and again under the next clause that
    makes it. What that clause leaves out is one set across its own figures,
    said in a single sentence however many of them carry overlapping gaps."""
    statements: list = []
    left_out: list = []
    for fig, as_rows in stated:
        said, gaps = _boundary(fig, cut=not as_rows)
        for statement in said:
            if statement not in statements:
                statements.append(statement)
        for account in gaps:
            if account not in left_out:
                left_out.append(account)
    lines = [_said(statement, ground) for statement in statements]
    if left_out:
        lines.append(moment("boundary_unmeasured",
                            account=_accounts_written(left_out, ground)))
    return lines


def _covered(cited) -> tuple[int, int] | None:
    """Which of the accounts a person holds the whole answer covers, as how
    many of them and how many they hold, or None where the answer cannot say.

    One claim about the answer, computed from what every stated figure declares
    rather than said once per figure and deduplicated as though two figures
    over an account each were one. The accounts are the ones the figures name —
    a slice a figure is, or a narrowing its read was given — so the count is of
    a set the code can list, and two figures naming one account between them
    are one account.

    How many accounts are held is whichever figure says so; it is a fact about
    the vault rather than about the answer, so any figure that carries it
    carries the same number.

    A figure counts towards this only where it declares, as data, exactly which
    accounts it covers: its boundary carries a count of accounts, and that
    count is the number of accounts the figure names. Any other figure is one
    the answer cannot enumerate — one counted over more accounts than it names
    reached accounts nothing here can list, and one declaring nothing about
    accounts at all, whatever it says about being the whole of what it
    measures, came from a read that ranged over accounts and said nothing about
    which. Either leaves every account this could count fewer than the answer
    covered, so a shortfall said in words about the whole answer would be a
    shortfall the answer does not have, and None is returned instead. What
    narrowed each read is still said under its own clause. Two declarations
    compared: how many accounts a figure says it counted, against the accounts
    that figure names."""
    named: set = set()
    held = 0
    for fig in cited:
        bound = fig.get("boundary") or {}
        counts = bound.get("accounts") or {}
        names = {item["value"] for item
                 in (bound.get("cut") or []) + (bound.get("selected") or [])
                 if item["kind"] == BY_ACCOUNT}
        if not counts or counts.get("counted", 0) != len(names):
            return None
        held = max(held, counts.get("held", 0))
        named |= names
    return len(named), held


# ------------------------------------------------------------------- the gate


def _labelled(entities) -> dict:
    """The things these entities are, as the one label each kind is told apart
    by, grouped by kind.

    It is the label the model was shown, taken from the same place the model
    took it from, so what a sentence names and what a figure's boundary names
    are one string rather than two spellings of one thing."""
    out: dict = {}
    for item in entities:
        out.setdefault(item["kind"], set()).add(_named(item)["label"])
    return out


def _misnamed(clause, references: dict, ground: _Ground):
    """The slice of a figure this clause states that the clause names a
    different thing for, as ``(slot, figure, cut entry, what was named)``, or
    None where every slice agrees with what the sentence names.

    An entity belongs to a figure when the figure's own boundary names it. The
    figure says which slice of a set it is; the sentence says which thing it is
    about, through a hole, which is a reference and never words; and those are
    two strings put there by code. Neither the sentence's words nor the read
    that emitted either half is read.

    Every axis of the cut is compared, because the cut is a set and a figure
    that is right about one axis of it and wrong about another is a figure
    about something else. A clause naming several things of one kind is
    answered by any of them: which of two things a number sits beside is the
    sentence's own order, and reading that would be reading the sentence.

    Two ways of agreeing are silence rather than a fault. A clause that names
    nothing of a slice's kind claims nothing about that slice, and a sentence
    that says which thing it is about only in its own words is prose nothing
    here checks. And a slice naming something no read of this run established
    is a set the run holds no thing for: nothing can be bound that would name
    it, so nothing can name it wrongly either.

    A figure stated as a line of a block is not compared. Every line is written
    beside the name of the slice it is, out of the same declaration this would
    compare it against, so a line says what it is about itself and there is no
    second declaration for it to disagree with."""
    bound = [references.get(slot.name) or {} for slot in clause.slots]
    named = _labelled(ground.entities[str(reference["entity"])]
                      for reference in bound if "entity" in reference)
    established = _labelled(ground.entities.values())
    for slot in clause.slots:
        reference = references.get(slot.name) or {}
        if "figure" not in reference:
            continue
        fig = ground.book[str(reference["figure"])]
        for item in (fig.get("boundary") or {}).get("cut") or []:
            here = named.get(item["kind"]) or set()
            value = str(item["value"])
            if not here or value not in established.get(item["kind"], set()):
                continue
            if value not in here:
                return slot, fig, item, sorted(here)
    return None


def _written_out(parts) -> str:
    """The whole answer as one piece of text, out of what each part wrote and
    whether that part is a block of lines.

    Sentences run on, the way sentences do. A block does not: it is a line per
    thing, so what sits either side of one begins on its own line. The read's
    own tail sentence therefore lands under the last row rather than beside it,
    which is what a person reading a list of ten needs it to do."""
    out, blocked = "", False
    for piece, block in parts:
        if not str(piece).strip():
            continue
        if out:
            out += "\n" if block or blocked else " "
        out += str(piece)
        blocked = block
    return out.strip()


def _gate(step: dict, transcript: list, ground: _Ground, shape: Shape,
          locale: str, *, tools) -> RunResult:
    """The checks on a delivery, over the structure and never the sentence.

    `tools` names the registered tools, which is what decides whether an entry
    in the transcript is a read that can account for a turn that established
    nothing. It has no default: a caller that omitted it would drop the cause
    silently, and the turn would look like it had none to give."""
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

    # Which figures each hole stands beside, by the clause it is in. The holes
    # are resolved one at a time and the clause is what says which of this
    # run's figures a day or a span in it belongs to, so the clause each hole
    # came from travels with it into the resolution.
    beside = {slot.name: _stated_figures(clause, bindings, ground)
              for clause in shape.clauses for slot in clause.slots}

    written: dict = {}
    references: dict = {}
    gaps: list = []
    for name, slot in slots.items():
        if name not in bindings:
            gaps.append({"name": name, "type": slot.type})
            continue
        value, tag, detail = _bound(slot, bindings[name], ground, locale,
                                    alongside=beside.get(name, ()))
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
                        shape, diagnosis=_diagnosed(transcript, tools))

    # The clause is the unit here, and it has to be: every hole above was
    # resolved on its own against everything this run established, so a figure
    # of one thing and a thing of the same kind can each be real and belong to
    # different sentences. What ties them together is that the figure's own
    # boundary names what the clause names. It runs over what survived the
    # drops, because a clause about to be dropped asserts nothing to be wrong
    # about.
    for clause in spoken:
        misnamed = _misnamed(clause, references, ground)
        if misnamed is None:
            continue
        slot, fig, item, named = misnamed
        return _refused(
            "wrong_subject",
            f"The clause holding {slot.name!r} names the {item['kind']} "
            + ", ".join(repr(one) for one in named)
            + f", and {fig['what']!r} was taken over the {item['kind']} "
            f"{str(item['value'])!r} — the number is real and it is a number "
            "about something else.", dicts, len(transcript), shape)

    # Only what survived asserts anything, so only what survived is answerable
    # for its records and its caveats. The holes are walked in the order the
    # sentence places them, which is the order a person reads it in.
    #
    # One figure can fill more than one hole — the same balance named in two
    # clauses of one answer. It is one figure and it is cited once.
    said = [s.name for c in spoken for s in c.slots]
    # And which figures each clause stated, in the order it stated them, so a
    # statement about where a figure's claim ends is placed under the sentence
    # that made it rather than in a pool at the end.
    per_clause: list = []
    cited, seen, as_numbers = [], set(), set()
    for clause in spoken:
        here: dict = {}
        for slot in clause.slots:
            reference = references[slot.name]
            as_rows = "read" in reference
            # A block of rows states every figure it wrote a line for, and
            # those are answerable exactly as a figure named in a sentence is:
            # for their records, for their caveats and for the answer's grade.
            # The figures of that read it wrote no line for — the read's own
            # total and its count — are not stated and are not cited.
            if as_rows:
                stated = [fid for fid in ground.readings[str(reference["read"])]
                          if _line_of(ground.book[fid])]
            elif "figure" in reference:
                stated = [str(reference["figure"])]
            else:
                continue
            for fid in stated:
                if not as_rows:
                    as_numbers.add(fid)
                # A figure stated as a number of its own says its own slices in
                # that sentence, however many blocks of the same clause it also
                # appears in; one stated only as a line has already said them,
                # as the line's name.
                here[fid] = here[fid] and as_rows if fid in here else as_rows
                if fid in seen:
                    continue
                seen.add(fid)
                cited.append(ground.book[fid])
        per_clause.append([(ground.book[fid], as_rows)
                           for fid, as_rows in here.items()])

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

    # How many of the accounts a person holds this answer covers, over every
    # figure the answer stated. It is one claim about the answer, so it is said
    # once and after the clauses, where the answer is what a person has just
    # read: two of these would be two counts of one thing, and one placed under
    # a clause would be a count of what that clause covers written in words
    # that are about the whole of it. An answer naming no account says nothing
    # here rather than saying it covers none, and an answer that cannot
    # enumerate what it covers says nothing here rather than a number it
    # cannot stand behind.
    #
    # It goes ahead of the limits: how far a claim reaches says what the claim
    # is about, and what the claim does not cover is read against that.
    covered, held = _covered(cited) or (0, 0)

    # How well what the answer stated is stood behind: the weakest grade among
    # every money figure it stated, lines of a block included, said in the
    # pack's one whole sentence for that word. It is the answer's own grade, so
    # what a person hears and what the result carries are one word.
    #
    # Whether it is said turns on whether any of those figures was stated as a
    # number in a sentence. Where every one of them is a line of a block, the
    # block has already stated this grade above itself. Where one was, the
    # block's figures are inside the set this speaks for, so this sentence can
    # only be weaker than or equal to the line above the block and the two can
    # never disagree.
    #
    # It lands after the boundaries and before the limits: a word about strength
    # heard before the extent of the claim has been stated invites reading it as
    # covering more than it does.
    graded = [f for f in cited if f["kind"] in MONEY_KINDS]
    stood_behind = weakest(f["grade"] for f in graded)
    stated_in_a_sentence = any(f["id"] in as_numbers for f in graded)

    parts: list = []
    for clause, figures in zip(spoken, per_clause):
        parts.append((clause.written(written),
                      any(isinstance(written[s.name], render.Rows)
                          for s in clause.slots)))
        parts += [(line, False) for line in _boundaries(figures, ground)]
    if covered and covered < held:
        parts.append((moment("boundary_accounts",
                             counted=render.count(covered),
                             held=render.count(held)), False))
    if stood_behind and stated_in_a_sentence:
        parts.append((moment(STOOD_BEHIND_MOMENT + stood_behind), False))
    if owed:
        parts.append((moment("answer_limits", limits=render.caveat(
            " ".join(ground.caveats[cid] for cid in owed))), False))
    for kind in dropped:
        # A clause nothing could fill is a disclosed gap, never a zero and
        # never a silence. What is missing is named by its kind, in the pack's
        # own words.
        parts.append((moment("answer_gap", what=moment(f"gap_{kind}")), False))
    return RunResult(
        answered=True, text=_written_out(parts),
        figures=[dict(f) for f in cited],
        grade=stood_behind,
        transcript=dicts, calls=len(transcript),
        shape=shape.to_dict(),
        bindings={n: references[n] for n in said},
        written={n: str(written[n]) for n in said}, gaps=gaps)


