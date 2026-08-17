"""A sentence is a structure before it is a sentence.

An answer is a **shape**: a list of clauses, each a run of literal words with
typed holes in it. A hole names what kind of thing in the world fills it —
an amount, a day, an account, a counterparty — and nothing more. What fills it
is decided later, by code, out of the ledger of things the run established.

Two properties carry this module, and they are the whole of its safety:

**The shape is authored before the data exists.** A shape is committed while
the run holds nothing, so a claim cannot be tailored to the number that turned
up. A model that has never seen an amount cannot call one unusually large, and
cannot decide what a figure it has not yet found is a total of.

**A shape's literal words carry no digits at all.** Not a filtered set of
digits, not digits in certain positions — none, anywhere outside a hole. That
is a character-class check over one field, so there is nothing here that reads
the sentence, guesses at meaning, or keeps a list of words. A magnitude can
only reach a person through a hole, and a hole is filled by the renderer.

**A hole that holds a magnitude says what the magnitude is of.** Typed holes
make a number impossible to invent; they do nothing about a real number put
where something else belongs, which is a false sentence assembled out of true
parts. So a hole wanting an amount, a count or a proportion names what it is
asking for, out of the same closed vocabulary the tools declare into, and the
comparison is between two declarations rather than a reading of the words
around the hole.

The clause is the unit, rather than one string with sentence boundaries in it,
because degradation is per clause: a hole nothing can fill costs its clause and
leaves the rest of the answer standing, with the gap disclosed. Sentence
boundaries inside a string are a text heuristic; a list is a structure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..render import CAVEAT, PROSE, QUANTITY_OF_TYPE, TYPES

# A hole: a name in braces. The name is how a binding refers to it; the type is
# declared beside the text rather than inside it, so the text stays words.
_HOLE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# The types a hole in an answer may declare. Reviewed pack prose is not among
# them: it nests one reviewed template inside another and is never a hole for
# words nobody reviewed. Neither is a caveat: the runner places what a stated
# figure owes, so nothing asks for one through a hole.
SLOT_TYPES = tuple(t for t in TYPES if t not in (PROSE, CAVEAT))

# Which kinds of hole hold a magnitude and which hold something else: exactly
# the kinds the pairing table gives a vocabulary of quantities to, and all the
# rest. Derived from that table rather than listed again, so the form a model
# fills in and the check that reads it back cannot describe different rules.
MAGNITUDE_TYPES = tuple(t for t in SLOT_TYPES if QUANTITY_OF_TYPE.get(t))
PLAIN_TYPES = tuple(t for t in SLOT_TYPES if t not in MAGNITUDE_TYPES)


def quantities_of(kind: str) -> tuple:
    """What a hole of this kind may say its number is of, sorted.

    The pairing table as the check reads it, and the only place anything else
    may read it from. Empty for a kind that holds no magnitude."""
    return tuple(sorted(QUANTITY_OF_TYPE.get(kind, ())))

# How much shape one turn may commit to. A ceiling rather than a rule about
# style: a shape is resent on every remaining call of the turn.
MAX_CLAUSES = 12
MAX_CLAUSE_CHARS = 400

# What to do about a reply that could not be used, as a machine tag. A check
# names the repair; the words a model is told for each one live in a reviewed
# file, so the same defect always asks for the same change. Two defects that
# read alike carry two tags wherever the change they call for differs — a hole
# that named no quantity is told to name one, and a hole that named the wrong
# one is told which it may choose from.
SEND_A_SHAPE = "send_a_shape"
SHAPE_THE_CLAUSE = "shape_the_clause"
SHAPE_THE_SLOTS = "shape_the_slots"
WORD_THE_QUANTITY = "word_the_quantity"
WORD_THE_CLAUSE = "word_the_clause"
SHORTEN_THE_CLAUSE = "shorten_the_clause"
HOLE_THE_NUMBER = "hole_the_number"
PLACE_EACH_HOLE_ONCE = "place_each_hole_once"
RENAME_THE_HOLE = "rename_the_hole"
MATCH_THE_HOLES = "match_the_holes"
CHOOSE_A_KIND = "choose_a_kind"
NAME_THE_QUANTITY = "name_the_quantity"
CHOOSE_THE_QUANTITY = "choose_the_quantity"
DROP_THE_QUANTITY = "drop_the_quantity"
FEWER_CLAUSES = "fewer_clauses"
# A delivery, which fills the holes a taken shape left, rather than a shape.
BIND_EACH_HOLE = "bind_each_hole"
BIND_ONE_THING = "bind_one_thing"
# A reply that was not a well-formed step at all, whatever it was carrying.
PROTOCOL = "protocol"

REPAIRS = (SEND_A_SHAPE, SHAPE_THE_CLAUSE, SHAPE_THE_SLOTS,
           WORD_THE_QUANTITY, WORD_THE_CLAUSE,
           SHORTEN_THE_CLAUSE, HOLE_THE_NUMBER, PLACE_EACH_HOLE_ONCE,
           RENAME_THE_HOLE, MATCH_THE_HOLES, CHOOSE_A_KIND, NAME_THE_QUANTITY,
           CHOOSE_THE_QUANTITY, DROP_THE_QUANTITY, FEWER_CLAUSES,
           BIND_EACH_HOLE, BIND_ONE_THING, PROTOCOL)


class Problem(str):
    """What was wrong, and what to do about it.

    Reads as the sentence naming the defect wherever a problem was one string,
    and carries beside it, on ``repair``, the tag of the change that answers
    it. The tag is one of ``REPAIRS``.

    A problem that names no repair is one about the protocol itself — a reply
    that was not a usable step at all — which is what the default says."""

    def __new__(cls, wrong: str, repair: str = PROTOCOL):
        problem = super().__new__(cls, wrong)
        problem.repair = repair
        return problem


class BadShape(ValueError):
    """A shape that cannot be spoken, named at the point it was built.

    Keeps the problem it was raised with, so a reader turning a model's shape
    into something to say back has the repair as well as the defect."""

    def __init__(self, problem):
        super().__init__(str(problem))
        self.problem = (problem if isinstance(problem, Problem)
                        else Problem(problem))


@dataclass(frozen=True)
class Slot:
    """One hole: the name a binding refers to it by, and what it holds.

    A hole that holds a magnitude says two things, because a number has a shape
    and a meaning and they are not the same declaration. ``type`` is the shape —
    an amount with a currency, a whole number of things, a proportion — and
    ``quantity`` is what the number is of. A hole holding something that is not
    a magnitude declares no quantity, because there is nothing to measure."""

    name: str
    type: str
    quantity: str = ""

    def to_dict(self) -> dict:
        out = {"name": self.name, "type": self.type}
        if self.quantity:
            out["quantity"] = self.quantity
        return out


@dataclass(frozen=True)
class Clause:
    """One run of words with its holes declared beside it.

    Built strictly: a clause whose text carries a digit, or whose holes and
    declarations disagree, does not come into being. Every later check can
    therefore assume it is looking at something sayable."""

    text: str
    slots: tuple = ()

    def __post_init__(self):
        if not str(self.text).strip():
            raise BadShape(Problem("a clause with no words says nothing",
                                   WORD_THE_CLAUSE))
        if len(self.text) > MAX_CLAUSE_CHARS:
            raise BadShape(Problem(
                f"a clause runs to {len(self.text)} characters, past the "
                f"{MAX_CLAUSE_CHARS} one clause may take",
                SHORTEN_THE_CLAUSE))
        digits = [c for c in self.text if c.isdigit()]
        if digits:
            raise BadShape(Problem(
                f"the clause {self.text!r} writes a digit in its own words — "
                "every magnitude, day and count reaches a person through a "
                "hole, so that the machine is what writes it",
                HOLE_THE_NUMBER))
        placed = _HOLE.findall(self.text)
        if len(placed) != len(set(placed)):
            raise BadShape(Problem(
                f"the clause {self.text!r} places the same hole twice",
                PLACE_EACH_HOLE_ONCE))
        declared = [s.name for s in self.slots]
        if len(declared) != len(set(declared)):
            raise BadShape(Problem("two holes in one clause share a name",
                                   RENAME_THE_HOLE))
        if set(placed) != set(declared):
            raise BadShape(Problem(
                f"the clause {self.text!r} places {sorted(set(placed))} and "
                f"declares {sorted(set(declared))} — a hole with no declaration "
                "says nothing about what fills it, and a declaration with no "
                "hole fills nothing",
                MATCH_THE_HOLES))
        for slot in self.slots:
            if slot.type not in SLOT_TYPES:
                raise BadShape(Problem(
                    f"the hole {slot.name!r} declares {slot.type!r}, which is "
                    f"not a kind of thing this holds: {', '.join(SLOT_TYPES)}",
                    CHOOSE_A_KIND))
            wanted = quantities_of(slot.type)
            if wanted and not slot.quantity:
                raise BadShape(Problem(
                    f"the hole {slot.name!r} holds a magnitude and does not say "
                    "what the magnitude is of; a number whose meaning nothing "
                    "states is one anything can be put into. It must be one of "
                    + ", ".join(wanted),
                    NAME_THE_QUANTITY))
            if wanted and slot.quantity not in wanted:
                raise BadShape(Problem(
                    f"the hole {slot.name!r} holds {slot.type} and says it "
                    f"measures {slot.quantity!r}, which is not something a "
                    f"{slot.type} hole can be of. It must be one of "
                    + ", ".join(wanted),
                    CHOOSE_THE_QUANTITY))
            if slot.quantity and not wanted:
                raise BadShape(Problem(
                    f"the hole {slot.name!r} holds {slot.type}, which measures "
                    f"nothing, and says it is {slot.quantity!r}",
                    DROP_THE_QUANTITY))

    def written(self, filled: dict) -> str:
        """The clause as words, every hole replaced by what the renderer wrote
        for it. Every hole must be filled; a clause that cannot be is dropped
        before it reaches here."""
        return _HOLE.sub(lambda m: str(filled[m.group(1)]), self.text)

    def to_dict(self) -> dict:
        return {"text": self.text, "slots": [s.to_dict() for s in self.slots]}


@dataclass(frozen=True)
class Shape:
    """A whole answer, before any of it is true of anything.

    Hole names are unique across the shape, not merely within a clause, because
    the bindings that fill them are one flat map: two holes sharing a name would
    be one binding standing for two claims."""

    clauses: tuple = ()

    def __post_init__(self):
        if not self.clauses:
            raise BadShape(Problem("a shape with no clauses is not an answer",
                                   SEND_A_SHAPE))
        if len(self.clauses) > MAX_CLAUSES:
            raise BadShape(Problem(
                f"a shape of {len(self.clauses)} clauses is past the "
                f"{MAX_CLAUSES} one answer may take",
                FEWER_CLAUSES))
        names = [s.name for c in self.clauses for s in c.slots]
        if len(names) != len(set(names)):
            raise BadShape(Problem(
                "two holes in this shape share a name; a binding names one "
                "hole, so a name used twice would fill two claims at once",
                RENAME_THE_HOLE))

    @property
    def slots(self) -> dict:
        """Every hole in the shape, by name."""
        return {s.name: s for c in self.clauses for s in c.slots}

    def to_dict(self) -> dict:
        return {"clauses": [c.to_dict() for c in self.clauses]}


def read_shape(raw) -> tuple:
    """A shape from what a model sent, or the problem with it.

    Returns ``(shape, "")`` or ``(None, problem)``, where the problem reads as
    the defect and carries the repair that answers it. Never raises: a
    malformed shape is something to say back to the model, not an exception to
    carry."""
    if not isinstance(raw, dict):
        return None, Problem("a shape is an object carrying 'clauses'",
                             SEND_A_SHAPE)
    clauses = raw.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        return None, Problem("'clauses' must be a non-empty list of clauses",
                             SEND_A_SHAPE)
    built = []
    for entry in clauses:
        if not isinstance(entry, dict):
            return None, Problem(
                "each clause is an object with 'text' and 'slots'",
                SHAPE_THE_CLAUSE)
        text = entry.get("text")
        if not isinstance(text, str):
            return None, Problem("each clause needs a 'text' string",
                                 SHAPE_THE_CLAUSE)
        slots = entry.get("slots") or []
        if not isinstance(slots, list):
            return None, Problem(
                "'slots' must be a list of {name, type} objects",
                SHAPE_THE_SLOTS)
        declared = []
        for slot in slots:
            if not isinstance(slot, dict):
                return None, Problem(
                    "each slot is an object with 'name' and 'type'",
                    SHAPE_THE_SLOTS)
            name, kind = slot.get("name"), slot.get("type")
            if not isinstance(name, str) or not isinstance(kind, str):
                return None, Problem(
                    "each slot needs a 'name' and a 'type', both strings",
                    SHAPE_THE_SLOTS)
            measures = slot.get("quantity") or ""
            if not isinstance(measures, str):
                return None, Problem("a slot's 'quantity' is what its number "
                                     "measures, as one word", WORD_THE_QUANTITY)
            declared.append(Slot(name=name, type=kind, quantity=measures))
        try:
            built.append(Clause(text=text, slots=tuple(declared)))
        except BadShape as bad:
            return None, bad.problem
    try:
        return Shape(clauses=tuple(built)), ""
    except BadShape as bad:
        return None, bad.problem


def weakens(before: Shape, after: Shape) -> bool:
    """Whether a second shape only takes claims away from the first.

    A shape may be re-authored once results contradict what it assumed, but only
    downwards: clauses may be dropped, and nothing may be added or reworded. So
    the new clauses must appear in the old ones, in order, unchanged. Anything
    else is a claim written after its data, which is the thing the ordering
    exists to prevent."""
    remaining = list(before.clauses)
    for clause in after.clauses:
        while remaining and remaining[0] != clause:
            remaining.pop(0)
        if not remaining:
            return False
        remaining.pop(0)
    return True
