"""The event fold: replay events into per-account state and the overlays.

`ProjectionCore` owns every piece of projection state — account states, the
ingest read-model, the transfer/category/tag/ruling overlays, the merchant
catalog, and the memoized caches the read modules share. It decides nothing
about what the state *means*; the view modules in this package do, each over
the same core so a cache filled by one read serves the next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from ..events import (SCOPE_ACCOUNT, SCOPE_ATTRIBUTE, SCOPE_CATEGORY,
                      SCOPE_MERCHANT, SCOPE_TAG, CORROBORATED, ISSUED,
                      UNVERIFIED, VERIFIED, Event, Provenance, postings_of)
from ..postings import EQUITY_OPENING


class UnknownAccountError(KeyError):
    """Asked for a balance on an account the ledger has never seen. Raised
    rather than answered with zero; the answer path turns it into a refusal."""


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


class ProjectionCore:
    """Fold events into state the read modules share.

    Built once and updated incrementally via ``apply``; the `Ledger` facade
    keeps one live instance so reads never re-replay the whole encrypted log.

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
        self._replies: dict[str, str] = {}      # doc_id -> latest extract reply
        # What the ledger posted for a document's closing, which is the
        # corrected figure when a person ruled on one. The reply is what the
        # model read; this is what was accepted.
        self._doc_closing: dict[str, tuple] = {}
        # The per-account statement register, derived from those replies on
        # first ask and dropped whenever a new reading arrives.
        self._statements: dict | None = None
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
        # The statement register is derived from this fold. Any event may change
        # it, so it is dropped on every one rather than on a chosen few — the
        # chosen few is what let a corrected statement leave a stale register
        # behind while a fresh replay of the same log disagreed.
        self._statements = None
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

        elif et == "ReadRecorded":
            # The reply a model gave for a document, kept verbatim so a reader
            # above this layer can recover what the document declared about
            # itself. Later replies win, so a document re-read after a prompt
            # change is described by the newer reading. Text only: this layer
            # parses nothing and knows no document format.
            if (event.body.get("phase", "extract") == "extract"
                    and event.body.get("parse_ok")):
                doc = event.body.get("doc_id", "")
                if doc:
                    self._replies[doc] = event.body.get("response_text", "")

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
                self._posted.add(did)
                # What was accepted for this document, which is the corrected
                # figure when a person ruled on one.
                self._doc_closing[did] = (event.body["amount"],
                                          event.occurred_at)
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
            from ...ingest.brokerage import is_cash_row
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
