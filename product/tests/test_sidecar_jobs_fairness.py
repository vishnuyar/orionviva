"""Real request-loop evidence for an unresponsive Jobs registry read."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import sys

from viva.desktop_bridge.rpc import CURRENT_PROTOCOL


ROOT = Path(__file__).resolve().parents[2]
CHILD_CODE = """
import threading
import viva.desktop_bridge.__main__ as bridge
from viva.desktop_bridge.handlers import BridgeDispatcher

gate = threading.Event()
opened_count = 0

class Vault:
    def __init__(self, identity):
        self.identity = identity
        self.closed = False
    def poll_read_store_worker(self): pass
    def close(self): self.closed = True

def candidate(payload):
    global opened_count
    if payload.get('fail'):
        raise RuntimeError('candidate refused')
    opened_count += 1
    return Vault(opened_count), False

def opened(vault, *_args):
    def read(payload):
        surface = payload['surface']
        if surface == 'jobs':
            gate.wait(30)
        if surface == 'release':
            gate.set()
        if vault.closed:
            raise RuntimeError('retired vault')
        return {'surface': surface, 'job_id': 'test',
                'data': {'state': 'ready', 'vault': vault.identity}}
    return BridgeDispatcher({'viva.surface.read': read})

bridge.OPEN_OPERATIONS['bridge.open_vault'] = candidate
bridge.handlers_for_opened_vault = opened
raise SystemExit(bridge.main())
"""


def _frame(request_id: str, operation: str, payload: dict) -> str:
    return json.dumps({"protocol": CURRENT_PROTOCOL.wire(), "request_id": request_id,
                       "operation": operation, "payload": payload}) + "\n"


def _answer(child: subprocess.Popen[bytes], timeout: float = 1.0) -> dict:
    assert child.stdout is not None
    ready, _, _ = select.select([child.stdout], [], [], timeout)
    assert ready, "the sidecar did not answer before the active-read deadline"
    return json.loads(child.stdout.readline())


def _child() -> subprocess.Popen[bytes]:
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "product"))
    return subprocess.Popen([sys.executable, "-c", CHILD_CODE], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, bufsize=0, env=environment)


def _send(child: subprocess.Popen[bytes], request_id: str, operation: str, payload: dict) -> None:
    assert child.stdin is not None
    child.stdin.write(_frame(request_id, operation, payload).encode())
    child.stdin.flush()


def test_blocked_jobs_handler_does_not_hold_priority_request_loop() -> None:
    child = _child()
    try:
        _send(child, "open", "bridge.open_vault", {})
        opened = _answer(child)
        assert opened["request_id"] == "open" and opened["ok"] is True, opened
        _send(child, "jobs", "viva.surface.read", {"surface": "jobs", "parameters": {}})
        _send(child, "priority", "viva.surface.read", {"surface": "overview_accounts", "parameters": {}})
        priority = _answer(child)
        assert priority["request_id"] == "priority", priority
        assert priority["ok"] is True
        _send(child, "second-jobs", "viva.surface.read", {"surface": "jobs", "parameters": {}})
        second = _answer(child)
        assert second["request_id"] == "second-jobs" and second["ok"] is False
        _send(child, "replace", "bridge.open_vault", {})
        retired = _answer(child)
        replacement = _answer(child)
        assert retired["request_id"] == "jobs" and retired["ok"] is False
        assert replacement["request_id"] == "replace" and replacement["ok"] is True
        _send(child, "new-jobs", "viva.surface.read", {"surface": "jobs", "parameters": {}})
        busy = _answer(child)
        assert busy["request_id"] == "new-jobs" and busy["ok"] is False
    finally:
        child.terminate()
        child.communicate(timeout=2)


def test_failed_candidate_keeps_old_vault_and_pending_jobs_reply() -> None:
    child = _child()
    try:
        _send(child, "open", "bridge.open_vault", {})
        assert _answer(child)["ok"] is True
        _send(child, "jobs", "viva.surface.read", {"surface": "jobs", "parameters": {}})
        _send(child, "failed-open", "bridge.open_vault", {"fail": True})
        failed = _answer(child)
        assert failed["request_id"] == "failed-open" and failed["ok"] is False
        _send(child, "priority", "viva.surface.read", {"surface": "overview_accounts", "parameters": {}})
        priority = _answer(child)
        assert priority["request_id"] == "priority" and priority["result"]["data"]["vault"] == 1
        _send(child, "duplicate", "viva.surface.read", {"surface": "jobs", "parameters": {}})
        duplicate = _answer(child)
        assert duplicate["request_id"] == "duplicate" and duplicate["ok"] is False
        _send(child, "release", "viva.surface.read", {"surface": "release", "parameters": {}})
        replies = [_answer(child) for _ in range(2)]
        assert {reply["request_id"] for reply in replies} == {"release", "jobs"}
        assert all(reply["ok"] is True and reply["result"]["data"]["vault"] == 1
                   for reply in replies)
        _send(child, "again", "viva.surface.read", {"surface": "jobs", "parameters": {}})
        again = _answer(child)
        assert again["request_id"] == "again" and again["ok"] is True
        assert again["result"]["data"]["vault"] == 1
    finally:
        child.terminate()
        child.communicate(timeout=2)
