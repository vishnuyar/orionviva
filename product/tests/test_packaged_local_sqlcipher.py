"""Opt-in smoke proof against a freshly built macOS application bundle."""

from __future__ import annotations

import json
import os
import select
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from viva.crypto import KdfParams, SALT_LEN
from viva.ingest.raw_store import RawStore
from viva.ledger import EventStore, account_opened
from viva.read_store import ReadStore, ReadStoreError


APP = os.environ.get("ORIONVIVA_LOCAL_PACKAGED_APP", "")
DMG = os.environ.get("ORIONVIVA_LOCAL_PACKAGED_DMG", "")
SENTINEL = "ORIONVIVA_PACKAGED_SENTINEL_25C0F9"
PASSPHRASE = "synthetic-packaged-passphrase"


def _start(binary: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, start_new_session=True)


def _ask(process: subprocess.Popen, request_id: str, operation: str,
         payload: dict) -> dict:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps({
        "protocol": "2.0", "request_id": request_id,
        "operation": operation, "payload": payload,
    }) + "\n")
    process.stdin.flush()
    ready, _, _ = select.select([process.stdout], [], [], 10)
    assert ready, (request_id, process.poll())
    response = json.loads(process.stdout.readline())
    assert response["request_id"] == request_id
    return response


def _stop_group(process: subprocess.Popen) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)
    assert process.stdin is not None and process.stdout is not None
    assert process.stderr is not None
    assert SENTINEL not in process.stderr.read()
    process.stdin.close()
    process.stdout.close()
    process.stderr.close()


@pytest.mark.skipif(not APP, reason="set ORIONVIVA_LOCAL_PACKAGED_APP to a fresh .app")
def test_mac_bundle_sqlcipher_crash_reopen_and_plaintext_containment(tmp_path: Path):
    app = Path(APP)
    binary = app / "Contents" / "MacOS" / "viva-desktop-bridge"
    assert app.suffix == ".app" and binary.is_file()
    vault_dir = tmp_path / "synthetic-vault"

    first = _start(binary)
    try:
        opened = _ask(first, "create", "bridge.open_vault", {
            "vault_directory": str(vault_dir), "passphrase": PASSPHRASE,
            "create": True,
        })
        assert opened["ok"] is True and opened["result"]["state"] == "created"
    finally:
        _stop_group(first)

    event_store = EventStore.open(vault_dir / "events.jsonl", PASSPHRASE)
    event_store.append(account_opened(
        "synthetic", "depository", SENTINEL, "USD", "2026-01-01"))
    committed = event_store.committed_snapshot().identity

    wrong = _start(binary)
    try:
        refused = _ask(wrong, "wrong", "bridge.open_vault", {
            "vault_directory": str(vault_dir), "passphrase": "incorrect",
            "create": False,
        })
        assert refused["ok"] is False
    finally:
        _stop_group(wrong)

    second = _start(binary)
    try:
        reopened = _ask(second, "reopen", "bridge.open_vault", {
            "vault_directory": str(vault_dir), "passphrase": PASSPHRASE,
            "create": False,
        })
        assert reopened["ok"] is True
        deadline = time.monotonic() + 15
        read_model = vault_dir / "read-model"
        while True:
            try:
                with ReadStore.open(read_model, PASSPHRASE) as reads:
                    with reads.open_reader() as revision:
                        source = reads.authenticated_source_identity(revision)
                        if (source["count"], source["head"]) == (
                                committed.count, committed.head_hash):
                            database = (read_model / "generations" /
                                        revision.generation / "projection.db")
                            cipher = revision.connection.execute(
                                "PRAGMA cipher_version").fetchone()
                            integrity = revision.connection.execute(
                                "PRAGMA integrity_check").fetchone()
                            assert cipher and cipher[0]
                            assert integrity == ("ok",)
                            assert revision.connection.execute(
                                "SELECT COUNT(*) FROM applied_events").fetchone() == (1,)
                            break
            except (ReadStoreError, OSError):
                pass
            assert time.monotonic() < deadline, "packaged rebuild did not catch up"
            time.sleep(0.05)
    finally:
        _stop_group(second)

    contents = database.read_bytes()
    assert not contents.startswith(b"SQLite format 3")
    assert SENTINEL.encode() not in contents
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(database).execute("SELECT * FROM applied_events").fetchall()
    with pytest.raises(ReadStoreError):
        ReadStore.open(read_model, "incorrect")

    forbidden = (SENTINEL.encode(), b"SQLite format 3")
    for root in (app, read_model):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            assert all(token not in str(path).encode() for token in forbidden)
            data = path.read_bytes()
            assert all(token not in data for token in forbidden), path.relative_to(root)
    if DMG:
        installer = Path(DMG)
        assert installer.is_file() and installer.suffix == ".dmg"
        assert all(token not in str(installer).encode() for token in forbidden)
        data = installer.read_bytes()
        assert all(token not in data for token in forbidden), installer.name


@pytest.mark.skipif(not APP, reason="set ORIONVIVA_LOCAL_PACKAGED_APP to a fresh .app")
def test_packaged_cpu_bound_open_is_contained_by_native_host(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    binary = Path(APP) / "Contents" / "MacOS" / "viva-desktop-bridge"
    assert binary.is_file()
    vault_dir = tmp_path / "slow-synthetic-vault"
    vault_dir.mkdir()
    with monkeypatch.context() as scoped:
        scoped.setattr(KdfParams, "new", classmethod(
            lambda _cls: KdfParams(os.urandom(SALT_LEN), n=2 ** 18)))
        EventStore.open(vault_dir / "events.jsonl", PASSPHRASE)
    RawStore.open(vault_dir / "raw", PASSPHRASE)

    started = time.monotonic()
    EventStore.open(vault_dir / "events.jsonl", PASSPHRASE)
    assert time.monotonic() - started > 0.1

    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["ORIONVIVA_PACKAGED_SIDECAR"] = str(binary)
    env["ORIONVIVA_PACKAGED_SLOW_VAULT"] = str(vault_dir)
    result = subprocess.run(
        ["cargo", "test", "packaged_cpu_bound_open_timeout_settles_peer_and_reaps_generation",
         "--", "--nocapture"],
        cwd=root / "desktop" / "src-tauri", env=env,
        capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
