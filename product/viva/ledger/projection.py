"""The running-balance projection — a view rebuilt by replaying the event log.

The projection layer owns no truth; it re-derives it (data-model-considerations.md).
Feed it the events, ask for a balance, and it returns not just a number but the
number's *grade* and *provenance* — because a finance answer without a cited
source and a confidence signal is exactly what this project refuses to ship
(principle 2).

The v0 grade ladder, constructed deterministically (never model-reported):

  - **corroborated** — the issuer's closing figure is attested AND the opening
    balance plus the period's transactions reconcile to it. Two independent
    routes to the same number agree. The strongest thing v0 can say.
  - **verified**     — a closing figure is attested but there are no transactions
    to reconcile it against (a lone snapshot, trusted because the issuer wrote
    it).
  - **conflicted**   — a closing figure is attested but the transactions do NOT
    reconcile to it. Surfaced loudly, never averaged or hidden.
  - **unverified**   — no attested closing figure; the balance is only the
    replayed sum of opening + transactions, with nothing to check it against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from vivacore.verify.arithmetic import CheckResult, check_balance_identity

from .events import (CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED, Event,
                     Posting, Provenance, postings_of)
from .postings import EQUITY_OPENING


class UnknownAccountError(KeyError):
    """Asked for a balance on an account the ledger has never seen. The honest
    answer is 'I don't have that', not a fabricated zero — the answer path turns
    this into a refusal."""


@dataclass
class BalanceAnswer:
    account: str
    amount: Decimal
    grade: str
    as_of: str | None
    provenance: Provenance
    reconciliation: CheckResult | None
    explanation: str

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "amount": str(self.amount),
            "grade": self.grade,
            "as_of": self.as_of,
            "provenance": self.provenance.to_dict(),
            "reconciliation": (self.reconciliation.explain()
                               if self.reconciliation else None),
            "explanation": self.explanation,
        }


@dataclass
class _AccountState:
    balance: Decimal = Decimal("0")            # running sum of all postings
    opening: Decimal | None = None
    opening_prov: Provenance = field(default_factory=Provenance)
    closing: Decimal | None = None
    closing_prov: Provenance = field(default_factory=Provenance)
    period_deltas: list[Decimal] = field(default_factory=list)  # non-opening postings
    seen: bool = False


class LedgerProjection:
    """Replay events into per-account state, then answer balance queries."""

    def __init__(self, events: Iterable[Event], as_of: str | None = None) -> None:
        self.as_of = as_of
        self._acct: dict[str, _AccountState] = {}
        for event in events:
            if as_of is not None and event.occurred_at > as_of:
                continue     # ISO dates sort lexically; skip the future
            self._apply(event)

    def _state(self, account: str) -> _AccountState:
        return self._acct.setdefault(account, _AccountState())

    def _apply(self, event: Event) -> None:
        et = event.event_type
        if et == "AccountOpened":
            self._state(event.body["account_id"]).seen = True

        elif et == "OpeningBalanceObserved":
            acct = event.body["account_id"]
            amount = Decimal(event.body["amount"])
            st = self._state(acct)
            st.seen = True
            st.opening = amount
            st.opening_prov = event.provenance
            # Seed the Opening Balance Equity pair: the account gets the money,
            # equity holds the mirror ("unexplained history"). Only the account
            # leg moves this account's balance.
            st.balance += amount
            self._state(EQUITY_OPENING).balance += -amount

        elif et == "ClosingBalanceObserved":
            acct = event.body["account_id"]
            st = self._state(acct)
            st.seen = True
            st.closing = Decimal(event.body["amount"])
            st.closing_prov = event.provenance

        elif et == "TransactionRecorded":
            for p in postings_of(event):
                st = self._state(p.account)
                st.seen = True
                st.balance += p.amount
                # Period deltas exclude the opening seed (that's tracked apart),
                # so reconciliation is opening + period == closing.
                if p.account != EQUITY_OPENING:
                    st.period_deltas.append(p.amount)

    # --------------------------------------------------------------- queries

    def accounts(self) -> list[str]:
        return sorted(a for a, s in self._acct.items() if s.seen)

    def balance(self, account: str) -> BalanceAnswer:
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)

        # No attested closing: the balance is a bare replayed sum.
        if st.closing is None:
            return BalanceAnswer(
                account=account, amount=st.balance, grade=UNVERIFIED,
                as_of=self.as_of, provenance=st.opening_prov, reconciliation=None,
                explanation=("Computed by replaying opening balance and "
                             "transactions; no closing figure was attested to "
                             "check it against."),
            )

        # Closing attested but no opening to reconcile from: a lone snapshot.
        if st.opening is None:
            return BalanceAnswer(
                account=account, amount=st.closing, grade=VERIFIED,
                as_of=self.as_of, provenance=st.closing_prov, reconciliation=None,
                explanation=("Attested closing balance; no opening figure or "
                             "transactions to corroborate it against."),
            )

        # Closing + opening + transactions: reconcile the two routes.
        recon = check_balance_identity(st.opening, st.period_deltas, st.closing)
        if recon.passed:
            return BalanceAnswer(
                account=account, amount=st.closing, grade=CORROBORATED,
                as_of=self.as_of, provenance=st.closing_prov, reconciliation=recon,
                explanation=("Attested closing balance, corroborated: opening "
                             "plus the period's transactions reconcile to it "
                             "to the cent."),
            )
        return BalanceAnswer(
            account=account, amount=st.closing, grade=CONFLICTED,
            as_of=self.as_of, provenance=st.closing_prov, reconciliation=recon,
            explanation=("The attested closing balance and the transactions "
                         f"disagree: {recon.explain()}. Surfaced, not averaged."),
        )
