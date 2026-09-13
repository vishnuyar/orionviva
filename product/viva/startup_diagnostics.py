"""Privacy-bounded timing records for desktop startup diagnosis.

The opt-in diagnostic channel accepts only enumerated operation and state values.
It excludes vault contents, paths, counts, and credentials.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from time import monotonic_ns
from typing import Iterator

_OPERATIONS = frozenset({
    "credential_kdf", "event_authenticated_snapshot", "projection_construction",
    "surface", "raw_store",
})
_STATES = frozenset({"started", "completed", "failed"})
_SURFACES = frozenset({
    "overview", "spending", "documents", "conversation", "review", "jobs",
    "trust", "activity", "account_ledger", "overview_accounts", "plans", "none",
})


def emit(operation: str, state: str, duration_ms: int = 0, *, surface: str = "none") -> None:
    """Write one allowlisted JSON record when startup diagnostics are enabled."""
    if os.environ.get("VIVA_STARTUP_DIAGNOSTICS") != "1":
        return
    if operation not in _OPERATIONS or state not in _STATES or surface not in _SURFACES:
        raise ValueError("diagnostic field is not allowlisted")
    record = {
        "kind": "viva.startup.span",
        "operation": operation,
        "surface": surface,
        "duration_ms": max(0, int(duration_ms)),
        "state": state,
    }
    print(json.dumps(record, separators=(",", ":"), sort_keys=True), file=sys.stderr, flush=True)


@contextmanager
def span(operation: str, *, surface: str = "none") -> Iterator[None]:
    """Bracket work with records containing timing and allowlisted identity only."""
    started = monotonic_ns()
    emit(operation, "started", surface=surface)
    try:
        yield
    except BaseException:
        emit(operation, "failed", (monotonic_ns() - started) // 1_000_000, surface=surface)
        raise
    emit(operation, "completed", (monotonic_ns() - started) // 1_000_000, surface=surface)
