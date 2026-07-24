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

import logging
from datetime import date
from decimal import Decimal

from ..ledger.events import transfer_linked, transfer_suggested, transfer_unlinked
from ..ledger.ledger import Ledger
from ..ledger.projection import LedgerProjection, MovementInfo

log = logging.getLogger(__name__)

# A transfer's legs post within a few days of each other (a card payment often
# clears a day or two after the checking debit).
DATE_WINDOW_DAYS = 5

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


def _strong_hint(proj: LedgerProjection, src: MovementInfo, dst: MovementInfo) -> bool:
    """True when the descriptions name/imply the OTHER own account — the evidence
    that separates 'payment to my card' (a transfer) from 'payment to my
    mortgage' (a real external outflow). Either leg naming the other's kind word,
    or either description carrying the other account's last-4, counts."""
    text = f"{src.description} {dst.description}".lower()
    words = _CARD_WORDS if dst.kind == "liability" else _DEPOSITORY_WORDS
    if any(w in text for w in words):
        return True
    for acct in (src.account, dst.account):
        l4 = _last4(proj, acct)
        if l4 and l4 in text:
            return True
    return False


def _has_transfer_word(src: MovementInfo, dst: MovementInfo) -> bool:
    text = f"{src.description} {dst.description}".lower()
    return any(w in text for w in _TRANSFER_WORDS)


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
    linked = auto = suggested = 0
    for skey, cands in graph.items():
        src = sources[skey]
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
            auto += 1
            linked += 1
        elif skey not in open_suggestions:
            log.info("transfer: ambiguous/weak for %s (%d candidate(s)) — suggesting",
                     src.account, len(cands))
            ledger.append(transfer_suggested(
                src.key, [c.key for c in cands],
                _evidence(src, cands[0], "suggested"),
                _later(src.date, cands[0].date)))
            suggested += 1
    if auto or suggested:
        log.info("transfer scan: %d auto-linked, %d suggested", auto, suggested)
    return {"linked": linked, "auto": auto, "suggested": suggested}


def find_corroborating_leg(proj: LedgerProjection, account: str, kind: str,
                           delta: Decimal, currency: str, o_date: str,
                           c_date: str) -> MovementInfo | None:
    """Cross-document corroboration (Slice 3): a statement is off by ``delta`` —
    the effect on *its* balance of a movement it is missing. If exactly one
    *decisive* unmatched counterparty movement on another own account is the
    complementary leg (equal magnitude, same currency, near the period, a strong
    own-account hint), return it — its line supplies what this document dropped.

    Returns None unless the match is decisive: a gap is never closed on a guess
    (principle 2). The missing leg's role is inferred from ``delta``'s effect on
    this account, and we look for its complement."""
    if delta == 0:
        return None
    missing_is_source = (kind == "depository" and delta < 0)
    missing_is_destination = ((kind == "depository" and delta > 0)
                              or (kind == "liability" and delta < 0))
    if not (missing_is_source or missing_is_destination):
        return None
    want = "source" if missing_is_destination else "destination"

    # A synthetic view of the missing leg, so _strong_hint can read its side too.
    missing = MovementInfo(key="", account=account, kind=kind, date=c_date,
                           amount=delta, description="", currency=currency,
                           provenance=None)  # type: ignore[arg-type]
    cands: list[MovementInfo] = []
    for m in proj.movements():
        if m.linked or m.account == account or m.currency != currency:
            continue
        if abs(m.amount) != abs(delta) or _flow(m) != want:
            continue
        if _days_apart(m.date, o_date) > 45 and _days_apart(m.date, c_date) > 45:
            continue
        src, dst = (m, missing) if want == "source" else (missing, m)
        if _strong_hint(proj, src, dst):
            cands.append(m)
    if len(cands) == 1:
        return cands[0]
    return None


def confirm_transfer(ledger: Ledger, movement_a: str, movement_b: str) -> None:
    """A person confirms a suggested pair — a `verified` link (their attestation
    is our highest grade), recorded as an event (correction-as-event, T4)."""
    log.info("transfer: human-confirmed %s <-> %s", movement_a[:24], movement_b[:24])
    ledger.append(transfer_linked(movement_a, movement_b, "verified",
                                  {"kind": "confirmed"}, _today(), by="human"))


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
