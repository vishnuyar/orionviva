"""Decompose descriptors through grammar, published and fallback layers.

The result carries provenance, person declarations and exact identity
candidates. Permanent merchant identity is resolved by the catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .descriptor import (brand_candidate, is_never_templatable, linted_example,
                         parse_descriptor)
from .normalize import is_shareable, normalize_merchant
from .profile import PERSONAL_SLOTS

RESOLVER_VERSION = "resolve-v1"

# Ordered best to worst. A caller comparing two resolutions compares these.
LAYERS = ("grammar", "published", "normalizer", "refused")


@dataclass
class Resolution:
    """What one descriptor decomposed into, and which layer produced it."""

    raw: str
    layer: str = "normalizer"
    local_key: str = ""                  # the deterministic per-user key (merch-v2)
    brand: str = ""                      # a CANDIDATE for the counterparty's name
    counterparty: str = ""               # set only when a slot said "a person"
    channel: str = "unknown"
    fields: dict = field(default_factory=dict)      # impersonal slots
    personal: dict = field(default_factory=dict)    # slots declared personal
    template: str = ""
    borrowed_from: str = ""              # profile id, when another bank's grammar explained it
    refused: bool = False
    identity_candidates: tuple[str, ...] = ()

    @property
    def is_person(self) -> bool:
        """True only when a slot declared it; never inferred from the text.

        Equivalently, whether `counterparty` is set — which only a grammar
        match can do."""
        return bool(self.counterparty)

    @property
    def rail(self) -> str:
        """What to key a stream on alongside the counterparty, from this line
        alone. `rail_of` is the same answer with the rest of the corpus in
        hand."""
        return rail_of(self)

    @property
    def key(self) -> str:
        """The local stream key before a reviewed alias resolves an identity.

        The local key, else the normalized raw line, else the raw line
        lowercased — never empty for a non-empty descriptor, because a line
        that cannot be decomposed still recurs."""
        return self.local_key or normalize_merchant(self.raw) or (self.raw or "").strip().lower()

    @property
    def merchant_key(self) -> str:
        """Return the normalized brand or the stable local fallback key.

        ``identity_candidates`` may later resolve to a permanent catalog id.
        """
        return normalize_merchant(self.brand) or self.key

    def shareable(self) -> dict:
        """The non-empty impersonal fields, plus `brand` when there is one.

        Never the counterparty, never a personal slot, never the raw line."""
        out = {k: v for k, v in self.fields.items() if v}
        if self.brand:
            out["brand"] = self.brand
        return out

    def example(self) -> str:
        """The most that may cross to a model that identifies brands.

        The grammar's brand slot when the layer is `grammar`; otherwise the
        Layer 0 lint over the raw line. A refused line yields ""."""
        if self.refused:
            return ""
        return self.brand if self.layer == "grammar" else linted_example(self.raw)

    def to_dict(self) -> dict:
        return {"layer": self.layer, "local_key": self.local_key,
                "brand": self.brand, "channel": self.channel,
                "is_person": self.is_person, "refused": self.refused,
                "template": self.template, "borrowed_from": self.borrowed_from,
                "fields": dict(self.fields),
                "resolver_version": RESOLVER_VERSION}


# Which rail carried a movement. A rail is claimed only where a published format
# proves one:
#
#   ach    the NACHA batch tail parsed itself
#   wire   two or more Fedwire message tags
#   card   an ISO 8583 DE43 structure fired — the trailing region subfield, the
#          processor asterisk at 3/7/12, or a phone/URL in the city slot
#   p2p    a grammar put a person in a slot named for one
#
# Everything else is `unknown` and stays `unknown`.
#
# Channel classification uses proved structure rather than descriptor words.
_DE43_RULES = frozenset({"de43_region_tail", "asterisk_at_3", "asterisk_at_7",
                         "asterisk_at_12", "phone_in_city_slot", "url_in_city_slot"})


def rail_of(res: "Resolution", proven=()) -> str:
    """What to key a stream on alongside the counterparty.

    In order: the channel this line proves; failing that the channel `proven`
    for the same counterparty's other lines, when those agree on exactly one;
    failing that `tmpl:<template>` when a grammar matched; otherwise "unknown".
    Two lines produced by one template came off one rail by construction, so
    where nothing about this counterparty is proven the template separates an
    ATM withdrawal from a cheque without either word appearing here.

    `proven` is the set of channels the caller has seen proven for this
    counterparty, which one line cannot know by itself; an empty one asks only
    about this line."""
    if res.channel != "unknown":
        return res.channel
    elsewhere = {c for c in proven if c and c != "unknown"}
    if len(elsewhere) == 1:
        return elsewhere.pop()
    return f"tmpl:{res.template}" if res.template else "unknown"


def channel_of(descriptor: str, parse=None) -> str:
    """Which rail carried this: "wire", "ach", "card", or "unknown".

    From the Layer 0 parse only; `parse` is reused when supplied. Never returns
    "p2p" — that is added by `resolve_descriptor` when a grammar names a person.
    `unknown` is a legitimate answer."""
    p = parse or parse_descriptor(descriptor or "")
    if p.never_templatable:
        return "wire"
    if p.ach:
        return "ach"
    if _DE43_RULES.intersection(p.rules):
        return "card"
    return "unknown"


def corroborates_a_business(descriptor: str, ach_split=None) -> bool:
    """Whether a published format says the other side of THIS line is a business.

    A slot name may say a hole holds a person; it may not, by itself, say a
    hole holds a business. This is what stands beside that claim:

        card   an ISO 8583 DE43 structure fired, and the network specifies its
               acceptor as a merchant
        ach    a NACHA line whose Company Name field came back with a value

    Read per line. A format proven by another line of the same counterparty
    corroborates nothing here, and "no" is a legitimate answer.

    The two clauses are not equally strong. The Company Name boundary is not
    printed on the line, so `split_ach_heads` recovers it from the statement as
    a whole, and any ACH line with a non-empty head satisfies that clause —
    including one whose head is a person's name. `ach_split` is that map, or
    None to leave the clause unsatisfiable."""
    if channel_of(descriptor) == "card":
        return True
    name, _entry = (ach_split or {}).get(descriptor, ("", ""))
    return bool(name)


def _slot_from(res: Resolution, match, parse, ach_split, raw: str) -> Resolution:
    """Fill a resolution from a grammar match, and return it.

    One body, two callers: the bank's own grammar and a borrowed one decompose
    identically."""
    res.layer, res.template = "grammar", match.template
    res.fields = match.shareable()
    res.personal = match.personal()
    # However the sender addressed them — a name, a phone, an email, a
    # username, or a contact slot sitting where the party belongs.
    res.counterparty = match.party()
    # Only a brand slot names a brand. An institution is the conduit the money
    # crossed, not the party at the other end, so it is not read as one: where a
    # grammar names no brand, `merchant_key` falls back to the whole line, which
    # still carries whoever was on it.
    res.brand = res.fields.get("brand") or ""
    # A peer rail is one the grammar identified as such, by putting a person in
    # a slot named for one. A proven card or wire channel is not overwritten.
    if res.counterparty and res.channel in ("unknown", "ach"):
        res.channel = "p2p"
    # A grammar usually makes the NACHA Company Entry Description part of its
    # literal text — `{brand} PAYROLL PPD ID: {company_id}` — so the field
    # leaves the slots, where Layer 0 had it. Recovered here.
    if parse.ach and ach_split and raw in ach_split:
        _name, entry = ach_split[raw]
        if entry:
            res.fields.setdefault("entry_description", entry)
    return res


def _with_identity_candidates(res: Resolution, parse) -> Resolution:
    """Attach the exact normalized strings eligible for reviewed alias lookup."""
    if res.refused or res.is_person or not is_shareable(res.raw):
        res.identity_candidates = ()
        return res
    candidates: list[str] = []

    def add(value: str) -> None:
        key = normalize_merchant(value)
        if key and key not in candidates:
            candidates.append(key)

    add(res.brand)
    if parse.clean:
        add(brand_candidate(parse))
    store = next((slot for slot in parse.slots
                  if slot.name == "store_number"), None)
    if store is not None:
        add(res.raw[:store.start])
    add(res.local_key)
    res.identity_candidates = tuple(candidates)
    return res


def resolve_descriptor(descriptor: str, profile=None, ach_split=None,
                       borrowed=None) -> Resolution:
    """Decompose one bank line, using the best layer that can prove its claim.

    `profile` is an induced grammar for the (institution × kind) this line came
    from, or None. None is the ordinary case and a working one: a bank whose
    grammar has not been induced still resolves through Layer 0.

    `ach_split` is `split_ach_heads()` over the whole statement, or None. It is
    corpus-level by necessity — the Company Name / Entry Description boundary
    does not exist on any single line — so it is passed in rather than computed
    here.

    `borrowed` is other institutions' grammars, tried in profile-id order and
    only after `profile` has failed, so the bank's own grammar always wins. A
    borrowed match sets `borrowed_from` and still reports layer `grammar`.

    Never raises. An empty descriptor comes back as an empty Resolution."""
    raw = (descriptor or "").strip()
    res = Resolution(raw=raw, local_key=normalize_merchant(raw))
    if not raw:
        return res

    parse = parse_descriptor(raw)
    res.channel = channel_of(raw, parse)

    # A wire is refused every layer. Checked first so no grammar and no
    # published rule can claim a field the sender typed freely.
    if is_never_templatable(raw):
        res.layer, res.refused = "refused", True
        return _with_identity_candidates(res, parse)

    # Layer 1 — an induced grammar. It claims the whole line or nothing, so a
    # match is a decomposition with no residue to explain away.
    match = profile.apply(raw) if profile is not None else None
    if match is not None:
        return _with_identity_candidates(
            _slot_from(res, match, parse, ach_split, raw), parse)

    # Layer 1' — somebody else's grammar, in a fixed order so the answer does
    # not depend on how a collection happened to iterate.
    for other in sorted(borrowed or [], key=lambda p: p.id):
        if profile is not None and other.id == profile.id:
            continue
        match = other.apply(raw)
        if match is not None:
            res.borrowed_from = other.id
            return _with_identity_candidates(
                _slot_from(res, match, parse, ach_split, raw), parse)

    # Layer 0 — published rules. They cannot claim the merchant name (no
    # specification says where it ends), so the brand is a candidate from what
    # is left, and the fields are only what a rule proved.
    res.layer = "published"
    res.fields = {sl.name: sl.text for sl in parse.slots
                  if sl.name not in PERSONAL_SLOTS and sl.name != "reference"}
    # The bank's own sentence words are not stripped here; separating them from
    # a merchant name is Layer 1's job.
    res.brand = brand_candidate(parse)

    if parse.ach and ach_split and raw in ach_split:
        # The statement-level split, when it was computed. The Entry
        # Description is the originator's own word for the movement
        # ("Payroll", "Assn Dues"), so it carries more than the SEC code, which
        # says only that the debit was prearranged.
        name, entry = ach_split[raw]
        if name:
            res.brand = name
        if entry:
            res.fields["entry_description"] = entry
    if not res.brand:
        # Nothing provable and nothing left over. Reported as layer
        # `normalizer` rather than as a `published` parse with an empty brand.
        res.layer = "normalizer"
        res.brand = res.local_key
    return _with_identity_candidates(res, parse)
