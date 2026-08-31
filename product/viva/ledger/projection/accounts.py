"""Which accounts exist, what each one is, and whether a statement's identity
signals belong to one of them."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..events import ISSUED
from ..identity import (account_key, account_labels_overlap, account_tokens,
                        conflicting_number_signals, distinctive_tokens, identity_number_key,
                        institution_names_overlap, names_overlap,
                        normalize_number, slug)
from .core import ProjectionCore, UnknownAccountError


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
class Resolution:
    """How a statement's identity signals resolve against known accounts."""
    account_id: str            # the account this statement belongs to
    key: str                   # the raw number/label key for these signals
    verdict: str               # "same" | "new" | "ambiguous"
    candidate: str = ""        # for ambiguous: the existing account it might be
    candidate_name: str = ""
    reason: str = ""           # human-readable why (for the ask)


def accounts(core: ProjectionCore) -> list[str]:
    return sorted(a for a, s in core._acct.items() if s.seen)


def seen_account(core: ProjectionCore, account: str) -> bool:
    st = core._acct.get(account)
    return bool(st and st.seen)


def account_info(core: ProjectionCore, account: str) -> AccountInfo:
    st = core._acct.get(account)
    if st is None or not st.seen:
        raise UnknownAccountError(account)
    return AccountInfo(account=account, kind=st.kind, origin=st.origin,
                       currency=st.currency, name=st.name,
                       institution=st.institution, number=st.number,
                       names=list(st.names), jurisdiction=st.jurisdiction,
                       opened_at=st.opened_at)


def account_infos(core: ProjectionCore) -> list[AccountInfo]:
    return [account_info(core, a) for a in accounts(core)]


def account_aliases(core: ProjectionCore) -> dict[str, str]:
    return dict(core._aliases)


def document_types_of(core: ProjectionCore, account: str) -> set:
    """The canonical doc types of every document that has spoken about this
    account. The strongest evidence there is for what KIND of thing it is:
    an issuer produced a card statement for it, so it is a card."""
    st = core._acct.get(account)
    if st is None or not st.doc_ids:
        return set()
    from ...ingest.registry import profile_for
    # The store itself, not a copy: this is called once per account.
    seen = core._captured
    out = set()
    for did in st.doc_ids:
        profile = profile_for(seen.get(did, ""))
        if profile is not None:
            out.add(profile.doc_type)
    return out


def resolve(core: ProjectionCore, institution: str, account_number: str,
            account_ref: str, names: list[str],
            kind: str = "depository") -> Resolution:
    """Return the same, new, or ambiguous account for these identity signals."""
    key = account_key(institution, account_number, account_ref)
    if conflicting_number_signals(account_number, account_ref):
        return Resolution(
            key, key, "ambiguous",
            reason=("the extracted account number and the printed last four "
                    "disagree, so neither can safely identify the account"))
    if key in core._aliases:                       # learned
        return Resolution(core._aliases[key], key, "same")
    st = core._acct.get(key)
    if st is not None and st.seen:                 # already this account
        return Resolution(key, key, "same")
    mine_number = identity_number_key(account_number, account_ref)
    mine_full = normalize_number(account_number)
    for aid, s in core._acct.items():              # name overlaps another account?
        if not s.seen or s.kind != kind or aid == key:
            continue
        their_full = normalize_number(s.number)
        # Full matching numbers resolve independently of issuer display names.
        if (len(mine_full) > 4 and len(their_full) > 4
                and mine_full == their_full):
            return Resolution(aid, key, "same")
        their_number = identity_number_key(s.number, s.name)
        if (mine_number and mine_number == their_number
                and institution_names_overlap(institution, s.institution)
                and names_overlap(names, s.names)
                and account_labels_overlap(account_ref, s.name)):
            return Resolution(aid, key, "same")
        if not (s.names and names_overlap(names, s.names)):
            continue
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


def own_account_tokens(core: ProjectionCore) -> dict[str, set[str]]:
    """Return identity tokens for issued accounts eligible as own accounts."""
    if core._own_tokens_cache is None:
        per_account = {
            a: account_tokens(s.institution, s.number, s.name)
            for a, s in core._acct.items()
            if s.seen and s.kind in ("depository", "liability", "investment")
            and s.origin == ISSUED}
        institutions = {
            a: s.institution for a, s in core._acct.items() if a in per_account}
        core._own_tokens_cache = distinctive_tokens(per_account, institutions)
    return core._own_tokens_cache
