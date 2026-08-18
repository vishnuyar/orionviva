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


# ---------------------------------------------------------------------------
# The rule index. `docs/rules.md` is written by hand from the rule blocks the
# documents carry, so nothing but the checks below stops it drifting from them
# — the drift this documentation scheme exists to prevent, reappearing one
# level up. Both sides are derived: the rules by walking the documents, the
# index by reading its own tables. No rule and no document is named here.
# ---------------------------------------------------------------------------

# A rule block opens `### <ID> — <name>`, which covers T1, I2, M1, X3, ADR-007
# and every cluster prefix without knowing what any of them are called.
_RULE_HEADING = re.compile(r"^###\s+(?P<id>[A-Z][A-Z0-9]*(?:-[0-9]+)?)\s+[—-]\s+(?P<name>.+?)\s*$")
_RULE_FIELD = re.compile(r"^\*\*(?P<field>State|Code|Test):\*\*\s*(?P<value>.*?)\s*$")
_INDEX_ROW = re.compile(r"^\|\s*\*{0,2}(?P<id>[A-Z][A-Z0-9]*(?:-[0-9]+)?)\*{0,2}\s*\|"
                        r"\s*(?P<name>[^|]*?)\s*\|\s*(?P<state>[^|]*?)\s*\|")

_RULE_INDEX = REPO / "docs" / "rules.md"
# A citation names a file, a function, or `file.py::function`. Only the
# function is a test name, so the file half is removed before the match.
_TEST_FILE = re.compile(r"\S*\.py")
_TEST_NAME = re.compile(r"\btest_[A-Za-z0-9_]+")


def _rule_documents() -> list[pathlib.Path]:
    """Every document that may define a rule — found, not listed."""
    return sorted(p for p in (REPO / "docs").rglob("*.md")
                  if not _HISTORICAL & set(p.parts) and p != _RULE_INDEX)


def _canonical_state(raw: str) -> str:
    """One state vocabulary out of two spellings.

    A rule block writes the machine form (`enforced-with-exception`); the index
    writes the reader's form (`enforced *(exception)*`). Both reduce to the same
    token, so neither spelling has to be listed as the correct one.
    """
    text = raw.replace("*", "").replace("_", "").strip().lower()
    for token in ("contradicted", "unmet", "untestable"):
        if token in text:
            return token
    held = "by-review" if "review" in text else "enforced"
    return f"{held}-with-exception" if "exception" in text else held


def _rule_blocks() -> dict[str, list[dict]]:
    """Every rule every document defines, with the fields it declares."""
    found: dict[str, list[dict]] = {}
    for path in _rule_documents():
        block = None
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            heading = _RULE_HEADING.match(line)
            if heading:
                block = {"id": heading.group("id"), "name": heading.group("name"),
                         "doc": path, "line": line_no,
                         "state": None, "code": None, "test": None}
                found.setdefault(block["id"], []).append(block)
            elif line.startswith("#"):
                block = None
            elif block:
                field = _RULE_FIELD.match(line)
                if field and block[field.group("field").lower()] is None:
                    block[field.group("field").lower()] = field.group("value")
    return found


# The index holds two kinds of table. The full one carries a Test column and
# lists every rule once; the shorter ones restate the subset that no test pins.
# A rule therefore appears twice on purpose, and the two are read apart here.
_FULL_TABLE = "| Rule | Name | State | Doc | Test |"
_SUBSET_TABLE = "| Rule | Name | State | Doc |"


def _index_rows(full: bool = True) -> dict[str, list[dict]]:
    """Every row of the index's full tables, or of its no-test subsets."""
    wanted = _FULL_TABLE if full else _SUBSET_TABLE
    rows: dict[str, list[dict]] = {}
    inside = False
    for line in _RULE_INDEX.read_text(encoding="utf-8").splitlines():
        if line.startswith("| Rule |"):
            inside = line.strip() == wanted
            continue
        if inside and not line.startswith("|"):
            inside = False
        if inside:
            row = _INDEX_ROW.match(line)
            if row and not set(row.group("id")) <= {"-"}:
                rows.setdefault(row.group("id"), []).append(
                    {"name": row.group("name"), "state": row.group("state"),
                     "line": line})
    return rows


def _names_evidence(block: dict) -> bool:
    """Whether a rule block says what a person could have read.

    Usually that is a file and a line. But a prohibition is met by the absence
    of the thing it forbids, and an absence has no line — so a block may cite
    one, provided it says which search established it. A bare `none found`
    says nothing anyone could check.
    """
    code = (block["code"] or "").strip()
    if not code.lower().startswith("none"):
        return bool(code)
    return bool(re.sub(r"^none( found)?", "", code, flags=re.I).strip(" .,—-()"))


def _pins_a_test(block: dict) -> bool:
    """Whether a rule block names a test, as opposed to explaining that none
    exists — a `**Test:**` line may say `none` and then name the tests it
    considered and rejected."""
    field = (block["test"] or "").strip()
    if field.lower().startswith("none"):
        return False
    return bool(_TEST_NAME.findall(_TEST_FILE.sub("", field)))


def _where(block: dict) -> str:
    return f"{block['doc'].relative_to(REPO)}:{block['line']}"


def test_a_rule_id_is_defined_once_in_the_whole_folder():
    """Two documents defining the same id give a reader two different rules
    under one name, and every citation of it becomes ambiguous."""
    clashes = [f"{rule_id} is defined {len(blocks)} times: "
               + ", ".join(f"{_where(b)} ({b['name']})" for b in blocks)
               for rule_id, blocks in sorted(_rule_blocks().items()) if len(blocks) > 1]

    assert not clashes, "a rule id names more than one rule:\n  " + "\n  ".join(clashes)


def test_every_rule_a_document_defines_is_indexed_exactly_once():
    """The index claims to hold every rule once. It is written by hand, so this
    is the only thing standing between it and the documents it was drawn from."""
    blocks, rows = _rule_blocks(), _index_rows()
    wrong = []
    for rule_id, defined in sorted(blocks.items()):
        if rule_id not in rows:
            wrong.append(f"{rule_id} ({_where(defined[0])}) is in no index table")
        elif len(rows[rule_id]) > 1:
            wrong.append(f"{rule_id} has {len(rows[rule_id])} index rows")
    for rule_id in sorted(rows):
        if rule_id not in blocks:
            wrong.append(f"{rule_id} is indexed but no document defines it")

    assert not wrong, "the rule index disagrees with the rules it indexes:\n  " + \
        "\n  ".join(wrong)


def test_the_index_states_the_state_the_rule_block_states():
    """A rule's state is the one thing a reader takes from the index without
    opening the document — so a state corrected in one place and not the other
    is the drift this scheme exists to prevent."""
    blocks, rows = _rule_blocks(), _index_rows()
    wrong = []
    for rule_id, defined in sorted(blocks.items()):
        if len(defined) != 1 or len(rows.get(rule_id, [])) != 1:
            continue                                # the tests above own these
        stated = _canonical_state(defined[0]["state"] or "")
        indexed = _canonical_state(rows[rule_id][0]["state"])
        if stated != indexed:
            wrong.append(f"{rule_id}: {defined[0]['doc'].relative_to(REPO)} says "
                         f"{stated!r}, the index says {indexed!r}")

    assert not wrong, "a rule's state differs between its document and the index:\n  " + \
        "\n  ".join(wrong)


def test_every_rule_declares_a_state_and_says_what_pins_it():
    """The shape is the contract. A block with no state cannot be indexed, and
    one with no test line hides whether anything holds the code to it."""
    missing = [f"{rule_id} ({_where(b)}) declares no **{field.title()}:**"
               for rule_id, blocks in sorted(_rule_blocks().items())
               for b in blocks for field in ("state", "test") if not b[field]]

    assert not missing, "a rule block is missing a required field:\n  " + \
        "\n  ".join(missing)


def test_a_test_a_rule_cites_is_a_test_that_exists():
    """A rule pointing at a test nobody wrote is worse than one pointing at
    nothing: it reads as pinned. Every cited name is looked up in the suite."""
    written = set()
    for path in REPO.rglob("test_*.py"):
        if _HISTORICAL & set(path.parts) or ".venv" in path.parts:
            continue
        written.update(node.name for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                       if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"))

    wrong = [f"{rule_id} ({_where(b)}) cites {name}, which no test file defines"
             for rule_id, blocks in sorted(_rule_blocks().items())
             for b in blocks
             for name in _TEST_NAME.findall(_TEST_FILE.sub("", b["test"] or ""))
             if name not in written]

    assert not wrong, "a rule cites a test that does not exist:\n  " + "\n  ".join(wrong)


def test_a_rule_no_test_pins_is_listed_among_the_rules_no_test_pins():
    """The index's closing lists are the backlog this scheme exists to produce.
    They are restated by hand from the same blocks, so a rule that gains a test
    and stays on the list — or loses one and never joins it — reads as covered
    when it is not."""
    listed = _index_rows(full=False)
    wrong = []
    for rule_id, blocks in sorted(_rule_blocks().items()):
        if len(blocks) != 1:
            continue                                # another test owns these
        pinned, on_list = _pins_a_test(blocks[0]), rule_id in listed
        if pinned and on_list:
            wrong.append(f"{rule_id} cites a test and is still on the no-test list")
        elif not pinned and not on_list:
            wrong.append(f"{rule_id} ({_where(blocks[0])}) cites no test "
                         f"and is on no no-test list")
        elif on_list and len(listed[rule_id]) > 1:
            wrong.append(f"{rule_id} is on {len(listed[rule_id])} no-test lists")

    assert not wrong, "the no-test lists disagree with the rules:\n  " + \
        "\n  ".join(wrong)


def test_a_rules_state_is_the_evidence_it_cites():
    """A state is a claim about *how* the rule is known, so the evidence beside
    it has to match: `enforced` means a test holds the code to it, `by-review`
    means a person read the code and no test does, and `untestable` means no
    test could. A state typed without the evidence it names is the drift this
    vocabulary was split apart to make visible.

    `unmet` and `contradicted` are deliberately unconstrained: a rule can be
    part-built with a test on the built part, and a contradiction is often found
    by the very test that fails to hold it.
    """
    wrong = []
    for rule_id, blocks in sorted(_rule_blocks().items()):
        for b in blocks:
            state, pinned, coded = _canonical_state(b["state"] or ""), _pins_a_test(b), _names_evidence(b)
            if state.startswith("enforced") and not pinned:
                wrong.append(f"{rule_id} ({_where(b)}) is {state} and cites no test — "
                             f"say by-review if a person checked it")
            elif state.startswith("by-review"):
                if pinned:
                    wrong.append(f"{rule_id} ({_where(b)}) is {state} and cites a test — "
                                 f"say enforced if the test holds it")
                if not coded:
                    wrong.append(f"{rule_id} ({_where(b)}) is {state} but names no evidence — "
                                 f"give a file and line, or say which search "
                                 f"established the absence")
            elif state == "untestable" and pinned:
                wrong.append(f"{rule_id} ({_where(b)}) is untestable and cites a test")

    assert not wrong, "a rule's state is not the evidence it cites:\n  " + \
        "\n  ".join(wrong)


# A citation's URL may carry a date; the document is not thereby naming one.
_LINK_TARGET = re.compile(r"\]\([^)]*\)|https?://\S+")
_A_DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:January|February|March|April|May|June|July|August|September"
    r"|October|November|December)\s+\d{4}\b"
    r"|\*\*(?:Last updated|Created|Updated)"
    r"|\b(?:Refined|Amended|Superseded|Ruled|Decided|Added|Corrected)\s+\d{4}\b"
    r"|\bas of\s+\d{4}\b", re.I)

# Two directories are dated on purpose: an ADR records reasoning at a moment,
# and an archived document is a historical record. Everything else is present
# tense, and derives its own exemption from where it sits rather than a list.
_DATED_BY_DESIGN = {"decisions", "archived"}


def _document_header(path: pathlib.Path) -> str:
    """Everything before the first `## ` section — where a document declares
    itself."""
    return path.read_text(encoding="utf-8").split("\n## ", 1)[0]


def test_a_document_names_no_date():
    """The one property this folder's whole format exists to produce, and the
    only one nothing else here can hold.

    A dated document invites the next writer to append rather than revise, and
    an appended document is a stack of amendments a reader must replay before
    they can find today's rule. Every document in this folder accreted exactly
    that way once. `docs/decisions/` and `docs/archived/` are exempt by where
    they sit: an ADR records a moment on purpose, and an archived document is
    history by construction.
    """
    dated = []
    for path in (REPO / "docs").rglob("*.md"):
        if _DATED_BY_DESIGN & set(path.parts) or _HISTORICAL & set(path.parts):
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for found in _A_DATE.finditer(_LINK_TARGET.sub("", line)):
                dated.append(f"{path.relative_to(REPO)}:{line_no} names "
                             f"{found.group(0)!r}")

    assert not dated, ("a document names a date — say it in the present tense, or "
                       "put what rots under Open:\n  " + "\n  ".join(dated))


def test_a_document_declares_the_rules_it_defines():
    """A document's `**Rules:**` line is how a reader knows what it is for, and
    the only place a rule id appears outside its own block and the index. It is
    written by hand, so a rule added without touching it goes unannounced — and
    a renumbering leaves the old id standing."""
    defined: dict[pathlib.Path, set] = {}
    for rule_id, blocks in _rule_blocks().items():
        for b in blocks:
            defined.setdefault(b["doc"], set()).add(rule_id)

    wrong = []
    for path in _rule_documents():
        header = _document_header(path)
        line = re.search(r"^\*\*Rules:\*\*(.*)$", header, re.M)
        declared = set()
        if line:
            declared = set(re.findall(r"\b[A-Z][A-Z0-9]*(?:-[0-9]+)?\b",
                                      line.group(1)))
        holds = defined.get(path, set())
        if not declared and not holds:
            continue
        if holds - declared:
            wrong.append(f"{path.relative_to(REPO)} defines but does not declare: "
                         + ", ".join(sorted(holds - declared)))
        if declared - holds:
            wrong.append(f"{path.relative_to(REPO)} declares but does not define: "
                         + ", ".join(sorted(declared - holds)))

    assert not wrong, "a document's **Rules:** line is not the rules it holds:\n  " + \
        "\n  ".join(wrong)


# The cross-cutting invariants are named by family and serial — T1, I2, M1, X3.
# Which families exist is not listed here; a citation is checked against the
# rules the documents actually define.
_AN_INVARIANT = re.compile(r"\b([TIMX][0-9]+)\b")


def test_an_invariant_a_document_cites_is_one_that_exists():
    """An invariant is cited by the rule it bears on, rather than listed in a
    header the document as a whole claims. That is the more precise form — it
    says *which* rule answers to the invariant — but it scatters the citation
    across hundreds of sentences, where a renumbering or a typo would leave a
    reference pointing at nothing and reading as though it pointed somewhere.
    """
    defined = set(_rule_blocks())
    dangling = []
    for path in _rule_documents():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for cited in _AN_INVARIANT.findall(_LINK_TARGET.sub("", line)):
                if cited not in defined:
                    dangling.append(f"{path.relative_to(REPO)}:{line_no} cites {cited}, "
                                    f"which no document defines")

    assert not dangling, "a document cites an invariant that does not exist:\n  " + \
        "\n  ".join(dangling)
