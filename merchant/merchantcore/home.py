"""Where merchant knowledge lives: two directories, split by provenance.

Neither a grammar nor a merchant record belongs to a vault. A bank's line
grammar is the bank's, identical for every customer of that bank, and a
merchant's category is true for everybody, so both are merchantcore's rather
than the product's.

``shipped()`` — inside this package, committed, read-only in practice. The seed
every install starts with. Empty today; it fills as grammars and merchant
records are ratified for publication.

``learned()`` — outside any working tree, writable, shared across every vault on
the machine. What this installation worked out for itself. A locally-induced
grammar carries literal text a model wrote, and outside the tree it cannot be
committed by accident. Overridable via ``MERCHANTCORE_HOME``.

Lookup is layered and learned wins: learned first, shipped second.

Nothing moves from learned to shipped automatically; promotion is a person's
decision.
"""

from __future__ import annotations

import os
import pathlib

# The package's own data, committed and distributed.
_SHIPPED = pathlib.Path(__file__).resolve().parent / "data"

# Where an installation keeps what it learned. Overridable, so a test or a
# machine with an unusual layout can point elsewhere.
HOME_ENV = "MERCHANTCORE_HOME"
DEFAULT_HOME = "~/.merchantcore"


def learned() -> pathlib.Path:
    """Writable, shared across vaults, never inside the working tree."""
    return pathlib.Path(os.environ.get(HOME_ENV) or DEFAULT_HOME).expanduser()


def shipped() -> pathlib.Path:
    """The seed that travels with the package. Read, never written."""
    return _SHIPPED


def profiles_dir() -> pathlib.Path:
    return learned() / "profiles"


def shipped_profiles_dir() -> pathlib.Path:
    return shipped() / "profiles"


def catalog_file() -> pathlib.Path:
    return learned() / "catalog.json"


def shipped_catalog_file() -> pathlib.Path:
    return shipped() / "catalog.json"


def describe() -> dict:
    """Where the stores are, for a report or an agent to print.

    Returns `learned` and `shipped` as strings, `learned_exists`, and
    `shipped_profiles` (the count of shipped profile files, 0 if none)."""
    return {"learned": str(learned()), "shipped": str(shipped()),
            "learned_exists": learned().is_dir(),
            "shipped_profiles": len(list(shipped_profiles_dir().glob("*.json")))
            if shipped_profiles_dir().is_dir() else 0}
