"""A file a person can hand to somebody, holding nothing about their money.

Somebody with a problem needs to be able to say what build they are running and
what it can reach. Everything else they might reasonably want to send — an
account name, a figure, a document, a merchant, a date one of their statements
carries — is the whole of what this product exists to keep on their machine.

So this file is built out of what is safe to say and nothing else, and it is
built by naming those things rather than by taking a vault and removing what
must not travel. A scrubber is a list of what to take out, and a list of what to
take out is wrong the first time somebody adds a field.

**Counts, never contents.** How many documents, how many events, how many model
calls, how many questions are open. A count of a person's documents says they
have some paperwork; the name of one says where they bank.

**No date from a vault.** Not the day a statement covers, not the day a document
arrived, not the earliest or the latest of anything a person's records carry.
When somebody used this product is a fact about them.

A pure function of counts already taken elsewhere. It opens nothing and reads no
vault: what it is handed is what travels, which is what makes the fence
checkable by reading one call site.
"""

from __future__ import annotations

import json
import platform
import sys
from typing import Any

# Every field this file may carry, named here. A field not on this list is not
# written, so adding one is an edit to this line and shows up in a diff as
# exactly the decision it is.
FIELDS = (
    "diagnostic_schema", "count_definitions",
    "build", "python", "platform",
    "model_named", "model_adapter", "locale", "currency",
    "documents", "events", "model_calls", "open_questions",
    "open_document_holds", "open_conversation_questions",
)


def diagnostics(counts: dict[str, int] | None = None) -> dict[str, Any]:
    """What this build is, what it can reach, and how much has gone through it.

    ``counts`` is whatever a caller already knows — documents, events, model
    calls, open questions. Every value is coerced to a whole number, so a
    caller that handed a string, a name or an amount by mistake writes a zero
    rather than writing it out."""
    from ..configuration import current
    from ..revision import source_revision

    settings = current()
    counted = counts or {}
    return {
        "diagnostic_schema": 2,
        "count_definitions": {
            "open_document_holds": "documents captured but not posted",
            "open_conversation_questions": "live questions awaiting a person or document",
            "open_questions": "legacy alias of open_conversation_questions",
        },
        "build": source_revision(),
        "python": sys.version.split()[0],
        # The platform family and nothing finer. A machine's hostname is a name.
        "platform": platform.system(),
        # Whether a model is named, and how it would be reached. Never the
        # model's own name: a pinned id names a provider and a spend.
        "model_named": settings.can_send,
        "model_adapter": settings.adapter,
        "locale": settings.locale,
        "currency": settings.currency,
        "documents": _count(counted, "documents"),
        "events": _count(counted, "events"),
        "model_calls": _count(counted, "model_calls"),
        "open_questions": _count(counted, "open_conversation_questions"),
        "open_document_holds": _count(counted, "open_document_holds"),
        "open_conversation_questions": _count(
            counted, "open_conversation_questions"),
    }


def _count(counted: dict[str, Any], name: str) -> int:
    value = counted.get(name, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def written(counts: dict[str, int] | None = None) -> str:
    """The file's own bytes. Stable and readable, so a person can read it
    before they send it — which is the only check that matters."""
    return json.dumps(diagnostics(counts), indent=2, sort_keys=True) + "\n"
