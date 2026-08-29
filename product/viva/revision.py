"""Report the packaged or checkout source revision without network access.

Packaged builds read ``REVISION`` beside the package; checkouts ask the git
tree containing this module. Unknown revisions are returned as ``unknown``.
"""

from __future__ import annotations

import logging
import pathlib
import subprocess

log = logging.getLogger(__name__)

# The filename a packaged build places beside the package.
REVISION_FILE = "REVISION"

# The explicit value for a revision that cannot be established.
UNKNOWN = "unknown"

# The number of git revision characters carried across the boundary.
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
    # Packaged revisions accept a hash with an optional dirty-tree marker.
    base, mark, suffix = written.partition("+")
    valid_mark = (not mark and not suffix) or (mark == "+" and suffix == "changes")
    return written if base.isalnum() and len(base) >= 7 and valid_mark else ""


def _git_revision() -> str:
    """The revision of the tree this module lives in, or empty.

    The lookup is independent of the caller's working directory. Dirty trees
    append ``+changes``.
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
