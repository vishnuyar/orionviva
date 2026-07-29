"""The layer an agent uses instead of a person typing commands.

Everything else in this product is a tool with a command line. `policy.assess`
turns a vault into a list of proposed actions with their preconditions already
evaluated — no model calls, no writes, no questions — so an agent can decide
what to do without a human deciding for it.

The rules are data (`policy.RULES`), and the division of labour is fixed:
mechanical decisions are the agent's, judgements about what money MEANS go to
the person, and anything that changes what other people see waits for a human.
"""

from .policy import (AUTONOMOUS, CALLS, NEEDS_RATIFICATION, RULES, Action,
                     assess, within_budget)

__all__ = ["assess", "within_budget", "Action", "RULES", "CALLS",
           "AUTONOMOUS", "NEEDS_RATIFICATION"]
