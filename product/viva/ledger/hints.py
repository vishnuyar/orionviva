"""What crosses to enrichment, built from streams rather than from descriptors.

A stream already knows who the counterparty is, whether they are a person, and
whether there is a counterparty at all, so this module asks the stream engine
rather than walking raw movements.

**The gate is a slot, where a grammar exists.** A stream is withheld because a
slot said a person is in it: the grammar's `{counterparty}` or
`{counterparty_handle}`.

**Where no grammar exists, `is_shareable` is the fallback.** Without a grammar
there is no slot to say a line holds a person, so the substring list stands in.
It over-blocks by design: its errors cost enrichment coverage rather than
somebody's name, and inducing a grammar for that institution retires it there.

**The key is the brand, not the descriptor.** Two locations of one retailer are
one key and one record.

**The payload is named slots, not a string.** Enrichment receives only slots
that are impersonal by declaration, and only those values the brand agreed on
across every occurrence — what varies belongs to the visit, what does not
belongs to the counterparty. The NACHA entry description (`Payroll`,
`Assn Dues`) is the originator's own word for what it is, and it travels.

Three kinds of stream never cross: a **person**, a **wire** (refused at every
layer), and anything **internal or activity** — there is no merchant to learn
about in a payment to your own card or a line describing a capital gain.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from merchantcore.normalize import is_shareable, normalize_merchant

from .streams import ACTIVITY, COUNTERPARTY, INTERNAL, MIXED

# Slots worth sending. The rule for keeping one: a value travels only if every
# occurrence of the brand agrees on it, so what belongs to the brand crosses and
# what belongs to a visit does not. A restaurant seen in one city keeps its
# city; a chain seen in five has none.
CONTEXT_SLOTS = ("entry_description", "sec_code", "purpose", "contact",
                 "city", "region")


@dataclass
class Hint:
    """One brand offered for enrichment, with impersonal context and nothing else."""

    key: str                      # normalized brand — the catalog/commons key
    brand: str                    # as the statement prints it
    context: dict = field(default_factory=dict)
    channels: set = field(default_factory=set)
    movements: int = 0
    layer: str = "normalizer"     # which layer named it: grammar > published > normalizer
    _values: dict = field(default_factory=dict, repr=False)   # slot -> values seen

    def example(self) -> str:
        """What a model is shown: the brand, then context in a fixed order, then
        the rails — so two vaults that saw the same merchant compose the same
        string."""
        parts = [self.brand]
        parts += [f"{k}={self.context[k]}" for k in CONTEXT_SLOTS if self.context.get(k)]
        if self.channels:
            parts.append("rail=" + "/".join(sorted(self.channels)))
        return " · ".join(parts)

    def to_dict(self) -> dict:
        return {"key": self.key, "brand": self.brand, "context": dict(self.context),
                "channels": sorted(self.channels), "movements": self.movements,
                "layer": self.layer}


def enrichment_hints(streams) -> dict:
    """`{brand key: Hint}` — everything a model may be asked about.

    Withholding is by structure, never by inspection:

      a person       a slot named one; the name never leaves this machine
      a wire         refused every layer, because its free-text field is
                     unbounded and no slot name can honour it
      internal       the other side is an account of yours
      activity       an investment line, which names no party

    A `mixed` stream still crosses: it is one counterparty with some links
    missing, and the merchant behind it is as real as any other.

    Each hint's `context` holds only slot values every occurrence agreed on."""
    out: dict = {}
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
        hint = out.get(key)
        if hint is None:
            hint = Hint(key=key, brand=brand, layer=s.layer)
            out[key] = hint
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
    for hint in out.values():
        # Unanimous or absent. A brand with two cities has no city.
        hint.context = {k: next(iter(v)) for k, v in hint._values.items()
                        if len(v) == 1}
    return out


_ORDER = {"grammar": 3, "published": 2, "normalizer": 1, "refused": 0}


def _rank(layer: str) -> int:
    return _ORDER.get(layer or "", 0)
