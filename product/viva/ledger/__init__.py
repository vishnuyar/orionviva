"""The ledger: encrypted append-only events, double-entry postings, projections.

Events are the source of truth (ADR-004); balances are projections rebuilt by
replaying them. Everything is encrypted at rest (ADR-005) and every answer
carries a grade and provenance.
"""

from ..crypto import CryptoError
from .events import (CONFLICTED, CORROBORATED, GRADES, UNVERIFIED, VERIFIED,
                     Event, Posting, Provenance, account_opened,
                     category_assigned, closing_balance_observed,
                     correction_applied, document_captured,
                     opening_balance_observed, postings_of, read_recorded,
                     statement_held, transaction_recorded, transfer_linked,
                     transfer_suggested, transfer_unlinked)
from .postings import (EQUITY_OPENING, EXPENSE_UNCATEGORIZED,
                       INCOME_UNCATEGORIZED, TRANSFERS_UNCATEGORIZED,
                       counter_account, simple_transaction, split_transaction,
                       transaction_balances)
from .ledger import Ledger
from .projection import (AccountInfo, BalanceAnswer, LedgerProjection,
                         MovementInfo, TxnLine, UnknownAccountError,
                         movement_key)
from .store import EventStore

__all__ = [
    "CryptoError",
    "Event", "Posting", "Provenance",
    "VERIFIED", "CORROBORATED", "UNVERIFIED", "CONFLICTED", "GRADES",
    "account_opened", "opening_balance_observed", "closing_balance_observed",
    "transaction_recorded", "postings_of", "document_captured",
    "statement_held", "correction_applied", "read_recorded",
    "transfer_linked", "transfer_unlinked", "transfer_suggested",
    "category_assigned",
    "simple_transaction", "split_transaction", "transaction_balances",
    "counter_account",
    "EQUITY_OPENING", "INCOME_UNCATEGORIZED", "EXPENSE_UNCATEGORIZED",
    "TRANSFERS_UNCATEGORIZED",
    "EventStore", "Ledger",
    "LedgerProjection", "BalanceAnswer", "AccountInfo", "TxnLine",
    "MovementInfo", "movement_key", "UnknownAccountError",
]
