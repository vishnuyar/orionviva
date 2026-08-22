"""What happens to this application when a new version of it exists.

A screen with a section about updates implies there is an update channel. There
is not: nothing here reaches the network to ask whether a newer version exists,
nothing here downloads one, and nothing compiled into this application can
install one. So what this read carries is that fact, in the plainest sentence
the pack holds, rather than a state machine standing in for a capability.

**The two things a person actually needs are here.** The first is that an update
replaces the application and nothing else — a vault is a folder they chose, it
is not inside the application, and installing a new version does not touch it.
The second is what to do when a version will not start: install the previous one
over it, which loses nothing, because nothing they have recorded lives inside
the application.

**How this copy got here is read rather than assumed.** A build that wrote its
revision beside the package was packaged; a build answering out of a git tree
was not; a build that can establish neither says the word for that. The
difference matters to somebody filing a report, and guessing it would put a
wrong answer in one.

Nothing here opens a vault, reaches a network or reads a clock. It is a fold
over what this process can establish about itself.
"""

from __future__ import annotations

from typing import Any

from ..persona import moment
from ..revision import UNKNOWN

# How this copy got here. `packaged` is a build that wrote its own revision
# down, which is the one thing only a packaging step does; `source` is a build
# answering out of the tree it lives in; `unknown` is a build that can
# establish neither, which is a fact rather than a missing field.
PACKAGED = "packaged"
SOURCE = "source"
UNESTABLISHED = "unknown"

# The sentence each origin gets. A table rather than a chain of conditions, so
# an origin added later has nowhere to land without a sentence.
ORIGINS: dict[str, str] = {
    PACKAGED: "update_installed_build",
    SOURCE: "update_source_build",
    UNESTABLISHED: "update_unknown_build",
}


def origin_of(revision: str, written: bool) -> str:
    """Which of the three this copy is.

    `written` is whether a revision file was found beside the package, which is
    the one thing only a packaging step produces. A revision the process could
    not establish at all is neither of the other two and says so."""
    if revision == UNKNOWN:
        return UNESTABLISHED
    return PACKAGED if written else SOURCE


def lifecycle(revision: str, written: bool) -> dict[str, Any]:
    """What this build can say about being installed, updated and recovered.

    Every sentence is the pack's. The state is `absent` rather than `ready`
    because there is no update channel to be ready about: a screen reading this
    is being told there is nothing here, not being handed a status."""
    origin = origin_of(revision, written)
    return {
        "state": "absent",
        "revision": revision,
        "origin": origin,
        "origin_sentence": moment(ORIGINS[origin]),
        # What a person is owed about updates, in the order they need it: that
        # there is no channel, that their records are not in the application,
        # and what to do when a version will not start.
        "sentence": moment("update_no_channel"),
        "notes": [
            {"id": "vault_untouched", "sentence": moment("update_vault_untouched")},
            {"id": "recovery", "sentence": moment("update_recovery")},
        ],
    }


def current() -> dict[str, Any]:
    """This process's own answer, read here because this is where it is read
    from — a caller handing in a revision could hand in somebody else's."""
    from ..revision import _written_revision, source_revision

    return lifecycle(source_revision(), bool(_written_revision()))
