"""The one shape every tool returns: a figure with its grade and its sources,
or a refusal that says why — never an exception across the boundary and never
a bare number.

Composition inherits the weakest grade among its parts, so a total built from
one unverified balance is itself unverified, and a conflicted part makes the
whole conflicted. A refusal is a first-class result: ``ok`` is False, ``refusal``
carries a machine tag, and ``text`` says honestly what is and is not held.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ledger import CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED

# Weakest-last, so composition takes the maximum index present. `conflicted`
# sits below `unverified`: a figure that disagrees with its own evidence is
# worse than one nothing has checked.
_STRENGTH = (VERIFIED, CORROBORATED, UNVERIFIED, CONFLICTED)


def weakest(grades) -> str:
    """The weakest grade present, by the ladder's order; "" when none given."""
    present = [g for g in grades if g in _STRENGTH]
    if not present:
        return ""
    return _STRENGTH[max(_STRENGTH.index(g) for g in present)]


@dataclass
class ToolResult:
    """What a tool call returns, whichever tool ran and however it went."""

    tool: str                                   # the verb that produced this
    ok: bool                                    # False is a refusal, not an error
    data: object = None                         # JSON-safe payload
    grade: str = ""                             # weakest grade the data rests on
    dated: str = ""                             # the value-time the data is good as of
    record_ids: list = field(default_factory=list)   # the documents behind it
    provenance: list = field(default_factory=list)   # provenance dicts, when few
    coverage: str = ""                          # what is included and what is not
    caveats: list = field(default_factory=list)
    refusal: str = ""                           # machine tag when ok is False
    text: str = ""                              # one honest sentence

    def to_dict(self) -> dict:
        return {"tool": self.tool, "ok": self.ok, "data": self.data,
                "grade": self.grade, "dated": self.dated,
                "record_ids": list(self.record_ids),
                "provenance": list(self.provenance),
                "coverage": self.coverage, "caveats": list(self.caveats),
                "refusal": self.refusal, "text": self.text}


def refusal(tool: str, reason: str, text: str, **extra) -> ToolResult:
    """A refusal envelope: the machine tag plus the honest sentence, and any
    context (known values, accepted shapes) the caller can act on."""
    result = ToolResult(tool=tool, ok=False, refusal=reason, text=text)
    if extra:
        result.data = dict(extra)
    return result
