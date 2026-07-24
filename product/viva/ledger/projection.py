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
from .identity import account_key, names_overlap
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


def movement_key(doc_id: str, account: str, date: str, amount: Decimal | str,
                 description: str, occurrence: int = 0) -> str:
    """A stable reference to one posted movement, for transfer links (Slice 3).

    Anchored to content — document, account, date, amount, description — plus an
    occurrence index that disambiguates identical siblings in the same document.
    It survives a reingest (which mints new event ids) because it depends on what
    was read, not on the event's identity. `occurrence` is assigned by the
    projection's canonical enumeration so the same movement always keys the same."""
    return f"{doc_id}|{account}|{date}|{amount}|{description}|{occurrence}"


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
            if st.kind not in ("depository", "liability"):
                continue
            for ln in sorted(st.lines, key=lambda l: (l.date, l.description, str(l.amount))):
                did = ln.provenance.doc_id
                sig = (did, account, ln.date, str(ln.amount), ln.description)
                occ = counts.get(sig, 0)
                counts[sig] = occ + 1
                key = movement_key(did, account, ln.date, ln.amount,
                                   ln.description, occ)
                out.append(MovementInfo(
                    key=key, account=account, kind=st.kind, date=ln.date,
                    amount=ln.amount, description=ln.description,
                    currency=st.currency, provenance=ln.provenance,
                    linked=key in linked))
        return out

    def transfer_suggestions(self) -> list[dict]:
        """Pending transfer suggestions awaiting a human ruling (not yet linked)."""
        return list(self._transfer_suggestions.values())

    def transfer_links(self) -> list[dict]:
        """Live transfer links (the recognized internal transfers), with grade."""
        return [{"a": min(p), "b": max(p), **info}
                for p, info in self._links.items()
                if info.get("status") == "linked"]

    def spending_by_currency(self) -> dict[str, Decimal]:
        """Minimal external-spending seed (S5 builds the real one): money that
        left an asset account to the outside world — i.e. depository outflows,
        **excluding** movements that are part of a transfer (moving your own
        money is not spending). Positive magnitudes, per currency."""
        linked = self.linked_keys()
        out: dict[str, Decimal] = {}
        for m in self.movements():
            if m.kind != "depository" or m.amount >= 0 or m.key in linked:
                continue
            out[m.currency] = out.get(m.currency, Decimal("0")) + (-m.amount)
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
