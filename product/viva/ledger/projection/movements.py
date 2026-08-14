"""Movements on real accounts: their stable keys, their economic nature, and
the transfer overlay that recognizes money moving between the person's own
accounts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..events import (MAJOR_ASSET, MAJOR_EXPENSE, MAJOR_INCOME,
                      MAJOR_LIABILITY, SCOPE_MOVEMENT, Provenance)
from . import accounts as accounts_view
from . import merchants as merchants_view
from .core import ProjectionCore, TxnLine, UnknownAccountError


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
BY_RULING = "ruling"                 # rung 2: a ruling said so
BY_OWN_ACCOUNT = "own_account"       # rung 3: names an account you hold
BY_CATEGORY = "category_hint"        # rung 4: what the counterparty implies
BY_DEFAULT = "default"               # rung 5: nothing said otherwise

# A movement resting only on rung 4 is flagged PROVISIONAL: one category
# (`loan_payments`) covers opposite natures — a mortgage payment is a real
# outflow, a payment to your own card is internal — so the figure reports its
# own uncertainty rather than deciding on that evidence alone.


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
    # rests only on a *suggested* implication: the suggestion is applied, so a
    # movement it moves off `spending` is EXCLUDED from the spending aggregates
    # and its amount is what `provisional_spending` reports — money removed on
    # weak evidence, not money counted with a caveat.
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


def leading_account(legs: list[dict]) -> str:
    for major in _LEG_PRIORITY:
        for leg in legs:
            if leg.get("major") == major and leg.get("account"):
                return leg["account"]
    return ""


# ------------------------------------------------------------------ transfers

def linked_keys(core: ProjectionCore) -> set[str]:
    """Movement keys that are part of a *live* transfer link (not unlinked)."""
    out: set[str] = set()
    for pair, info in core._links.items():
        if info.get("status") == "linked":
            out.update(pair)
    return out


def is_linked(core: ProjectionCore, key: str) -> bool:
    return key in linked_keys(core)


def transfer_suggestions(core: ProjectionCore) -> list[dict]:
    """Pending transfer suggestions awaiting a ruling.

    A suggestion is dropped when its source is now linked, or when every one
    of its candidates is — either way the money it asks about has been
    settled elsewhere and the question has no answer left to give.

    Filtered on the read side, never withdrawn by an event: unlink the pair
    that took the candidate and the question comes back."""
    linked = linked_keys(core)
    out = []
    for s in core._transfer_suggestions.values():
        if s["a"] in linked:
            continue
        cands = s.get("candidates") or []
        # A suggestion with no candidates at all is kept, so a malformed one
        # is surfaced rather than dropped.
        if cands and all(c in linked for c in cands):
            continue
        out.append(s)
    return out


def transfer_links(core: ProjectionCore) -> list[dict]:
    """Live transfer links (the recognized internal transfers), with grade."""
    return [{"a": min(p), "b": max(p), **info}
            for p, info in core._links.items()
            if info.get("status") == "linked"]


# ---------------------------------------------------------------- enumeration

def _enumerated(core: ProjectionCore):
    """The canonical enumeration every movement key derives from: each real
    account's lines in (date, description, amount) order, with the occurrence
    index that separates identical siblings. One generator, so every reader
    that needs a key assigns the same one."""
    counts: dict[tuple, int] = {}
    for account in accounts_view.accounts(core):
        st = core._acct[account]
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
            yield (movement_key(did, account, ln.date, ln.amount,
                                ln.description, occ), account, st, ln)


def movements(core: ProjectionCore) -> list[MovementInfo]:
    """Every posted movement on a real (asset/liability) account, each with
    its stable transfer key and its derived nature.

    Occurrence indices are assigned here, once, so the matcher and the
    projection agree on every key. Uncategorized counter-legs are excluded:
    they are not transfer candidates."""
    linked = linked_keys(core)
    out: list[MovementInfo] = []
    for key, account, st, ln in _enumerated(core):
        m = MovementInfo(
            key=key, account=account, kind=st.kind, date=ln.date,
            amount=ln.amount, description=ln.description,
            currency=st.currency, provenance=ln.provenance,
            linked=key in linked)
        decide_nature(core, m)
        out.append(m)
    return out


def movement_grades(core: ProjectionCore) -> dict[str, str]:
    """{movement key: the posting's grade} for every enumerated movement —
    the per-line grade `MovementInfo` does not carry, keyed exactly as
    `movements` keys it."""
    return {key: ln.grade for key, _account, _st, ln in _enumerated(core)}


def transactions(core: ProjectionCore, account: str) -> list[TxnLine]:
    st = core._acct.get(account)
    if st is None or not st.seen:
        raise UnknownAccountError(account)
    # Sorted by value-time date: the log is append-only in knowledge-time,
    # so a backfilled older statement lands last, but a person reads a
    # statement chronologically.
    return sorted(st.lines, key=lambda ln: ln.date)


def decide_nature(core: ProjectionCore, m: MovementInfo) -> None:
    """Set `nature`, `nature_reason`, `provisional` and `ruling_account` on
    one movement, from the strongest evidence available.

    1. linked            — a live TransferLink. Decisive.
    2. a ruling          — someone said what this is.
    3. own account       — the description distinctively names another
                           account you hold, so a card payment whose
                           counterpart statement was never ingested is
                           still not spending.
    4. category hint     — what the counterparty implies; applied, and
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
    ruling = (core._rulings.get((SCOPE_MOVEMENT, m.key))
              or merchants_view.merchant_ruling(core, m))
    if ruling and ruling.get("legs"):
        m.nature, m.nature_reason = nature_of_legs(ruling["legs"]), BY_RULING
        m.ruling_account = leading_account(ruling["legs"])
        # Components known, proportions not — reported as provisional.
        m.provisional = (m.nature == MIXED)
        return
    nature = (core._categories.get(m.key) or {}).get("nature")
    if nature not in (TRANSFER, SETTLEMENT, SPENDING):
        merchant = merchants_view.merchant_record(core, m) or {}
        nature = (merchant.get("attributes") or {}).get("nature")
    if nature in (TRANSFER, SETTLEMENT, SPENDING):
        m.nature, m.nature_reason = nature, BY_RULING
        return
    # Rung 3: does this movement name one of YOUR OTHER accounts?
    low = (m.description or "").lower()
    for account, tokens in accounts_view.own_account_tokens(core).items():
        if account == m.account:
            continue                      # naming itself proves nothing
        if tokens and any(tok in low for tok in tokens):
            m.nature, m.nature_reason = TRANSFER, BY_OWN_ACCOUNT
            return
    # Rung 4: what this COUNTERPARTY implies, given which way the money
    # went. Learned at enrichment rather than matched against a word list. A
    # `forced` implication is decisive; a `suggested` one is provisional.
    implied = merchants_view.implication_of(core, m)
    if implied:
        nature = _NATURE_OF_MAJOR.get(implied["major"], SPENDING)
        if nature != SPENDING:
            m.nature, m.nature_reason = nature, BY_CATEGORY
            m.provisional = implied.get("confidence") != "forced"
            return
    m.nature, m.nature_reason, m.provisional = SPENDING, BY_DEFAULT, False


# ---------------------------------------------------------- spending predicates

def is_expense(m: MovementInfo) -> bool:
    """A movement with the *shape* of spending: money out of an asset, or a
    charge on a liability (a card purchase). A card *payment* — liability,
    negative — is not.

    Shape alone does not decide; what a movement is economically is its
    `nature`, and ``counts_as_spending`` applies both."""
    return ((m.kind == "depository" and m.amount < 0)
            or (m.kind == "liability" and m.amount > 0))


def money_effect(m: MovementInfo) -> Decimal:
    """The movement's amount as it moved the person's money: positive in,
    negative out.

    The account's kind decides the sign, not the posting's. A liability
    records a charge positive — what is owed grew — so its sign is read the
    other way up; every other kind reads as recorded."""
    return -m.amount if m.kind == "liability" else m.amount


def counts_as_spending(m: MovementInfo) -> bool:
    """True when a movement belongs in a spending figure: it has the shape of
    an expense AND its nature is `spending`. A card payment, a brokerage
    contribution, or a movement naming another account you hold is excluded
    whether or not a link was formed."""
    return is_expense(m) and m.nature == SPENDING


def provisional_spending(core: ProjectionCore,
                         currency: str | None = None) -> Decimal:
    """The total magnitude of expense-shaped movements whose nature rests on
    weak evidence (`provisional`), filtered by `currency` if given. Reported
    alongside the spending total, so the figure states its uncertainty."""
    total = Decimal("0")
    for m in movements(core):
        if not is_expense(m) or not m.provisional:
            continue
        if currency is not None and m.currency != currency:
            continue
        total += abs(m.amount)
    return total


def excluded_from_spending(core: ProjectionCore) -> list[MovementInfo]:
    """Expense-shaped movements kept OUT of spending because their nature is
    not `spending`, each carrying the rung that decided it."""
    return [m for m in movements(core)
            if is_expense(m) and m.nature != SPENDING]


def spending_by_currency(core: ProjectionCore) -> dict[str, Decimal]:
    """Depository outflows per currency, as positive magnitudes, excluding
    non-spending natures. Superseded by ``spending_by_category``, which is
    the full view; kept for callers that predate it."""
    out: dict[str, Decimal] = {}
    for m in movements(core):
        if m.kind != "depository" or m.amount >= 0 or m.nature != SPENDING:
            continue
        out[m.currency] = out.get(m.currency, Decimal("0")) + (-m.amount)
    return out
