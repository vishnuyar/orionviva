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
                     Provenance, postings_of)
from .identity import account_key, account_tokens, names_overlap
from .merchants import normalize_merchant
from .postings import EQUITY_OPENING, INCOME_UNCATEGORIZED


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


@dataclass
class PositionRecord:
    """One holding measured at a date (Slice 6). A measurement, not a posting —
    unrealized gain is DERIVED here, as-of-date, never a stored/ledger fact (M1)."""
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
        """market_value − cost_basis, or None when cost basis is unknown. Computed
        on demand (presentation view), never posted or reconciled."""
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
    """A stable reference to one posted movement, for transfer links (Slice 3).

    Anchored to content — document, account, date, amount, description — plus an
    occurrence index that disambiguates identical siblings in the same document.
    It survives a reingest (which mints new event ids) because it depends on what
    was read, not on the event's identity. `occurrence` is assigned by the
    projection's canonical enumeration so the same movement always keys the same."""
    return f"{doc_id}|{account}|{date}|{amount}|{description}|{occurrence}"


# --------------------------------------------------------- movement nature (S6.5)

# What a movement *is*, economically — the distinction that makes "spending" mean
# money that left your LIFE, not money that left an ACCOUNT (M1). Derived, never
# stored: a projection over events we already write (T4), so it is retroactive for
# free and costs no re-ingest.
SPENDING = "spending"        # real external outflow — the only thing aggregates count
TRANSFER = "transfer"        # the money is still yours (own card, own brokerage, ...)
SETTLEMENT = "settlement"    # a person's ruling: repaid a loan, was paid back, ...

# How a nature was decided, strongest first. Carried on the movement so a figure
# can explain itself (T1) and so the surface can show WHY something was excluded.
BY_LINK = "linked"                   # rung 1: a live TransferLinked (decisive)
BY_OWN_ACCOUNT = "own_account"       # rung 2: names an account you hold
BY_RULING = "ruling"                 # rung 3: a human said so
BY_CATEGORY = "category_hint"        # rung 4: category/subcategory SUGGESTS it
BY_DEFAULT = "default"               # rung 5: nothing said otherwise

# Category/subcategory labels that merely *suggest* a non-spending nature. They
# never decide alone: the real-vault run showed one category (`loan_payments`)
# covering opposite natures — a mortgage payment (real outflow) and a payment to
# your own card (internal). A movement resting only on this rung stays counted and
# is flagged PROVISIONAL, so the number is honest about its own uncertainty (X2).
_TRANSFER_HINT_CATEGORIES = frozenset({"transfers"})
_TRANSFER_HINT_SUBCATEGORIES = frozenset({
    "credit card payment", "card payment", "investment", "transfer",
    "internal transfer", "brokerage", "atm", "cash withdrawal"})


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
    # Slice 6.5 — derived, with the rung that decided it. `provisional` means the
    # nature rests only on a category hint (or the default), so the figure is
    # counted but its uncertainty is reported rather than hidden.
    nature: str = SPENDING
    nature_reason: str = BY_DEFAULT
    provisional: bool = False


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
    closing_confirmed: bool = False            # a human attested the closing
    lines: list = field(default_factory=list)  # TxnLine per posting on this account
    # Holdings (Slice 6): instrument -> latest PositionObserved measurement (by
    # as_of). Measurements, not postings — they never touch `balance`.
    positions: dict = field(default_factory=dict)
    # Cash/sweep lines that were recorded as "positions" before we recognized them
    # (Slice 6 fix). Kept apart so an existing vault reads correctly with no
    # re-ingest: they compose into the account's cash, never its holdings.
    position_cash: dict = field(default_factory=dict)


class LedgerProjection:
    """Replay events into per-account state, then answer balance queries.

    The read model for the whole ledger: per-account balances AND ingest state
    (what's captured, posted, held). Built once and updated incrementally via
    ``apply`` — the `Ledger` facade keeps one live instance so reads never
    re-replay the whole encrypted log.

    Opening Balance Equity is the *earliest known* opening (individual-as-
    enterprise.md): the injection is computed from ``st.opening`` at query time,
    not accumulated per opening — so a backfilled older statement simply re-seats
    the earliest opening, with no double-count and no event to reverse.
    """

    def __init__(self, events: Iterable[Event], as_of: str | None = None) -> None:
        self.as_of = as_of
        self._acct: dict[str, _AccountState] = {}
        # Ingest read-model, maintained incrementally alongside balances.
        self._captured: dict[str, str] = {}     # doc_id -> model's doc_type
        self._posted: set[str] = set()           # doc_ids with posting events
        self._held: dict[str, dict] = {}         # doc_id -> latest StatementHeld body
        self._aliases: dict[str, str] = {}       # learned: signal-key -> account_id
        # Transfer overlay (Slice 3): links between two movement keys, and
        # unresolved suggestions awaiting a human ruling. Links are ledger-wide,
        # not per-account (a transfer spans two accounts).
        self._links: dict[frozenset, dict] = {}         # {a,b} -> {status,grade,by}
        self._transfer_suggestions: dict[str, dict] = {}  # movement key -> body
        # Category overlay (Slice 5): movement key -> {category, grade, by,
        # descriptor}. A human confirmation (verified) supersedes a model
        # suggestion (unverified); we keep the highest-trust ruling.
        self._categories: dict[str, dict] = {}
        # Merchant catalog (Slice 5.5): normalized merchant -> {category, grade,
        # by}. The prior a transaction's category derives from when it has no
        # per-movement override. Highest-trust ruling wins.
        self._merchant_categories: dict[str, dict] = {}
        # Own-account token index (Slice 6.5), built lazily and invalidated when a
        # new account is opened — used to recognize an internal movement even when
        # no transfer link was formed.
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
            self._own_tokens_cache = None      # a new account changes the index

        elif et == "OpeningBalanceObserved":
            acct = event.body["account_id"]
            amount = Decimal(event.body["amount"])
            st = self._state(acct)
            st.seen = True
            if did:
                self._posted.add(did)
            # The Opening Balance Equity is the EARLIEST known opening: keep the
            # earliest, and inject it once at query time (never accumulate each
            # opening, so a backfilled older statement re-seats it cleanly).
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
            self._links[pair] = {"status": "linked", "grade": event.body.get("grade", ""),
                                 "by": event.body.get("by", "")}
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

        elif et in ("MerchantCategorized", "MerchantEnriched"):
            merchant = event.body["merchant"]
            prior = self._merchant_categories.get(merchant)
            # Keep the highest-trust ruling; a later equal-or-higher grade wins.
            # MerchantCategorized (human/category-only) and MerchantEnriched (the
            # richer package-synced record) share this catalog.
            if prior is None or _grade_rank(event.body.get("grade")) >= _grade_rank(prior.get("grade")):
                self._merchant_categories[merchant] = event.body

        elif et == "ClosingBalanceObserved":
            acct = event.body["account_id"]
            st = self._state(acct)
            st.seen = True
            if did:
                self._posted.add(did)
            # Across stitched months the latest-dated closing is the current
            # balance to answer with; earlier closings were true when written.
            if st.closing is None or event.occurred_at >= st.closing_date:
                st.closing = Decimal(event.body["amount"])
                st.closing_date = event.occurred_at
                st.closing_prov = event.provenance
                st.closing_confirmed = event.body.get("confirmed_by") == "human"

        elif et == "PositionObserved":
            acct = event.body["account_id"]
            st = self._state(acct)
            st.seen = True
            if did:
                self._posted.add(did)
            instrument = event.body["instrument"]
            # A cash/sweep line misfiled as a holding by an older read is cash, not
            # a position. Reinterpreting it HERE (rather than only at ingest) makes
            # an existing vault correct on the next query — no re-ingest, no model
            # cost, nothing rewritten. The ingest-side fold stops new ones arriving.
            from ..ingest.brokerage import is_cash_row
            bucket = st.position_cash if is_cash_row(instrument) else st.positions
            prior = bucket.get(instrument)
            # Keep the latest measurement by value-time (as_of); an earlier one was
            # true when written. Append-only: a revaluation is a new observation.
            if prior is None or event.occurred_at >= prior.get("as_of", ""):
                cb = event.body.get("cost_basis", "")
                bucket[instrument] = {
                    "units": Decimal(event.body["units"]),
                    "market_value": Decimal(event.body["market_value"]),
                    "currency": event.body.get("currency", ""),
                    "as_of": event.occurred_at,
                    "cost_basis": Decimal(cb) if cb not in (None, "") else None,
                    "valuation_class": event.body.get("valuation_class", "measured"),
                    "grade": event.body.get("grade", ""),
                    "provenance": event.provenance}

        elif et == "TransactionRecorded":
            if did:
                self._posted.add(did)
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
        """True once an opening balance has been booked — i.e. the account's
        history has a starting point and later statements continue from it rather
        than re-seeding it."""
        st = self._acct.get(account)
        return bool(st and st.opening is not None)

    @staticmethod
    def _effective(st: _AccountState) -> Decimal:
        """Account balance = earliest opening (the OBE injection) + transaction
        postings. The opening is injected here, once, from the earliest known
        opening — never accumulated per opening event."""
        return (st.opening or Decimal("0")) + st.balance

    def running_balance(self, account: str) -> Decimal | None:
        """The replayed balance, or None if the account is unseen. Used by ingest
        to check that a new statement's opening continues from where we left off."""
        st = self._acct.get(account)
        return self._effective(st) if (st and st.seen) else None

    def earliest_opening(self, account: str) -> Decimal | None:
        """The account's earliest known opening — the balance a still-older
        statement must *close* at to backfill in front of the chain."""
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

    # ------------------------------------------------------- transfers (Slice 3)

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
        its stable transfer key. Occurrence indices are assigned here, once, so
        the matcher and the projection agree on every key. Uncategorized
        counter-legs are excluded — they are not transfer candidates."""
        linked = self.linked_keys()
        out: list[MovementInfo] = []
        counts: dict[tuple, int] = {}
        for account in self.accounts():
            st = self._acct[account]
            # depository/liability movements, plus an investment account's cash
            # activity (Slice 6 Stage 2) — so a contribution into a brokerage ties
            # to the funding account as a transfer.
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
        """Distinctive tokens for every account we hold, so a movement naming one
        of them can be recognized as internal even when no link was formed."""
        if self._own_tokens_cache is None:
            self._own_tokens_cache = {
                a: account_tokens(s.institution, s.number, s.name)
                for a, s in self._acct.items()
                if s.seen and s.kind in ("depository", "liability", "investment")}
        return self._own_tokens_cache

    def _decide_nature(self, m: "MovementInfo") -> None:
        """Decide what a movement IS, strongest evidence first (Slice 6.5).

        1. linked            — a live TransferLink. Decisive.
        2. own account       — the description distinctively names another account
                               you hold (a card payment whose counterpart statement
                               was never ingested still isn't spending).
        3. a human ruling    — you said what this is.
        4. category hint     — SUGGESTS internal; counted but marked provisional,
                               because one category can cover opposite natures.
        5. default           — spending.
        """
        if m.linked:
            m.nature, m.nature_reason = TRANSFER, BY_LINK
            return
        # Rung 2: does this movement name one of YOUR OTHER accounts?
        low = (m.description or "").lower()
        for account, tokens in self._own_account_tokens().items():
            if account == m.account:
                continue                      # naming itself proves nothing
            if tokens and any(tok in low for tok in tokens):
                m.nature, m.nature_reason = TRANSFER, BY_OWN_ACCOUNT
                return
        # Rung 3: a person's explicit ruling — on this movement (the category
        # overlay's body) or on its MERCHANT (the enrichment attributes bag, so a
        # ruling settles every transaction from that counterparty, past and
        # future). Neither needed a new event type; Move 3 is where a generic
        # Ruling would go, if a fifth question type ever earns it.
        nature = (self._categories.get(m.key) or {}).get("nature")
        if nature not in (TRANSFER, SETTLEMENT, SPENDING):
            merchant = self._merchant_categories.get(normalize_merchant(m.description)) or {}
            nature = (merchant.get("attributes") or {}).get("nature")
        if nature in (TRANSFER, SETTLEMENT, SPENDING):
            m.nature, m.nature_reason = nature, BY_RULING
            return
        # Rung 4: the category/subcategory only SUGGESTS — provisional, never silent.
        derived = self.derived_category(m) or {}
        cat = (derived.get("category") or "").strip().lower()
        sub = (derived.get("subcategory") or "").strip().lower()
        if cat in _TRANSFER_HINT_CATEGORIES or sub in _TRANSFER_HINT_SUBCATEGORIES:
            m.nature, m.nature_reason = TRANSFER, BY_CATEGORY
            m.provisional = True
            return
        m.nature, m.nature_reason, m.provisional = SPENDING, BY_DEFAULT, False

    def transfer_suggestions(self) -> list[dict]:
        """Pending transfer suggestions awaiting a human ruling — with the source
        not yet linked (a suggestion whose money was since confirmed elsewhere is
        no longer a question)."""
        linked = self.linked_keys()
        return [s for s in self._transfer_suggestions.values()
                if s["a"] not in linked]

    def transfer_links(self) -> list[dict]:
        """Live transfer links (the recognized internal transfers), with grade."""
        return [{"a": min(p), "b": max(p), **info}
                for p, info in self._links.items()
                if info.get("status") == "linked"]

    def income_by_currency(self) -> dict[str, Decimal]:
        """RECOGNIZED income (income we have actually attributed), per currency —
        the sum of `Income:*` accounts as a positive magnitude, **excluding the
        `Income:Uncategorized` placeholder**. Today the only attributed income is
        a decomposed pay stub (`Income:Salary` at gross, Slice 4).

        We deliberately do NOT report `Income:Uncategorized`: it is the undiffer-
        entiated inflow bucket, and — until categorization (Slice 5) makes the
        counter-leg *kind-aware* — it is also polluted, because a liability's
        counter-leg sign is inverted (a card purchase currently lands here as if
        it were income). Reporting it would be a number we can't stand behind
        (principle 2); attributed income is the honest figure.

        Income buckets carry no currency of their own; with exactly one account
        currency we attribute income to it, otherwise '?' (I1)."""
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
        """Minimal external-spending seed (superseded by spending_by_category):
        depository outflows, excluding non-spending natures (Slice 6.5). Positive
        magnitudes, per currency. Kept for back-compat; the category view is the
        real one."""
        out: dict[str, Decimal] = {}
        for m in self.movements():
            if m.kind != "depository" or m.amount >= 0 or m.nature != SPENDING:
                continue
            out[m.currency] = out.get(m.currency, Decimal("0")) + (-m.amount)
        return out

    # ------------------------------------------------------- categories (Slice 5)

    @staticmethod
    def _is_expense(m: "MovementInfo") -> bool:
        """A movement with the *shape* of spending: money out of an asset, or a
        charge on a liability (a card purchase). A card *payment* (liability,
        negative) is a transfer — the kind-aware distinction from Slice 5.

        Shape is necessary but not sufficient: what a movement *is* economically
        is its `nature` (Slice 6.5). ``_counts_as_spending`` applies both."""
        return ((m.kind == "depository" and m.amount < 0)
                or (m.kind == "liability" and m.amount > 0))

    def _counts_as_spending(self, m: "MovementInfo") -> bool:
        """Does this movement belong in a spending figure? It must have the shape
        of an expense AND have `spending` nature — money that left your LIFE, not
        merely an account (M1). This one predicate is what makes the headline
        honest: a card payment, a brokerage contribution, or a movement naming
        another account you hold is excluded whether or not a link was formed."""
        return self._is_expense(m) and m.nature == SPENDING

    def provisional_spending(self, currency: str | None = None) -> Decimal:
        """How much of the reported spending rests on *weak* evidence — movements
        excluded (or kept) only on a category hint. Surfaced alongside the total so
        the figure states its own uncertainty instead of hiding it (X2): 'I count
        X as spending; Y of that I'm not certain about.'"""
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
        not `spending` — with the rung that decided each. The audit trail for
        'why isn't this in my spending?'"""
        return [m for m in self.movements()
                if self._is_expense(m) and m.nature != SPENDING]

    def derived_category(self, m: "MovementInfo") -> dict | None:
        """A movement's effective category (Slice 5.5): a per-transaction override
        wins; else the merchant catalog (by normalized descriptor); else None.
        Returns the ruling dict ({category, grade, ...}) or None if unknown."""
        override = self._categories.get(m.key)
        if override is not None:
            return override
        return self._merchant_categories.get(normalize_merchant(m.description))

    def category_of(self, key: str) -> dict | None:
        """The per-transaction override ruling on a movement, or None (the raw
        overlay; ``derived_category`` resolves the merchant prior too)."""
        return self._categories.get(key)

    def merchant_categories(self) -> dict[str, dict]:
        """The merchant catalog: normalized merchant -> ruling (Slice 5.5)."""
        return dict(self._merchant_categories)

    def spending_by_category(self, currency: str | None = None) -> dict[str, Decimal]:
        """Real spending, grouped by category (Slice 5): every expense movement —
        card purchases included — **excluding transfers**, bucketed by its
        *derived* category (override → merchant catalog → ``Uncategorized``, per
        Slice 5.5). Positive magnitudes; ``currency`` filters if given.

        Slice 6.5: exclusion is by **nature**, not merely by link — so an internal
        movement that never linked (a card payment, a brokerage contribution) is
        no longer counted as consumption, and `transfers` can never appear as a
        line item inside spending."""
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
        """Finer spending slice (Slice 5.6): expense movements grouped by the
        merchant's model-provided **subcategory** ("streaming", "warehouse club"),
        falling back to the primary category, then ``Uncategorized``. The extra
        axis for slicing and dicing. Positive magnitudes; non-spending natures
        excluded (Slice 6.5)."""
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
        non-spending natures excluded (Slice 6.5) — we never ask you to categorize
        money that didn't leave your life."""
        return [m for m in self.movements()
                if self._counts_as_spending(m)
                and self.derived_category(m) is None]

    def uncategorized_merchants(self) -> dict[str, dict]:
        """Unknown merchants across the uncategorized expense queue, deduped by
        normalized key (Slice 5.5): {merchant -> {count, example, shareable}}.
        This is the batched categorizer's pending set and the surface's unit."""
        from .merchants import is_shareable
        out: dict[str, dict] = {}
        for m in self.uncategorized_expenses():
            key = normalize_merchant(m.description)
            if not key:
                continue
            row = out.setdefault(key, {"count": 0, "example": m.description,
                                       "shareable": is_shareable(m.description)})
            row["count"] += 1
        return out

    # ------------------------------------------------- identity resolution

    def resolve(self, institution: str, account_number: str, account_ref: str,
                names: list[str], kind: str = "depository") -> Resolution:
        """Resolve a statement's identity signals against known accounts:
        'same' (a learned alias or an account with this key), 'new', or
        'ambiguous' (a holder name matches an existing account *of the same kind*
        but the number differs — ask the person once, then learn it).

        The ambiguity is scoped to the same account ``kind``: a card and a
        checking account sharing a holder are simply two different accounts, not
        the same account under two labels — only a like-kind name clash is
        genuinely ambiguous."""
        key = account_key(institution, account_number, account_ref)
        if key in self._aliases:                       # learned
            return Resolution(self._aliases[key], key, "same")
        st = self._acct.get(key)
        if st is not None and st.seen:                 # already this account
            return Resolution(key, key, "same")
        for aid, s in self._acct.items():              # name overlaps another account?
            if not s.seen or s.kind != kind or aid == key:
                continue
            if s.names and names_overlap(names, s.names):
                who = s.name or aid
                return Resolution(
                    key, key, "ambiguous", candidate=aid, candidate_name=who,
                    reason=(f"a holder name matches {who}, but the account "
                            "number is different"))
        return Resolution(key, key, "new")

    def account_info(self, account: str) -> AccountInfo:
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)
        return AccountInfo(account=account, kind=st.kind,
                           currency=st.currency, name=st.name,
                           institution=st.institution, number=st.number,
                           names=list(st.names))

    def account_infos(self) -> list[AccountInfo]:
        return [self.account_info(a) for a in self.accounts()]

    def transactions(self, account: str) -> list[TxnLine]:
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)
        # Sorted by value-time date: the log is append-only in knowledge-time
        # (a backfilled older statement lands last), but a person reads a
        # statement chronologically. Bitemporality made visible.
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
                # A human who ruled on the figure is our highest attestation.
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

    # ------------------------------------------------- positions (Slice 6)

    def positions(self, account: str | None = None) -> list[PositionRecord]:
        """Latest measured holdings, across investment accounts (or one). Each is a
        dated measurement (`class=measured`), carrying its as-of date and grade —
        never presented as "current"."""
        out: list[PositionRecord] = []
        for acct, st in self._acct.items():
            if account is not None and acct != account:
                continue
            for instrument, p in sorted(st.positions.items()):
                out.append(PositionRecord(
                    account=acct, instrument=instrument, units=p["units"],
                    market_value=p["market_value"], currency=p["currency"],
                    as_of=p["as_of"], cost_basis=p["cost_basis"],
                    valuation_class=p["valuation_class"], grade=p["grade"],
                    provenance=p["provenance"]))
        return out

    def holdings_value(self, account: str) -> Decimal:
        """Σ market value of an account's latest measured positions (no cash)."""
        st = self._acct.get(account)
        if st is None:
            return Decimal("0")
        return sum((p["market_value"] for p in st.positions.values()),
                   start=Decimal("0"))

    def cash_value(self, account: str) -> Decimal:
        """An account's cash: its observed balance plus any cash/sweep line that an
        older read misfiled as a "position" (Slice 6 fix). This is what the person
        actually holds in cash, regardless of how the statement was read."""
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)
        base = self._effective(st) if st.closing is None else st.closing
        return base + sum((p["market_value"] for p in st.position_cash.values()),
                          start=Decimal("0"))

    def holdings_as_of(self, account: str) -> tuple[str, bool]:
        """The as-of date an account's composed value is honest at, and whether
        the measurements it sums were taken on DIFFERENT dates.

        A real run mixed a cash measurement from one month with holdings from the
        next and presented one total. Summing measurements of different vintages
        is exactly the stale-price dressing the valuation-class invariant exists to
        prevent — so the composed figure reports the OLDEST measurement it rests on
        (the date the whole number is truly good as of) and flags the mix, rather
        than quietly implying it is all current (Slice 6 fix, 2026-07-25)."""
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
        """An account's total value: for an investment account, cash (the observed
        balance) + Σ latest position market values; for any other, its balance.
        The composition an investment account's headline figure comes from.

        Pair with ``holdings_as_of`` to present it honestly: the figure is only
        good as of the OLDEST measurement it sums, and that call reports whether
        the parts were measured on different dates."""
        st = self._acct.get(account)
        if st is None or not st.seen:
            raise UnknownAccountError(account)
        if st.kind == "investment":
            return self.cash_value(account) + self.holdings_value(account)
        return self.balance(account).amount

    def unrealized_gain(self, account: str | None = None) -> Decimal | None:
        """The derived paper gain over held positions (Σ market_value − Σ cost
        basis), as-of the latest measurements — a PRESENTATION view (M1), never a
        ledger fact. None when no position carries a cost basis to compare."""
        total = Decimal("0")
        any_basis = False
        for p in self.positions(account):
            if p.cost_basis is not None:
                any_basis = True
                total += p.market_value - p.cost_basis
        return total if any_basis else None
