"""Balances with their grade and provenance, and the income aggregate.

The grade ladder, constructed deterministically (never model-reported):

  - **corroborated** — the issuer's closing figure is attested AND the opening
    balance plus the period's transactions reconcile to it: two independent
    routes to the same number.
  - **verified**     — a closing figure is attested but there are no
    transactions to reconcile it against (a lone snapshot), or a person
    confirmed the figure.
  - **conflicted**   — a closing figure is attested but the transactions do not
    reconcile to it. Reported, never averaged or hidden.
  - **unverified**   — no attested closing figure; the balance is only the
    replayed sum of opening + transactions, with nothing to check it against.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from vivacore.verify.arithmetic import CheckResult, check_balance_identity

from ..events import CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED, Provenance
from ..postings import INCOME_UNCATEGORIZED
from .core import ProjectionCore, UnknownAccountError, _AccountState


@dataclass
class BalanceAnswer:
    account: str
    amount: Decimal
    grade: str
    as_of: str | None
    provenance: Provenance
    reconciliation: CheckResult | None
    explanation: str
    currency: str = ""
    dated: str = ""            # the value-time date this balance is as of

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "amount": str(self.amount),
            "currency": self.currency,
            "grade": self.grade,
            "as_of": self.as_of,
            "dated": self.dated,
            "provenance": self.provenance.to_dict(),
            "reconciliation": (self.reconciliation.explain()
                               if self.reconciliation else None),
            "explanation": self.explanation,
        }


def effective(st: _AccountState) -> Decimal:
    """Account balance = earliest opening (the OBE injection) + transaction
    postings. The opening is injected here, once, rather than accumulated
    per opening event."""
    return (st.opening or Decimal("0")) + st.balance


def running_balance(core: ProjectionCore, account: str) -> Decimal | None:
    """The replayed balance, or None if the account is unseen. Used by ingest
    to check that a new statement's opening continues from where we left off."""
    st = core._acct.get(account)
    return effective(st) if (st and st.seen) else None


def earliest_opening(core: ProjectionCore, account: str) -> Decimal | None:
    """The account's earliest known opening, or None if unseen — the balance
    a still-older statement must *close* at to backfill in front of the
    chain."""
    st = core._acct.get(account)
    return st.opening if st else None


def is_seeded(core: ProjectionCore, account: str) -> bool:
    """True once an opening balance has been booked: the account's history
    has a starting point, and later statements continue from it rather than
    re-seeding it."""
    st = core._acct.get(account)
    return bool(st and st.opening is not None)


def balance(core: ProjectionCore, account: str) -> BalanceAnswer:
    st = core._acct.get(account)
    if st is None or not st.seen:
        raise UnknownAccountError(account)

    # No attested closing: the balance is a bare replayed sum.
    if st.closing is None:
        ans = BalanceAnswer(
            account=account, amount=effective(st), grade=UNVERIFIED,
            as_of=core.as_of, provenance=st.opening_prov, reconciliation=None,
            explanation=("Computed by replaying opening balance and "
                         "transactions; no closing figure was attested to "
                         "check it against."))
    # Closing attested but no opening to reconcile from: a lone snapshot.
    elif st.opening is None:
        ans = BalanceAnswer(
            account=account, amount=st.closing, grade=VERIFIED,
            as_of=core.as_of, provenance=st.closing_prov, reconciliation=None,
            explanation=("Attested closing balance; no opening figure or "
                         "transactions to corroborate it against."))
    else:
        # Closing + opening + transactions: reconcile the two routes.
        recon = check_balance_identity(st.opening, st.period_deltas, st.closing)
        if recon.passed:
            # A person who confirmed the figure is the highest attestation.
            grade = VERIFIED if st.closing_confirmed else CORROBORATED
            note = ("confirmed by you and reconciled"
                    if st.closing_confirmed
                    else "opening plus the period's transactions reconcile "
                         "to it to the cent")
            ans = BalanceAnswer(
                account=account, amount=st.closing, grade=grade,
                as_of=core.as_of, provenance=st.closing_prov,
                reconciliation=recon,
                explanation=f"Attested closing balance, {note}.")
        else:
            ans = BalanceAnswer(
                account=account, amount=st.closing, grade=CONFLICTED,
                as_of=core.as_of, provenance=st.closing_prov,
                reconciliation=recon,
                explanation=("The attested closing balance and the "
                             f"transactions disagree: {recon.explain()}. "
                             "Surfaced, not averaged."))
    ans.currency = st.currency
    ans.dated = st.closing_date or st.opening_date
    return ans


def income_by_currency(core: ProjectionCore) -> dict[str, Decimal]:
    """Attributed income per currency: the sum of `Income:*` accounts as a
    positive magnitude, **excluding the `Income:Uncategorized` placeholder**.

    `Income:Uncategorized` is the undifferentiated inflow bucket and is
    excluded, so an inflow nothing has attributed is not reported as income.

    Income buckets carry no currency of their own: with exactly one account
    currency, income is attributed to it, otherwise to '?'."""
    held = {s.currency for a, s in core._acct.items()
            if s.seen and s.kind in ("depository", "liability", "investment")
            and s.currency}
    default = next(iter(held)) if len(held) == 1 else "?"
    out: dict[str, Decimal] = {}
    for account, st in core._acct.items():
        if (not st.seen or not account.startswith("Income:")
                or account == INCOME_UNCATEGORIZED):
            continue
        amt = -effective(st)          # credits are negative; report positive
        if amt != 0:
            cur = st.currency or default
            out[cur] = out.get(cur, Decimal("0")) + amt
    return out
