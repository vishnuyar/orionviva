"""What crosses to enrichment, built from streams rather than from descriptors.

Enrichment used to walk raw movements: key each on `normalize_merchant(raw)`,
gate on a substring list, hand over a linted string. Three things were wrong with
that and all three are fixed by asking the stream engine instead, because a
stream already knows who the counterparty is, whether they are a person, and
whether there is a counterparty at all.

**The gate stops being a word list — where a grammar exists.** A stream is
withheld because a *slot said a person is in it*: the grammar's
`{counterparty}` or `{counterparty_handle}`.

**Where no grammar exists, the word list stays, as a fallback.** This is not a
retreat. Without a grammar there is no slot, so there is nothing to say a line
holds a person, and a peer payment is indistinguishable from a shop. The old
`is_shareable` was wrong as a *primary mechanism* — it decided a question
enrichment exists to answer, using substrings, in one language. It is defensible
as a conservative answer to *"we cannot tell"*, because its errors then cost
enrichment coverage rather than somebody's name. It over-blocks on purpose, and
inducing a grammar for that institution retires it there.

The distinction is the whole point: a rule that guesses in place of knowledge is
a bug; the same rule declining to send when nothing is known is a safeguard.

**The key stops being the descriptor.** Two locations of one retailer are one
brand and one record, not two of each. That is the brand-level identity the
whole field converged on and the catalog never had.

**The payload stops being a string.** Enrichment receives named slots, every one
of them impersonal by declaration rather than by lint, and only those the brand
AGREED on across every occurrence — what varies belongs to the visit, what does
not belongs to the counterparty. The NACHA entry description is the quiet win:
`Payroll`, `Assn Dues`, `Moneyline` is the originator's own word for what they
are, and it costs nothing to pass on.

And three kinds of stream never cross at all: a **person**, a **wire** (refused
every layer), and anything **internal or activity** — there is no merchant to
learn about when the movement is you paying your own card, or a line describing
a capital gain.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from merchantcore.normalize import is_shareable, normalize_merchant

from .streams import ACTIVITY, COUNTERPARTY, INTERNAL, MIXED

# Slots worth sending, and the rule for keeping one: **a value travels only if
# every occurrence of the brand agrees on it.**
#
# This is not a privacy filter — the vocabulary already settled what is
# impersonal. It is about what belongs to a BRAND rather than to a visit. A
# restaurant seen only in one city keeps its city, and that genuinely helps
# identify it; a chain seen in five drops it, because no single city is a fact
# about the chain. The same rule handles store numbers, which are never
# brand-level, without needing to say so.
#
# It is the same idea the rest of this package runs on: what does not vary is
# what the thing IS.
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
        """What a model is shown. The brand, plus context in a fixed order so two
        vaults that saw the same merchant compose the same string."""
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
    missing, and the merchant behind it is as real as any other."""
    out: dict = {}
    for s in streams:
        if s.is_person or s.refused:
            continue
        if s.role not in (COUNTERPARTY, MIXED):
            continue
        # No grammar named this counterparty, so no slot vouched for it. Fall
        # back to the conservative list, which over-blocks by design: the cost
        # of a false positive here is a merchant left unidentified, and the cost
        # of a false negative is a person's name in a shared catalog.
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
        # the normalizer's. Recorded so the catalog can say how well it knows
        # what it was told, rather than treating every key as equally sure.
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
