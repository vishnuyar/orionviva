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

from merchantcore.taxonomy import subcategory_identity

from ..events import (SCOPE_ACCOUNT, SCOPE_ATTRIBUTE, SCOPE_CATEGORY,
                      SCOPE_MERCHANT, SCOPE_TAG, CORROBORATED, ISSUED,
                      UNVERIFIED, VERIFIED, Event, Provenance, postings_of)
from ..identity import usable_full_number
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
    # Currency belongs to the real account leg that gave this posting meaning.
    # Counter accounts (Income:*, Expenses:*) do not have independent account
    # metadata, so the transaction fold carries the sole real-leg currency onto
    # every line. Empty means the transaction could not be attributed to one
    # currency and must never be relabelled by a read.
    currency: str = ""

    def to_dict(self) -> dict:
        return {"date": self.date, "description": self.description,
                "amount": str(self.amount), "grade": self.grade,
                "currency": self.currency,
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
        # What the file was called where it came from, kept beside the type so a
        # document can be listed under a name its owner recognises rather than
        # under the address its own bytes decide.
        self._captured_names: dict[str, str] = {}   # doc_id -> filename
        self._replies: dict[str, str] = {}      # doc_id -> latest extract reply
        # Every document some model was asked about at all, whether or not the
        # reply parsed. A document in this set was read; one outside it was
        # never read, and the two are different things to tell a person.
        self._read_attempted: set[str] = set()  # doc_ids with any ReadRecorded
        # And those whose reading declared itself usable. The reading says so
        # about itself; whether anything was later done with it is a different
        # fact, recorded elsewhere and never read as this one.
        self._read_parsed: set[str] = set()     # doc_ids whose extract parsed
        # What the ledger posted for a document's closing, which is the
        # corrected figure when a person ruled on one. The reply is what the
        # model read; this is what was accepted.
        self._doc_closing: dict[str, tuple] = {}
        # The per-account statement register, derived from those replies on
        # first ask and dropped whenever a new reading arrives.
        self._statements: dict | None = None
        self._posted: set[str] = set()           # doc_ids with posting events
        # (account, period end) -> (doc_id, closing amount). A statement is
        # identified by whose account it is and the day its period ends; this is
        # what a second copy of one is recognised against.
        self._periods: dict[tuple[str, str], tuple[str, str]] = {}
        # Pay decompositions already on the ledger, as (description, pay date,
        # gross). A stub has no balance and no closing figure, so it is
        # recognised by the decomposition it would write.
        self._decomposed: set[tuple[str, str, str]] = set()
        self._held: dict[str, dict] = {}         # doc_id -> latest StatementHeld body
        # Brokerage holdings and activity have independent reconciliation
        # gates. A valid snapshot can post while these movements stay held.
        self._activity_held: dict[str, dict] = {}
        self._aliases: dict[str, str] = {}       # learned: signal-key -> account_id
        self._alias_evidence: dict[str, dict] = {}  # safe scope of new aliases
        # A person's ruling for one exact document. Unlike a lossy signal alias,
        # this can safely choose among several accounts sharing the same last four.
        self._document_account_aliases: dict[str, str] = {}
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
        # The same category folds, keyed and valued by subcategory identity, so
        # a ruling recorded against one spelling reaches every spelling the
        # separator fold declares the same. Built here rather than folded per
        # lookup: `derived_category` reads it once per movement.
        self._subcategory_alias_map: dict[str, str] = {}
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
        # Durable turns in arrival order and proposals with immutable input data.
        self._conversation_turns: list[dict] = []
        self._conversation_turn_index: dict[str, int] = {}
        self._conversation_proposals: dict[str, dict] = {}
        # Save-up goals preserve complete term snapshots and every reservation
        # movement. Desired targets never become money merely by existing.
        self._goals: dict[str, dict] = {}
        self._goal_proposals: dict[str, dict] = {}
        # Findings set aside at the exact evidence stake a person saw. The
        # finding projection compares it to the live stake and uses no clock.
        self._finding_set_asides: dict[str, dict] = {}
        self._agent_log: list[dict] = []
        # Own-account token index, built lazily and invalidated when a new
        # account is opened. Recognizes an internal movement when no transfer
        # link was formed.
        self._own_tokens_cache: dict[str, set[str]] | None = None
        for event in events:
            self.apply(event)

    def apply(self, event: Event) -> None:
        """Fold one event into the projection (respecting an as_of horizon)."""
        # The statement register is derived from this fold, so any event may
        # change it and every event drops it.
        self._statements = None
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

        elif et == "AccountIdentityObserved":
            account = event.body["account_id"]
            st = self._state(account)
            observed_number = event.body.get("account_number", "")
            # Only genuine full-number evidence can strengthen the stored
            # identity. A mask exposing many digits is still partial evidence.
            if (usable_full_number(observed_number)
                    and not usable_full_number(st.number)):
                st.number = observed_number
            st.institution = st.institution or event.body.get("institution", "")
            for name in event.body.get("account_names", []):
                if name and name not in st.names:
                    st.names.append(name)
            if did:
                st.doc_ids.add(did)
            self._own_tokens_cache = None
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
            self._captured_names[event.body["doc_id"]] = event.body.get(
                "filename", "")

        elif et == "ReadRecorded":
            # The reply a model gave for a document, kept verbatim so a reader
            # above this layer can recover what the document declared about
            # itself. Later replies win, so a document re-read after a prompt
            # change is described by the newer reading. Text only: this layer
            # parses nothing and knows no document format.
            doc = event.body.get("doc_id", "")
            if doc:
                # That a model was asked is recorded for every phase and
                # whatever came back; what it said is kept only where the
                # extract pass parsed. A read that yielded nothing happened.
                self._read_attempted.add(doc)
                if (event.body.get("phase", "extract") == "extract"
                        and event.body.get("parse_ok")):
                    self._read_parsed.add(doc)
                    self._replies[doc] = event.body.get("response_text", "")

        elif et == "StatementHeld":
            # Legacy activity-reason holds map to the independent activity gate.
            if event.body.get("reason") == "activity":
                self._activity_held[event.body["doc_id"]] = event.body
            else:
                self._held[event.body["doc_id"]] = event.body

        elif et == "BrokerageActivityHeld":
            self._activity_held[event.body["doc_id"]] = event.body

        elif et == "BrokerageActivityResolved":
            self._activity_held.pop(event.body["doc_id"], None)

        elif et == "AccountAliasConfirmed":
            if event.body.get("learn_signal", True):
                alias = event.body["alias_key"]
                self._aliases[alias] = event.body["account_id"]
                # Absence means a legacy event whose historical broad replay
                # must remain readable. New events carry all three keys.
                if any(key in event.body for key in
                       ("match_names", "match_label", "kind")):
                    self._alias_evidence[alias] = {
                        "names": list(event.body.get("match_names") or []),
                        "label": event.body.get("match_label", ""),
                        "kind": event.body.get("kind", ""),
                    }
                else:
                    self._alias_evidence.pop(alias, None)
            doc = event.body.get("doc_id", "")
            if doc:
                self._document_account_aliases[doc] = event.body["account_id"]

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
                if scope == SCOPE_CATEGORY:
                    raw_subject = event.body["subject"]
                    raw_same_as = event.body["same_as"]
                    subject = subcategory_identity(raw_subject)
                    same_as = subcategory_identity(raw_same_as)
                    # A fold whose two sides share one identity is already
                    # folded, and would be a step from a label to itself.
                    if subject and same_as and subject != same_as:
                        # Preserve the raw historical spellings here.  Alias
                        # resolution normalizes the complete graph at once so
                        # two raw keys with one identity and different targets
                        # remain a detectable collision rather than silently
                        # overwriting each other during projection replay.
                        self._subcategory_alias_map[raw_subject] = raw_same_as

        elif et == "QuestionDeclined":
            # Last decline wins; a question re-declined after returning simply
            # updates its snapshot to the new stake.
            # The event id travels with the snapshot: a read reporting the
            # agent's own behaviour cites the record that made it true, the way
            # a read about money cites a document.
            self._declined[event.body["question_id"]] = {
                **event.body, "event_id": event.event_id}

        elif et == "ConversationTurnOpened":
            turn_id = event.body.get("turn_id", "")
            if turn_id and turn_id not in self._conversation_turn_index:
                self._conversation_turn_index[turn_id] = len(
                    self._conversation_turns)
                self._conversation_turns.append({
                    **event.body, "occurred_at": event.occurred_at,
                    "event_id": event.event_id, "outcome": "stale",
                    "message": "", "reason": "interrupted",
                    "answer": {}, "proposal_id": ""})

        elif et == "ConversationTurnSettled":
            turn_id = event.body.get("turn_id", "")
            index = self._conversation_turn_index.get(turn_id)
            if index is not None:
                self._conversation_turns[index].update({
                    "outcome": event.body.get("outcome", ""),
                    "message": event.body.get("message", ""),
                    "reason": event.body.get("reason", ""),
                    "answer": dict(event.body.get("answer") or {}),
                    "proposal_id": event.body.get("proposal_id", ""),
                    "settled_event_id": event.event_id})

        elif et == "ConversationProposalRecorded":
            proposal_id = event.body.get("proposal_id", "")
            if proposal_id and proposal_id not in self._conversation_proposals:
                self._conversation_proposals[proposal_id] = {
                    **event.body, "occurred_at": event.occurred_at,
                    "event_id": event.event_id, "status": "open",
                    "outcome": "proposal", "message": "", "reason": ""}

        elif et == "ConversationProposalResolved":
            proposal_id = event.body.get("proposal_id", "")
            proposal = self._conversation_proposals.get(proposal_id)
            if proposal is not None and proposal.get("status") == "open":
                proposal.update({
                    "status": "resolved",
                    "resolution_turn_id": event.body.get("turn_id", ""),
                    "outcome": event.body.get("outcome", ""),
                    "message": event.body.get("message", ""),
                    "reason": event.body.get("reason", ""),
                    "resolved_event_id": event.event_id})

        elif et == "GoalCreated":
            goal_id = event.body.get("goal_id", "")
            if goal_id and goal_id not in self._goals:
                self._goals[goal_id] = {
                    **event.body, "state": "active",
                    "created_at": event.occurred_at,
                    "updated_at": event.occurred_at,
                    "event_ids": [event.event_id],
                    "reservations": {}, "reservation_history": [],
                    "issues": []}

        elif et == "GoalTermsChanged":
            goal_id = event.body.get("goal_id", "")
            goal = self._goals.get(goal_id)
            if goal is not None:
                for key in ("kind", "title", "currency", "target_amount",
                            "target_date", "monthly_contribution",
                            "contribution_day", "proposal_id"):
                    goal[key] = event.body.get(key, "")
                goal["updated_at"] = event.occurred_at
                goal["event_ids"].append(event.event_id)

        elif et in ("GoalFundsReserved", "GoalFundsReleased"):
            goal_id = event.body.get("goal_id", "")
            goal = self._goals.get(goal_id)
            if goal is not None:
                account_id = event.body.get("account_id", "")
                amount = Decimal(event.body.get("amount", "0"))
                direction = Decimal("1") if et == "GoalFundsReserved" else Decimal("-1")
                before = goal["reservations"].get(account_id, Decimal("0"))
                applied = amount
                if direction < 0 and amount > before:
                    applied = max(before, Decimal("0"))
                    goal["issues"].append(
                        f"release_exceeds_reserved:{account_id}:{event.event_id}")
                goal["reservations"][account_id] = max(
                    before + direction * applied, Decimal("0"))
                goal["reservation_history"].append({
                    **event.body, "kind": "reserved" if direction > 0 else "released",
                    "applied_amount": str(applied),
                    "valid": applied == amount,
                    "occurred_at": event.occurred_at,
                    "event_id": event.event_id})
                goal["updated_at"] = event.occurred_at
                goal["event_ids"].append(event.event_id)

        elif et == "GoalStateChanged":
            goal_id = event.body.get("goal_id", "")
            goal = self._goals.get(goal_id)
            if goal is not None:
                goal["state"] = event.body.get("state", goal["state"])
                goal["proposal_id"] = event.body.get("proposal_id", "")
                goal["updated_at"] = event.occurred_at
                goal["event_ids"].append(event.event_id)

        elif et == "GoalProposalRecorded":
            proposal_id = event.body.get("proposal_id", "")
            if proposal_id and proposal_id not in self._goal_proposals:
                self._goal_proposals[proposal_id] = {
                    **event.body, "occurred_at": event.occurred_at,
                    "event_id": event.event_id, "status": "open",
                    "outcome": "proposal", "reason": ""}

        elif et == "GoalProposalResolved":
            proposal_id = event.body.get("proposal_id", "")
            proposal = self._goal_proposals.get(proposal_id)
            if proposal is not None and proposal.get("status") == "open":
                proposal.update({
                    "status": "resolved",
                    "outcome": event.body.get("outcome", ""),
                    "reason": event.body.get("reason", ""),
                    "resolved_event_id": event.event_id})

        elif et == "FindingSetAside":
            # Last decision wins. If a finding returns on changed evidence and
            # is set aside again, this replaces the old snapshot.
            self._finding_set_asides[event.body["finding_id"]] = {
                **event.body, "occurred_at": event.occurred_at,
                "event_id": event.event_id}

        elif et == "AgentActed":
            # Kept in arrival order and never collapsed, so the log answers both
            # "what is the latest attempt on this target?" (the cooldown) and
            # "what has the agent been doing?" (the journal).
            self._agent_log.append({**event.body,
                                    "occurred_at": event.occurred_at,
                                    "event_id": event.event_id})

        elif et in ("MerchantCategorized", "MerchantEnriched"):
            merchant = event.body["merchant"]
            prior = self._merchant_categories.get(merchant)
            # Keep the highest-trust record; a later equal-or-higher grade wins.
            # MerchantCategorized (category only) and MerchantEnriched (the
            # richer package-synced record) share this catalog.
            if prior is None or _grade_rank(event.body.get("grade")) >= _grade_rank(prior.get("grade")):
                applied = dict(event.body)
                aliases = set(applied.get("aliases") or ())
                if prior is not None:
                    aliases.update(prior.get("aliases") or ())
                if aliases:
                    applied["aliases"] = sorted(aliases)
                self._merchant_categories[merchant] = applied
                self._mkeys_of = {}
            elif event.body.get("aliases"):
                aliases = set(prior.get("aliases") or ())
                aliases.update(event.body["aliases"])
                if aliases != set(prior.get("aliases") or ()):
                    self._merchant_categories[merchant] = {
                        **prior, "aliases": sorted(aliases)}
                    self._mkeys_of = {}

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
                self._periods.setdefault((acct, event.occurred_at),
                                         (did, event.body["amount"]))
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
            postings = list(postings_of(event))
            # A normal transaction has one currency even though one of its
            # legs is a synthetic income/expense account. Infer it only from
            # already-declared account metadata; ambiguity remains empty.
            currencies = {
                self._acct[p.account].currency
                for p in postings
                if p.account in self._acct and self._acct[p.account].currency
            }
            transaction_currency = next(iter(currencies)) \
                if len(currencies) == 1 else ""
            if did:
                self._posted.add(did)
            for _p in postings:
                if _p.account == "Income:Salary":
                    self._decomposed.add((event.body.get("description", ""),
                                          event.occurred_at, str(-_p.amount)))
            # A new descriptor may resolve differently once the ACH corpus
            # grows, so the key map is dropped rather than extended.
            self._mkeys, self._mkeys_of = None, {}
            for p in postings:
                st = self._state(p.account)
                st.seen = True
                st.balance += p.amount           # transaction postings only (no OBE)
                st.lines.append(TxnLine(
                    date=event.occurred_at,
                    description=event.body.get("description", ""),
                    amount=p.amount, grade=p.grade,
                    provenance=event.provenance,
                    currency=st.currency or transaction_currency))
                # Period deltas exclude the opening seed (that's tracked apart),
                # so reconciliation is opening + period == closing.
                if p.account != EQUITY_OPENING:
                    st.period_deltas.append(p.amount)
