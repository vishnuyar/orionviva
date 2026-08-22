"""Injected vault-backed surface reads and progress contracts.

This module deliberately knows neither the vault implementation nor the desktop
transport. A sidecar entry point can inject a provider and a progress sink.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from .handlers import BridgeRequestError
from .jobs import JobProgressEvent, ProgressStatus

# A read is one step, and it is finished by the time the frame it answers is
# written. It therefore takes no registry entry: a row that appears and
# vanishes before anything could show it is not a job a person can be told
# about, and it would push the jobs a person *can* be told about out of a
# bounded registry. What a read does carry is the pair of events that bracket
# it, which is what a caller correlates against the identity it sent.
__all__ = [
    "JobProgressEvent",
    "ProgressStatus",
    "ProgressSink",
    "VaultSurfaceProvider",
    "VaultSurfaceReader",
]


class VaultSurfaceProvider(Protocol):
    """Read one named surface from an already-open vault."""

    def read_surface(
        self, surface: str, parameters: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


ProgressSink = Callable[[JobProgressEvent], None]


class VaultSurfaceReader:
    """Adapt an injected vault provider into an allowlisted bridge handler."""

    def __init__(
        self,
        provider: VaultSurfaceProvider,
        progress_sink: ProgressSink | None = None,
    ) -> None:
        self._provider = provider
        self._progress_sink = progress_sink

    def read(self, payload: dict[str, Any]) -> dict[str, Any]:
        surface, parameters, job_id = _read_request(payload)
        self._emit(JobProgressEvent(job_id, "started", 0, 1, f"reading {surface}"))
        try:
            result = self._provider.read_surface(surface, parameters)
            if not isinstance(result, Mapping):
                raise TypeError("surface provider must return a mapping")
            json.dumps(result)
        except Exception as exc:
            self._emit(JobProgressEvent(job_id, "failed", 0, 1, str(exc)))
            raise
        self._emit(JobProgressEvent(job_id, "completed", 1, 1, f"read {surface}"))
        return {
            "surface": surface,
            "job_id": job_id,
            "data": dict(result),
        }

    def _emit(self, event: JobProgressEvent) -> None:
        if self._progress_sink is not None:
            self._progress_sink(event)


def _read_request(payload: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], str]:
    allowed = {"surface", "parameters", "job_id"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            f"viva.surface.read does not accept fields: {', '.join(sorted(unexpected))}"
        )
    surface = payload.get("surface")
    if not isinstance(surface, str) or not surface.strip():
        raise BridgeRequestError("surface must be a non-empty string")
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, Mapping):
        raise BridgeRequestError("parameters must be an object")
    job_id = payload.get("job_id", "surface-read")
    if not isinstance(job_id, str) or not job_id.strip():
        raise BridgeRequestError("job_id must be a non-empty string")
    return surface, dict(parameters), job_id
