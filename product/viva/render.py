"""One figure becomes words, in one place.

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

`money()` is the only way to produce a `Money`, which is what lets a template
refuse a bare number where an amount belongs — a magnitude with no currency is
the thing I1 forbids, and it cannot be smuggled through a slot that asks for
money.

The other types below name what a slot holds. Their renderers arrive with the
direction that needs them; declaring the type first is what makes an untyped
slot impossible to add quietly.
"""

from __future__ import annotations

from decimal import Decimal

from vivacore.verify.normalize import separators_for

# What a slot holds — what kind of thing in the world it is, never what a
# surface is about to do with it. The same type means the same thing in a
# question and in an answer.
MONEY = "money"          # an amount and the currency it is in
COUNT = "count"          # a number of things, never a currency
DATE = "date"            # a day some record carries
ACCOUNT = "account"      # an account, by whichever of its names is shown
MERCHANT = "merchant"    # a counterparty, as the ledger knows it
CATEGORY = "category"    # what money is, as a label
DOCUMENT = "document"    # a kind of document, never one particular record
PROSE = "prose"          # reviewed words from a pack, placed whole

TYPES = (MONEY, COUNT, DATE, ACCOUNT, MERCHANT, CATEGORY, DOCUMENT, PROSE)

# Money is written to the minor unit, and a figure is quantized before it is
# grouped so that the digits shown are the digits rounded.
CENTS = Decimal("0.01")


class Money(str):
    """An amount, written. Produced by `money()` and by nothing else.

    A place that asks for an amount can therefore ask for this, and a bare
    number — a magnitude with no currency, under no convention — cannot fill
    it."""

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


def _grouped(digits: str, separator: str) -> str:
    """Digits in threes, from the right."""
    groups = []
    while len(digits) > 3:
        groups.append(digits[-3:])
        digits = digits[:-3]
    groups.append(digits)
    return separator.join(reversed(groups))


# What each type's renderer produces, for the types that have one. A declaration
# a placer can check against, so a slot asking for a rendered thing cannot be
# handed something that was never rendered.
RENDERED: dict[str, type] = {MONEY: Money}
