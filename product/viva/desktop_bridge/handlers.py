"""Allowlisted bridge handlers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from viva.surface import CURRENT_PROTOCOL, serialize_registry


class BridgeRequestError(ValueError):
    """Raised by a bridge handler for an invalid operation payload."""


class BridgeDispatcher:
    """Own an immutable operation allowlist for one sidecar instance."""

    def __init__(self, handlers: Mapping[str, Callable[[dict[str, Any]], Any]]) -> None:
        self._handlers = MappingProxyType(dict(handlers))

    @property
    def handlers(self) -> Mapping[str, Callable[[dict[str, Any]], Any]]:
        return self._handlers


def _handshake(payload: dict[str, Any]) -> dict[str, str]:
    if payload:
        raise BridgeRequestError("bridge.handshake does not accept payload fields")
    return {"protocol": CURRENT_PROTOCOL.wire(), "transport": "json-lines"}


def _surface_capabilities(payload: dict[str, Any]) -> dict[str, Any]:
    """Read the reviewed surface registry without crossing into vault code."""

    if payload:
        raise BridgeRequestError("viva.surface.capabilities does not accept payload fields")
    return {
        "protocol": CURRENT_PROTOCOL.wire(),
        "capabilities": json.loads(serialize_registry()),
    }


def default_handlers() -> BridgeDispatcher:
    """Return the safe baseline allowlist for a newly started sidecar."""

    return BridgeDispatcher({
        "bridge.handshake": _handshake,
        "viva.surface.capabilities": _surface_capabilities,
    })


def handlers_with_surface_provider(
    provider: Any,
    progress_sink: Callable[[Any], None] | None = None,
) -> BridgeDispatcher:
    """Build the default allowlist plus an injected vault surface read."""

    from .surface_read import VaultSurfaceReader

    reader = VaultSurfaceReader(provider, progress_sink)
    return BridgeDispatcher({
        **default_handlers().handlers,
        "viva.surface.read": reader.read,
    })


def handlers_for_opened_vault(
    vault: Any,
    progress_sink: Callable[[Any], None] | None = None,
) -> BridgeDispatcher:
    """Build the allowlist for one concrete, already-open product vault."""

    from .vault_surface import OpenedVaultSurfaceProvider

    return handlers_with_surface_provider(
        OpenedVaultSurfaceProvider(vault), progress_sink
    )
