"""Transfer detection: recognising that two movements are one internal transfer.

Deterministic; no model calls. A transfer is an overlay over two existing
postings rather than a re-post, so each statement still reconciles on its own.

A decisive match is linked automatically at grade ``corroborated``. Anything
softer is recorded as a suggestion for a person to rule on, and nothing is
netted out of spending until it is confirmed. Links are formed only between
movements on accounts already held; a named but un-ingested destination is left
to the own-account question.

Design rationale, including the evidence rules and what they replaced:
docs/transfer-links-and-cross-document-corroboration.md
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

# Maximum days between the two legs of one transfer. A card payment usually
# clears a day or two after the bank debit.
DATE_WINDOW_DAYS = 5

def _flow(m: MovementInfo) -> str:
    """Return "source", "destination", or "neither" for a movement.

    Direction only, for matching; net worth uses the full economic sign.
    Depository and investment accounts: down is a source, up a destination.
    A liability going down (a paydown) is a destination; going up it is a charge
    and matches nothing.
    """
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
    """Tokens that identify one account in a description.

    Delegates to the ledger identity layer, which owns the single implementation.
    Works for an account that has not been opened yet."""
    return account_tokens(institution, number, ref)


def _account_tokens(proj: LedgerProjection, account: str) -> set[str]:
    """Tokens for an account that is already open; empty set if it is not."""
    try:
        info = proj.account_info(account)
    except Exception:
        return set()
    return account_tokens_from(info.institution, info.number, info.name)


def _names_account(text: str, tokens: set[str]) -> bool:
    """True when any of `tokens` appears in `text`, case-insensitively."""
    from ..ledger.identity import text_has_token
    return any(text_has_token(text, tok) for tok in tokens)


def _distinctive(proj: LedgerProjection) -> dict:
    """Map each account to the tokens no other held account carries.

    Computed once per scan from the accounts in the projection."""
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
    """True when either description carries a token distinctive to either account.

    `distinctive` is the map from `_distinctive`; it is recomputed if omitted."""
    text = f"{src.description} {dst.description}".lower()
    dist = distinctive if distinctive is not None else _distinctive(proj)
    return (_names_account(text, dist.get(src.account, set()))
            or _names_account(text, dist.get(dst.account, set())))


# ------------------------------------------------------------ printed evidence
#
# A source line such as "02/17 Payment To Acme Card Ending IN 2222" carries the
# transaction date and the account it paid. Both are already named slots:
# `{date}` and `{account_ref}` under an induced grammar, `posting_date` under the
# published rules when no grammar exists.


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
    """Name the rule that says the counterpart is an own account, or "".

    "account_ref_slot" when the parsed account reference exactly equals a token
    distinctive to the destination; "named_account" when `_strong_hint` matches
    the whole line; "" when neither does. The name is what the link records.

    The slot path cannot widen coverage — a slot's text is part of the line, so
    `named_account` matches wherever it does. It only names the evidence more
    precisely."""
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
        matches = [d for d in dests if is_transfer_candidate(s, d)]
        if matches:
            graph[s.key] = matches
    return graph, {s.key: s for s in sources}


def is_transfer_candidate(source: MovementInfo,
                          destination: MovementInfo) -> bool:
    """Whether two current movements pass the transfer candidate gate.

    The Activity read uses this same predicate when a persisted suggestion is
    shown later.  That keeps a once-qualified candidate from remaining
    actionable after replay has changed either referenced movement.
    """
    return (_flow(source) == "source"
            and _flow(destination) == "destination"
            and destination.account != source.account
            and destination.currency == source.currency
            and abs(destination.amount) == abs(source.amount)
            and _days_apart(source.date, destination.date) <= DATE_WINDOW_DAYS)


def default_profile_for(proj: LedgerProjection):
    """Return a memoised `profile_for(movement)` reading the real profile store.

    Any failure yields None, which falls back to the published rules; those name
    the printed date too, so the matcher still works with no grammar induced.
    Callers may pass their own resolver instead; tests do, to stay off the real
    store."""
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
    """Score every (source, destination) pair.

    Returns `(strength, why)`: the score per pair, and the names of the rules that
    produced it. Pure — no ledger and no appends — so `transfer_report` can call
    it to rehearse a scan."""
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
    """Map each decisive source key to the destination key it pairs with.

    A source is decisive when both directions are unambiguous: one of its
    candidates scores strictly highest, and among that destination's claimants
    this source scores strictly highest. Ties are refused, and the scores are
    computed for the whole graph first, so the result does not depend on
    iteration order. Sources in `consumed` are skipped."""
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
    """Scan for internal transfers, linking the decisive ones and asking about the rest.

    Decisive pairs are appended as `TransferLinked` at grade ``corroborated``;
    anything else becomes a `TransferSuggested` for a person to rule on. Returns
    counts of `linked`, `auto`, and `suggested`.

    Idempotent: already-linked movements and already-open suggestions are skipped,
    so it is safe to run after every post and heal.

    `profile_for(movement)` supplies the induced grammar for the movement's
    (institution × kind); omitted, it defaults to the real profile store."""
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
        # Every match that is not decisive becomes a question. Volume is the
        # question queue's problem; it ranks by money moved and summarises the
        # tail.
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
    """Build the evidence dict recorded on a link or suggestion.

    `decided_by` holds the NAME of the rule that fired
    ("named_account+printed_date"), never the value it matched."""
    return {"verdict": verdict, "amount": str(abs(src.amount)),
            "currency": src.currency, "days_apart": _days_apart(src.date, dst.date),
            "source": src.account, "destination": dst.account,
            "decided_by": decided_by,
            "source_desc": src.description, "destination_desc": dst.description}


def _later(a: str, b: str) -> str:
    return max(a, b)


def _today() -> str:
    return date.today().isoformat()
