"""Local question claims and answer scope from existing typed evidence."""
from dataclasses import dataclass
from typing import Iterable, Literal

from .ledger.merchants import is_shareable

Evidence = Literal["business", "peer", "instrument", "abstain"]


@dataclass(frozen=True)
class QuestionEvidence:
    kind: Evidence
    generalizes: bool

    def scope_note(self, count: int) -> str:
        return "merchant_movement_single_note" if count == 1 else "merchant_movement_note"

    @property
    def nature_reason(self) -> str:
        return "nature_peer_why" if self.kind == "peer" else "nature_single_why"


def decide(descriptor: str, kind: str) -> QuestionEvidence:
    """Permission constrains scope but never supplies identity evidence."""
    evidence = kind if kind in ("business", "peer", "instrument") else "abstain"
    return QuestionEvidence(evidence, is_shareable(descriptor)
                            and evidence not in ("peer", "instrument"))


def group_decision(members: Iterable[QuestionEvidence]) -> QuestionEvidence:
    """A group asserts only what every member supports and permits."""
    members = tuple(members)
    kinds = {member.kind for member in members}
    kind = next(iter(kinds)) if len(kinds) == 1 else "abstain"
    return QuestionEvidence(kind, bool(members) and all(m.generalizes for m in members))
