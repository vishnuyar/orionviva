"""The wake: look, decide, act within a ceiling, record, report.

    observe → assess → cool → budget → perform → record

Only `perform` spends; the rest is pure or read-only, and the loop leaves the
vault consistent if it stops after any step. `cool()` holds back an action whose
last attempt failed against an unchanged stake, so a repeated wake over an
unchanged vault buys nothing twice. Nothing here answers a question about what a
movement means; those go to the question queue.

Design rationale: docs/the-maintenance-agent.md
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

# Model calls one wake may spend, unless `--budget` or VIVA_AGENT_BUDGET_CALLS
# overrides it. Sized to cover six (institution x kind) pairs at
# CALLS["induce"] x best_of plus enrichment for a few hundred brands. Work that
# does not fit is deferred to the next wake, not refused.
DEFAULT_BUDGET_CALLS = 60


def budget_calls() -> int:
    raw = os.environ.get("VIVA_AGENT_BUDGET_CALLS", "")
    try:
        return max(0, int(raw)) if raw else DEFAULT_BUDGET_CALLS
    except ValueError:
        return DEFAULT_BUDGET_CALLS


def machinery_for(kind: str) -> str:
    """The version string of the code that would do this kind of work.

    `merchantcore.induce.machinery_version()` for an induction, `ENRICHMENT_
    VERSION` for an enrichment, "" for a kind with no versioned machinery."""
    if kind in ("induce", "reinduce"):
        from merchantcore.induce import machinery_version
        return machinery_version()
    if kind == "enrich":
        from merchantcore.enrich import ENRICHMENT_VERSION
        return ENRICHMENT_VERSION
    return ""


def stake_of(action) -> dict:
    """The fingerprint a cooldown compares.

    `action.evidence` sorted by key, floats rounded to three places, plus a
    `machinery` entry when `machinery_for` names one. Counts and versions only:
    it carries no descriptor, amount or account."""
    stake = {k: (round(v, 3) if isinstance(v, float) else v)
             for k, v in sorted(action.evidence.items())}
    machinery = machinery_for(action.kind)
    if machinery:
        stake["machinery"] = machinery
    return stake


def cool(actions, attempts) -> tuple[list, list]:
    """Split `actions` into `(live, cooled)`.

    `attempts` is `projection.agent_attempts()` — the last attempt per (rule,
    target). An action is cooled when that attempt did not succeed and its stake
    equals the action's current stake; `cooled` entries are `(action, attempt)`.
    A "done" attempt never cools anything."""
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
    """One wake, in full — what was seen, held back, deferred and done."""

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
    """One pass of the decision half — `(considered, cooled, fits, deferred)`.

    Pure with respect to the vault: it reads, and writes nothing."""
    actions = assess(obs.pairs, obs.recent, obs.store,
                     unknown_brands=obs.unknown_brands, rules=rules)
    live, cooled = cool(actions, obs.proj.agent_attempts())
    # `wait` and `ask` are reported but never performed and never budgeted.
    doable = [a for a in live if a.kind not in ("wait", "ask")]
    fits, deferred = within_budget(doable, ceiling_left)
    return actions, cooled, fits, deferred


def wake(vault, remaining_calls: int | None = None, dry_run: bool = False,
         best_of_override: int | None = None, rules: dict | None = None,
         recent_days: int = 120) -> Run:
    """One wake. Returns a `Run`; the only events it writes are `AgentActed`.

    The observation and the plan are remade after every action, so the budget is
    applied to current estimates. Each (rule, target) is attempted at most once
    per wake, which is what terminates the loop. `dry_run` stops before the first
    model call and writes nothing; `remaining_calls` overrides `budget_calls()`;
    `best_of_override` overrides every rule's `best_of`."""
    from ..ledger.events import agent_acted

    cfg = {**RULES, **(rules or {})}
    ceiling = budget_calls() if remaining_calls is None else remaining_calls
    obs = observe(vault, recent_days=recent_days)

    considered, cooled, fits, deferred = _plan(obs, rules, ceiling)
    run = Run(observation=obs.summary(), considered=considered, cooled=cooled,
              deferred=deferred, calls_budget=ceiling, dry_run=dry_run,
              calls_lifetime=obs.proj.agent_calls_spent())

    if dry_run:
        # "planned" is a report word: it is not one of the outcomes the event
        # log accepts, and a dry run writes no event.
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
