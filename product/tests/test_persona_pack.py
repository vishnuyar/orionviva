"""Viva's voice is data, and it cannot invent facts.

Two disciplines, both enforced here rather than remembered:

1. Prompts-as-files, extended to the persona: question text lives in the pack,
   never in Python — and a released pack is frozen (a recorded ``pack_version``
   must keep resolving to the exact words that asked).
2. A phrasing may only place fields the deterministic question intent supplies
   (``INTENT_FIELDS``). The queue decides WHAT is said; the pack decides HOW it
   sounds. A template that could smuggle in a number would let a wording change
   put a claim in Viva's mouth — the lint below makes that structurally
   impossible rather than a review hope.
"""

import hashlib
import pathlib

import pytest

from viva import persona


def _pack_files(version):
    d = persona.pack_dir if hasattr(persona, "pack_dir") else None
    base = pathlib.Path(persona.__file__).resolve().parent / version
    return sorted(p for p in base.iterdir() if p.suffix in (".json", ".md"))


def test_every_intent_has_a_phrasing_and_no_orphans():
    """A question kind with no phrasing is a build error, not a render-time
    surprise; a phrasing no intent claims is dead voice."""
    keys = {k for k in persona.load()["phrasings"] if not k.startswith("_")}
    assert keys == set(persona.INTENT_FIELDS), (
        f"pack and contract disagree: only-in-pack={sorted(keys - set(persona.INTENT_FIELDS))}, "
        f"only-in-contract={sorted(set(persona.INTENT_FIELDS) - keys)}")
    mkeys = {k for k in persona.load()["moments"] if not k.startswith("_")}
    assert mkeys == set(persona.MOMENT_FIELDS)


def test_phrasings_use_only_their_intent_fields():
    """The no-new-facts lint: every {slot} must name a field the intent
    supplies. This is the no-invented-figures boundary at the wording layer."""
    for key, template in persona.load()["phrasings"].items():
        if key.startswith("_"):
            continue
        extra = persona.slots_of(template) - persona.INTENT_FIELDS[key]
        assert not extra, (f"phrasing {key!r} references {sorted(extra)} — "
                          "not fields the question intent supplies")
    for key, template in persona.load()["moments"].items():
        if key.startswith("_"):
            continue
        extra = persona.slots_of(template) - persona.MOMENT_FIELDS[key]
        assert not extra, f"moment {key!r} references {sorted(extra)}"


def test_rendering_is_strict_about_missing_slots():
    """A hole where a figure should be is a bluff by omission — raise, never
    render a blank."""
    with pytest.raises(KeyError):
        persona.say("merchant", example="ACME")     # count and money missing
    out = persona.say("merchant", example="ACME", count=3, money="USD 12.00",
                      irrelevant="ignored")          # extras are fine
    assert "ACME" in out and "USD 12.00" in out


def test_moments_render_with_and_without_a_name():
    with_name = persona.moment("welcome_back", name_part=", Alex")
    without = persona.moment("welcome_back", name_part="")
    assert "Alex" in with_name
    assert with_name != without and "  " not in without


def test_question_text_no_longer_lives_in_code():
    """Question sentences live in the pack, and must not survive as literals in
    questions.py."""
    src = (pathlib.Path(persona.__file__).resolve().parents[1] /
           "questions.py").read_text()
    for sentinel in ("Can you check the figure I flagged",
                     "Is it one you already have",
                     "What was this one for", "Or tell me in your own words"):
        assert sentinel not in src, (
            f"question text {sentinel!r} is back in questions.py — it belongs "
            "in the persona pack")


# A released pack is FROZEN: to change wording, add a new pack directory. These
# digests are each pack's fingerprint; if one changes, the fix is a new version
# id, never an edit (same rule, same reason as the prompt library's FROZEN
# table). pack-v1 is the original wording verbatim; pack-v2 is the Viva-manner
# pass plus the expectation phrasings; pack-v3 adds the interview's wording,
# which wraps the schema pack's own question and benefit in Viva's manner.
FROZEN_PACKS = {
    "pack-v1": "16c9bf533d3d4e31",
    "pack-v2": "7e8f38e3db15c2f9",
    "pack-v3": "d747faa1484a9dd0",
}


def test_released_packs_are_frozen():
    assert persona.ACTIVE_PACK in FROZEN_PACKS, "the active pack must be released"
    for version, digest in FROZEN_PACKS.items():
        h = hashlib.sha256()
        for p in _pack_files(version):
            h.update(p.name.encode())
            h.update(p.read_bytes())
        assert h.hexdigest()[:16] == digest, (
            f"{version} changed — a released pack is immutable; add a new "
            "pack directory instead")
