"""What the agent did unattended — the journal, and the reads over it."""

from __future__ import annotations

from .core import ProjectionCore


def agent_log(core: ProjectionCore) -> list[dict]:
    """Everything the agent did unattended, oldest first: rule, target,
    outcome, model calls actually spent, and the artifact produced. Every
    attempt is kept; none is collapsed."""
    return list(core._agent_log)


def agent_attempts(core: ProjectionCore) -> dict[tuple[str, str], dict]:
    """The most recent attempt per (rule, target), whatever its outcome.

    Data, not policy: this remembers and the runner decides, as
    `declined_questions` remembers and the queue decides."""
    out: dict[tuple[str, str], dict] = {}
    for a in core._agent_log:
        out[(a.get("rule", ""), a.get("target", ""))] = a
    return out


def agent_calls_spent(core: ProjectionCore, since: str = "") -> int:
    """Model calls the agent has spent on its own initiative — actuals, not
    estimates. `since` is an ISO date; omit it for the lifetime figure."""
    return sum(int(a.get("calls", 0)) for a in core._agent_log
               if not since or str(a.get("occurred_at", ""))[:10] >= since)
