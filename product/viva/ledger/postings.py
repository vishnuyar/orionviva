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
# A liability's payment reduces what's owed — a debt reduction funded by a
# transfer, NOT an expense. It lands here so it never inflates spending (Slice 5).
TRANSFERS_UNCATEGORIZED = "Transfers:Uncategorized"


def counter_account(kind: str, amount: Decimal) -> str:
    """The Uncategorized counter-leg for a movement, by (account kind, direction)
    — the kind-aware fix (Slice 5). Asset signs and liability signs are opposite:
    money out of an asset and a charge on a liability are both *expenses*; money
    into an asset is *income*; a payment on a liability is a *transfer* (debt
    reduction), not income. Getting this right is what makes spending honest."""
    if kind == "liability":
        return EXPENSE_UNCATEGORIZED if amount > 0 else TRANSFERS_UNCATEGORIZED
    return INCOME_UNCATEGORIZED if amount > 0 else EXPENSE_UNCATEGORIZED

# Pay-stub decomposition targets (Slice 4). Universal buckets — jurisdiction is an
# attribute, never a per-country table (I5): a US 401k and an Indian EPF both land
# in Assets:Retirement. Retirement is an ASSET (money moved to your retirement),
# not spending; tax and insurance are expenses.
INCOME_SALARY = "Income:Salary"
DEDUCTION_ACCOUNTS = {
    "tax": "Expenses:Tax",
    "retirement": "Assets:Retirement",
    "insurance": "Expenses:Insurance",
    "other": "Expenses:Other",
}


def paystub_decomposition(gross: Decimal | str, net: Decimal | str,
                          deductions: list, description: str, occurred_at: str,
                          provenance=None) -> Event:
    """Decompose a net-pay deposit into what the bank couldn't see (Slice 4).

    The pay stub *explains* a checking deposit already booked as uncategorized
    income. This posts: gross recognized as salary income; each deduction into its
    universal bucket (graded ``unverified`` — the category is the model's proposal
    until confirmed, X2); and a reversal of the deposit's ``Income:Uncategorized``
    placeholder for the net, so the net is counted ONCE (the checking inflow stays;
    its placeholder income is replaced by the real gross-and-deductions picture).
    The legs sum to zero: −gross + net + Σdeductions = 0, since gross − Σ = net.

    ``deductions`` is a list of objects with ``.amount`` and ``.category``.
    """
    gross_d, net_d = Decimal(gross), Decimal(net)
    postings = [
        Posting(INCOME_SALARY, -gross_d, VERIFIED),          # the employer attests gross
        Posting(INCOME_UNCATEGORIZED, net_d, UNVERIFIED),    # cancel the deposit's placeholder
    ]
    for d in deductions:
        acct = DEDUCTION_ACCOUNTS.get(getattr(d, "category", "other"),
                                      DEDUCTION_ACCOUNTS["other"])
        postings.append(Posting(acct, abs(Decimal(d.amount)), UNVERIFIED))
    return transaction_recorded(_require_balanced(postings), description,
                                occurred_at, None, provenance)


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
                       provenance=None, account_grade: str = VERIFIED,
                       kind: str = "depository") -> Event:
    """A single-category movement on ``account``.

    ``amount`` is the signed effect on the account's printed balance. The named
    account's leg is ``verified`` by default (the statement attests the
    movement); the Uncategorized counter-leg mirrors the amount but is
    ``unverified`` — its category is not yet inferred. ``kind`` picks the correct
    counter-leg (Slice 5): a card purchase is an expense, a card payment a
    transfer, never income. A leg *supplied by cross-document corroboration*
    (Slice 3) passes ``account_grade=CORROBORATED``."""
    amt = Decimal(amount)
    if amt == 0:
        raise ValueError("a transaction of zero is not a movement")
    counter = counter_account(kind, amt)
    postings = _require_balanced([
        Posting(account, amt, account_grade),
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
