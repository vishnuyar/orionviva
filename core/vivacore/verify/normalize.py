"""Locale-aware normalization of printed values. Product embryo (I1, I2).

The honesty contract, enforced by types rather than intentions:
- Every parse returns a status: "ok", "ambiguous", or "invalid".
- "ambiguous" is a first-class outcome — the caller decides what doubt means
  (in the product: grade `conflicted`, never guess). We NEVER pick silently.
- Every assumption used (e.g. "locale de-DE implies comma decimal") is
  recorded in the result, so a verdict can always explain itself.

Amounts are Decimal. Floats do not appear in this module (T2): 0.1 + 0.2
must equal 0.3 in a product that promises to never bluff a number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

RULES_VERSION = "nv1"

# Locale families for separator conventions. Extend deliberately, with tests.
_COMMA_DECIMAL_LOCALES = ("de", "fr", "es", "it", "pt", "nl", "tr")   # 1.234,56
_DOT_DECIMAL_LOCALES = ("en", "ja", "zh", "ko", "hi", "th")           # 1,234.56

_CURRENCY_SYMBOLS = {
    "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY",
    "₹": "INR", "₩": "KRW", "C$": "CAD", "A$": "AUD", "CHF": "CHF",
}
_CURRENCY_CODES = ("USD", "EUR", "GBP", "JPY", "INR", "CAD", "AUD", "CHF", "CNY", "KRW")

_SPACES = "    "  # nbsp, thin space, narrow nbsp, space


@dataclass(frozen=True)
class Normalized:
    status: str                      # "ok" | "ambiguous" | "invalid"
    value: str | None = None         # canonical form: amount as plain Decimal string, date as ISO yyyy-mm-dd
    currency: str | None = None      # ISO 4217 if detected or supplied (I1)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    reason: str | None = None        # for ambiguous/invalid: why
    rules_version: str = RULES_VERSION

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def decimal(self) -> Decimal:
        if self.status != "ok" or self.value is None:
            raise ValueError(f"No usable value: status={self.status}, reason={self.reason}")
        return Decimal(self.value)


# ------------------------------------------------------------------ amounts


def parse_amount(raw: str, locale: str | None = None, currency: str | None = None) -> Normalized:
    """Parse a printed monetary amount.

    ``locale`` (e.g. "en-US", "de-DE") decides separator conventions; without
    it, genuinely ambiguous strings (like "1.234") come back "ambiguous".
    ``currency`` is the document's declared currency; a conflicting printed
    symbol makes the parse invalid rather than silently preferring either.
    """
    if raw is None or not str(raw).strip():
        return Normalized(status="invalid", reason="empty value")
    text = str(raw)
    assumptions: list[str] = []

    for ch in _SPACES:
        text = text.replace(ch, " ")
    text = text.strip()

    # --- negativity conventions ------------------------------------------
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
        assumptions.append("parentheses denote negative")
    m = re.search(r"\b(DR|CR)\.?\s*$", text, re.IGNORECASE)
    if m:
        if m.group(1).upper() == "DR":
            negative = True
            assumptions.append("trailing DR denotes negative (debit)")
        else:
            assumptions.append("trailing CR denotes positive (credit)")
        text = text[: m.start()].strip()
    if text.endswith("-"):
        negative = True
        text = text[:-1].strip()
        assumptions.append("trailing minus denotes negative")
    if text.startswith("-") or text.startswith("−"):
        negative = True
        text = text.lstrip("-−").strip()
    if text.startswith("+"):
        text = text[1:].strip()

    # --- currency ---------------------------------------------------------
    detected_currency = None
    for symbol in sorted(_CURRENCY_SYMBOLS, key=len, reverse=True):
        if text.startswith(symbol) or text.endswith(symbol):
            detected_currency = _CURRENCY_SYMBOLS[symbol]
            text = text.removeprefix(symbol).removesuffix(symbol).strip()
            break
    if detected_currency is None:
        for code in _CURRENCY_CODES:
            pattern = rf"(^{code}\b)|(\b{code}$)"
            if re.search(pattern, text):
                detected_currency = code
                text = re.sub(pattern, "", text).strip()
                break
    if detected_currency and currency and detected_currency != currency.upper():
        return Normalized(
            status="invalid",
            reason=f"printed currency {detected_currency} conflicts with document currency {currency.upper()}",
            assumptions=tuple(assumptions),
        )
    final_currency = detected_currency or (currency.upper() if currency else None)

    text = text.replace(" ", "")
    if not text or not re.fullmatch(r"[0-9.,']+", text):
        return Normalized(
            status="invalid",
            reason=f"not a recognizable number: {raw!r}",
            assumptions=tuple(assumptions),
        )
    text = text.replace("'", "")  # Swiss grouping

    # --- separators -------------------------------------------------------
    result = _resolve_separators(text, locale, assumptions)
    if result.status != "ok":
        return Normalized(
            status=result.status,
            reason=result.reason,
            currency=final_currency,
            assumptions=tuple(assumptions),
        )

    try:
        value = Decimal(result.value)  # type: ignore[arg-type]
    except InvalidOperation:
        return Normalized(
            status="invalid",
            reason=f"unparseable after separator resolution: {result.value!r}",
            assumptions=tuple(assumptions),
        )
    if negative:
        value = -value
    return Normalized(
        status="ok",
        value=str(value),
        currency=final_currency,
        assumptions=tuple(assumptions),
    )


def _decimal_separator_for(locale: str | None) -> str | None:
    if not locale:
        return None
    lang = locale.split("-")[0].lower()
    if lang in _COMMA_DECIMAL_LOCALES:
        return ","
    if lang in _DOT_DECIMAL_LOCALES:
        return "."
    return None


def _resolve_separators(text: str, locale: str | None, assumptions: list[str]) -> Normalized:
    """Turn a digits-with-separators string into a plain Decimal string."""
    has_dot, has_comma = "." in text, "," in text

    if not has_dot and not has_comma:
        return Normalized(status="ok", value=text)

    if has_dot and has_comma:
        # Whichever separator appears LAST is the decimal separator; the other
        # is grouping. Unambiguous regardless of locale: "1.234,56" / "1,234.56".
        last_dot, last_comma = text.rfind("."), text.rfind(",")
        dec = "," if last_comma > last_dot else "."
        grp = "." if dec == "," else ","
        assumptions.append(f"both separators present; '{dec}' (last) taken as decimal")
        cleaned = text.replace(grp, "").replace(dec, ".")
        return _validate_single_decimal(cleaned)

    sep = "." if has_dot else ","
    parts = text.split(sep)

    # Multiple occurrences of one separator => it is grouping: "1.234.567",
    # "1,23,45,678" (Indian grouping falls out naturally here).
    if len(parts) > 2:
        assumptions.append(f"repeated '{sep}' taken as grouping separator")
        return Normalized(status="ok", value=text.replace(sep, ""))

    # Exactly one separator occurrence: the interesting case.
    head, tail = parts
    if len(tail) != 3:
        # "1234.56", "0,5", "12.3456" — grouping would demand exactly 3 digits,
        # so this must be a decimal separator.
        assumptions.append(f"single '{sep}' with {len(tail)} trailing digits taken as decimal")
        return _validate_single_decimal(f"{head}.{tail}")

    # Exactly 3 trailing digits: "1.234" / "1,234" — the truly ambiguous shape.
    locale_dec = _decimal_separator_for(locale)
    if locale_dec is None:
        return Normalized(
            status="ambiguous",
            reason=(
                f"{head}{sep}{tail}: '{sep}' could be decimal or grouping; "
                "no locale provided to decide"
            ),
        )
    if sep == locale_dec:
        assumptions.append(f"locale {locale} implies '{sep}' is decimal")
        return _validate_single_decimal(f"{head}.{tail}")
    assumptions.append(f"locale {locale} implies '{sep}' is grouping")
    return Normalized(status="ok", value=head + tail)


def _validate_single_decimal(candidate: str) -> Normalized:
    if candidate.count(".") > 1:
        return Normalized(status="invalid", reason=f"multiple decimal points: {candidate!r}")
    return Normalized(status="ok", value=candidate)


# ------------------------------------------------------------------ dates


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Locales whose numeric dates read month-first. Everyone else: day-first.
_MONTH_FIRST_LOCALES = ("en-US", "en-PH")


def parse_date(raw: str, locale: str | None = None,
               default_year: int | None = None) -> Normalized:
    """Parse a printed date to ISO yyyy-mm-dd.

    The infamous trap — "03/04/2025" — is March 4 in the US and April 3 in
    most of the world. With a locale we resolve it and record the assumption;
    without one, if both readings are valid, the answer is "ambiguous".

    ``default_year`` supplies the year for a date printed WITHOUT one (bank
    statements print transaction lines as "04/17"); the caller derives it from
    the statement period. Without it, a year-less date stays invalid — we never
    invent a year.
    """
    if raw is None or not str(raw).strip():
        return Normalized(status="invalid", reason="empty value")
    text = str(raw).strip()
    assumptions: list[str] = []

    # ISO: 2025-04-03 (also 2025/04/03, 2025.04.03)
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        y, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _make_date(y, a, b, assumptions + ["year-first read as ISO year-month-day"])

    # Month-name forms: "Jan 5, 2026", "5 Jan 2026", "January 5 2026", "05-Jan-2026"
    m = re.fullmatch(
        r"(?:(\d{1,2})[\s\-]+)?([A-Za-z]{3,9})\.?[\s\-,]+(\d{1,2})?,?\s*(\d{4})", text
    )
    if m:
        day_before, month_name, day_after, year = m.groups()
        month = _MONTHS.get(month_name.lower()[:4].rstrip("."), _MONTHS.get(month_name.lower()[:3]))
        day = day_before or day_after
        if month and day:
            return _make_date(int(year), month, int(day), assumptions + ["month written as name"])
        return Normalized(status="invalid", reason=f"unrecognized month name in {raw!r}")

    # Numeric: a/b/yyyy or a-b-yyyy or a.b.yyyy (2- or 4-digit year)
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
            assumptions.append("two-digit year read as 20xx")
        a_could_be_month = 1 <= a <= 12
        b_could_be_month = 1 <= b <= 12
        if a_could_be_month and not b_could_be_month:
            return _make_date(y, a, b, assumptions + ["only first field can be a month"])
        if b_could_be_month and not a_could_be_month:
            return _make_date(y, b, a, assumptions + ["only second field can be a month"])
        if not a_could_be_month and not b_could_be_month:
            return Normalized(status="invalid", reason=f"no valid month reading of {raw!r}")
        if a == b:
            return _make_date(y, a, b, assumptions)  # 3/3/2026 — same either way
        # Both readings valid: the trap. Locale or bust.
        if locale in _MONTH_FIRST_LOCALES:
            return _make_date(y, a, b, assumptions + [f"locale {locale} reads month-first"])
        if locale:
            return _make_date(y, b, a, assumptions + [f"locale {locale} reads day-first"])
        return Normalized(
            status="ambiguous",
            reason=f"{raw!r}: both month-first and day-first readings are valid; no locale to decide",
        )

    # Year-less numeric: "04/17", "4-17" — common on statement transaction lines.
    # Only resolvable with a default_year the caller derived from the period.
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})", text)
    if m and default_year is not None:
        a, b = int(m.group(1)), int(m.group(2))
        y = default_year
        note = f"no year printed; used statement-period year {y}"
        a_month, b_month = 1 <= a <= 12, 1 <= b <= 12
        if a_month and not b_month:
            return _make_date(y, a, b, assumptions + [note, "first field is month"])
        if b_month and not a_month:
            return _make_date(y, b, a, assumptions + [note, "second field is month"])
        if not a_month and not b_month:
            return Normalized(status="invalid", reason=f"no valid month reading of {raw!r}")
        if a == b:
            return _make_date(y, a, b, assumptions + [note])
        if locale in _MONTH_FIRST_LOCALES:
            return _make_date(y, a, b, assumptions + [note, f"locale {locale} month-first"])
        if locale:
            return _make_date(y, b, a, assumptions + [note, f"locale {locale} day-first"])
        return Normalized(
            status="ambiguous",
            reason=f"{raw!r}: month/day order unresolved and no locale given")

    return Normalized(status="invalid", reason=f"unrecognized date format: {raw!r}")


_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _make_date(year: int, month: int, day: int, assumptions: list[str]) -> Normalized:
    if not (1 <= month <= 12):
        return Normalized(status="invalid", reason=f"month {month} out of range")
    if not (1 <= day <= _DAYS_IN_MONTH[month - 1]):
        return Normalized(status="invalid", reason=f"day {day} invalid for month {month}")
    if month == 2 and day == 29 and not _is_leap(year):
        return Normalized(status="invalid", reason=f"Feb 29 in non-leap year {year}")
    return Normalized(
        status="ok",
        value=f"{year:04d}-{month:02d}-{day:02d}",
        assumptions=tuple(assumptions),
    )


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
