"""Which accounts exist, what each one is, and whether a statement's identity
signals belong to one of them."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..events import ISSUED
from ..identity import (account_key, account_labels_overlap, account_tokens,
                        conflicting_number_signals, distinctive_tokens,
                        identity_number_key,
                        institution_names_overlap, masked_label, names_overlap,
                        preferred_account_key, slug,
                        usable_full_number)
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
    candidates: tuple[str, ...] = ()
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


def _learned_alias_matches(core: ProjectionCore, key: str, names: list[str],
                           account_ref: str, kind: str) -> bool:
    """Whether a new-style alias covers this holder/product signature."""
    evidence = core._alias_evidence.get(key)
    if evidence is None:
        return False
    if evidence.get("kind") and evidence["kind"] != kind:
        return False
    learned_names = evidence.get("names") or []
    holders_match = ((not names and not learned_names)
                     or names_overlap(names, learned_names))
    learned_label = evidence.get("label", "")
    exact_label = slug(account_ref)
    labels_match = (bool(exact_label) and exact_label == slug(learned_label))
    return (holders_match
            and (labels_match
                 or account_labels_overlap(account_ref, learned_label)))


def resolve(core: ProjectionCore, institution: str, account_number: str,
            account_ref: str, names: list[str],
            kind: str = "depository", doc_id: str = "") -> Resolution:
    """Return the same, new, or ambiguous account for these identity signals."""
    key = account_key(institution, account_number, account_ref)
    preferred = preferred_account_key(institution, account_number, account_ref)
    decided = core._document_account_aliases.get(doc_id) if doc_id else None
    if decided:
        decided_state = core._acct.get(decided)
        kind_scoped_new = decided.startswith(f"acct:{slug(kind)}:")
        if ((decided_state is not None and decided_state.seen
             and decided_state.kind == kind)
                or (decided_state is None and kind_scoped_new)):
            return Resolution(decided, key, "same")
    if conflicting_number_signals(account_number, account_ref):
        return Resolution(
            preferred, key, "ambiguous",
            reason=("the extracted account number and the printed last four "
                    "disagree, so neither can safely identify the account"))
    mine_number = identity_number_key(account_number, account_ref)
    mine_full = usable_full_number(account_number)
    known = [(aid, state) for aid, state in core._acct.items()
             if state.seen and state.kind == kind]

    # A usable full number is the strongest signal. It remains authoritative
    # across issuer display-name changes and old vaults whose ids were derived
    # from a different display label.
    if len(mine_full) > 4:
        for aid, state in known:
            their_full = usable_full_number(state.number)
            if their_full and mine_full == their_full:
                return Resolution(aid, key, "same")

    # Match the lossy number signal only against accounts not disproved by two
    # different full numbers. This supports masked-to-full transitions while
    # refusing to collapse a genuine full-number collision.
    number_candidates = []
    if mine_number:
        for aid, state in known:
            their_number = identity_number_key(state.number, state.name)
            their_full = usable_full_number(state.number)
            if not (their_number and mine_number == their_number):
                continue
            candidate_key = account_key(
                state.institution, state.number, state.name)
            if (candidate_key != key
                    and not institution_names_overlap(
                        institution, state.institution)):
                continue
            if mine_full and their_full and mine_full != their_full:
                continue
            number_candidates.append((aid, state))

    if len(number_candidates) == 1:
        aid, state = number_candidates[0]
        # A prior one-candidate ruling is safe to reuse: it names the only
        # account compatible with this number signal. Multi-candidate signals
        # deliberately never reach the learned map below.
        alias_scope_matches = (
            key not in core._alias_evidence
            or _learned_alias_matches(core, key, names, account_ref, kind))
        if (core._aliases.get(key) == aid and alias_scope_matches
                and not (mine_full and not usable_full_number(state.number))):
            return Resolution(aid, key, "same")
        holders_compatible = (not names and not state.names) or names_overlap(
            names, state.names)
        compatible = (holders_compatible
                      and account_labels_overlap(account_ref, state.name))
        # Shared trailing digits are never enough on their own. A full number
        # can enrich a masked identity only when holder and product agree too.
        if compatible:
            return Resolution(aid, key, "same")
        who = masked_label(state.name or aid)
        return Resolution(
            preferred, key, "ambiguous", candidate=aid,
            candidate_name=who, candidates=(aid,),
            reason=(f"the trailing digits and institution match {who}, but "
                    "the holder or product evidence is not strong enough to "
                    "merge them safely"))
    if len(number_candidates) > 1:
        strong = [
            (aid, state) for aid, state in number_candidates
            if ((not names and not state.names)
                or names_overlap(names, state.names))
            and account_labels_overlap(account_ref, state.name)
        ]
        if len(strong) == 1:
            return Resolution(strong[0][0], key, "same")
        return Resolution(
            preferred, key, "ambiguous",
            candidates=tuple(aid for aid, _state in number_candidates),
            reason=("the available trailing digits identify more than one "
                    "account, and this statement does not contain enough "
                    "information to choose safely"))

    # Learned rulings and exact label keys are consulted only after number
    # ambiguity is ruled out. A lossy alias must never silently select one of
    # multiple accounts sharing the same trailing digits.
    target = core._aliases.get(key)
    target_state = core._acct.get(target) if target else None
    evidence_safe = (key not in core._alias_evidence
                     or _learned_alias_matches(
                         core, key, names, account_ref, kind))
    if target == preferred and target_state is None:
        # A confirmed-new target may not exist until this document posts.
        return Resolution(target, key, "same")
    if (evidence_safe and target_state is not None and target_state.seen
            and target_state.kind == kind):
        target_full = usable_full_number(target_state.number)
        if not (mine_full and target_full and mine_full != target_full):
            return Resolution(target, key, "same")
    state = core._acct.get(preferred)
    if (not mine_number and state is not None and state.seen
            and state.kind == kind):
        return Resolution(preferred, key, "same")

    for aid, state in known:                       # name overlaps another account?
        their_full = usable_full_number(state.number)
        if mine_full and their_full and mine_full != their_full:
            continue
        if not (state.names and names_overlap(names, state.names)):
            continue
        their_number = identity_number_key(state.number, state.name)
        if mine_number and their_number and mine_number != their_number:
            continue                               # two numbers, two accounts
        if not mine_number and not their_number:
            mine_label, their_label = slug(account_ref), slug(state.name)
            if mine_label and their_label and mine_label != their_label:
                continue                           # two products, two accounts
        who = masked_label(state.name or aid)
        return Resolution(
            preferred, key, "ambiguous", candidate=aid, candidate_name=who,
            candidates=(aid,),
            reason=(f"a holder name matches {who}, and nothing stronger "
                    "tells them apart"))
    return Resolution(preferred, key, "new")


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
