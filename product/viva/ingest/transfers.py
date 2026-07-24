"""Transfer detection — recognizing that two movements are one internal transfer.

Deterministic, no model calls (T2). A transfer is an *overlay* over two existing
postings (never a re-post), so each statement still reconciles on its own; see
docs/transfer-links-and-cross-document-corroboration.md.

The trust discipline mirrors the reconciliation ladder's forced/suggested split:
a **decisive** match auto-links (grade ``corroborated``); anything softer is
**surfaced** as a suggestion for a human ruling and nothing is netted until
confirmed (principle 2 — never bluff). v1 links only movements on accounts we
already hold (all ingested accounts are the user's own); a named-but-unseen
destination is Stage 3's own-account question.
"""

from __future__ import annotations

import itertools
import logging
import re
from datetime import date
from decimal import Decimal

from ..ledger.events import transfer_linked, transfer_suggested, transfer_unlinked
from ..ledger.ledger import Ledger
from ..ledger.projection import LedgerProjection, MovementInfo

log = logging.getLogger(__name__)

# A transfer's legs post within a few days of each other (a card payment usually
# clears a day or two after the bank debit). Kept tight to limit coincidental
# amount matches; a match still only *auto*-links with a naming hint, and is only
# *suggested* when the line carries a transfer signal (see `_transfer_signal`).
DATE_WINDOW_DAYS = 5

# Common words that are not distinctive account tokens (so "chase"/"checking"
# alone don't count as naming the *other* account when both are Chase).
_STOPWORDS = frozenset({
    "chase", "bank", "card", "credit", "account", "checking", "savings",
    "total", "statement", "rise", "the", "and", "for", "payment", "rewards"})

# Generic hints that a movement is an internal transfer rather than external
# spending. A hint alone is NOT decisive (a mortgage payment says "payment" too);
# decisiveness also needs the counterpart to be one of your own accounts named or
# implied. See `_strong_hint`.
_TRANSFER_WORDS = ("transfer", "xfer", "payment", "pymt", "autopay", "auto pay",
                   "online payment", "thank you", "epay", "e-payment", "bill pay",
                   "billpay", "to savings", "to checking")
_CARD_WORDS = ("card", "credit", "visa", "mastercard", "amex", "discover")
_DEPOSITORY_WORDS = ("saving", "checking", "chequing", "current", "transfer")


def _flow(m: MovementInfo) -> str:
    """Classify a movement's role in a possible transfer — a *matching* read of
    direction only (the full economic sign for net worth is Slice 7):
      - an asset (depository) going down is a **source** (money out);
      - an asset going up, or a liability going down (a paydown), is a
        **destination** (money arriving);
      - a liability going up is a charge — **neither**.
    """
    if m.kind == "depository":
        return "source" if m.amount < 0 else "destination"
    if m.kind == "liability":
        return "destination" if m.amount < 0 else "neither"
    return "neither"


def _days_apart(a: str, b: str) -> int:
    try:
        return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)
    except ValueError:
        return 10_000


def _last4(proj: LedgerProjection, account: str) -> str:
    try:
        num = "".join(ch for ch in (proj.account_info(account).number or "") if ch.isdigit())
    except Exception:
        num = ""
    return num[-4:] if len(num) >= 4 else ""


def account_tokens_from(institution: str, number: str, ref: str) -> set[str]:
    """Distinctive tokens that identify one account in a transaction description:
    its institution, its last-4, and product words from its label (e.g.
    'imprint', 'freedom') — minus generic stopwords. Derived from raw identity
    signals so it works even for an account not yet opened (a statement mid-post
    that is failing to reconcile). These are what a bank line like 'PAYMENT TO
    IMPRINT' carries to name the card it paid.

    The account HOLDER's name is deliberately excluded — it is shared across all
    of the user's own accounts, so it does not distinguish one from another."""
    toks: set[str] = set()
    if institution and len(institution) >= 3:
        toks.add(institution.lower())
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    if len(digits) >= 4:
        toks.add(digits[-4:])
    for w in re.split(r"[^a-z0-9]+", (ref or "").lower()):
        if len(w) >= 4 and w not in _STOPWORDS:
            toks.add(w)
    return {t for t in toks if t and t not in _STOPWORDS}


def _account_tokens(proj: LedgerProjection, account: str) -> set[str]:
    """Distinctive tokens for an *opened* account (used by the both-legs matcher)."""
    try:
        info = proj.account_info(account)
    except Exception:
        return set()
    return account_tokens_from(info.institution, info.number, info.name)


def _names_account(text: str, tokens: set[str]) -> bool:
    """True when a description distinctively names an account (institution,
    last-4, or product token) — the strong own-account evidence."""
    low = text.lower()
    return any(tok in low for tok in tokens)


def _strong_hint(proj: LedgerProjection, src: MovementInfo, dst: MovementInfo) -> bool:
    """True when the descriptions name/imply the OTHER own account — the evidence
    that separates 'payment to my card' (a transfer) from 'payment to my
    mortgage' (a real external outflow). A kind word ('card'), the other
    account's last-4, its institution, or a product token all count."""
    text = f"{src.description} {dst.description}".lower()
    words = _CARD_WORDS if dst.kind == "liability" else _DEPOSITORY_WORDS
    if any(w in text for w in words):
        return True
    return (_names_account(text, _account_tokens(proj, src.account))
            or _names_account(text, _account_tokens(proj, dst.account)))


def _transfer_signal(m: MovementInfo) -> bool:
    """True when a movement's description carries a transfer-ish word — the weak
    signal that gates whether an ambiguous match is worth *asking* about. Without
    it, an equal-amount coincidence (a $50 purchase vs a $50 card paydown) is
    treated as ordinary spending, not a question — the fix for review-flooding."""
    low = m.description.lower()
    return any(w in low for w in _TRANSFER_WORDS)


def _candidates(proj: LedgerProjection) -> dict:
    """For each unlinked source movement, the unlinked destination movements it
    could pair with (equal magnitude + same currency + within the date window +
    a different account). The bipartite candidate graph the gate reasons over."""
    movements = [m for m in proj.movements() if not m.linked]
    sources = [m for m in movements if _flow(m) == "source"]
    dests = [m for m in movements if _flow(m) == "destination"]
    graph: dict[str, list[MovementInfo]] = {}
    for s in sources:
        matches = [d for d in dests
                   if d.account != s.account
                   and d.currency == s.currency
                   and abs(d.amount) == abs(s.amount)
                   and _days_apart(s.date, d.date) <= DATE_WINDOW_DAYS]
        if matches:
            graph[s.key] = matches
    return graph, {s.key: s for s in sources}


def link_transfers(ledger: Ledger) -> dict:
    """Scan for internal transfers and act: decisive pairs auto-link
    (``corroborated``); ambiguous or weak ones are surfaced as suggestions for a
    human. Idempotent — already-linked movements and already-open suggestions are
    skipped, so it is safe to run after every post and heal."""
    proj = ledger.projection()
    graph, sources = _candidates(proj)
    # A destination is contested if more than one source can pair with it.
    dest_uses: dict[str, int] = {}
    for cand in graph.values():
        for d in cand:
            dest_uses[d.key] = dest_uses.get(d.key, 0) + 1

    open_suggestions = {b["a"] for b in proj.transfer_suggestions()}
    consumed: set[str] = set()          # movements linked earlier in THIS scan
    linked = auto = suggested = 0
    for skey, cands0 in graph.items():
        if skey in consumed:
            continue
        src = sources[skey]
        cands = [c for c in cands0 if c.key not in consumed]   # skip already-taken
        if not cands:
            continue
        # Decisive: exactly one candidate, uniquely claiming it, with a strong
        # hint that the counterpart is your own account.
        if (len(cands) == 1 and dest_uses.get(cands[0].key, 0) == 1
                and _strong_hint(proj, src, cands[0])):
            dst = cands[0]
            log.info("transfer: decisive %s <-> %s (%s %s) — auto-linking",
                     src.account, dst.account, src.currency, abs(src.amount))
            ledger.append(transfer_linked(
                src.key, dst.key, "corroborated",
                _evidence(src, dst, "decisive"), _later(src.date, dst.date), by="auto"))
            consumed.add(src.key)
            consumed.add(dst.key)       # a consumed movement won't be offered again
            auto += 1
            linked += 1
        # Only ASK when there is a transfer signal on either side — a pure
        # amount coincidence with no such word is treated as ordinary spending,
        # not a question (the fix for review-flooding).
        elif (skey not in open_suggestions
              and (_transfer_signal(src) or any(_transfer_signal(c) for c in cands))):
            log.info("transfer: ambiguous for %s (%d candidate(s)) — suggesting",
                     src.account, len(cands))
            ledger.append(transfer_suggested(
                src.key, [c.key for c in cands],
                _evidence(src, cands[0], "suggested"),
                _later(src.date, cands[0].date)))
            suggested += 1
    if auto or suggested:
        log.info("transfer scan: %d auto-linked, %d suggested", auto, suggested)
    return {"linked": linked, "auto": auto, "suggested": suggested}


def find_corroborating_legs(proj: LedgerProjection, account: str, kind: str,
                            delta: Decimal, currency: str, o_date: str,
                            c_date: str, own_tokens: set[str] | None = None
                            ) -> list[MovementInfo]:
    """Cross-document corroboration (Slice 3): a statement is off by ``delta`` —
    the net effect on *its* balance of one or more movements it is missing (e.g.
    a card whose whole payments section was dropped). Find counterparty movements
    on other own accounts that **distinctively name this account** (so the
    candidate set is small and safe) and whose magnitudes **uniquely sum** to
    ``|delta|``. Return that subset — its lines supply what this document dropped.

    Returns [] unless the subset is unique: a gap is never closed on a guess
    (principle 2). Single-leg (one payment) is the size-1 case; the missing
    section (several payments) is the size-N case, gated by uniqueness."""
    if delta == 0:
        return []
    missing_is_source = (kind == "depository" and delta < 0)
    missing_is_destination = ((kind == "depository" and delta > 0)
                              or (kind == "liability" and delta < 0))
    if not (missing_is_source or missing_is_destination):
        return []
    want = "source" if missing_is_destination else "destination"
    tokens = own_tokens if own_tokens is not None else _account_tokens(proj, account)
    if not tokens:
        return []                     # no way to name the account → can't be safe

    cands: list[MovementInfo] = []
    for m in proj.movements():
        if m.linked or m.account == account or m.currency != currency:
            continue
        if _flow(m) != want or abs(m.amount) > abs(delta):
            continue
        if _days_apart(m.date, o_date) > 45 and _days_apart(m.date, c_date) > 45:
            continue
        # Each candidate must distinctively name THIS account — the strong signal
        # that keeps a multi-leg subset-sum from matching unrelated movements.
        if _names_account(m.description, tokens):
            cands.append(m)

    target = abs(delta)
    subsets = _subsets_summing_to(cands, target, max_size=6)
    if len(subsets) == 1:                     # exactly one explanation → decisive
        return subsets[0]
    return []


def _subsets_summing_to(items: list[MovementInfo], target: Decimal,
                        max_size: int) -> list[list[MovementInfo]]:
    """All distinct subsets (up to ``max_size``) whose magnitudes sum to
    ``target``. The candidate list is pre-filtered to movements naming the
    account, so it is small and this stays cheap. Returns the matching subsets;
    the caller acts only if there is exactly one (uniqueness = decisive)."""
    found: list[list[MovementInfo]] = []
    n = min(len(items), 12)                   # hard bound; candidates are few
    for size in range(1, min(max_size, n) + 1):
        for combo in itertools.combinations(items[:n], size):
            if sum((abs(m.amount) for m in combo), start=Decimal("0")) == target:
                found.append(list(combo))
    return found


def confirm_transfer(ledger: Ledger, movement_a: str, movement_b: str) -> bool:
    """A person confirms a suggested pair — a `verified` link (their attestation
    is our highest grade), recorded as an event (correction-as-event, T4).

    Guards against double-linking: if either movement is already part of a live
    link (e.g. it was confirmed under a different suggestion), this is a no-op —
    a movement belongs to at most one transfer. Returns whether a link was made."""
    linked = ledger.projection().linked_keys()
    if movement_a in linked or movement_b in linked:
        log.info("transfer: confirm skipped — %s already linked",
                 (movement_a if movement_a in linked else movement_b)[:24])
        return False
    log.info("transfer: human-confirmed %s <-> %s", movement_a[:24], movement_b[:24])
    ledger.append(transfer_linked(movement_a, movement_b, "verified",
                                  {"kind": "confirmed"}, _today(), by="human"))
    return True


def reject_transfer(ledger: Ledger, movement_a: str, movement_b: str = "") -> None:
    """A person says 'these are not the same money' — dismiss the suggestion (and
    revoke the link if one existed). Append-only; nothing is deleted."""
    log.info("transfer: human-rejected %s", movement_a[:24])
    ledger.append(transfer_unlinked(movement_a, movement_b, _today(), by="human"))


def _evidence(src: MovementInfo, dst: MovementInfo, verdict: str) -> dict:
    return {"verdict": verdict, "amount": str(abs(src.amount)),
            "currency": src.currency, "days_apart": _days_apart(src.date, dst.date),
            "source": src.account, "destination": dst.account,
            "source_desc": src.description, "destination_desc": dst.description}


def _later(a: str, b: str) -> str:
    return max(a, b)


def _today() -> str:
    return date.today().isoformat()
