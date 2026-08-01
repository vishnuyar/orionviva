"""The running-balance projection — a view rebuilt by replaying the event log.

The projection layer owns no truth; it re-derives it. Feed it the events, ask
for a balance, and it returns the number together with that number's *grade* and
*provenance*.

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

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from vivacore.verify.arithmetic import CheckResult, check_balance_identity

from .events import (SCOPE_CATEGORY, SCOPE_MERCHANT, SCOPE_TAG, ASSERTED, CONFLICTED, CORROBORATED, ISSUED, MAJOR_ASSET,
                     MAJOR_EXPENSE, MAJOR_INCOME, MAJOR_LIABILITY,
                     SCOPE_ACCOUNT, SCOPE_ATTRIBUTE, SCOPE_MERCHANT,
                     SCOPE_MOVEMENT, UNVERIFIED,
                     VERIFIED, Event, Provenance, postings_of)
from .identity import (account_key, account_tokens, names_overlap,
                       number_key, slug)
from merchantcore.descriptor import linted_example
from .merchants import is_shareable, normalize_merchant
from .postings import EQUITY_OPENING, INCOME_UNCATEGORIZED


class UnknownAccountError(KeyError):
    """Asked for a balance on an account the ledger has never seen. Raised
    rather than answered with zero; the answer path turns it into a refusal."""


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


@dataclass
class AccountInfo:
    account: str
    kind: str = ""
    currency: str = ""
    name: str = ""
    institution: str = ""
    number: str = ""                       # as extracted (mask for display)
    names: list[str] = field(default_factory=list)   # account holder name(s)
    origin: str = ISSUED     # who says this account exists
    # Where the INSTRUMENT lives — not where the person lives, and not its
    # currency: a person may hold an instrument of one country from another.
    # It decides which schema applies and which documents would attest it.
    jurisdiction: str = ""
    opened_at: str = ""      # when this account entered the ledger


@dataclass
class PositionRecord:
    """One holding measured at a date. A measurement, not a posting; unrealized
    gain is derived here, as-of that date, and is never a stored ledger fact."""
    account: str
    instrument: str
    units: Decimal
    market_value: Decimal
    currency: str
    as_of: str
    cost_basis: Decimal | None
    valuation_class: str
    grade: str
    provenance: Provenance

    def unrealized_gain(self) -> Decimal | None:
        """market_value − cost_basis, or None when the cost basis is unknown.
        Computed on demand; never posted or reconciled."""
        return None if self.cost_basis is None else self.market_value - self.cost_basis

    def to_dict(self) -> dict:
        ug = self.unrealized_gain()
        return {"account": self.account, "instrument": self.instrument,
                "units": str(self.units), "market_value": str(self.market_value),
                "currency": self.currency, "as_of": self.as_of,
                "cost_basis": (str(self.cost_basis)
                               if self.cost_basis is not None else None),
                "unrealized_gain": (str(ug) if ug is not None else None),
                "valuation_class": self.valuation_class, "grade": self.grade,
                "provenance": self.provenance.to_dict()}


@dataclass
class Resolution:
    """How a statement's identity signals resolve against known accounts."""
    account_id: str            # the account this statement belongs to
    key: str                   # the raw number/label key for these signals
    verdict: str               # "same" | "new" | "ambiguous"
    candidate: str = ""        # for ambiguous: the existing account it might be
    candidate_name: str = ""
    reason: str = ""           # human-readable why (for the ask)


@dataclass
class TxnLine:
    date: str
    description: str
    amount: Decimal
    grade: str
    provenance: Provenance

    def to_dict(self) -> dict:
        return {"date": self.date, "description": self.description,
                "amount": str(self.amount), "grade": self.grade,
                "provenance": self.provenance.to_dict()}


_GRADE_RANK = {VERIFIED: 3, CORROBORATED: 2, UNVERIFIED: 1}


def _grade_rank(grade: str | None) -> int:
    return _GRADE_RANK.get(grade or "", 0)


def movement_key(doc_id: str, account: str, date: str, amount: Decimal | str,
                 description: str, occurrence: int = 0) -> str:
    """A stable reference to one posted movement, for transfer links.

    Anchored to content — document, account, date, amount, description — plus an
    occurrence index that separates identical siblings in the same document. It
    survives a reingest, which mints new event ids, because it depends on what
    was read rather than on the event's identity. `occurrence` is assigned by
    the projection's canonical enumeration, so one movement always keys the
    same."""
    return f"{doc_id}|{account}|{date}|{amount}|{description}|{occurrence}"


# ------------------------------------------------------------- movement nature

# What a movement *is*, economically — the distinction that makes "spending"
# mean money that left your LIFE rather than money that left an ACCOUNT. Derived
# on the read side from events already written, so it is retroactive.
SPENDING = "spending"        # real external outflow — what aggregates count
TRANSFER = "transfer"        # the money is still yours (own card, own brokerage)
SETTLEMENT = "settlement"    # a ruling: repaid a loan, was paid back, ...
# A compound movement whose components are known but whose PROPORTIONS are not:
# a mortgage payment is interest (spending), principal (settlement) and escrow
# (still yours) at once, and the split is on a statement the ledger does not
# hold. Neither counted nor dropped — it gets its own line, named, with the
# document that would resolve it.
MIXED = "mixed"

# How a nature was decided, strongest first. Carried on the movement so a figure
# can explain itself and the surface can say why something was excluded.
BY_LINK = "linked"                   # rung 1: a live TransferLinked (decisive)
BY_OWN_ACCOUNT = "own_account"       # rung 3: names an account you hold
BY_RULING = "ruling"                 # rung 2: a ruling said so
BY_CATEGORY = "category_hint"        # rung 4: what the counterparty implies
BY_DEFAULT = "default"               # rung 5: nothing said otherwise

# A movement resting only on rung 4 is flagged PROVISIONAL: one category
# (`loan_payments`) covers opposite natures — a mortgage payment is a real
# outflow, a payment to your own card is internal — so the figure reports its
# own uncertainty rather than deciding on that evidence alone.

# Which tier a movement falls in, and therefore whether it is worth a person's
# attention. The rule: ask only where the counterparty cannot tell us.
TIER_SETTLED = "settled"      # enriched, implies nothing → silence
TIER_STRUCTURAL = "structural"  # implies a relationship → an informed proposal
TIER_UNKNOWN = "unknown"      # an instrument or a peer → a real question
TIER_UNENRICHED = "unenriched"  # the merchant is unidentified → enrich first



@dataclass
class MovementInfo:
    """One posted movement on a real (asset/liability) account, with the stable
    key a transfer link references. Fed to the transfer matcher."""
    key: str
    account: str
    kind: str
    date: str
    amount: Decimal
    description: str
    currency: str
    provenance: Provenance
    linked: bool = False
    # Derived, with the rung that decided it. `provisional` means the nature
    # rests only on a suggested implication, so the figure is counted and its
    # uncertainty is reported alongside.
    nature: str = SPENDING
    nature_reason: str = BY_DEFAULT
    provisional: bool = False
    # The chart-of-accounts path a ruling put this movement's counter-leg on
    # ("Liabilities:Mortgage:Acme"). Derived, never posted: the posted
    # counter-leg stays an Uncategorized bucket and every aggregate reads this
    # overlay instead.
    ruling_account: str = ""


# --- majors → nature ---------------------------------------------------------
# `nature` answers one question: did this money leave your LIFE, or only an
# account? Each major answers it directly.
_NATURE_OF_MAJOR = {
    MAJOR_EXPENSE: SPENDING,      # gone — what a spending figure counts
    MAJOR_ASSET: TRANSFER,        # you still have it, in another form
    MAJOR_LIABILITY: SETTLEMENT,  # what you owe changed; not consumption
    MAJOR_INCOME: SPENDING,       # only read for expense-shaped movements
}
# Which leg names the account a ruling brings into being, in priority order. A
# mortgage payment creates the LOAN account rather than an interest bucket, so
# the liability leads the asset.
#
# Expense and income are absent: only "you now own it" or "you now owe it" names
# a thing tracked as an account, and ordinary spending is described by its
# category in the Uncategorized bucket. A ruling with expense legs alone
# therefore names no account.
_LEG_PRIORITY = (MAJOR_LIABILITY, MAJOR_ASSET)


def nature_of_legs(legs: list[dict]) -> str:
    """The nature a ruling's legs imply: one nature among them gives that
    nature, several give ``MIXED``, and no legs gives ``SPENDING``."""
    natures = {_NATURE_OF_MAJOR.get(leg.get("major", ""), SPENDING) for leg in legs}
    if not natures:
        return SPENDING
    return natures.pop() if len(natures) == 1 else MIXED


def _leading_account(legs: list[dict]) -> str:
    for major in _LEG_PRIORITY:
        for leg in legs:
            if leg.get("major") == major and leg.get("account"):
                return leg["account"]
    return ""


@dataclass
class _AccountState:
    balance: Decimal = Decimal("0")            # running sum of all postings
    opening: Decimal | None = None
    opening_date: str = ""
    opening_prov: Provenance = field(default_factory=Provenance)
    closing: Decimal | None = None
    closing_date: str = ""
    closing_prov: Provenance = field(default_factory=Provenance)
    period_deltas: list[Decimal] = field(default_factory=list)  # non-opening postings
    seen: bool = False
    kind: str = ""
    currency: str = ""
    name: str = ""
    institution: str = ""
    number: str = ""
    names: list = field(default_factory=list)
    origin: str = ISSUED          # who says this account exists
    jurisdiction: str = ""        # where the instrument lives
    opened_at: str = ""           # when it entered the ledger
    # Every document that has said anything about this account. What KIND of
    # thing an account is is best answered by the documents an issuer produced
    # for it, so this is the evidence a schema is chosen on.
    doc_ids: set = field(default_factory=set)
    closing_confirmed: bool = False            # a human attested the closing
    # Every dated closing, not just the latest: net worth is a curve, so "the
    # balance at D" must be answerable for any D. The latest-wins fields above
    # answer for today.
    closings: list = field(default_factory=list)   # (date, Decimal, grade, doc_id)
    lines: list = field(default_factory=list)  # TxnLine per posting on this account
    # Holdings: instrument -> latest PositionObserved measurement (by as_of).
    # Measurements, not postings — they never touch `balance`.
    positions: dict = field(default_factory=dict)
    # Every position measurement ever seen, per instrument, in arrival order, so
    # an earlier point on the curve does not move when a later statement
    # arrives. {instrument: [observation, ...]}
    position_history: dict = field(default_factory=dict)
    # Cash/sweep lines recorded as "positions" by a read that did not recognize
    # them. Kept apart: they compose into the account's cash, never its holdings.
    position_cash: dict = field(default_factory=dict)


class LedgerProjection:
    """Replay events into per-account state, then answer balance queries.

    The read model for the whole ledger: per-account balances and ingest state
    (what is captured, posted, held). Built once and updated incrementally via
    ``apply``; the `Ledger` facade keeps one live instance so reads never
    re-replay the whole encrypted log.

    Opening Balance Equity is the *earliest known* opening. The injection is
    computed from ``st.opening`` at query time rather than accumulated per
    opening event, so a backfilled older statement re-seats the earliest opening
    with no double-count and no event to reverse.
    """

    def __init__(self, events: Iterable[Event], as_of: str | None = None,
                 resolve_keys=None) -> None:
        self.as_of = as_of
        # How a descriptor becomes the key its merchant knowledge is filed
        # under. None means "normalize the descriptor", which is right wherever
        # no grammar has named a brand. See `merchant_keys`.
        self._resolve_keys = resolve_keys
        self._mkeys: dict | None = None
        self._mkeys_of: dict = {}
        self._acct: dict[str, _AccountState] = {}
        # Ingest read-model, maintained incrementally alongside balances.
        self._captured: dict[str, str] = {}     # doc_id -> model's doc_type
        self._posted: set[str] = set()           # doc_ids with posting events
        self._held: dict[str, dict] = {}         # doc_id -> latest StatementHeld body
        self._aliases: dict[str, str] = {}       # learned: signal-key -> account_id
        # Transfer overlay: links between two movement keys, and unresolved
        # suggestions awaiting a ruling. Links are ledger-wide rather than
        # per-account, because a transfer spans two accounts.
        self._links: dict[frozenset, dict] = {}         # {a,b} -> {status,grade,by}
        self._transfer_suggestions: dict[str, dict] = {}  # movement key -> body
        # Category overlay: movement key -> {category, grade, by, descriptor}.
        # A human confirmation (verified) supersedes a model suggestion
        # (unverified); the highest-trust ruling is kept.
        self._categories: dict[str, dict] = {}
        # The tag overlay, in its own state and its own event type, so "tags
        # never leave this device" stays an event-level rule.
        self._movement_tags: dict[str, list] = {}
        self._merchant_tags: dict[str, list] = {}
        self._category_alias_map: dict[str, str] = {}
        self._tag_alias_map: dict[str, str] = {}
        # Merchant catalog: normalized merchant -> {category, grade, by}. The
        # prior a transaction's category derives from when it has no
        # per-movement override. Highest-trust ruling wins.
        self._merchant_categories: dict[str, dict] = {}
        # Rulings: (scope, subject) -> body. One dict for every scope, so a
        # movement ruling and a merchant ruling are looked up the same way.
        self._rulings: dict[tuple[str, str], dict] = {}
        # Every attribute ruling ever recorded, in arrival order, not just the
        # latest. A correction must not reach backwards: an earlier point on
        # the net-worth curve has to keep reading the answer that was true when
        # it was drawn, the same reason closings and holdings keep histories.
        self._attribute_history: list[dict] = []
        # Declined questions: question id -> the decline body, which snapshots
        # the stake (amount, count) the question showed when it was set aside.
        # The queue compares against the live stake; this only remembers.
        self._declined: dict[str, dict] = {}
        self._agent_log: list[dict] = []
        # Own-account token index, built lazily and invalidated when a new
        # account is opened. Recognizes an internal movement when no transfer
        # link was formed.
        self._own_tokens_cache: dict[str, set[str]] | None = None
        for event in events:
            self.apply(event)

    def apply(self, event: Event) -> None:
        """Fold one event into the projection (respecting an as_of horizon)."""
        if self.as_of is not None and event.occurred_at > self.as_of:
            return          # ISO dates sort lexically; skip the future
        self._apply(event)

    def _state(self, account: str) -> _AccountState:
        return self._acct.setdefault(account, _AccountState())

    def _apply(self, event: Event) -> None:
        et = event.event_type
        did = event.provenance.doc_id

        if et == "AccountOpened":
            st = self._state(event.body["account_id"])
            st.seen = True
            st.kind = event.body.get("kind", "")
            st.currency = event.body.get("currency", "")
            st.name = event.body.get("name", "")
            st.institution = event.body.get("institution", "")
            st.number = event.body.get("account_number", "")
            st.names = list(event.body.get("account_names", []))
            # An absent `origin` reads as `issued`: an event written before the
            # field existed came from a document.
            st.origin = event.body.get("origin", ISSUED)
            st.jurisdiction = event.body.get("jurisdiction", "")
            st.opened_at = st.opened_at or event.occurred_at
            if did:
                st.doc_ids.add(did)
            self._own_tokens_cache = None      # a new account changes the index
            # Which grammar reads an account's descriptors follows from its
            # institution and kind, so learning either re-keys its merchants.
            self._mkeys, self._mkeys_of = None, {}

        elif et == "OpeningBalanceObserved":
            acct = event.body["account_id"]
            amount = Decimal(event.body["amount"])
            st = self._state(acct)
            st.seen = True
            if did:
                st.doc_ids.add(did)
            if did:
                self._posted.add(did)
            # Keep the EARLIEST opening; it is injected once at query time, so a
            # backfilled older statement re-seats it rather than adding a seed.
            if st.opening is None or event.occurred_at < st.opening_date:
                st.opening = amount
                st.opening_date = event.occurred_at
                st.opening_prov = event.provenance

        elif et == "DocumentCaptured":
            self._captured[event.body["doc_id"]] = event.body.get("doc_type", "")

        elif et == "StatementHeld":
            self._held[event.body["doc_id"]] = event.body

        elif et == "AccountAliasConfirmed":
            self._aliases[event.body["alias_key"]] = event.body["account_id"]

        elif et == "TransferLinked":
            pair = frozenset({event.body["a"], event.body["b"]})
            # `decided_by` only, not the whole evidence dict: the evidence
            # carries both descriptions verbatim, while the rule's NAME is what
            # makes a link reviewable and carries nothing personal.
            self._links[pair] = {"status": "linked", "grade": event.body.get("grade", ""),
                                 "by": event.body.get("by", ""),
                                 "decided_by": (event.body.get("evidence")
                                                or {}).get("decided_by", "")}
            # A confirmed/auto link resolves any pending suggestion on either leg.
            self._transfer_suggestions.pop(event.body["a"], None)
            self._transfer_suggestions.pop(event.body["b"], None)

        elif et == "TransferUnlinked":
            pair = frozenset({event.body["a"], event.body["b"]})
            self._links[pair] = {"status": "unlinked"}
            # A rejection also dismisses any pending suggestion on either leg.
            self._transfer_suggestions.pop(event.body["a"], None)
            self._transfer_suggestions.pop(event.body["b"], None)

        elif et == "TransferSuggested":
            self._transfer_suggestions[event.body["a"]] = event.body

        elif et == "CategoryAssigned":
            key = event.body["movement_key"]
            prior = self._categories.get(key)
            # A verified (human) ruling wins; otherwise the latest applies.
            if prior is None or event.body.get("grade") == VERIFIED or prior.get("grade") != VERIFIED:
                self._categories[key] = event.body

        elif et == "RulingRecorded":
            key = (event.body["scope"], event.body["subject"])
            # The date travels with the ruling: an attribute stated in
            # September must not change what an earlier point on the net-worth
            # curve says about itself.
            event.body.setdefault("occurred_at", event.occurred_at)
            prior = self._rulings.get(key)
            # Same precedence as every other overlay: a verified ruling wins and
            # is never overwritten by a model's later guess.
            if prior is None or event.body.get("grade") == VERIFIED or prior.get("grade") != VERIFIED:
                self._rulings[key] = event.body
            if event.body["scope"] == SCOPE_ACCOUNT:
                self._own_tokens_cache = None
            if event.body["scope"] == SCOPE_ATTRIBUTE:
                self._attribute_history.append(dict(event.body))
            # Label aliases are maintained here rather than derived per lookup:
            # `derived_category` is the funnel every aggregate reads through, so
            # a per-lookup derivation would rebuild the map on every call.
            scope = event.body["scope"]
            if scope in (SCOPE_CATEGORY, SCOPE_TAG) and event.body.get("same_as"):
                target = (self._category_alias_map if scope == SCOPE_CATEGORY
                          else self._tag_alias_map)
                target[event.body["subject"]] = event.body["same_as"]

        elif et == "QuestionDeclined":
            # Last decline wins; a question re-declined after returning simply
            # updates its snapshot to the new stake.
            self._declined[event.body["question_id"]] = event.body

        elif et == "AgentActed":
            # Kept in arrival order and never collapsed, so the log answers both
            # "what is the latest attempt on this target?" (the cooldown) and
            # "what has the agent been doing?" (the journal).
            self._agent_log.append({**event.body, "occurred_at": event.occurred_at})

        elif et in ("MerchantCategorized", "MerchantEnriched"):
            merchant = event.body["merchant"]
            prior = self._merchant_categories.get(merchant)
            # Keep the highest-trust record; a later equal-or-higher grade wins.
            # MerchantCategorized (category only) and MerchantEnriched (the
            # richer package-synced record) share this catalog.
            if prior is None or _grade_rank(event.body.get("grade")) >= _grade_rank(prior.get("grade")):
                self._merchant_categories[merchant] = event.body

        elif et == "ClosingBalanceObserved":
            acct = event.body["account_id"]
            st = self._state(acct)
            st.seen = True
            if did:
                st.doc_ids.add(did)
            if did:
                self._posted.add(did)
            # Across stitched months the latest-dated closing is the current
            # balance to answer with; earlier closings were true when written.
            if st.closing is None or event.occurred_at >= st.closing_date:
                st.closing = Decimal(event.body["amount"])
                st.closing_date = event.occurred_at
                st.closing_prov = event.provenance
                st.closing_confirmed = event.body.get("confirmed_by") == "human"
            # A closing reaches the ledger only from a statement that
            # reconciled, so it grades corroborated; a person who attested it
            # raises that to verified. The grade is derived here, not read off
            # the body, which carries no `grade` key.
            st.closings.append((event.occurred_at, Decimal(event.body["amount"]),
                                VERIFIED if event.body.get("confirmed_by") == "human"
                                else CORROBORATED, did or ""))

        elif et == "MovementTagged":
            # Last write wins on the COMPLETE set — removing a tag is appending
            # the set without it, so there is no untag event to reconcile
            # against an add that arrived out of order.
            b = event.body or {}
            bucket = (self._merchant_tags if b.get("scope") == SCOPE_MERCHANT
                      else self._movement_tags)
            bucket[b.get("subject", "")] = list(b.get("tags") or [])

        elif et == "PositionObserved":
            acct = event.body["account_id"]
            st = self._state(acct)
            st.seen = True
            if did:
                self._posted.add(did)
            instrument = event.body["instrument"]
            # A cash/sweep line misfiled as a holding by an older read is cash,
            # not a position. Reinterpreting it here rather than only at ingest
            # makes an existing vault correct on the next query, with nothing
            # rewritten; the ingest-side fold stops new ones arriving.
            from ..ingest.brokerage import is_cash_row
            bucket = st.position_cash if is_cash_row(instrument) else st.positions
            cb = event.body.get("cost_basis", "")
            record = {
                "units": Decimal(event.body["units"]),
                "market_value": Decimal(event.body["market_value"]),
                "currency": event.body.get("currency", ""),
                "as_of": event.occurred_at,
                "cost_basis": Decimal(cb) if cb not in (None, "") else None,
                "valuation_class": event.body.get("valuation_class", "measured"),
                "grade": event.body.get("grade", ""),
                "provenance": event.provenance,
                "is_cash": is_cash_row(instrument)}
            # History carries the WHOLE measurement, so a reader can rebuild any
            # statement's snapshot, not only the latest one per instrument.
            st.position_history.setdefault(instrument, []).append(record)
            prior = bucket.get(instrument)
            # Keep the latest measurement by value-time (as_of); an earlier one
            # was true when written, and a revaluation is a new observation.
            if prior is None or event.occurred_at >= prior.get("as_of", ""):
                bucket[instrument] = record

        elif et == "TransactionRecorded":
            if did:
                self._posted.add(did)
            # A new descriptor may resolve differently once the ACH corpus
            # grows, so the key map is dropped rather than extended.
            self._mkeys, self._mkeys_of = None, {}
            for p in postings_of(event):
                st = self._state(p.account)
                st.seen = True
                st.balance += p.amount           # transaction postings only (no OBE)
                st.lines.append(TxnLine(
                    date=event.occurred_at,
                    description=event.body.get("description", ""),
                    amount=p.amount, grade=p.grade, provenance=event.provenance))
                # Period deltas exclude the opening seed (that's tracked apart),
                # so reconciliation is opening + period == closing.
                if p.account != EQUITY_OPENING:
                    st.period_deltas.append(p.amount)

    # --------------------------------------------------------------- queries

    def accounts(self) -> list[str]:
        return sorted(a for a, s in self._acct.items() if s.seen)

    def seen_account(self, account: str) -> bool:
        st = self._acct.get(account)
        return bool(st and st.seen)

    def is_seeded(self, account: str) -> bool:
        """True once an opening balance has been booked: the account's history
        has a starting point, and later statements continue from it rather than
        re-seeding it."""
        st = self._acct.get(account)
        return bool(st and st.opening is not None)

    @staticmethod
    def _effective(st: _AccountState) -> Decimal:
        """Account balance = earliest opening (the OBE injection) + transaction
        postings. The opening is injected here, once, rather than accumulated
        per opening event."""
        return (st.opening or Decimal("0")) + st.balance

    def running_balance(self, account: str) -> Decimal | None:
        """The replayed balance, or None if the account is unseen. Used by ingest
        to check that a new statement's opening continues from where we left off."""
        st = self._acct.get(account)
        return self._effective(st) if (st and st.seen) else None

    def earliest_opening(self, account: str) -> Decimal | None:
        """The account's earliest known opening, or None if unseen — the balance
        a still-older statement must *close* at to backfill in front of the
        chain."""
        st = self._acct.get(account)
        return st.opening if st else None

    # ------------------------------------------------------ ingest read-model

    def is_resolved(self, doc_id: str) -> bool:
        """A document has reached a terminal state — posted, or held for review."""
        return doc_id in self._posted or doc_id in self._held

    def posted_doc_ids(self) -> set[str]:
        return set(self._posted)

    def captured_docs(self) -> dict[str, str]:
        return dict(self._captured)

    def open_holds(self) -> list[dict]:
        """StatementHeld bodies for documents not since posted."""
        return [b for did, b in self._held.items() if did not in self._posted]

    def gap_holds(self) -> list[dict]:
        return [b for b in self.open_holds() if b.get("reason") == "gap"]

    # ----------------------------------------------------------- transfers

    def linked_keys(self) -> set[str]:
        """Movement keys that are part of a *live* transfer link (not unlinked)."""
        out: set[str] = set()
        for pair, info in self._links.items():
            if info.get("status") == "linked":
                out.update(pair)
        return out

    def is_linked(self, key: str) -> bool:
        return key in self.linked_keys()

    def movements(self) -> list["MovementInfo"]:
        """Every posted movement on a real (asset/liability) account, each with
        its stable transfer key and its derived nature.

        Occurrence indices are assigned here, once, so the matcher and the
        projection agree on every key. Uncategorized counter-legs are excluded:
        they are not transfer candidates."""
        linked = self.linked_keys()
        out: list[MovementInfo] = []
        counts: dict[tuple, int] = {}
        for account in self.accounts():
            st = self._acct[account]
            # depository/liability movements, plus an investment account's cash
            # activity, so a contribution into a brokerage ties to the funding
            # account as a transfer.
            if st.kind not in ("depository", "liability", "investment"):
                continue
            for ln in sorted(st.lines, key=lambda l: (l.date, l.description, str(l.amount))):
                did = ln.provenance.doc_id
                sig = (did, account, ln.date, str(ln.amount), ln.description)
                occ = counts.get(sig, 0)
                counts[sig] = occ + 1
                key = movement_key(did, account, ln.date, ln.amount,
                                   ln.description, occ)
                m = MovementInfo(
                    key=key, account=account, kind=st.kind, date=ln.date,
                    amount=ln.amount, description=ln.description,
                    currency=st.currency, provenance=ln.provenance,
                    linked=key in linked)
                self._decide_nature(m)
                out.append(m)
        return out

    def _own_account_tokens(self) -> dict[str, set[str]]:
        """`{account: tokens}` for every account held, so a movement naming one
        of them is recognized as internal even when no link was formed.

        ISSUED accounts only. An `asserted` account is named after the
        counterparty whose payments created it — `Liabilities:Mortgage:Acme`
        from "ACME MORTGAGE SERVICING" — so including it would read every one of
        those payments as an internal transfer to itself."""
        if self._own_tokens_cache is None:
            self._own_tokens_cache = {
                a: account_tokens(s.institution, s.number, s.name)
                for a, s in self._acct.items()
                if s.seen and s.kind in ("depository", "liability", "investment")
                and s.origin == ISSUED}
        return self._own_tokens_cache

    # --- merchant identity ---------------------------------------------------
    #
    # A merchant is filed under its BRAND: two locations of one retailer are one
    # key and one record. Naming the brand takes the resolution layers, and the
    # best of them is a grammar living outside the event log — so the key map is
    # built by an injected resolver rather than derived from events. Without one
    # a descriptor normalizes to itself, which is what every read did before
    # grammars existed.
    #
    # Every lookup therefore considers TWO keys. Knowledge recorded before a
    # grammar could name the brand sits under the descriptor, and a person's
    # answer is the most trustworthy record in the vault; a lookup that found
    # only the brand key would lose it. The candidates are ranked by grade, the
    # brand winning a tie, so the strongest record answers regardless of which
    # name it happens to be filed under.

    def _merchant_key_map(self) -> dict:
        """`{(account, descriptor): brand key}` for every line held.

        Built once and dropped whenever a transaction or an account arrives,
        because both can change how a descriptor resolves."""
        if self._mkeys is None:
            if self._resolve_keys is None:
                self._mkeys = {}
            else:
                # Only the accounts `movements` reads: the other side of a
                # posting is a category, and a category has no counterparty.
                self._mkeys = self._resolve_keys(
                    [(account, st.institution, st.kind, ln.description)
                     for account, st in self._acct.items()
                     if st.kind in ("depository", "liability", "investment")
                     for ln in st.lines])
        return self._mkeys

    def merchant_keys_of(self, m: "MovementInfo") -> tuple:
        """Every key this movement's merchant could be filed under, strongest
        identity first: the brand, then the descriptor where they differ.

        Memoized per descriptor: this is read several times for every movement
        in the vault on every aggregate, and normalization is a run of regular
        expressions."""
        cached = self._mkeys_of.get((m.account, m.description))
        if cached is not None:
            return cached
        descriptor_key = normalize_merchant(m.description)
        brand_key = self._merchant_key_map().get((m.account, m.description),
                                                 descriptor_key)
        keys = ((descriptor_key,) if brand_key in ("", descriptor_key)
                else (brand_key, descriptor_key))
        self._mkeys_of[(m.account, m.description)] = keys
        return keys

    def merchant_key_of(self, m: "MovementInfo") -> str:
        """The single key this movement's merchant is known by now — what a
        surface groups on and what a new ruling about it is written under."""
        return self.merchant_keys_of(m)[0]

    def _merchant_graded(self, get, m: "MovementInfo") -> dict | None:
        """The highest-graded record `get(key)` finds among the candidates, or
        None. Ties go to the first candidate, which is the brand."""
        best = None
        for key in self.merchant_keys_of(m):
            found = get(key)
            if found is None:
                continue
            if best is None or _grade_rank(found.get("grade")) > _grade_rank(best.get("grade")):
                best = found
        return best

    def _merchant_record(self, m: "MovementInfo") -> dict | None:
        """This movement's catalog record — what enrichment learned about the
        counterparty, or what a person ruled about it."""
        return self._merchant_graded(self._merchant_categories.get, m)

    def _merchant_ruling(self, m: "MovementInfo") -> dict | None:
        """The merchant-scoped ruling covering this movement, if one was made."""
        return self._merchant_graded(
            lambda key: self._rulings.get((SCOPE_MERCHANT, key)), m)

    def _decide_nature(self, m: "MovementInfo") -> None:
        """Set `nature`, `nature_reason`, `provisional` and `ruling_account` on
        one movement, from the strongest evidence available.

        1. linked            — a live TransferLink. Decisive.
        2. a ruling          — someone said what this is.
        3. own account       — the description distinctively names another
                               account you hold, so a card payment whose
                               counterpart statement was never ingested is
                               still not spending.
        4. category hint     — what the counterparty implies; counted, and
                               marked provisional unless the implication is
                               `forced`.
        5. default           — spending.

        A ruling outranks the own-account rung, which is a heuristic over
        description text: when the two disagree the ruling decides."""
        if m.linked:
            m.nature, m.nature_reason = TRANSFER, BY_LINK
            return
        # Rung 2: an explicit ruling, from three places, strongest first — a
        # RulingRecorded on this movement, then one on its MERCHANT (so one
        # answer settles every transaction from that counterparty, past and
        # future), then the `nature` field carried on the category overlay or
        # the merchant's attributes.
        ruling = (self._rulings.get((SCOPE_MOVEMENT, m.key))
                  or self._merchant_ruling(m))
        if ruling and ruling.get("legs"):
            m.nature, m.nature_reason = nature_of_legs(ruling["legs"]), BY_RULING
            m.ruling_account = _leading_account(ruling["legs"])
            # Components known, proportions not — reported as provisional.
            m.provisional = (m.nature == MIXED)
            return
        nature = (self._categories.get(m.key) or {}).get("nature")
        if nature not in (TRANSFER, SETTLEMENT, SPENDING):
            merchant = self._merchant_record(m) or {}
            nature = (merchant.get("attributes") or {}).get("nature")
        if nature in (TRANSFER, SETTLEMENT, SPENDING):
            m.nature, m.nature_reason = nature, BY_RULING
            return
        # Rung 3: does this movement name one of YOUR OTHER accounts?
        low = (m.description or "").lower()
        for account, tokens in self._own_account_tokens().items():
            if account == m.account:
                continue                      # naming itself proves nothing
            if tokens and any(tok in low for tok in tokens):
                m.nature, m.nature_reason = TRANSFER, BY_OWN_ACCOUNT
                return
        # Rung 4: what this COUNTERPARTY implies, given which way the money
        # went. Learned at enrichment rather than matched against a word list. A
        # `forced` implication is decisive; a `suggested` one is provisional.
        implied = self.implication_of(m)
        if implied:
            nature = _NATURE_OF_MAJOR.get(implied["major"], SPENDING)
            if nature != SPENDING:
                m.nature, m.nature_reason = nature, BY_CATEGORY
                m.provisional = implied.get("confidence") != "forced"
                return
        m.nature, m.nature_reason, m.provisional = SPENDING, BY_DEFAULT, False

    def transfer_suggestions(self) -> list[dict]:
        """Pending transfer suggestions awaiting a ruling.

        A suggestion is dropped when its source is now linked, or when every one
        of its candidates is — either way the money it asks about has been
        settled elsewhere and the question has no answer left to give.

        Filtered on the read side, never withdrawn by an event: unlink the pair
        that took the candidate and the question comes back."""
        linked = self.linked_keys()
        out = []
        for s in self._transfer_suggestions.values():
            if s["a"] in linked:
                continue
            cands = s.get("candidates") or []
            # A suggestion with no candidates at all is kept, so a malformed one
            # is surfaced rather than dropped.
            if cands and all(c in linked for c in cands):
                continue
            out.append(s)
        return out

    def transfer_links(self) -> list[dict]:
        """Live transfer links (the recognized internal transfers), with grade."""
        return [{"a": min(p), "b": max(p), **info}
                for p, info in self._links.items()
                if info.get("status") == "linked"]

    def income_by_currency(self) -> dict[str, Decimal]:
        """Attributed income per currency: the sum of `Income:*` accounts as a
        positive magnitude, **excluding the `Income:Uncategorized` placeholder**.

        `Income:Uncategorized` is the undifferentiated inflow bucket and is
        excluded, so an inflow nothing has attributed is not reported as income.

        Income buckets carry no currency of their own: with exactly one account
        currency, income is attributed to it, otherwise to '?'."""
        held = {s.currency for a, s in self._acct.items()
                if s.seen and s.kind in ("depository", "liability", "investment")
                and s.currency}
        default = next(iter(held)) if len(held) == 1 else "?"
        out: dict[str, Decimal] = {}
        for account, st in self._acct.items():
            if (not st.seen or not account.startswith("Income:")
                    or account == INCOME_UNCATEGORIZED):
                continue
            amt = -self._effective(st)          # credits are negative; report positive
            if amt != 0:
                cur = st.currency or default
                out[cur] = out.get(cur, Decimal("0")) + amt
        return out

    def spending_by_currency(self) -> dict[str, Decimal]:
        """Depository outflows per currency, as positive magnitudes, excluding
        non-spending natures. Superseded by ``spending_by_category``, which is
        the full view; kept for callers that predate it."""
        out: dict[str, Decimal] = {}
        for m in self.movements():
            if m.kind != "depository" or m.amount >= 0 or m.nature != SPENDING:
                continue
            out[m.currency] = out.get(m.currency, Decimal("0")) + (-m.amount)
        return out

    # ----------------------------------------------------------- categories

    @staticmethod
    def _is_expense(m: "MovementInfo") -> bool:
        """A movement with the *shape* of spending: money out of an asset, or a
        charge on a liability (a card purchase). A card *payment* — liability,
        negative — is not.

        Shape alone does not decide; what a movement is economically is its
        `nature`, and ``_counts_as_spending`` applies both."""
        return ((m.kind == "depository" and m.amount < 0)
                or (m.kind == "liability" and m.amount > 0))

    def _counts_as_spending(self, m: "MovementInfo") -> bool:
        """True when a movement belongs in a spending figure: it has the shape of
        an expense AND its nature is `spending`. A card payment, a brokerage
        contribution, or a movement naming another account you hold is excluded
        whether or not a link was formed."""
        return self._is_expense(m) and m.nature == SPENDING

    def provisional_spending(self, currency: str | None = None) -> Decimal:
        """The total magnitude of expense-shaped movements whose nature rests on
        weak evidence (`provisional`), filtered by `currency` if given. Reported
        alongside the spending total, so the figure states its uncertainty."""
        total = Decimal("0")
        for m in self.movements():
            if not self._is_expense(m) or not m.provisional:
                continue
            if currency is not None and m.currency != currency:
                continue
            total += abs(m.amount)
        return total

    def excluded_from_spending(self) -> list["MovementInfo"]:
        """Expense-shaped movements kept OUT of spending because their nature is
        not `spending`, each carrying the rung that decided it."""
        return [m for m in self.movements()
                if self._is_expense(m) and m.nature != SPENDING]

    def undecomposed(self, currency: str | None = None) -> dict:
        """Money whose components are known but whose proportions are not — the
        ``MIXED`` bucket, filtered by `currency` if given.

        Reported as its own line rather than folded into spending: counting it
        all overstates spending and dropping it understates.

        Returns ``{total, count, accounts, corroborates}``, where
        ``corroborates`` names the documents that would resolve the split."""
        total, count = Decimal("0"), 0
        accounts: set[str] = set()
        docs: set[str] = set()
        for m in self.movements():
            if m.nature != MIXED or not self._is_expense(m):
                continue
            if currency is not None and m.currency != currency:
                continue
            total += abs(m.amount)
            count += 1
            if m.ruling_account:
                accounts.add(m.ruling_account)
            ruling = (self._rulings.get((SCOPE_MOVEMENT, m.key))
                      or self._merchant_ruling(m))
            if ruling and ruling.get("corroborates"):
                docs.add(ruling["corroborates"])
        return {"total": total, "count": count,
                "accounts": sorted(accounts), "corroborates": sorted(docs)}

    def ruled_accounts(self) -> dict[str, dict]:
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
        for m in self.movements():
            if not m.ruling_account:
                continue
            row = out.setdefault(m.ruling_account, {
                "account": m.ruling_account, "paid": Decimal("0"), "count": 0,
                "currency": m.currency, "origin": ASSERTED,
                "reliable_balance": True, "valuation": "measured"})
            row["paid"] += abs(m.amount)
            row["count"] += 1
            if m.nature == MIXED:
                row["reliable_balance"] = False
                row["valuation"] = "estimated"
        return out

    def rulings(self, scope: str | None = None) -> list[dict]:
        """Every ruling, sorted, optionally filtered to one scope. Each dict is
        the event body plus its ``scope`` and ``subject``."""
        return [dict(body, scope=s, subject=subj)
                for (s, subj), body in sorted(self._rulings.items())
                if scope is None or s == scope]

    def implication_for(self, merchant: str, inflow: bool = False) -> dict | None:
        """The first implication a MERCHANT KEY carries in the given direction,
        or None. Keyed on the catalog rather than on a movement, so a caller can
        ask about a counterparty it has not seen yet."""
        return self._implication_in(self._merchant_categories.get(merchant),
                                    inflow=inflow)

    @staticmethod
    def _implication_in(record: dict | None, inflow: bool = False) -> dict | None:
        """The first implication a catalog record carries in the given
        direction, or None."""
        implies = ((record or {}).get("attributes") or {}).get("implies") or []
        want = "inflow" if inflow else "outflow"
        for item in implies:
            if item.get("on") in (want, "both"):
                return item
        return None

    def implication_of(self, m: "MovementInfo") -> dict | None:
        """What this movement's counterparty implies, filtered by DIRECTION.

        Money out to a lender repays borrowing; money in from one is the
        borrowing. Same counterparty, opposite sign, opposite meaning — so `on`
        is data on the implication rather than a branch in the caller."""
        return self._implication_in(self._merchant_record(m),
                                    inflow=m.amount > 0)

    def counterparty_kind(self, m: "MovementInfo") -> str:
        """business | instrument | peer | "" — learned, not pattern-matched."""
        return ((self._merchant_record(m) or {}).get("attributes")
                or {}).get("counterparty_kind", "")

    def kind_of_merchant(self, merchant: str) -> str:
        record = self._merchant_categories.get(merchant)
        return ((record or {}).get("attributes") or {}).get("counterparty_kind", "")

    def tier_of(self, m: "MovementInfo") -> str:
        """Which tier this movement falls in — how much of a person's attention
        it deserves. The queue's rule: ask only where the counterparty cannot
        tell us. A supermarket tells us everything (settled); a mortgage servicer
        tells us there is a loan but not which property (structural); a check
        tells us nothing (unknown)."""
        if self.counterparty_kind(m) in ("instrument", "peer"):
            return TIER_UNKNOWN
        # A descriptor that cannot be SHARED never reaches enrichment, so it can
        # never become `settled` and `unenriched` would promise an identification
        # that will not come. It is `unknown`, the tier that asks one transaction
        # at a time.
        if not is_shareable(m.description):
            return TIER_UNKNOWN
        if self.derived_category(m) is None:
            return TIER_UNENRICHED
        return TIER_STRUCTURAL if self.implication_of(m) else TIER_SETTLED

    def tier_summary(self, currency: str | None = None) -> dict:
        """Per tier, ``{count, amount, merchants}`` — the measurement that sizes
        the queue. ``merchants`` is a count of distinct normalized keys."""
        out: dict[str, dict] = {}
        for m in self.movements():
            if currency is not None and m.currency != currency:
                continue
            row = out.setdefault(self.tier_of(m), {"count": 0, "amount": Decimal("0"),
                                                   "merchants": set()})
            row["count"] += 1
            row["amount"] += abs(m.amount)
            row["merchants"].add(self.merchant_key_of(m) or m.description)
        return {k: {"count": v["count"], "amount": v["amount"],
                    "merchants": len(v["merchants"])} for k, v in out.items()}

    # --- category identity ---------------------------------------------------
    #
    # A category label is a bare string rather than a resolved identity, so
    # `poker` and `playing poker` can both exist and split a total. The fix is
    # the same primitive accounts, transfers and merchants use: ask when
    # ambiguous, record the ruling, apply it on the READ side. Not fuzzy string
    # matching — a recorded alias is auditable and stable between runs, and is
    # reversed by appending rather than editing.

    # --- tags ----------------------------------------------------------------
    #
    # A category PARTITIONS (one per movement, parts sum to the whole); a tag
    # OVERLAYS (many per movement, overlapping, and the totals do NOT sum).
    # Double-entry governs the money; tags govern the meaning.

    def tags_of(self, m: "MovementInfo") -> list[str]:
        """Every tag on this movement, canonicalized and sorted: its own tags
        unioned with its merchant's.

        A union rather than an override — "everything from this gym is martial
        arts" and "this visit was a birthday present" are both true, and the
        movement is found under either."""
        own = self._movement_tags.get(m.key, [])
        shared = next((self._merchant_tags[k] for k in self.merchant_keys_of(m)
                       if self._merchant_tags.get(k)), [])
        return sorted({self.canonical_tag(t) for t in list(own) + list(shared)})

    def tag_aliases(self) -> dict[str, str]:
        """Tag-vocabulary aliases, kept apart from category aliases: a tag
        "poker" and a category "poker" are different things, and merging one
        does not merge the other."""
        return dict(self._tag_alias_map)

    def canonical_tag(self, label: str) -> str:
        aliases = self._tag_alias_map
        seen: set[str] = set()
        current = (label or "").strip().lower()
        while current in aliases and current not in seen:
            seen.add(current)
            current = aliases[current]
        return current

    def known_tags(self) -> list[str]:
        """The tag vocabulary, canonical labels only — offered before a new tag
        can be minted, exactly as the category vocabulary is."""
        out = {self.canonical_tag(t)
               for tags in list(self._movement_tags.values())
               + list(self._merchant_tags.values()) for t in tags}
        return sorted(t for t in out if t)

    def spending_by_tag(self, currency: str | None = None) -> dict:
        """Spending per tag: ``{by_tag, untagged, total, overlaps}``.

        The per-tag figures DO NOT sum to `total`, and callers must show
        `untagged` and `total` alongside them: one movement carrying three tags
        appears in three lines, and money with no tags appears in none. The
        category report is the one that partitions; this answers a different
        question ("how much on the Japan trip, across every merchant?")."""
        by_tag: dict[str, Decimal] = {}
        untagged = total = Decimal("0")
        for m in self.movements():
            if not self._counts_as_spending(m):
                continue
            if currency is not None and m.currency != currency:
                continue
            amount = abs(m.amount)
            total += amount
            tags = self.tags_of(m)
            if not tags:
                untagged += amount
            for tag in tags:
                by_tag[tag] = by_tag.get(tag, Decimal("0")) + amount
        return {"by_tag": by_tag, "untagged": untagged, "total": total,
                "overlaps": True}

    def declined_questions(self) -> dict[str, dict]:
        """Questions set aside, by the queue's stable question id. Each body
        carries the stake snapshot (amount, count) from the moment of decline.
        Data, not policy: this remembers, the queue decides."""
        return dict(self._declined)

    def agent_log(self) -> list[dict]:
        """Everything the agent did unattended, oldest first: rule, target,
        outcome, model calls actually spent, and the artifact produced. Every
        attempt is kept; none is collapsed."""
        return list(self._agent_log)

    def agent_attempts(self) -> dict[tuple[str, str], dict]:
        """The most recent attempt per (rule, target), whatever its outcome.

        Data, not policy: this remembers and the runner decides, as
        `declined_questions` remembers and the queue decides."""
        out: dict[tuple[str, str], dict] = {}
        for a in self._agent_log:
            out[(a.get("rule", ""), a.get("target", ""))] = a
        return out

    def agent_calls_spent(self, since: str = "") -> int:
        """Model calls the agent has spent on its own initiative — actuals, not
        estimates. `since` is an ISO date; omit it for the lifetime figure."""
        return sum(int(a.get("calls", 0)) for a in self._agent_log
                   if not since or str(a.get("occurred_at", ""))[:10] >= since)

    def category_aliases(self) -> dict[str, str]:
        """{duplicate label -> the label it is really the same as}."""
        return dict(self._category_alias_map)

    def canonical_category(self, label: str) -> str:
        """Follow a label to the one every total counts it under.

        Chains are followed (a → b → c) and a cycle terminates rather than
        hanging, returning the last label reached."""
        aliases = self._category_alias_map
        seen: set[str] = set()
        current = label
        while current in aliases and current not in seen:
            seen.add(current)
            current = aliases[current]
        return current

    def known_categories(self) -> list[str]:
        """The category vocabulary that already exists, canonical labels only.

        Offered to every path that could MINT a label: the surface picker, the
        free-text ruling, and enrichment's prompt."""
        out = {self.canonical_category(c)
               for row in self._merchant_categories.values()
               for c in [(row.get("category") or "").strip()] if c}
        out |= {self.canonical_category((row.get("category") or "").strip())
                for row in self._categories.values()
                if (row.get("category") or "").strip()}
        return sorted(out)

    def known_subcategories(self) -> list[str]:
        """The finer vocabulary, canonicalized — the subcategory labels the
        merchant catalog and the per-movement overlay carry."""
        out = {self.canonical_category(s)
               for row in list(self._merchant_categories.values())
               + list(self._categories.values())
               for s in [(row.get("subcategory") or "").strip()] if s}
        return sorted(out)

    def derived_category(self, m: "MovementInfo") -> dict | None:
        """A movement's effective category: a per-transaction override wins,
        else the strongest catalog record its merchant is filed under, else
        None. Returns the ruling dict ({category, grade, ...}) with its labels
        canonicalized."""
        override = self._categories.get(m.key)
        found = override if override is not None else self._merchant_record(m)
        if found is None:
            return None
        # Canonicalized here, at the one funnel every aggregate reads through,
        # so a single alias ruling corrects spending-by-category,
        # spending-by-subcategory, the tiers and net worth at once.
        if not self._category_alias_map:
            return found
        out = dict(found)
        for field_name in ("category", "subcategory"):
            value = (out.get(field_name) or "").strip()
            if value:
                out[field_name] = self.canonical_category(value)
        return out

    def category_of(self, key: str) -> dict | None:
        """The per-transaction override ruling on a movement, or None (the raw
        overlay; ``derived_category`` resolves the merchant prior too)."""
        return self._categories.get(key)

    def merchant_categories(self) -> dict[str, dict]:
        """The merchant catalog: normalized merchant -> ruling."""
        return dict(self._merchant_categories)

    def spending_by_category(self, currency: str | None = None) -> dict[str, Decimal]:
        """Real spending grouped by category: every expense movement, card
        purchases included, bucketed by its *derived* category (override →
        merchant catalog → ``Uncategorized``). Positive magnitudes;
        ``currency`` filters if given.

        Exclusion is by **nature**, not merely by link, so an internal movement
        that never linked — a card payment, a brokerage contribution — is not
        counted, and `transfers` never appears as a line item inside spending."""
        out: dict[str, Decimal] = {}
        for m in self.movements():
            if not self._counts_as_spending(m):
                continue
            if currency is not None and m.currency != currency:
                continue
            cat = (self.derived_category(m) or {}).get("category", "Uncategorized")
            out[cat] = out.get(cat, Decimal("0")) + abs(m.amount)
        return out

    def spending_by_subcategory(self, currency: str | None = None) -> dict[str, Decimal]:
        """Finer spending view: expense movements grouped by the merchant's
        **subcategory** ("streaming", "warehouse club"), falling back to the
        primary category, then ``Uncategorized``. Positive magnitudes;
        non-spending natures excluded."""
        out: dict[str, Decimal] = {}
        for m in self.movements():
            if not self._counts_as_spending(m):
                continue
            if currency is not None and m.currency != currency:
                continue
            ruling = self.derived_category(m) or {}
            label = (ruling.get("subcategory") or ruling.get("category")
                     or "Uncategorized")
            out[label] = out.get(label, Decimal("0")) + abs(m.amount)
        return out

    def uncategorized_expenses(self) -> list["MovementInfo"]:
        """Expense movements whose *derived* category is still unknown — no
        override and no merchant-catalog entry. The categorization queue;
        non-spending natures are excluded, so money that did not leave the
        person's life is never asked about."""
        return [m for m in self.movements()
                if self._counts_as_spending(m)
                and self.derived_category(m) is None]

    def uncategorized_merchants(self, expenses_only: bool = False) -> dict[str, dict]:
        """Every counterparty we have not identified yet, deduped by normalized
        key: {merchant -> {count, example, shareable}}. The batched enricher's
        pending set.

        Every counterparty, not just the expense-shaped ones: employers,
        transfers, card payments and inflows are all visible to enrichment.

        `expenses_only=True` gives the narrower, expense-only view for the
        spending queue."""
        from .merchants import is_shareable
        out: dict[str, dict] = {}
        source = (self.uncategorized_expenses() if expenses_only
                  else [m for m in self.movements()
                        if self.derived_category(m) is None])
        for m in source:
            key = self.merchant_key_of(m)
            if not key:
                continue
            # The LINTED example, never the raw line: a raw descriptor carries
            # store numbers, order ids and posting dates, none of which help
            # identify a brand and all of which would cross to a model provider.
            row = out.setdefault(key, {"count": 0,
                                       "example": linted_example(m.description),
                                       "shareable": is_shareable(m.description)})
            row["count"] += 1
        return out

    # ------------------------------------------------- identity resolution

    def resolve(self, institution: str, account_number: str, account_ref: str,
                names: list[str], kind: str = "depository") -> Resolution:
        """Resolve a statement's identity signals against known accounts.

        The verdict is 'same' (a learned alias, or an account with this key),
        'new', or 'ambiguous' (nothing stronger than a holder name connects this
        statement to a held account, so it is worth one question).

        A holder's name is the weakest identity signal: it is on every account
        that person owns. It raises an ambiguity only when the stronger signals
        cannot settle the question, and three rules settle it first:

        * **Two readable, different account numbers are two accounts.** The
          number is the anchor, and a checking and a savings account at one bank
          share a holder by definition.
        * **When neither statement shows a number**, two different product
          labels are two accounts, compared as slugs rather than fuzzily.
        * The comparison is scoped to one account ``kind``, so a card and a
          checking account sharing a holder are two accounts.

        A wrong split is visible and a merge ruling repairs it; a wrong merge
        corrupts a balance silently."""
        key = account_key(institution, account_number, account_ref)
        if key in self._aliases:                       # learned
            return Resolution(self._aliases[key], key, "same")
        st = self._acct.get(key)
        if st is not None and st.seen:                 # already this account
            return Resolution(key, key, "same")
        mine_number = number_key(account_number)
        for aid, s in self._acct.items():              # name overlaps another account?
            if not s.seen or s.kind != kind or aid == key:
                continue
            if not (s.names and names_overlap(names, s.names)):
                continue
            their_number = number_key(s.number)
            if mine_number and their_number and mine_number != their_number:
                continue                               # two numbers, two accounts
            if not mine_number and not their_number:
                mine_label, their_label = slug(account_ref), slug(s.name)
                if mine_label and their_label and mine_label != their_label:
                    continue                           # two products, two accounts
            who = s.name or aid
            return Resolution(
                key, key, "ambiguous", candidate=aid, candidate_name=who,
                reason=(f"a holder name matches {who}, and nothing stronger "
                        "tells them apart"))
        return Resolution(key, key, "new")

    def account_info(self, account: str) -> AccountInfo:
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)
        return AccountInfo(account=account, kind=st.kind, origin=st.origin,
                           currency=st.currency, name=st.name,
                           institution=st.institution, number=st.number,
                           names=list(st.names), jurisdiction=st.jurisdiction,
                           opened_at=st.opened_at)

    def document_types_of(self, account: str) -> set:
        """The canonical doc types of every document that has spoken about this
        account. The strongest evidence there is for what KIND of thing it is:
        an issuer produced a card statement for it, so it is a card."""
        st = self._acct.get(account)
        if st is None or not st.doc_ids:
            return set()
        from ..ingest.registry import profile_for
        # The store itself, not a copy: this is called once per account.
        seen = self._captured
        out = set()
        for did in st.doc_ids:
            profile = profile_for(seen.get(did, ""))
            if profile is not None:
                out.add(profile.doc_type)
        return out

    def account_infos(self) -> list[AccountInfo]:
        return [self.account_info(a) for a in self.accounts()]

    def transactions(self, account: str) -> list[TxnLine]:
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)
        # Sorted by value-time date: the log is append-only in knowledge-time,
        # so a backfilled older statement lands last, but a person reads a
        # statement chronologically.
        return sorted(st.lines, key=lambda ln: ln.date)

    def balance(self, account: str) -> BalanceAnswer:
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)

        # No attested closing: the balance is a bare replayed sum.
        if st.closing is None:
            ans = BalanceAnswer(
                account=account, amount=self._effective(st), grade=UNVERIFIED,
                as_of=self.as_of, provenance=st.opening_prov, reconciliation=None,
                explanation=("Computed by replaying opening balance and "
                             "transactions; no closing figure was attested to "
                             "check it against."))
        # Closing attested but no opening to reconcile from: a lone snapshot.
        elif st.opening is None:
            ans = BalanceAnswer(
                account=account, amount=st.closing, grade=VERIFIED,
                as_of=self.as_of, provenance=st.closing_prov, reconciliation=None,
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
                    as_of=self.as_of, provenance=st.closing_prov,
                    reconciliation=recon,
                    explanation=f"Attested closing balance, {note}.")
            else:
                ans = BalanceAnswer(
                    account=account, amount=st.closing, grade=CONFLICTED,
                    as_of=self.as_of, provenance=st.closing_prov,
                    reconciliation=recon,
                    explanation=("The attested closing balance and the "
                                 f"transactions disagree: {recon.explain()}. "
                                 "Surfaced, not averaged."))
        ans.currency = st.currency
        ans.dated = st.closing_date or st.opening_date
        return ans

    # ------------------------------------------------------------ positions

    def snapshot_positions(self, st, as_of: str = "") -> dict:
        """An account's holdings from its LATEST statement at or before `as_of`
        (all statements when `as_of` is empty), as `{instrument: observation}`.
        Cash rows are excluded.

        A brokerage statement states everything the account holds on its date,
        so the holdings are one snapshot rather than a composition across
        statements: an instrument the newest statement does not list is no
        longer held, and composing would also let one instrument written two
        ways count twice."""
        obs = [(name, ob) for name, history in st.position_history.items()
               for ob in history
               if ob.get("as_of") and (not as_of or ob["as_of"] <= as_of)
               and not ob.get("is_cash")]
        if not obs:
            return {}
        newest = max(ob["as_of"] for _n, ob in obs)
        return {name: ob for name, ob in obs if ob["as_of"] == newest}

    def positions(self, account: str | None = None) -> list[PositionRecord]:
        """Measured holdings from each account's latest statement, one snapshot
        per account, or from `account` alone if given. Each is a dated
        measurement carrying its as-of date and grade, never a current price."""
        out: list[PositionRecord] = []
        for acct, st in self._acct.items():
            if account is not None and acct != account:
                continue
            for instrument, p in sorted(self.snapshot_positions(st).items()):
                out.append(PositionRecord(
                    account=acct, instrument=instrument, units=p["units"],
                    market_value=p["market_value"], currency=p["currency"],
                    as_of=p["as_of"], cost_basis=p["cost_basis"],
                    valuation_class=p["valuation_class"], grade=p["grade"],
                    provenance=p["provenance"]))
        return out

    def holdings_value(self, account: str) -> Decimal:
        """Σ market value of an account's latest statement's holdings (no cash)."""
        st = self._acct.get(account)
        if st is None:
            return Decimal("0")
        return sum((p["market_value"] for p in self.snapshot_positions(st).values()),
                   start=Decimal("0"))

    def cash_value(self, account: str) -> Decimal:
        """An account's cash: its observed closing balance, or its replayed sum
        when none was attested, plus any cash/sweep line an older read misfiled
        as a "position". Raises UnknownAccountError on an unseen account."""
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)
        base = self._effective(st) if st.closing is None else st.closing
        return base + sum((p["market_value"] for p in st.position_cash.values()),
                          start=Decimal("0"))

    def holdings_as_of(self, account: str) -> tuple[str, bool]:
        """`(as_of, mixed)` for an account's composed value: the OLDEST
        measurement the figure rests on, and whether the parts it sums were
        measured on different dates. `("", False)` when nothing was measured.

        A cash measurement from one month can sit beside holdings from the next,
        so the composed figure is only good as of the oldest of them."""
        st = self._acct.get(account)
        measured = (list(st.positions.values()) + list(st.position_cash.values())
                    if st else [])
        dates = {p["as_of"] for p in measured if p["as_of"]}
        if st is not None and st.closing_date:
            dates.add(st.closing_date)
        if not dates:
            return "", False
        return min(dates), len(dates) > 1

    def account_value(self, account: str) -> Decimal:
        """An account's total value: for an investment account, cash plus Σ of
        the latest position market values; for any other, its balance.

        Pair with ``holdings_as_of``, which reports the date the composed figure
        is good as of and whether its parts were measured on different dates."""
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)
        if st.kind == "investment":
            return self.cash_value(account) + self.holdings_value(account)
        return self.balance(account).amount

    def unrealized_gain(self, account: str | None = None) -> Decimal | None:
        """The derived paper gain over held positions (Σ market_value − Σ cost
        basis) as of the latest measurements, for one account or all of them.
        A read-side view, never a ledger fact. None when no position carries a
        cost basis to compare."""
        total = Decimal("0")
        any_basis = False
        for p in self.positions(account):
            if p.cost_basis is not None:
                any_basis = True
                total += p.market_value - p.cost_basis
        return total if any_basis else None
