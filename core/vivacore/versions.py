"""The manifest: which version of each versioned file a package has in force.

A package's `versions.json` is the single declaration of what is running. It has
two halves and they answer different questions.

``released`` is the pin table: every version file the package holds, by stem,
against the fingerprint of its bytes. A released version's content never
changes, so a digest that no longer matches fails the suite.

``in_force`` names the families that have one active pointer, and which
directory that family lives in. Code reads its pointer through :func:`active`
instead of declaring a literal, so promoting a version is a one-line change in
the manifest and nothing else.

Not every versioned file belongs to a family. A file pinned in ``released`` but
claimed by no ``in_force`` entry is one whose pointer lives elsewhere as data —
the document-type registry names its own extraction prompts per row. Such a file
is held immutable like any other; it simply has no single active version to
resolve.

A family whose ``active`` is not its highest released version must say, version
by version, why each newer one is not in force: ``withdrawn`` maps a version to
the reason it was passed over. The mark is per version, so a version released
after a withdrawal is unmarked and raises the same complaint as any other.

Design rationale: docs/prompts-as-files.md
"""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re
from functools import lru_cache

MANIFEST = "versions.json"

# A version file is named for its version, and a version ends in a number. The
# series is everything before the whole trailing run of digits, so `speak-v6`
# and `speak-final-v6` are different series, and `speak-v10` is series
# `speak-v` at 10 rather than series `speak-v1` at 0.
_SERIES = re.compile(r"^(.*[^\d])(\d+)$")

# What may carry a version in a declared directory: a prompt, a pack held as one
# document, or a pack held as a directory of them.
_SUFFIXES = (".txt", ".json")


class ManifestError(RuntimeError):
    """The manifest is absent, malformed, or names something that is not there.

    Raised rather than falling back to any version."""


def _root(package_root: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(package_root)


@lru_cache(maxsize=8)
def _parsed(package_root: str | pathlib.Path) -> dict:
    path = _root(package_root) / MANIFEST
    if not path.is_file():
        raise ManifestError(
            f"no {MANIFEST} in {package_root}. Every package that ships "
            f"versioned files declares what it has in force.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ManifestError(f"{path} is not readable JSON: {e}") from None
    for half in ("in_force", "released"):
        if half not in data:
            raise ManifestError(f"{path} has no {half!r} section")
    for name, entry in data["in_force"].items():
        for required in ("in", "active"):
            if required not in entry:
                raise ManifestError(
                    f"{path}: family {name!r} does not say {required!r}")
    return data


def manifest(package_root: str | pathlib.Path) -> dict:
    """The package's version declaration, parsed once and handed out as a copy
    so a caller cannot edit what every later reader sees."""
    return copy.deepcopy(_parsed(package_root))


def series_of(version: str) -> tuple[str, int]:
    """`('speak-v', 6)` for `speak-v6` — the series it belongs to and its place
    in it. Raises ValueError for a version that does not end in a number."""
    m = _SERIES.match(version)
    if not m:
        raise ValueError(f"{version!r} does not end in a version number")
    return m.group(1), int(m.group(2))


def contents(path: pathlib.Path) -> list[pathlib.Path]:
    """The files a version directory consists of, in the order it is hashed.

    Files whose name begins with a dot are not content and are skipped."""
    return sorted(p for p in path.iterdir()
                  if p.is_file() and not p.name.startswith("."))


def fingerprint(path: pathlib.Path) -> str:
    """sha256[:16] of what is at `path` — its bytes for a file, or every file it
    holds, by name in sorted order, for a directory.

    The single definition of a version's bytes; the audit and the freeze tests
    both call it."""
    if path.is_dir():
        h = hashlib.sha256()
        for p in contents(path):
            h.update(p.name.encode())
            h.update(p.read_bytes())
        return h.hexdigest()[:16]
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@lru_cache(maxsize=8)
def _index(package_root: str | pathlib.Path) -> dict:
    """Every versioned file in the declared directories, by stem.

    Raises ManifestError when one stem is present in two directories: a pin
    table keyed by stem cannot say which of them it froze."""
    root = _root(package_root)
    found: dict[str, pathlib.Path] = {}
    for folder in sorted({e["in"] for e in _parsed(package_root)["in_force"].values()}):
        d = root / folder
        if not d.is_dir():
            raise ManifestError(f"{d} is declared in {MANIFEST} and does not exist")
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix not in _SUFFIXES:
                continue
            if not _SERIES.match(p.stem):
                continue
            if p.stem in found:
                raise ManifestError(
                    f"{p.stem!r} exists in both {found[p.stem].parent} and "
                    f"{p.parent}; a version stem names one file")
            found[p.stem] = p
    return found


def path_of(package_root: str | pathlib.Path, version: str) -> pathlib.Path:
    """Where a released version lives. Raises ManifestError if it is not there."""
    try:
        return _index(package_root)[version]
    except KeyError:
        raise ManifestError(
            f"{version!r} is not among the versioned files of {package_root}"
        ) from None


def active(package_root: str | pathlib.Path, family: str) -> str:
    """The version of `family` this package runs. The one accessor code uses;
    nothing declares a version id as a literal."""
    entry = _parsed(package_root)["in_force"].get(family)
    if entry is None:
        known = ", ".join(sorted(_parsed(package_root)["in_force"]))
        raise ManifestError(
            f"no family {family!r} in {package_root}/{MANIFEST}. Declared: {known}")
    return entry["active"]


def pin(package_root: str | pathlib.Path, version: str) -> str:
    """The fingerprint a released version is frozen against."""
    released = _parsed(package_root)["released"]
    if version not in released:
        raise ManifestError(f"{version!r} is not pinned in {package_root}/{MANIFEST}")
    return released[version]


def stamp(package_root: str | pathlib.Path, family: str) -> str:
    """`<active version>@<fingerprint>` — the id a record stamps, joined to the
    bytes it must resolve to."""
    version = active(package_root, family)
    return f"{version}@{pin(package_root, version)}"


def audit(package_root: str | pathlib.Path) -> list[str]:
    """Every way the manifest and the files on disk disagree, in plain sentences.

    Empty means: nothing is unpinned, nothing released has changed or vanished,
    every family points at something released, and any family running behind its
    newest version says why."""
    data = _parsed(package_root)
    released, in_force = data["released"], data["in_force"]
    index = _index(package_root)
    out: list[str] = []

    for stem, path in index.items():
        if stem not in released:
            out.append(
                f"{stem} exists in {path.parent.name}/ and is unpinned — add its "
                f"digest to released in {MANIFEST}, in the commit that adds it")
    for stem, digest in sorted(released.items()):
        if stem not in index:
            out.append(f"{stem} is pinned and absent — versions are append-only")
            continue
        got = fingerprint(index[stem])
        if got != digest:
            out.append(
                f"{stem} changed ({digest} -> {got}) — a released version is "
                f"immutable; add a new version rather than editing this one")

    seen: dict[str, str] = {}
    for name, entry in sorted(in_force.items()):
        version = entry.get("active", "")
        if version not in released:
            out.append(f"{name} runs {version!r}, which is not released")
            continue
        prefix, number = series_of(version)
        if prefix in seen:
            out.append(f"{name} and {seen[prefix]} both claim the series {prefix!r}")
        seen[prefix] = name
        withdrawn = entry.get("withdrawn", {})
        for other in sorted(released):
            series, place = series_of(other)
            if series != prefix or place <= number:
                continue
            if not str(withdrawn.get(other, "")).strip():
                out.append(
                    f"{other} is released and {name} still runs {version} — "
                    f"promote it in {MANIFEST}, or record in this family's "
                    f"'withdrawn' why {other} is not in force")
        for other in sorted(withdrawn):
            if other not in released:
                out.append(f"{name} withdraws {other}, which is not released")
    return out
