"""Real process interruption and exact-boundary publication recovery."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

import pytest

from viva.sql_authority import SQLAuthority, AuthorityError, IntegrityError
from viva.sql_authority.application import ApplicationSQLAuthority
from viva.sql_authority.application_io import RecoveryRequired, Busy
from test_sql_application_history import _accepted_statement


pytestmark = pytest.mark.production_kdf


def _process(program, payload, root, *, timeout=45):
    request = dict(payload, import_paths=[str(Path(path).resolve()) for path in sys.path])
    prefix = "import json, sys\nrequest=json.loads(sys.stdin.read())\nsys.path[:]=request['import_paths']\n"
    return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", prefix + program],
                          input=json.dumps(request), text=True, capture_output=True,
                          env={}, cwd=root.parent, timeout=timeout, check=False)


_INTERRUPTED_TRANSACTION = """
import hashlib
import os
from pathlib import Path
import signal
import stat
from viva.sql_authority import SQLAuthority
from viva.sql_authority import application_io as io
from test_sql_authority_bank import ingest

root = Path(request["root"])
doc_id = hashlib.sha256(b"synthetic process forward source").hexdigest()
owner = SQLAuthority.open(root, request["passphrase"], verification="complete", application=True)
armed = False
rollback_injected = False
before_database = None

def stop(target):
    print(json.dumps({"interrupted": target, "actual_process": True,
                      "native_cache_spill": target == "before_audit"}), flush=True)
    if request["termination"] == "sigkill":
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(73)

def fault(point):
    global armed, rollback_injected, before_database
    pending = owner._pending
    if pending is None or pending[1]["kind"] != "transaction":
        return
    if point == "after_initial_intent":
        item = owner._engine._row("items", "doc_id=?", (doc_id,))
        if item and item["state"] == "staged":
            armed = True
            owner._engine._db.execute("PRAGMA cache_size=1")
            owner._engine._db.execute("PRAGMA cache_spill=ON")
            before_database = hashlib.sha256((root / "sql" / "authority.db").read_bytes()).hexdigest()
    if not armed:
        return
    if request.get("abort") and point == "after_prepared_intent" and not rollback_injected:
        rollback_injected = True
        raise RuntimeError("injected rollback after exact normal preparation")
    target = request["point"]
    selected = point == target
    if target == "abort_file":
        selected = point == "after_prepared_file" and (pending[0] / "prepared-abort.json").exists()
    if not selected:
        return
    if target == "before_audit":
        assert (root / "sql" / "authority.db-journal").is_file()
        assert (root / "sql" / "authority.db-journal").stat().st_size > 0
        assert hashlib.sha256((root / "sql" / "authority.db").read_bytes()).hexdigest() != before_database
    stop(target)

owner._fault = fault
owner._engine._fault = fault
original_fsync, original_replace = os.fsync, os.replace
original_open = os.open
opened_names = {}
def observed_open(path, *args, **kwargs):
    descriptor = original_open(path, *args, **kwargs)
    opened_names[descriptor] = str(path)
    return descriptor
def interrupted_fsync(descriptor):
    target = request["point"]
    pending = owner._pending
    if armed and owner._committed and target == "immutable_rename_before_directory_fsync" and stat.S_ISDIR(os.fstat(descriptor).st_mode):
        sequence = pending[1]["prior_terminal"]["sequence"] + 1
        final = root / "history" / (str(sequence).zfill(20) + ".json")
        terminal = json.loads((root / "terminal.json").read_text())
        if final.exists() and terminal["sequence"] == sequence - 1:
            stop(target)
    original_fsync(descriptor)
    if target == "initial_intent_file_fsync" and pending and pending[1]["kind"] == "transaction" and opened_names.get(descriptor) == "intent.next":
        item = owner._engine._row("items", "doc_id=?", (doc_id,))
        if item and item["state"] == "staged":
            stop(target)
    if armed:
        directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        if target == "prepared_file_fsync" and not directory:
            stop(target)
        if target == "prepared_directory_fsync" and directory:
            stop(target)
def interrupted_replace(source, destination, **kwargs):
    original_replace(source, destination, **kwargs)
    if armed and request["point"] == "prepared_intent_rename" and destination == "intent.json":
        stop(request["point"])
    if armed and request["point"] == "terminal_rename" and destination == "terminal.json":
        stop(request["point"])
os.open = observed_open
os.fsync = interrupted_fsync
os.replace = interrupted_replace
try:
    ingest(owner, b"synthetic process forward source", opening="90", closing="80",
           start="2026-01-31", end="2026-02-28")
finally:
    owner.close()
raise AssertionError("selected persistent interruption was not reached")
"""


@pytest.mark.parametrize("point,expected_balance", [
    ("after_initial_intent", "90"), ("before_audit", "90"), ("before_commit", "90"),
    ("after_prepared_file", "90"), ("after_prepared_intent", "90"),
    ("after_sql_commit", "80"), ("after_history_publication", "80"),
    ("after_terminal_publication", "80"), ("after_published_intent", "80"),
    ("after_intent_cleanup", "80"), ("after_pending_cleanup", "80"),
    ("initial_intent_file_fsync", "90"), ("prepared_file_fsync", "90"),
    ("prepared_directory_fsync", "90"), ("prepared_intent_rename", "90"),
    ("immutable_rename_before_directory_fsync", "80"), ("terminal_rename", "80"),
])
@pytest.mark.parametrize("termination", ["exit", "sigkill"])
def test_actual_process_transaction_interruption_has_one_recoverable_outcome(tmp_path, point, expected_balance, termination):
    if termination == "sigkill" and os.name == "nt":
        pytest.skip("native SIGKILL is unavailable on this target")
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        trusted = owner.terminal
    completed = _process(_INTERRUPTED_TRANSACTION, dict(root=str(root), passphrase=passphrase,
                          point=point, termination=termination), root)
    assert completed.returncode == (-9 if termination == "sigkill" else 73), completed.stderr
    event = json.loads(completed.stdout)
    assert event["interrupted"] == point and event["actual_process"] is True
    if point == "before_audit":
        assert event["native_cache_spill"] is True
    pending = list((root / "pending").iterdir())
    if pending:
        with pytest.raises(RecoveryRequired):
            SQLAuthority.open(root, passphrase, verification="complete", application=True)
        with pytest.raises(RecoveryRequired):
            ApplicationSQLAuthority.verify_live_chain(root)
    result = ApplicationSQLAuthority.recover(root, passphrase, expected_prefix=trusted)
    assert result["status"] == "ready"
    assert result["outcome"] in {"committed", "aborted", "cleanup_only", "already_ready"}
    assert not list((root / "pending").iterdir())
    with SQLAuthority.open(root, passphrase, verification="complete", application=True) as owner:
        assert owner.account(accepted.account_id)["running_balance"] == expected_balance
        expected_count = 2 if expected_balance == "80" else 1
        assert len(owner.transactions(accepted.account_id)) == expected_count
        head, terminal = owner.head, owner.terminal
        duplicate_recovery = ApplicationSQLAuthority.recover(root, passphrase, expected_prefix=trusted)
        assert duplicate_recovery["outcome"] == "already_ready"
        assert owner.head == head and owner.terminal == terminal
        assert owner.verify()["counts"]["transactions"] == expected_count
    assert ApplicationSQLAuthority.verify_live_chain(root, expected_terminal=result["terminal"])["structural"] is True


@pytest.mark.parametrize("point", ["abort_file", "after_abort_prepared_intent", "after_prepared_cleanup", "after_intent_cleanup"])
def test_interrupted_abort_preserves_original_proposed_bytes_once(tmp_path, point):
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        trusted = owner.terminal
    completed = _process(_INTERRUPTED_TRANSACTION, dict(root=str(root), passphrase=passphrase,
                          point=point, termination="exit", abort=True), root)
    assert completed.returncode == 73, completed.stderr
    assert json.loads(completed.stdout)["interrupted"] == point
    result = ApplicationSQLAuthority.recover(root, passphrase, expected_prefix=trusted)
    assert result["outcome"] in {"aborted", "cleanup_only"}
    with SQLAuthority.open(root, passphrase, verification="complete", application=True) as owner:
        assert owner.account(accepted.account_id)["running_balance"] == "90"
        assert len(owner.transactions(accepted.account_id)) == 1
        _, records, payloads = owner._history.scan()
        aborts = [payload["body"] for record, payload in zip(records, payloads) if record["kind"] == "interrupted_abort"]
        assert len(aborts) == 1
        assert aborts[0]["superseded_publication"] is not None
        from viva.sql_authority.application_history import digest
        assert digest(aborts[0]["superseded_publication"].encode()) == aborts[0]["prepared_sha256"]


@pytest.mark.parametrize("point", ["after_initial_intent", "after_original_preparation", "after_original_publication", "after_prepared_file", "after_prepared_intent", "after_history_publication", "after_terminal_publication", "after_published_intent", "after_intent_cleanup"])
def test_actual_process_capture_recovers_custody_without_financial_acceptance(tmp_path, point):
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True):
        pass
    program = """
import hashlib, os
from pathlib import Path
from viva.sql_authority import SQLAuthority
from test_sql_authority_bank import ingest
root=Path(request["root"])
owner=SQLAuthority.open(root, request["passphrase"], verification="complete", application=True)
def fault(point):
    if owner._pending and owner._pending[1]["kind"] == "capture" and point == request["point"]:
        print(json.dumps({"interrupted": point}), flush=True)
        os._exit(73)
owner._fault=fault
ingest(owner)
raise AssertionError("capture fault point not reached")
"""
    completed = _process(program, dict(root=str(root), passphrase=passphrase, point=point), root)
    assert completed.returncode == 73, completed.stderr
    assert json.loads(completed.stdout)["interrupted"] == point
    result = ApplicationSQLAuthority.recover(root, passphrase)
    assert result["outcome"] in {"custody", "aborted", "cleanup_only"}
    with SQLAuthority.open(root, passphrase, verification="complete", application=True) as owner:
        assert owner.verify()["counts"]["transactions"] == 0
        if point != "after_initial_intent":
            import hashlib
            assert owner.original(hashlib.sha256(b"synthetic source").hexdigest()) == b"synthetic source"


def test_independent_process_root_contention_and_lock_replacement_refuse(tmp_path):
    import time
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    program = """
from pathlib import Path
from viva.sql_authority.application import ApplicationSQLAuthority
from viva.sql_authority.application_io import Busy
try:
    ApplicationSQLAuthority.verify_live_chain(Path(request["root"]))
except Busy:
    print(json.dumps({"busy": True}))
else:
    raise AssertionError("held native root lock was bypassed")
"""
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        with owner.operation("phase"):
            started = time.monotonic()
            completed = _process(program, dict(root=str(root)), root, timeout=12)
            elapsed = time.monotonic() - started
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == {"busy": True}
        assert 4.5 <= elapsed < 12
        lock = root / "application.lock"
        old_lock = root / "old-lock"
        lock.rename(old_lock)
        lock.touch(mode=0o600)
        try:
            with pytest.raises(IntegrityError, match="lock ownership"):
                owner.account(accepted.account_id)
        finally:
            lock.unlink()
            old_lock.rename(lock)


def test_same_process_independent_handles_do_not_reenter_each_other(tmp_path):
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as first:
        accepted = _accepted_statement(first)
        with SQLAuthority.open(root, passphrase, verification="complete", application=True) as second:
            with first.operation("phase"):
                with pytest.raises(Busy):
                    second.account(accepted.account_id)
            assert second.account(accepted.account_id)["running_balance"] == "90"


@pytest.mark.parametrize("member", ["unexpected", "intent.next", "terminal.next", "journal_without_intent"])
def test_unknown_interruption_artifacts_never_get_auto_adopted(tmp_path, member):
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        trusted = owner.terminal
    if member == "intent.next":
        directory = root / "pending" / ("f" * 64)
        directory.mkdir(mode=0o700)
        path = directory / member
    elif member == "journal_without_intent":
        path = root / "sql" / "authority.db-journal"
    else:
        path = root / member
    path.write_bytes(b"incomplete synthetic evidence")
    path.chmod(0o600)
    evidence = path.read_bytes()
    with pytest.raises((AuthorityError, OSError)):
        SQLAuthority.open(root, passphrase, verification="complete", application=True)
    with pytest.raises((AuthorityError, OSError)):
        ApplicationSQLAuthority.recover(root, passphrase, expected_prefix=trusted)
    assert path.read_bytes() == evidence


@pytest.mark.parametrize("point,ready", [
    ("application.next", False), ("authority.next", False), ("after_engine_creation", False),
    ("prepared-publication.json", True), ("after_prepared_intent", True),
    ("after_history_publication", True), ("after_terminal_publication", True),
    ("after_published_intent", True), ("after_intent_cleanup", True),
])
def test_creation_process_interruption_never_invents_genesis(tmp_path, point, ready):
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    program = """
import os
from pathlib import Path
from viva.sql_authority import SQLAuthority
from viva.sql_authority.application import ApplicationSQLAuthority
from viva.sql_authority import application_io as io

target=request["point"]
original_init=ApplicationSQLAuthority.__init__
def interrupted_init(self,*args,**kwargs):
    original_init(self,*args,**kwargs)
    def fault(point):
        if point == target:
            print(json.dumps({"interrupted": target}),flush=True)
            os._exit(73)
    self._fault=fault
ApplicationSQLAuthority.__init__=interrupted_init
original_write=io.exclusive_write
def interrupted_write(path,data):
    original_write(path,data)
    if path.name == target:
        print(json.dumps({"interrupted": target}),flush=True)
        os._exit(73)
io.exclusive_write=interrupted_write
original_replace_held=io._replace_held
def interrupted_replace(path, temporary, *args, **kwargs):
    if temporary == target:
        print(json.dumps({"interrupted": target}),flush=True)
        os._exit(73)
    return original_replace_held(path, temporary, *args, **kwargs)
io._replace_held=interrupted_replace
SQLAuthority.create(Path(request["root"]),request["passphrase"],verification="complete",application=True)
raise AssertionError("creation fault point not reached")
"""
    completed = _process(program, dict(root=str(root), passphrase=passphrase, point=point), root)
    assert completed.returncode == 73, completed.stderr
    assert json.loads(completed.stdout)["interrupted"] == point
    if ready:
        result = ApplicationSQLAuthority.recover(root, passphrase)
        assert result["outcome"] in {"genesis", "cleanup_only"}
        with SQLAuthority.open(root, passphrase, verification="complete", application=True) as owner:
            assert owner.head == {"revision": 0, "head": "0" * 64}
            assert owner.verify()["counts"]["accounts"] == 0
            assert owner.terminal["sequence"] == 1
    else:
        evidence = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        with pytest.raises((AuthorityError, OSError)):
            ApplicationSQLAuthority.recover(root, passphrase)
        assert evidence == {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_native_mutable_replace_uses_one_parent_descriptor_and_exact_preparation(tmp_path, monkeypatch):
    from viva.sql_authority import application_io as io
    parent = io.mkdir(tmp_path.resolve() / "owned")
    target = parent / "terminal.json"
    io.exclusive_write(target, b"synthetic old opaque head")
    calls = []
    original = os.replace
    def observed(source, destination, **kwargs):
        assert source == "terminal.next" and destination == "terminal.json"
        assert kwargs["src_dir_fd"] == kwargs["dst_dir_fd"]
        descriptor = kwargs["src_dir_fd"]
        info = os.fstat(descriptor)
        prepared = os.stat(source, dir_fd=descriptor, follow_symlinks=False)
        calls.append((info.st_dev, info.st_ino, prepared.st_dev, prepared.st_ino))
        return original(source, destination, **kwargs)
    monkeypatch.setattr(os, "replace", observed)
    io.replace_head(target, b"synthetic exact successor", temporary="terminal.next")
    assert len(calls) == 1
    actual = target.stat()
    assert calls[0][:2] == (parent.stat().st_dev, parent.stat().st_ino)
    assert calls[0][2:] == (actual.st_dev, actual.st_ino)
    assert target.read_bytes() == b"synthetic exact successor"
    assert not (parent / "terminal.next").exists()


def test_native_mutable_replace_cannot_write_into_substituted_parent(tmp_path, monkeypatch):
    from viva.sql_authority import application_io as io
    parent = io.mkdir(tmp_path.resolve() / "owned")
    retained = tmp_path.resolve() / "retained-owned-directory"
    io.exclusive_write(parent / "terminal.json", b"synthetic old opaque head")
    original = os.replace
    calls = []
    def substituted(source, destination, **kwargs):
        calls.append((source, destination))
        assert kwargs["src_dir_fd"] == kwargs["dst_dir_fd"]
        parent.rename(retained)
        parent.mkdir(mode=0o700)
        sentinel = parent / "terminal.json"
        sentinel.write_bytes(b"synthetic substitute must survive")
        sentinel.chmod(0o600)
        return original(source, destination, **kwargs)
    monkeypatch.setattr(os, "replace", substituted)
    with pytest.raises(IntegrityError, match="parent|directory"):
        io.replace_head(parent / "terminal.json", b"synthetic exact successor", temporary="terminal.next")
    assert calls == [("terminal.next", "terminal.json")]
    assert (parent / "terminal.json").read_bytes() == b"synthetic substitute must survive"
    assert {path.name for path in parent.iterdir()} == {"terminal.json"}
    assert (retained / "terminal.json").read_bytes() == b"synthetic exact successor"
    assert not (retained / "terminal.next").exists()


def test_unsupported_descriptor_replace_has_no_pathname_fallback(tmp_path, monkeypatch):
    from viva.sql_authority import application_io as io
    parent = io.mkdir(tmp_path.resolve() / "owned")
    io.exclusive_write(parent / "terminal.json", b"synthetic old opaque head")
    calls = []
    def unsupported(source, destination, **kwargs):
        calls.append((source, destination, dict(kwargs)))
        assert set(kwargs) == {"src_dir_fd", "dst_dir_fd"}
        assert kwargs["src_dir_fd"] == kwargs["dst_dir_fd"]
        raise NotImplementedError("injected unsupported descriptor operation")
    monkeypatch.setattr(os, "replace", unsupported)
    with pytest.raises(NotImplementedError, match="unsupported descriptor"):
        io.replace_head(parent / "terminal.json", b"synthetic exact successor", temporary="terminal.next")
    assert len(calls) == 1
    assert (parent / "terminal.json").read_bytes() == b"synthetic old opaque head"
    assert (parent / "terminal.next").read_bytes() == b"synthetic exact successor"


@pytest.mark.parametrize("temporary", ["../terminal.next", "/terminal.next", ".", "unknown.next", "intent.next"])
def test_mutable_head_accepts_only_protocol_fixed_basename_pair(tmp_path, temporary):
    from viva.sql_authority import application_io as io
    parent = io.mkdir(tmp_path.resolve() / "owned")
    with pytest.raises(AuthorityError, match="mutable application member"):
        io.replace_head(parent / "terminal.json", b"synthetic successor", temporary=temporary)
    assert not list(parent.iterdir())


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "public_mode", "directory", "fifo"])
def test_mutable_target_safety_is_checked_without_following(tmp_path, unsafe):
    from viva.sql_authority import application_io as io
    parent = io.mkdir(tmp_path.resolve() / "owned")
    target = parent / "terminal.json"
    retained = tmp_path.resolve() / "retained"
    if unsafe in {"symlink", "hardlink"}:
        retained.write_bytes(b"synthetic unrelated must survive")
        retained.chmod(0o600)
        if unsafe == "symlink":
            target.symlink_to(retained)
        else:
            os.link(retained, target)
    elif unsafe == "public_mode":
        target.write_bytes(b"synthetic old")
        target.chmod(0o644)
    elif unsafe == "directory":
        target.mkdir(mode=0o700)
    else:
        os.mkfifo(target, 0o600)
    with pytest.raises(AuthorityError):
        io.replace_head(target, b"synthetic successor", temporary="terminal.next")
    assert (parent / "terminal.next").read_bytes() == b"synthetic successor"
    if retained.exists():
        assert retained.read_bytes() == b"synthetic unrelated must survive"


@pytest.mark.parametrize("failure", ["file_fsync", "replace", "directory_fsync"])
def test_injected_mutable_publication_failure_preserves_uncertain_artifacts(tmp_path, monkeypatch, failure):
    import stat
    from viva.sql_authority import application_io as io
    parent = io.mkdir(tmp_path.resolve() / "owned")
    target = parent / "terminal.json"
    io.exclusive_write(target, b"synthetic old opaque head")
    original_fsync, original_replace = os.fsync, os.replace
    failed = []
    def injected_fsync(descriptor):
        directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        selected = (failure == "directory_fsync" and directory) or (failure == "file_fsync" and not directory)
        if selected and not failed:
            failed.append(failure)
            raise OSError("injected mutable flush failure")
        return original_fsync(descriptor)
    def injected_replace(*args, **kwargs):
        if failure == "replace":
            failed.append(failure)
            raise OSError("injected mutable rename failure")
        return original_replace(*args, **kwargs)
    monkeypatch.setattr(os, "fsync", injected_fsync)
    monkeypatch.setattr(os, "replace", injected_replace)
    with pytest.raises(OSError, match="injected mutable"):
        io.replace_head(target, b"synthetic exact successor", temporary="terminal.next")
    assert failed == [failure]
    if failure == "directory_fsync":
        assert target.read_bytes() == b"synthetic exact successor"
        assert not (parent / "terminal.next").exists()
    else:
        assert target.read_bytes() == b"synthetic old opaque head"
        assert (parent / "terminal.next").read_bytes() == b"synthetic exact successor"


def test_existing_mutable_draft_must_equal_authenticated_successor(tmp_path):
    from viva.sql_authority import application_io as io
    parent = io.mkdir(tmp_path.resolve() / "owned")
    io.exclusive_write(parent / "terminal.json", b"synthetic old opaque head")
    io.exclusive_write(parent / "terminal.next", b"synthetic changed draft")
    with pytest.raises(IntegrityError, match="after authentication"):
        io.finish_head(parent / "terminal.json", temporary="terminal.next", expected=b"synthetic authenticated successor")
    assert (parent / "terminal.json").read_bytes() == b"synthetic old opaque head"
    assert (parent / "terminal.next").read_bytes() == b"synthetic changed draft"


def test_injected_windows_capability_gate_refuses_before_application_effects(tmp_path, monkeypatch):
    """Capability-gate coverage only, not native Windows qualification."""
    from types import SimpleNamespace
    from viva.sql_authority import application_io as io
    root = tmp_path.resolve() / "untouched"
    monkeypatch.setattr(io, "os", SimpleNamespace(name="nt"))
    with pytest.raises(AuthorityError, match="not qualified"):
        SQLAuthority.create(root, secrets.token_urlsafe(32), verification="complete", application=True)
    assert not root.exists()


_PHASE_INTERRUPTED_TRANSACTION = """
import hashlib, os, signal
from pathlib import Path
from viva.sql_authority import SQLAuthority
from viva.sql_authority import application_io as io
from test_sql_authority_bank import ingest
root = Path(request["root"])
owner = SQLAuthority.open(root, request["passphrase"], verification="complete", application=True)
value = request["user_version"]
assert type(value) is int and -2147483648 <= value <= 2147483647
owner._engine._db.execute("PRAGMA main.user_version=" + str(value))
assert owner._engine._db.execute("PRAGMA main.user_version").fetchall() == [(value,)]
doc_id = hashlib.sha256(b"synthetic process forward source").hexdigest()
armed = False
def fault(point):
    global armed
    pending = owner._pending
    if pending is None or pending[1]["kind"] != "transaction":
        return
    if point == "after_initial_intent":
        item = owner._engine._row("items", "doc_id=?", (doc_id,))
        if item and item["state"] == "staged":
            armed = True
            owner._engine._db.execute("PRAGMA cache_size=1")
            owner._engine._db.execute("PRAGMA cache_spill=ON")
    selected = "after_initial_intent" if request["stage"] == "initial" else "after_prepared_intent"
    if not armed or point != selected:
        return
    outer, inner = owner._history.read_intent(io.read(pending[0] / "intent.json"))
    members = sorted(member.name for member in pending[0].iterdir())
    assert outer["stage"] == request["stage"] and inner["issued"]["kind"] == "transaction"
    assert members == (["intent.json"] if request["stage"] == "initial" else ["intent.json", "prepared-publication.json"])
    print(json.dumps({"authenticated_stage": outer["stage"], "kind": inner["issued"]["kind"],
                      "members": members, "journal": (root / "sql" / "authority.db-journal").exists(),
                      "user_version": value, "prior_terminal": inner["issued"]["prior_terminal"],
                      "prior_sql": inner["issued"]["prior_sql"]}), flush=True)
    if request["termination"] == "sigkill":
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(73)
owner._fault = owner._engine._fault = fault
ingest(owner, b"synthetic process forward source", opening="90", closing="80",
       start="2026-01-31", end="2026-02-28")
raise AssertionError("authenticated phase was not reached")
"""


def _phase_old_fixture(tmp_path, *, stage="prepared", termination="exit", user_version=0):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        trusted, head = owner.terminal, owner.head
        postings = owner.postings(accepted.doc_id)
        original = owner.original(accepted.doc_id)
    result = _process(_PHASE_INTERRUPTED_TRANSACTION,
                      dict(root=str(root), passphrase=passphrase, stage=stage,
                           termination=termination, user_version=user_version), root)
    assert result.returncode == (-9 if termination == "sigkill" else 73), result.stderr
    observed = json.loads(result.stdout)
    assert observed["authenticated_stage"] == stage and observed["kind"] == "transaction"
    assert observed["members"] == (["intent.json"] if stage == "initial" else ["intent.json", "prepared-publication.json"])
    assert observed["user_version"] == user_version
    assert observed["prior_terminal"]["root_id"] == trusted["root_id"]
    assert observed["prior_terminal"]["sequence"] >= trusted["sequence"]
    assert observed["prior_sql"]["revision"] >= head["revision"]
    return root, passphrase, accepted, observed["prior_terminal"], observed["prior_sql"], postings, original, observed


def _pending_bytes(root):
    pending = list((root / "pending").iterdir())
    assert len(pending) == 1
    return {member.name: member.read_bytes() for member in pending[0].iterdir()}


def _assert_one_old_abort(fixture, before, user_version):
    root, passphrase, accepted, trusted, head, postings, original, _observed = fixture
    result = ApplicationSQLAuthority.recover(root, passphrase, expected_prefix=trusted)
    assert result["outcome"] == "aborted"
    assert not (root / "sql" / "authority.db-journal").exists()
    assert not list((root / "pending").iterdir())
    with SQLAuthority.open(root, passphrase, verification="complete", application=True) as owner:
        assert owner.head == head
        assert owner.account(accepted.account_id)["running_balance"] == "90"
        assert len(owner.transactions(accepted.account_id)) == 1
        assert owner.postings(accepted.doc_id) == postings
        assert owner.original(accepted.doc_id) == original
        assert owner._engine._db.execute("PRAGMA main.user_version").fetchall() == [(user_version,)]
        assert owner.verify()["counts"]["transactions"] == 1
        _terminal, records, payloads = owner._history.scan()
        aborted = [payload for record, payload in zip(records, payloads) if record["kind"] == "interrupted_abort"]
        assert len(aborted) == 1
        proposed = aborted[0]["body"]["superseded_publication"]
        if "prepared-publication.json" in before:
            assert proposed.encode() == before["prepared-publication.json"]
        else:
            assert proposed is None
        terminal = owner.terminal
        assert terminal["sequence"] == trusted["sequence"] + 1
        assert records[-1]["previous_hash"] == trusted["head"]
        assert aborted[0]["issued"]["prior_sql"] == head
    assert ApplicationSQLAuthority.recover(root, passphrase, expected_prefix=trusted)["outcome"] == "already_ready"
    from test_sql_application_history import _fresh_keyless_check
    assert _fresh_keyless_check(root, terminal)["result"]["structural"] is True


@pytest.mark.parametrize("stage", ["initial", "prepared"])
@pytest.mark.parametrize("termination", ["exit", "sigkill"])
def test_native_authenticated_phase_old_abort_keeps_financial_boundary(tmp_path, monkeypatch, stage, termination):
    if termination == "sigkill" and os.name == "nt":
        pytest.skip("native SIGKILL is unavailable on this target")
    fixture = _phase_old_fixture(tmp_path, stage=stage, termination=termination)
    root, passphrase, *_rest = fixture
    before = _pending_bytes(root)
    observed = fixture[-1]
    if stage == "prepared":
        assert observed["journal"] is True
    with pytest.raises(RecoveryRequired):
        SQLAuthority.open(root, passphrase, verification="complete", application=True)
    writes = []
    opened = ApplicationSQLAuthority._open_engine
    def instrument(owner, *args, **kwargs):
        result = opened(owner, *args, **kwargs)
        owner._engine._db = _MaintenanceConnection(owner._engine._db, writes=writes)
        return result
    monkeypatch.setattr(ApplicationSQLAuthority, "_open_engine", instrument)
    _assert_one_old_abort(fixture, before, 0)
    assert writes == (["PRAGMA main.user_version=0"] if observed["journal"] else [])


@pytest.mark.parametrize("user_version", [17, -2147483648, 2147483647])
def test_native_old_journal_preserves_nonzero_signed_header(tmp_path, monkeypatch, user_version):
    fixture = _phase_old_fixture(tmp_path, user_version=user_version)
    assert fixture[-1]["journal"] is True
    before = _pending_bytes(fixture[0])
    writes = []
    opened = ApplicationSQLAuthority._open_engine
    def instrument(owner, *args, **kwargs):
        result = opened(owner, *args, **kwargs)
        owner._engine._db = _MaintenanceConnection(owner._engine._db, writes=writes)
        return result
    monkeypatch.setattr(ApplicationSQLAuthority, "_open_engine", instrument)
    _assert_one_old_abort(fixture, before, user_version)
    assert writes == ["PRAGMA main.user_version=" + str(user_version)]


class _MaintenanceRows:
    def __init__(self, rows):
        self.rows = rows
    def fetchall(self):
        return self.rows


class _MaintenanceConnection:
    """Labeled query/fault injection around the real native connection."""
    def __init__(self, connection, *, writes=None, header=None, fault=None):
        self.connection, self.writes = connection, [] if writes is None else writes
        self.header, self.fault, self.assigned = header, fault, False
        self.rollback_count = 0
        self.commit_count = 0
    def __getattr__(self, name):
        return getattr(self.connection, name)
    def execute(self, sql, *args):
        if sql == "PRAGMA main.user_version" and self.header is not None:
            return _MaintenanceRows(self.header)
        if sql.startswith("PRAGMA main.user_version="):
            self.writes.append(sql)
            if self.fault == "assignment":
                raise OSError("labeled assignment refusal")
            self.assigned = True
        if sql == "COMMIT" and self.assigned:
            self.commit_count += 1
            if self.fault == "commit":
                raise OSError("labeled commit refusal")
        if sql == "ROLLBACK":
            self.rollback_count += 1
        return self.connection.execute(sql, *args)


@pytest.mark.parametrize("rows", [[], [(True,)], [("0",)], [(2147483648,)], [(-2147483649,)], [(0, 1)], [(0,), (0,)]])
def test_labeled_malformed_header_refuses_before_assignment_preserving_pending(tmp_path, monkeypatch, rows):
    fixture = _phase_old_fixture(tmp_path)
    root, passphrase, *_rest = fixture
    before = _pending_bytes(root)
    proxies = []
    opened = ApplicationSQLAuthority._open_engine
    def instrument(owner, *args, **kwargs):
        result = opened(owner, *args, **kwargs)
        proxy = _MaintenanceConnection(owner._engine._db, header=rows)
        owner._engine._db = proxy
        proxies.append(proxy)
        return result
    monkeypatch.setattr(ApplicationSQLAuthority, "_open_engine", instrument)
    with pytest.raises(IntegrityError, match="header integer"):
        ApplicationSQLAuthority.recover(root, passphrase)
    assert proxies and proxies[0].writes == [] and proxies[0].rollback_count == 1
    assert _pending_bytes(root) == before
    assert not (root / "terminal.next").exists()


@pytest.mark.parametrize("mutation", ["missing", "corrupt", "foreign", "unknown"])
def test_old_journal_refuses_changed_preparation_before_native_assignment(tmp_path, monkeypatch, mutation):
    from viva.sql_authority import application_history as history
    from viva.sql_authority import application_io as io
    fixture = _phase_old_fixture(tmp_path)
    root, passphrase, *_rest = fixture
    path = next((root / "pending").iterdir())
    prepared = path / "prepared-publication.json"
    if mutation == "missing":
        prepared.unlink()
    elif mutation == "corrupt":
        data = prepared.read_bytes()
        prepared.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    elif mutation == "foreign":
        foreign = _phase_old_fixture(tmp_path / "foreign")
        prepared.write_bytes(next((foreign[0] / "pending").iterdir()).joinpath("prepared-publication.json").read_bytes())
    else:
        io.exclusive_write(path / "unknown.json", history.encoded({"synthetic": "unknown"}))
    before = _pending_bytes(root)
    writes = []
    opened = ApplicationSQLAuthority._open_engine
    def instrument(owner, *args, **kwargs):
        result = opened(owner, *args, **kwargs)
        owner._engine._db = _MaintenanceConnection(owner._engine._db, writes=writes)
        return result
    monkeypatch.setattr(ApplicationSQLAuthority, "_open_engine", instrument)
    with pytest.raises((AuthorityError, IntegrityError, RecoveryRequired, ValueError)):
        ApplicationSQLAuthority.recover(root, passphrase)
    assert writes == [] and _pending_bytes(root) == before
    assert not (root / "terminal.next").exists()


@pytest.mark.parametrize("context", ["owner", "root", "thread", "recovering", "pending", "extension", "capture", "creation", "committed", "abort_prepared"])
def test_labeled_wrong_old_context_refuses_before_native_assignment(tmp_path, monkeypatch, context):
    import threading
    from viva.sql_authority import application_io as io
    fixture = _phase_old_fixture(tmp_path)
    root, passphrase, *_rest = fixture
    before = _pending_bytes(root)
    writes = []
    original = ApplicationSQLAuthority._finalize_old_journal
    opened = ApplicationSQLAuthority._open_engine
    def instrument(owner, *args, **kwargs):
        result = opened(owner, *args, **kwargs)
        owner._engine._db = _MaintenanceConnection(owner._engine._db, writes=writes)
        return result
    def wrong(owner):
        binding = owner._binding
        engine_root = owner._engine.root
        if context == "owner":
            owner._binding = object()
        elif context == "root":
            owner._engine.root = owner.root
        elif context == "thread":
            owner._root_lock.owner = threading.get_ident() + 1
        elif context == "recovering":
            owner._recovering = False
        elif context == "pending":
            owner._pending = (owner.root / "pending" / ("f" * 64), owner._pending[1])
        elif context == "extension":
            owner._extension = b"synthetic unissued extension"
        elif context in {"capture", "creation"}:
            path, issued = owner._pending
            owner._pending = path, dict(issued, kind=context)
        elif context == "committed":
            owner._observed = dict(owner._observed, sequence=owner._observed["sequence"] + 1)
        else:
            path, issued = owner._pending
            data = owner._history.intent(issued, "abort_prepared", ("prepared-abort.json", "0" * 64))
            io.replace_head(path / "intent.json", data, temporary="intent.next")
        try:
            return original(owner)
        finally:
            owner._binding = binding
            owner._engine.root = engine_root
            # Disposal still owns the original root lock.
            if context == "thread":
                owner._root_lock.owner = threading.get_ident()
    monkeypatch.setattr(ApplicationSQLAuthority, "_open_engine", instrument)
    monkeypatch.setattr(ApplicationSQLAuthority, "_finalize_old_journal", wrong)
    with pytest.raises((AuthorityError, IntegrityError, RecoveryRequired)):
        ApplicationSQLAuthority.recover(root, passphrase)
    assert writes == []
    if context != "abort_prepared":
        assert _pending_bytes(root) == before
    else:
        after = _pending_bytes(root)
        assert after["prepared-publication.json"] == before["prepared-publication.json"]
        assert after["intent.json"] != before["intent.json"]
    assert not (root / "terminal.next").exists()


@pytest.mark.parametrize("fault", ["before_write", "assignment", "commit", "remaining_journal", "postcommit_verify"])
def test_labeled_maintenance_fault_never_publishes_abort_or_discards_evidence(tmp_path, monkeypatch, fault):
    from viva.sql_authority import application_io as io
    fixture = _phase_old_fixture(tmp_path)
    root, passphrase, *_rest = fixture
    before = _pending_bytes(root)
    proxies = []
    opened = ApplicationSQLAuthority._open_engine
    def instrument(owner, *args, **kwargs):
        result = opened(owner, *args, **kwargs)
        proxy = _MaintenanceConnection(owner._engine._db, fault=fault)
        owner._engine._db = proxy
        proxies.append(proxy)
        verify = owner._engine._verify_current
        def checked(*a, **kw):
            if fault == "before_write" and owner._engine._db.in_transaction:
                raise OSError("labeled prewrite refusal")
            if fault == "postcommit_verify" and proxy.commit_count:
                raise IntegrityError("labeled postcommit refusal")
            return verify(*a, **kw)
        owner._engine._verify_current = checked
        return result
    exists = Path.exists
    def journal_exists(path):
        if fault == "remaining_journal" and path == root / "sql" / "authority.db-journal" and proxies and proxies[0].commit_count:
            return True
        return exists(path)
    monkeypatch.setattr(ApplicationSQLAuthority, "_open_engine", instrument)
    monkeypatch.setattr(Path, "exists", journal_exists)
    with pytest.raises((OSError, IntegrityError, RecoveryRequired)):
        ApplicationSQLAuthority.recover(root, passphrase)
    proxy = proxies[0]
    assert proxy.writes == ([] if fault == "before_write" else ["PRAGMA main.user_version=0"])
    assert proxy.rollback_count == (1 if fault in {"before_write", "assignment", "commit", "postcommit_verify"} else 0)
    assert _pending_bytes(root) == before
    assert not (root / "terminal.next").exists()
    assert len(list((root / "history").iterdir())) == fixture[3]["sequence"]


_MAINTENANCE_INTERRUPTED_RECOVERY = """
import os, signal
from pathlib import Path
from viva.sql_authority import application_io as io
from viva.sql_authority.application import ApplicationSQLAuthority
root = Path(request["root"])
original = ApplicationSQLAuthority._open_engine
class InterruptedConnection:
    def __init__(self, connection, owner):
        self.connection, self.owner, self.assigned = connection, owner, False
    def __getattr__(self, name):
        return getattr(self.connection, name)
    def execute(self, sql, *args):
        result = self.connection.execute(sql, *args)
        if sql.startswith("PRAGMA main.user_version="):
            self.assigned = True
            if request["point"] == "after_assignment":
                stop(self.owner)
        if sql == "COMMIT" and self.assigned and request["point"] == "after_commit":
            stop(self.owner)
        return result
def stop(owner):
    path, issued = owner._pending
    outer, inner = owner._history.read_intent(io.read(path / "intent.json"))
    assert outer["stage"] == "prepared" and inner["issued"] == issued
    assert sorted(p.name for p in path.iterdir()) == ["intent.json", "prepared-publication.json"]
    print(json.dumps({"point": request["point"], "stage": outer["stage"],
                      "kind": issued["kind"], "journal": (root / "sql" / "authority.db-journal").exists()}), flush=True)
    if request["termination"] == "sigkill":
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(74)
def opened(owner, *args, **kwargs):
    result = original(owner, *args, **kwargs)
    owner._engine._db = InterruptedConnection(owner._engine._db, owner)
    return result
ApplicationSQLAuthority._open_engine = opened
ApplicationSQLAuthority.recover(root, request["passphrase"])
raise AssertionError("maintenance interruption was not reached")
"""


@pytest.mark.parametrize("point", ["after_assignment", "after_commit"])
@pytest.mark.parametrize("termination", ["exit", "sigkill"])
def test_native_interrupted_maintenance_retains_owned_old_recovery(tmp_path, point, termination):
    if termination == "sigkill" and os.name == "nt":
        pytest.skip("native SIGKILL is unavailable on this target")
    fixture = _phase_old_fixture(tmp_path)
    root, passphrase, *_rest = fixture
    before = _pending_bytes(root)
    assert fixture[-1]["journal"] is True
    result = _process(_MAINTENANCE_INTERRUPTED_RECOVERY,
                      dict(root=str(root), passphrase=passphrase, point=point, termination=termination), root)
    assert result.returncode == (-9 if termination == "sigkill" else 74), result.stderr
    event = json.loads(result.stdout)
    assert event["point"] == point and event["stage"] == "prepared" and event["kind"] == "transaction"
    assert event["journal"] is (point == "after_assignment")
    assert _pending_bytes(root) == before
    _assert_one_old_abort(fixture, before, 0)


@pytest.mark.parametrize("setting,value", [("journal_mode", "persist"), ("synchronous", 1), ("cipher_use_hmac", 0), ("locking_mode", "exclusive")])
def test_labeled_unsupported_native_profile_is_not_changed_or_written(tmp_path, monkeypatch, setting, value):
    fixture = _phase_old_fixture(tmp_path)
    root, passphrase, *_rest = fixture
    before = _pending_bytes(root)
    proxies = []
    opened = ApplicationSQLAuthority._open_engine
    class ProfileConnection(_MaintenanceConnection):
        def execute(self, sql, *args):
            if sql == "PRAGMA " + setting:
                return _MaintenanceRows([(value,)])
            return super().execute(sql, *args)
    def instrument(owner, *args, **kwargs):
        result = opened(owner, *args, **kwargs)
        proxy = ProfileConnection(owner._engine._db)
        owner._engine._db = proxy
        proxies.append(proxy)
        return result
    monkeypatch.setattr(ApplicationSQLAuthority, "_open_engine", instrument)
    with pytest.raises(AuthorityError, match="durability profile"):
        ApplicationSQLAuthority.recover(root, passphrase)
    assert proxies[0].writes == [] and proxies[0].rollback_count == 0
    assert _pending_bytes(root) == before


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_labeled_header_equality_mismatch_blocks_abort(tmp_path, monkeypatch, phase):
    fixture = _phase_old_fixture(tmp_path)
    root, passphrase, *_rest = fixture
    before = _pending_bytes(root)
    proxies = []
    opened = ApplicationSQLAuthority._open_engine
    def instrument(owner, *args, **kwargs):
        result = opened(owner, *args, **kwargs)
        proxy = _MaintenanceConnection(owner._engine._db)
        owner._engine._db = proxy
        proxies.append(proxy)
        query = owner._journal_user_version
        def mismatch():
            captured = query()
            if proxy.assigned and ((phase == "before_commit" and not proxy.commit_count)
                                   or (phase == "after_commit" and proxy.commit_count)):
                return captured + 1
            return captured
        owner._journal_user_version = mismatch
        return result
    monkeypatch.setattr(ApplicationSQLAuthority, "_open_engine", instrument)
    with pytest.raises(IntegrityError, match="header changed|committed state changed"):
        ApplicationSQLAuthority.recover(root, passphrase)
    assert proxies[0].writes == ["PRAGMA main.user_version=0"]
    assert proxies[0].rollback_count == 1
    assert _pending_bytes(root) == before
    assert not (root / "terminal.next").exists()


def test_labeled_preexisting_transaction_is_never_rolled_back_by_maintenance(tmp_path, monkeypatch):
    fixture = _phase_old_fixture(tmp_path)
    root, passphrase, *_rest = fixture
    before = _pending_bytes(root)
    finalize = ApplicationSQLAuthority._finalize_old_journal
    def independent_writer(owner):
        connection = owner._engine._db
        proxy = _MaintenanceConnection(connection)
        owner._engine._db = proxy
        connection.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(AuthorityError, match="independent writer"):
                finalize(owner)
            assert connection.in_transaction and proxy.writes == [] and proxy.rollback_count == 0
        finally:
            connection.execute("ROLLBACK")
        raise AuthorityError("labeled foreign writer refused")
    monkeypatch.setattr(ApplicationSQLAuthority, "_finalize_old_journal", independent_writer)
    with pytest.raises(AuthorityError, match="foreign writer"):
        ApplicationSQLAuthority.recover(root, passphrase)
    assert _pending_bytes(root) == before
