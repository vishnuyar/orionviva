"""Double-entry posting shapes for a checking statement.

Two mechanisms of categorization, kept apart:

  1. **Split by amount** → double-entry. One movement whose counter-side is
     several postings that sum to the whole. ``split_transaction`` builds it;
     the postings still balance to zero.
  2. **Overlapping labels** → the ``tags`` overlay on the transaction, a
     many-to-many descriptive layer that never has to balance.

A movement's counter-leg goes to an Uncategorized bucket graded ``unverified``:
the amount is attested, the classification is not. Categorization raises that
leg's grade and fills its account and tags; the structure does not change.

Sign convention: an ``amount`` is the signed change to the named account.
Positive means money into the account (a deposit into checking); negative means
money out (a withdrawal). Every transaction's postings sum to exactly zero.
"""

from __future__ import annotations

from decimal import Decimal

from vivacore.verify.arithmetic import CheckResult, check_sum

from .events import (MAJOR_ASSET, MAJOR_EXPENSE, MAJOR_INCOME, MAJOR_LIABILITY,
                     UNVERIFIED, VERIFIED, Event, Posting, transaction_recorded)

# --- the chart of accounts (a tiny fixed set; a registry grows it later) -----

EQUITY_OPENING = "Equity:OpeningBalance"      # the "unexplained history" bucket
INCOME_UNCATEGORIZED = "Income:Uncategorized"
EXPENSE_UNCATEGORIZED = "Expenses:Uncategorized"
# A liability's payment reduces what's owed — a debt reduction funded by a
# transfer, not an expense. It lands here so it never inflates spending.
TRANSFERS_UNCATEGORIZED = "Transfers:Uncategorized"

# --- the four majors, as account roots --------------------------------------
# A category is an overlay keyed on movement_key, so these roots are a read-side
# concern: the posted counter-leg stays an Uncategorized bucket, the projection
# materializes the chart of accounts from rulings, and a path such as
# `Assets:Vehicles:Roadster` is never written into a posting.
LIABILITIES_UNCATEGORIZED = "Liabilities:Uncategorized"

MAJOR_ROOTS = {
    MAJOR_EXPENSE: "Expenses",
    MAJOR_ASSET: "Assets",
    MAJOR_LIABILITY: "Liabilities",
    MAJOR_INCOME: "Income",
}
MAJOR_UNCATEGORIZED = {
    MAJOR_EXPENSE: EXPENSE_UNCATEGORIZED,
    MAJOR_ASSET: "Assets:Uncategorized",
    MAJOR_LIABILITY: LIABILITIES_UNCATEGORIZED,
    MAJOR_INCOME: INCOME_UNCATEGORIZED,
}


def account_path(major: str, *parts: str) -> str:
    """Build a chart-of-accounts path: the major's root is fixed code and every
    level beneath it is free data — `Assets:Vehicles:<name>`,
    `Liabilities:Mortgage:<lender>`.

    Empty parts are dropped, and a `:` inside a part is collapsed to a space so
    a name can never inject a level into the hierarchy. Raises ValueError on a
    major outside ``MAJOR_ROOTS``."""
    if major not in MAJOR_ROOTS:
        raise ValueError(f"unknown major {major!r}")
    clean = [p.strip().replace(":", " ").strip() for p in parts]
    return ":".join([MAJOR_ROOTS[major]] + [p for p in clean if p])


def counter_account(kind: str, amount: Decimal) -> str:
    """The Uncategorized counter-leg for a movement, chosen by account kind and
    direction. Asset and liability signs are opposite: money out of an asset and
    a charge on a liability are both expenses, money into an asset is income,
    and a payment on a liability is a transfer — a debt reduction, not income."""
    if kind == "liability":
        return EXPENSE_UNCATEGORIZED if amount > 0 else TRANSFERS_UNCATEGORIZED
    return INCOME_UNCATEGORIZED if amount > 0 else EXPENSE_UNCATEGORIZED

# Pay-stub decomposition targets. Universal buckets — jurisdiction is an
# attribute rather than a per-country table, so a US 401k and an Indian EPF both
# land in Assets:Retirement. Retirement is an asset, not spending; tax and
# insurance are expenses.
INCOME_SALARY = "Income:Salary"
DEDUCTION_ACCOUNTS = {
    "tax": "Expenses:Tax",
    "retirement": "Assets:Retirement",
    "insurance": "Expenses:Insurance",
    "other": "Expenses:Other",
}

# Brokerage cash-activity targets, one counter-leg per reason the investment
# account's cash moved: dividends/interest/capital gains feed income; a fee is
# an expense; a buy or sell moves cash to or from Assets:Investments, an
# internal reallocation that is neither spending nor income; a contribution or
# withdrawal is a transfer tying to the funding account.
INCOME_DIVIDENDS = "Income:Dividends"
INCOME_INTEREST = "Income:Interest"
INCOME_CAPITAL_GAINS = "Income:CapitalGains"   # REALIZED gain on a sell (a tax event)
EXPENSE_FEES = "Expenses:Fees"
ASSET_INVESTMENTS = "Assets:Investments"       # invested capital at cost (buys − sold basis)

# Signed cash effect of each activity kind (+ money into the account's cash).
BROKERAGE_CASH_IN = frozenset({"contribution", "dividend", "interest", "sell"})
BROKERAGE_CASH_OUT = frozenset({"withdrawal", "fee", "buy"})
BROKERAGE_ACTIVITY_KINDS = BROKERAGE_CASH_IN | BROKERAGE_CASH_OUT


def brokerage_cash_effect(kind: str, amount: Decimal | str) -> Decimal:
    """The signed effect of one activity on the account's cash (+ in, − out)."""
    amt = Decimal(amount)
    if kind in BROKERAGE_CASH_IN:
        return amt
    if kind in BROKERAGE_CASH_OUT:
        return -amt
    raise ValueError(f"unknown brokerage activity kind {kind!r}")


def brokerage_activity_transaction(account: str, kind: str, amount: Decimal | str,
                                   description: str, occurred_at: str,
                                   instrument: str = "",
                                   realized_gain: Decimal | str | None = None,
                                   provenance=None) -> Event:
    """One brokerage cash movement, posted with the counter-leg its reason
    dictates.

    ``amount`` is a positive magnitude; the cash leg's sign comes from ``kind``.
    A contribution or withdrawal balances against Transfers, a dividend or
    interest against Income, a fee against Expenses, and a buy or sell against
    Assets:Investments. A sell's ``realized_gain``, when the statement reports
    it, is split off to Income:CapitalGains (proceeds = basis + gain).

    Only realized cash events post; an unrealized paper change never does.
    Raises ValueError on a non-positive amount or an unknown kind."""
    amt = Decimal(amount)
    if amt <= 0:
        raise ValueError("a brokerage activity amount must be a positive magnitude")
    cash = brokerage_cash_effect(kind, amt)      # signed cash leg
    if kind in ("contribution", "withdrawal"):
        counter = [Posting(TRANSFERS_UNCATEGORIZED, -cash, UNVERIFIED)]
    elif kind == "dividend":
        counter = [Posting(INCOME_DIVIDENDS, -cash, VERIFIED)]
    elif kind == "interest":
        counter = [Posting(INCOME_INTEREST, -cash, VERIFIED)]
    elif kind == "fee":
        counter = [Posting(EXPENSE_FEES, -cash, VERIFIED)]
    elif kind == "buy":
        counter = [Posting(ASSET_INVESTMENTS, -cash, VERIFIED)]
    elif kind == "sell":
        gain = (Decimal(realized_gain)
                if realized_gain not in (None, "") else None)
        if gain is None:                          # pure conversion; gain unknown
            counter = [Posting(ASSET_INVESTMENTS, -cash, VERIFIED)]
        else:                                     # proceeds = basis + realized gain
            basis = cash - gain                   # cash is +proceeds here
            counter = [Posting(ASSET_INVESTMENTS, -basis, VERIFIED),
                       Posting(INCOME_CAPITAL_GAINS, -gain, VERIFIED)]
    else:
        raise ValueError(f"unknown brokerage activity kind {kind!r}")
    label = description or (f"{kind} {instrument}".strip())
    legs = _require_balanced([Posting(account, cash, VERIFIED), *counter])
    return transaction_recorded(legs, label, occurred_at, None, provenance)


def paystub_decomposition(gross: Decimal | str, net: Decimal | str,
                          deductions: list, description: str, occurred_at: str,
                          provenance=None) -> Event:
    """Decompose a net-pay deposit into what the bank could not see.

    The pay stub explains a checking deposit already booked as uncategorized
    income. This posts gross as salary income; each deduction into its universal
    bucket, graded ``unverified`` until confirmed; and a reversal of the
    deposit's ``Income:Uncategorized`` placeholder for the net, so the net is
    counted once. The legs sum to zero: −gross + net + Σdeductions = 0, since
    gross − Σdeductions = net.

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

    Runs on the shared deterministic arithmetic (exact Decimal, no float, no
    silent tolerance) — the same check that reconciles a statement."""
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
    account's leg is ``verified`` by default; the Uncategorized counter-leg
    mirrors the amount but is ``unverified``, its category not yet inferred.
    ``kind`` picks the counter-leg: a card purchase is an expense, a card
    payment a transfer, never income. A leg supplied by cross-document
    corroboration passes ``account_grade=CORROBORATED``.

    Raises ValueError on a zero amount."""
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
    ``abs(amount)``; they are the counter-legs, signed opposite to the account
    leg. The account leg is ``verified`` and each split leg is ``unverified``
    until categorization confirms its classification.

    Raises ValueError on a zero amount, a non-positive split magnitude, or
    magnitudes that do not sum to the whole movement."""
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
