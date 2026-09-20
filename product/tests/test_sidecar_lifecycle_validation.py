"""The lifecycle check must detect loss, refused reopen and false version evidence."""
from pathlib import Path

import pytest

from scripts import validate_sidecar_lifecycle as lifecycle


def fixture_artifacts(tmp_path):
    baseline, candidate = tmp_path / "baseline", tmp_path / "candidate"
    baseline.write_bytes(b"baseline synthetic executable")
    candidate.write_bytes(b"candidate synthetic executable")
    return baseline, candidate


def fake_probe(executable, home, *, create):
    vault = home / "vault"
    if create:
        vault.mkdir()
        (vault / "raw").mkdir()
        (vault / "raw" / "document").write_bytes(b"synthetic encrypted original")
        (vault / "events.jsonl").write_bytes(b"synthetic encrypted ledger")
        (vault / "events.jsonl.head").write_bytes(b"synthetic authenticated head")
    else:
        assert (vault / "events.jsonl").is_file()
    return "synthetic-revision"


def test_roundtrip_reopens_without_recreating_and_cleans_profile(tmp_path, monkeypatch):
    seen = []
    def probe(executable, home, *, create):
        seen.append((home, create, executable.read_bytes()))
        return fake_probe(executable, home, create=create)
    monkeypatch.setattr(lifecycle, "probe", probe)
    report = lifecycle.validate(*fixture_artifacts(tmp_path), require_distinct=True)
    assert report["mode"] == "distinct-artifact"
    assert [create for _, create, _ in seen] == [True, False, False, False]
    assert seen[0][2] == seen[2][2] == seen[3][2] != seen[1][2]
    assert not seen[0][0].exists()


def test_same_bytes_cannot_be_reported_as_version_transition(tmp_path, monkeypatch):
    baseline, _ = fixture_artifacts(tmp_path)
    monkeypatch.setattr(lifecycle, "probe", fake_probe)
    assert lifecycle.validate(baseline, baseline)["mode"] == "same-artifact-smoke"
    with pytest.raises(RuntimeError, match="distinct artifact"):
        lifecycle.validate(baseline, baseline, require_distinct=True)


@pytest.mark.parametrize("mutation", ["delete-ledger", "change-ledger", "delete-original", "refuse-open"])
def test_bad_replacement_fails_and_cleans_up(tmp_path, monkeypatch, mutation):
    homes = []
    def probe(executable, home, *, create):
        homes.append(home)
        revision = fake_probe(executable, home, create=create)
        if not create:
            if mutation == "refuse-open":
                raise RuntimeError("refused reopen")
            path = home / "vault" / ("raw/document" if mutation == "delete-original" else "events.jsonl")
            if mutation == "change-ledger":
                path.write_bytes(b"corrupt")
            else:
                path.unlink()
        return revision
    monkeypatch.setattr(lifecycle, "probe", probe)
    with pytest.raises(RuntimeError):
        lifecycle.validate(*fixture_artifacts(tmp_path))
    assert not homes[0].exists()


def test_removal_cannot_destroy_vault(tmp_path, monkeypatch):
    original = lifecycle.shutil.rmtree
    def destructive_remove(path, *args, **kwargs):
        if Path(path).name == "installation":
            (Path(path).parent / "profile/vault/events.jsonl").unlink()
        return original(path, *args, **kwargs)
    monkeypatch.setattr(lifecycle, "probe", fake_probe)
    monkeypatch.setattr(lifecycle.shutil, "rmtree", destructive_remove)
    with pytest.raises(RuntimeError, match="removing application"):
        lifecycle.validate(*fixture_artifacts(tmp_path))


def test_environment_drops_credentials_proxies_and_loader_injection(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "HTTPS_PROXY", "VIVA_ENV_FILE", "PYTHONPATH", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "PATH"):
        monkeypatch.setenv(name, "must-not-reach-child")
    environment = lifecycle.isolated_environment(tmp_path)
    assert "must-not-reach-child" not in environment.values()
    assert Path(environment["VIVA_ENV_FILE"]).read_text() == ""
    assert environment["HOME"] == environment["USERPROFILE"] == str(tmp_path)


def test_failed_cli_removes_stale_passing_report(tmp_path, monkeypatch):
    baseline, candidate = fixture_artifacts(tmp_path)
    output = tmp_path / "report.json"
    output.write_text('{"status":"passed"}')
    monkeypatch.setattr("sys.argv", ["check", "--baseline", str(baseline), "--candidate", str(candidate), "--output", str(output)])
    def fail(*args, **kwargs):
        raise RuntimeError("broken artifact")
    monkeypatch.setattr(lifecycle, "validate", fail)
    with pytest.raises(RuntimeError):
        lifecycle.main()
    assert not output.exists()


def test_response_timeout_kills_only_owned_process(tmp_path, monkeypatch):
    import subprocess
    import sys
    original = subprocess.Popen
    def launch(command, **kwargs):
        return original([sys.executable, "-c", "import sys,time; sys.stdin.readline(); time.sleep(30)"], **kwargs)
    monkeypatch.setattr(lifecycle.subprocess, "Popen", launch)
    session = lifecycle.Session(tmp_path / "synthetic", tmp_path, timeout=0.02)
    with pytest.raises(RuntimeError, match="timed out"):
        session.ask("bridge.handshake")
    session.process.kill()
    with pytest.raises(RuntimeError, match="exit cleanly"):
        session.close()
    assert session.process.poll() is not None


def test_release_workflow_requires_lifecycle_before_bundling():
    import yaml
    root = Path(__file__).parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/release-desktop.yml").read_text())
    job = workflow["jobs"]["package"]
    def check(candidate):
        steps = candidate["steps"]
        gates = [step for step in steps if step.get("run") ==
                 'python scripts/validate_sidecar_lifecycle.py --target "${{ matrix.target }}" --output sidecar-lifecycle.json']
        assert len(gates) == 1
        assert not candidate.get("continue-on-error") and not candidate.get("if")
        assert not gates[0].get("continue-on-error") and not gates[0].get("if")
        bundle = next(step for step in steps if step.get("uses", "").startswith("tauri-apps/tauri-action@"))
        assert steps.index(gates[0]) < steps.index(bundle)
    check(job)
    import copy
    for mutation in ("remove", "suppressed", "echo"):
        changed = copy.deepcopy(job)
        gate = next(step for step in changed["steps"] if "validate_sidecar_lifecycle.py" in step.get("run", ""))
        if mutation == "remove":
            changed["steps"].remove(gate)
        elif mutation == "suppressed":
            gate["continue-on-error"] = True
        else:
            gate["run"] = "echo " + gate["run"]
        with pytest.raises(AssertionError):
            check(changed)


def test_report_cannot_overwrite_input_artifact(tmp_path, monkeypatch):
    baseline, candidate = fixture_artifacts(tmp_path)
    original = baseline.read_bytes()
    monkeypatch.setattr("sys.argv", ["check", "--baseline", str(baseline), "--candidate", str(candidate), "--output", str(baseline)])
    with pytest.raises(SystemExit):
        lifecycle.main()
    assert baseline.read_bytes() == original


def test_changed_copy_does_not_receive_passing_hash_binding(tmp_path, monkeypatch):
    original = lifecycle.shutil.copy2
    def corrupt(source, destination):
        original(source, destination)
        Path(destination).write_bytes(b"changed")
    monkeypatch.setattr(lifecycle.shutil, "copy2", corrupt)
    monkeypatch.setattr(lifecycle, "probe", fake_probe)
    with pytest.raises(RuntimeError, match="changed before launch"):
        lifecycle.validate(*fixture_artifacts(tmp_path))


@pytest.mark.parametrize("data", [{"state": "failed", "documents": [{}]}, {"state": "ready", "documents": []}, {"state": "absent"}])
def test_probe_rejects_failed_or_empty_sample_reads(tmp_path, monkeypatch, data):
    class Replies:
        def __init__(self, *args):
            pass
        def ask(self, operation, payload=None):
            if operation == "bridge.handshake":
                return {"protocol": "2.1", "revision": "synthetic"}
            if operation == "viva.lifecycle.read":
                return {"origin": "packaged"}
            if operation == "bridge.open_demo_vault":
                return {"sample": True}
            if payload["surface"] == "overview_accounts":
                return {"data": {"freshness": "current"}}
            return {"data": data}
        def close(self):
            pass
    monkeypatch.setattr(lifecycle, "Session", Replies)
    with pytest.raises(RuntimeError, match="read surfaces"):
        lifecycle.probe(tmp_path / "synthetic", tmp_path, create=True)


def test_queued_events_cannot_extend_response_deadline(monkeypatch):
    import io
    import json
    import queue
    import time
    from types import SimpleNamespace
    session = lifecycle.Session.__new__(lifecycle.Session)
    session.process = SimpleNamespace(stdin=io.StringIO())
    session.frames = queue.Queue()
    session.number, session.timeout = 0, 0.01
    for _ in range(20):
        session.frames.put('{"event":"progress"}')
    session.frames.put('{"request_id":"lifecycle-1","ok":true,"result":{}}')
    original = json.loads
    def delayed(line):
        time.sleep(0.002)
        return original(line)
    monkeypatch.setattr(lifecycle.json, "loads", delayed)
    with pytest.raises(RuntimeError, match="timed out"):
        session.ask("bridge.handshake")


def test_close_escalates_only_its_owned_child(monkeypatch):
    import io
    import subprocess
    from types import SimpleNamespace
    calls = []
    def wait(*, timeout):
        calls.append("wait")
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("synthetic", timeout)
    process = SimpleNamespace(stdin=io.StringIO(), stdout=io.StringIO(),
                              wait=wait, kill=lambda: calls.append("kill"), returncode=-9)
    session = lifecycle.Session.__new__(lifecycle.Session)
    session.process = process
    session.reader = SimpleNamespace(join=lambda **kwargs: calls.append("join"))
    with pytest.raises(RuntimeError, match="exit cleanly"):
        session.close()
    assert calls == ["wait", "kill", "wait", "join"]


def _assert_quality_lifecycle(workflow):
    assert "workflow_dispatch" in workflow.get("on", workflow.get(True, {}))
    desktop = workflow["jobs"]["desktop"]
    assert set(desktop["strategy"]["matrix"]["runner"]) == {
        "macos-latest", "windows-latest", "ubuntu-22.04"}
    assert not desktop.get("if") and not desktop.get("continue-on-error")
    assert desktop["defaults"]["run"] == {"working-directory": "desktop", "shell": "bash"}
    command = '''python ../scripts/validate_sidecar_lifecycle.py --target "$(rustc -vV | sed -n 's/^host: //p')" --output sidecar-lifecycle.json'''
    steps = desktop["steps"]
    gates = [step for step in steps if step.get("run") == command]
    assert len(gates) == 1
    gate = gates[0]
    assert not gate.get("if") and not gate.get("continue-on-error")
    assert gate.get("shell", "bash") == "bash"
    validation = next(step for step in steps if "validate_packaged_artifact.py" in step.get("run", ""))
    build = next(step for step in steps if step.get("run") == "npx tauri build")
    assert steps.index(validation) < steps.index(gate) < steps.index(build)
    uploads = [step for step in steps if step.get("with", {}).get("name") ==
               "quality-sidecar-lifecycle-${{ matrix.runner }}"]
    assert len(uploads) == 1
    assert uploads[0]["with"]["path"] == "desktop/sidecar-lifecycle.json"
    assert uploads[0]["with"]["if-no-files-found"] == "error"
    assert not uploads[0].get("continue-on-error") and not uploads[0].get("if")
    assert uploads[0]["uses"] == "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    assert steps.index(gate) < steps.index(uploads[0])
    privacy = workflow["jobs"]["showcase"]
    assert " ".join(privacy["if"].split()) == (
        "github.event_name == 'push' || github.event_name == 'workflow_dispatch' || "
        "github.event.pull_request.head.repo.full_name == github.repository")
    assert not privacy.get("continue-on-error")


def test_manual_quality_checks_all_platforms_without_skipping_privacy():
    import yaml
    root = Path(__file__).parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/quality.yml").read_text())
    _assert_quality_lifecycle(workflow)


@pytest.mark.parametrize("mutation", ["no-dispatch", "privacy-skip", "remove", "echo", "suppressed", "conditional", "wrong-report", "missing-report-ok"])
def test_quality_lifecycle_rejects_missing_or_ineffective_gates(mutation):
    import yaml
    root = Path(__file__).parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/quality.yml").read_text())
    desktop = workflow["jobs"]["desktop"]
    gate = next(step for step in desktop["steps"] if "validate_sidecar_lifecycle.py" in step.get("run", ""))
    upload = next(step for step in desktop["steps"] if "quality-sidecar-lifecycle" in step.get("with", {}).get("name", ""))
    if mutation == "no-dispatch":
        del workflow.get("on", workflow.get(True))["workflow_dispatch"]
    elif mutation == "privacy-skip":
        workflow["jobs"]["showcase"]["if"] = "github.event_name == 'push'"
    elif mutation == "remove":
        desktop["steps"].remove(gate)
    elif mutation == "echo":
        gate["run"] = "echo " + gate["run"]
    elif mutation == "suppressed":
        gate["continue-on-error"] = True
    elif mutation == "conditional":
        gate["if"] = "runner.os == 'macOS'"
    elif mutation == "wrong-report":
        upload["with"]["path"] = "sidecar-lifecycle.json"
    else:
        upload["with"]["if-no-files-found"] = "warn"
    with pytest.raises(AssertionError):
        _assert_quality_lifecycle(workflow)
