"""One descriptor in, one decomposition out — the only door to the four layers.

Everything downstream of a bank line — the merchant catalog, the stream engine,
the question queue — needs the same three things from it: who the counterparty
was, whether that counterparty is a person, and what may leave the machine.
`resolve_descriptor` is the single answer, and it applies the layers in a fixed
order, each answering only what it can prove:

    refused        a wire dump — no layer may claim it; it stays local and whole
    Layer 1        an induced grammar for this bank, if one exists
    Layer 1'       a grammar induced for another bank that explains this line
    Layer 0        published card and NACHA rules, which need no grammar
    the normalizer the deterministic fallback

A borrowed grammar is recorded as layer `grammar`, not as a weaker layer name:
it is structurally the same claim — the same closed vocabulary, the same
compiled expression, the same rule that a person is whatever landed in a slot
named for one — and downstream privacy checks key on that word. Where it came
from rides in `borrowed_from`.

The result carries which layer produced each field: "a brand from a grammar
slot" and "a brand from stripping punctuation" are different claims.

Identity is not decided here. A brand candidate is a string a bank printed;
only the knowledge base can say it and a brand are the same thing.

Design rationale: docs/the-conduit-and-the-counterparty.md
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .descriptor import (brand_candidate, is_never_templatable, linted_example,
                         parse_descriptor)
from .normalize import normalize_merchant
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

    @property
    def is_person(self) -> bool:
        """True only when a slot declared it; never inferred from the text.

        Equivalently, whether `counterparty` is set — which only a grammar
        match can do."""
        return bool(self.counterparty)

    @property
    def rail(self) -> str:
        """What to key a stream on alongside the counterparty.

        The proven channel when there is one, otherwise `tmpl:<template>` when
        a grammar matched, otherwise "unknown". Two lines produced by one
        template came off one rail by construction, so the template separates an
        ATM withdrawal from a cheque without either word appearing here."""
        if self.channel != "unknown":
            return self.channel
        return f"tmpl:{self.template}" if self.template else "unknown"

    @property
    def key(self) -> str:
        """The stream and catalog key, until a brand key resolves.

        The local key, else the normalized raw line, else the raw line
        lowercased — never empty for a non-empty descriptor, because a line
        that cannot be decomposed still recurs."""
        return self.local_key or normalize_merchant(self.raw) or (self.raw or "").strip().lower()

    @property
    def merchant_key(self) -> str:
        """The key everything known about this counterparty is filed under: the
        normalized brand a layer named, else `key`.

        Identity is brand-level, so two locations of one retailer are one key.
        Where no layer could name a brand the fallback is the whole descriptor
        normalized, which is what `key` already is — so a line nothing could
        decompose is still filed under something stable.

        One property rather than an expression each caller writes: a merchant
        filed under one key and looked up under another is knowledge that
        cannot be read."""
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
# Constraint: a channel is decided by structure, never by a word in the text.
_DE43_RULES = frozenset({"de43_region_tail", "asterisk_at_3", "asterisk_at_7",
                         "asterisk_at_12", "phone_in_city_slot", "url_in_city_slot"})


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
    res.brand = (res.fields.get("brand") or res.fields.get("institution") or "")
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
        return res

    # Layer 1 — an induced grammar. It claims the whole line or nothing, so a
    # match is a decomposition with no residue to explain away.
    match = profile.apply(raw) if profile is not None else None
    if match is not None:
        return _slot_from(res, match, parse, ach_split, raw)

    # Layer 1' — somebody else's grammar, in a fixed order so the answer does
    # not depend on how a collection happened to iterate.
    for other in sorted(borrowed or [], key=lambda p: p.id):
        if profile is not None and other.id == profile.id:
            continue
        match = other.apply(raw)
        if match is not None:
            res.borrowed_from = other.id
            return _slot_from(res, match, parse, ach_split, raw)

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
    return res
