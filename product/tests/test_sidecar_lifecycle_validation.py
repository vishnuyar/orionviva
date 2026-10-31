"""The lifecycle check must detect loss, refused reopen and false version evidence."""
from pathlib import Path

import pytest

from scripts import validate_sidecar_lifecycle as lifecycle


def fixture_artifacts(tmp_path):
    baseline, candidate = tmp_path / "baseline", tmp_path / "candidate"
    baseline.write_bytes(b"baseline synthetic executable")
    candidate.write_bytes(b"candidate synthetic executable")
    return baseline, candidate


def sample_root(home):
    return home/'vault/versioned/sample-vaults/five-year-life-v1'/('a'*32)/'vault'


def fake_probe(executable, home, *, create, vault_root=None):
    vault = sample_root(home)
    if not create: assert vault_root == vault
    if create:
        import json
        vault.mkdir(parents=True)
        pointer = home/'vault/versioned/five-year-sample-active.json'
        pointer.write_text(json.dumps({'version':'five-year-life-v1','instance_id':'a'*32}))
        (vault / "raw").mkdir()
        (vault / "raw" / "document").write_bytes(b"synthetic encrypted original")
        (vault / "events.jsonl").write_bytes(b"synthetic encrypted ledger")
        (vault / "events.jsonl.head").write_bytes(b"synthetic authenticated head")
    else:
        assert (vault / "events.jsonl").is_file()
    return "synthetic-revision"


def test_roundtrip_reopens_without_recreating_and_cleans_profile(tmp_path, monkeypatch):
    seen = []
    def probe(executable, home, *, create, vault_root=None):
        seen.append((home, create, executable.read_bytes()))
        return fake_probe(executable, home, create=create, vault_root=vault_root)
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
    def probe(executable, home, *, create, vault_root=None):
        homes.append(home)
        revision = fake_probe(executable, home, create=create, vault_root=vault_root)
        if not create:
            if mutation == "refuse-open":
                raise RuntimeError("refused reopen")
            path = sample_root(home) / ("raw/document" if mutation == "delete-original" else "events.jsonl")
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
            (sample_root(Path(path).parent / "profile")/"events.jsonl").unlink()
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
        def ask(self, operation, payload=None, **kwargs):
            if operation == "bridge.handshake":
                return {"protocol": "2.1", "revision": "synthetic"}
            if operation == "viva.lifecycle.read":
                return {"origin": "packaged"}
            if operation in {"bridge.sample.prepare", "bridge.sample.status"}:
                return {'state':'ready','sample_version':'five-year-life-v1',
                        'completed_documents':794,'total_documents':794,'posted_documents':790,
                        'held_documents':4,'phase':'ready','message':'Prepared.'}
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
        session.frames.put(json.dumps({'protocol':'2.1','request_id':'lifecycle-1','event':'job.progress',
                                      'result':{'job_id':'synthetic','status':'progress','completed':0,'total':1}}))
    session.frames.put('{"protocol":"2.1","request_id":"lifecycle-1","ok":true,"result":{}}')
    original = json.loads
    def delayed(line, **kwargs):
        time.sleep(0.002)
        return original(line, **kwargs)
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


@pytest.mark.parametrize("windows_relative_paths", [False, True])
@pytest.mark.parametrize("canonical", [False, True])
def test_snapshot_uses_portable_names_and_real_file_digests(
        tmp_path, windows_relative_paths, canonical):
    import hashlib
    from pathlib import PureWindowsPath

    files = {
        "events.jsonl": b"synthetic encrypted ledger",
        "events.jsonl.head": b"synthetic authenticated head",
        "raw/nested/document": b"synthetic encrypted original",
        "read-model/cache": b"disposable projection",
    }
    for name, data in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    class WindowsRelativePath(type(tmp_path)):
        # Retain real host filesystem IO, but expose Windows relative spelling.
        def relative_to(self, *args, **kwargs):
            return PureWindowsPath(*super().relative_to(*args, **kwargs).parts)

    root = WindowsRelativePath(tmp_path) if windows_relative_paths else tmp_path
    if windows_relative_paths:
        assert str((root / "raw/nested/document").relative_to(root)) == (
            "raw\\nested\\document")
    expected = {name: hashlib.sha256(data).hexdigest()
                for name, data in files.items()
                if not canonical or not name.startswith("read-model/")}
    assert lifecycle.snapshot(root, canonical=canonical) == expected


def status_value(state='ready'):
    complete = 794 if state == 'ready' else 0
    return dict(state=state, sample_version='five-year-life-v1',
                completed_documents=complete, total_documents=794,
                posted_documents=complete, held_documents=0,
                phase=state if state in {'ready', 'failed'} else 'validating', message='Synthetic status.')


def test_preparation_polls_once_under_one_original_deadline(monkeypatch):
    calls=[]; clock=[0.0]
    monkeypatch.setattr(lifecycle.time, 'monotonic', lambda:clock[0])
    monkeypatch.setattr(lifecycle.time, 'sleep', lambda seconds:clock.__setitem__(0, clock[0]+seconds))
    def ask(operation, *, deadline):
        calls.append((operation, deadline))
        return status_value('ready' if len(calls) == 3 else 'preparing')
    assert lifecycle.prepare_sample(ask, deadline=90)['state'] == 'ready'
    assert [operation for operation, _ in calls] == ['bridge.sample.prepare','bridge.sample.status','bridge.sample.status']
    assert {deadline for _, deadline in calls} == {90}


@pytest.mark.parametrize('mutation', ['failed','missing','extra','bad-counter','wrong-version','ready-partial'])
def test_bad_preparation_status_fails_without_retry(mutation):
    status=status_value()
    if mutation == 'failed': status=status_value('failed')
    elif mutation == 'missing': del status['phase']
    elif mutation == 'extra': status['unknown']=True
    elif mutation == 'bad-counter': status['completed_documents']=True
    elif mutation == 'wrong-version': status['sample_version']='foreign'
    else: status['completed_documents']=status['posted_documents']=1
    calls=[]
    def ask(operation, *, deadline):
        calls.append(operation);return status
    import time
    with pytest.raises(RuntimeError): lifecycle.prepare_sample(ask, deadline=time.monotonic()+90)
    assert calls == ['bridge.sample.prepare']


def test_a_poll_cannot_restart_the_overall_preparation_deadline(monkeypatch):
    clock=[0.0];calls=[]
    monkeypatch.setattr(lifecycle.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(lifecycle.time,'sleep',lambda seconds:None)
    def ask(operation, *, deadline):
        calls.append((operation,deadline));clock[0]+=46
        return status_value('preparing')
    with pytest.raises(RuntimeError,match='timed out'):
        lifecycle.prepare_sample(ask,deadline=90)
    assert len(calls)==2 and {deadline for _,deadline in calls}=={90}


@pytest.mark.parametrize('mutation', ['extra','traversal','wrong-version','duplicate','oversize',
                                     'pointer-link','version-link','vault-link','missing-vault'])
def test_pointer_and_selected_root_fail_closed(tmp_path, mutation):
    import json
    home=tmp_path/'home';home.mkdir()
    fake_probe(None,home,create=True)
    pointer=home/'vault/versioned/five-year-sample-active.json'
    original=pointer.read_bytes();root=sample_root(home)
    if mutation == 'extra': pointer.write_text(json.dumps(dict(version='five-year-life-v1',instance_id='a'*32,extra=True)))
    elif mutation == 'traversal': pointer.write_text(json.dumps(dict(version='five-year-life-v1',instance_id='../foreign')))
    elif mutation == 'wrong-version': pointer.write_text(json.dumps(dict(version='foreign',instance_id='a'*32)))
    elif mutation == 'duplicate': pointer.write_text('{"version":"five-year-life-v1","version":"five-year-life-v1","instance_id":"'+'a'*32+'"}')
    elif mutation == 'oversize': pointer.write_bytes(b' '*513)
    elif mutation == 'pointer-link':
        copy=tmp_path/'foreign-pointer';copy.write_bytes(original);pointer.unlink();pointer.symlink_to(copy)
    elif mutation == 'version-link':
        version=root.parent.parent;foreign=tmp_path/'foreign-version';version.rename(foreign);version.symlink_to(foreign,target_is_directory=True)
    elif mutation == 'vault-link':
        foreign=tmp_path/'foreign-vault';root.rename(foreign);root.symlink_to(foreign,target_is_directory=True)
    else:
        lifecycle.shutil.rmtree(root)
    with pytest.raises((RuntimeError,ValueError,OSError)): lifecycle.resolve_sample_root(home)


def test_lifecycle_binds_initial_pointer_once_even_when_a_later_pointer_changes(tmp_path, monkeypatch):
    roots=[];resolves=[]
    original=lifecycle.resolve_sample_root
    def resolve(home):
        resolves.append(home);return original(home)
    def probe(executable,home,*,create,vault_root=None):
        result=fake_probe(executable,home,create=create,vault_root=vault_root)
        roots.append(vault_root)
        if not create:
            pointer=home/'vault/versioned/five-year-sample-active.json'
            pointer.write_text('{"version":"five-year-life-v1","instance_id":"'+'b'*32+'"}')
        return result
    monkeypatch.setattr(lifecycle,'resolve_sample_root',resolve)
    monkeypatch.setattr(lifecycle,'probe',probe)
    lifecycle.validate(*fixture_artifacts(tmp_path))
    assert len(resolves)==1
    assert roots[0] is None and len(set(roots[1:]))==1 and roots[1]==sample_root(resolves[0])


def test_enclosing_deadline_bounds_a_single_blocking_reply(tmp_path, monkeypatch):
    import subprocess,sys,time
    original=subprocess.Popen
    def launch(command,**kwargs):
        return original([sys.executable,'-c','import sys,time;sys.stdin.readline();time.sleep(30)'],**kwargs)
    monkeypatch.setattr(lifecycle.subprocess,'Popen',launch)
    session=lifecycle.Session(tmp_path/'fake',tmp_path,timeout=90)
    started=time.monotonic()
    try:
        with pytest.raises(RuntimeError,match='timed out'):
            session.ask('bridge.handshake',deadline=started+0.03)
        assert time.monotonic()-started<1
    finally:
        session.process.kill()
        with pytest.raises(RuntimeError,match='exit cleanly'):session.close()


@pytest.mark.parametrize('change',['wrong-request','wrong-protocol','malformed-progress','unknown-event','wrong-result','non-object'])
def test_only_correlated_well_formed_frames_are_accepted(change):
    import io,json,queue
    from types import SimpleNamespace
    session=lifecycle.Session.__new__(lifecycle.Session)
    session.process=SimpleNamespace(stdin=io.StringIO());session.frames=queue.Queue()
    session.number=0;session.timeout=1
    frame={'protocol':'2.1','request_id':'lifecycle-1','ok':True,'result':{}}
    if change=='wrong-request':frame['request_id']='foreign'
    elif change=='wrong-protocol':frame['protocol']='foreign'
    elif change=='wrong-result':frame['result']=[]
    elif change=='non-object':frame=[]
    else:
        frame={'protocol':'2.1','request_id':'lifecycle-1','event':'job.progress' if change=='malformed-progress' else 'unknown', 'result':{}}
    session.frames.put(json.dumps(frame))
    with pytest.raises(RuntimeError):session.ask('bridge.handshake')


def test_multibyte_frame_cannot_bypass_the_byte_bound(monkeypatch):
    import io,queue
    from types import SimpleNamespace
    session=lifecycle.Session.__new__(lifecycle.Session)
    session.process=SimpleNamespace(stdout=io.StringIO('ééé\n'))
    session.frames=queue.Queue();session.reader_error=None
    monkeypatch.setattr(lifecycle,'MAX_FRAME_BYTES',4)
    session._read()
    assert isinstance(session.reader_error,RuntimeError)
    assert 'oversized' in str(session.reader_error)
    assert session.frames.get_nowait() is None


def test_blocked_stdin_write_respects_enclosing_deadline_and_stops_only_owned_child(tmp_path, monkeypatch):
    import subprocess,sys,time
    original=subprocess.Popen
    def launch(command,**kwargs):
        return original([sys.executable,'-c','import time;time.sleep(30)'],**kwargs)
    monkeypatch.setattr(lifecycle.subprocess,'Popen',launch)
    session=lifecycle.Session(tmp_path/'fake',tmp_path,timeout=90)
    started=time.monotonic()
    with pytest.raises(RuntimeError,match='timed out writing'):
        session.ask('bridge.handshake',{'synthetic':'x'*1_000_000},deadline=started+0.05)
    assert time.monotonic()-started<2
    with pytest.raises(RuntimeError,match='exit cleanly'):session.close()
    assert session.process.poll() is not None


def test_duplicate_frame_fields_are_rejected():
    import io,queue
    from types import SimpleNamespace
    session=lifecycle.Session.__new__(lifecycle.Session)
    session.process=SimpleNamespace(stdin=io.StringIO());session.frames=queue.Queue()
    session.number=0;session.timeout=1
    session.frames.put('{"protocol":"foreign","protocol":"2.1","request_id":"lifecycle-1","ok":true,"result":{}}')
    with pytest.raises(RuntimeError,match='duplicate'):session.ask('bridge.handshake')


def test_canonical_snapshot_rejects_a_linked_raw_root(tmp_path):
    root=tmp_path/'vault';root.mkdir()
    (root/'events.jsonl').write_bytes(b'synthetic canonical ledger')
    (root/'events.jsonl.head').write_bytes(b'synthetic canonical head')
    foreign=tmp_path/'foreign';foreign.mkdir()
    (foreign/'raw-header.json').write_bytes(b'synthetic header')
    (root/'raw').symlink_to(foreign,target_is_directory=True)
    with pytest.raises(RuntimeError,match='ordinary'):lifecycle.snapshot(root,canonical=True)
