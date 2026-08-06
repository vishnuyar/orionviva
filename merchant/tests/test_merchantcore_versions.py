"""merchantcore declares what it runs in `merchantcore/versions.json`.

The mechanism and its negative cases are tested once, in the product's
`test_versions.py`. This file checks that merchantcore's own manifest agrees
with its files, and that no module here writes a version id as a literal.
"""

import pathlib

from vivacore import versions

import merchantcore
from merchantcore.enrich import ENRICHMENT_VERSION
from merchantcore.induce import INDUCTION_VERSION

PACKAGE = pathlib.Path(merchantcore.__file__).resolve().parent


def test_the_manifest_and_the_files_agree():
    assert versions.audit(PACKAGE) == []


def test_the_versions_stamped_on_records_come_from_the_manifest():
    """A record naming `enrich-v4` must resolve to the text that produced it,
    and the manifest is what says which text that is."""
    assert ENRICHMENT_VERSION == versions.active(PACKAGE, "enrich")
    assert INDUCTION_VERSION == versions.active(PACKAGE, "induce_profile")
    for version in (ENRICHMENT_VERSION, INDUCTION_VERSION):
        assert versions.path_of(PACKAGE, version).is_file()


def test_no_version_id_is_declared_as_a_literal():
    declared = set(versions.manifest(PACKAGE)["released"])
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
