"""The job registry, and the channel that reports what a job is doing.

Three defects the status record names are closed here, and they are one design
rather than three errands. Progress events were produced and discarded, because
nothing on either side of the bridge held a job long enough to attach them to;
there was no registry, so a job had no identity a second frame could name; and
there was no cancellation, because a person cannot stop what cannot be named.

**A job is minted by the sidecar and never by a caller.** An identity a caller
sends is a claim about work the caller has not done, and a second caller could
send the same one. Every handler that does work long enough to report on asks
this registry for a job, and the identity travels outward in the reply and in
every event.

**Granularity is declared, not counted afterwards.** A job says how many steps
it has when it opens and names each one as it reaches it, so a person is told
what is happening rather than shown a bar moving at a rate nobody chose. A step
that has no name is not a step this channel reports.

**Cancellation is honoured at checkpoints and nowhere else.** A job asks the
registry, between steps, whether a person has asked it to stop; the answer is
read from state a cancel frame wrote. Nothing is interrupted mid-write: a step
runs to its end or does not begin, so a cancelled job leaves the vault in a
state some step finished at, never in one no step ever declared.

This module knows nothing about vaults, transports or surfaces. It is handed a
sink to write events to and a pump to call between steps, and both are optional
— a registry with neither still records what happened, which is what makes it
testable without a bridge.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, Literal

# The words a progress event may carry. `started` and `completed` bracket a job
# that ran to its end; `failed` is one that raised; `cancelled` is one a person
# stopped. A running job's steps are reported as `progress`, which is the one
# word that says the job is neither finished nor over.
ProgressStatus = Literal["started", "progress", "completed", "failed", "cancelled"]


class JobState(StrEnum):
    """Where a job stands. A closed set, because it reaches a person.

    `QUEUED` is a job that has an identity and has not begun — the only state a
    cancel can reach without a checkpoint being run. `RUNNING` is one between
    its first and last step. The other three are terminal and never move.
    """

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED})


class JobCancelled(RuntimeError):
    """Raised at a checkpoint when a person has asked this job to stop.

    It carries the job's identity rather than a sentence: what a person is told
    about a cancelled job is written where sentences are written, and an
    exception message is not that place.
    """

    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id


@dataclass(frozen=True)
class JobProgressEvent:
    """A JSON-safe progress update emitted during one job.

    `completed` and `total` are steps of this job and not bytes of anything: a
    channel that reports two different units under one pair of names reports
    neither. `step` is the name of the step just reached, and it is empty only
    on the events that bracket the job.

    `attempt` is which try this is, counting from one. It is on every event
    rather than only on a retry, because a bar that restarts with no word for
    why has told a person their work was lost.
    """

    job_id: str
    status: ProgressStatus
    completed: int
    total: int
    message: str = ""
    operation: str = ""
    step: str = ""
    attempt: int = 1

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id must be a non-empty string")
        if self.completed < 0 or self.total < 0 or self.completed > self.total:
            raise ValueError("completed must be between zero and total")
        if self.status == "completed" and self.completed != self.total:
            raise ValueError("completed events must reach total")
        if self.attempt < 1:
            raise ValueError("an attempt is counted from one")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JobRecord:
    """What the registry holds about one job, ready to render.

    `steps` is the names of the steps this job declared, in order, so a reader
    of the record can say which of them a stalled job stopped at without being
    told separately.
    """

    job_id: str
    operation: str
    state: JobState
    completed: int
    total: int
    message: str
    step: str
    attempt: int
    steps: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "operation": self.operation,
            "state": self.state.value,
            "completed": self.completed,
            "total": self.total,
            "message": self.message,
            "step": self.step,
            "attempt": self.attempt,
            "steps": list(self.steps),
            # Whether a cancel frame naming this job would reach anything. It
            # is stated by the registry rather than derived on the far side,
            # because the rule is this module's and a second derivation of it
            # is a second rule.
            "cancellable": self.state not in TERMINAL,
        }


@dataclass
class _Job:
    """The registry's own mutable half. Nothing outside this module holds one."""

    record: JobRecord
    cancel_requested: bool = False
    listeners: list[Callable[[], None]] = field(default_factory=list)


class JobHandle:
    """One job, from the inside — what the code doing the work holds.

    Every method here is a declaration about the work rather than a request to
    the registry: `reached` says a named step is done, `retry` says the work is
    starting again, and `checkpoint` asks the one question a long job may ask.
    """

    def __init__(self, registry: "JobRegistry", job_id: str) -> None:
        self._registry = registry
        self._job_id = job_id

    @property
    def job_id(self) -> str:
        return self._job_id

    def begin(self, message: str = "") -> None:
        self._registry._begin(self._job_id, message)

    def reached(self, step: str, message: str = "") -> None:
        """One named step of this job is finished.

        The step must be one the job declared. A step nobody declared would
        move a bar past a place the person was never told about, and the count
        it moves against would stop being a count of anything."""
        self._registry._reached(self._job_id, step, message)

    def checkpoint(self, *, pump: bool = True) -> None:
        """Stop here if a person has asked this job to stop.

        Called between steps and never inside one. It runs the pump first, so
        a cancel that is sitting unread on the transport is read before the
        question is answered — otherwise the answer is always no and the
        checkpoint is decoration."""
        self._registry._checkpoint(self._job_id, pump=pump)

    def retry(self, message: str = "") -> None:
        """This job is starting again from its first step."""
        self._registry._retry(self._job_id, message)

    def finish(self, message: str = "") -> None:
        self._registry._finish(self._job_id, message)

    def fail(self, message: str) -> None:
        self._registry._fail(self._job_id, message)

    def __enter__(self) -> "JobHandle":
        self.begin()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        """Close the job with what actually happened, and swallow nothing.

        A job left open by a raise would sit in the registry saying it was
        running for as long as the sidecar lived, which is a channel reporting
        a job nobody is doing."""
        if exc_type is None:
            self._registry._finish_if_open(self._job_id)
            return False
        if isinstance(exc, JobCancelled):
            return False
        self._registry._fail_if_open(self._job_id, str(exc) or exc_type.__name__)
        return False


class JobRegistry:
    """Hold one vault's jobs in minting order, with optional durable receipts."""

    def __init__(
        self,
        sink: Callable[[JobProgressEvent], None] | None = None,
        pump: Callable[[], None] | None = None,
        limit: int = 50,
        state_file: Path | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("a registry that holds no job reports nothing")
        self._sink = sink
        self._pump = pump
        self._limit = limit
        self._persist_lock = RLock()
        self._state_file = Path(state_file) if state_file is not None else None
        self._jobs: dict[str, _Job] = {}
        self._order: list[str] = []
        self._restore()
        last = max((int(job_id.rsplit("-", 1)[-1])
                    for job_id in self._order
                    if job_id.rsplit("-", 1)[-1].isdigit()), default=0)
        self._numbers: Iterator[int] = itertools.count(last + 1)
        if self._order:
            self._persist()

    def _restore(self) -> None:
        """Recover durable job receipts; interrupted work becomes failed."""
        if self._state_file is None or not self._state_file.is_file():
            return
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
            for item in raw[-self._limit:]:
                state = JobState(item["state"])
                if state not in TERMINAL:
                    state = JobState.FAILED
                    item["message"] = ("Interrupted when the app closed; start "
                                       "maintenance again to continue.")
                record = JobRecord(
                    job_id=str(item["job_id"]), operation=str(item["operation"]),
                    state=state, completed=int(item["completed"]),
                    total=int(item["total"]), message=str(item.get("message", "")),
                    step=str(item.get("step", "")), attempt=int(item.get("attempt", 1)),
                    steps=tuple(item.get("steps", ())))
                self._jobs[record.job_id] = _Job(record)
                self._order.append(record.job_id)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._jobs.clear()
            self._order.clear()

    def _persist(self) -> None:
        if self._state_file is None:
            return
        with self._persist_lock:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_file.with_suffix(
                self._state_file.suffix + ".tmp")
            temporary.write_text(
                json.dumps([self._jobs[job_id].record.as_dict()
                            for job_id in self._order], indent=2) + "\n",
                encoding="utf-8")
            temporary.replace(self._state_file)

    # ------------------------------------------------------------ minting

    def open(self, operation: str, steps: tuple[str, ...]) -> JobHandle:
        """Mint one job for one operation, declaring its steps up front.

        Raises ValueError for an operation with no steps: a job that declares
        no step has nothing to report, and a channel carrying it would say only
        that something started and something stopped."""
        if not operation.strip():
            raise ValueError("a job belongs to a named operation")
        if not steps or any(not step.strip() for step in steps):
            raise ValueError("a job declares its steps, each of them named")
        with self._persist_lock:
            job_id = f"{operation}-{next(self._numbers)}"
            self._jobs[job_id] = _Job(JobRecord(
                job_id=job_id, operation=operation, state=JobState.QUEUED,
                completed=0, total=len(steps), message="", step="", attempt=1,
                steps=tuple(steps)))
            self._order.append(job_id)
            self._forget_the_oldest_settled()
            self._persist()
            return JobHandle(self, job_id)

    def active(self, operation: str) -> JobRecord | None:
        """The newest unfinished job for an operation, if one exists."""
        with self._persist_lock:
            return next((self._jobs[job_id].record
                         for job_id in reversed(self._order)
                         if self._jobs[job_id].record.operation == operation
                         and self._jobs[job_id].record.state not in TERMINAL), None)

    def _forget_the_oldest_settled(self) -> None:
        """Keep the registry bounded, and drop only jobs that are over.

        A sidecar that runs all day would otherwise grow one record per capture
        forever. What is dropped is the oldest job that has finished: a running
        job is what the channel exists to report, so it is never the thing that
        makes room."""
        while len(self._order) > self._limit:
            settled = next((job_id for job_id in self._order
                            if self._jobs[job_id].record.state in TERMINAL), None)
            if settled is None:
                return
            self._order.remove(settled)
            del self._jobs[settled]

    # ------------------------------------------------------------ movement

    def _job(self, job_id: str) -> _Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _write(self, job: _Job, status: ProgressStatus) -> None:
        record = job.record
        event = JobProgressEvent(
            job_id=record.job_id, status=status, completed=record.completed,
            total=record.total, message=record.message,
            operation=record.operation, step=record.step, attempt=record.attempt)
        if self._sink is not None:
            self._sink(event)
        self._persist()

    def _move(self, job_id: str, status: ProgressStatus, **fields: Any) -> None:
        with self._persist_lock:
            job = self._job(job_id)
            job.record = replace(job.record, **fields)
            self._write(job, status)

    def _begin(self, job_id: str, message: str) -> None:
        with self._persist_lock:
            job = self._job(job_id)
            if job.record.state in TERMINAL:
                raise ValueError(f"{job_id} is over and cannot begin again")
            self._move(job_id, "started", state=JobState.RUNNING, message=message)

    def _reached(self, job_id: str, step: str, message: str) -> None:
        with self._persist_lock:
            job = self._job(job_id)
            if step not in job.record.steps:
                raise ValueError(
                    f"{step!r} is not a step {job_id} declared: "
                    + ", ".join(job.record.steps))
            completed = job.record.steps.index(step) + 1
            if completed <= job.record.completed:
                raise ValueError(f"{job_id} has already reached {step!r}")
            self._move(job_id, "progress", state=JobState.RUNNING,
                       completed=completed, step=step, message=message)

    def _retry(self, job_id: str, message: str) -> None:
        with self._persist_lock:
            job = self._job(job_id)
            if job.record.state in TERMINAL:
                raise ValueError(f"{job_id} is over and is not tried again")
            self._move(job_id, "started", state=JobState.RUNNING, completed=0,
                       step="", message=message, attempt=job.record.attempt + 1)

    def _finish(self, job_id: str, message: str) -> None:
        with self._persist_lock:
            job = self._job(job_id)
            self._move(job_id, "completed", state=JobState.COMPLETED,
                       completed=job.record.total, message=message)

    def _fail(self, job_id: str, message: str) -> None:
        with self._persist_lock:
            self._move(job_id, "failed", state=JobState.FAILED, message=message)

    def _finish_if_open(self, job_id: str) -> None:
        with self._persist_lock:
            record = self._job(job_id).record
            if record.state not in TERMINAL:
                self._finish(job_id, record.message)

    def _fail_if_open(self, job_id: str, message: str) -> None:
        with self._persist_lock:
            if self._job(job_id).record.state not in TERMINAL:
                self._fail(job_id, message)

    # -------------------------------------------------------- cancellation

    def cancel(self, job_id: str) -> JobRecord:
        """Request cancellation and return the job's resulting record."""
        with self._persist_lock:
            job = self._job(job_id)
            if job.record.state in TERMINAL:
                return job.record
            job.cancel_requested = True
            if job.record.state == JobState.QUEUED:
                # Queued jobs cancel immediately; running jobs use checkpoints.
                self._move(job_id, "cancelled", state=JobState.CANCELLED)
            return self._job(job_id).record

    def cancel_requested(self, job_id: str) -> bool:
        with self._persist_lock:
            return self._job(job_id).cancel_requested

    def _checkpoint(self, job_id: str, *, pump: bool = True) -> None:
        if pump and self._pump is not None:
            self._pump()
        with self._persist_lock:
            job = self._job(job_id)
            if not job.cancel_requested:
                return
            self._move(job_id, "cancelled", state=JobState.CANCELLED)
            raise JobCancelled(job_id)

    # ------------------------------------------------------------ reading

    def records(self) -> tuple[JobRecord, ...]:
        with self._persist_lock:
            return tuple(self._jobs[job_id].record for job_id in self._order)

    def record(self, job_id: str) -> JobRecord:
        with self._persist_lock:
            return self._job(job_id).record

    def read(self) -> dict[str, Any]:
        """The jobs surface, as a read model.

        `state` is the panel's, not a job's: a vault whose sidecar has run no
        job has no channel to show, and says so as an absence rather than as an
        empty list a reader has to interpret."""
        records = self.records()
        running = [record for record in records if record.state == JobState.RUNNING]
        return {
            "state": "ready" if records else "absent",
            "jobs": [record.as_dict() for record in records],
            "running": [record.job_id for record in running],
        }


def a_step_named(steps: tuple[str, ...], step: str) -> str:
    """The step named, checked against the job's own declaration.

    Exported so a caller can name its steps as constants and have the same
    check run where the constant is written rather than where it is used."""
    if step not in steps:
        raise ValueError(f"{step!r} is not among {', '.join(steps)}")
    return step
