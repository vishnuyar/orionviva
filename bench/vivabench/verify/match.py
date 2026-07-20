"""Comparing an extracted claim against ground truth. Product embryo.

Two verdicts per comparison, reported separately because they answer
different questions (design doc §5):

- strict:      the model reproduced the printed characters exactly
               ("value_raw fidelity" — matters for provenance display).
- normalized:  the model's value MEANS the same thing as the truth
               ("semantic accuracy" — what accuracy metrics use).

A model can fail strict while passing normalized ("1234.00" for "1,234.00");
that's a fidelity note, not an error. Failing normalized is an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import Normalized, parse_amount, parse_date


@dataclass(frozen=True)
class MatchResult:
    strict: bool
    normalized: bool | None      # None = could not compare (a parse failed)
    detail: str

    @property
    def correct(self) -> bool:
        """The headline verdict: semantically right?"""
        return bool(self.normalized)


def _strict_equal(a: str, b: str) -> bool:
    return a.strip() == b.strip()


def match_amount(
    extracted_raw: str,
    truth_raw: str,
    locale: str | None,
    currency: str | None,
) -> MatchResult:
    strict = _strict_equal(extracted_raw, truth_raw)
    ext = parse_amount(extracted_raw, locale=locale, currency=currency)
    tru = parse_amount(truth_raw, locale=locale, currency=currency)
    if not tru.ok:
        return MatchResult(
            strict=strict,
            normalized=None,
            detail=f"ground truth itself failed to parse ({tru.reason}) — key needs review",
        )
    if not ext.ok:
        return MatchResult(
            strict=strict,
            normalized=False,
            detail=f"extracted value unparseable/ambiguous: {ext.reason}",
        )
    same = ext.decimal() == tru.decimal()
    return MatchResult(
        strict=strict,
        normalized=same,
        detail="exact" if strict else ("equal after normalization" if same else
               f"differs: {ext.value} vs {tru.value}"),
    )


def match_date(
    extracted_raw: str,
    truth_raw: str,
    locale: str | None,
) -> MatchResult:
    strict = _strict_equal(extracted_raw, truth_raw)
    ext = parse_date(extracted_raw, locale=locale)
    tru = parse_date(truth_raw, locale=locale)
    if not tru.ok:
        return MatchResult(
            strict=strict,
            normalized=None,
            detail=f"ground truth date failed to parse ({tru.reason}) — key needs review",
        )
    if not ext.ok:
        return MatchResult(
            strict=strict,
            normalized=False,
            detail=f"extracted date unparseable/ambiguous: {ext.reason}",
        )
    same = ext.value == tru.value
    return MatchResult(
        strict=strict,
        normalized=same,
        detail="exact" if strict else ("equal after normalization" if same else
               f"differs: {ext.value} vs {tru.value}"),
    )


_WS = re.compile(r"\s+")


def match_text(extracted_raw: str, truth_raw: str) -> MatchResult:
    """Payees/descriptions: exact, then case/whitespace-insensitive."""
    strict = _strict_equal(extracted_raw, truth_raw)
    a = _WS.sub(" ", extracted_raw.strip().lower())
    b = _WS.sub(" ", truth_raw.strip().lower())
    same = a == b
    return MatchResult(
        strict=strict,
        normalized=same,
        detail="exact" if strict else ("equal ignoring case/whitespace" if same else "differs"),
    )
