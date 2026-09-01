"""Per-turn evidence graph, with node lineage over the existing ground law."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..tools.runner import _Ground


@dataclass
class EvidenceGraph:
    """Evidence established this turn and the program node that established it.

    The existing ground implementation remains the stamping authority.  This
    contract adds source lineage and serialization without teaching a second
    component how figures, entities, periods, caveats, and reads gain identity.
    """

    question: str
    ground: _Ground = field(init=False)
    by_node: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)

    def __post_init__(self):
        self.ground = _Ground(question=self.question)

    @property
    def book(self):
        return self.ground.book

    def stamp(self, node_id: str, result) -> None:
        before = {
            "figures": set(self.ground.book), "entities": set(self.ground.entities),
            "periods": set(self.ground.periods), "readings": set(self.ground.readings),
            "dates": set(self.ground.dates),
        }
        self.ground.stamp(result)
        refs = {
            "figures": tuple(fig["id"] for fig in result.figures if fig.get("id")),
            "entities": tuple(item["id"] for item in result.identifiers
                              if isinstance(item, dict) and item.get("id")),
            "periods": tuple(sorted(set(self.ground.periods) - before["periods"])),
            "readings": (result.id,) if result.id else (),
            "dates": tuple(sorted(
                ({str(result.dated)} if result.dated else set())
                | {str(fig.get("dated")) for fig in result.figures if fig.get("dated")})),
        }
        self.by_node[node_id] = refs

    def attach(self, node_id: str, source_node: str) -> None:
        self.by_node[node_id] = dict(self.by_node[source_node])

    def references(self, node_id: str, kind: str) -> tuple[str, ...]:
        plural = {"figure": "figures", "entity": "entities", "period": "periods",
                  "date": "dates", "date_of": "figures", "read": "readings",
                  "read_figures": "readings"}.get(
                      kind, kind)
        return tuple(self.by_node.get(node_id, {}).get(plural, ()))

    def to_dict(self) -> dict:
        return {
            "figures": list(self.ground.book.values()),
            "entities": list(self.ground.entities.values()),
            "periods": list(self.ground.periods.values()),
            "readings": dict(self.ground.readings),
            "dates": sorted(self.ground.dates),
            "caveats": dict(self.ground.caveats),
            "owed": {key: list(value) for key, value in self.ground.owed.items()},
            "lineage": {node: {kind: list(ids) for kind, ids in refs.items()}
                        for node, refs in self.by_node.items()},
        }

    @property
    def size_bytes(self) -> int:
        return len(json.dumps(self.to_dict(), sort_keys=True,
                              separators=(",", ":")).encode())


__all__ = ["EvidenceGraph"]
