"""The identities financial documents impose on themselves.

Exact Decimal arithmetic, no floats, and no tolerance by default: a statement
that does not reconcile to the cent fails. Every check takes an explicit
``tolerance`` for documents that round their displayed subtotals; it defaults to
zero and is recorded in the result.

Passing a float raises TypeError rather than being coerced (T2).
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

    A bank or card statement's own flow check: passing it corroborates every
    transaction amount and both balances at once. Transactions carry their sign.
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

    A pay stub's own check: passing it corroborates the gross, every deduction
    and the net at once. Deductions are given as positive magnitudes.
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


def check_brokerage_identity(
    position_values: Iterable[Decimal | str],
    cash: Decimal | str,
    total: Decimal | str,
    tolerance: Decimal | str = "0",
) -> CheckResult:
    """sum(position market values) + cash == account total.

    A brokerage statement's own check: a point-in-time snapshot test rather than
    a flow. Passing it corroborates every position value and the cash against
    the stated total at once, so a single misread holding fails it.
    """
    cash_d = _as_decimal(cash)
    total_d = _as_decimal(total)
    tol = _as_decimal(tolerance)
    holdings = sum((_as_decimal(v) for v in position_values), start=Decimal("0"))
    expected = holdings + cash_d
    delta = total_d - expected
    return CheckResult(
        passed=abs(delta) <= tol,
        check="brokerage identity (Σ positions + cash = total)",
        expected=str(expected),
        actual=str(total_d),
        delta=str(delta),
        tolerance=str(tol),
    )


def check_sum(
    items: Iterable[Decimal | str],
    total: Decimal | str,
    label: str = "line items sum to total",
    tolerance: Decimal | str = "0",
) -> CheckResult:
    """sum(items) == total — subtotals, fee totals, deposit totals.

    ``label`` names the check in the result."""
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
