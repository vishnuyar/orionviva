"""The running-balance projection — a view rebuilt by replaying the event log.

The projection layer owns no truth; it re-derives it. Feed it the events, ask
for a balance, and it returns the number together with that number's *grade* and
*provenance*.

One package, one core, several read families: `core` folds events into shared
state, and each sibling module answers one family of questions over it —
balances, accounts, movements and transfers, merchants, categories and tags,
tiers, positions, ingest coverage, rulings, agent activity. `LedgerProjection`
is the facade that presents them as a single surface; callers that need only
one family may import its module directly.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from ..events import Event
from . import (accounts as _accounts, activity as _activity,
               balances as _balances, categories as _categories,
               coverage as _coverage, merchants as _merchants,
               movements as _movements, positions as _positions,
               rhythm as _rhythm, rulings as _rulings, tiers as _tiers)
from .accounts import AccountInfo, Resolution
from .balances import BalanceAnswer
from .core import ProjectionCore, TxnLine, UnknownAccountError
from .movements import (BY_CATEGORY, BY_DEFAULT, BY_LINK, BY_OWN_ACCOUNT,
                        BY_RULING, MIXED, SETTLEMENT, SPENDING, TRANSFER,
                        MovementInfo, _NATURE_OF_MAJOR, movement_key,
                        nature_of_legs)
from .positions import ComposedValue, PositionRecord
from .rhythm import RhythmComponent, RhythmHypothesis
from .tiers import (TIER_SETTLED, TIER_STRUCTURAL, TIER_UNENRICHED,
                    TIER_UNKNOWN)

__all__ = [
    "AccountInfo", "BalanceAnswer", "ComposedValue", "LedgerProjection",
    "MovementInfo", "PositionRecord", "ProjectionCore", "Resolution",
    "RhythmComponent", "RhythmHypothesis", "TxnLine",
    "UnknownAccountError", "movement_key", "nature_of_legs",
    "SPENDING", "TRANSFER", "SETTLEMENT", "MIXED",
    "BY_LINK", "BY_OWN_ACCOUNT", "BY_RULING", "BY_CATEGORY", "BY_DEFAULT",
    "TIER_SETTLED", "TIER_STRUCTURAL", "TIER_UNKNOWN", "TIER_UNENRICHED",
]


class LedgerProjection:
    """Replay events into per-account state, then answer balance queries.

    The read model for the whole ledger: per-account balances and ingest state
    (what is captured, posted, held). Built once and updated incrementally via
    ``apply``; the `Ledger` facade keeps one live instance so reads never
    re-replay the whole encrypted log.

    A facade over one `ProjectionCore` and this package's read modules: state
    and caches live on the core, so every family reads the same fold and a
    cache filled by one read serves the next.
    """

    def __init__(self, events: Iterable[Event], as_of: str | None = None,
                 resolve_keys=None) -> None:
        self._core = ProjectionCore(events, as_of, resolve_keys)

    @property
    def core(self) -> ProjectionCore:
        """The shared fold this facade reads. A caller needing one read family
        may pass this to that family's module directly instead of going
        through the facade."""
        return self._core

    @property
    def as_of(self) -> str | None:
        return self._core.as_of

    def apply(self, event: Event) -> None:
        """Fold one event into the projection (respecting an as_of horizon)."""
        self._core.apply(event)

    def _state(self, account: str):
        return self._core._state(account)

    # State the write paths and surfaces read directly; the objects are the
    # core's own, exactly as they were when the facade held them itself.
    @property
    def _posted(self) -> set:
        return self._core._posted

    @property
    def _merchant_tags(self) -> dict:
        return self._core._merchant_tags

    @property
    def _attribute_history(self) -> list:
        return self._core._attribute_history

    # --------------------------------------------------------------- accounts

    def accounts(self) -> list[str]:
        return _accounts.accounts(self._core)

    def seen_account(self, account: str) -> bool:
        return _accounts.seen_account(self._core, account)

    def account_info(self, account: str) -> AccountInfo:
        return _accounts.account_info(self._core, account)

    def account_infos(self) -> list[AccountInfo]:
        return _accounts.account_infos(self._core)

    def document_types_of(self, account: str) -> set:
        return _accounts.document_types_of(self._core, account)

    def resolve(self, institution: str, account_number: str, account_ref: str,
                names: list[str], kind: str = "depository") -> Resolution:
        return _accounts.resolve(self._core, institution, account_number,
                                 account_ref, names, kind)

    def _own_account_tokens(self) -> dict[str, set[str]]:
        return _accounts.own_account_tokens(self._core)

    # --------------------------------------------------------------- balances

    def is_seeded(self, account: str) -> bool:
        return _balances.is_seeded(self._core, account)

    def running_balance(self, account: str) -> Decimal | None:
        return _balances.running_balance(self._core, account)

    def earliest_opening(self, account: str) -> Decimal | None:
        return _balances.earliest_opening(self._core, account)

    def balance(self, account: str) -> BalanceAnswer:
        return _balances.balance(self._core, account)

    def income_by_currency(self) -> dict[str, Decimal]:
        return _balances.income_by_currency(self._core)

    # ------------------------------------------------------ ingest read-model

    def is_resolved(self, doc_id: str) -> bool:
        return _coverage.is_resolved(self._core, doc_id)

    def posted_period(self, account: str, period_end: str) -> tuple | None:
        return _coverage.posted_period(self._core, account, period_end)

    def is_pay_decomposed(self, description: str, pay_date: str,
                          gross: str) -> bool:
        return _coverage.is_pay_decomposed(self._core, description, pay_date,
                                           gross)

    def posted_doc_ids(self) -> set[str]:
        return _coverage.posted_doc_ids(self._core)

    def captured_docs(self) -> dict[str, str]:
        return _coverage.captured_docs(self._core)

    def captured_filenames(self) -> dict[str, str]:
        return _coverage.captured_filenames(self._core)

    def read_attempted_docs(self) -> set[str]:
        return _coverage.read_attempted_docs(self._core)

    def read_parsed_docs(self) -> set[str]:
        return _coverage.read_parsed_docs(self._core)

    def document_contributions(self) -> dict[str, dict]:
        return _coverage.document_contributions(self._core)

    def open_holds(self) -> list[dict]:
        return _coverage.open_holds(self._core)

    def statements(self, account: str):
        """What this account's statements declare, and where they join. None
        when no statement is held for it."""
        from ..statements import register
        return register(self._core).get(account)

    def attested_runs(self, account: str) -> list:
        """The periods this account's statements attest, in order. Empty when
        nothing is held: a period is never inferred from movements."""
        held = self.statements(account)
        return list(held.runs) if held else []

    def gap_holds(self) -> list[dict]:
        return _coverage.gap_holds(self._core)

    # ------------------------------------------------- movements and transfers

    def linked_keys(self) -> set[str]:
        return _movements.linked_keys(self._core)

    def is_linked(self, key: str) -> bool:
        return _movements.is_linked(self._core, key)

    def movements(self) -> list[MovementInfo]:
        return _movements.movements(self._core)

    def transactions(self, account: str) -> list[TxnLine]:
        return _movements.transactions(self._core, account)

    def transfer_suggestions(self) -> list[dict]:
        return _movements.transfer_suggestions(self._core)

    def transfer_links(self) -> list[dict]:
        return _movements.transfer_links(self._core)

    def spending_by_currency(self) -> dict[str, Decimal]:
        return _movements.spending_by_currency(self._core)

    def provisional_spending(self, currency: str | None = None) -> Decimal:
        return _movements.provisional_spending(self._core, currency)

    def excluded_from_spending(self) -> list[MovementInfo]:
        return _movements.excluded_from_spending(self._core)

    @staticmethod
    def _is_expense(m: MovementInfo) -> bool:
        return _movements.is_expense(m)

    def _counts_as_spending(self, m: MovementInfo) -> bool:
        return _movements.counts_as_spending(m)

    def _decide_nature(self, m: MovementInfo) -> None:
        _movements.decide_nature(self._core, m)

    # -------------------------------------------------------------- merchants

    def merchant_keys_of(self, m: MovementInfo) -> tuple:
        return _merchants.merchant_keys_of(self._core, m)

    def merchant_key_of(self, m: MovementInfo) -> str:
        return _merchants.merchant_key_of(self._core, m)

    def merchant_categories(self) -> dict[str, dict]:
        return _merchants.merchant_categories(self._core)

    def implication_for(self, merchant: str, inflow: bool = False) -> dict | None:
        return _merchants.implication_for(self._core, merchant, inflow)

    def implication_of(self, m: MovementInfo) -> dict | None:
        return _merchants.implication_of(self._core, m)

    def counterparty_kind(self, m: MovementInfo) -> str:
        return _merchants.counterparty_kind(self._core, m)

    def kind_of_merchant(self, merchant: str) -> str:
        return _merchants.kind_of_merchant(self._core, merchant)

    def _merchant_record(self, m: MovementInfo) -> dict | None:
        return _merchants.merchant_record(self._core, m)

    def _merchant_ruling(self, m: MovementInfo) -> dict | None:
        return _merchants.merchant_ruling(self._core, m)

    # ----------------------------------------------------- categories and tags

    def derived_category(self, m: MovementInfo) -> dict | None:
        return _categories.derived_category(self._core, m)

    def category_of(self, key: str) -> dict | None:
        return _categories.category_of(self._core, key)

    def category_aliases(self) -> dict[str, str]:
        return _categories.category_aliases(self._core)

    def canonical_category(self, label: str) -> str:
        return _categories.canonical_category(self._core, label)

    def known_categories(self) -> list[str]:
        return _categories.known_categories(self._core)

    def known_subcategories(self) -> list[str]:
        return _categories.known_subcategories(self._core)

    def known_subcategory_pairs(self) -> list[str]:
        return _categories.known_subcategory_pairs(self._core)

    def subcategory_spelling(self, m: MovementInfo) -> tuple[str, str]:
        return _categories.subcategory_spelling(self._core, m)

    def subcategory_merges(self) -> dict[str, list[str]]:
        return _categories.subcategory_merges(self._core)

    def spending_by_category(self, currency: str | None = None) -> dict[str, Decimal]:
        return _categories.spending_by_category(self._core, currency)

    def spending_by_subcategory(self, currency: str | None = None) -> dict[str, Decimal]:
        return _categories.spending_by_subcategory(self._core, currency)

    def spending_by_category_then_subcategory(
            self, currency: str | None = None) -> dict[str, dict[str, Decimal]]:
        return _categories.spending_by_category_then_subcategory(
            self._core, currency)

    def uncategorized_expenses(self) -> list[MovementInfo]:
        return _categories.uncategorized_expenses(self._core)

    def uncategorized_merchants(self, expenses_only: bool = False) -> dict[str, dict]:
        return _categories.uncategorized_merchants(self._core, expenses_only)

    def tags_of(self, m: MovementInfo) -> list[str]:
        return _categories.tags_of(self._core, m)

    def movement_tags_of(self, m: MovementInfo) -> list[str]:
        return _categories.movement_tags_of(self._core, m)

    def inherited_tags_of(self, m: MovementInfo) -> list[str]:
        return _categories.inherited_tags_of(self._core, m)

    def tag_aliases(self) -> dict[str, str]:
        return _categories.tag_aliases(self._core)

    def canonical_tag(self, label: str) -> str:
        return _categories.canonical_tag(self._core, label)

    def known_tags(self) -> list[str]:
        return _categories.known_tags(self._core)

    def spending_by_tag(self, currency: str | None = None) -> dict:
        return _categories.spending_by_tag(self._core, currency)

    # ---------------------------------------------------------------- rulings

    def rulings(self, scope: str | None = None) -> list[dict]:
        return _rulings.rulings(self._core, scope)

    def ruled_accounts(self) -> dict[str, dict]:
        return _rulings.ruled_accounts(self._core)

    def undecomposed(self, currency: str | None = None) -> dict:
        return _rulings.undecomposed(self._core, currency)

    # ------------------------------------------------------------------ tiers

    def tier_of(self, m: MovementInfo) -> str:
        return _tiers.tier_of(self._core, m)

    def tier_summary(self, currency: str | None = None) -> dict:
        return _tiers.tier_summary(self._core, currency)

    def declined_questions(self) -> dict[str, dict]:
        return _tiers.declined_questions(self._core)

    # ----------------------------------------------------------------- rhythm

    def rhythm_of(self, merchant: str, direction: str) -> tuple:
        """The periodicities confirmed for one counterparty, one way round.

        Ask under the strongest key for the merchant — what `merchant_key_of`
        returns for its movements. That key reaches a ruling recorded under any
        spelling of the name; one of the other spellings reaches only what was
        recorded under itself and under the brand, so a caller holding a
        descriptor can miss an answer and be told nothing."""
        return _rhythm.rhythm_of(self._core, merchant, direction)

    def rhythm_hypotheses(self) -> list[RhythmHypothesis]:
        return _rhythm.rhythm_hypotheses(self._core)

    # -------------------------------------------------------------- positions

    def snapshot_positions(self, st, as_of: str = "",
                           *, cash: bool = False) -> dict:
        return _positions.snapshot_positions(st, as_of, cash=cash)

    def positions(self, account: str | None = None) -> list[PositionRecord]:
        return _positions.positions(self._core, account)

    def holdings_value(self, account: str) -> Decimal:
        return _positions.holdings_value(self._core, account)

    def cash_value(self, account: str) -> Decimal:
        return _positions.cash_value(self._core, account)

    def holdings_as_of(self, account: str) -> tuple[str, bool]:
        return _positions.holdings_as_of(self._core, account)

    def account_value(self, account: str) -> Decimal:
        return _positions.account_value(self._core, account)

    def composed_values(self, account: str,
                        as_of: str = "") -> list[ComposedValue]:
        return _positions.composed_values(self._core, account, as_of)

    def unrealized_gain(self, account: str | None = None) -> Decimal | None:
        return _positions.unrealized_gain(self._core, account)

    # --------------------------------------------------------------- activity

    def agent_log(self) -> list[dict]:
        return _activity.agent_log(self._core)

    def agent_attempts(self) -> dict[tuple[str, str], dict]:
        return _activity.agent_attempts(self._core)

    def agent_calls_spent(self, since: str = "") -> int:
        return _activity.agent_calls_spent(self._core, since)
