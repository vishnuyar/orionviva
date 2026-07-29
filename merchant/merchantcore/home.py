"""Where merchant knowledge lives — and why it is two places, not one.

Neither a grammar nor a merchant record belongs to a vault. A bank's line
grammar is the bank's, identical for every customer. "A warehouse club is a
warehouse club" is true for everybody. Both were sitting under the product's
home directory, which quietly said they were the product's; they are
merchantcore's, and they outlive any particular ledger.

**Two directories, split by where the knowledge came from.**

``shipped()`` — inside this package, committed, read-only in practice. The seed
every install starts with, so a new person's first month costs nothing for
knowledge somebody already paid for. Empty today; it fills as grammars and
merchant records are ratified for publication.

``learned()`` — outside the repository entirely, writable, shared across every
vault on the machine. What this installation worked out for itself.

The split is not tidiness. Put both in one directory and the moment it ships,
that path holds two different kinds of thing with no way to tell them apart —
and the one you must never commit is a locally-induced grammar, whose literal
text comes from a model and could carry a person's name that slipped past the
narrow-template check. Keeping learned data **outside the working tree** means it
cannot be committed by accident rather than merely should not be. That is a
stronger guarantee than a `.gitignore`, which is one `git add -f` away from
failing, and it survives someone copying the repo somewhere new.

Two further reasons the same directory would have hurt:

- An installed package is often read-only — a wheel, a container image,
  site-packages under a system Python. Writing learned data into it works only
  while the install is editable, which is today and not tomorrow.
- ``pip install -U`` replaces a package directory. Anything learned and stored
  inside it disappears on upgrade, silently, and the next run pays for it again.

**Lookup is layered, and local wins.** Learned first, shipped second — the same
precedence the catalog already applies to commons imports, now applied to
storage. What this installation worked out beats what it was handed.

**Promotion is deliberate.** Nothing moves from learned to shipped on its own.
That is the human ratification step: a grammar going into the package is a
grammar going to everybody, and no automated check catches the failure that
matters there.
"""

from __future__ import annotations

import os
import pathlib

# The package's own data, committed and distributed.
_SHIPPED = pathlib.Path(__file__).resolve().parent / "data"

# Where an installation keeps what it learned. Overridable so a test, a second
# profile, or a machine with an unusual layout can point it elsewhere.
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
    """What a report or an agent should print about where it is reading from.

    A store that silently loads the wrong file is worse than no store at all —
    this project has already been bitten by a catalog that looked empty because
    it was a different file from the one that had been filled."""
    return {"learned": str(learned()), "shipped": str(shipped()),
            "learned_exists": learned().is_dir(),
            "shipped_profiles": len(list(shipped_profiles_dir().glob("*.json")))
            if shipped_profiles_dir().is_dir() else 0}
