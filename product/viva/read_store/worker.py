"""Isolated disposable read-model synchronization entry point."""
from __future__ import annotations

import json
import sys
import shutil
from pathlib import Path


def open_stores(payload: bytes):
    request = json.loads(payload.decode("utf-8"))
    directory = Path(request.pop("directory"))
    passphrase = request.pop("passphrase")
    token = request.pop("token")
    if (request or not isinstance(passphrase, str) or not passphrase
            or not isinstance(token, str) or len(token) < 32 or len(token) > 128):
        raise ValueError("invalid read-store worker request")
    from ..ledger.store import EventStore
    from .store import ReadStore, ReadStoreError

    events = EventStore.open(directory / "events.jsonl", passphrase)
    root = directory / "read-model"
    try:
        reads = ReadStore.open(root, passphrase)
    except ReadStoreError:
        reads = ReadStore.open_for_recovery(root, passphrase)
    passphrase = ""
    return events, reads, token


def _cleanup_quarantined_roots(directory: Path) -> None:
    """Bounded worker-only retention; foreground open only renames roots."""
    candidates = sorted(directory.glob(".read-model-quarantine-*"),
                        key=lambda path: path.lstat().st_mtime_ns, reverse=True)
    for path in candidates[2:]:
        if path.is_symlink() or path.parent.resolve() != directory.resolve():
            continue
        if path.is_dir():
            shutil.rmtree(path)


def main() -> int:
    try:
        first = sys.stdin.buffer.readline()
        events, reads, token = open_stores(first)
    except Exception:
        return 1
    try:
        _cleanup_quarantined_roots(events.path.parent)
        while True:
            try:
                answer = {"state": reads.synchronize(events).state, "token": token}
            except Exception:
                # A synchronization failure is recoverable: the worker keeps
                # its already-derived keys and can retry without asking the
                # foreground process to retain or resend the passphrase.
                answer = {"state": "degraded", "token": token}
            sys.stdout.write(json.dumps(answer, separators=(",", ":")) + "\n")
            sys.stdout.flush()
            command = sys.stdin.buffer.readline()
            if not command:
                break
            try:
                request = json.loads(command.decode("utf-8"))
            except Exception:
                break
            if (not isinstance(request, dict)
                    or set(request) != {"command", "token"}
                    or request.get("command") != "synchronize"
                    or not isinstance(request.get("token"), str)
                    or not 32 <= len(request["token"]) <= 128):
                break
            token = request["token"]
        return 0
    finally:
        reads.close()
