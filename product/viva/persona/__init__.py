"""Viva's voice lives here, as data — the persona pack (Slice 6.10).

Everything Viva says is an entry in a versioned pack directory, never a Python
literal. The discipline is prompts-as-files applied to the persona: her whole
vocabulary is reviewable in one sitting, a wording change is a pack change (a
NEW version once a pack is released — a recorded ``pack_version`` must keep
resolving, exactly as a recorded ``prompt_version`` must), and a test keeps
question text out of code the same way ``test_no_prompt_text_lives_in_code``
keeps prompts out.

Two hard rules, enforced mechanically (test_persona_pack.py):

1. **A phrasing may not introduce a fact.** Every ``{slot}`` in a template must
   name a field the deterministic question intent supplies — ``INTENT_FIELDS``
   below is that contract. The queue decides WHAT is said (figures, evidence,
   options); the pack only decides HOW it sounds. A phrasing's failure mode is
   *stiff*, never *false*.
2. **Rendering is strict.** A template referencing a slot the caller didn't
   supply raises immediately rather than rendering a hole — a question with a
   blank where a figure should be is a bluff by omission.

The pack is impersonal by construction (T9): it contains no user data, so it is
shareable, reviewable in a PR, and swappable — a terser Viva, or another
language (I5), is a pack, not a code change.
"""

from __future__ import annotations

import json
import pathlib
import string
from functools import lru_cache

_DIR = pathlib.Path(__file__).resolve().parent

# The voice currently speaking. Bump by ADDING a pack directory, never by
# editing a released one — declines record the pack that asked (T8 discipline).
# pack-v1: the queue's original wording, verbatim. pack-v2: the wording pass in
# Viva's manner (docs/viva-persona.md), model-drafted, author-reviewed (D2) —
# and the Slice 6.11 expectation phrasings.
ACTIVE_PACK = "pack-v2"

# ------------------------------------------------------------- the contract
#
# Phrasing key -> the slots its template MAY use. These are the fields the
# question queue's deterministic intent supplies — nothing else may appear in a
# template, so a phrasing cannot smuggle a claim into a question (T2).
# Slot values arrive PRE-FORMATTED (money already carries its currency): the
# pack places figures, it never computes them.

INTENT_FIELDS: dict[str, frozenset] = {
    "identity":                    frozenset({"account_ref"}),
    "reconciliation_gap":          frozenset({"account_ref", "opening_date",
                                              "closing_date"}),
    "reconciliation_gap_why":      frozenset({"opening_money"}),
    "reconciliation_flagged":      frozenset({"account_ref"}),
    "reconciliation_held":         frozenset({"doc_type", "for_account"}),
    "transfer":                    frozenset({"date", "money", "description"}),
    "transfer_why":                frozenset({"candidates"}),
    "merchant":                    frozenset({"example", "count", "money"}),
    "merchant_peer_note":          frozenset(),
    "merchant_why":                frozenset(),
    "nature_single":               frozenset({"date", "description", "money"}),
    "nature_single_why":           frozenset(),
    "nature_group_head":           frozenset({"count", "example", "money"}),
    "nature_group_meaning":        frozenset({"what"}),
    "nature_group_compound":       frozenset(),
    "nature_group_ask":            frozenset(),
    "nature_group_why":            frozenset(),
    "nature_group_why_documents":  frozenset({"documents"}),
    "corroboration":               frozenset({"name", "money", "document"}),
    "corroboration_why":           frozenset(),
    "corroboration_why_unreliable": frozenset(),
    "free_text_invite":            frozenset(),
    # Slice 6.11 — the expectations engine. One phrasing pair per mechanism;
    # the document name comes from the registry (data), never from the model.
    "expectation_retirement_flow":         frozenset({"money", "document"}),
    "expectation_retirement_flow_why":     frozenset(),
    "expectation_investment_account":      frozenset({"account_name", "document"}),
    "expectation_investment_account_why":  frozenset({"money"}),
    "expectation_account_cadence":         frozenset({"account_name", "last_date"}),
    "expectation_account_cadence_why":     frozenset(),
}

# Moment key -> its slots. Moments are the relationship lines (welcome, return,
# the "I don't know" reassurance) from the persona guide (docs/viva-persona.md).
# The only personal slot is the name, derived deterministically from the
# vault's own account holders, never asked of a model.
MOMENT_FIELDS: dict[str, frozenset] = {
    "welcome_empty":  frozenset({"name_part"}),
    "welcome_back":   frozenset({"name_part"}),
    "reassurance":    frozenset({"name_part"}),
    "not_now_ack":    frozenset({"name_part"}),
    "dont_know_ack":  frozenset({"name_part"}),
    "all_settled":    frozenset({"name_part"}),
}


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
    ignored (the intent may know more than the phrasing chooses to say)."""
    return load(version)["phrasings"][key].format_map(_Strict(fields))


def moment(key: str, *, version: str = ACTIVE_PACK, **fields) -> str:
    """Render one relationship moment."""
    return load(version)["moments"][key].format_map(_Strict(fields))
