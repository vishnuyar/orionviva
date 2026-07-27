"""Prompts as versioned, addressable DATA — files on disk.

The read happens in phases: a cheap **classify** pass names the document, then
an **extract** pass runs the prompt that belongs to that type's profile. A
third, **interpret**, reads a person's own sentence.

**Every version lives in `viva/prompts/<id>.txt`.** This module holds no prompt
text at all — only the composition rules and the accessors.

Retention discipline (enforced by ``test_prompt_library``): the files are
**append-only**. To change a prompt you add a NEW id; you never edit an existing
one. A read recorded under ``card-v1`` must resolve to card-v1's text forever,
even after ``card-v2`` exists — and the only way to break that is to edit a
file whose digest is pinned, which fails the freeze.

The extraction prompt is *composed*: a shared ``base`` (the parse shape +
universal rules, identical for every balance type) plus a per-type fragment
(what the balance means, and that type's completeness traps). Composition yields
a self-describing version id like ``extract:base-v1+card-v1``.
"""

from __future__ import annotations

import pathlib

from vivacore import promptstore

PROMPTS = pathlib.Path(__file__).resolve().parent.parent / "prompts"

# Filenames carry a family prefix so three namespaces share one directory
# without colliding. The ids RECORDED ON EVENTS omit the extract prefix, so a
# stored read resolves to the same text whatever the filename convention.
_EXTRACT_PREFIX = "extract-"


def _file_id(version: str) -> str:
    """The filename stem for a recorded version id."""
    if version.startswith("classify-") or version.startswith("interpret-"):
        return version
    return f"{_EXTRACT_PREFIX}{version}"


def classify_prompt(version: str = "classify-v2") -> tuple[str, str]:
    """The classification prompt text and its version id (v2 knows pay stubs)."""
    return promptstore.load(PROMPTS, version), version


def interpret_prompt(version: str = "interpret-v2") -> tuple[str, str]:
    """The interpretation prompt and its version id. The caller fills
    the placeholders; the version is stamped on the ruling so the reading stays
    reproducible after the text is superseded."""
    return promptstore.load(PROMPTS, version), version


def compose_extraction(base_version: str, fragment_version: str) -> tuple[str, str]:
    """Compose the shared base with a per-type fragment. Returns (text, version),
    where the version is the self-describing composite ``extract:<base>+<frag>``
    that gets stamped on the read and round-trips through ``resolve``."""
    text = (promptstore.load(PROMPTS, _file_id(base_version)) + "\n"
            + promptstore.load(PROMPTS, _file_id(fragment_version)))
    return text, f"extract:{base_version}+{fragment_version}"


def resolve(version: str) -> str:
    """Reconstruct the exact prompt text for any recorded ``prompt_version`` — a
    classify id, an interpret id, a base/fragment id, or a composite
    ``extract:base+frag``. This is what makes a stored read reproducible without
    leaving the app, and it must never fall back to the *current* text: a
    silent default would re-explain an old reading with new instructions."""
    if version.startswith("extract:"):
        base_v, frag_v = version[len("extract:"):].split("+", 1)
        return (promptstore.load(PROMPTS, _file_id(base_v)) + "\n"
                + promptstore.load(PROMPTS, _file_id(frag_v)))
    return promptstore.load(PROMPTS, _file_id(version))


def versions() -> list[str]:
    """Every prompt version on disk, as RECORDED ids (family prefix stripped)."""
    return sorted(s[len(_EXTRACT_PREFIX):] if s.startswith(_EXTRACT_PREFIX) else s
                  for s in promptstore.ids(PROMPTS))
