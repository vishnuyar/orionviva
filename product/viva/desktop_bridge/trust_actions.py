"""Serve vault-backed maintenance and privacy-filtered diagnostic actions.

Maintenance plans without spending by default. Paid maintenance runs as a
durable background job. Diagnostics contain only allowlisted operational
counts computed by this module and no document-derived values.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from threading import Thread
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError
from .jobs import JobCancelled, JobRegistry

UNCONFIGURED = "no_model_named"
UNWRITABLE = "file_unwritable"
CANCELLED = "job_cancelled"

# The named planning and paid-execution steps of one maintenance job.
PLANNED = "planned"
SPENT = "spent"
MAINTENANCE_STEPS = (PLANNED, SPENT)


class TrustActions:
    """The allowlisted Trust handlers for one already-open vault."""

    def __init__(self, vault: Any, jobs: JobRegistry | None = None) -> None:
        self._vault = vault
        self._jobs = jobs if jobs is not None else JobRegistry()

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Plan once by default, or enqueue one paid run when requested.

        A dry run returns its report. A paid run returns its durable job id;
        progress and completion remain available through the job registry.
        """
        from viva.agent.run import wake
        from viva.persona import moment

        spend, budget = _run_request(payload)
        if spend:
            active = self._jobs.active("viva.maintenance.run")
            if active is not None:
                return ActionOutcome(
                    "completed", moment("maintenance_started"),
                    state={"job_id": active.job_id, "queued": True}).as_dict()
        job = self._jobs.open("viva.maintenance.run", MAINTENANCE_STEPS)
        if spend:
            Thread(target=self._spend_in_background,
                   args=(job, budget), daemon=True).start()
            return ActionOutcome(
                "completed", moment("maintenance_started"),
                state={"job_id": job.job_id, "queued": True}).as_dict()
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

    def _spend_in_background(self, job, budget: int | None) -> None:
        """Run paid maintenance on isolated caches without pumping transport."""
        from viva.agent.run import wake

        try:
            with job:
                # Background cancellation is read from the registry.
                job.checkpoint(pump=False)
                worker_vault = (self._vault.fork_for_background()
                                if hasattr(self._vault, "fork_for_background")
                                else self._vault)
                # Planning completes before the cancellable paid step begins.
                wake(worker_vault, remaining_calls=budget, dry_run=True)
                job.reached(PLANNED, "Maintenance plan completed.")
                job.checkpoint(pump=False)
                run = wake(worker_vault, remaining_calls=budget, dry_run=False)
                if run.could_not_spend:
                    job.fail("Maintenance could not spend because no model is configured.")
                    return
                job.reached(
                    SPENT,
                    f"Maintenance completed using {run.calls_spent} model call(s).")
        except JobCancelled:
            return

    def diagnose(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write a diagnostic containing allowlisted operational counts."""
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
        """Return the diagnostic's five allowlisted operational counts."""
        projection = self._vault.ledger.projection()
        events = list(self._vault.events())
        from viva.questions import open_questions
        question_count = open_questions(projection, limit=1)["total"]
        return {
            "documents": len(projection.captured_docs()),
            "events": len(events),
            "model_calls": sum(1 for event in events
                               if event.event_type == "ReadRecorded"),
            "open_document_holds": len(projection.open_holds()),
            "open_conversation_questions": question_count,
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
