"""The ledger: encrypted append-only events, double-entry postings, projections.

Events are the source of truth (ADR-004); balances are projections rebuilt by
replaying them. Everything is encrypted at rest (ADR-005) and every answer
carries a grade and provenance.
"""

from ..crypto import CryptoError
from .events import (CONFLICTED, CORROBORATED, GRADES, UNVERIFIED, VERIFIED,
                     Event, Posting, Provenance, account_opened,
                     closing_balance_observed, opening_balance_observed,
                     postings_of, transaction_recorded)
from .postings import (EQUITY_OPENING, EXPENSE_UNCATEGORIZED,
                       INCOME_UNCATEGORIZED, simple_transaction,
                       split_transaction, transaction_balances)
from .projection import (AccountInfo, BalanceAnswer, LedgerProjection,
                         UnknownAccountError)
from .store import EventStore

__all__ = [
    "CryptoError",
    "Event", "Posting", "Provenance",
    "VERIFIED", "CORROBORATED", "UNVERIFIED", "CONFLICTED", "GRADES",
    "account_opened", "opening_balance_observed", "closing_balance_observed",
    "transaction_recorded", "postings_of",
    "simple_transaction", "split_transaction", "transaction_balances",
    "EQUITY_OPENING", "INCOME_UNCATEGORIZED", "EXPENSE_UNCATEGORIZED",
    "EventStore",
    "LedgerProjection", "BalanceAnswer", "AccountInfo", "UnknownAccountError",
]
