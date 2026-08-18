"""Injected vault-backed surface reads and progress contracts.

This module deliberately knows neither the vault implementation nor the desktop
transport. A sidecar entry point can inject a provider and a progress sink.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from .handlers import BridgeRequestError

ProgressStatus = Literal["started", "completed", "failed"]


@dataclass(frozen=True)
class JobProgressEvent:
    """A JSON-safe progress update emitted during one surface read."""

    job_id: str
    status: ProgressStatus
    completed: int
    total: int
    message: str = ""

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id must be a non-empty string")
        if self.completed < 0 or self.total < 0 or self.completed > self.total:
            raise ValueError("completed must be between zero and total")
        if self.status == "completed" and self.completed != self.total:
            raise ValueError("completed events must reach total")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
