"""One descriptor in, one decomposition out — the only door to the four layers.

Everything downstream of a bank line — the merchant catalog, the stream engine,
the question queue — needs the same three things from it: who the counterparty
was, whether that counterparty is a person, and what may leave the machine. Before
this module there were three different answers available (the normalizer's key,
Layer 0's brand candidate, an induced grammar's `{brand}` slot) and no statement
of which one wins. Three answers to one question is how two totals of the same
population come to disagree, which has been a bug in this codebase before.

So there is one function, and it applies the layers in a fixed order, each
answering only what it can prove:

    refused        a wire dump — no layer may claim it; it stays local and whole
    Layer 1        an induced grammar for THIS bank, if one exists
    Layer 1'       a grammar induced for ANOTHER bank that explains this line
    Layer 0        published card and NACHA rules, which need no grammar
    the normalizer the deterministic fallback that has always been there

A BORROWED grammar is still a grammar and is recorded as one, because it is
structurally the same claim: the same closed vocabulary, the same compiled
expression, the same rule that a person is whatever landed in a slot named for
one. What differs is only where it came from, so that rides along in
`borrowed_from` rather than becoming a weaker layer. This matters most for an
account too small to induce from — twenty distinct lines can never teach a
grammar, and can perfectly well be explained by one.

The result carries **where each field came from**, because "Costco, from a
grammar slot" and "Costco, from stripping punctuation" are different claims and
only the first is worth publishing. That is T1 applied below the ledger.

What this module does NOT do is decide identity. A brand *candidate* is a string
a bank printed; a brand is a thing in the world, and only the knowledge base can
say they are the same. This hands over a candidate, always.
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
    """What one descriptor decomposed into, and how much of that is believable."""

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
        """True only when a slot *declared* it — never inferred from the text.

        The whole point of the vocabulary is that this question is answered by
        the name of the slot the text came out of, not by looking at the text."""
        return bool(self.counterparty)

    @property
    def rail(self) -> str:
        """What to key a stream on alongside the counterparty.

        A proven channel when one exists. Otherwise — and this is the part that
        replaces the deleted keyword table — **the template**, when a grammar
        matched. Two lines produced by one template came off one rail by
        construction, so the template separates an ATM withdrawal from a cheque
        without this package ever containing the words "ATM" or "cheque". The
        bank supplied the distinction; we only noticed it."""
        if self.channel != "unknown":
            return self.channel
        return f"tmpl:{self.template}" if self.template else "unknown"

    @property
    def key(self) -> str:
        """The stream and catalog key, until a brand key resolves (see the
        two-key model). Falls back down the layers rather than returning
        nothing, because a line we cannot decompose is still a line that
        recurs."""
        return self.local_key or normalize_merchant(self.raw) or (self.raw or "").strip().lower()

    def shareable(self) -> dict:
        """Everything impersonal, including the brand candidate. Never the
        counterparty, never a personal slot, never the raw line."""
        out = {k: v for k, v in self.fields.items() if v}
        if self.brand:
            out["brand"] = self.brand
        return out

    def example(self) -> str:
        """The most that may cross to a model that identifies brands.

        A grammar's brand slot when there is one — it is bounded by construction.
        Otherwise the Layer 0 lint, which is bounded by removing everything
        provable and every digit. A refused line offers nothing at all."""
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


# Which rail carried a movement, decided by STRUCTURE and never by words.
#
# An earlier version of this matched `\bcard purchase\b`, `\batm\b`,
# `\bpaper check\b`. That is a raw-text keyword table doing classification —
# the exact thing `is_shareable` was, with the same defect: it classifies by
# language, so it is silently wrong on the first non-English statement, and the
# channel is half the stream key. It is gone.
#
# What replaces it claims a rail only where a published format proves one:
#
#   ach    the NACHA batch tail parsed itself
#   wire   two or more Fedwire message tags
#   card   an ISO 8583 DE43 structure fired — the trailing region subfield, the
#          processor asterisk at 3/7/12, or a phone/URL in the city slot
#   p2p    a grammar put a PERSON in a slot named for one
#
# Everything else is `unknown`, and stays `unknown`. That loses the ATM and
# cheque distinctions Layer 0 used to guess at, deliberately: an induced grammar
# recovers them for free, because two lines matching the same template came off
# the same rail by construction, and the template is derived from the bank's own
# statement rather than written here in English.
_DE43_RULES = frozenset({"de43_region_tail", "asterisk_at_3", "asterisk_at_7",
                         "asterisk_at_12", "phone_in_city_slot", "url_in_city_slot"})


def channel_of(descriptor: str, parse=None) -> str:
    """Which rail carried this, from evidence only.

    `unknown` is a legitimate answer and stays one — a stream keyed on a guessed
    channel is a stream split by a mistake, and a wrong split is harder to notice
    than a missing one."""
    p = parse or parse_descriptor(descriptor or "")
    if p.never_templatable:
        return "wire"
    if p.ach:
        return "ach"
    if _DE43_RULES.intersection(p.rules):
        return "card"
    return "unknown"


def _slot_from(res: Resolution, match, parse, ach_split, raw: str) -> Resolution:
    """Fill a resolution from a grammar match. One body, two callers — the
    bank's own grammar and a borrowed one decompose identically, and writing it
    twice is how they would come to differ."""
    res.layer, res.template = "grammar", match.template
    res.fields = match.shareable()
    res.personal = match.personal()
    # However the sender addressed them — a name, a phone, an email, a
    # username, or a contact slot sitting where the party belongs.
    res.counterparty = match.party()
    res.brand = (res.fields.get("brand") or res.fields.get("institution") or "")
    # A rail that carries people is a rail the GRAMMAR identified as such,
    # by putting a person in a slot named for one. Not a list of app names —
    # that list is the thing this design deleted, and it does not survive
    # a new country.
    if res.counterparty and res.channel in ("unknown", "ach"):
        res.channel = "p2p"
    # A grammar usually makes the NACHA Company Entry Description part of
    # its literal text — `{brand} PAYROLL PPD ID: {company_id}` — because
    # that is what it is. Correct, and it means the field vanishes from the
    # slots, where Layer 0 had it. Recovered here so the better layer does
    # not quietly return less than the worse one.
    if parse.ach and ach_split and raw in ach_split:
        _name, entry = ach_split[raw]
        if entry:
            res.fields.setdefault("entry_description", entry)
    return res


def resolve_descriptor(descriptor: str, profile=None, ach_split=None,
                       borrowed=None) -> Resolution:
    """Decompose one bank line, using the best layer that can prove its claim.

    `profile` is an induced grammar for the (institution × kind) this line came
    from, or None. None is the ordinary case today and must stay a working one:
    a bank whose grammar has not been induced is not a bank the product refuses
    to serve.

    `ach_split` is `split_ach_heads()` over the whole statement, or None. It is
    corpus-level by necessity — the Company Name / Entry Description boundary
    does not exist on any single line — so it is passed in rather than computed
    here.

    `borrowed` is other institutions' grammars, tried only after this one's has
    failed. A sentence shape is not the exclusive property of the bank it was
    learned from, and an account with twenty distinct lines will never teach a
    grammar while being perfectly explicable by one. Own first, always: a bank's
    own grammar was measured against its own lines, and a borrowed one was not."""
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

    # Layer 1 — an induced grammar. It claims the WHOLE line or nothing, so a
    # match is a decomposition with no residue to explain away.
    match = profile.apply(raw) if profile is not None else None
    if match is not None:
        return _slot_from(res, match, parse, ach_split, raw)

    # Layer 1' — somebody else's grammar. Tried in a fixed order so the answer
    # does not depend on how a dict happened to iterate.
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
    # No attempt is made here to strip the bank's own sentence words. A rule
    # that did was removed after a real vault showed the three populations —
    # bank words, geography and merchants — are interleaved by frequency, so no
    # cut separates them, and a cut low enough to catch the ACH markers deletes
    # merchant names. Under-cleaning leaves an ugly key; over-cleaning destroys
    # an identity, and only one of those is recoverable.
    res.brand = brand_candidate(parse)

    if parse.ach and ach_split and raw in ach_split:
        # The statement-level split, when it was computed. The Entry Description
        # is the originator's own word for the movement ("Payroll", "Assn Dues")
        # and is the single most informative field in an ACH line — far more so
        # than the SEC code, which says only that the debit was prearranged.
        name, entry = ach_split[raw]
        if name:
            res.brand = name
        if entry:
            res.fields["entry_description"] = entry
    if not res.brand:
        # Nothing provable and nothing left over: the normalizer is all there is,
        # and saying so is more useful than an empty brand that reads as absent
        # rather than as unresolved.
        res.layer = "normalizer"
        res.brand = res.local_key
    return res
