"""Trust's remainder: the maintenance run, anchoring, and a file to send.

Two of the three are about saying plainly what this machine cannot establish.
The third is about a file somebody can hand over without handing over their
money.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from viva.desktop_bridge.handlers import BridgeRequestError, handlers_for_opened_vault
from viva.desktop_bridge.trust_actions import TrustActions, _run_request
from viva.desktop_bridge.jobs import JobRegistry
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger.events import document_captured, read_recorded
from viva.persona import moment
from viva.surface.diagnostics import FIELDS, diagnostics, written
from viva.vault import Vault

PASSPHRASE = "a-real-passphrase"


def _vault(tmp_path: Path) -> Vault:
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    vault.ledger.append(document_captured("d" * 64, "everyday-checking.pdf", 11,
                                          "statement", 0.9, "2026-07-01"))
    vault.ledger.append(read_recorded("d" * 64, "a-pinned-1", "p", "text", "{}",
                                      0.25, 1, 2, True, None, "2026-07-01"))
    vault.synchronize_read_store()
    return vault


# ------------------------------------------------------- unattended work


def test_a_request_that_does_not_say_to_spend_plans_and_stops(tmp_path: Path):
    """The agent reaches a model. A request that did not say to spend has not
    asked for that."""
    answered = TrustActions(_vault(tmp_path)).run({})

    assert answered["kind"] == "completed"
    assert answered["message"] == moment("maintenance_planned")
    assert answered["state"]["dry_run"] is True
    assert answered["state"]["calls_spent"] == 0


def test_a_run_with_work_to_do_and_no_model_named_says_so_and_sends_nothing(
        tmp_path: Path, monkeypatch):
    import viva.agent.run as agent

    monkeypatch.setattr(agent, "model_configured", lambda: False)

    answered = TrustActions(_vault(tmp_path)).run({"spend": True})

    assert answered["state"]["queued"] is True
    assert answered["state"]["job_id"]
    assert answered["message"] == moment("maintenance_started")


def test_an_unconfigured_paid_job_fails_before_the_spent_step(
        tmp_path: Path, monkeypatch):
    import viva.agent.run as agent

    monkeypatch.setattr(agent, "wake", lambda *_args, **_kwargs:
                        SimpleNamespace(could_not_spend=True, calls_spent=0))
    jobs = JobRegistry()
    actions = TrustActions(_vault(tmp_path), jobs)
    job = jobs.open("viva.maintenance.run", ("planned", "spent"))

    actions._spend_in_background(job, None)

    record = jobs.record(job.job_id)
    assert record.state.value == "failed"
    assert record.completed == 1
    assert record.step == "planned"
    assert "no model is configured" in record.message


def test_paid_maintenance_uses_an_isolated_vault_and_reuses_an_active_job(
        tmp_path: Path, monkeypatch):
    import threading
    import viva.agent.run as agent

    vault = _vault(tmp_path)
    seen = []
    gate = threading.Event()
    release = threading.Event()

    def wake(worker, **_kwargs):
        seen.append(worker)
        gate.set()
        release.wait(2)
        return SimpleNamespace(could_not_spend=True, calls_spent=0)

    monkeypatch.setattr(agent, "wake", wake)
    jobs = JobRegistry()
    actions = TrustActions(vault, jobs)

    first = actions.run({"spend": True})
    assert gate.wait(2)
    second = actions.run({"spend": True})
    release.set()

    assert seen[0] is not vault
    assert first["state"]["job_id"] == second["state"]["job_id"]
    assert len(jobs.records()) == 1


def test_paid_maintenance_reports_the_free_plan_and_can_stop_before_spend(
        tmp_path: Path, monkeypatch):
    import viva.agent.run as agent

    calls = []
    jobs = JobRegistry()
    actions = TrustActions(_vault(tmp_path), jobs)
    job = jobs.open("viva.maintenance.run", ("planned", "spent"))

    def wake(_vault, **kwargs):
        calls.append(kwargs["dry_run"])
        if kwargs["dry_run"]:
            jobs.cancel(job.job_id)
        return SimpleNamespace(could_not_spend=False, calls_spent=0)

    monkeypatch.setattr(agent, "wake", wake)
    actions._spend_in_background(job, 1)

    record = jobs.record(job.job_id)
    assert calls == [True]
    assert record.state.value == "cancelled"
    assert record.completed == 1 and record.step == "planned"


def test_paid_maintenance_waits_for_forked_events_to_reach_activity(
        tmp_path: Path, monkeypatch):
    import threading
    import viva.agent.run as agent

    vault = _vault(tmp_path)
    jobs = JobRegistry()
    actions = TrustActions(vault, jobs)
    job = jobs.open("viva.maintenance.run", ("planned", "spent"))
    committed = threading.Event()
    release = threading.Event()
    original_sync = vault.synchronize_read_store

    def delayed_sync(**kwargs):
        assert release.wait(2)
        return original_sync(**kwargs)

    def wake(worker, **kwargs):
        if not kwargs["dry_run"]:
            worker.ledger.append(document_captured(
                "e" * 64, "synthetic.pdf", 1, "statement", 0.9, "2026-07-02"))
            committed.set()
        return SimpleNamespace(could_not_spend=False, calls_spent=0)

    monkeypatch.setattr(agent, "wake", wake)
    monkeypatch.setattr(vault, "synchronize_read_store", delayed_sync)
    thread = threading.Thread(target=actions._spend_in_background, args=(job, 0))
    thread.start()
    try:
        assert committed.wait(2)
        assert jobs.record(job.job_id).state.value == "running"
        assert jobs.record(job.job_id).step == "planned"
        with pytest.raises(BridgeRequestError, match="not caught up"):
            OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert jobs.record(job.job_id).state.value == "completed"
    assert OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})


def test_paid_maintenance_reports_saved_events_when_read_store_cannot_catch_up(
        tmp_path: Path, monkeypatch):
    import viva.agent.run as agent
    import viva.desktop_bridge.trust_actions as trust

    vault = _vault(tmp_path)
    jobs = JobRegistry()
    actions = TrustActions(vault, jobs)
    job = jobs.open("viva.maintenance.run", ("planned", "spent"))
    before = vault.ledger.store.authenticated_identity()

    def wake(worker, **kwargs):
        if not kwargs["dry_run"]:
            worker.ledger.append(document_captured(
                "e" * 64, "synthetic.pdf", 1, "statement", 0.9, "2026-07-02"))
        return SimpleNamespace(could_not_spend=False, calls_spent=0)

    monkeypatch.setattr(agent, "wake", wake)
    monkeypatch.setattr(trust, "READ_VISIBILITY_TIMEOUT", 0.02)
    monkeypatch.setattr(vault, "synchronize_read_store", lambda **_kwargs: "stale")
    actions._spend_in_background(job, 0)

    record = jobs.record(job.job_id)
    assert vault.ledger.store.authenticated_identity() != before
    assert record.state.value == "failed"
    assert record.completed == 1 and record.step == "planned"
    assert "may have been saved" in record.message
    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})

    # The failed job never reruns its committed work. Disposable SQL can still
    # recover in the background after its temporary failure clears.
    monkeypatch.setattr(vault, "synchronize_read_store",
                        Vault.synchronize_read_store.__get__(vault))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})
            break
        except BridgeRequestError:
            time.sleep(0.01)
    else:
        pytest.fail("read store did not recover after failed maintenance")


def test_visibility_wait_rechecks_a_newer_canonical_write(tmp_path: Path, monkeypatch):
    vault = _vault(tmp_path)
    original_sync = vault.synchronize_read_store
    writes = 0

    def write_during_first_publication(**kwargs):
        nonlocal writes
        state = original_sync(**kwargs)
        if writes == 0:
            writes += 1
            vault.fork_for_background().ledger.append(document_captured(
                "e" * 64, "synthetic.pdf", 1, "statement", 0.9, "2026-07-02"))
        return state

    monkeypatch.setattr(vault, "synchronize_read_store", write_during_first_publication)
    vault._read_store_visibility_held = True
    assert vault.wait_for_read_store(timeout=2)
    assert writes == 1
    assert vault.read_store_lifecycle == "equal"
    assert OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})


def test_cancel_after_canonical_commit_does_not_undo_or_repeat_work(
        tmp_path: Path, monkeypatch):
    import threading
    import viva.agent.run as agent

    vault = _vault(tmp_path)
    jobs = JobRegistry()
    actions = TrustActions(vault, jobs)
    job = jobs.open("viva.maintenance.run", ("planned", "spent"))
    waiting = threading.Event()
    release = threading.Event()
    original_sync = vault.synchronize_read_store
    paid = 0

    def delayed_sync(**kwargs):
        waiting.set()
        assert release.wait(2)
        return original_sync(**kwargs)

    def wake(worker, **kwargs):
        nonlocal paid
        if not kwargs["dry_run"]:
            paid += 1
            worker.ledger.append(document_captured(
                "e" * 64, "synthetic.pdf", 1, "statement", 0.9, "2026-07-02"))
        return SimpleNamespace(could_not_spend=False, calls_spent=0)

    monkeypatch.setattr(agent, "wake", wake)
    monkeypatch.setattr(vault, "synchronize_read_store", delayed_sync)
    thread = threading.Thread(target=actions._spend_in_background, args=(job, 0))
    thread.start()
    try:
        assert waiting.wait(2)
        jobs.cancel(job.job_id)
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert jobs.record(job.job_id).state.value == "cancelled"
    assert paid == 1
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            assert OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})
            break
        except BridgeRequestError:
            time.sleep(0.01)
    else:
        pytest.fail("read store did not recover after cancellation")


def test_failed_paid_wake_releases_visibility_fence_after_recovery(
        tmp_path: Path, monkeypatch):
    import viva.agent.run as agent

    vault = _vault(tmp_path)
    jobs = JobRegistry()
    actions = TrustActions(vault, jobs)
    job = jobs.open("viva.maintenance.run", ("planned", "spent"))

    def wake(worker, **kwargs):
        if not kwargs["dry_run"]:
            worker.ledger.append(document_captured(
                "e" * 64, "synthetic.pdf", 1, "statement", 0.9, "2026-07-02"))
            raise RuntimeError("synthetic paid-wake failure")
        return SimpleNamespace(could_not_spend=False, calls_spent=0)

    monkeypatch.setattr(agent, "wake", wake)
    with pytest.raises(RuntimeError, match="synthetic paid-wake failure"):
        actions._spend_in_background(job, 0)
    assert jobs.record(job.job_id).state.value == "failed"
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            assert OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})
            break
        except BridgeRequestError:
            time.sleep(0.01)
    else:
        pytest.fail("read store did not recover after paid-wake failure")


def test_failed_job_keeps_activity_closed_during_delayed_recovery(
        tmp_path: Path, monkeypatch):
    import threading
    import viva.agent.run as agent
    import viva.desktop_bridge.trust_actions as trust

    vault = _vault(tmp_path)
    jobs = JobRegistry()
    actions = TrustActions(vault, jobs)
    job = jobs.open("viva.maintenance.run", ("planned", "spent"))
    recovering = threading.Event()
    release = threading.Event()
    original_sync = vault.synchronize_read_store

    def sync(**kwargs):
        if jobs.record(job.job_id).state.value != "failed":
            return "stale"
        recovering.set()
        assert release.wait(2)
        return original_sync(**kwargs)

    def wake(worker, **kwargs):
        if not kwargs["dry_run"]:
            worker.ledger.append(document_captured(
                "e" * 64, "synthetic.pdf", 1, "statement", 0.9, "2026-07-02"))
        return SimpleNamespace(could_not_spend=False, calls_spent=0)

    monkeypatch.setattr(agent, "wake", wake)
    monkeypatch.setattr(trust, "READ_VISIBILITY_TIMEOUT", 0.02)
    monkeypatch.setattr(vault, "synchronize_read_store", sync)
    actions._spend_in_background(job, 0)
    try:
        assert recovering.wait(2)
        # A late worker reply may advertise its earlier generation as ready.
        vault.read_store_lifecycle = "equal"
        with pytest.raises(BridgeRequestError, match="not caught up"):
            OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            assert OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})
            break
        except BridgeRequestError:
            time.sleep(0.01)
    else:
        pytest.fail("read store did not recover")


def test_old_recovery_cannot_release_a_new_paid_jobs_read_fence(
        tmp_path: Path, monkeypatch):
    import threading
    import viva.agent.run as agent
    import viva.desktop_bridge.trust_actions as trust

    vault = _vault(tmp_path)
    jobs = JobRegistry()
    actions = TrustActions(vault, jobs)
    old = jobs.open("viva.maintenance.run", ("planned", "spent"))
    recovering = threading.Event()
    release_recovery = threading.Event()
    new_paid = threading.Event()
    release_new = threading.Event()
    original_sync = vault.synchronize_read_store
    paid = 0

    def sync(**kwargs):
        if jobs.record(old.job_id).state.value != "failed":
            return "stale"
        if not recovering.is_set():
            recovering.set()
            assert release_recovery.wait(2)
        return original_sync(**kwargs)

    def wake(worker, **kwargs):
        nonlocal paid
        if not kwargs["dry_run"]:
            paid += 1
            if paid == 2:
                new_paid.set()
                assert release_new.wait(2)
            worker.ledger.append(document_captured(
                ("e" if paid == 1 else "f") * 64,
                "synthetic.pdf", 1, "statement", 0.9, "2026-07-02"))
        return SimpleNamespace(could_not_spend=False, calls_spent=0)

    monkeypatch.setattr(agent, "wake", wake)
    monkeypatch.setattr(trust, "READ_VISIBILITY_TIMEOUT", 0.02)
    monkeypatch.setattr(vault, "synchronize_read_store", sync)
    actions._spend_in_background(old, 0)
    assert recovering.wait(2)
    monkeypatch.setattr(trust, "READ_VISIBILITY_TIMEOUT", 2)
    new = jobs.open("viva.maintenance.run", ("planned", "spent"))
    thread = threading.Thread(target=actions._spend_in_background, args=(new, 0))
    thread.start()
    try:
        assert new_paid.wait(2)
        release_recovery.set()
        time.sleep(0.05)
        vault.read_store_lifecycle = "equal"
        with pytest.raises(BridgeRequestError, match="not caught up"):
            OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})
    finally:
        release_new.set()
        thread.join(2)
    assert not thread.is_alive()
    assert paid == 2
    assert jobs.record(new.job_id).state.value == "completed"
    assert OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})


def test_visibility_serial_change_is_atomic_with_old_waiter_release(
        tmp_path: Path, monkeypatch):
    import threading

    vault = _vault(tmp_path)
    old_serial = vault.hold_read_store_visibility()
    entered = threading.Event()
    release = threading.Event()
    original_source = vault.read_store.authenticated_source_identity

    def delayed_source(revision):
        entered.set()
        assert release.wait(2)
        return original_source(revision)

    monkeypatch.setattr(vault.read_store, "authenticated_source_identity",
                        delayed_source)
    finished = threading.Event()

    def old_waiter():
        assert vault.wait_for_read_store(timeout=2, visibility_serial=old_serial)
        finished.set()

    thread = threading.Thread(target=old_waiter)
    thread.start()
    try:
        assert entered.wait(2)
        new_serial = vault.hold_read_store_visibility()
    finally:
        release.set()
        thread.join(2)
    assert finished.is_set()
    assert vault.holds_read_store_visibility(new_serial)
    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})
    assert vault.wait_for_read_store(timeout=2, visibility_serial=new_serial)
    assert OpenedVaultSurfaceProvider(vault).read_surface("activity", {"limit": 10})


def test_the_reply_carries_the_whole_run_rather_than_a_summary(tmp_path: Path):
    """A report of unattended work that summarised itself would be the one
    place in this product where somebody has to take a summary on trust."""
    answered = TrustActions(_vault(tmp_path)).run({})

    for named in ("observation", "considered", "cooled", "deferred",
                  "performed", "calls_spent", "calls_budget"):
        assert named in answered["state"]


def test_spending_is_a_word_and_a_budget_is_a_number():
    assert _run_request({}) == (False, None)
    assert _run_request({"spend": True, "budget": 3}) == (True, 3)
    with pytest.raises(BridgeRequestError):
        _run_request({"spend": "yes"})
    with pytest.raises(BridgeRequestError):
        _run_request({"budget": -1})
    with pytest.raises(BridgeRequestError):
        _run_request({"spend": True, "rules": {}})


# ----------------------------------------------------------- what is absent


def test_the_trust_read_says_plainly_that_nothing_is_anchored(tmp_path: Path):
    """An absent capability described in soft words reads as a capability."""
    read = OpenedVaultSurfaceProvider(_vault(tmp_path)).read_surface("trust", {})

    anchoring = [item for item in read["absences"] if item["id"] == "anchoring"]
    assert anchoring
    assert anchoring[0]["sentence"] == moment("trust_no_anchoring")


def test_a_vault_nothing_has_run_over_says_that_too(tmp_path: Path):
    read = OpenedVaultSurfaceProvider(_vault(tmp_path)).read_surface("trust", {})

    assert [item["id"] for item in read["absences"]] == [
        "anchoring", "maintenance"]


# --------------------------------------------------- a file somebody can send


def test_the_diagnostic_carries_only_the_fields_it_names():
    """Built from a list of what may be said rather than by removing what must
    not travel: a list of what to take out is wrong the first time somebody
    adds a field."""
    assert set(diagnostics()) == set(FIELDS)


def test_nothing_from_a_vault_reaches_the_diagnostic(tmp_path: Path):
    vault = _vault(tmp_path)
    written_to = tmp_path / "diagnostic.json"

    answered = TrustActions(vault).diagnose({"file": str(written_to)})
    held = written_to.read_text()

    assert answered["kind"] == "completed"
    assert answered["message"] == moment("diagnostic_written")
    for private in ("everyday-checking.pdf", "d" * 64, "0.25", "2026-07-01"):
        assert private not in held


def test_the_diagnostic_counts_what_a_vault_holds_without_naming_any_of_it(
        tmp_path: Path):
    vault = _vault(tmp_path)
    written_to = tmp_path / "diagnostic.json"

    TrustActions(vault).diagnose({"file": str(written_to)})
    held = json.loads(written_to.read_text())

    assert held["documents"] == 1
    assert held["model_calls"] == 1
    assert held["events"] >= 2
    assert held["open_document_holds"] == 0
    assert held["open_conversation_questions"] == held["open_questions"]


def test_the_model_is_reported_as_named_or_not_and_never_by_name(monkeypatch):
    """A pinned id names a provider and a spend."""
    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "anthropic")
    monkeypatch.setenv("VIVA_MODEL", "a-very-particular-model-1")

    held = diagnostics()

    assert held["model_named"] is True
    assert held["model_adapter"] == "anthropic"
    assert "a-very-particular-model-1" not in json.dumps(held)


def test_a_count_that_is_not_a_count_writes_a_zero_rather_than_itself():
    """A caller that handed a name or an amount by mistake writes a zero rather
    than writing it out."""
    held = diagnostics({"documents": "Everyday Checking", "events": -4,
                        "model_calls": True})

    assert held["documents"] == 0
    assert held["events"] == 0
    assert held["model_calls"] == 0


def test_the_file_is_readable_before_it_is_sent():
    """The only check that matters is a person reading it."""
    text = written({"documents": 2})

    assert json.loads(text)["documents"] == 2
    assert text.endswith("\n")


def test_a_file_that_will_not_be_written_changes_nothing(tmp_path: Path):
    answered = TrustActions(_vault(tmp_path)).diagnose(
        {"file": str(tmp_path / "vault" / "events.jsonl" / "nope.json")})

    assert answered["kind"] == "refused"
    assert answered["reason"] == "file_unwritable"


def test_both_actions_are_served_by_an_opened_vault():
    handlers = handlers_for_opened_vault(object()).handlers

    assert "viva.maintenance.run" in handlers
    assert "viva.maintenance.diagnose" in handlers
