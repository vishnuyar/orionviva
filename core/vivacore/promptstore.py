"""The loader for prompts held as files.

Every prompt this project sends to a model is a `.txt` file in a `prompts/`
directory beside the code that uses it, one file per version, the filename being
the version id. No YAML, no front-matter, no templating engine — placeholders
stay ordinary `str.format` fields.

Prompts are read-only package data. There is no user-editable override
directory; `load()` takes the directory as an argument, so an override can later
become a second search path rather than a rewrite.

Design rationale: docs/prompts-as-files.md
"""

from __future__ import annotations

import hashlib
import pathlib

SUFFIX = ".txt"


class PromptNotFound(KeyError):
    """A recorded prompt version that resolves to no file.

    Raised rather than defaulted: a stored reading must resolve to the exact
    instructions that produced it (T8), never to the current ones."""


def _dir(package_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(package_dir)


def load(package_dir: str | pathlib.Path, version: str) -> str:
    """The exact text of one prompt version — no interpolation, no stripping.

    Raises PromptNotFound if the version has no file."""
    path = _dir(package_dir) / f"{version}{SUFFIX}"
    if not path.is_file():
        raise PromptNotFound(
            f"prompt {version!r} not found in {package_dir}. A recorded "
            f"prompt_version must always resolve (T8) — if this is a version "
            f"that was edited over rather than superseded, recover it from git "
            f"history and add {version}{SUFFIX} rather than pointing it at the "
            f"current text.")
    return path.read_text(encoding="utf-8")


def ids(package_dir: str | pathlib.Path) -> list[str]:
    """Every version present in the directory, sorted. Empty if it does not
    exist."""
    d = _dir(package_dir)
    return sorted(p.stem for p in d.glob(f"*{SUFFIX}")) if d.is_dir() else []


def digest(package_dir: str | pathlib.Path, version: str) -> str:
    """sha256[:16] of a version's text — the pin a released prompt is frozen
    against. Editing a released file changes this."""
    return hashlib.sha256(load(package_dir, version).encode()).hexdigest()[:16]


def digests(package_dir: str | pathlib.Path) -> dict[str, str]:
    return {v: digest(package_dir, v) for v in ids(package_dir)}
