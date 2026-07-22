"""Double-entry posting shapes for a checking statement.

Two mechanisms of categorization, kept apart on purpose (see
data-model-considerations.md, "Categorization is two mechanisms"):

  1. **Split by amount** → double-entry. One movement whose counter-side is
     several postings that sum to the whole. ``split_transaction`` builds it;
     the postings still balance to zero.
  2. **Overlapping labels** → the ``tags`` overlay on the transaction, a
     many-to-many descriptive layer that never has to balance.

v0 seeds neither category nor tags (categorization is deferred), so a movement's
counter-leg goes to an Uncategorized bucket graded ``unverified``: the amount is
attested, the classification is not. The structure is already the real one, so
increment 2 only has to raise that leg's grade and fill its account/tags — no
rewrite.

Sign convention: an ``amount`` is the signed change to the named account.
Positive means money into the account (a deposit into checking); negative means
money out (a withdrawal). Every transaction's postings sum to exactly zero.
"""

from __future__ import annotations

from decimal import Decimal

from vivacore.verify.arithmetic import CheckResult, check_sum

from .events import (UNVERIFIED, VERIFIED, Event, Posting,
                     transaction_recorded)

# --- the v0 chart of accounts (a tiny fixed set; a registry grows it later) ---

EQUITY_OPENING = "Equity:OpeningBalance"      # the "unexplained history" bucket
INCOME_UNCATEGORIZED = "Income:Uncategorized"
EXPENSE_UNCATEGORIZED = "Expenses:Uncategorized"


def transaction_balances(postings: list[Posting],
                         tolerance: Decimal | str = "0") -> CheckResult:
    """The double-entry law: a transaction's postings sum to exactly zero.

    Reuses the shared deterministic arithmetic (exact Decimal, no float, no
    silent tolerance) — the same check that reconciles a statement reconciles a
    transaction."""
    return check_sum(
        [p.amount for p in postings], Decimal("0"),
        label="transaction postings sum to zero", tolerance=tolerance,
    )


def _require_balanced(postings: list[Posting]) -> list[Posting]:
    result = transaction_balances(postings)
    if not result.passed:
        raise ValueError(
            f"postings do not balance: {result.explain()} — a transaction whose "
            "legs don't sum to zero is not double-entry"
        )
    return postings


def simple_transaction(account: str, amount: Decimal | str, description: str,
                       occurred_at: str, tags: list[str] | None = None,
                       provenance=None) -> Event:
    """A single-category movement on ``account``.

    ``amount`` > 0 is money in (deposit), < 0 is money out (withdrawal). The
    named account's leg is ``verified`` (the statement attests the movement); the
    Uncategorized counter-leg mirrors the amount but is ``unverified`` — its
    category is not yet inferred."""
    amt = Decimal(amount)
    if amt == 0:
        raise ValueError("a transaction of zero is not a movement")
    counter = INCOME_UNCATEGORIZED if amt > 0 else EXPENSE_UNCATEGORIZED
    postings = _require_balanced([
        Posting(account, amt, VERIFIED),
        Posting(counter, -amt, UNVERIFIED),
    ])
    return transaction_recorded(postings, description, occurred_at, tags, provenance)


def split_transaction(account: str, amount: Decimal | str,
                      splits: list[tuple[str, Decimal | str]], description: str,
                      occurred_at: str, tags: list[str] | None = None,
                      provenance=None) -> Event:
    """One movement split across categories by amount (mechanism 1).

    ``amount`` is the signed change to ``account`` (negative for money out).
    ``splits`` are (category_account, magnitude) pairs whose magnitudes sum to
    ``abs(amount)`` — they are the counter-legs, signed opposite to the account
    leg. The account leg is ``verified``; each split leg is ``verified`` for its
    amount but the classification is the user's, so we grade it ``corroborated``
    only once confirmed — here, at construction from a statement, they inherit
    ``unverified`` until categorization confirms them."""
    amt = Decimal(amount)
    if amt == 0:
        raise ValueError("a transaction of zero is not a movement")
    sign = Decimal(-1) if amt > 0 else Decimal(1)   # counter-legs oppose the account leg
    legs = [Posting(account, amt, VERIFIED)]
    total = Decimal("0")
    for cat, mag in splits:
        m = Decimal(mag)
        if m <= 0:
            raise ValueError(f"split magnitude for {cat!r} must be positive, got {m}")
        total += m
        legs.append(Posting(cat, sign * m, UNVERIFIED))
    if total != abs(amt):
        raise ValueError(
            f"split magnitudes sum to {total}, but the movement is {abs(amt)} — "
            "a split must account for the whole amount"
        )
    return transaction_recorded(_require_balanced(legs), description,
                                occurred_at, tags, provenance)
