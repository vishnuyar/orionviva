"""Resolving a whole vault's descriptors to the keys merchant knowledge is
filed under.

Enrichment files what it learns under a brand — `costco`, not
`POS DEBIT 0912 COSTCO WHSE #114 CITYVILLE 06/12`. Naming the brand takes the
four resolution layers, and the best of them is an induced grammar, which lives
on disk rather than in the event log. So the projection cannot compute a
merchant key from an event alone; something has to hand it the grammars.

That is what a *resolver* is: a callable the projection is constructed with,
which takes every (account, institution, kind, descriptor) row the ledger holds
and returns the key each line is filed under, plus the lines a grammar slot
declared a person on — the one fact about a line that no read can recover for
itself, for the same reason. A projection built without a resolver falls back
to normalizing the descriptor and knows of no persons, which is what every read
did before grammars existed and remains correct wherever no grammar has been
induced.

The corpus, not the line, is the unit: the ACH company-name boundary does not
exist on any single descriptor, so it is computed once over all of them and
passed into each resolution — exactly as the stream engine does it. Two callers
resolving the same vault differently is the failure this module exists to
prevent, so both go through `resolve_descriptor` with the same corpus.
"""

from __future__ import annotations

from merchantcore.descriptor import split_ach_heads
from merchantcore.resolve import resolve_descriptor


class MerchantKeys(dict):
    """`{(account, descriptor): merchant key}`, carrying which of those lines a
    slot declared a person on.

    A mapping first: every read wants the key, and a person's line has one like
    any other. `persons` holds the `(account, descriptor)` pairs a grammar slot
    named a party on — the same declaration the stream engine reads, and the
    one thing only a resolver can state, because only a resolver holds the
    grammars. It is empty wherever no grammar has named a line.
    """

    def __init__(self, keys=(), persons=()) -> None:
        super().__init__(keys)
        self.persons = frozenset(persons)


def resolve_keys(rows, profile_for=None) -> MerchantKeys:
    """`{(account, descriptor): merchant key}` for a whole vault, as a
    `MerchantKeys` — the mapping, plus the lines a slot named a party on.

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
        key = res.merchant_key
        if key:
            out[(account, descriptor)] = key
    return MerchantKeys(out, persons)


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
