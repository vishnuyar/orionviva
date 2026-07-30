"""The wake: look, decide, act within a ceiling, record, report.

    observe → assess → cool → budget → perform → record

Five of those six are pure or read-only; only `perform` spends. The loop is
written so that it can be stopped after any step and the vault is consistent,
because it will be stopped after any step — a laptop closes, a key expires, a
provider returns 503.

**Why re-running is safe.** `assess` is deterministic, so two wakes over an
unchanged vault propose the same list. That is a feature for correctness and a
hazard for cost: a proposal that fails will be re-proposed forever unless the
failure is remembered. `cool()` is where it is remembered, over the agent's own
events, using the stake-snapshot rule the question queue already uses for a
decline — quiet while nothing has changed, awake the moment it has.

**What this loop may not do.** It never answers a question about what money
means. Those go to a person, ranked by consequence, through the queue that
already exists. The division is not squeamishness: only the person knows whether
five hundred to a friend was rent or a loan, so an agent answering it would be
confidently wrong rather than usefully autonomous.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date

from .act import Outcome, perform
from .observe import model_configured, observe
from .policy import RULES, assess, best_of, within_budget

log = logging.getLogger(__name__)

# Model calls one wake may spend.
#
# THE NUMBER IS SIZED TO FINISH THE JOB, and that is a correction rather than a
# preference. A ceiling exists to stop a runaway, and the runaway this agent can
# actually have is REPETITION — the same refused action bought again on every
# wake — which `cool()` stops directly and a ceiling only ever slowed down. What
# a low ceiling stops instead is the ordinary work of an ordinary vault, half
# way through, waiting for somebody to run the command again. That is not
# safety; it is the chore this layer exists to remove. An agent whose default
# settings require a person to say "continue" is a script with better prose.
#
# Sized for the shape of a real vault: six (institution x kind) pairs at
# CALLS["induce"] x best_of, plus enrichment for a few hundred brands. Bigger
# than the author's own vault needs (~33), so a first run completes, and small
# enough that a misconfigured rule set cannot quietly spend a hundred.
#
# What it does NOT protect against is a vault with forty institutions. That is
# the case the ceiling is for, and when it binds the deferred work is picked up
# by the next wake at no extra cost — a deferral is not a failure and is never
# cooled.
DEFAULT_BUDGET_CALLS = 60


def budget_calls() -> int:
    raw = os.environ.get("VIVA_AGENT_BUDGET_CALLS", "")
    try:
        return max(0, int(raw)) if raw else DEFAULT_BUDGET_CALLS
    except ValueError:
        return DEFAULT_BUDGET_CALLS


def machinery_for(kind: str) -> str:
    """The version of the code that would do this work.

    In the stake because a cooldown that fingerprints only the DATA holds back
    work that NEW CODE would now succeed at. A refusal says "this evidence, run
    through this machinery, produced nothing" — and a changed prompt or a changed
    pack rule makes that a different sentence, so the refusal should expire on
    its own rather than waiting for a person to remember.

    The string is already pinned and already composed by the induction itself
    (`induce-profile-v1+prof-v1+pack-v2` in its logs). Reusing it beats inventing
    a parallel notion of "has the code changed", which would immediately drift."""
    if kind in ("induce", "reinduce"):
        from merchantcore.induce import machinery_version
        return machinery_version()
    if kind == "enrich":
        from merchantcore.enrich import ENRICHMENT_VERSION
        return ENRICHMENT_VERSION
    return ""


def stake_of(action) -> dict:
    """The fingerprint a cooldown compares.

    The evidence that justified the action, plus the version of the machinery
    that would act on it. Floats are rounded so that a figure recomputed to the
    last bit does not read as new evidence. Counts and versions, never content —
    this ends up in an event, and an agent's journal is not a place for bank
    lines to accumulate."""
    stake = {k: (round(v, 3) if isinstance(v, float) else v)
             for k, v in sorted(action.evidence.items())}
    machinery = machinery_for(action.kind)
    if machinery:
        stake["machinery"] = machinery
    return stake


def cool(actions, attempts) -> tuple[list, list]:
    """Split into what is worth trying and what would repeat a known refusal.

    `attempts` is `projection.agent_attempts()` — the last attempt per (rule,
    target). An action is held back when that attempt did not succeed AND the
    stake has not moved since, because the same inputs will reach the same
    refusal at the same price. A successful attempt is never a reason to hold
    back: success changes the world, so `assess` stops proposing it on its own,
    and if it is proposing it again something genuinely is different."""
    live, cooled = [], []
    for a in actions:
        last = attempts.get((a.rule, a.target))
        if (last and last.get("outcome") != "done"
                and last.get("stake") == stake_of(a)):
            cooled.append((a, last))
        else:
            live.append(a)
    return live, cooled


@dataclass
class Run:
    """One wake, in full. Everything a report or an interface needs."""

    observation: dict = field(default_factory=dict)
    considered: list = field(default_factory=list)   # every Action assess proposed
    cooled: list = field(default_factory=list)       # (Action, last attempt)
    deferred: list = field(default_factory=list)     # over budget
    performed: list = field(default_factory=list)    # (Action, Outcome)
    calls_spent: int = 0
    calls_budget: int = 0
    calls_lifetime: int = 0
    dry_run: bool = False
    could_not_spend: str = ""

    def to_dict(self) -> dict:
        return {
            "observation": dict(self.observation),
            "considered": [a.to_dict() for a in self.considered],
            "cooled": [{**a.to_dict(), "last": last} for a, last in self.cooled],
            "deferred": [a.to_dict() for a in self.deferred],
            "performed": [{**a.to_dict(), "outcome": o.outcome, "calls": o.calls,
                           "produced": o.produced, "replaced": o.replaced,
                           "detail": o.detail, "result": o.result}
                          for a, o in self.performed],
            "calls_spent": self.calls_spent,
            "calls_budget": self.calls_budget,
            "calls_lifetime": self.calls_lifetime,
            "dry_run": self.dry_run,
            "could_not_spend": self.could_not_spend,
        }


def _plan(obs, rules: dict | None, ceiling_left: int):
    """One pass of the decision half. Pure with respect to the vault."""
    actions = assess(obs.pairs, obs.recent, obs.store,
                     unknown_brands=obs.unknown_brands, rules=rules)
    live, cooled = cool(actions, obs.proj.agent_attempts())
    # `wait` and `ask` are proposals about the future, not work — reported so
    # that "nothing to do" is distinguishable from "broken", and never budgeted.
    doable = [a for a in live if a.kind not in ("wait", "ask")]
    fits, deferred = within_budget(doable, ceiling_left)
    return actions, cooled, fits, deferred


def wake(vault, remaining_calls: int | None = None, dry_run: bool = False,
         best_of_override: int | None = None, rules: dict | None = None,
         recent_days: int = 120) -> Run:
    """One pass. Returns what it saw and did; writes only agent events.

    **The plan is remade after every action, not computed once.** A grammar
    written halfway through changes what a brand IS, so an enrichment estimate
    made before it is an estimate of different work — and a ceiling checked once,
    against numbers that no longer describe the job, is not a ceiling. Re-planning
    costs one projection walk per action and buys a budget that means what it
    says. Termination is not left to the arithmetic: each (rule, target) is
    attempted at most once per wake, whatever the rules say."""
    from ..ledger.events import agent_acted

    cfg = {**RULES, **(rules or {})}
    ceiling = budget_calls() if remaining_calls is None else remaining_calls
    obs = observe(vault, recent_days=recent_days)

    considered, cooled, fits, deferred = _plan(obs, rules, ceiling)
    run = Run(observation=obs.summary(), considered=considered, cooled=cooled,
              deferred=deferred, calls_budget=ceiling, dry_run=dry_run,
              calls_lifetime=obs.proj.agent_calls_spent())

    if dry_run:
        # "planned" is a report word, not an event word — a dry run writes
        # nothing, so it never has to be one of the three outcomes the log
        # understands, and calling it "done" would read as a lie in the one
        # place this product cannot afford one.
        run.performed = [(a, Outcome("planned",
                                     detail="not run — --dry-run stops at the "
                                            "line where money starts"))
                         for a in fits]
        return run
    if fits and not model_configured():
        run.could_not_spend = (
            "no model configured — set VIVA_MODEL_ADAPTER and VIVA_MODEL "
            "(and the key), or in ./.env")
        run.deferred = fits + deferred
        return run

    attempted: set = set()
    while True:
        _, _, fits, deferred = _plan(obs, rules, ceiling - run.calls_spent)
        todo = [a for a in fits if (a.rule, a.target) not in attempted]
        if not todo:
            run.deferred = [a for a in deferred
                            if (a.rule, a.target) not in attempted]
            break

        action = todo[0]
        attempted.add((action.rule, action.target))
        tries = (best_of_override if best_of_override is not None
                 else best_of(cfg.get(action.rule, {})))
        outcome = perform(vault, action, obs, best_of=tries)
        run.calls_spent += outcome.calls
        run.performed.append((action, outcome))
        vault.ledger.append(agent_acted(
            rule=action.rule, kind=action.kind, target=action.target,
            outcome=outcome.outcome, occurred_at=date.today().isoformat(),
            calls=outcome.calls, stake=stake_of(action),
            produced=outcome.produced, replaced=outcome.replaced,
            detail=outcome.detail))
        log.info("agent: %s %s -> %s (%d of ~%d call(s))",
                 action.kind, action.target, outcome.outcome, outcome.calls,
                 action.estimated_calls)
        obs = observe(vault, recent_days=recent_days)

    return run
