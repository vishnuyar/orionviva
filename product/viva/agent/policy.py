"""What should happen next, and whether anyone needs to be asked.

`assess` reads a vault's shape and returns proposed `Action`s with their
preconditions already evaluated and their cost estimated. Pure: no model calls,
no writes, no questions. The thresholds are data in `RULES`.

Every action proposed here is mechanical — a pair has enough lines and no
grammar, a grammar's recent coverage has dropped, brands are unknown. What a
movement means is the question queue's, not this module's. `AUTONOMOUS` names
the rules an agent may act on alone; `NEEDS_RATIFICATION` names the ones a
person must approve.

Design rationale: docs/the-maintenance-agent.md
"""

from __future__ import annotations

from dataclasses import dataclass, field

# What an action costs, in model calls, so a budget can be applied before
# anything runs. For induction this is calls PER ATTEMPT (merchantcore's
# MAX_ROUNDS); an estimate multiplies it by the rule's `best_of`.
CALLS = {"induce": 3, "reinduce": 3, "enrich": 1}   # enrich: per batch of ~40

# The rules, as data: the thresholds each one fires on and the sentence it
# reports itself with.
RULES = {
    "induce_missing": {
        "min_lines": 30,          # below this, a grammar memorises rather than learns
        "best_of": 3,             # independent attempts; the best HELD-OUT score wins
        "why": "this bank has enough lines to be characteristic and no grammar yet",
    },
    "reinduce_drifted": {
        "recent_drop": 0.15,      # points of RECENT coverage lost since it was measured
        "min_recent_lines": 20,   # ...over enough recent lines to mean anything
        "best_of": 3,
        "why": "the bank changed what it prints and the grammar stopped keeping up",
    },
    "enrich_unknown": {
        "min_brands": 1,
        "why": "brands with no record, and a record is bought once and kept",
    },
}

# Rules an agent may act on unattended. Anything not listed here is proposed
# and waits.
AUTONOMOUS = frozenset({"induce_missing", "reinduce_drifted", "enrich_unknown"})

# Rules that change what other people see. A human ratifies these, always.
NEEDS_RATIFICATION = frozenset({"publish_grammar", "publish_merchant"})


def best_of(rule: dict) -> int:
    """How many independent attempts a rule buys; at least 1.

    Read by both the call estimate and the executing code, so the two agree."""
    return max(1, int(rule.get("best_of", 1)))


@dataclass
class Action:
    """One thing that could be done now, with the evidence for doing it."""

    rule: str
    kind: str                       # induce | reinduce | enrich | publish | ask
    target: str                     # "Northgate/depository", "brands", …
    why: str
    evidence: dict = field(default_factory=dict)
    estimated_calls: int = 0

    @property
    def autonomous(self) -> bool:
        return self.rule in AUTONOMOUS and self.rule not in NEEDS_RATIFICATION

    def to_dict(self) -> dict:
        return {"rule": self.rule, "kind": self.kind, "target": self.target,
                "why": self.why, "evidence": dict(self.evidence),
                "estimated_calls": self.estimated_calls,
                "autonomous": self.autonomous}


def assess(pairs: dict, recent: dict, store, unknown_brands: int = 0,
           rules: dict | None = None) -> list:
    """Everything worth doing to this vault right now, most valuable first.

    Pure: no model calls, no writes, no questions. `pairs` and `recent` are
    `{(institution, kind): {descriptor: movements}}` all-time and recent; `store`
    is a `ProfileStore`. Deterministic: the same inputs always yield the same
    list, in the same order — grammars, then brands, then waits.
    """
    from merchantcore.induce import drift
    from merchantcore.profile import is_inducible

    cfg = {**RULES, **(rules or {})}
    out: list = []

    for (inst, kind), counts in pairs.items():
        if not is_inducible(kind):
            continue                       # names no party; nothing to induce
        target = f"{inst}/{kind}"
        current = store.latest_for(inst, kind)

        if current is None:
            rule = cfg["induce_missing"]
            if len(counts) >= rule["min_lines"]:
                out.append(Action(
                    rule="induce_missing", kind="induce", target=target,
                    why=rule["why"],
                    estimated_calls=CALLS["induce"] * best_of(rule),
                    evidence={"distinct_lines": len(counts),
                              "movements": sum(counts.values())}))
            else:
                # Below the threshold: reported as a `wait`, not omitted.
                out.append(Action(
                    rule="induce_missing", kind="wait", target=target,
                    why=f"only {len(counts)} distinct line(s); a grammar fitted "
                        f"to that many memorises them",
                    evidence={"distinct_lines": len(counts),
                              "needed": rule["min_lines"]}))
            continue

        rule = cfg["reinduce_drifted"]
        d = drift(current, counts, recent.get((inst, kind)))
        if (d.get("recent_lines", 0) >= rule["min_recent_lines"]
                and d.get("recent_drop", 0.0) >= rule["recent_drop"]):
            out.append(Action(
                rule="reinduce_drifted", kind="reinduce", target=target,
                why=rule["why"],
                estimated_calls=CALLS["reinduce"] * best_of(rule),
                evidence={"profile": current.id, "measured": current.measured,
                          "recent": d["recent"], "drop": d["recent_drop"]}))

    if unknown_brands >= cfg["enrich_unknown"]["min_brands"]:
        out.append(Action(
            rule="enrich_unknown", kind="enrich", target="brands",
            why=cfg["enrich_unknown"]["why"],
            estimated_calls=max(1, (unknown_brands + 39) // 40) * CALLS["enrich"],
            evidence={"unknown_brands": unknown_brands}))

    # Grammars first, brands second, waits last: a grammar changes how a brand
    # is keyed, so induction has to run before enrichment.
    order = {"induce": 0, "reinduce": 1, "enrich": 2, "publish": 3, "wait": 4}
    return sorted(out, key=lambda a: (order.get(a.kind, 9), a.target))


def within_budget(actions, remaining_calls: int) -> tuple[list, list]:
    """Split into `(fits, deferred)` by cumulative `estimated_calls`.

    Walks `actions` in the order given and admits each while the running total
    stays within `remaining_calls`. A `wait` action always fits and costs
    nothing."""
    fits, deferred, spent = [], [], 0
    for a in actions:
        if a.kind == "wait" or spent + a.estimated_calls <= remaining_calls:
            fits.append(a)
            spent += a.estimated_calls
        else:
            deferred.append(a)
    return fits, deferred
