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
    if stage == "prepared":
        fixture = _residual_old_fixture(tmp_path, termination=termination)
        with pytest.raises(RecoveryRequired):
            SQLAuthority.open(fixture.root, fixture.passphrase, verification="complete", application=True)
        with _ResidualScope(fixture) as scope:
            _assert_residual_old_abort(fixture, scope)
        assert scope.proxy.writes == ["PRAGMA main.user_version=0"]
        return
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
    fixture = _residual_old_fixture(tmp_path, user_version=user_version)
    with _ResidualScope(fixture) as scope:
        _assert_residual_old_abort(fixture, scope)
    assert scope.proxy.writes == ["PRAGMA main.user_version=" + str(user_version)]


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
    fixture = _residual_old_fixture(tmp_path)
    with _ResidualScope(fixture, header=rows) as scope:
        with pytest.raises(IntegrityError, match="header integer"):
            ApplicationSQLAuthority.recover(fixture.root, fixture.passphrase, expected_prefix=fixture.trusted_prefix)
    assert scope.header_injections == 1 and scope.context_success >= 2
    assert scope.proxy.writes == [] and scope.proxy.rollback_count == 1
    assert scope.rollback_kinds == ["writer"]
    scope.assert_refusal_preserved()


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
    fixture = _residual_old_fixture(tmp_path)
    with _ResidualScope(fixture, wrong_context=context) as scope:
        with pytest.raises((AuthorityError, IntegrityError, RecoveryRequired)):
            ApplicationSQLAuthority.recover(fixture.root, fixture.passphrase, expected_prefix=fixture.trusted_prefix)
    assert scope.context_requested == 1 and scope.context_success == 0
    assert scope.proxy.writes == [] and scope.writer_begin_success == 0
    scope.assert_refusal_preserved(changed_intent=context == "abort_prepared")


@pytest.mark.parametrize("fault", ["before_write", "assignment", "commit", "remaining_journal", "postcommit_verify"])
def test_labeled_maintenance_fault_never_publishes_abort_or_discards_evidence(tmp_path, monkeypatch, fault):
    fixture = _residual_old_fixture(tmp_path)
    with _ResidualScope(fixture, fault=fault) as scope:
        with pytest.raises((OSError, IntegrityError, RecoveryRequired)):
            ApplicationSQLAuthority.recover(fixture.root, fixture.passphrase, expected_prefix=fixture.trusted_prefix)
    proxy = scope.proxy
    assert scope.context_success >= 1 and scope.writer_begin_success == 1
    assert proxy.writes == ([] if fault == "before_write" else ["PRAGMA main.user_version=0"])
    assert proxy.rollback_count == (1 if fault in {"before_write", "assignment", "commit", "postcommit_verify"} else 0)
    if fault == "before_write":
        assert scope.assignment_success == 0 and scope.rollback_kinds == ["writer"]
    elif fault == "assignment":
        assert scope.assignment_refusals == 1 and scope.assignment_success == 0 and scope.rollback_kinds == ["writer"]
    elif fault == "commit":
        assert scope.commit_refusals == 1 and scope.writer_commit_success == 0 and scope.rollback_kinds == ["writer"]
    elif fault == "postcommit_verify":
        assert scope.writer_commit_success == 1 and scope.rollback_kinds == ["snapshot"]
    else:
        assert scope.writer_commit_success == 1 and scope.journal_absent_after_commit and scope.rollback_kinds == []
    scope.assert_refusal_preserved()
    assert len(list((fixture.root / "history").iterdir())) == fixture.prior_terminal["sequence"]


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
    fixture = _residual_old_fixture(tmp_path)
    result = _process(_RESIDUAL_MAINTENANCE_INTERRUPTED_RECOVERY,
                      dict(root=str(fixture.root), passphrase=fixture.passphrase, trusted_prefix=fixture.trusted_prefix,
                           point=point, termination=termination), fixture.root)
    assert result.returncode == (-9 if termination == "sigkill" else 74), result.stderr
    event = json.loads(result.stdout)
    assert event["point"] == point and event["stage"] == "prepared" and event["kind"] == "transaction"
    assert event["journal"] is (point == "after_assignment")
    assert event["normalization_verified"] is True and event["assignment_success"] == 1
    assert event["writer_commit_success"] == (1 if point == "after_commit" else 0)
    import hashlib
    expected_digest = hashlib.sha256(json.dumps({k: hashlib.sha256(v).hexdigest() for k,v in fixture.canonical.items()}, sort_keys=True).encode()).hexdigest()
    assert event["canonical_sha256"] == expected_digest
    assert _pending_bytes(fixture.root) == fixture.canonical
    assert _residual_history_bytes(fixture.root) == fixture.history_before
    fixture.prior_terminal, fixture.prior_sql = event["prior_terminal"], event["prior_sql"]
    assert fixture.prior_terminal["root_id"] == fixture.trusted_prefix["root_id"]
    assert fixture.prior_terminal["sequence"] >= fixture.trusted_prefix["sequence"]
    result = ApplicationSQLAuthority.recover(fixture.root, fixture.passphrase, expected_prefix=fixture.prior_terminal)
    _assert_residual_completed(fixture, fixture.canonical, result)


@pytest.mark.parametrize("setting,value", [("journal_mode", "persist"), ("synchronous", 1), ("cipher_use_hmac", 0), ("locking_mode", "exclusive")])
def test_labeled_unsupported_native_profile_is_not_changed_or_written(tmp_path, monkeypatch, setting, value):
    fixture = _residual_old_fixture(tmp_path)
    with _ResidualScope(fixture, profile=(setting, value)) as scope:
        with pytest.raises(AuthorityError, match="durability profile"):
            ApplicationSQLAuthority.recover(fixture.root, fixture.passphrase, expected_prefix=fixture.trusted_prefix)
    assert scope.context_success == 1 and scope.profile_injections == 1
    assert scope.proxy.writes == [] and scope.proxy.rollback_count == 0
    assert scope.writer_begin_success == 0
    scope.assert_refusal_preserved()


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_labeled_header_equality_mismatch_blocks_abort(tmp_path, monkeypatch, phase):
    fixture = _residual_old_fixture(tmp_path)
    with _ResidualScope(fixture, mismatch=phase) as scope:
        with pytest.raises(IntegrityError, match="header changed|committed state changed"):
            ApplicationSQLAuthority.recover(fixture.root, fixture.passphrase, expected_prefix=fixture.trusted_prefix)
    assert scope.proxy.writes == ["PRAGMA main.user_version=0"]
    assert scope.proxy.rollback_count == 1 and scope.assignment_success == 1
    assert scope.rollback_kinds == (["writer"] if phase == "before_commit" else ["snapshot"])
    assert scope.writer_commit_success == (1 if phase == "after_commit" else 0)
    scope.assert_refusal_preserved()


def test_labeled_preexisting_transaction_is_never_rolled_back_by_maintenance(tmp_path, monkeypatch):
    fixture = _residual_old_fixture(tmp_path)
    with _ResidualScope(fixture, preexisting=True) as scope:
        with pytest.raises(AuthorityError, match="foreign writer"):
            ApplicationSQLAuthority.recover(fixture.root, fixture.passphrase, expected_prefix=fixture.trusted_prefix)
    assert scope.foreign_refused and scope.context_success == 1
    assert scope.proxy.writes == [] and scope.proxy.rollback_count == 0
    assert scope.writer_begin_success == 0
    scope.assert_refusal_preserved()


class _ResidualFixture:
    def __repr__(self):
        return "<fresh synthetic residual-journal fixture>"


def _residual_history_bytes(root):
    values = {p.name: p.read_bytes() for p in (root / "history").iterdir()}
    values["terminal.json"] = (root / "terminal.json").read_bytes()
    assert not (root / "terminal.next").exists()
    return values


def _residual_journal(root):
    import stat
    value = (root / "sql" / "authority.db-journal").lstat()
    assert stat.S_ISREG(value.st_mode) and value.st_nlink == 1
    return value.st_dev, value.st_ino


def _residual_old_fixture(tmp_path, *, termination="exit", user_version=0):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture = _ResidualFixture()
    fixture.root = tmp_path.resolve() / "application"
    fixture.passphrase = secrets.token_urlsafe(32)
    fixture.user_version = user_version
    with SQLAuthority.create(fixture.root, fixture.passphrase, verification="complete", application=True) as owner:
        fixture.accepted = _accepted_statement(owner)
        fixture.trusted_prefix = owner.terminal
        fixture.postings = owner.postings(fixture.accepted.doc_id)
        fixture.original = owner.original(fixture.accepted.doc_id)
        if user_version:
            owner._engine._db.execute("PRAGMA main.user_version=" + str(user_version))
        assert owner._engine._db.execute("PRAGMA main.user_version").fetchall() == [(user_version,)]
    completed = _process(_INTERRUPTED_TRANSACTION,
                         dict(root=str(fixture.root), passphrase=fixture.passphrase,
                              point="initial_intent_file_fsync", termination=termination), fixture.root)
    assert completed.returncode == (-9 if termination == "sigkill" else 73), completed.stderr
    marker = json.loads(completed.stdout)
    assert marker["interrupted"] == "initial_intent_file_fsync" and marker["actual_process"] is True
    fixture.raw = _pending_bytes(fixture.root)
    assert set(fixture.raw) == {"intent.json", "intent.next", "prepared-publication.json"}
    fixture.canonical = {"intent.json": fixture.raw["intent.next"],
                         "prepared-publication.json": fixture.raw["prepared-publication.json"]}
    fixture.history_before = _residual_history_bytes(fixture.root)
    fixture.journal_identity = _residual_journal(fixture.root)
    fixture.prior_terminal = fixture.prior_sql = None
    return fixture


class _ResidualMaintenanceConnection(_MaintenanceConnection):
    def __init__(self, connection, scope):
        super().__init__(connection)
        self.scope = scope
        self.transaction_kind = None

    def execute(self, sql, *args):
        scope = self.scope
        active = scope.active
        if active and sql == "PRAGMA main.user_version" and scope.header is not None:
            scope.header_injections += 1
            return _MaintenanceRows(scope.header)
        if active and scope.phase == "profile" and sql in scope.profile_queries:
            scope.profile_seen.append(sql)
            if scope.profile is not None and sql == "PRAGMA " + scope.profile[0]:
                scope.profile_injections += 1
                return _MaintenanceRows([(scope.profile[1],)])
        assignment = sql.startswith("PRAGMA main.user_version=")
        if assignment:
            self.writes.append(sql)
            if active and scope.fault == "assignment":
                scope.assignment_refusals += 1
                raise OSError("labeled assignment refusal")
        if sql == "COMMIT" and self.assigned:
            self.commit_count += 1
            if active and scope.fault == "commit" and not scope.writer_commit_success:
                scope.commit_refusals += 1
                raise OSError("labeled commit refusal")
        if sql == "ROLLBACK":
            self.rollback_count += 1
        kind = self.transaction_kind
        result = self.connection.execute(sql, *args)
        if sql == "BEGIN IMMEDIATE":
            self.transaction_kind = "writer"
            if active:
                scope.writer_begin_success += 1
                scope.phase = "writer"
        elif sql == "BEGIN":
            self.transaction_kind = "snapshot"
        elif assignment:
            self.assigned = True
            if active:
                scope.assignment_success += 1
                if scope.crash_point == "after_assignment":
                    scope.crash(self.scope.owner)
        elif sql == "COMMIT":
            self.transaction_kind = None
            if active and kind == "writer":
                scope.writer_commit_success += 1
                scope.phase = "postcommit"
                try:
                    (scope.fixture.root / "sql" / "authority.db-journal").lstat()
                except FileNotFoundError:
                    scope.journal_absent_after_commit = True
                if scope.crash_point == "after_commit":
                    scope.crash(scope.owner)
        elif sql == "ROLLBACK":
            self.transaction_kind = None
            if active:
                scope.rollback_kinds.append(kind)
        return result


class _ResidualScope:
    profile_queries = ("PRAGMA journal_mode", "PRAGMA synchronous", "PRAGMA cipher_use_hmac", "PRAGMA locking_mode")

    def __init__(self, fixture, *, header=None, fault=None, wrong_context=None,
                 profile=None, mismatch=None, preexisting=False, crash_point=None, crash=None):
        self.fixture = fixture
        self.header, self.fault, self.wrong_context = header, fault, wrong_context
        self.profile, self.mismatch, self.preexisting = profile, mismatch, preexisting
        self.crash_point, self.crash = crash_point, crash
        self.active = False
        self.phase = "inactive"
        self.normalizer_calls = self.entry_count = self.context_requested = self.context_success = 0
        self.precondition_context_calls = 0
        self.writer_begin_success = self.assignment_success = self.writer_commit_success = 0
        self.header_injections = self.profile_injections = 0
        self.assignment_refusals = self.commit_refusals = 0
        self.verify_success = 0
        self.profile_seen, self.header_values, self.rollback_kinds = [], [], []
        self.journal_absent_after_commit = False
        self.before = None
        self.proxy = self.owner = None
        self.foreign_refused = False
        self.saved = {}

    def __enter__(self):
        from viva.sql_authority import application_history as history
        cls = ApplicationSQLAuthority
        for name in ("_recover_intent_head", "_finalize_old_journal", "_old_journal_context", "_journal_user_version"):
            self.saved[name] = getattr(cls, name)
        original_normalizer = self.saved["_recover_intent_head"]
        original_finalize = self.saved["_finalize_old_journal"]
        original_context = self.saved["_old_journal_context"]
        original_header = self.saved["_journal_user_version"]
        fixture = self.fixture
        scope = self

        def normalizer(owner, path):
            if owner.root != fixture.root:
                return original_normalizer(owner, path)
            assert scope.normalizer_calls == 0
            raw = _pending_bytes(owner.root)
            assert raw == fixture.raw and set(raw) == {"intent.json", "intent.next", "prepared-publication.json"}
            assert _residual_history_bytes(owner.root) == fixture.history_before
            current, initial = owner._history.read_intent(raw["intent.json"])
            successor, prepared = owner._history.read_intent(raw["intent.next"])
            assert current["stage"] == "initial" and successor["stage"] == "prepared"
            issued = initial["issued"]
            assert issued == prepared["issued"] and issued["kind"] == "transaction"
            assert current["operation_id"] == successor["operation_id"] == path.name == issued["operation_id"]
            assert current["root_id"] == successor["root_id"] == owner._metadata["root_id"]
            assert initial["prepared_name"] is initial["prepared_sha256"] is None
            assert initial["superseded_name"] is initial["superseded_sha256"] is None
            assert prepared["prepared_name"] == "prepared-publication.json"
            assert prepared["prepared_sha256"] == history.digest(raw["prepared-publication.json"])
            assert prepared["superseded_name"] is prepared["superseded_sha256"] is None
            assert not (owner.root / "history" / ("%020d.json" % (issued["prior_terminal"]["sequence"] + 1))).exists()
            assert not (owner.root / "terminal.next").exists()
            owner._validate_issued_frontier(issued)
            owner._validate_prepared_members(path, successor, prepared)
            record = owner._history.record(raw["prepared-publication.json"], previous=issued["prior_terminal"])
            assert record["kind"] == "sql_commit"
            assert owner._history.payload(record, previous=issued["prior_terminal"])["issued"] == issued
            result = original_normalizer(owner, path)
            scope.normalizer_calls += 1
            assert result[0]["stage"] == "prepared" and result[1]["issued"] == issued
            assert _pending_bytes(owner.root) == fixture.canonical
            assert _residual_history_bytes(owner.root) == fixture.history_before
            fixture.prior_terminal, fixture.prior_sql = issued["prior_terminal"], issued["prior_sql"]
            assert fixture.prior_terminal["root_id"] == fixture.trusted_prefix["root_id"]
            assert fixture.prior_terminal["sequence"] >= fixture.trusted_prefix["sequence"]
            scope.before = dict(fixture.canonical)
            return result

        def context(owner):
            if scope.active and owner is scope.owner:
                scope.context_requested += 1
            value = original_context(owner)
            if scope.active and owner is scope.owner:
                scope.context_success += 1
                if scope.context_success == 1:
                    scope.phase = "profile"
            return value

        def header(owner):
            value = original_header(owner)
            if scope.active and owner is scope.owner:
                scope.header_values.append(value)
                if scope.proxy.assigned and ((scope.mismatch == "before_commit" and not scope.writer_commit_success)
                                             or (scope.mismatch == "after_commit" and scope.writer_commit_success)):
                    return value + 1
            return value

        def finalize(owner):
            if owner.root != fixture.root:
                return original_finalize(owner)
            assert scope.entry_count == 0 and scope.normalizer_calls == 1
            scope.entry_count += 1
            scope.owner = owner
            identity = _residual_journal(owner.root)
            assert identity == fixture.journal_identity
            assert _pending_bytes(owner.root) == scope.before
            assert _residual_history_bytes(owner.root) == fixture.history_before
            preserved, terminal = original_context(owner)
            scope.precondition_context_calls += 1
            assert preserved == scope.before and terminal == fixture.prior_terminal
            assert _residual_journal(owner.root) == identity
            assert _pending_bytes(owner.root) == scope.before
            raw_db = owner._engine._db
            scope.proxy = _ResidualMaintenanceConnection(raw_db, scope)
            owner._engine._db = scope.proxy
            verified = owner._engine._verify_current

            def verify(*args, **kwargs):
                if scope.active and scope.fault == "before_write" and scope.proxy.transaction_kind == "writer" and not scope.proxy.assigned:
                    raise OSError("labeled prewrite refusal")
                if scope.active and scope.fault == "postcommit_verify" and scope.writer_commit_success:
                    raise IntegrityError("labeled postcommit refusal")
                result = verified(*args, **kwargs)
                if scope.active:
                    scope.verify_success += 1
                return result

            owner._engine._verify_current = verify
            saved_fields = (owner._binding, owner._engine.root, owner._root_lock.owner,
                            owner._recovering, owner._pending, owner._extension, owner._observed)
            scope.active = True
            scope.phase = "context"
            if scope.preexisting:
                raw_db.execute("BEGIN IMMEDIATE")
            try:
                _residual_mutate_context(owner, scope.wrong_context)
                if scope.preexisting:
                    with pytest.raises(AuthorityError, match="independent writer"):
                        original_finalize(owner)
                    assert raw_db.in_transaction and scope.proxy.writes == [] and scope.proxy.rollback_count == 0
                    scope.foreign_refused = True
                    raise AuthorityError("labeled foreign writer refused")
                return original_finalize(owner)
            finally:
                scope.active = False
                owner._engine._verify_current = verified
                owner._binding, owner._engine.root, owner._root_lock.owner, owner._recovering, owner._pending, owner._extension, owner._observed = saved_fields
                if scope.preexisting and raw_db.in_transaction:
                    raw_db.execute("ROLLBACK")

        self.saved_exists = Path.exists
        def exists(path):
            if (scope.active and scope.fault == "remaining_journal" and scope.writer_commit_success
                    and path == fixture.root / "sql" / "authority.db-journal"):
                return True
            return scope.saved_exists(path)
        cls._recover_intent_head = normalizer
        cls._old_journal_context = context
        cls._journal_user_version = header
        cls._finalize_old_journal = finalize
        Path.exists = exists
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(ApplicationSQLAuthority, name, value)
        Path.exists = self.saved_exists
        return False

    def assert_refusal_preserved(self, *, changed_intent=False):
        assert self.normalizer_calls == self.entry_count == self.precondition_context_calls == 1
        after = _pending_bytes(self.fixture.root)
        if changed_intent:
            assert set(after) == set(self.before)
            assert after["prepared-publication.json"] == self.before["prepared-publication.json"]
            assert after["intent.json"] != self.before["intent.json"]
        else:
            assert after == self.before
        assert _residual_history_bytes(self.fixture.root) == self.fixture.history_before
        assert not (self.fixture.root / "terminal.next").exists()
        assert not list((self.fixture.root / "pending").rglob("prepared-abort.json"))

    def assert_success(self):
        assert self.normalizer_calls == self.entry_count == self.precondition_context_calls == 1
        assert self.context_requested == self.context_success == 4
        assert self.profile_seen == list(self.profile_queries)
        assert self.writer_begin_success == self.assignment_success == self.writer_commit_success == 1
        assert self.verify_success == 3
        assert self.header_values == [self.fixture.user_version] * 4
        assert self.journal_absent_after_commit and self.proxy.rollback_count == 0


def _residual_mutate_context(owner, context):
    import threading
    from viva.sql_authority import application_io as io
    if context is None:
        return
    if context == "owner":
        owner._binding = object()
    elif context == "root":
        owner._engine.root = owner.root
    elif context == "thread":
        owner._root_lock.owner = threading.get_ident() + 1
    elif context == "recovering":
        owner._recovering = False
    elif context == "pending":
        owner._pending = owner.root / "pending" / ("f" * 64), owner._pending[1]
    elif context == "extension":
        owner._extension = b"synthetic unissued extension"
    elif context in {"capture", "creation"}:
        owner._pending = owner._pending[0], dict(owner._pending[1], kind=context)
    elif context == "committed":
        owner._observed = dict(owner._observed, sequence=owner._observed["sequence"] + 1)
    elif context == "abort_prepared":
        path, issued = owner._pending
        io.replace_head(path / "intent.json", owner._history.intent(issued, "abort_prepared", ("prepared-abort.json", "0" * 64)), temporary="intent.next")
    else:
        raise AssertionError("unknown labeled context")


def _assert_residual_completed(fixture, before, result):
    root, passphrase, accepted = fixture.root, fixture.passphrase, fixture.accepted
    trusted, head = fixture.prior_terminal, fixture.prior_sql
    assert result["outcome"] == "aborted"
    assert not (root / "sql" / "authority.db-journal").exists()
    assert not list((root / "pending").iterdir())
    with SQLAuthority.open(root, passphrase, verification="complete", application=True) as owner:
        assert owner.head == head
        assert owner.account(accepted.account_id)["running_balance"] == "90"
        assert len(owner.transactions(accepted.account_id)) == 1
        assert owner.postings(accepted.doc_id) == fixture.postings
        assert owner.original(accepted.doc_id) == fixture.original
        assert owner._engine._db.execute("PRAGMA main.user_version").fetchall() == [(fixture.user_version,)]
        assert owner.verify()["counts"]["transactions"] == 1
        _terminal, records, payloads = owner._history.scan()
        aborted = [payload for record, payload in zip(records, payloads) if record["kind"] == "interrupted_abort"]
        assert len(aborted) == 1
        assert aborted[0]["body"]["superseded_publication"].encode() == before["prepared-publication.json"]
        terminal = owner.terminal
        assert terminal["sequence"] == trusted["sequence"] + 1
        assert records[-1]["previous_hash"] == trusted["head"]
        assert aborted[0]["issued"]["prior_sql"] == head
    assert ApplicationSQLAuthority.recover(root, passphrase, expected_prefix=trusted)["outcome"] == "already_ready"
    from test_sql_application_history import _fresh_keyless_check
    assert _fresh_keyless_check(root, terminal)["result"]["structural"] is True


def _assert_residual_old_abort(fixture, scope):
    result = ApplicationSQLAuthority.recover(fixture.root, fixture.passphrase, expected_prefix=fixture.trusted_prefix)
    scope.assert_success()
    _assert_residual_completed(fixture, scope.before, result)


_RESIDUAL_MAINTENANCE_INTERRUPTED_RECOVERY = """
import hashlib, os, signal
from pathlib import Path
from test_sql_application_recovery import _ResidualFixture, _ResidualScope, _pending_bytes, _residual_history_bytes
from viva.sql_authority.application import ApplicationSQLAuthority
root = Path(request["root"])
fixture = _ResidualFixture()
fixture.root = root
fixture.raw = _pending_bytes(root)
assert set(fixture.raw) == {"intent.json", "intent.next", "prepared-publication.json"}
fixture.canonical = {"intent.json": fixture.raw["intent.next"], "prepared-publication.json": fixture.raw["prepared-publication.json"]}
fixture.history_before = _residual_history_bytes(root)
fixture.trusted_prefix = request["trusted_prefix"]
fixture.user_version = 0
from test_sql_application_recovery import _residual_journal
fixture.journal_identity = _residual_journal(root)
fixture.prior_terminal = fixture.prior_sql = None
def stop(owner):
    assert _pending_bytes(root) == fixture.canonical
    assert _residual_history_bytes(root) == fixture.history_before
    assert scope.entry_count == scope.precondition_context_calls == scope.normalizer_calls == 1
    assert scope.context_success >= 2 and scope.writer_begin_success == 1 and scope.assignment_success == 1
    assert scope.writer_commit_success == (1 if request["point"] == "after_commit" else 0)
    print(json.dumps({"point": request["point"], "stage": "prepared", "kind": "transaction",
                      "journal": (root / "sql" / "authority.db-journal").exists(),
                      "normalization_verified": True,
                      "canonical_sha256": hashlib.sha256(json.dumps({k: hashlib.sha256(v).hexdigest() for k,v in fixture.canonical.items()}, sort_keys=True).encode()).hexdigest(),
                      "prior_terminal": fixture.prior_terminal, "prior_sql": fixture.prior_sql,
                      "assignment_success": scope.assignment_success, "writer_commit_success": scope.writer_commit_success}), flush=True)
    if request["termination"] == "sigkill":
        os.kill(os.getpid(), signal.SIGKILL)
    os._exit(74)
with _ResidualScope(fixture, crash_point=request["point"], crash=stop) as scope:
    ApplicationSQLAuthority.recover(root, request["passphrase"], expected_prefix=fixture.trusted_prefix)
raise AssertionError("maintenance interruption was not reached")
"""
