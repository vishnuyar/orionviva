"""Injected vault-backed rescan: one pass back over what is already held.

This module knows neither the vault implementation nor the desktop transport. A
sidecar entry point injects one already-open vault and gets back the handler for
the sweep.

**It reads nothing new.** The sweep stitches gaps, closes holds a counterparty
now attests, and links transfers among movements that are already posted. No
document is read, so no model runs and nothing leaves the machine whatever this
machine's environment holds — which is what makes this an action a person can
press without being asked to agree to anything first.

**It writes, and it is idempotent.** Links, heals and corroborations are events.
Running it twice over an unchanged vault produces the second reply saying
nothing changed rather than a second set of the same events.

What comes back is a reviewed read model rather than the counts the sweep
returns. Counts are not a read model: a screen handed a number of gaps has to
invent the words for what a gap is, and the words it invents are the ones nobody
reviewed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError
from .jobs import JobCancelled, JobRegistry

CANCELLED = "job_cancelled"

# The steps one pass declares. Both are things that happen: the sweep runs over
# the whole vault, and what it did is then said in words. Splitting the sweep
# itself would claim granularity this handler does not have — the engine runs it
# as one call and reports at the end.
SWEPT = "swept"
SAID = "said"
RESCAN_STEPS = (SWEPT, SAID)


class RescanActions:
    """Adapt one already-open vault into the allowlisted rescan handler."""

    def __init__(self, vault: Any, jobs: JobRegistry | None = None) -> None:
        self._vault = vault
        self._jobs = jobs if jobs is not None else JobRegistry()

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Go back over everything already here, and say what changed.

        The reply is completed in every branch that ran: a pass that changed
        nothing did happen, and telling a person otherwise would have them
        press it again expecting a different answer."""
        from viva.ingest import sweep
        from viva.surface.rescan import rescan

        _no_fields(payload)
        job = self._jobs.open("viva.documents.rescan", RESCAN_STEPS)
        try:
            with job:
                job.checkpoint()
                result = sweep(self._vault.ledger)
                job.reached(SWEPT)
                view = rescan(result)
                job.reached(SAID)
                return ActionOutcome(
                    "completed", view["sentence"],
                    state={"job_id": job.job_id, **view},
                ).as_dict()
        except JobCancelled:
            from viva.persona import moment

            return ActionOutcome("refused", moment("jobs_stopped"),
                                 reason=CANCELLED,
                                 state={"job_id": job.job_id}).as_dict()


def _no_fields(payload: Mapping[str, Any]) -> None:
    """The whole request, which carries nothing.

    A pass goes over the whole vault. A field naming part of it would be a
    caller asserting a scope the sweep does not have, and the fence is the
    shape of the request rather than a check that could be relaxed."""
    # Written as an empty tuple rather than as a call, because the field set a
    # sidecar validator accepts is read out of this module by a gate that reads
    # a literal: a set built by calling something is a fence nothing can check.
    allowed = ()
    unexpected = set(payload) - set(allowed)
    if unexpected:
        raise BridgeRequestError(
            "viva.documents.rescan does not accept fields: "
            + ", ".join(sorted(unexpected)))
