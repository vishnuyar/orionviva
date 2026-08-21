"""The agent's own paperwork, composed from one projection.

Lists what the vault has taken in and what it has been able to do with it: the
name each document arrived under, the type a read named it, whether anything
came of that read, and whether the original is still there to open. Nothing
here is a figure — no amount, no grade, no coverage — because this read is an
account of documents rather than of money, and it is composed directly from a
projection for that reason.

The one thing it decides is how to say why a document has not been read. Three
states a person would otherwise read as one are told apart, each derived from
events the log already holds: nothing has looked at this document, something
looked and came back with nothing usable, and something looked and made
something of it. The words for them are the persona pack's, and the panel says
at most one of them, once, rather than repeating an apology on every row.

A pure function of a projection, the set of documents whose original bytes the
vault still holds, and whether this machine names a reader at all. It opens
nothing, reads no environment and knows nothing about how the payload travels.
"""

from __future__ import annotations

from typing import Any

from ..ingest.review import held_items, other_holds
from ..persona import moment
from .models import PanelState

# How far a document's reading got. A closed set, because it reaches a person
# as a claim about what was done with their file: `never_read` is a document no
# reading was ever recorded against, `read` one whose reading declared itself
# usable, and `read_yielded_nothing` one whose reading declared otherwise. Each
# is about the reading and none is about what the ledger did next.
NEVER_READ = "never_read"
READ_YIELDED_NOTHING = "read_yielded_nothing"
READ = "read"

# The panel's one sentence, by what is true of the vault. Two of them are for a
# document nothing has read, and which applies is a fact about this machine
# rather than about the document: a person who has chosen no reader is told
# reading waits on that choice, and a person whose machine names one is told
# plainly that nothing read it.
_UNREAD_MOMENT = "documents_saved_no_reader"
_UNREAD_CONFIGURED_MOMENT = "documents_saved_unread"
_YIELDED_NOTHING_MOMENT = "documents_read_yielded_nothing"


def documents(projection, raw_doc_ids: frozenset[str],
              reading_configured: bool) -> dict[str, Any]:
    """Every document this vault has captured, ready to render.

    ``raw_doc_ids`` is which originals the vault still holds, which is a fact
    about the blob store rather than about the projection, so it is handed in.
    ``reading_configured`` says whether this machine names a reader at all,
    which decides which of two true sentences a person is shown."""
    captured = projection.captured_docs()
    filenames = projection.captured_filenames()
    attempted = projection.read_attempted_docs()
    parsed = projection.read_parsed_docs()
    holds = [item.to_dict() for item in held_items(projection)]
    holds.extend(other_holds(projection))
    rows = [
        {
            "id": doc_id,
            # What the file was called where it came from. A person who has
            # just added a document recognises the name they gave it; the
            # address its own bytes decide is a receipt they cannot read.
            "filename": filenames.get(doc_id, ""),
            "doc_type": doc_type,
            "resolved": projection.is_resolved(doc_id),
            "raw_available": doc_id in raw_doc_ids,
            "reading": _reading(doc_id, attempted, parsed),
        }
        for doc_id, doc_type in sorted(captured.items())
    ]
    return {
        # A panel earns its existence from data: a vault that has captured
        # nothing has no paperwork to show, and says so as a state rather than
        # as an empty list a reader has to interpret.
        "state": (PanelState.READY if captured else PanelState.ABSENT).value,
        "reading_sentence": _reading_sentence(rows, reading_configured),
        "documents": rows,
        "holds": holds,
        "raw_document_count": len(raw_doc_ids),
    }


def _reading(doc_id: str, attempted: set[str], parsed: set[str]) -> str:
    """How far this document got, in the closed set a row carries.

    Each word is read off a declaration the vault wrote about the reading, and
    off nothing else. A document with no reading recorded against it was never
    read. A document whose reading declared itself usable was read. One with a
    reading that declared otherwise was read and yielded nothing.

    What became of the reading afterwards is not consulted. Whether a document
    reached a terminal state is a fact about the ledger, not about whether
    anything looked at it: a document can be settled with no reading behind it,
    and one can be read cleanly and have nowhere to be put. Deciding this word
    from that one would say either of those things wrong."""
    if doc_id not in attempted:
        return NEVER_READ
    return READ if doc_id in parsed else READ_YIELDED_NOTHING


def _reading_sentence(rows: list[dict], reading_configured: bool) -> str:
    """The one sentence the panel says about reading, or none.

    One per panel, never one per row: a list where every line apologises for
    itself is a list whose apologies stop being read. A document nothing has
    looked at is said before one that was looked at and yielded nothing,
    because it is the one that changes what the person should do next — which
    is the test the one-absence-per-panel rule states for whether an absence
    earns its sentence at all."""
    words = {row["reading"] for row in rows}
    if NEVER_READ in words:
        return moment(_UNREAD_CONFIGURED_MOMENT if reading_configured
                      else _UNREAD_MOMENT)
    if READ_YIELDED_NOTHING in words:
        return moment(_YIELDED_NOTHING_MOMENT)
    return ""
