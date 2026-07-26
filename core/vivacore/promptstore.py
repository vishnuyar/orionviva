"""Prompts live in FILES, not in Python. The loader that makes that true.

Every prompt this project sends to a model is a `.txt` file in a `prompts/`
directory beside the code that uses it, one file per version, **the filename is
the version id**. Nothing else. No YAML, no front-matter, no templating engine —
placeholders stay ordinary `str.format` fields, which is what every call site
already used when the prompts were string literals.

Why files, when a versioned dict in Python already existed and was tested:

  * **T8 is the point.** A recorded `prompt_version` must resolve to the exact
    text that produced the reading. When the text is a literal someone can edit
    in place, that promise holds only by everyone's good behaviour — and it
    already failed: `enrich-v1` and `enrich-v2` were edited over, so events in a
    real vault name prompts whose text no longer exists anywhere but git.
  * **The path of least resistance decides.** Adding a prompt used to mean
    editing a module, importing it, wiring a dict — while a local `\"\"\"...\"\"\"`
    was one line. Intent loses to friction every time, which is why the same
    drift happened twice after being called out. Creating a file is now the
    *cheap* path and a literal in code *fails a test*.
  * **A prompt is not code.** It is the most domain-specific data in the system
    (I5), it is what a reviewer most needs to read, and one day it is what a
    person tunes for their own agent. None of that wants a Python file.

Read-only package data (decision P1, 2026-07-25). A user-editable override
directory is deliberately deferred: an edited prompt breaks the digest chain, so
a stored read would resolve to text the person changed — a T8 hazard wearing a
feature's clothes. `load()` takes the directory as an argument precisely so that
later becomes a second search path rather than a rewrite.
"""

from __future__ import annotations

import hashlib
import pathlib

SUFFIX = ".txt"


class PromptNotFound(KeyError):
    """A recorded version that resolves to nothing.

    This is a T8 failure, not a missing-file inconvenience: some stored read
    claims to have been produced by instructions we cannot show. Raised loudly
    rather than defaulted, because a silent fallback to the *current* prompt
    would quietly re-explain old readings with new instructions."""


def _dir(package_dir: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(package_dir)


def load(package_dir: str | pathlib.Path, version: str) -> str:
    """The exact bytes of one prompt version. No interpolation, no stripping."""
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
    """Every version present, sorted. The inventory a retention test walks."""
    d = _dir(package_dir)
    return sorted(p.stem for p in d.glob(f"*{SUFFIX}")) if d.is_dir() else []


def digest(package_dir: str | pathlib.Path, version: str) -> str:
    """sha256[:16] of a version's text — the pin that makes a released prompt
    immutable. Changing a released file changes this and fails the freeze."""
    return hashlib.sha256(load(package_dir, version).encode()).hexdigest()[:16]


def digests(package_dir: str | pathlib.Path) -> dict[str, str]:
    return {v: digest(package_dir, v) for v in ids(package_dir)}
