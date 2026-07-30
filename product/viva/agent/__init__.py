"""The maintenance agent: what Viva does to its own knowledge unprompted.

Four modules, in the order one wake uses them:

    observe   what is true right now — the vault, the grammars, the catalog
    policy    what is worth doing about it (pure; no side effects)
    act       doing one of those things, and counting what it cost
    run       the loop, the ceiling, the cooldown, and the record

Every attempt, including a refusal, is recorded as an `AgentActed` event; that
record is what the cooldown reads and the only trace of what an unattended run
spent.

Design rationale: docs/the-maintenance-agent.md
"""

from .policy import (AUTONOMOUS, CALLS, NEEDS_RATIFICATION, RULES, Action,
                     assess, within_budget)
from .act import Meter, Outcome, perform
from .observe import Observation, observe
from .run import Run, cool, machinery_for, stake_of, wake

__all__ = ["assess", "within_budget", "Action", "RULES", "CALLS",
           "AUTONOMOUS", "NEEDS_RATIFICATION",
           "observe", "Observation", "perform", "Outcome", "Meter",
           "wake", "Run", "cool", "stake_of", "machinery_for"]
