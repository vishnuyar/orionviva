"""Viva's voice lives here, as data — the persona pack.

Everything Viva says is an entry in a versioned pack directory, never a Python
literal. The discipline is prompts-as-files applied to the persona: her whole
vocabulary is reviewable in one sitting, a wording change is a pack change (a
NEW version once a pack is released — a recorded ``pack_version`` must keep
resolving, exactly as a recorded ``prompt_version`` must), and a test keeps
question text out of code the same way ``test_no_prompt_text_lives_in_code``
keeps prompts out.

Three hard rules, enforced mechanically (test_persona_pack.py):

1. **A phrasing may not introduce a fact.** Every ``{slot}`` in a template must
   name a field the deterministic question intent supplies — ``INTENT_FIELDS``
   below is that contract. The queue decides WHAT is said (figures, evidence,
   options); the pack only decides HOW it sounds. A phrasing's failure mode is
   *stiff*, never *false*.
2. **A slot says what it holds.** The contract is typed, so a hole in a sentence
   names a kind of thing in the world rather than only a word. An amount is a
   value and a currency written under one locale's conventions, and a slot
   asking for one cannot be handed a bare number — the type is checked where the
   sentence is made, not hoped for at review.
3. **Rendering is strict.** A template referencing a slot the caller didn't
   supply raises immediately rather than rendering a hole — a question with a
   blank where a figure should be is a bluff by omission.

The pack is impersonal by construction: it contains no user data, so it is
shareable, reviewable in a PR, and swappable — a terser Viva, or another
language, is a pack, not a code change.
"""

from __future__ import annotations

import json
import pathlib
import string
from functools import lru_cache

from vivacore import versions

from ..render import (ACCOUNT, CATEGORY, COUNT, DATE, DOCUMENT, MERCHANT,
                      MONEY, PROSE, RENDERED)

_DIR = pathlib.Path(__file__).resolve().parent

# The voice currently speaking, as `viva/versions.json` declares it. Change it
# by ADDING a pack directory and promoting it there, never by editing a released
# one — a decline records the pack that asked, and that pack_version must keep
# resolving to the exact words it recorded.
ACTIVE_PACK = versions.active(_DIR.parent, "persona_pack")

# How a grade finds its sentence in the pack. One reviewed line per word on the
# ladder, in a namespace of its own, said wherever a run states how well a set
# of figures is stood behind. Two sets are stated, so there are two namespaces:
# the answer's own, and a block of rows'. Each names its set in its own words,
# which is what tells a person which figures the word is about when both are in
# front of them.
STOOD_BEHIND_MOMENT = "stood_behind_"
ROWS_STOOD_BEHIND_MOMENT = "rows_stood_behind_"

from .contracts import INTENT_FIELDS, MOMENT_FIELDS


# ------------------------------------------------------------- the machinery


@lru_cache(maxsize=4)
def load(version: str = ACTIVE_PACK) -> dict:
    """The pack, loaded once. A missing pack is a build error, not a fallback —
    Viva with no voice must fail loudly, not mumble defaults from code."""
    d = _DIR / version
    return {
        "version": version,
        "phrasings": json.loads((d / "phrasings.json").read_text()),
        "moments": json.loads((d / "moments.json").read_text()),
    }


def slots_of(template: str) -> set:
    """The slot names a template references — for the lint test."""
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


class _Strict(dict):
    def __missing__(self, key):
        raise KeyError(f"phrasing slot {{{key}}} was not supplied — a question "
                       "with a hole where a fact should be is a bluff")


def say(key: str, *, version: str = ACTIVE_PACK, **fields) -> str:
    """Render one phrasing. Strict: a missing slot raises; extra fields are
    ignored (the intent may know more than the phrasing chooses to say); a
    declared slot handed something of the wrong kind raises."""
    _check_types(key, fields)
    return load(version)["phrasings"][key].format_map(_Strict(fields))


def _check_types(key: str, fields: dict) -> None:
    """Every declared field must be the kind of thing it was declared to be, and
    the declaration must be the kind of thing the intent actually supplies.

    Only a type whose renderer exists can be checked, and today that is money:
    what `render.money` produced carries a currency and one locale's
    conventions, and a bare number carries neither. A figure that formatted
    itself somewhere else is refused here rather than reaching a person as the
    only sentence in the product written under a convention nobody declared.

    The check runs both ways, because a contract only one side is held to is
    half a contract: a slot declared as money and handed something else fails,
    and so does a slot handed a rendered amount while declaring it as anything
    other than money."""
    declared = INTENT_FIELDS[key]
    for name, value in fields.items():
        want = RENDERED.get(declared.get(name, ""))
        if want is not None and not isinstance(value, want):
            raise TypeError(
                f"phrasing {key!r} places {name!r} as {declared[name]}, and was "
                f"handed {value!r} — a {declared[name]} slot takes what the one "
                f"renderer produced, never a value formatted elsewhere")
        made = next((t for t, produced in RENDERED.items()
                     if isinstance(value, produced)), "")
        if made and name in declared and declared[name] != made:
            raise TypeError(
                f"phrasing {key!r} declares {name!r} as {declared[name]}, and "
                f"the intent supplies what the {made} renderer wrote — the "
                f"declaration is what a reader of the contract is told this "
                f"slot holds, so it must say {made}")


def moment(key: str, *, version: str = ACTIVE_PACK, **fields) -> str:
    """Render one relationship moment."""
    return load(version)["moments"][key].format_map(_Strict(fields))
