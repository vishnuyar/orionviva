"""What should happen next, and whether anyone needs to be asked.

Everything built so far is a tool a person types. An agent cannot type. This is
the layer between: it looks at a vault and returns **proposed actions with their
preconditions already evaluated** — no model calls, no side effects, no
questions. The agent reads the list, checks it against a budget, and acts.

Three ideas hold it together.

**The rules are data.** `RULES` below is a list of conditions and consequences,
not logic buried in a CLI. Changing when the agent induces a grammar is editing
a value, not editing a function — the same choice this project already made for
the document-type registry and the expectations registry.

**Autonomy over procedure, deference over meaning.** An action here is always
mechanical: a pair has enough lines and no grammar; a grammar's recent coverage
has dropped; brands are unknown. Nothing in this module decides what a movement
*means* — that is the question queue's job, and it goes to a person because only
a person knows whether five hundred to a friend was rent or a loan. An agent that
answered those itself would be less useful, not more autonomous.

**Blast radius decides who ratifies.** An agent may induce a grammar and use it
on this vault without asking, because a wrong grammar here is wrong for one
person and the drift check will catch it. Publishing one to the commons needs a
human, because a wrong grammar there is wrong for everybody and no automated
check can catch the failure that matters — a grammar can cover 90% of lines
while putting cities in `{brand}`, and only reading it finds that.

That last point is worth stating plainly rather than burying: **every quality
gate in this system assumes a human eventually reads the templates.** Coverage,
holdout, drift and narrow-template checks all measure whether a template
*matched*, never whether it *slotted correctly*. There is no automated substitute
today, so the boundary is drawn where an unread grammar can do the least harm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- what an action costs, so a budget can be applied before anything runs ---
# Deliberately an estimate in CALLS, not currency: the price of a call is the
# adapter's business and changes without warning, while the count is a property
# of the plan and is what a runaway loop inflates.
CALLS = {"induce": 3, "reinduce": 3, "enrich": 1}   # enrich: per batch of ~40

# --- the rules, as data ------------------------------------------------------
#
# Each is (name, why it fires, what it proposes). The thresholds live here so
# that tuning the agent is editing a value rather than editing behaviour.
RULES = {
    "induce_missing": {
        "min_lines": 30,          # below this, a grammar memorises rather than learns
        "why": "this bank has enough lines to be characteristic and no grammar yet",
    },
    "reinduce_drifted": {
        "recent_drop": 0.15,      # points of RECENT coverage lost since it was measured
        "min_recent_lines": 20,   # ...over enough recent lines to mean anything
        "why": "the bank changed what it prints and the grammar stopped keeping up",
    },
    "enrich_unknown": {
        "min_brands": 1,
        "why": "brands with no record, and a record is bought once and kept",
    },
}

# Actions an agent may take unattended, because a mistake stays inside this
# vault and is recoverable. Anything not listed here is proposed and waits.
AUTONOMOUS = frozenset({"induce_missing", "reinduce_drifted", "enrich_unknown"})

# Actions that change what other people see. A human ratifies these, always.
NEEDS_RATIFICATION = frozenset({"publish_grammar", "publish_merchant"})


@dataclass
class Action:
    """One thing that could be done now, with the evidence for doing it."""

    rule: str
    kind: str                       # induce | reinduce | enrich | publish | ask
    target: str                     # "Chase/depository", "brands", …
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
    is a `ProfileStore`. Deterministic, so two runs a minute apart propose the
    same things and an agent can safely re-assess on every wake.
    """
    from merchantcore.induce import drift
    from merchantcore.profile import is_inducible

    cfg = {**RULES, **(rules or {})}
    out: list = []

    for (inst, kind), counts in pairs.items():
        if not is_inducible(kind):
            continue                       # names no party; instrumentcore's job
        target = f"{inst}/{kind}"
        current = store.latest_for(inst, kind)

        if current is None:
            rule = cfg["induce_missing"]
            if len(counts) >= rule["min_lines"]:
                out.append(Action(
                    rule="induce_missing", kind="induce", target=target,
                    why=rule["why"], estimated_calls=CALLS["induce"],
                    evidence={"distinct_lines": len(counts),
                              "movements": sum(counts.values())}))
            else:
                # Named, not silently skipped: an agent that reports nothing to
                # do is indistinguishable from one that is broken.
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
                why=rule["why"], estimated_calls=CALLS["reinduce"],
                evidence={"profile": current.id, "measured": current.measured,
                          "recent": d["recent"], "drop": d["recent_drop"]}))

    if unknown_brands >= cfg["enrich_unknown"]["min_brands"]:
        out.append(Action(
            rule="enrich_unknown", kind="enrich", target="brands",
            why=cfg["enrich_unknown"]["why"],
            estimated_calls=max(1, (unknown_brands + 39) // 40) * CALLS["enrich"],
            evidence={"unknown_brands": unknown_brands}))

    # A grammar first, brands second, waiting last. Not arbitrary: a grammar
    # changes what a brand IS, so enriching before inducing buys records keyed on
    # a string the next hour will rewrite.
    order = {"induce": 0, "reinduce": 1, "enrich": 2, "publish": 3, "wait": 4}
    return sorted(out, key=lambda a: (order.get(a.kind, 9), a.target))


def within_budget(actions, remaining_calls: int) -> tuple[list, list]:
    """Split into what fits and what does not, in the order given.

    An agent that triggers model calls needs a ceiling, or one bad loop is
    expensive in a way nobody notices until the invoice. The ceiling is counted
    in calls rather than currency because a call count is a property of the plan
    while a price is the adapter's business and changes without warning."""
    fits, deferred, spent = [], [], 0
    for a in actions:
        if a.kind == "wait" or spent + a.estimated_calls <= remaining_calls:
            fits.append(a)
            spent += a.estimated_calls
        else:
            deferred.append(a)
    return fits, deferred
