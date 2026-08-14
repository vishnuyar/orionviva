"""Claims in the prose that a machine can check against the code.

Every check derives what it compares against: version ids from each package's
manifest, the Python floor from the pyproject files, a model adapter's permitted
imports from the dependency table of the package that holds it, a section's
count from the document's own structure, the tool count by building the
registry. Nothing is enumerated here — no list of documents, no list of
families, no expected numbers.

Markdown under a directory named `archived` is out of scope: an archived
document naming an old version is correct.

Out of reach, and named so the coverage is not read as wider than it is: any
file `.gitignore` excludes, since no test running in this repo can open one; a
claim about behaviour rather than about a name or a count, which wants a test of
the behaviour instead; and a count stated in a document that holds no table,
which has no local source to check against.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
import tomllib

import pytest

from vivacore import versions

REPO = pathlib.Path(__file__).resolve().parents[2]

# A directory whose contents are history by construction. An archived document
# naming an old version is correct, not stale.
_HISTORICAL = {"archived", ".git", "node_modules", "__pycache__", "_to_delete"}


def _prose() -> list[pathlib.Path]:
    """Every tracked markdown file whose claims are meant to be current."""
    return sorted(p for p in REPO.rglob("*.md")
                  if not _HISTORICAL & set(p.parts))


def _package_roots() -> list[pathlib.Path]:
    """Every package that declares a manifest — found, not listed."""
    return sorted(p.parent for p in REPO.rglob(versions.MANIFEST)
                  if not _HISTORICAL & set(p.parts))


def _pyprojects() -> list[pathlib.Path]:
    return sorted(p for p in REPO.rglob("pyproject.toml")
                  if not _HISTORICAL & set(p.parts))


# A token that could be a version id: starts with a letter, ends in a digit.
# Deliberately loose — membership in a manifest's `released` table is what
# decides, so this pattern never has to know what a family is called.
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]*[0-9]")


def test_no_document_names_an_older_version_than_the_one_in_force():
    """For every family the prose mentions at all, the newest id it names is the
    id in force.

    Corpus-level, not per-line: a past-tense mention of a superseded id is
    correct, and tense is not machine-readable, so the rule asks only whether
    some document names the current id. A family no document mentions is
    skipped.

    Scoped per package — two packages may use one series name for unrelated
    things, and membership in that package's `released` table is what admits a
    token. Compared against `active`, not against the highest released id, since
    a family may run behind a withdrawn one.
    """
    stale = []
    for root in _package_roots():
        manifest = versions.manifest(root)
        released = set(manifest["released"])
        in_force = {}
        for family, entry in manifest["in_force"].items():
            prefix, number = versions.series_of(entry["active"])
            in_force[prefix] = (family, number, entry["active"])

        highest: dict[str, tuple[int, str, str]] = {}
        for path in _prose():
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for token in _TOKEN.findall(line):
                    if token not in released:
                        continue
                    prefix, number = versions.series_of(token)
                    if prefix not in in_force:
                        continue          # released, but no single active pointer
                    if number > highest.get(prefix, (-1,))[0]:
                        rel = path.relative_to(REPO)
                        highest[prefix] = (number, token, f"{rel}:{line_no}")

        for prefix, (family, number, active) in in_force.items():
            if prefix not in highest:
                continue                  # the prose has never named this family
            found, token, where = highest[prefix]
            if found != number:
                stale.append(
                    f"{root.name}/{family}: in force is {active}, but the newest "
                    f"version any document names is {token} ({where})")

    assert not stale, (
        "the record has not been told about a version promotion — say so where "
        "the family is documented, in the past tense for the old id:\n  "
        + "\n  ".join(stale))


def test_a_python_floor_in_prose_is_the_floor_the_packages_declare():
    """A `Python <major>.<minor>+` claim in the prose names the highest
    `requires-python` floor any pyproject in the repo declares.

    Skips when no package declares a floor.
    """
    floors = set()
    for path in _pyprojects():
        spec = tomllib.loads(path.read_text(encoding="utf-8"))
        requires = spec.get("project", {}).get("requires-python")
        if requires:
            floors.update(re.findall(r"\d+\.\d+", requires))
    if not floors:
        pytest.skip("no package declares a Python floor")
    declared = max(floors, key=lambda v: tuple(int(n) for n in v.split(".")))

    claimed = re.compile(r"Python (\d+\.\d+)\+")
    wrong = []
    for path in _prose():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for version in claimed.findall(line):
                if version != declared:
                    wrong.append(f"{path.relative_to(REPO)}:{line_no} says "
                                 f"Python {version}+, the packages require {declared}+")
    assert not wrong, "\n  ".join([""] + wrong)


def test_the_model_adapters_import_nothing_the_package_did_not_declare():
    """Every import in `core/vivacore/models/` resolves to the standard library,
    to a dependency `core/pyproject.toml` declares, or to `vivacore` itself.

    The permitted set is derived from the dependency table rather than named
    here, so no list of provider SDKs is maintained: declaring a dependency is
    what permits importing it.
    """
    core = REPO / "core"
    if not (core / "pyproject.toml").exists():
        pytest.skip("no core package")
    spec = tomllib.loads((core / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {re.split(r"[<>=!~ \[]", d)[0].replace("-", "_").lower()
                for d in spec.get("project", {}).get("dependencies", [])}
    allowed = declared | set(sys.stdlib_module_names) | {"vivacore"}

    adapters = sorted((core / "vivacore" / "models").glob("*.py"))
    assert adapters, "the model access layer moved; this test must follow it"

    smuggled = []
    for path in adapters:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] if node.level == 0 else []
            else:
                continue
            for name in names:
                top = name.split(".")[0].lower()
                if top and top not in allowed:
                    smuggled.append(f"{path.name}:{node.lineno} imports {name}")

    assert not smuggled, (
        "a model adapter imports something core does not declare — if this is a "
        "provider SDK, it is the supply-chain trade this project keeps refusing "
        f"(threat-model-and-ingestion-security.md): {smuggled}")


# A section heading that carries its own count: `### Reading the ledger (5)`.
_COUNTED_HEADING = re.compile(r"^#{2,6}\s+(.*?)\s*\((\d+)\)\s*$")
# A row in one of those sections: `| \`query_ledger()\` | … |`
_NAMED_ROW = re.compile(r"^\|\s*`")

_CARDINALS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}
_CARDINAL = re.compile(r"\b(" + "|".join(_CARDINALS) + r")\b", re.IGNORECASE)


def test_a_section_that_counts_itself_counts_what_it_holds():
    """A heading carrying its own count, `### Reading the ledger (5)`, is
    followed by that many table rows whose first cell opens with a backtick.

    Self-consistency within one file, not agreement with code: a count of things
    that are designed rather than built has no source outside the document.
    """
    wrong = []
    for path in _prose():
        lines = path.read_text(encoding="utf-8").splitlines()
        heading = None
        for line_no, line in enumerate(lines, 1):
            match = _COUNTED_HEADING.match(line)
            if match:
                if heading and heading[2] != heading[3]:
                    wrong.append(_mismatch(path, heading))
                heading = [line_no, match.group(1), int(match.group(2)), 0]
            elif line.startswith("#") and heading:
                if heading[2] != heading[3]:
                    wrong.append(_mismatch(path, heading))
                heading = None
            elif heading and _NAMED_ROW.match(line):
                heading[3] += 1
        if heading and heading[2] != heading[3]:
            wrong.append(_mismatch(path, heading))

    assert not wrong, "a section's own count disagrees with its rows:\n  " + \
        "\n  ".join(wrong)


def _mismatch(path: pathlib.Path, heading: list) -> str:
    line_no, title, claimed, found = heading
    return (f"{path.relative_to(REPO)}:{line_no} '{title} ({claimed})' "
            f"holds {found} rows")


def test_a_documents_headline_count_is_the_sum_of_its_sections():
    """In a file whose sections carry their own counts, a cardinal number word in
    any other heading equals the sum of those counts.

    Applies only to files that already count their sections; cardinals of two or
    below are ignored, being too common in prose to read as a total.
    """
    wrong = []
    for path in _prose():
        lines = path.read_text(encoding="utf-8").splitlines()
        section_total = sum(int(m.group(2))
                            for line in lines
                            if (m := _COUNTED_HEADING.match(line)))
        if not section_total:
            continue
        for line_no, line in enumerate(lines, 1):
            if not line.startswith("#") or _COUNTED_HEADING.match(line):
                continue
            for word in _CARDINAL.findall(line):
                value = _CARDINALS[word.lower()]
                if value != section_total and value > 2:
                    wrong.append(
                        f"{path.relative_to(REPO)}:{line_no} heading says "
                        f"'{word}' where its sections sum to {section_total}")
    assert not wrong, "\n  ".join([""] + wrong)


def test_the_registered_tool_count_is_whatever_the_registry_holds():
    """A cardinal number word qualifying the word "registered" equals the number
    of tools `default_registry` builds.

    The cardinal taken is the last one before the word, and only when at most two
    words and no sentence boundary separate them: a sentence may carry both the
    design count and the registered count, and only the second is this claim.
    """
    from viva.tools import default_registry

    class _Nothing:
        def __getattr__(self, name):
            raise AssertionError("the registry must not read the projection")

    registry = default_registry(_Nothing(), locale="en_US", today="2026-01-01")
    names = {spec.name for spec in registry.specs()} \
        if hasattr(registry, "specs") else set(registry.names())
    assert names, "the registry built empty; this test's grip is gone"

    # Scanned over the whole file, not line by line, because markdown wraps and
    # "six are\nregistered" is the same claim as "six are registered". The
    # cardinal taken is the *last* one before the word, since a sentence may
    # legitimately carry both counts — "the thirteen verbs are unchanged; six
    # are registered" is the true sentence this must not trip on.
    wrong = []
    for path in _prose():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\bregistered\b", text, re.IGNORECASE):
            window = text[max(0, match.start() - 40):match.start()]
            found = list(_CARDINAL.finditer(window))
            if not found:
                continue
            gap = window[found[-1].end():]
            # The cardinal must be *counting* the registered things, not merely
            # standing near the word. A sentence boundary or more than a couple
            # of words in between means it is a different claim — "…summed to
            # thirteen. The split registered `list_movements`…" is prose about
            # an event, not an assertion that thirteen tools are registered.
            if set(".!?;") & set(gap) or len(gap.split()) > 2:
                continue
            word = found[-1].group(1)
            if _CARDINALS[word.lower()] != len(names):
                line_no = text.count("\n", 0, match.start()) + 1
                wrong.append(f"{path.relative_to(REPO)}:{line_no} says "
                             f"'{word} … registered'; the registry holds "
                             f"{len(names)}: {sorted(names)}")
    assert not wrong, "\n  ".join([""] + wrong)
