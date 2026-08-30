"""Resolve a vault's descriptors to merchant keys and identity evidence.

Resolution uses one corpus-wide ACH split and optional installed grammars.
Results include person declarations and exact catalog candidates.
"""

from __future__ import annotations

from merchantcore.descriptor import split_ach_heads
from merchantcore.resolve import resolve_descriptor


class MerchantKeys(dict):
    """Resolved local keys plus person declarations and identity candidates.

    A mapping first: every read wants the key, and a person's line has one like
    any other. `persons` holds the `(account, descriptor)` pairs a grammar slot
    named a party on — the same declaration the stream engine reads, and the
    one thing only a resolver can state, because only a resolver holds the
    grammars. ``candidates`` carries the ordered, structurally justified strings
    an exact reviewed catalog alias may recognize. Both sets are empty where
    privacy or resolution supplied no authority.
    """

    def __init__(self, keys=(), persons=(), candidates=()) -> None:
        super().__init__(keys)
        self.persons = frozenset(persons)
        self.candidates = dict(candidates)


def resolve_keys(rows, profile_for=None) -> MerchantKeys:
    """Resolve a whole vault to local keys, person declarations and candidates.

    `rows` is an iterable of `(account, institution, kind, descriptor)`.
    `profile_for(institution, kind)` returns the induced grammar for that pair
    or None; without it every line resolves through the published rules and the
    normalizer, which is a working case and the only case until a grammar has
    been induced.

    Never raises on a single line: a descriptor that cannot be resolved is
    simply absent from the result, and the caller falls back to normalizing it.
    """
    rows = list(rows)
    ach_split = split_ach_heads(descriptor for _a, _i, _k, descriptor in rows)
    profiles: dict = {}
    out: dict = {}
    persons: set = set()
    candidates: dict = {}
    seen: set = set()
    for account, institution, kind, descriptor in rows:
        if (account, descriptor) in seen:
            continue
        seen.add((account, descriptor))
        pair = (institution or "?", kind or "?")
        if pair not in profiles:
            profiles[pair] = profile_for(*pair) if profile_for else None
        res = resolve_descriptor(descriptor, profiles[pair], ach_split)
        if res.is_person:
            persons.add((account, descriptor))
        candidates[(account, descriptor)] = res.identity_candidates
        key = res.merchant_key
        if key:
            out[(account, descriptor)] = key
    return MerchantKeys(out, persons, candidates)


def installed_resolver():
    """A resolver reading the grammars this installation has induced.

    The one the product wires into a real vault. Returns a callable suitable as
    `LedgerProjection(..., resolve_keys=...)`; the profile store is opened once
    per call, so a grammar induced after a projection was built is picked up the
    next time the vault is opened."""
    from ..induce_profile import profile_store

    def resolve(rows):
        store = profile_store()
        return resolve_keys(rows, profile_for=store.latest_for)

    return resolve
