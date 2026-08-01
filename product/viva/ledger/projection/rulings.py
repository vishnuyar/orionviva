"""What rulings have said, and the derived accounts they brought into being."""

from __future__ import annotations

from decimal import Decimal

from ..events import ASSERTED, SCOPE_MOVEMENT
from . import merchants as merchants_view
from . import movements as movements_view
from .core import ProjectionCore


def rulings(core: ProjectionCore, scope: str | None = None) -> list[dict]:
    """Every ruling, sorted, optionally filtered to one scope. Each dict is
    the event body plus its ``scope`` and ``subject``."""
    return [dict(body, scope=s, subject=subj)
            for (s, subj), body in sorted(core._rulings.items())
            if scope is None or s == scope]


def ruled_accounts(core: ProjectionCore) -> dict[str, dict]:
    """The chart of accounts as rulings have built it: every ruled account
    path, with the cash that flowed to it, the movement count, and whether
    the figure can be trusted as a BALANCE.

    Three properties net worth reads:

    * ``origin`` is ``asserted`` — nobody issued these accounts.
    * ``reliable_balance`` is False whenever any contributing movement was
      ``MIXED``: cash reaching a mortgage account is a fact, but part of it
      was interest, so it is not a debt reduction of that size.
    * ``paid`` is **cost — what was paid** — never a present-day value. A
      car account holds its purchase price, and ``valuation`` says
      ``measured`` or ``estimated``."""
    out: dict[str, dict] = {}
    for m in movements_view.movements(core):
        if not m.ruling_account:
            continue
        row = out.setdefault(m.ruling_account, {
            "account": m.ruling_account, "paid": Decimal("0"), "count": 0,
            "currency": m.currency, "origin": ASSERTED,
            "reliable_balance": True, "valuation": "measured"})
        row["paid"] += abs(m.amount)
        row["count"] += 1
        if m.nature == movements_view.MIXED:
            row["reliable_balance"] = False
            row["valuation"] = "estimated"
    return out


def undecomposed(core: ProjectionCore, currency: str | None = None) -> dict:
    """Money whose components are known but whose proportions are not — the
    ``MIXED`` bucket, filtered by `currency` if given.

    Reported as its own line rather than folded into spending: counting it
    all overstates spending and dropping it understates.

    Returns ``{total, count, accounts, corroborates}``, where
    ``corroborates`` names the documents that would resolve the split."""
    total, count = Decimal("0"), 0
    accounts: set[str] = set()
    docs: set[str] = set()
    for m in movements_view.movements(core):
        if m.nature != movements_view.MIXED or not movements_view.is_expense(m):
            continue
        if currency is not None and m.currency != currency:
            continue
        total += abs(m.amount)
        count += 1
        if m.ruling_account:
            accounts.add(m.ruling_account)
        ruling = (core._rulings.get((SCOPE_MOVEMENT, m.key))
                  or merchants_view.merchant_ruling(core, m))
        if ruling and ruling.get("corroborates"):
            docs.add(ruling["corroborates"])
    return {"total": total, "count": count,
            "accounts": sorted(accounts), "corroborates": sorted(docs)}
