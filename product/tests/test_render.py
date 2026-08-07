"""A figure becomes words in one place, and the words read back as the figure.

One property carries this file: **what the renderer writes, the parser reads,
and it reads it as the same amount.** The two directions share one set of
locale conventions — the versioned rules in `vivacore.verify.normalize` — so a
figure a person is shown and a figure a person types are the same kind of
object, written and read the same way.

That is also what makes the property testable without anyone deciding how a
number ought to look: the correct rendering is whichever one the rules already
in force read back unchanged. A form the parser refuses, or reads as a different
amount, is wrong however good it looks.
"""

import pathlib
import re
from decimal import Decimal

import pytest
from vivacore.verify.normalize import parse_amount

from viva import render

_PACKAGE = pathlib.Path(render.__file__).resolve().parent

# A module speaks to a person when it places the pack's words or the renderer's
# figures. Found rather than listed, because a hand-kept list of two modules
# stops being the rule the moment a third one starts writing sentences.
_SPEAKS = re.compile(r"^from \.+(?:persona|render) import", re.M)

# A figure written anywhere but the one renderer. The forms are what a second
# convention looks like in Python: a format spec with a fixed number of decimal
# places, however it is reached, and a number turned into a string by rounding
# it first.
_SELF_FORMATTED = (re.compile(r"\.\d+f"), re.compile(r"str\(\s*round\("))


def _person_facing():
    """Every module that puts words or figures in front of a person, except the
    renderer itself — which is the one place a figure is allowed to become
    characters."""
    return [p for p in sorted(_PACKAGE.rglob("*.py"))
            if p.name != "render.py" and _SPEAKS.search(p.read_text())]

# Two locales whose conventions disagree about both separators, which is the
# disagreement a single format string cannot survive.
DOT_DECIMAL = "en-US"
COMMA_DECIMAL = "de-DE"


@pytest.mark.parametrize("locale", [DOT_DECIMAL, COMMA_DECIMAL])
@pytest.mark.parametrize("amount", ["0.05", "12.00", "1234.56", "1234567.89"])
def test_an_amount_written_is_read_back_as_the_same_amount(locale, amount):
    """The round trip, over sizes that cross every grouping boundary."""
    written = render.money(amount, "USD", locale=locale)
    read = parse_amount(written, locale=locale, currency="USD")

    assert read.ok, read.reason
    assert read.decimal() == Decimal(amount)
    assert read.currency == "USD"


def test_two_locales_write_the_same_amount_differently_and_both_are_read():
    """Which is the whole point of taking the conventions from the rules module
    rather than from a format string: one of these two is what a person's
    paperwork looks like, and the product does not get to decide which."""
    dotted = render.money("1234.56", "EUR", locale=DOT_DECIMAL)
    commaed = render.money("1234.56", "EUR", locale=COMMA_DECIMAL)

    assert dotted != commaed
    assert parse_amount(dotted, locale=DOT_DECIMAL).decimal() == Decimal("1234.56")
    assert parse_amount(commaed, locale=COMMA_DECIMAL).decimal() == Decimal("1234.56")


def test_with_no_locale_a_figure_is_grouped_by_nothing():
    """A grouping separator only means something under a convention. With none
    named, the parser calls a grouped figure ambiguous rather than guessing — so
    the only honest thing to write is the ungrouped form it reads back."""
    written = render.money("1234567.89", "USD")

    assert "," not in written and written.count(".") == 1
    read = parse_amount(written)
    assert read.ok and read.decimal() == Decimal("1234567.89")


def test_a_negative_amount_reads_back_negative():
    """A sign is part of the figure, not decoration on it. It leads, because
    that is the arrangement the parser reads back and the form the rules module
    itself carries a negative value in."""
    written = render.money("-500.00", "USD", locale=DOT_DECIMAL)
    read = parse_amount(written, locale=DOT_DECIMAL, currency="USD")

    assert read.ok, read.reason
    assert read.decimal() == Decimal("-500.00")


def test_an_amount_whose_currency_is_unknown_is_not_given_one():
    """A figure with no currency is written as the value alone. Supplying one
    would be the product deciding what a person holds."""
    written = render.money("40.00")
    read = parse_amount(written)

    assert read.ok and read.decimal() == Decimal("40.00")
    assert read.currency is None


def test_only_the_renderer_produces_something_a_money_slot_accepts():
    """An amount is a value AND a currency (I1). The renderer's output says so
    by its type, so a slot that needs one can ask for it and a bare number
    cannot be passed off as one."""
    assert isinstance(render.money("1.00", "USD"), render.Money)
    assert not isinstance("USD 1.00", render.Money)
    assert render.RENDERED[render.MONEY] is render.Money


def test_no_module_that_speaks_to_a_person_formats_money_itself():
    """Every amount a person is shown goes through the one renderer. A number
    formatted anywhere else is a second convention, and a second convention is
    what disagreed with the first.

    Both halves of this are the point: the forms a figure can be formatted in
    are checked, not one of them, and the modules checked are whichever ones
    speak to a person, not a list someone remembered to extend."""
    speaking = _person_facing()
    found = {str(p.relative_to(_PACKAGE)) for p in speaking}
    assert {"questions.py", "knowledge/__init__.py"} <= found, (
        f"the search for person-facing modules found {sorted(found)} — it has "
        "stopped reaching modules that are plainly speaking")
    for path in speaking:
        source = path.read_text()
        for pattern in _SELF_FORMATTED:
            assert not pattern.search(source), (
                f"{path.name} formats a figure itself ({pattern.pattern!r}) — an "
                "amount is written by the one renderer, under the locale's own "
                "conventions")
