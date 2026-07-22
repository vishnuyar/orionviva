"""verify/ — product embryo. The first draft of OrionViva's verification layer.

Everything in this package is deterministic, locale-aware, versioned, and
tested to a stricter standard than the rest of viva-bench (ADR-010: this is
the code that one day decides whether Viva says "I'm sure").

Modules:
- normalize   — raw printed strings -> typed values, honestly (ambiguity is a
                first-class outcome, never a guess). Invariants I1, I2.
- arithmetic  — the identities financial documents impose on themselves
                (balances reconcile, line items sum). Exact Decimal math (T2).
- match       — comparing an extracted claim against ground truth.

RULES_VERSION identifies the normalization ruleset; scores are only comparable
within a version (I2).
"""

from .normalize import (
    RULES_VERSION,
    Normalized,
    parse_amount,
    parse_date,
)
from .arithmetic import CheckResult, check_balance_identity, check_sum
from .match import MatchResult, match_amount, match_date, match_text

__all__ = [
    "RULES_VERSION",
    "Normalized",
    "parse_amount",
    "parse_date",
    "CheckResult",
    "check_balance_identity",
    "check_sum",
    "MatchResult",
    "match_amount",
    "match_date",
    "match_text",
]
