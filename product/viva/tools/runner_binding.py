"""Reference binding and claim-boundary checks for a tool run."""

from __future__ import annotations

from .. import quantity, render
from ..persona import moment
from .boundary import SELECTED_TERMS, accounts_written, named_slice
from .boundary import said as _said
from .boundary import statements as _boundary
from .compute import numbers_said
from .envelope import (BY_ACCOUNT, BY_PERIOD, EXACT, HYPOTHETICAL,
                       MONEY_KINDS, weakest)
from .runner import _Ground, _decimal, _is_iso_date
from .shape import WHOLE

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
        lines.append((named_slice(cut, ground.accounts()),
                      _hedged(written, fig, kind)))
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
    accounts = ground.accounts()
    lines = [_said(statement, accounts) for statement in statements]
    if left_out:
        lines.append(moment("boundary_unmeasured",
                            account=accounts_written(left_out, accounts)))
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


