"""Injected vault-backed Trust actions: the maintenance run, and a file to send.

This module knows neither the vault implementation nor the desktop transport. A
sidecar entry point injects one already-open vault and gets back the handlers.

**Unattended work is asked for, and its dry run is the default.** The agent
spends money, so a request that does not say to spend plans and stops at the
line where money starts. Saying to spend is a person's own word, the same shape
as saying yes to a model at all, and the reply reports what was actually spent
rather than what was budgeted.

**Nothing about a person's money leaves in the diagnostic.** The file is built
from a list of what may be said rather than by taking a vault and removing what
must not travel — a scrubber is a list of what to take out, and that list is
wrong the first time somebody adds a field. What this handler contributes is
four counts it takes itself; nothing it hands over came off a document.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError
from .jobs import JobCancelled, JobRegistry

UNCONFIGURED = "no_model_named"
UNWRITABLE = "file_unwritable"
CANCELLED = "job_cancelled"

# The steps a wake declares. Observing and assessing happen before anything is
# spent, and the spending is its own step for the same reason the reading half
# of a capture is: it is the part a person is paying for.
PLANNED = "planned"
SPENT = "spent"
MAINTENANCE_STEPS = (PLANNED, SPENT)


class TrustActions:
    """The allowlisted Trust handlers for one already-open vault."""

    def __init__(self, vault: Any, jobs: JobRegistry | None = None) -> None:
        self._vault = vault
        self._jobs = jobs if jobs is not None else JobRegistry()

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Wake the agent once, planning by default and spending only if asked.

        The reply carries the whole run — what was seen, what was held back,
        what was deferred over budget and what was done — because a report of
        unattended work that summarised itself would be the one place in this
        product where somebody has to take a summary on trust."""
        from viva.agent.run import wake
        from viva.persona import moment

        spend, budget = _run_request(payload)
        job = self._jobs.open("viva.maintenance.run", MAINTENANCE_STEPS)
        try:
            with job:
                job.checkpoint()
                run = wake(self._vault, remaining_calls=budget,
                           dry_run=not spend)
                job.reached(PLANNED)
                job.checkpoint()
                if spend:
                    job.reached(SPENT)
                said = ("maintenance_planned" if not spend
                        else "maintenance_unconfigured" if run.could_not_spend
                        else "maintenance_ran")
                return ActionOutcome(
                    "completed" if not run.could_not_spend else "refused",
                    moment(said),
                    reason=UNCONFIGURED if run.could_not_spend else None,
                    state={"job_id": job.job_id, **run.to_dict()}).as_dict()
        except JobCancelled:
            return ActionOutcome("refused", moment("jobs_stopped"),
                                 reason=CANCELLED,
                                 state={"job_id": job.job_id}).as_dict()

    def diagnose(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write a file somebody can send, holding nothing about their money.

        The counts are taken here because this is where a vault is; what they
        are counts *of* is decided where the file is built, and nothing but
        counts crosses between the two."""
        from viva.persona import moment
        from viva.surface.diagnostics import written

        path = _diagnose_request(payload)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(written(self._counts()), encoding="utf-8")
        except OSError:
            return ActionOutcome("refused", moment("diagnostic_unwritable"),
                                 reason=UNWRITABLE).as_dict()
        return ActionOutcome("completed", moment("diagnostic_written"),
                             state={"file": str(path)}).as_dict()

    def _counts(self) -> dict[str, int]:
        """The four numbers the file carries, and no fifth.

        Counted here rather than passed in, so what a caller sends cannot
        decide what a diagnostic says about their vault."""
        projection = self._vault.ledger.projection()
        events = list(self._vault.events())
        return {
            "documents": len(projection.captured_docs()),
            "events": len(events),
            "model_calls": sum(1 for event in events
                               if event.event_type == "ReadRecorded"),
            "open_questions": len(projection.open_holds()),
        }


def _run_request(payload: Mapping[str, Any]) -> tuple[bool, int | None]:
    """Whether to spend, and how much. Planning is what a silent request gets.

    `spend` is a person's own word rather than a default, because the agent
    reaches a model and a request that did not say so has not asked for
    that."""
    allowed = {"spend", "budget"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            "viva.maintenance.run does not accept fields: "
            + ", ".join(sorted(unexpected)))
    spend = payload.get("spend", False)
    if not isinstance(spend, bool):
        raise BridgeRequestError("spend must be true or false")
    budget = payload.get("budget")
    if budget is not None and (isinstance(budget, bool)
                               or not isinstance(budget, int) or budget < 0):
        raise BridgeRequestError("budget must be a whole number of model calls")
    return spend, budget


def _diagnose_request(payload: Mapping[str, Any]) -> Path:
    allowed = {"file"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            "viva.maintenance.diagnose does not accept fields: "
            + ", ".join(sorted(unexpected)))
    path = payload.get("file")
    if not isinstance(path, str) or not path.strip():
        raise BridgeRequestError("file must be a non-empty string")
    return Path(path)
