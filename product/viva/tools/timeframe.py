"""What an answer's dates mean, and whether the reads covered them.

A date is a coordinate, not a quantity. It is checked by containment — does it
fall inside a period a read reported covering, or is it a date a read asserted
— rather than by matching its digits against the pool of numbers a figure draws
from. Keeping the two apart is what stops an amount riding on a date's year.

Recognizing a date written in prose is delegated to the shared normalization
layer, which owns every date format and the locale that disambiguates them. The
patterns here are structural: they say where a date might be written, never
what any word means.
"""

from __future__ import annotations

import re

from vivacore.verify.normalize import parse_date

# Where a date might be written: an ISO date, a month word carrying a year with
# or without a day, or a numeric date. Whether any of these IS a date, and
# which one, is decided by parse_date.
_MENTION = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|(?:\d{1,2}(?:st|nd|rd|th)?[\s\-]+)?[A-Za-z]{3,9}\.?[\s\-,]+"
    r"(?:\d{1,2}(?:st|nd|rd|th)?,?[\s\-]+)?\d{4}"
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}",
    re.IGNORECASE)

_ORDINAL = re.compile(r"(?<=\d)(?:st|nd|rd|th)\b", re.IGNORECASE)

_MONTH_AND_YEAR = re.compile(r"([A-Za-z]{3,9})\.?[\s\-,]+(\d{4})")


def mentions(text: str, locale: str) -> list:
    """Every date written in `text`, as `(what was written, what it means)`.

    The meaning is an ISO date when a day was written and a `YYYY-MM` month
    when only a month and a year were. A run shaped like a date that resolves
    to no real date is not a mention: its digits fall through to the figure
    check, which is what refuses an invented number."""
    found = []
    for match in _MENTION.finditer(text):
        written = match.group(0)
        raw = _ORDINAL.sub("", written).strip().strip(",").strip()
        parsed = parse_date(raw, locale)
        if parsed.ok and parsed.value:
            found.append((written, parsed.value))
            continue
        month = _month(raw, locale)
        if month:
            found.append((written, month))
    return found


def _month(raw: str, locale: str) -> str:
    """`YYYY-MM` when `raw` names a month and a year and nothing else.

    The month word is resolved by asking the shared parser for the first of
    that month, so the names of the months live in one place and this module
    holds no vocabulary of its own."""
    parts = _MONTH_AND_YEAR.fullmatch(raw)
    if not parts:
        return ""
    word, year = parts.groups()
    parsed = parse_date(f"1 {word} {year}", locale)
    return parsed.value[:7] if parsed.ok and parsed.value else ""


def covered_by(period, when: str) -> bool:
    """Whether a `(from, to)` period covers a date, or overlaps a month."""
    start, end = period
    if not start or not end:
        return False
    if len(when) == 7:
        return start[:7] <= when <= end[:7]
    return start <= when <= end


def stated_by(meaning: str, dates) -> bool:
    """Whether one of the declared dates is what a written date meant — the
    date itself, or any day of it when only a month was written."""
    if len(meaning) == 7:
        return any(d[:7] == meaning for d in dates)
    return meaning in dates
