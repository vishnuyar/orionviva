"""Build impersonal enrichment hints from resolved streams.

Person, wire, internal and activity streams are withheld. Grammar brands
require published-format corroboration; other lines use ``is_shareable``.
Hints retain unresolved keys and exact identity candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from merchantcore.descriptor import split_ach_heads
from merchantcore.normalize import is_shareable, normalize_merchant
from merchantcore.resolve import corroborates_a_business

from .streams import ACTIVITY, COUNTERPARTY, INTERNAL, MIXED

# Slots worth sending. The rule for keeping one: a value travels only if every
# occurrence of the brand agrees on it, so what belongs to the brand crosses and
# what belongs to a visit does not. A restaurant seen in one city keeps its
# city; a chain seen in five has none.
CONTEXT_SLOTS = ("entry_description", "sec_code", "purpose", "contact",
                 "city", "region")


@dataclass
class Hint:
    """One unresolved merchant offered with impersonal context and nothing else."""

    key: str                      # unresolved local/model filing key
    brand: str                    # structural brand candidate, where one exists
    context: dict = field(default_factory=dict)
    channels: set = field(default_factory=set)
    movements: int = 0
    layer: str = "normalizer"     # which layer named it: grammar > published > normalizer
    identity_candidates: list[str] = field(default_factory=list)
    _values: dict = field(default_factory=dict, repr=False)   # slot -> values seen

    def example(self) -> str:
        """Return brand, ordered context and sorted rails as one model input."""
        parts = [self.brand]
        parts += [f"{k}={self.context[k]}" for k in CONTEXT_SLOTS if self.context.get(k)]
        if self.channels:
            parts.append("rail=" + "/".join(sorted(self.channels)))
        return " · ".join(parts)

    def to_dict(self) -> dict:
        return {"key": self.key, "brand": self.brand, "context": dict(self.context),
                "channels": sorted(self.channels), "movements": self.movements,
                "layer": self.layer,
                "identity_candidates": list(self.identity_candidates)}


def enrichment_hints(streams) -> dict:
    """`{unresolved stream key: Hint}` — everything a model may be asked about.

    Withholding is by structure, never by inspection:

      a person       a slot named one; the name never leaves this machine
      a wire         refused every layer, because its free-text field is
                     unbounded and no slot name can honour it
      internal       the other side is an account of yours
      activity       an investment line, which names no party

    A `mixed` stream still crosses: it is one counterparty with some links
    missing, and the merchant behind it is as real as any other.

    A brand a grammar named crosses only where a published format corroborates
    it on every line behind it — see `_named_by_a_slot`. One uncorroborated
    occurrence withholds the whole hint, whatever else contributed to it.

    Each hint's `context` holds only slot values every occurrence agreed on."""
    streams = list(streams)
    # The NACHA name/description split needs the statement as a whole, so it is
    # computed once over every line behind these streams rather than per line.
    ach_split = split_ach_heads(o.description
                                for s in streams for o in s.occurrences)
    out: dict = {}
    withheld: set = set()
    for s in streams:
        if s.is_person or s.refused:
            continue
        if s.role not in (COUNTERPARTY, MIXED):
            continue
        # No grammar named this counterparty, so no slot vouched for it: fall
        # back to the conservative list, which over-blocks by design.
        if s.layer != "grammar" and not all(
                is_shareable(o.description) for o in s.occurrences):
            continue
        brand = (s.brand or s.counterparty or "").strip()
        key = normalize_merchant(brand)
        if not key:
            continue
        # A model's word that a hole holds a business, standing alone, is not
        # enough to send it. Corroboration is read from each line, so a rail
        # proven by a sibling certifies nothing here.
        if _named_by_a_slot(s) and not all(
                corroborates_a_business(o.description, ach_split)
                for o in s.occurrences):
            withheld.add(key)
            continue
        hint = out.get(key)
        if hint is None:
            hint = Hint(key=key, brand=brand, layer=s.layer,
                        identity_candidates=list(s.identity_candidates))
            out[key] = hint
        else:
            hint.identity_candidates = list(dict.fromkeys(
                [*hint.identity_candidates, *s.identity_candidates]))
        # A grammar's reading of a brand beats a published rule's, which beats
        # the normalizer's. The winning layer is recorded on the hint.
        if _rank(s.layer) > _rank(hint.layer):
            hint.layer, hint.brand = s.layer, brand
        hint.movements += s.n
        hint.channels.add(s.channel if not s.channel.startswith("tmpl:") else "grammar")
        for slot in CONTEXT_SLOTS:
            for value in s.field_values.get(slot, ()):
                if value.strip():
                    hint._values.setdefault(slot, set()).add(value.strip())
        if s.entry_description:
            hint._values.setdefault("entry_description", set()).add(s.entry_description)
    # Brand and context leave together or not at all: emitting the rest of a
    # hint whose brand was withheld still sends whatever a context slot holds.
    for key in withheld:
        out.pop(key, None)
    for hint in out.values():
        # Unanimous or absent. A brand with two cities has no city.
        hint.context = {k: next(iter(v)) for k, v in hint._values.items()
                        if len(v) == 1}
    return out


def _named_by_a_slot(stream) -> bool:
    """Whether this stream's brand came out of a grammar's brand slot.

    True means the claim that a business is on the other side rests on a model's
    label. A published rule's reading and the whole-line fallback are not this,
    and are not gated by corroboration."""
    return stream.layer == "grammar" and bool(stream.brand)


_ORDER = {"grammar": 3, "published": 2, "normalizer": 1, "refused": 0}


def _rank(layer: str) -> int:
    return _ORDER.get(layer or "", 0)
