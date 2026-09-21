"""Native-process exclusion and portable commit/recovery regressions."""

import errno
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from viva.ledger import EventStore
from viva.ledger import platform_io


def _wait_for(path, process):
    deadline = time.monotonic() + 15
    while not path.exists():
        assert process.poll() is None, process.communicate()
        assert time.monotonic() < deadline, "child did not reach synchronization point"
        time.sleep(0.01)


@pytest.mark.parametrize("legacy_unix", [False, pytest.param(
    True, marks=pytest.mark.skipif(os.name == "nt", reason="Unix flock interoperability"))])
def test_writer_lock_excludes_process_and_allows_separate_read_handle(tmp_path, legacy_unix):
    path = tmp_path / "ledger.jsonl"
    EventStore.open(path, "synthetic-passphrase")
    ready, acquired = tmp_path / "ready", tmp_path / "acquired"
    with path.open("ab") as stream:
        if legacy_unix:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        else:
            platform_io.lock_writer(stream.fileno())
        child = subprocess.Popen([sys.executable, "-c", """
import sys
from pathlib import Path
from viva.ledger.platform_io import lock_writer, unlock_writer
path, ready, acquired = map(Path, sys.argv[1:])
with path.open('ab') as stream:
    ready.touch()
    lock_writer(stream.fileno())
    acquired.touch()
    unlock_writer(stream.fileno())
""", str(path), str(ready), str(acquired)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            _wait_for(ready, child)
            time.sleep(0.2)
            assert not acquired.exists()
            # Windows must not reserve bytes containing the encrypted header.
            assert path.read_bytes().startswith(b'{')
        finally:
            platform_io.unlock_writer(stream.fileno())
            try:
                output = child.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
                raise
        assert child.returncode == 0, output
        assert acquired.exists()


def test_concurrent_process_decisions_observe_all_preceding_commits(tmp_path):
    path = tmp_path / "ledger.jsonl"
    EventStore.open(path, "synthetic-passphrase")
    children = []
    try:
        for index in range(3):
            ready = tmp_path / f"ready-{index}"
            child = subprocess.Popen([sys.executable, "-c", """
import sys
from pathlib import Path
from viva.ledger import EventStore, account_opened
store = EventStore.open(Path(sys.argv[1]), 'synthetic-passphrase')
Path(sys.argv[2]).touch()
sys.stdin.readline()
for _ in range(6):
    store.append_atomically(lambda events: (
        account_opened(str(len(events)), 'depository', 'Synthetic account', 'USD', '2026-01-01'),
    ))
""", str(path), str(ready)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            children.append(child)
            _wait_for(ready, child)
        for child in children:
            child.stdin.write(b"start\n")
            child.stdin.flush()
        for child in children:
            output = child.communicate(timeout=30)
            assert child.returncode == 0, output
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()
    reopened = EventStore.open(path, "synthetic-passphrase")
    assert reopened.verify_chain() == (True, 18)
    assert [event.body['account_id'] for event in reopened.events()] == [str(n) for n in range(18)]
    assert b'\r\n' not in path.read_bytes()
    assert b'\r\n' not in path.with_suffix('.jsonl.head').read_bytes()


def test_decision_exception_releases_lock_for_another_handle(tmp_path):
    path = tmp_path / "ledger.jsonl"
    store = EventStore.open(path, "synthetic-passphrase")
    with pytest.raises(ValueError, match="synthetic decision"):
        store.append_atomically(lambda _: (_ for _ in ()).throw(ValueError("synthetic decision")))
    child = subprocess.run([sys.executable, "-c", """
from pathlib import Path
import sys
from viva.ledger import EventStore, account_opened
EventStore.open(Path(sys.argv[1]), 'synthetic-passphrase').append(
    account_opened('test', 'depository', 'Synthetic account', 'USD', '2026-01-01'))
""", str(path)], capture_output=True, timeout=15)
    assert child.returncode == 0, child.stderr
    assert EventStore.open(path, "synthetic-passphrase").verify_chain() == (True, 1)


@pytest.fixture
def windows_lock_offset(monkeypatch):
    # These unit tests mock msvcrt. Unix filesystems may reject Windows' full
    # 64-bit reservation; Windows itself must exercise the production offset.
    if os.name != "nt":
        monkeypatch.setattr(platform_io, "WINDOWS_LOCK_OFFSET", 1 << 20)
    return platform_io.WINDOWS_LOCK_OFFSET


@pytest.mark.parametrize("failure", [errno.EACCES, errno.EAGAIN, errno.EBADF])
def test_windows_lock_restores_position_and_only_retries_contention(
        tmp_path, monkeypatch, failure, windows_lock_offset):
    calls = []
    with (tmp_path / "lock").open("w+b") as stream:
        stream.write(b"header")
        stream.flush()
        stream.seek(2)

        def locking(fd, mode, count):
            calls.append((os.lseek(fd, 0, os.SEEK_CUR), mode, count))
            if len(calls) == 1:
                raise OSError(failure, "synthetic lock failure")

        monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(
            locking=locking, LK_UNLCK=0, LK_NBLCK=2))
        if failure == errno.EBADF:
            with pytest.raises(OSError):
                platform_io._windows_lock(stream.fileno(), release=False)
            assert len(calls) == 1
        else:
            platform_io._windows_lock(stream.fileno(), release=False)
            assert len(calls) == 2
        assert os.lseek(stream.fileno(), 0, os.SEEK_CUR) == 2
        assert all(call == (windows_lock_offset, 2, 1) for call in calls)
        assert os.fstat(stream.fileno()).st_size == 6


def test_windows_unlock_failure_propagates_without_retry(
        tmp_path, monkeypatch, windows_lock_offset):
    calls = []

    def locking(fd, mode, count):
        calls.append(mode)
        raise OSError(errno.EACCES, "synthetic unlock failure")

    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(
        locking=locking, LK_UNLCK=0, LK_NBLCK=2))
    with (tmp_path / "lock").open("w+b") as stream:
        with pytest.raises(OSError, match="unlock failure"):
            platform_io._windows_lock(stream.fileno(), release=True)
        assert os.lseek(stream.fileno(), 0, os.SEEK_CUR) == 0
    assert calls == [0]


@pytest.mark.parametrize("succeeds", [True, False])
def test_windows_commit_requests_write_through_and_propagates_errors(tmp_path, monkeypatch, succeeds):
    import ctypes

    calls = []

    def move(source, target, flags):
        calls.append((source, target, flags))
        return succeeds

    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: SimpleNamespace(MoveFileExW=move), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code, "synthetic rename failure"), raising=False)
    source, target = tmp_path / "head.tmp", tmp_path / "head"
    if succeeds:
        platform_io._windows_replace(source, target)
    else:
        with pytest.raises(OSError, match="rename failure"):
            platform_io._windows_replace(source, target)
    assert calls == [(str(source), str(target), 9)]


def test_windows_reservation_cannot_overlap_supported_log_extent(monkeypatch):
    monkeypatch.setattr(platform_io, "os", SimpleNamespace(
        name="nt", fstat=lambda fd: SimpleNamespace(st_size=platform_io.WINDOWS_LOCK_OFFSET)))
    with pytest.raises(OSError, match="supported Windows extent"):
        platform_io.lock_writer(1)


def test_windows_append_cannot_grow_into_lock_reservation(monkeypatch):
    from viva.ledger import store

    monkeypatch.setattr(store, "os", SimpleNamespace(
        name="nt", fstat=lambda fd: SimpleNamespace(st_size=store.WINDOWS_LOCK_OFFSET - 2)))
    stream = SimpleNamespace(fileno=lambda: 1, write=lambda value: pytest.fail("reserved byte overwritten"))
    with pytest.raises(OSError, match="supported Windows extent"):
        store._write_batch(stream, "xx")


@pytest.mark.parametrize("commit_head", [False, True])
def test_process_exit_releases_writer_and_recovers_authenticated_boundary(tmp_path, commit_head):
    path = tmp_path / "ledger.jsonl"
    EventStore.open(path, "synthetic-passphrase")
    child = subprocess.run([sys.executable, "-c", """
import os
from pathlib import Path
import sys
from viva.ledger import EventStore, account_opened
from viva.ledger import store as module
store = EventStore.open(Path(sys.argv[1]), 'synthetic-passphrase')
write_head = module.write_head
def exit_at_boundary(*args, **kwargs):
    if sys.argv[2] == 'commit':
        write_head(*args, **kwargs)
    os._exit(31)
module.write_head = exit_at_boundary
store.append(account_opened('first', 'depository', 'Synthetic account', 'USD', '2026-01-01'))
""", str(path), "commit" if commit_head else "uncommitted"], capture_output=True, timeout=15)
    assert child.returncode == 31, child.stderr
    reopened = EventStore.open(path, "synthetic-passphrase")
    assert reopened.verify_chain() == (True, int(commit_head))
    # Reopening and appending would hang if process death left exclusion held.
    child = subprocess.run([sys.executable, "-c", """
from pathlib import Path
import sys
from viva.ledger import EventStore, account_opened
EventStore.open(Path(sys.argv[1]), 'synthetic-passphrase').append(
    account_opened('second', 'depository', 'Synthetic account', 'USD', '2026-01-01'))
""", str(path)], capture_output=True, timeout=15)
    assert child.returncode == 0, child.stderr
    assert EventStore.open(path, "synthetic-passphrase").verify_chain() == (True, int(commit_head) + 1)
