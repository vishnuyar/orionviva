"""The ledger: encrypted append-only events, double-entry postings, projections.

Events are the source of truth; balances are projections rebuilt by
replaying them. Everything is encrypted at rest and every answer carries a
grade and provenance.
"""

from ..crypto import CryptoError
from .events import (ACT_OUTCOMES, AGENT_ACTED, CONFLICTED, CORROBORATED,
                     GRADES, UNVERIFIED, VERIFIED,
                     Event, Posting, Provenance, account_identity_observed,
                     account_opened, agent_acted,
                     category_assigned, closing_balance_observed,
                     correction_applied, document_captured, merchant_categorized,
                     opening_balance_observed, postings_of, read_recorded,
                     statement_held, transaction_recorded, transfer_linked,
                     transfer_suggested, transfer_unlinked,
                     goal_created, goal_terms_changed, goal_funds_reserved,
                     goal_funds_released, goal_state_changed,
                     goal_proposal_recorded, goal_proposal_resolved)
from .merchants import (NORMALIZER_VERSION, is_shareable, normalize_merchant)
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
    "account_opened", "account_identity_observed",
    "opening_balance_observed", "closing_balance_observed",
    "transaction_recorded", "postings_of", "document_captured",
    "statement_held", "correction_applied", "read_recorded",
    "transfer_linked", "transfer_unlinked", "transfer_suggested",
    "category_assigned", "merchant_categorized",
    "goal_created", "goal_terms_changed", "goal_funds_reserved",
    "goal_funds_released", "goal_state_changed",
    "goal_proposal_recorded", "goal_proposal_resolved",
    "agent_acted", "AGENT_ACTED", "ACT_OUTCOMES",
    "normalize_merchant", "is_shareable", "NORMALIZER_VERSION",
    "simple_transaction", "split_transaction", "transaction_balances",
    "counter_account",
    "EQUITY_OPENING", "INCOME_UNCATEGORIZED", "EXPENSE_UNCATEGORIZED",
    "TRANSFERS_UNCATEGORIZED",
    "EventStore", "Ledger",
    "LedgerProjection", "BalanceAnswer", "AccountInfo", "TxnLine",
    "MovementInfo", "movement_key", "UnknownAccountError",
]
