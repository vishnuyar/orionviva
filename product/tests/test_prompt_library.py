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
from vivacore import versions as manifest

from viva.ingest import prompt_library as pl

PACKAGE = pl.PACKAGE

# The pins live in `viva/versions.json`, keyed by each file's own stem, so one
# table covers prompts, packs and registries alike. If a digest changes, the fix
# is not to bump the number there — it is to add a new version id and leave the
# old text intact.
FROZEN = {v: d for v, d in manifest.manifest(PACKAGE)["released"].items()
          if v.startswith(("classify-", "interpret-", "extract-"))}


def test_active_versions_are_frozen():
    live = set(pl.versions())
    for stem, digest in FROZEN.items():
        version = stem[len("extract-"):] if stem.startswith("extract-") else stem
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


def test_current_card_fragment_excludes_summary_rows_from_transactions():
    from viva.ingest import profile_for

    fragment = profile_for("credit_card_statement").type_fragment
    assert fragment == "card-v2"
    text = pl.resolve(fragment).lower()
    for excluded in ("section heading", "subtotal", "payment-summary",
                     "only printed transaction line items"):
        assert excluded in text


# ----------------------------------------------------- the interpret prompt


def test_the_interpret_prompt_is_addressable_like_every_other():
    """An unversioned prompt is rewritable in place, which would mean that
    tuning it silently reinterprets every ruling made before the change."""
    text, version = pl.interpret_prompt()
    assert version == "interpret-v3"
    assert pl.resolve(version) == text          # a recorded ruling round-trips
    # v1 and v2 are retained, unchanged: rulings recorded under them stay
    # explainable.
    assert pl.resolve("interpret-v1") != text
    assert pl.resolve("interpret-v2") != text


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
    editing prose, and a missing one fails loudly instead of silently.

    The slots and the context are placeholders too: the instructions are the
    same for every question, and what differs is data the caller supplies."""
    text, _ = pl.interpret_prompt()
    filled = text.format(said="i bought a car",
                         asked="What was this one for?",
                         context="- counterparty: ACME MOTORS",
                         slots="- legs: SEVERAL")
    assert "i bought a car" in filled and "ACME MOTORS" in filled
    assert "What was this one for?" in filled and "- legs: SEVERAL" in filled
    assert "{" in text and "{" not in filled.split("Fill exactly")[0]

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
            # 200 was too generous by half: the hint that framed a document's
            # own text for the model sat at about a hundred characters and was
            # therefore invisible here — unversioned, and unrecoverable from a
            # recorded prompt_version. 100 catches it. Below about 100 the hits
            # are log lines and CLI help, and a gate that cries wolf is a gate
            # somebody adds an exclusion list to.
            if len(text) < 100 or "\n" not in text:
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


# The modules that assemble what a model is sent. Membership is derived, not
# listed: importing the prompt loader is what makes a file one of these.
_PROMPT_LOADERS = ("promptstore", "prompt_library")


def _composes_prompts(tree) -> bool:
    import ast
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [a.name for a in node.names]
        else:
            continue
        if any(any(loader in n for loader in _PROMPT_LOADERS) for n in names):
            return True
    return False


def _literal_text(node):
    """The model-facing text a node spells out, or None.

    An f-string is where prompt text hides most comfortably: the walker sees
    `ast.Constant` and an f-string is an `ast.JoinedStr` whose pieces are each
    too short to notice on their own. Interpolations are counted as the one
    thing they always are — a value that will be dropped in — so the sentence is
    measured whole rather than in fragments."""
    import ast
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            else:
                parts.append("{}")
        return "".join(parts)
    return None


def test_a_prompt_composing_module_holds_no_model_facing_literal():
    """In a module that assembles model-facing text, a long literal is prompt
    text — no phrase-matching required.

    `test_no_prompt_text_lives_in_code` asks whether a literal *looks like* an
    instruction, against seven phrases. That is what a hint framing a document's
    own text escaped through: ninety-two characters, matching none of the seven,
    sitting in the one function that composes what the reader sends. It was
    model-facing text living in code for as long as the reader has existed, and
    no length threshold would have found it, because length was never why it
    was missed.

    So this asks a structural question instead. A file that imports the prompt
    loader is a file that builds prompts, and a multi-line literal of any real
    size in one is the thing the rule forbids, whatever it happens to say."""
    import ast

    offenders = []
    for path in _python_files():
        # Tests only, and deliberately: a test scripts what a model *replies*,
        # which is the opposite direction. A fenced JSON block standing in for a
        # model's answer is not text this product sends anyone.
        if path.name.startswith("test_") or "tests" in path.parts:
            continue
        if path.name == "promptstore.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        if not _composes_prompts(tree):
            continue
        docstrings = {id(ast.get_docstring(n, clean=False))
                      for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef,
                                        ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in ast.walk(tree):
            text = _literal_text(node)
            if text is None or len(text) < 80 or "\n" not in text:
                continue
            if id(text) in docstrings or text is ast.get_docstring(tree, clean=False):
                continue
            offenders.append(f"{path.relative_to(_repo_root())}:{node.lineno} "
                             f"({len(text)} chars)")

    assert not offenders, (
        "a module that composes prompts holds a long string literal at "
        + ", ".join(offenders) + ".\n"
        "If it is model-facing, it belongs in <package>/prompts/<id>.txt with a "
        "version. If it is not, it wants to be a comment or a shorter string.")
