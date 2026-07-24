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


def check_paystub_identity(
    gross: Decimal | str,
    deductions: Iterable[Decimal | str],
    net: Decimal | str,
    tolerance: Decimal | str = "0",
) -> CheckResult:
    """gross - sum(deductions) == net.

    A pay stub's self-check, the divergent sibling of the balance identity: if it
    passes, the gross, every deduction, and the net corroborate each other at
    once. The universal gate runs it; the formula is the pay stub profile's data
    (the registry's 'code universal, per-type formula is data' claim, Slice 4).
    """
    gross_d = _as_decimal(gross)
    net_d = _as_decimal(net)
    tol = _as_decimal(tolerance)
    total_ded = sum((_as_decimal(d) for d in deductions), start=Decimal("0"))
    expected_net = gross_d - total_ded
    delta = net_d - expected_net
    return CheckResult(
        passed=abs(delta) <= tol,
        check="pay-stub identity (gross - deductions = net)",
        expected=str(expected_net),
        actual=str(net_d),
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
