"""What moved, composed from one projection.

Every row here came off a document somebody added. Two things are decided by
this module and by nothing downstream of it.

**Which way the money went is read from the account's kind.** A posted amount is
signed by its effect on the balance the document prints, so on a card a purchase
posts positive; the one function that knows the kind decides, and it raises
rather than guessing when it is handed none. This is what the direction site
closing bought, and it is why this read can speak direction at all.

**A movement that is not plain spending says what it is.** Money moved between
a person's own pockets is not spending; a movement held out of spending on weak
evidence is neither counted nor quietly kept; a movement whose components are
known and whose proportions are not gets its own line. Each is a reviewed
sentence rather than a missing row, because a row that disappears is a figure
that changed with nothing said about why.

Nothing here is a total. Money in different currencies is not added, and this
read hands back rows rather than a sum — the picture is where a figure lives,
and a second place computing one would be a second answer.

A pure function of a projection. It opens nothing, reads no clock and knows
nothing about how the payload travels.
"""

from __future__ import annotations

from typing import Any

from .. import render
from ..ledger.projection.movements import (BY_CATEGORY, MIXED, SETTLEMENT,
                                           SPENDING, TRANSFER)
from ..ledger.streams import money_effect
from ..persona import moment
from .models import PanelState

# How many rows one read hands back. A person meets what moved most recently;
# everything else is behind a question this read does not take yet, and the
# count of what was left out travels so nothing is hidden — only not pushed.
DEFAULT_LIMIT = 50

# What a row is, beyond spending, against the sentence that says so. A nature
# outside this table is plain spending and carries no sentence: the row is what
# it looks like, and a line saying so would be noise on every ordinary row.
NATURES: dict[str, str] = {
    TRANSFER: "activity_transfer",
    SETTLEMENT: "activity_transfer",
    MIXED: "activity_unsettled",
}


def activity(projection, locale: str = "", limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Everything that moved, newest first, ready to render.

    ``limit`` bounds what is handed over. What was left out is reported with
    its count rather than dropped: a list that silently stops is a list a
    person reads as the whole of what happened."""
    movements = list(projection.movements())
    if not movements:
        return {
            "state": PanelState.ABSENT.value,
            # Not the same as nothing having moved, and said so.
            "sentence": moment("activity_empty"),
            "items": [],
            "beyond": {"count": 0},
        }
    ordered = sorted(movements, key=lambda m: (str(m.date), m.key), reverse=True)
    shown, rest = ordered[:limit], ordered[limit:]
    return {
        "state": PanelState.READY.value,
        "sentence": moment("activity_scope"),
        "items": [_row(movement, locale) for movement in shown],
        # What ranking pushed below the fold, reported with its size. No amount
        # travels with it: the rows beyond are in whatever currencies they are
        # in, and one number over them would be a total of unlike things.
        "beyond": {"count": len(rest)},
    }


def _row(movement, locale: str) -> dict[str, Any]:
    """One movement, as a person meets it.

    The direction is derived here from the account's kind, through the one
    function that decides it — never from the posted sign, which reads a card
    purchase as money arriving."""
    effect = money_effect(movement.kind, movement.amount)
    return {
        "id": movement.key,
        "date": movement.date,
        "description": movement.description,
        "account": movement.account,
        # `direction` is what the money did, and it is the kind's answer. The
        # amount travels unsigned beside it, because a sign and a word saying
        # the same thing are two chances to disagree.
        "direction": "in" if effect > 0 else "out",
        "exact_value": str(abs(effect)),
        "currency": movement.currency,
        "display": str(render.money(abs(effect), movement.currency,
                                    locale=locale)),
        "nature": movement.nature,
        # What this is, where it is not plain spending. Empty on an ordinary
        # row, because a line saying "this is spending" on every spending row
        # is a line that stops being read.
        "sentence": _sentence(movement),
        # Whether this movement is one a link, a ruling or a document settled,
        # or one resting on weaker evidence. It is the reason the projection
        # recorded, carried rather than re-derived.
        "decided_by": movement.nature_reason,
        "provisional": bool(movement.provisional),
        "linked": bool(movement.linked),
    }


def _sentence(movement) -> str:
    """The reviewed line for what this row is, or nothing.

    A movement held out of spending on weak evidence is said before what its
    nature nominally is: that it rests on a hint is the more important fact,
    and it is the one that explains why a total moved."""
    if movement.provisional or movement.nature_reason == BY_CATEGORY:
        if movement.nature != SPENDING:
            return moment("activity_provisional")
    key = NATURES.get(movement.nature, "")
    return moment(key) if key else ""
