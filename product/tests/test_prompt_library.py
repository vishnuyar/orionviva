"""Prompts are retained, addressable, versioned data — files, not string literals.

The frozen-hash test enforces the retention discipline: a version id's text may
never change. To edit a prompt you add a NEW id, so a read stored under the old
id keeps resolving to exactly what produced it.

**These pinned digests are also the proof that the move to files was faithful.**
The prompts left `prompt_library.py` and became `viva/prompts/*.txt` without a
single character changing — and the evidence is that this test still passes with
the same numbers it had when the text lived in Python. No new test to trust, no
diff to eyeball: if one byte had moved, a digest would differ."""

import hashlib
import pathlib

import pytest

from viva.ingest import prompt_library as pl

# Pinned digests of every ACTIVE version. If one changes, the fix is not to bump
# the number here — it is to add a new version id and leave the old text intact.
FROZEN = {
    "classify-v1": "78d4a6f76dda419c",
    "classify-v2": "b0068911c228303a",
    "base-v1": "93c67860a6626894",
    "balance-generic-v1": "b7c12fe0406a602e",
    "checking-v1": "2bda917dce1ee26f",
    "savings-v1": "222ae6d74f94e8f6",
    "card-v1": "1fb3e7b3dfb1c9c9",
    "paystub-base-v1": "0c6d6940246743c5",
    "paystub-v1": "03b31eadbe878505",
    "interpret-v1": "999d8aa496da5691",
    "interpret-v2": "7ac87ea8a867d0ba",
}


def test_active_versions_are_frozen():
    live = set(pl.versions())
    for version, digest in FROZEN.items():
        assert version in live, f"{version} disappeared — versions are append-only"
        got = hashlib.sha256(pl.resolve(version).encode()).hexdigest()[:16]
        assert got == digest, (
            f"{version} text changed. Do not edit a released prompt version; add "
            f"a new id (a new file in viva/prompts/) and point the profile at it.")


def test_no_prompt_text_lives_in_the_library_module():
    """The module is accessors and composition rules only. A prompt that sneaks
    back in as a literal would be un-diffable, un-reviewable, and editable in
    place, which is how a version's text gets lost."""
    source = pathlib.Path(pl.__file__).read_text()
    assert "Return ONLY" not in source and "You are reading" not in source
    assert len(source.splitlines()) < 120


def test_a_missing_version_raises_rather_than_defaulting():
    """A recorded version that resolves to nothing must be an error, never a
    silent fallback to the CURRENT prompt — that would re-explain an old reading
    with new instructions and look like it worked."""
    from vivacore.promptstore import PromptNotFound

    with pytest.raises(PromptNotFound):
        pl.resolve("card-v99")
    with pytest.raises(PromptNotFound):
        pl.resolve("extract:base-v1+never-existed")


def test_classify_prompt_carries_its_version():
    text, version = pl.classify_prompt()
    assert version == "classify-v2" and "doc_type" in text
    assert "pay_stub" in text                          # v2 knows pay stubs


def test_compose_extraction_yields_self_describing_version():
    text, version = pl.compose_extraction("base-v1", "card-v1")
    assert version == "extract:base-v1+card-v1"
    # The composite is base THEN the type fragment — shape first, meaning second.
    assert text.startswith(pl.resolve("base-v1"))
    assert pl.resolve("card-v1") in text


def test_resolve_round_trips_every_kind_of_version():
    # A stored read's prompt_version must resolve to its exact text, whether it is
    # a classify id, a base/fragment id, or a composite extract id.
    assert pl.resolve("classify-v1") == pl.resolve("classify-v1")
    assert pl.resolve("card-v1") == pl.resolve("card-v1")
    _, version = pl.compose_extraction("base-v1", "checking-v1")
    composed, _ = pl.compose_extraction("base-v1", "checking-v1")
    assert pl.resolve(version) == composed


def test_resolve_unknown_version_raises():
    with pytest.raises(KeyError):
        pl.resolve("does-not-exist")


def test_card_fragment_carries_the_payments_completeness_rule():
    # The card-specific completeness guidance lives ONLY in the card fragment —
    # it must not leak into the checking fragment.
    assert "payments" in pl.resolve("card-v1").lower()
    assert "separate section" in pl.resolve("card-v1").lower()
    assert "separate section" not in pl.resolve("checking-v1").lower()


# ----------------------------------------------------- the interpret prompt


def test_the_interpret_prompt_is_addressable_like_every_other():
    """An unversioned prompt is rewritable in place, which would mean that
    tuning it silently reinterprets every ruling made before the change."""
    text, version = pl.interpret_prompt()
    assert version == "interpret-v2"
    assert pl.resolve(version) == text          # a recorded ruling round-trips
    # v1 is retained, unchanged: rulings recorded under it stay explainable.
    assert pl.resolve("interpret-v1") != text


def test_the_interpret_prompt_assumes_no_particular_instrument():
    """A vault holds cards, brokerages, retirement and loan accounts — and one
    day, accounts in other countries. A prompt that says "your bank account"
    mis-frames all of them (code universal, specifics are data)."""
    import re

    text, _ = pl.interpret_prompt()
    low = text.lower()
    # Word-boundary matching, not substrings — "first" contains "irs".
    for bank_shaped in (r"bank account", r"from their bank", r"on the statement",
                        r"\bdollars?\b", r"\$", r"\birs\b", r"\b1098\b",
                        r"\bchecking\b"):
        assert not re.search(bank_shaped, low), f"prompt assumes {bank_shaped!r}"
    # And it says so positively, rather than merely avoiding the word.
    assert "any financial instrument" in low and "any country" in low


def test_the_interpret_prompt_fills_from_named_placeholders():
    """Placeholders, not string surgery — so a caller can add context without
    editing prose, and a missing one fails loudly instead of silently."""
    text, _ = pl.interpret_prompt()
    filled = text.format(said="i bought a car", counterparty="ACME MOTORS",
                         source="a credit account", category="transport",
                         subcategory="auto dealer")
    assert "i bought a car" in filled and "a credit account" in filled
    assert "{" in text and "{" not in filled.split("Reply with:")[0]

    import pytest
    with pytest.raises(KeyError):
        text.format(said="x")                   # a forgotten arg is not silent


def test_a_ruling_records_which_prompt_read_it():
    """Without this, tuning the prompt makes past rulings unexplainable and
    eval runs incomparable across time."""
    from viva.ledger.events import MAJOR_ASSET, SCOPE_MERCHANT, ruling_recorded
    ev = ruling_recorded(SCOPE_MERCHANT, "acme motors", "2026-07-25",
                         legs=[{"major": MAJOR_ASSET}], said="i bought a car",
                         prompt_version="interpret-v1")
    assert ev.body["prompt_version"] == "interpret-v1"
    assert pl.resolve(ev.body["prompt_version"])       # still reconstructible


def test_v2_asks_for_the_label_the_person_named_and_not_for_a_document():
    """v2 asks for the label the person named, so an answer like "add it to
    poker category" is not half-dropped, and it drops the unguided
    "corroborates" field, whose free-text answers reached the surface as
    nonsense. v1 keeps both, unchanged."""
    v2, _ = pl.interpret_prompt("interpret-v2")
    assert '"category"' in v2 and "Copy their word" in v2
    assert "corroborates" not in v2        # code maps kind -> document, not the model
    assert '"corroborates"' in pl.resolve("interpret-v1")   # v1 still has it, intact


# ------------------------------------------------- the test that makes it stick


def _repo_root():
    return pathlib.Path(__file__).resolve().parents[2]


def _python_files():
    for pkg in ("core", "product", "merchant", "bench"):
        root = _repo_root() / pkg
        if not root.is_dir():
            continue
        for f in root.rglob("*.py"):
            parts = set(f.parts)
            if parts & {"build", ".venv", "node_modules", "__pycache__"}:
                continue
            yield f


# Words that only appear when a string is INSTRUCTING A MODEL. This is a
# deliberate keyword check, and the distinction is worth stating rather than
# hiding: keyword classification is banned for a USER'S DATA, where being wrong
# corrupts a ledger. This is a lint over OUR OWN SOURCE, where being wrong costs
# a contributor one comment. Same technique, opposite blast radius.
_INSTRUCTION_MARKERS = (
    "return only a json", "reply with json", "you are reading",
    "you are identifying", "you are classifying", "return only the",
    "reply with only",
)


def test_no_prompt_text_lives_in_code():
    """Model-facing text may not live in code as a string literal.

    Intent loses to friction: a triple-quoted string is one line and the library
    is five plus an import. So the friction moves — creating a file is the cheap
    path, and a literal here is a build failure with the fix printed in the
    message."""
    import ast

    offenders = []
    for path in _python_files():
        if path.name in ("test_prompt_library.py", "promptstore.py"):
            continue                      # this file names the markers on purpose
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:               # not ours to police
            continue
        docstrings = {id(ast.get_docstring(n, clean=False))
                      for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef,
                                        ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value
            if len(text) < 200 or "\n" not in text:
                continue
            if id(text) in docstrings or text is ast.get_docstring(tree, clean=False):
                continue
            low = text.lower()
            if any(mark in low for mark in _INSTRUCTION_MARKERS):
                offenders.append(f"{path.relative_to(_repo_root())}:{node.lineno}")

    assert not offenders, (
        "prompt text found in code at " + ", ".join(offenders) + ".\n"
        "Prompts are files. Move it to <package>/prompts/<id>.txt and load it "
        "with `promptstore.load(PROMPTS, '<id>')` — then pin its digest in "
        "FROZEN so it can never be edited in place.")


def test_every_version_the_code_can_emit_resolves():
    """Every version the code can emit must resolve, or an event can go on
    naming text that no longer exists."""
    from viva.ingest import registry

    for doc_type in list(registry._INDEX):
        got = registry.extraction_prompt_for(doc_type)
        if got:
            text, version = got
            assert pl.resolve(version) == text, version
    for version in (pl.classify_prompt()[1], pl.interpret_prompt()[1]):
        assert pl.resolve(version)


def test_the_other_packages_keep_their_prompts_in_files_too():
    """The discipline is not one module's local habit."""
    from vivacore import promptstore
    from vivacore.prompts import PROMPT_VERSION
    from vivacore.prompts import PROMPTS as CORE
    from merchantcore.enrich import ENRICHMENT_VERSION
    from merchantcore.enrich import PROMPTS as MERCH

    assert promptstore.load(CORE, f"extract-image-{PROMPT_VERSION}")
    assert promptstore.load(MERCH, ENRICHMENT_VERSION)
    # enrich-v2 is retained, so reads recorded under it stay explainable rather
    # than pointing at nothing.
    assert "enrich-v2" in promptstore.ids(MERCH)
