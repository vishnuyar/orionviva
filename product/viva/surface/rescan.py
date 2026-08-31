"""What a pass back over an already-held vault did, ready to render.

The sweep returns counts. Counts are not a read model: a screen handed
``{"gaps": 2, "auto": 1}`` has to invent words for what a gap is and what was
linked to what, and the words it invents are the ones nobody reviewed. So this
module turns those counts into the sentences that describe them, chosen from
the persona pack, one per kind of change that actually happened.

Three decisions live here and nowhere else.

**A pass that changed nothing says so in its own sentence.** An empty list of
changes and a sweep that found nothing look identical on a screen and mean
different things — the first reads as a panel that failed to render.

**A count of zero is not a row.** A line saying nothing was linked is a line a
person reads and learns nothing from, and six of them are a screen that has
stopped meaning anything.

**What is still open is not a change.** The sweep reports how many possible
transfers are waiting, and that is a standing fact about the vault rather than
something this pass did; it is carried apart from the changes so that a screen
cannot present it as an outcome.

A pure function of what the sweep returned. It opens nothing, reads no clock
and knows nothing about how the payload travels.
"""

from __future__ import annotations

from typing import Any

from .. import render
from ..persona import moment
from .models import PanelState

# Each kind of change the sweep counts, in the order a person meets it, against
# the sentence that says what that kind of change is. The order is a reading
# order rather than an importance one: what was closed comes before what was
# agreed with, which comes before what turned out to be one movement, because
# each explains the one after it.
CHANGES: tuple[tuple[str, str], ...] = (
    ("gaps", "rescan_gaps"),
    ("corroborated", "rescan_corroborated"),
    ("auto", "rescan_linked"),
    ("resolved", "rescan_settled"),
)

# What the sweep reports about the vault as it stands, rather than about what
# this pass did. It is carried apart so no screen can render it as an outcome.
STANDING: tuple[tuple[str, str], ...] = (
    ("suggested", "rescan_open"),
)


def rescan(result: dict[str, Any]) -> dict[str, Any]:
    """The read model for one pass back over a vault.

    ``result`` is what :func:`viva.ingest.sweep` returned. A key it does not
    carry is read as no change of that kind, which is the same as zero and is
    the only reading available: a sweep that reported nothing about gaps did
    not heal any."""
    changes = [
        {"id": key, "count": _count(result, key),
         "sentence": moment(sentence, count=render.count(_count(result, key)))}
        for key, sentence in CHANGES
        if _count(result, key) > 0
    ]
    standing = [
        {"id": key, "count": _count(result, key),
         "sentence": moment(sentence, count=render.count(_count(result, key))),
         "movement_ids": (_movement_ids(result) if key == "suggested" else [])}
        for key, sentence in STANDING
        if _count(result, key) > 0
    ]
    return {
        "state": PanelState.READY.value,
        # One sentence for the whole panel. A pass that changed nothing says so
        # rather than rendering an empty list, and a pass that changed
        # something says what this pass does not do — because the obvious next
        # thought after "it went back over everything" is that it read the
        # documents, and it did not.
        "sentence": moment("rescan_nothing") if not changes
        else moment("rescan_unread"),
        "changes": changes,
        "standing": standing,
        # The total links this vault holds, after the pass. It is a figure
        # about the vault rather than about the pass, and it carries no
        # sentence: nothing here has a reviewed line for it, and inventing one
        # is exactly what this module exists to avoid.
        "link_count": _count(result, "links"),
    }


def _count(result: dict[str, Any], key: str) -> int:
    """One count out of the sweep's reply, or nothing.

    A value that is not a whole number of things is read as none rather than
    coerced: a count is what a sentence places, and a sentence placing
    something that is not a count is a sentence saying something nobody
    checked."""
    value = result.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _movement_ids(result: dict[str, Any]) -> list[str]:
    value = result.get("review_movements", [])
    if not isinstance(value, list):
        return []
    return sorted({item.strip() for item in value
                   if isinstance(item, str) and item.strip()})
