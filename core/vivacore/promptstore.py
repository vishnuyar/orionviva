"""Prompts live in FILES, not in Python. The loader that makes that true.

Every prompt this project sends to a model is a `.txt` file in a `prompts/`
directory beside the code that uses it, one file per version, **the filename is
the version id**. Nothing else. No YAML, no front-matter, no templating engine —
placeholders stay ordinary `str.format` fields.

Why files rather than a versioned dict in Python:

  * A recorded `prompt_version` must resolve to the exact text that produced a
    reading. A literal can be edited in place, and then the version a stored
    reading names no longer resolves to anything.
  * The path of least resistance decides. Creating a file is the cheap way to
    add a prompt, and model-facing text written as a Python literal fails a
    test.
  * A prompt is not code. It is the most domain-specific data in the system, it
    is what a reviewer most needs to read, and one day it is what a person tunes
    for their own agent. None of that wants a Python file.

Prompts are read-only package data. There is no user-editable override
directory: an edited prompt breaks the digest chain, so a stored read would
resolve to text the person changed. `load()` takes the directory as an argument
so that an override can later become a second search path rather than a rewrite.
"""

from __future__ import annotations

import hashlib
import pathlib

SUFFIX = ".txt"


class PromptNotFound(KeyError):
    """A recorded version that resolves to nothing.

    Some stored read claims to have been produced by instructions that cannot be
    shown. Raised loudly rather than defaulted, because a silent fallback to the
    *current* prompt would quietly re-explain old readings with new
    instructions."""


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
