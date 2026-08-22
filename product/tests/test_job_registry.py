"""The job registry, the progress channel, and the stop a person can reach.

Three defects the status record named are one design, so they are tested as
one: a job has an identity the sidecar minted, its steps are the steps it
declared, and a person can stop it between two of them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from viva.desktop_bridge.jobs import (JobCancelled, JobProgressEvent,
                                      JobRegistry, JobState)
from viva.desktop_bridge.__main__ import Sidecar
from viva.vault import Vault


STEPS = ("checked", "opened", "settled")


def _registry(**kwargs) -> tuple[JobRegistry, list[JobProgressEvent]]:
    events: list[JobProgressEvent] = []
    return JobRegistry(events.append, **kwargs), events


def test_a_job_is_minted_by_the_registry_and_names_its_operation():
    registry, _ = _registry()

    first = registry.open("viva.documents.upload", STEPS)
    second = registry.open("viva.documents.upload", STEPS)

    assert first.job_id != second.job_id
    assert first.job_id.startswith("viva.documents.upload-")
    assert registry.record(first.job_id).total == len(STEPS)


def test_a_job_with_no_declared_step_is_refused():
    """A job that declares no step has nothing to report, and a channel
    carrying it would say only that something started and something stopped."""
    registry, _ = _registry()

    with pytest.raises(ValueError, match="declares its steps"):
        registry.open("viva.documents.upload", ())


def test_every_step_the_channel_reports_is_one_the_job_declared():
    registry, _ = _registry()
    job = registry.open("viva.documents.upload", STEPS)
    job.begin()

    with pytest.raises(ValueError, match="is not a step"):
        job.reached("sealing")


def test_the_channel_brackets_a_job_and_names_each_step_between():
    registry, events = _registry()
    job = registry.open("viva.documents.upload", STEPS)

    with job:
        for step in STEPS:
            job.reached(step)

    assert [event.status for event in events] == [
        "started", "progress", "progress", "progress", "completed"]
    assert [event.step for event in events] == ["", *STEPS, "settled"]
    assert [event.completed for event in events] == [0, 1, 2, 3, 3]
    assert all(event.total == 3 for event in events)
    assert all(event.operation == "viva.documents.upload" for event in events)


def test_a_job_left_open_by_a_raise_is_closed_as_failed():
    """A job left open would sit in the registry saying it was running for as
    long as the sidecar lived, which is a channel reporting work nobody does."""
    registry, events = _registry()
    job = registry.open("viva.documents.upload", STEPS)

    with pytest.raises(RuntimeError, match="the disk went away"):
        with job:
            job.reached("checked")
            raise RuntimeError("the disk went away")

    assert registry.record(job.job_id).state is JobState.FAILED
    assert events[-1].status == "failed"
    assert events[-1].message == "the disk went away"


def test_a_retry_says_which_try_this_is_rather_than_restarting_silently():
    """A bar that restarts with no word for why has told a person their work
    was lost."""
    registry, events = _registry()
    job = registry.open("viva.documents.upload", STEPS)

    with job:
        job.reached("checked")
        job.retry("the reader was not there")
        for step in STEPS:
            job.reached(step)

    assert [event.attempt for event in events] == [1, 1, 2, 2, 2, 2, 2]
    assert registry.record(job.job_id).attempt == 2


def test_a_checkpoint_stops_a_job_a_person_asked_to_stop():
    registry, events = _registry()
    job = registry.open("viva.documents.upload", STEPS)
    reached = []

    with pytest.raises(JobCancelled):
        with job:
            job.checkpoint()
            job.reached("checked")
            reached.append("checked")
            registry.cancel(job.job_id)
            job.checkpoint()
            job.reached("opened")
            reached.append("opened")

    assert reached == ["checked"]
    assert registry.record(job.job_id).state is JobState.CANCELLED
    assert events[-1].status == "cancelled"


def test_a_checkpoint_runs_the_pump_before_it_answers():
    """A cancel sitting unread on the transport has to be read before the
    question is asked, or the answer is always no and the checkpoint is
    decoration."""
    pumped = []
    registry = JobRegistry(None, lambda: pumped.append(True))
    job = registry.open("viva.documents.upload", STEPS)

    with job:
        job.checkpoint()

    assert pumped == [True]


def test_a_queued_job_stops_without_anyone_running_a_checkpoint():
    """Nothing will run a checkpoint for work that has not begun, so the
    registry closes it itself."""
    registry, events = _registry()
    job = registry.open("viva.documents.upload", STEPS)

    record = registry.cancel(job.job_id)

    assert record.state is JobState.CANCELLED
    assert events[-1].status == "cancelled"


def test_stopping_a_job_that_is_over_moves_nothing_and_says_what_it_found():
    registry, _ = _registry()
    job = registry.open("viva.documents.upload", STEPS)
    with job:
        for step in STEPS:
            job.reached(step)

    record = registry.cancel(job.job_id)

    assert record.state is JobState.COMPLETED
    assert record.as_dict()["cancellable"] is False


def test_the_registry_is_bounded_and_never_forgets_a_running_job():
    registry, _ = _registry(limit=2)
    running = registry.open("viva.documents.upload", STEPS)
    running.begin()
    for _ in range(4):
        done = registry.open("viva.documents.upload", STEPS)
        with done:
            for step in STEPS:
                done.reached(step)

    held = [record.job_id for record in registry.records()]

    assert running.job_id in held
    assert len(held) <= 3


def test_the_registry_read_is_absent_before_any_job_and_ready_after_one():
    registry, _ = _registry()

    assert registry.read()["state"] == "absent"

    job = registry.open("viva.documents.upload", STEPS)
    job.begin()

    read = registry.read()
    assert read["state"] == "ready"
    assert read["running"] == [job.job_id]
    assert read["jobs"][0]["steps"] == list(STEPS)
    json.dumps(read, allow_nan=False)


def test_a_progress_event_counts_steps_and_refuses_an_impossible_count():
    with pytest.raises(ValueError, match="between zero and total"):
        JobProgressEvent("job-1", "started", 2, 1)
    with pytest.raises(ValueError, match="counted from one"):
        JobProgressEvent("job-1", "started", 0, 1, attempt=0)


# ------------------------------------------------------- the pump, end to end


class _Line:
    """A transport that hands back frames a test has already placed on it.

    It is a real file, because the pump asks for a file descriptor and a
    source that cannot give one is not asked at all."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.write_text("")
        self._handle = self._path.open("r")

    def fileno(self) -> int:
        return self._handle.fileno()

    def readline(self) -> str:
        return self._handle.readline()

    def place(self, frame: dict) -> None:
        at = self._handle.tell()
        with self._path.open("a") as out:
            out.write(json.dumps(frame) + "\n")
        self._handle.seek(at)


class _Output:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    def write(self, text: str) -> None:
        self.frames.append(json.loads(text))

    def flush(self) -> None:
        pass


def _frame(operation: str, payload: dict, request_id: str = "r1") -> dict:
    return {"protocol": "2.0", "request_id": request_id,
            "operation": operation, "payload": payload}


def test_the_pump_answers_a_stop_and_holds_everything_else(tmp_path):
    """Answering anything but a stop mid-job would put a second handler on the
    vault while the first is still working, which is the one thing the
    single-frame loop exists to prevent."""
    source = _Line(tmp_path / "frames")
    output = _Output()
    sidecar = Sidecar(output, source)
    sidecar.handle(json.dumps(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "vault"), "passphrase": "pw"})))
    source.place(_frame("viva.documents.cancel", {"job_id": "nothing"}, "c1"))
    source.place(_frame("viva.surface.read", {"surface": "overview"}, "r2"))

    sidecar.pump()

    assert [frame["request_id"] for frame in output.frames] == ["c1"]
    assert [json.loads(held)["request_id"] for held in sidecar.held()] == ["r2"]


def test_a_capture_can_be_stopped_by_a_frame_that_arrives_while_it_runs(
        tmp_path, monkeypatch):
    """The whole point of the pump, end to end: the stop is placed on the
    transport after the capture has begun, and the capture does not finish."""
    source = _Line(tmp_path / "frames")
    output = _Output()
    sidecar = Sidecar(output, source)
    sidecar.handle(json.dumps(_frame(
        "bridge.open_vault",
        {"vault_directory": str(tmp_path / "vault"), "passphrase": "pw"})))
    document = tmp_path / "statement.pdf"
    document.write_bytes(b"%PDF-1.4 statement")

    # The stop names the job the sidecar is about to mint. Nothing guesses the
    # name: it is read off the registry the moment the job exists, from inside
    # the step that runs before the first checkpoint that could honour it.
    from viva.ingest import reader as reader_module
    real_stat = Path.stat

    def place_the_stop(self, *args, **kwargs):
        if self == document and not source._placed:
            source._placed = True
            source.place(_frame("viva.documents.cancel",
                                {"job_id": "viva.documents.upload-1"}, "c1"))
        return real_stat(self, *args, **kwargs)

    source._placed = False
    monkeypatch.setattr(Path, "stat", place_the_stop)
    monkeypatch.setattr(reader_module, "live_reading_configured", lambda: False)

    responses = sidecar.handle(json.dumps(
        _frame("viva.documents.upload", {"path": str(document)}, "u1")))

    answered = json.loads(responses[0])
    assert answered["result"]["kind"] == "refused"
    assert answered["result"]["reason"] == "job_cancelled"
    vault = Vault.open(tmp_path / "vault", "pw")
    assert vault.raw.doc_ids() == []
