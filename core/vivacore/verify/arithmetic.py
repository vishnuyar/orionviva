"""The identities financial documents impose on themselves. Product embryo (T2).

Exact Decimal arithmetic, no floats, no tolerance by default: a statement that
doesn't reconcile to the cent is a finding, not a rounding error. (A tolerance
parameter exists because some documents legitimately round displayed subtotals;
using it is a recorded decision, never a silent default.)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    check: str                 # which identity ran
    expected: str              # Decimal as string
    actual: str
    delta: str                 # actual - expected
    tolerance: str

    def explain(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"[{verdict}] {self.check}: expected {self.expected}, "
            f"got {self.actual} (delta {self.delta}, tolerance {self.tolerance})"
        )


def _as_decimal(x: Decimal | str | int) -> Decimal:
    if isinstance(x, float):  # type: ignore[unreachable]
        raise TypeError(
            "float is not allowed in verification arithmetic (T2); "
            "pass Decimal or str"
        )
    return Decimal(x)


def check_balance_identity(
    opening: Decimal | str,
    transactions: Iterable[Decimal | str],
    closing: Decimal | str,
    tolerance: Decimal | str = "0",
) -> CheckResult:
    """opening + sum(signed transactions) == closing.

    The single strongest check a bank/card statement offers: if it passes,
    every transaction amount and both balances corroborate each other at once.
    """
    opening_d = _as_decimal(opening)
    closing_d = _as_decimal(closing)
    tol = _as_decimal(tolerance)
    total = sum((_as_decimal(t) for t in transactions), start=Decimal("0"))
    expected = opening_d + total
    delta = closing_d - expected
    return CheckResult(
        passed=abs(delta) <= tol,
        check="balance identity (opening + transactions = closing)",
        expected=str(expected),
        actual=str(closing_d),
        delta=str(delta),
        tolerance=str(tol),
    )


def check_sum(
    items: Iterable[Decimal | str],
    total: Decimal | str,
    label: str = "line items sum to total",
    tolerance: Decimal | str = "0",
) -> CheckResult:
    """sum(items) == total — subtotals, fee totals, deposit totals, etc."""
    tol = _as_decimal(tolerance)
    total_d = _as_decimal(total)
    expected = sum((_as_decimal(i) for i in items), start=Decimal("0"))
    delta = total_d - expected
    return CheckResult(
        passed=abs(delta) <= tol,
        check=label,
        expected=str(expected),
        actual=str(total_d),
        delta=str(delta),
        tolerance=str(tol),
    )
