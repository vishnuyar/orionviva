"""The evidence ledger and delivery gate for machine-built answer structures.

The one-shot AnswerProgram runtime owns planning and execution.  This module is
the data-blind delivery boundary it reuses: current-turn evidence gains stable
identities here, and an answer shape can bind only to those identities.

A turn reaches this boundary only after three enforced stages:

1. **The shape.** Before any read, the compiler commits a shape:
   clauses of literal words with typed holes in them and no digits anywhere.
   Nothing has been read, so no claim can be tailored to a figure that turned
   up, and what the shape declares is what the turn then goes looking for.
2. **The reads.** The tools appear. Everything a read establishes gets an
   identity in this run's own ledger — figures, the accounts and counterparties
   it spoke about, the days its results carry, the spans its documents attest,
   and the caveats it wrote about its own numbers.
3. **The bindings.** The pre-data program declares selectors, and deterministic
   code resolves them against that ledger. Every binding is a reference; not
   one of them is text.

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

from .. import quantity, render
from ..persona import STOOD_BEHIND_MOMENT, moment
from .boundary import SELECTED_TERMS, accounts_written, named_slice
from .boundary import said as _said
from .boundary import statements as _boundary
from .compute import numbers_said
from .envelope import (BY_ACCOUNT, BY_PERIOD, ENTITY_ACCOUNT, ENTITY_MARKS,
                       EXACT, HYPOTHETICAL, MONEY_KINDS, SPEAKABLE_REFUSALS,
                       ToolResult, _named, weakest)
from .shape import WHOLE

_ISO_DATE_LENGTH = 10


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
    # Verbatim limitations actually placed for stated figures. Keeping this
    # structural observable lets admission prove that caveats were delivered
    # without trying to infer them from prose or from a grade word.
    caveats: list = field(default_factory=list)
    disclosures: list = field(default_factory=list)
    # The answer-program path distinguishes why a turn did not answer.  The
    # legacy runner leaves this empty; surfaces may then retain their existing
    # answered/refused interpretation during the replacement.
    status: str = ""
    outcome_tag: str = ""
    options: list = field(default_factory=list)
    missing: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"answered": self.answered, "text": self.text,
                "figures": list(self.figures), "grade": self.grade,
                "refusal": self.refusal, "diagnosis": self.diagnosis,
                "detail": self.detail,
                "transcript": list(self.transcript), "calls": self.calls,
                "shape": dict(self.shape), "bindings": dict(self.bindings),
                "written": dict(self.written), "gaps": list(self.gaps),
                "caveats": list(self.caveats),
                "disclosures": list(self.disclosures),
                "status": self.status, "outcome_tag": self.outcome_tag,
                "options": list(self.options), "missing": list(self.missing)}


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

    def accounts(self) -> dict:
        """The accounts this run established, by ledger path.

        What an account is written from, handed to whatever writes one, so the
        name in a boundary sentence is the name every other sentence uses."""
        return {item["account"]: item for item in self.entities.values()
                if item.get("kind") == ENTITY_ACCOUNT and item.get("account")}

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
DELIVERY_REFUSAL_TAGS = (
    "bad_delivery", "unshaped_binding", "bad_binding",
    "unknown_figure", "unknown_entity", "unknown_period", "unknown_reading",
    "unfounded_date", "unfounded_stipulation", "wrong_kind",
    "wrong_quantity", "wrong_scope", "wrong_subject",
    "nothing_established", "uncited_figure",
)

# How a tag finds its sentence in the pack. A turn's own tag finds the verdict;
# a read's tag finds the cause, in a namespace of its own so that neither set of
# sentences can be reached by the other's tag.
REFUSAL_MOMENT = "refusal_"
DIAGNOSIS_MOMENT = "diagnosis_"

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
    produced: non-read execution records are passed over, and a turn whose last
    read succeeded has no read refusal
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


# Compatibility exports. The implementation lives beside the execution loop,
# but existing imports continue to resolve through this module.
from .runner_binding import (APPROX_TERMS, BINDING_KEYS, SOLE_BINDING,
                             _MAGNITUDE_WRITERS, _bound, _boundaries,
                             _covered, _figure_bound, _hedged, _line_of,
                             _named_reference, _rows_bound, _stated_figures)
from .runner_delivery import _gate, _labelled, _misnamed, _written_out
