"""Viva's voice is data, and it cannot invent facts.

Two disciplines, both enforced here rather than remembered:

1. Prompts-as-files, extended to the persona: question text lives in the pack,
   never in Python — and a released pack is frozen (a recorded ``pack_version``
   must keep resolving to the exact words that asked).
2. A phrasing may only place fields the deterministic question intent supplies,
   of the kinds it declares them to be (``INTENT_FIELDS``). The queue decides
   WHAT is said; the pack decides HOW it sounds. A template that could smuggle
   in a number would let a wording change put a claim in Viva's mouth — the lint
   below makes that structurally impossible rather than a review hope.
3. An amount placed in a sentence is what the one renderer wrote: a value, its
   currency and one locale's conventions. A figure that formatted itself
   somewhere else cannot reach a person.
"""

import ast
import hashlib
import pathlib

import pytest
from vivacore import versions as manifest

from viva import persona, render

_PACKAGE = pathlib.Path(persona.__file__).resolve().parent.parent

# The renderer for each type is the function named after it, which is how a
# reader of `render.py` finds one. A call to any of them is code declaring
# "this is that kind of thing in the world".
_RENDERERS = {name: name for name in render.RENDERED}


def _renderer_calls(tree) -> dict:
    """The local names this module calls a renderer by, mapped to the slot type
    each one renders. Read from the imports, so an alias is followed rather than
    guessed at."""
    called = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("render"):
            for alias in node.names:
                if alias.name in _RENDERERS:
                    called[alias.asname or alias.name] = _RENDERERS[alias.name]
    return called


def _rendered_type(value, called: dict) -> str:
    """The slot type a keyword's value was rendered as, or ""."""
    if not isinstance(value, ast.Call):
        return ""
    func = value.func
    if isinstance(func, ast.Name):
        return called.get(func.id, "")
    if isinstance(func, ast.Attribute):
        return _RENDERERS.get(func.attr, "") if isinstance(func.value, ast.Name) \
            and func.value.id.endswith("render") else ""
    return ""


def _placed_by_the_intent():
    """Every `(phrasing key, slot name, the type it is filled with)` the code
    actually places, read from the calls themselves."""
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text())
        called = _renderer_calls(tree)
        if not called:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "say" and node.args):
                continue
            key = node.args[0]
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            for keyword in node.keywords:
                placed = _rendered_type(keyword.value, called)
                if keyword.arg and placed:
                    yield path.name, key.value, keyword.arg, placed


def _pack_files(version):
    """What the pack consists of, as `versions.fingerprint` counts it — the same
    accessor the manifest audit uses."""
    base = pathlib.Path(persona.__file__).resolve().parent / version
    return manifest.contents(base)


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
    supplies, and that field must be declared as some kind of thing in the
    world. This is the no-invented-figures boundary at the wording layer — a
    slot with no type could be handed anything, which is where a figure that
    formatted itself would get in."""
    for key, template in persona.load()["phrasings"].items():
        if key.startswith("_"):
            continue
        declared = persona.INTENT_FIELDS[key]
        extra = persona.slots_of(template) - set(declared)
        assert not extra, (f"phrasing {key!r} references {sorted(extra)} — "
                          "not fields the question intent supplies")
        for name in persona.slots_of(template):
            assert declared[name] in render.TYPES, (
                f"phrasing {key!r} places {name!r} as {declared[name]!r}, which "
                f"is not one of {render.TYPES}")
    for key, template in persona.load()["moments"].items():
        if key.startswith("_"):
            continue
        extra = persona.slots_of(template) - persona.MOMENT_FIELDS[key]
        assert not extra, f"moment {key!r} references {sorted(extra)}"


def test_every_way_a_turn_can_refuse_has_a_reviewed_sentence():
    """A refusal is chosen by its machine tag, so a tag with no sentence in the
    pack is a person hearing nothing — or hearing a tag. It fails here, at
    build time, rather than there. And a sentence no tag can reach is dead
    voice, the same way an orphan phrasing is."""
    from viva.tools.runner import REFUSAL_MOMENT, REFUSAL_TAGS

    declared = {k for k in persona.MOMENT_FIELDS if k.startswith(REFUSAL_MOMENT)}
    wanted = {REFUSAL_MOMENT + tag for tag in REFUSAL_TAGS}
    assert declared == wanted, (
        f"only-in-pack={sorted(declared - wanted)}, "
        f"only-in-code={sorted(wanted - declared)}")
    for tag in REFUSAL_TAGS:
        said = persona.moment(REFUSAL_MOMENT + tag)
        assert said.strip(), tag
        assert tag not in said, (
            f"the sentence for {tag!r} says the machine's tag out loud")


def test_every_kind_a_set_can_be_narrowed_to_has_a_reviewed_sentence():
    """A figure says what set it was taken over, and a kind of thing with no
    sentence in the pack is a boundary the machine holds and cannot say. It
    fails here, at build time, rather than as a figure reaching a person
    looking like a total. The other way round is dead voice."""
    from viva.tools.envelope import SELECTED_KINDS
    from viva.tools.runner import SELECTED_TERMS

    assert set(SELECTED_TERMS) == set(SELECTED_KINDS), (
        f"only-in-terms={sorted(set(SELECTED_TERMS) - set(SELECTED_KINDS))}, "
        f"only-in-vocabulary={sorted(set(SELECTED_KINDS) - set(SELECTED_TERMS))}")
    for kind in SELECTED_KINDS:
        key, slot, _writes = SELECTED_TERMS[kind]
        assert persona.MOMENT_FIELDS[key] == {slot}
        assert persona.moment(key, **{slot: "something"}).strip()


def test_a_slot_the_intent_fills_with_a_rendered_thing_declares_that_type():
    """The other half of the contract: the DECLARATION has to be true.

    The lint above holds a template to what the intent supplies. Nothing held
    the intent's own declaration to what the intent does, so a slot could be
    declared as one kind of thing while being filled with another, and the
    contract would read as settled while saying something false about itself."""
    placed = list(_placed_by_the_intent())
    assert placed, ("no phrasing slot is filled from the renderer — either the "
                    "queue has stopped placing figures, or this lint has "
                    "stopped finding them")
    for module, key, name, rendered in placed:
        declared = persona.INTENT_FIELDS[key].get(name, "")
        assert declared == rendered, (
            f"{module} fills {name!r} of phrasing {key!r} with what the "
            f"{rendered} renderer wrote, and the contract declares it "
            f"{declared!r} — the declaration is what anyone reading the "
            "contract is told the slot holds")


def test_a_declared_type_that_disagrees_with_what_is_placed_raises():
    """And at the moment the sentence is made, for the fills a reader of the
    source cannot follow — a value handed through a dict, or from further
    away."""
    written = render.money("12", "USD", locale="en-US")
    with pytest.raises(TypeError):
        # `count` is declared as a number of things; an amount is not one.
        persona.say("merchant", example="ACME", count=written, money=written)


def test_rendering_is_strict_about_missing_slots():
    """A hole where a figure should be is a bluff by omission — raise, never
    render a blank."""
    written = render.money("12", "USD", locale="en-US")
    who = render.merchant({"example": "ACME"})
    how_many = render.count(3)
    with pytest.raises(KeyError):
        persona.say("merchant", example=who)        # count and money missing
    out = persona.say("merchant", example=who, count=how_many, money=written,
                      irrelevant="ignored")          # extras are fine
    assert "ACME" in out and "USD 12.00" in out


def test_a_money_slot_cannot_be_handed_a_figure_that_formatted_itself():
    """The typed half of the contract, and the reason it is typed.

    A slot declared as money takes an amount the one renderer wrote — a value,
    a currency and one locale's conventions. Anything else is a figure written
    under conventions nobody declared, and it is refused where the sentence is
    made rather than noticed after a person has read it."""
    who = render.merchant({"example": "ACME"})
    how_many = render.count(3)
    with pytest.raises(TypeError):
        persona.say("merchant", example=who, count=how_many, money="12.00")
    with pytest.raises(TypeError):
        persona.say("merchant", example=who, count=how_many,
                    money=f"USD {12:,.2f}")
    # And the same rule on a slot that is not money: a counterparty a sentence
    # spelled itself is a second decision about which of its names to show.
    with pytest.raises(TypeError):
        persona.say("merchant", example="ACME", count=how_many,
                    money=render.money("12", "USD", locale="en-US"))
    out = persona.say("merchant", example=who, count=how_many,
                      money=render.money("12", "USD", locale="en-US"))
    assert "USD 12.00" in out


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
FROZEN_PACKS = {v: d for v, d in
                manifest.manifest(_PACKAGE)["released"].items()
                if v.startswith("pack-")}


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
