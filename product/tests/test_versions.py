"""The manifest is the only declaration of what is running.

One table, in `viva/versions.json`, says which version of each family is in
force and what every released version's bytes must be. The audit is the wire:
a new version file that nobody promoted, a released file edited in place, a
released file deleted, and a family running behind its newest version with no
reason given all fail here.

The negative tests build a package root of their own and break one rule each,
so every branch of the audit is watched going red.
"""

import json
import pathlib

import pytest

from vivacore import versions

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "viva"


def _write(root, in_force, released, files):
    """A package root with a manifest and the files it claims."""
    (root / "prompts").mkdir(parents=True, exist_ok=True)
    for stem, text in files.items():
        (root / "prompts" / f"{stem}.txt").write_text(text, encoding="utf-8")
    (root / "versions.json").write_text(
        json.dumps({"in_force": in_force, "released": released}), encoding="utf-8")
    return root


def _fake(tmp_path, name, *, active="a-v1", files=None, released=None,
          withdrawn=None):
    """A one-family package whose only released version is `a-v1`, unless a test
    says otherwise."""
    root = tmp_path / name
    files = {"a-v1": "one"} if files is None else files
    entry = {"in": "prompts", "active": active}
    if withdrawn is not None:
        entry["withdrawn"] = withdrawn
    root.mkdir()
    _write(root, {"a": entry}, released, files)
    return root


def _digest(root, stem):
    return versions.fingerprint(root / "prompts" / f"{stem}.txt")


# ----------------------------------------------------------- the real manifest


def test_the_manifest_and_the_files_agree():
    """Nothing unpinned, nothing released changed or vanished, every family
    pointing at something released, and nothing newer sitting unpromoted."""
    assert versions.audit(PACKAGE) == []


def test_every_family_in_force_resolves_to_something_on_disk():
    for family in versions.manifest(PACKAGE)["in_force"]:
        active = versions.active(PACKAGE, family)
        assert versions.path_of(PACKAGE, active).exists()


def test_every_declared_file_is_packaged():
    """Resolving on disk is not resolving in an install: the audit walks the
    working tree, where every declared file is present by construction."""
    left_behind = versions.unshipped(PACKAGE, PACKAGE.parent / "pyproject.toml")
    assert left_behind == [], "\n".join(left_behind)


def test_a_stamp_carries_the_version_and_its_digest():
    """`stamp` returns the active id joined to the fingerprint of its file."""
    stamp = versions.stamp(PACKAGE, "speak")
    version, _, digest = stamp.partition("@")
    assert version == versions.active(PACKAGE, "speak")
    assert digest == versions.fingerprint(versions.path_of(PACKAGE, version))
    assert len(digest) == 16


def test_an_undeclared_family_raises_and_says_what_is_declared():
    with pytest.raises(versions.ManifestError) as e:
        versions.active(PACKAGE, "no_such_family")
    assert "speak" in str(e.value)


def test_no_version_id_is_declared_as_a_literal_in_the_modules_that_use_one():
    """No module under `viva/` writes a released version id as its own literal.

    The match is textual and reaches a quoted id only: an id assembled by
    concatenation or by an f-string passes this test and is caught nowhere. The
    extraction fragments the document-type registry names per row also pass,
    because the manifest keys them with their `extract-` file prefix and the
    registry rows carry the recorded id without it."""
    declared = {v for v in versions.manifest(PACKAGE)["released"]}
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for version in declared:
            if f'"{version}"' in source or f"'{version}'" in source:
                offenders.append(f"{path.name} names {version}")
    assert not offenders, (
        "a version id is written as a literal again — read it through "
        f"versions.active() instead: {offenders}")


# -------------------------------------------------------------- the lint bites


def test_a_new_version_nobody_promoted_fails(tmp_path):
    """a-v2 is released, no family points at it and nothing marks it withdrawn,
    so the audit names it rather than leaving a-v1 running in silence."""
    root = _fake(tmp_path, "unpromoted", files={"a-v1": "one", "a-v2": "two"},
                 released={})
    manifest = json.loads((root / "versions.json").read_text())
    manifest["released"] = {s: _digest(root, s) for s in ("a-v1", "a-v2")}
    (root / "versions.json").write_text(json.dumps(manifest))
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    problems = versions.audit(root)
    assert any("a-v2 is released and a still runs a-v1" in p for p in problems), problems


def test_holding_an_older_version_is_allowed_when_it_says_why(tmp_path):
    """A family running behind its newest version audits clean once that version
    carries a `withdrawn` reason."""
    root = _fake(tmp_path, "held", files={"a-v1": "one", "a-v2": "two"},
                 released={}, withdrawn={"a-v2": "flails on long threads"})
    manifest = json.loads((root / "versions.json").read_text())
    manifest["released"] = {s: _digest(root, s) for s in ("a-v1", "a-v2")}
    (root / "versions.json").write_text(json.dumps(manifest))
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    assert versions.audit(root) == []


def test_withdrawing_one_version_does_not_silence_the_next(tmp_path):
    """A `withdrawn` reason covers the version it is keyed to and no other: with
    a-v2 marked, a-v3 still audits as unpromoted."""
    root = _fake(tmp_path, "silenced",
                 files={"a-v1": "one", "a-v2": "two", "a-v3": "three"},
                 released={}, withdrawn={"a-v2": "flails on long threads"})
    manifest = json.loads((root / "versions.json").read_text())
    manifest["released"] = {s: _digest(root, s) for s in ("a-v1", "a-v2", "a-v3")}
    (root / "versions.json").write_text(json.dumps(manifest))
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    problems = versions.audit(root)
    assert any("a-v3 is released and a still runs a-v1" in p for p in problems), problems
    assert not any("a-v2 is released" in p for p in problems), problems


def test_withdrawing_a_version_that_was_never_released_fails(tmp_path):
    root = _fake(tmp_path, "phantom", released={},
                 withdrawn={"a-v7": "never existed"})
    manifest = json.loads((root / "versions.json").read_text())
    manifest["released"] = {"a-v1": _digest(root, "a-v1")}
    (root / "versions.json").write_text(json.dumps(manifest))
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    assert any("withdraws a-v7" in p for p in versions.audit(root))


def test_a_stray_hidden_file_is_not_a_changed_pack(tmp_path):
    """A hidden file appearing inside a pack directory leaves the pack's
    fingerprint unchanged."""
    pack = tmp_path / "pack-v1"
    pack.mkdir()
    (pack / "phrasings.json").write_text("{}")
    before = versions.fingerprint(pack)
    (pack / ".DS_Store").write_bytes(b"\x00junk")
    assert versions.fingerprint(pack) == before


def test_an_unpinned_file_fails(tmp_path):
    root = _fake(tmp_path, "unpinned", files={"a-v1": "one", "b-v1": "two"},
                 released={})
    manifest = json.loads((root / "versions.json").read_text())
    manifest["released"] = {"a-v1": _digest(root, "a-v1")}
    (root / "versions.json").write_text(json.dumps(manifest))
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    assert any("b-v1 exists" in p and "unpinned" in p for p in versions.audit(root))


def test_editing_a_released_version_fails(tmp_path):
    root = _fake(tmp_path, "edited", released={})
    manifest = json.loads((root / "versions.json").read_text())
    manifest["released"] = {"a-v1": _digest(root, "a-v1")}
    (root / "versions.json").write_text(json.dumps(manifest))
    (root / "prompts" / "a-v1.txt").write_text("one, but different")
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    problems = versions.audit(root)
    assert any("a-v1 changed" in p and "immutable" in p for p in problems), problems


def test_deleting_a_released_version_fails(tmp_path):
    root = _fake(tmp_path, "deleted", released={})
    manifest = json.loads((root / "versions.json").read_text())
    manifest["released"] = {"a-v1": _digest(root, "a-v1"),
                            "a-v0": "0000000000000000"}
    (root / "versions.json").write_text(json.dumps(manifest))
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    assert any("a-v0 is pinned and absent" in p for p in versions.audit(root))


def test_a_family_pointing_at_an_unreleased_version_fails(tmp_path):
    root = _fake(tmp_path, "dangling", active="a-v9", released={})
    manifest = json.loads((root / "versions.json").read_text())
    manifest["released"] = {"a-v1": _digest(root, "a-v1")}
    (root / "versions.json").write_text(json.dumps(manifest))
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    assert any("not released" in p for p in versions.audit(root))


def test_a_package_with_no_manifest_raises_rather_than_defaulting(tmp_path):
    """A package root with no `versions.json` raises ManifestError."""
    (tmp_path / "bare").mkdir()
    versions._parsed.cache_clear()
    with pytest.raises(versions.ManifestError):
        versions.manifest(tmp_path / "bare")


def test_the_series_is_the_whole_trailing_number(tmp_path):
    """The series is everything before the whole trailing run of digits, so
    `tools-v10` is `tools-v` at 10 rather than `tools-v1` at 0."""
    assert versions.series_of("tools-v10") == ("tools-v", 10)
    assert versions.series_of("tools-v9") == ("tools-v", 9)
    assert versions.series_of("speak-final-v6") == ("speak-final-v", 6)
    assert versions.series_of("speak-v6") == ("speak-v", 6)


# ------------------------------------------------- what the wheel would carry


def _packaged(root, globs, excluding=()):
    """A pyproject beside `root` that ships `globs` from it and nothing else,
    minus anything `excluding` names."""
    path = root.parent / "pyproject.toml"
    def table(name, patterns):
        listed = ", ".join(f'"{g}"' for g in patterns)
        return f'[tool.setuptools.{name}]\n"{root.name}" = [{listed}]\n'
    text = table("package-data", globs)
    if excluding:
        text += table("exclude-package-data", excluding)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_declared_directory_that_does_not_ship_fails(tmp_path):
    """A versioned file that resolves here and that no package-data pattern
    covers is named."""
    root = _fake(tmp_path, "pkg")
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    left = versions.unshipped(root, _packaged(root, ["versions.json"]))

    assert any("a-v1.txt" in line for line in left)


def test_the_manifest_itself_must_ship(tmp_path):
    """It is read before anything it declares, so leaving it behind fails first
    and takes every family with it."""
    root = _fake(tmp_path, "pkg")
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    left = versions.unshipped(root, _packaged(root, ["prompts/*.txt"]))

    assert any("versions.json" in line for line in left)


def test_a_pattern_does_not_reach_past_a_directory_boundary(tmp_path):
    """A package-data `*` stops at a `/`, so `*.txt` covers a file at the root of
    the package and not one a directory down."""
    root = _fake(tmp_path, "pkg")
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    left = versions.unshipped(root, _packaged(root, ["versions.json", "*.txt"]))

    assert any("a-v1.txt" in line for line in left)


def test_a_version_held_as_a_directory_ships_every_document_it_is_hashed_from(
        tmp_path):
    """A pack missing one document is a changed pack, so covering some of its
    files is not covering the pack."""
    root = _fake(tmp_path, "pkg")
    pack = root / "prompts" / "a-v2"
    pack.mkdir()
    (pack / "tone.md").write_text("warm", encoding="utf-8")
    (pack / "moments.json").write_text("{}", encoding="utf-8")
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    left = versions.unshipped(
        root, _packaged(root, ["versions.json", "prompts/*.txt",
                               "prompts/*/*.json"]))

    assert any("tone.md" in line for line in left)
    assert not any("moments.json" in line for line in left)


def test_a_fully_packaged_manifest_leaves_nothing_behind(tmp_path):
    root = _fake(tmp_path, "pkg")
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    assert versions.unshipped(
        root, _packaged(root, ["versions.json", "prompts/*.txt"])) == []


def _pack(root, stem, files):
    """A version held as a directory of documents, inside the declared folder."""
    pack = root / "prompts" / stem
    pack.mkdir()
    for name, text in files.items():
        (pack / name).write_text(text, encoding="utf-8")
    return pack


def test_an_excluded_file_is_not_shipped_though_a_pattern_covers_it(tmp_path):
    """A file matched by both tables is named: covering it is not shipping it."""
    root = _fake(tmp_path, "pkg")
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    left = versions.unshipped(
        root, _packaged(root, ["versions.json", "prompts/*.txt"],
                        excluding=["prompts/a-*.txt"]))

    assert any("a-v1.txt" in line and "exclude-package-data" in line
               for line in left)


def test_an_exclusion_crosses_a_directory_boundary(tmp_path):
    """An exclusion is matched with `fnmatch`, where a `*` crosses a `/`, so
    `prompts/*` reaches a document inside a pack and not only beside it."""
    root = _fake(tmp_path, "pkg")
    _pack(root, "a-v2", {"tone.md": "warm"})
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    left = versions.unshipped(
        root, _packaged(root, ["versions.json", "prompts/*.txt",
                               "prompts/*/*.md"],
                        excluding=["prompts/*"]))

    assert any("a-v2/tone.md" in line for line in left)


def test_an_exclusion_reads_a_character_class(tmp_path):
    """`[ab]` names a set of characters to `fnmatch`, so an exclusion written
    that way drops the file it matches."""
    root = _fake(tmp_path, "pkg")
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    left = versions.unshipped(
        root, _packaged(root, ["versions.json", "prompts/*.txt"],
                        excluding=["prompts/[ab]-v1.txt"]))

    assert any("a-v1.txt" in line for line in left)


def test_a_double_star_crosses_any_number_of_directories(tmp_path):
    """`**/` matches no segments as readily as two, so one pattern covers the
    manifest at the root and a document two directories down."""
    root = _fake(tmp_path, "pkg")
    _pack(root, "a-v2", {"tone.md": "warm"})
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    assert versions.unshipped(
        root, _packaged(root, ["**/*.json", "**/*.txt", "**/*.md"])) == []


def test_a_question_mark_matches_one_character_and_not_a_separator(tmp_path):
    """`?` stands for exactly one character, and never for the `/` between two
    segments."""
    root = _fake(tmp_path, "pkg")
    versions._parsed.cache_clear()
    versions._index.cache_clear()

    assert versions.unshipped(
        root, _packaged(root, ["versions.json", "prompts/a-v?.txt"])) == []
    assert any("a-v1.txt" in line for line in versions.unshipped(
        root, _packaged(root, ["versions.json", "prompts/a-?.txt"])))
    assert any("a-v1.txt" in line for line in versions.unshipped(
        root, _packaged(root, ["versions.json", "prompts?a-v1.txt"])))


def test_a_pattern_under_the_wildcard_key_applies_to_this_package(tmp_path):
    """A `*` key stands for every package, so a pattern listed under it covers
    the same files as one listed under the package's own name."""
    root = _fake(tmp_path, "pkg")
    versions._parsed.cache_clear()
    versions._index.cache_clear()
    path = root.parent / "pyproject.toml"
    path.write_text('[tool.setuptools.package-data]\n'
                    '"*" = ["versions.json", "prompts/*.txt"]\n', encoding="utf-8")

    assert versions.unshipped(root, path) == []
