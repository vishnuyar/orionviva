"""verify/ — the verification layer.

Everything in this package is deterministic, locale-aware and versioned: no
model call, no network, no clock.

Modules:
- normalize   — raw printed strings -> typed values; ambiguity is a first-class
                outcome, never a guess.
- arithmetic  — the identities financial documents impose on themselves
                (balances reconcile, line items sum). Exact Decimal math.
- match       — comparing an extracted claim against ground truth.

RULES_VERSION identifies the normalization ruleset; scores are only comparable
within a version.
"""

from .normalize import (
    normalize_locale,
    RULES_VERSION,
    Normalized,
    parse_amount,
    parse_date,
)
from .arithmetic import (CheckResult, check_balance_identity,
                         check_paystub_identity, check_sum)
from .match import MatchResult, match_amount, match_date, match_text

__all__ = [
    "RULES_VERSION",
    "Normalized",
    "parse_amount",
    "parse_date",
    "CheckResult",
    "check_balance_identity",
    "check_paystub_identity",
    "check_sum",
    "MatchResult",
    "match_amount",
    "match_date",
    "match_text",
]
