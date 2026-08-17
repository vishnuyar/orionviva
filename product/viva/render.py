"""One thing becomes words, in one place, once.

The outbound half of the same mechanism `reply.py` runs inbound. There, a
person's words become a typed value; here, a typed value becomes words. A slot
is the same kind of thing in both directions, so the two modules name one
vocabulary between them and neither knows anything about a surface: no vault, no
environment, no question queue. The caller supplies the locale, exactly as it
supplies it to the parser.

**An amount is a value AND a currency** (I1), and how its digits are grouped and
where its decimal point sits are locale conventions — held once, versioned, in
`vivacore.verify.normalize`, which is the module that already reads them in the
other direction (I2). Nothing here carries a format string of its own: a figure
written under one convention and read back under the same one is the same
figure, and that round trip is the property that says so.

**Every slot binds a reference, never a string.** The type says what kind of
thing is referenced; this module owns the choice of surface form. An account is
an entity with a name, a path, a number and an institution, and which of those a
person is shown is decided here rather than by whichever code path assembled the
sentence — so one account has one written form wherever it is spoken about.

Each constructor below is the only way to produce its own written form, which is
what lets a template refuse a bare string where a rendered thing belongs — a
magnitude with no currency is the thing I1 forbids, and it cannot be smuggled
through a slot that asks for money.
"""

from __future__ import annotations

from decimal import Decimal

from vivacore.verify.normalize import separators_for

from . import quantity
from .quantity import PER_HUNDRED

# What a slot holds — what kind of thing in the world it is, never what a
# surface is about to do with it. The same type means the same thing in a
# question and in an answer.
MONEY = "money"          # an amount and the currency it is in
COUNT = "count"          # a number of things, never a currency
RATE = "rate"            # a proportion, per hundred
DATE = "date"            # a day some record carries
PERIOD = "period"        # a span one account's statements attest
ACCOUNT = "account"      # an account, by whichever of its names is shown
MERCHANT = "merchant"    # a counterparty, as the ledger knows it
CATEGORY = "category"    # what money is, as a label
DOCUMENT = "document"    # a kind of document, never one particular record
GRADE = "grade"          # how well a figure is stood behind
ROWS = "rows"            # every figure of one read, each beside what it covers
CAVEAT = "caveat"        # what a result said its own number does not cover
SUPPOSED = "supposed"    # a value the person themselves put into this turn
PROSE = "prose"          # reviewed words from a pack, placed whole

TYPES = (MONEY, COUNT, RATE, DATE, PERIOD, ACCOUNT, MERCHANT, CATEGORY,
         DOCUMENT, GRADE, ROWS, CAVEAT, SUPPOSED, PROSE)

# Which quantities a hole of each type may ask for. A type says what shape a
# number takes and a quantity says what it is of, and the pairing is not free:
# a proportion is the only thing spoken per hundred, a number of things is the
# only thing written without a currency and without a decimal part. A type
# absent here holds no magnitude, and a hole of that type asking for one is a
# shape that never comes into being.
#
# A supposed value may be any of them, because the person may suppose about
# anything they can name — including a year, which is a point in time and not a
# magnitude, and which is therefore written as one.
QUANTITY_OF_TYPE: dict[str, frozenset] = {
    MONEY: frozenset({quantity.SPENDING, quantity.INCOME, quantity.BALANCE,
                      quantity.OWED, quantity.NET_WORTH, quantity.GROSS_FLOW,
                      quantity.NET_MOVEMENT, quantity.MOVEMENT}),
    COUNT: frozenset({quantity.COUNT}),
    RATE: frozenset({quantity.RATIO}) | frozenset(quantity.RATIOS),
    SUPPOSED: frozenset(quantity.KINDS),
}

# The same pairing read the other way: what a number MEANS decides what shape
# it takes. A hole says which of the two it wants and a figure need not, so
# anywhere a magnitude is written with no hole above it — a row of a block — the
# figure's own declaration is what picks the renderer.
#
# `SUPPOSED` is left out: it is not a shape a figure takes but a mark on a value
# the person put into their own turn, and it may be of anything, so including it
# would make every quantity ambiguous.
MAGNITUDE_OF_TYPE = {kind: measures for kind, measures in QUANTITY_OF_TYPE.items()
                     if kind != SUPPOSED}
TYPE_OF_QUANTITY: dict[str, str] = {
    measure: kind for kind, measures in MAGNITUDE_OF_TYPE.items()
    for measure in measures}

# Money is written to the minor unit, and a figure is quantized before it is
# grouped so that the digits shown are the digits rounded.
CENTS = Decimal("0.01")

# A count is a number of things, so it is written to the thing.
WHOLE = Decimal(1)

# How many significant digits a proportion keeps, counted from its leading
# digit, so a share far smaller than a hundredth is still written as itself
# rather than as zero.
RATE_FIGURES = 6


class _Written(str):
    """A thing this module wrote. A place that asks for one kind of thing can
    therefore ask for it by type, and a string that formatted itself elsewhere
    cannot be passed off as one."""

    __slots__ = ()


class Money(_Written):
    __slots__ = ()


class Count(_Written):
    __slots__ = ()


class Rate(_Written):
    __slots__ = ()


class Date(_Written):
    __slots__ = ()


class Period(_Written):
    __slots__ = ()


class Account(_Written):
    __slots__ = ()


class Merchant(_Written):
    __slots__ = ()


class Category(_Written):
    __slots__ = ()


class Document(_Written):
    __slots__ = ()


class Grade(_Written):
    __slots__ = ()


class Rows(_Written):
    __slots__ = ()


class Label(_Written):
    __slots__ = ()


class Caveat(_Written):
    __slots__ = ()


class Supposed(_Written):
    __slots__ = ()


def money(amount, currency: str = "", *, locale: str = "") -> Money:
    """One amount, in words, under one locale's conventions.

    The grouping and decimal conventions are the ones the rules module reads,
    so an amount written here is read back to the same value by
    `parse_amount` under the same locale. A locale it knows no convention for
    groups with nothing — a figure is never printed under a convention nothing
    can claim.

    The sign leads, ahead of the currency, which is the one arrangement of the
    two that reads back: the canonical form of a negative value carries its
    minus in front. An empty currency writes the value alone; that is what a
    figure whose currency is not known looks like, rather than a currency
    invented to fill the gap."""
    value = Decimal(amount).quantize(CENTS)
    point, group = separators_for(locale)
    sign = "-" if value < 0 else ""
    whole, _, fraction = str(abs(value)).partition(".")
    if group:
        whole = _grouped(whole, group)
    written = f"{whole}{point}{fraction}"
    return Money(f"{sign}{currency} {written}" if currency
                 else f"{sign}{written}")


def count(number) -> Count:
    """A number of things. Never a currency, never grouped by a convention an
    amount would be grouped by: a count of five hundred accounts is not five
    hundred of anything a person holds.

    A count is whole, and a value that is not is rounded to the nearest whole
    one rather than truncated: the digits shown are the digits of the value,
    the same way an amount's are.

    A value rounding to zero is written without a sign, so nothing is ever
    written as a negative nothing."""
    whole = Decimal(str(number)).quantize(WHOLE)
    return Count(str(abs(whole) if not whole else whole))


def rate(proportion, *, locale: str = "") -> Rate:
    """A proportion, written per hundred, to a fixed count of significant
    digits.

    The value taken is the quotient itself — one half is `0.5` — which is what
    `quantity.RATIO` names and what every division in the product produces.
    `quantity.PER_HUNDRED` is applied here and undone by the reader of a typed
    proportion in `reply`, so a proportion has one value wherever it is carried
    and one form wherever it is shown.

    Significant digits are counted from the leading digit, so a power of ten
    moves the point without moving the digits and a share far smaller than a
    hundredth keeps its own digits instead of being written as zero. Rounded,
    not truncated, to the same count of digits whatever the size."""
    value = Decimal(str(proportion)) * PER_HUNDRED
    if value:
        value = value.quantize(
            Decimal(1).scaleb(value.adjusted() - RATE_FIGURES + 1))
    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    point, _ = separators_for(locale)
    return Rate(text.replace(".", point) + "%")


def date(iso: str) -> Date:
    """A day, in the one display form this product writes.

    The form is the one the date parser reads back under every locale, which is
    what keeps a question's day and an answer's day the same day. The forms
    that are ambiguous between locales are exactly the ones I2 names as a trap,
    and none of them is written here."""
    return Date(str(iso))


def period(start: str, end: str) -> Period:
    """A span, as its two days. A period is scope — what a document answers for
    — never an account of what happened inside it."""
    return Period(f"{start} to {end}")


def _account_label(fields: dict) -> str:
    """The name one account answers to, before anything else is added."""
    name = str(fields.get("name") or "").strip()
    if not name:
        name = str(fields.get("account") or fields.get("path")
                   or "").rpartition(":")[2].strip()
    if not name:
        name = str(fields.get("number_masked") or "").strip()
    return name


def account(entity, *, among=()) -> Account:
    """One account, by whichever of its names says most.

    An account is an entity, not a string: it has a name someone gave it, a
    ledger path, a number and an institution, and choosing between them is this
    function's job rather than the job of whatever assembled the sentence. The
    name a person gave it comes first; the last segment of a ledger path is
    used where nothing else carries a name. A raw path and a bare number are
    never what a person reads.

    `among` is the company this account is being written in. Where another of
    them is written the same way, the masked number goes with the name, so two
    accounts in one sentence are never written identically. An account nothing
    collides with keeps its plain name."""
    fields = dict(entity or {})
    name = _account_label(fields)
    twins = [other for other in among
             if other is not entity and _account_label(dict(other or {})) == name]
    mask = str(fields.get("number_masked") or "").strip()
    if twins and mask and mask != name:
        return Account(f"{name} {mask}")
    return Account(name)


def accounts(entities) -> Account:
    """Several accounts in one place, each written the same way as one, and each
    told apart from the others it is written beside."""
    held = [dict(e or {}) for e in entities]
    return Account(", ".join(account(e, among=held) for e in held))


def merchant(entity) -> Merchant:
    """One counterparty, in the form this surface may show.

    A merchant has an impersonal normalized key and a descriptor lifted from
    the person's own statement, and which of the two is shown is a T9 decision.
    This is the one function that makes it, so nothing else has to remember to.
    A person reading their own ledger is shown what their statement said; the
    key is what identifies it where the descriptor may not travel."""
    fields = dict(entity or {})
    example = str(fields.get("example") or fields.get("description") or "").strip()
    return Merchant(example or str(fields.get("key") or "").strip())


def category(label) -> Category:
    """A canonical category label, as it is held."""
    return Category(str(label or "").strip())


def document(name) -> Document:
    """A kind of document, as this product's own registries name one. Never a
    particular record: naming an instance is closed on purpose."""
    return Document(str(name or "").strip())


def grade(word) -> Grade:
    """How well a figure is stood behind, in the ladder's own word."""
    return Grade(str(word or "").strip())


def label(name) -> Label:
    """A name the vault holds for a slice of itself, written as it is held.

    Not every slice of a ledger is a thing that can be asked about. A
    subcategory is stored as a pair, because two categories may each hold a
    "Fees"; a tag overlaps its neighbours; a currency code is not a thing anyone
    holds. None of the three is an entity, so none can be referred to — and all
    three are still what a figure beside them is a figure OF. This writes that
    name, as a statement of scope and never as a handle: a person handed one
    back as a filter would be refused, and the refusal names what is
    filterable."""
    return Label(str(name or "").strip())


def rows(lines, *, grade: str = "") -> Rows:
    """Every figure of one read, one to a line, each beside the slice it covers.

    A block, not a sentence, and it opens on a line of its own: the words that
    introduce it sit in the same clause, ahead of the hole, so the first line
    starts under them rather than beside them. How many lines there are is not
    knowable when the answer is shaped — the person may hold three subcategories
    or thirty — so nothing above ever writes a line, and nothing here knows what
    the lines are about: `lines` is pairs of things this module already wrote, a
    name and the magnitude taken over it.

    The grade goes once, above, and is worded as being about the set. It is one
    grade computed over the whole read and stamped on every figure in it, so a
    word repeated per line would read as a claim about that line when it is a
    claim about the read. Where nothing carries a grade, nothing is said.

    The words around the two halves of a line are the pack's, like every other
    thing Viva says."""
    from .persona import moment

    written = [moment("rows_line", name=name, amount=amount)
               for name, amount in lines]
    if grade:
        written.insert(0, moment("rows_stood_behind", grade=grade))
    return Rows("\n" + "\n".join(written))


def caveat(sentence) -> Caveat:
    """What a result said its own number does not cover, in the tool's own
    words. Verbatim: a caveat re-worded is a caveat weakened."""
    return Caveat(str(sentence or "").strip())


def supposed(value, measures: str, *, locale: str = "") -> Supposed:
    """A value the person themselves put into this turn, marked as theirs.

    A premise is not a measurement, and the words saying whose premise it is
    are placed here rather than left to whatever writes the sentence around it,
    so a value resting on no record cannot reach a person unmarked.

    `measures` decides how it is written: an amount as an amount whose currency
    nothing has stated, a number of things as a count, a proportion per
    hundred, and a point in time as itself rather than as a magnitude.

    The marker's words come from the pack, like every other thing Viva says.
    The pack is loaded at the moment of writing rather than at import, so this
    module and the persona need not be imported in any particular order."""
    from .persona import moment

    if measures == quantity.TIME:
        return Supposed(moment("supposed_time", when=str(value).strip()))
    if measures == quantity.COUNT:
        written = count(value)
    elif quantity.is_ratio(measures):
        # A value the person put into their own question is already per
        # hundred, so it is scaled down before `rate` scales it back up and
        # their own digits come out.
        written = rate(Decimal(str(value)) / PER_HUNDRED, locale=locale)
    else:
        written = money(value, locale=locale)
    return Supposed(moment("supposed_amount", amount=written))


def _grouped(digits: str, separator: str) -> str:
    """Digits in threes, from the right."""
    groups = []
    while len(digits) > 3:
        groups.append(digits[-3:])
        digits = digits[:-3]
    groups.append(digits)
    return separator.join(reversed(groups))


# What each type's renderer produces. A declaration a placer can check against,
# so a slot asking for a rendered thing cannot be handed something that was
# never rendered. `prose` has no entry deliberately: reviewed pack words nest
# inside reviewed pack words, and are never a hole for text nobody reviewed.
# `label` has none for a different reason: it is not a kind of thing a hole may
# hold. A name the vault holds for a slice of itself is written where the
# machine places one, and there is nothing to refer to it by.
RENDERED: dict[str, type] = {
    MONEY: Money, COUNT: Count, RATE: Rate, DATE: Date, PERIOD: Period,
    ACCOUNT: Account, MERCHANT: Merchant, CATEGORY: Category,
    DOCUMENT: Document, GRADE: Grade, ROWS: Rows, CAVEAT: Caveat,
    SUPPOSED: Supposed,
}
