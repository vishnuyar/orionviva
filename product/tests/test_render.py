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


def _significant(written) -> str:
    """The digits a written proportion actually shows. A sign, a point and any
    leading zeros say where the value sits, not what it is."""
    text = str(written).rstrip("%").lstrip("-")
    return text.replace(",", "").replace(".", "").lstrip("0")


@pytest.mark.parametrize("number, whole", [("18.9", "19"), ("18.2857", "18"),
                                           ("-18.9", "-19"), ("1.5", "2"),
                                           ("128", "128"), ("-0.4", "0")])
def test_a_count_is_written_to_the_nearest_whole_thing(number, whole):
    """A count is whole, and a value that is not is rounded to the nearest one.

    Cutting it off at the point is a different number — always smaller, always
    silently — and the person is shown digits that are not the digits of the
    value they were told about. The last of these is the other half: a value
    rounded away to nothing is nothing, and a sign in front of it would say a
    direction it no longer has."""
    assert render.count(number) == whole


@pytest.mark.parametrize("power", [0, 2, -2, -4])
def test_a_proportion_keeps_its_digits_wherever_the_point_falls(power):
    """Significant digits, which is what the count of them is named for: a
    power of ten moves the point without moving the digits, so a share far
    smaller than a hundredth is written as itself rather than rounded a second
    time by the position it happens to sit at."""
    value = Decimal("1.23456789").scaleb(power)
    written = render.rate(value)

    assert _significant(written) == _significant(render.rate("1.23456789"))
    assert len(_significant(written)) == render.RATE_FIGURES


def test_a_proportion_shows_the_digits_it_was_rounded_to():
    """And rounded, not cut: the last digit shown is the one the value rounds
    to. Cutting would write 123456 where the value is nearer 123457."""
    assert _significant(render.rate("0.1234567")) == "123457"


@pytest.mark.parametrize("proportion,written", [
    ("0.5", "50%"), ("1", "100%"), ("0.001", "0.1%"), ("2", "200%"), ("0", "0%"),
])
def test_a_proportion_is_carried_per_one_and_written_per_hundred(proportion,
                                                                written):
    """`ratio` is one quantity over another — a quotient — so a half is `0.5`
    everywhere it is carried and fifty percent where it is written. The two
    units meet in this function and in the reader of a typed proportion, and
    nowhere else."""
    assert str(render.rate(proportion)) == written


def test_only_the_renderer_produces_something_a_money_slot_accepts():
    """An amount is a value AND a currency (I1). The renderer's output says so
    by its type, so a slot that needs one can ask for it and a bare number
    cannot be passed off as one."""
    assert isinstance(render.money("1.00", "USD"), render.Money)
    assert not isinstance("USD 1.00", render.Money)
    assert render.RENDERED[render.MONEY] is render.Money


def test_no_module_that_speaks_to_a_person_formats_money_itself():
    """Every amount a person is shown goes through the one renderer. A number
    formatted anywhere else is a second convention.

    Both halves matter: the forms a figure can be formatted in are checked,
    not one of them, and the modules checked are whichever ones speak to a
    person rather than a list someone remembered to extend."""
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


@pytest.mark.parametrize("name", [
    "Checking 000000001234",
    "Checking 0000 0000 1234",
    "Checking 0000-0000-1234",
])
def test_an_account_name_cannot_bypass_number_masking(name):
    written = render.account({"name": name, "number_masked": "••••1234"})

    assert written == "Checking ••••1234"
    assert "0000" not in written
