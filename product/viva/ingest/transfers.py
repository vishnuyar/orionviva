"""Transfer detection — recognizing that two movements are one internal transfer.

Deterministic, no model calls. A transfer is an *overlay* over two existing
postings (never a re-post), so each statement still reconciles on its own.

The trust discipline mirrors the reconciliation ladder's forced/suggested split:
a **decisive** match auto-links (grade ``corroborated``); anything softer is
**surfaced** as a suggestion for a human ruling and nothing is netted until
confirmed — never bluff a number. Links are only formed between movements on
accounts we already hold (all ingested accounts are the user's own); a
named-but-unseen destination is left to the own-account question.
"""

from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..ledger.events import transfer_linked, transfer_suggested, transfer_unlinked
from ..ledger.identity import account_tokens
from ..ledger.ledger import Ledger
from ..ledger.projection import LedgerProjection, MovementInfo

log = logging.getLogger(__name__)

# A transfer's legs post within a few days of each other (a card payment usually
# clears a day or two after the bank debit). Kept tight to limit coincidental
# amount matches; a match still only *auto*-links when the description names one
# of the two accounts distinctively (`_strong_hint`), and is otherwise suggested.
#
# THIS CONSTANT IS NOT THE DIAL FOR "too much is being caught", and it is worth
# saying so where someone will reach for it. Auto-linking needs exactly one
# candidate, so a WIDER window finds more candidates and pushes pairs out of
# decisive and into questions; narrowing it can therefore produce MORE auto-links,
# not fewer. And narrowing unlinks nothing already linked — `_candidates` only
# looks at movements where `linked` is false. The dial is `_strong_hint`.
DATE_WINDOW_DAYS = 5

# FOUR ENGLISH KEYWORD TABLES USED TO LIVE HERE, and they are gone (2026-07-29).
#
#   _STOPWORDS         "chase", "bank", "the", "and" — words a token may not be
#   _TRANSFER_WORDS    "transfer", "payment", "thank you", "autopay"
#   _CARD_WORDS        "card", "credit", "visa", "mastercard", "amex"
#   _DEPOSITORY_WORDS  "saving", "checking", "chequing", "current"
#
# _CARD_WORDS was the load-bearing one and the reason too much was being caught.
# `_strong_hint` returned true if any of those words appeared ANYWHERE in either
# description — and a credit card statement prints "card" on nearly every line,
# so for a card destination the hint was close to always-true and the only real
# constraints left were equal amount and uniqueness. A word list that is always
# true is not evidence; it is a rubber stamp.
#
# What replaces them is what the project has used every other time it deleted
# one of these: a property of the DATA rather than of the language.
#
#   naming an account   the description carries a token that belongs to one of
#                       these two accounts AND to no other account you hold.
#                       `distinctive_tokens` computes that from the accounts
#                       themselves, so a stopword list has nothing to guess at.
#
#   worth asking about  the match itself. Same amount, same currency, opposite
#                       direction, both accounts yours, within the window. That
#                       IS the evidence; whether the bank chose the word
#                       "payment" is evidence about English. Volume is the
#                       question queue's problem and it was built for exactly
#                       that — rank by money moved, summarise the tail.


def _flow(m: MovementInfo) -> str:
    """Classify a movement's role in a possible transfer — a *matching* read of
    direction only (net worth uses the full economic sign):
      - an asset (depository) going down is a **source** (money out);
      - an asset going up, or a liability going down (a paydown), is a
        **destination** (money arriving);
      - a liability going up is a charge — **neither**.
    """
    # An investment account's cash behaves like a depository for matching: money
    # in (a contribution) is a destination, money out (a withdrawal) a source
    # (a checking→brokerage contribution is an internal transfer).
    if m.kind in ("depository", "investment"):
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
    """Distinctive tokens that identify one account in a transaction description.

    The single implementation lives in the ledger's identity layer (the
    projection's nature derivation needs the same tokens); this stays as the
    ingest-side name so callers here are unchanged. Works even for an account
    not yet opened (a statement mid-post that is failing to reconcile)."""
    return account_tokens(institution, number, ref)


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


def _distinctive(proj: LedgerProjection) -> dict:
    """Per account, the tokens no OTHER account of yours carries. Computed once
    per scan; the vault is the authority on what is distinctive about it."""
    from ..ledger.identity import distinctive_tokens
    per, inst = {}, {}
    for acct in proj.accounts():
        try:
            info = proj.account_info(acct)
        except Exception:                                   # noqa: BLE001
            continue
        per[acct] = account_tokens_from(info.institution, info.number, info.name)
        inst[acct] = info.institution
    return distinctive_tokens(per, inst)


def _strong_hint(proj: LedgerProjection, src: MovementInfo, dst: MovementInfo,
                 distinctive: dict | None = None) -> bool:
    """True when the descriptions NAME one of these two accounts distinctively.

    The evidence that separates 'payment to my card' (a transfer) from 'payment
    to my mortgage' (a real external outflow) is that the line carries something
    identifying the account it paid: its last four, its institution, a product
    word — and that nothing else you own carries the same thing.

    It used to also accept the bare word "card", which on a card statement is
    every line. That is why this is now the only path."""
    text = f"{src.description} {dst.description}".lower()
    dist = distinctive if distinctive is not None else _distinctive(proj)
    return (_names_account(text, dist.get(src.account, set()))
            or _names_account(text, dist.get(dst.account, set())))


# --------------------------------------------------------------- what the line
# --------------------------------------------------------------- says about itself
#
# A bank that prints "02/17 Payment To Acme Card Ending IN 2222" has told you
# two facts the matcher spent a year not reading: WHEN the money moved and WHICH
# account it went to. Both are already named slots — `{date}` and `{account_ref}`
# under an induced grammar, `posting_date` under the published rules when no
# grammar exists — so nothing new has to be parsed, learned, or bought.
#
# This is what replaced the deleted word lists as the tiebreaker. It is the same
# bet the grammar work rests on: read what the bank PRINTED, not what an English
# word is presumed to mean. It needs no induction to start working and no list to
# be maintained per country.


@dataclass
class _Parts:
    """The named parts of one description that bear on transfer matching."""

    date: str = ""              # as printed: "02/17", "17-02", "12/31/24"
    account_ref: str = ""       # the account the line says it paid
    layer: str = ""             # grammar | published | refused — for the record


def _parts_of(m: MovementInfo, profile_for=None) -> _Parts:
    """Resolve one description, grammar first and published rules as fallback.

    `resolve_descriptor` already implements exactly that precedence, so this is a
    reader over it rather than a second copy of the rule. `profile_for(movement)`
    supplies the induced grammar for the movement's (institution × kind) or None;
    None is the ordinary case and stays a working one.

    `account_ref` comes out of `res.personal`, never `res.fields`. That is not an
    accident of where it landed: an account reference identifies YOU, so the
    vocabulary declares it personal and it never crosses into shareable data. The
    transfer matcher lives entirely inside the personal boundary — it reads your
    ledger to decide about your accounts — so it may read it. What it may not do
    is copy the value anywhere shareable, which is why the link records the NAME
    of the evidence and not its content."""
    from merchantcore.resolve import resolve_descriptor

    profile = None
    if profile_for is not None:
        try:
            profile = profile_for(m)
        except Exception:                                   # noqa: BLE001
            profile = None
    try:
        res = resolve_descriptor(m.description or "", profile=profile)
    except Exception:                                       # noqa: BLE001
        # A matcher that dies because a descriptor is strange is worse than one
        # that falls back to amount-and-name evidence, which is where it was.
        return _Parts()
    if res.refused:
        return _Parts(layer="refused")
    return _Parts(date=str(res.fields.get("date")
                           or res.fields.get("posting_date") or ""),
                  account_ref=str(res.personal.get("account_ref") or ""),
                  layer=res.layer)


def _prints_date(printed: str, iso: str) -> bool:
    """True when a date the bank printed on a line IS a candidate's date.

    Month and day only, and BOTH ORDERS are accepted, which is what makes this
    work outside the United States without a locale setting. 03/09 is the ninth
    of March to one bank and the third of September to another, and the matcher
    does not need to know which: every candidate is already within
    DATE_WINDOW_DAYS of the source, and two dates that close cannot be six months
    apart, so at most one reading can ever match. The ambiguity that would
    require a locale is arithmetically unreachable here.

    The year is not needed for the same reason, which is what lets a 12/31 line
    posting on 01/02 match with no year arithmetic at all."""
    m = re.match(r"\s*(\d{1,2})[/-](\d{1,2})", printed or "")
    if not m or len(iso or "") < 10:
        return False
    try:
        a, b = int(m.group(1)), int(m.group(2))
        month, day = int(iso[5:7]), int(iso[8:10])
    except ValueError:
        return False
    return (a, b) == (month, day) or (b, a) == (month, day)


def _account_evidence(proj: LedgerProjection, src: MovementInfo,
                      dst: MovementInfo, distinctive: dict,
                      parts: _Parts) -> str:
    """WHICH evidence says the counterpart is your own account, or "".

    Returns the name of the rule rather than a boolean, because that name is what
    the link records and what `transfer_report` shows you. A link whose reasoning
    cannot be recovered is a link you can only accept or delete wholesale.

    BE CLEAR ABOUT WHAT THE SLOT PATH DOES AND DOES NOT ADD. A slot's text is part
    of the line, so anything `account_ref_slot` matches, `named_account` would
    have matched too by substring — it cannot widen coverage and no link exists
    because of it. What it does is say WHICH, and say it from a slot a grammar
    proved holds an account reference rather than from a substring that happened
    to appear. That distinction is worth recording and worth nothing else, and
    writing it down here is cheaper than someone later measuring its contribution
    and finding zero.

    The obvious next move, deliberately not taken: a slot naming a DIFFERENT
    account of yours is evidence AGAINST the pair, not merely absent evidence
    for it. On this vault the one case that would catch ("...Ending IN 2222"
    against another card's credit) is already refused for want of account evidence, so
    the rule would be untested the day it shipped."""
    ref = (parts.account_ref or "").strip().lower()
    if ref and ref in distinctive.get(dst.account, set()):
        return "account_ref_slot"
    if _strong_hint(proj, src, dst, distinctive):
        return "named_account"
    return ""


# How much one (source, destination) pair is worth. Account evidence is worth 2
# and a printed date 1, so the date can only ever break a tie BETWEEN pairs that
# already have account evidence — it never creates a link on its own. That keeps
# the gate exactly where it was and adds a discriminator underneath it, which is
# the whole reason the questions were unanswerable: nineteen of your twenty-nine
# were one source against several identical "Payment Thank You" credits, where
# the account evidence was equally true of every candidate.
_EV_ACCOUNT = 2
_EV_DATE = 1
_EV_FLOOR = _EV_ACCOUNT       # below this nothing links, whatever else matched


def _sole_max(items, score):
    """The unique highest-scoring item, or None if it ties or scores too low.

    'Unique' is the point. Ties do not get broken by iteration order here; they
    become questions, which is what a tie honestly is."""
    best = max((score(i) for i in items), default=0)
    if best < _EV_FLOOR:
        return None
    top = [i for i in items if score(i) == best]
    return top[0] if len(top) == 1 else None


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


def default_profile_for(proj: LedgerProjection):
    """The induced grammar for a movement's (institution × kind), memoised.

    Built here rather than threaded through `capture_and_ingest`, `sweep` and
    `_try_corroboration` because those three signatures are load-bearing and this
    is a lookup, not a policy. Any caller may still pass its own — tests do, to
    stay off the real store.

    Every failure degrades to None, which means the published rules, which name
    the printed date anyway. Worth stating plainly so nobody later reads the
    fallback as broken: on the vault this was built against, Layer 0 alone
    resolved every one of the twenty-four. The grammar is the better source and
    it has not yet been the deciding one."""
    cache: dict = {}

    def _for(m):
        try:
            info = proj.account_info(m.account)
        except Exception:                                   # noqa: BLE001
            return None
        pair = (info.institution or "?", info.kind or "?")
        if pair not in cache:
            try:
                from ..induce_profile import profile_store
                cache[pair] = profile_store().latest_for(*pair)
            except Exception:                               # noqa: BLE001
                cache[pair] = None
        return cache[pair]

    return _for


def weigh(proj: LedgerProjection, graph: dict, sources: dict,
          distinctive: dict, profile_for=None) -> tuple[dict, dict]:
    """Score every (source, destination) pair, and say what scored it.

    Split out of `link_transfers` because it is the whole decision and it is
    pure: no ledger, no appends. `transfer_report` calls this to show you what a
    scan WOULD do, and it is the same function, so the rehearsal cannot drift
    from the performance."""
    parts = {k: _parts_of(s, profile_for) for k, s in sources.items()}
    strength: dict[tuple[str, str], int] = {}
    why: dict[tuple[str, str], str] = {}
    for skey, cands in graph.items():
        src, p = sources[skey], parts[skey]
        for c in cands:
            evidence = _account_evidence(proj, src, c, distinctive, p)
            dated = bool(p.date) and _prints_date(p.date, c.date)
            strength[(skey, c.key)] = ((_EV_ACCOUNT if evidence else 0)
                                       + (_EV_DATE if dated else 0))
            why[(skey, c.key)] = "+".join(
                x for x in (evidence, "printed_date" if dated else "") if x)
    return strength, why


def decide(graph: dict, strength: dict, consumed: set | None = None) -> dict:
    """Source key -> the destination key it is decisive for, for every source
    that is decisive at all.

    Decisive means BOTH directions are unambiguous, which is the correction this
    whole pass is. The old rule asked only whether a source had one candidate and
    that candidate had one suitor; it never asked which of several equally-named
    candidates the line itself pointed at, so a checking account paying its card
    four times in one week produced four unanswerable questions instead of four
    obvious links.

        forward   among the source's candidates, one scores strictly highest
        backward  among that destination's suitors, this source scores strictly
                  highest

    Both use `_sole_max`, so both refuse to break a tie. Neither depends on dict
    order: the scores are computed for the whole graph before anything is
    chosen."""
    consumed = consumed or set()
    claimants: dict[str, list[str]] = {}
    for (skey, dkey) in strength:
        claimants.setdefault(dkey, []).append(skey)

    out: dict[str, str] = {}
    for skey in sorted(graph):                  # sorted: a stable scan order
        if skey in consumed:
            continue
        keys = [c.key for c in graph[skey] if c.key not in consumed]
        dkey = _sole_max(keys, lambda k: strength.get((skey, k), 0))
        if dkey is None:
            continue
        rivals = [s for s in claimants.get(dkey, []) if s not in consumed]
        if _sole_max(rivals, lambda s: strength.get((s, dkey), 0)) == skey:
            out[skey] = dkey
    return out


def link_transfers(ledger: Ledger, profile_for=None) -> dict:
    """Scan for internal transfers and act: decisive pairs auto-link
    (``corroborated``); ambiguous or weak ones are surfaced as suggestions for a
    human. Idempotent — already-linked movements and already-open suggestions are
    skipped, so it is safe to run after every post and heal.

    `profile_for(movement)` supplies the induced grammar for the movement's
    (institution × kind), or None. Omitted, it defaults to the real profile
    store; a bank with no grammar falls to the published rules, which name the
    printed date anyway, so no caller has to know whether induction has run."""
    proj = ledger.projection()
    distinctive = _distinctive(proj)
    graph, sources = _candidates(proj)
    if profile_for is None:
        profile_for = default_profile_for(proj)
    strength, why = weigh(proj, graph, sources, distinctive, profile_for)

    open_suggestions = {b["a"] for b in proj.transfer_suggestions()}
    consumed: set[str] = set()          # movements linked earlier in THIS scan
    linked = auto = suggested = 0

    verdicts = decide(graph, strength, consumed)
    for skey in sorted(graph):
        if skey in consumed:
            continue
        src = sources[skey]
        cands = [c for c in graph[skey] if c.key not in consumed]
        if not cands:
            continue
        dkey = verdicts.get(skey)
        if dkey is not None and dkey not in consumed:
            dst = next(c for c in cands if c.key == dkey)
            reason = why.get((skey, dkey), "")
            log.info("transfer: decisive %s <-> %s (%s %s) via %s — auto-linking",
                     src.account, dst.account, src.currency, abs(src.amount), reason)
            ledger.append(transfer_linked(
                src.key, dst.key, "corroborated",
                _evidence(src, dst, "decisive", reason),
                _later(src.date, dst.date), by="auto"))
            consumed.add(src.key)
            consumed.add(dst.key)       # a consumed movement won't be offered again
            auto += 1
            linked += 1
            continue
        # ASK about every ambiguous match. The gate here used to be a
        # transfer-word list, on the reasoning that a pure amount coincidence
        # with no such word is ordinary spending — but the coincidence IS the
        # evidence, and whether the bank wrote "payment" is a fact about
        # English. Flooding is the queue's problem: it ranks by money moved and
        # summarises the tail, which is what it was built to do.
        if skey not in open_suggestions:
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
    """Cross-document corroboration: a statement is off by ``delta`` —
    the net effect on *its* balance of one or more movements it is missing (e.g.
    a card whose whole payments section was dropped). Find counterparty movements
    on other own accounts that **distinctively name this account** (so the
    candidate set is small and safe) and whose magnitudes **uniquely sum** to
    ``|delta|``. Return that subset — its lines supply what this document dropped.

    Returns [] unless the subset is unique: a gap is never closed on a guess.
    Single-leg (one payment) is the size-1 case; the missing
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
    is our highest grade), recorded as an event (correction-as-event).

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


def _evidence(src: MovementInfo, dst: MovementInfo, verdict: str,
              decided_by: str = "") -> dict:
    """What justified this ruling, in a form a person can audit later.

    `decided_by` names the RULE that fired ("named_account+printed_date"), never
    the value it matched. The account reference that resolved a link is personal
    data; the fact that an account reference resolved it is not, and it is the
    fact that makes a link reviewable. Whole descriptions are already here — this
    record has always lived inside the personal boundary — but a name that cannot
    leak is still better than a value that must not."""
    return {"verdict": verdict, "amount": str(abs(src.amount)),
            "currency": src.currency, "days_apart": _days_apart(src.date, dst.date),
            "source": src.account, "destination": dst.account,
            "decided_by": decided_by,
            "source_desc": src.description, "destination_desc": dst.description}


def _later(a: str, b: str) -> str:
    return max(a, b)


def _today() -> str:
    return date.today().isoformat()
