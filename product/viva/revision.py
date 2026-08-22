"""Which build of this engine is running, said where a caller can check it.

A packaged sidecar and a source checkout are two different things and a person
looking at a bug report needs to know which one answered. The revision is
therefore read, never guessed: a build writes it into a file beside the package,
a checkout is asked of git, and a process that can establish neither says so in
a word rather than reporting a plausible one.

**An unknown revision is a value, not an absence.** A field that vanishes when
the answer is not known reads, to everything downstream, exactly like a field
nobody thought to send — so this returns a word that says the fact rather than
leaving a hole for a reader to interpret.

Nothing here reaches the network, and nothing here reads the working directory:
the file is found beside this module and the git question is asked of the tree
this module lives in, so no caller's location can change the answer.
"""

from __future__ import annotations

import logging
import pathlib
import subprocess

log = logging.getLogger(__name__)

# What a build writes, and where. A packaged sidecar has no git tree to ask, so
# the packaging step is the one that knows, and it writes the answer down.
REVISION_FILE = "REVISION"

# The word for a build that cannot establish its own revision. It is not empty
# and it is not a plausible-looking hash: both would be read as an answer.
UNKNOWN = "unknown"

# How much of a revision is carried. Long enough to be unambiguous in any tree
# this product will have, short enough to be read aloud.
_LENGTH = 12


def _package_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def _written_revision() -> str:
    """The revision a build wrote beside this package, or empty."""
    path = _package_root() / REVISION_FILE
    try:
        written = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    # A file holding something that is not a revision is not a revision. Only
    # the shape is checked, because checking the value against a tree that may
    # not be here is a question a packaged build cannot answer.
    return written if written.isalnum() and len(written) >= 7 else ""


def _git_revision() -> str:
    """The revision of the tree this module lives in, or empty.

    Asked of this file's own directory rather than of the working directory, so
    a sidecar started anywhere reports the tree it was loaded from. A tree with
    uncommitted changes is reported with a mark, because a revision that names
    a commit the running code does not match is worse than no revision.
    """
    root = _package_root()
    try:
        found = subprocess.run(
            ["git", "-C", str(root), "rev-parse", f"--short={_LENGTH}", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False)
        if found.returncode != 0:
            return ""
        revision = found.stdout.strip()
        if not revision:
            return ""
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=False)
        return f"{revision}+changes" if dirty.stdout.strip() else revision
    except (OSError, subprocess.SubprocessError):
        return ""


def source_revision() -> str:
    """The revision this sidecar is running, or the word for not knowing.

    The written file wins over git, because a packaged build that also happens
    to sit in a tree is the packaged build a person is running."""
    return _written_revision() or _git_revision() or UNKNOWN
