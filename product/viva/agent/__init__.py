"""The layer an agent uses instead of a person typing commands.

Everything else in this product is a tool with a command line. `policy.assess`
turns a vault into a list of proposed actions with their preconditions already
evaluated — no model calls, no writes, no questions — so an agent can decide
what to do without a human deciding for it.

The rules are data (`policy.RULES`), and the division of labour is fixed:
mechanical decisions are the agent's, judgements about what money MEANS go to
the person, and anything that changes what other people see waits for a human.

Four modules, in the order one wake uses them:

    observe   what is true right now — the vault, the grammars, the catalog
    policy    what is worth doing about it (pure; the one with no side effects)
    act       doing one of those things, and counting what it cost
    run       the loop, the ceiling, the cooldown, and the record

The record is `AgentActed`, and it is load-bearing rather than decorative. A
refused induction leaves no other trace — the write-guard raises and writes
nothing — while `assess` is deterministic and would propose it again on every
wake. Remembering the refusal against the evidence that prompted it is what
turns two good properties into a loop that terminates.
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
