"""Prompts as versioned, addressable data — files on disk.

Three families: a **classify** pass names the document, an **extract** pass runs
the prompt belonging to that type's profile, and **interpret** reads a person's
own sentence.

Every version lives in `viva/prompts/<id>.txt`; this module holds no prompt text,
only the composition rules and the accessors. The files are append-only —
changing a prompt means adding a new id — so a read recorded under ``card-v1``
resolves to card-v1's text forever. ``test_prompt_library`` pins the digests.

An extraction prompt is composed from a shared ``base`` (the parse shape and
universal rules, identical for every balance type) plus a per-type fragment,
yielding the self-describing version id ``extract:base-v1+card-v1``.
"""

from __future__ import annotations

import pathlib

from vivacore import promptstore

PROMPTS = pathlib.Path(__file__).resolve().parent.parent / "prompts"

# Filenames carry a family prefix so the three namespaces share one directory
# without colliding. The ids recorded on events omit the extract prefix.
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
    """The interpretation prompt and its version id.

    The caller fills the placeholders. The version is stamped on the ruling, so
    the reading stays reproducible after the text is superseded."""
    return promptstore.load(PROMPTS, version), version


def compose_extraction(base_version: str, fragment_version: str) -> tuple[str, str]:
    """Compose the shared base with a per-type fragment.

    Returns (text, version), the version being the composite
    ``extract:<base>+<frag>`` that is stamped on the read and round-trips
    through ``resolve``."""
    text = (promptstore.load(PROMPTS, _file_id(base_version)) + "\n"
            + promptstore.load(PROMPTS, _file_id(fragment_version)))
    return text, f"extract:{base_version}+{fragment_version}"


def resolve(version: str) -> str:
    """Reconstruct the exact prompt text for any recorded ``prompt_version``.

    Accepts a classify id, an interpret id, a base or fragment id, or the
    composite ``extract:base+frag``. Raises rather than falling back to the
    current text, so an old reading is never re-explained with new
    instructions."""
    if version.startswith("extract:"):
        base_v, frag_v = version[len("extract:"):].split("+", 1)
        return (promptstore.load(PROMPTS, _file_id(base_v)) + "\n"
                + promptstore.load(PROMPTS, _file_id(frag_v)))
    return promptstore.load(PROMPTS, _file_id(version))


def versions() -> list[str]:
    """Every prompt version on disk, as recorded ids: the extract prefix is
    stripped, classify and interpret ids are returned as they are."""
    return sorted(s[len(_EXTRACT_PREFIX):] if s.startswith(_EXTRACT_PREFIX) else s
                  for s in promptstore.ids(PROMPTS))
