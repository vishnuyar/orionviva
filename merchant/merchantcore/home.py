"""Locate shipped and installation-learned merchant knowledge.

Shipped data is package-owned and read-only. Learned data is shared across
vaults under ``MERCHANTCORE_HOME`` and overrides shipped records after reviewed
alias resolution. No learned record is promoted automatically.
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
