"""Allowlisted bridge handlers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from viva.surface import (
    BRIDGE_HANDSHAKE,
    CURRENT_PROTOCOL,
    SURFACE_CAPABILITIES,
    SURFACE_READ,
    action_operations_for,
    operation_names,
    serialize_registry,
)

# The capability whose actions an opened vault may serve, mapped to the
# operations they are reached by. The names come from the registry, so asking
# for an action it no longer declares raises here. A declared action with no
# handler below is not in the allowlist and is refused as an operation the
# sidecar does not serve.
REVIEW_CAPABILITY = "review.questions"
REVIEW_OPERATIONS = action_operations_for(REVIEW_CAPABILITY)
DOCUMENTS_CAPABILITY = "documents.ingest"
DOCUMENTS_OPERATIONS = action_operations_for(DOCUMENTS_CAPABILITY)


class BridgeRequestError(ValueError):
    """Raised by a bridge handler for an invalid operation payload."""


class BridgeDispatcher:
    """Own an immutable operation allowlist for one sidecar instance."""

    def __init__(self, handlers: Mapping[str, Callable[[dict[str, Any]], Any]]) -> None:
        undeclared = sorted(set(handlers) - operation_names())
        if undeclared:
            raise ValueError(
                "the bridge may only serve declared operations; undeclared: "
                + ", ".join(undeclared)
            )
        self._handlers = MappingProxyType(dict(handlers))

    @property
    def handlers(self) -> Mapping[str, Callable[[dict[str, Any]], Any]]:
        return self._handlers


def _handshake(payload: dict[str, Any]) -> dict[str, str]:
    if payload:
        raise BridgeRequestError(f"{BRIDGE_HANDSHAKE} does not accept payload fields")
    return {"protocol": CURRENT_PROTOCOL.wire(), "transport": "json-lines"}


def _surface_capabilities(payload: dict[str, Any]) -> dict[str, Any]:
    """Read the reviewed surface registry without crossing into vault code."""

    if payload:
        raise BridgeRequestError(
            f"{SURFACE_CAPABILITIES} does not accept payload fields"
        )
    return {
        "protocol": CURRENT_PROTOCOL.wire(),
        "capabilities": json.loads(serialize_registry()),
    }


def default_handlers() -> BridgeDispatcher:
    """Return the safe baseline allowlist for a newly started sidecar."""

    return BridgeDispatcher({
        BRIDGE_HANDSHAKE: _handshake,
        SURFACE_CAPABILITIES: _surface_capabilities,
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
        SURFACE_READ: reader.read,
    })


def handlers_for_opened_vault(
    vault: Any,
    progress_sink: Callable[[Any], None] | None = None,
) -> BridgeDispatcher:
    """Build the allowlist for one concrete, already-open product vault."""

    from .document_actions import DocumentActions
    from .review_actions import ReviewActions
    from .vault_surface import OpenedVaultSurfaceProvider

    reads = handlers_with_surface_provider(
        OpenedVaultSurfaceProvider(vault), progress_sink
    )
    actions = ReviewActions(vault)
    captures = DocumentActions(vault)
    return BridgeDispatcher({
        **reads.handlers,
        REVIEW_OPERATIONS["decline"]: actions.decline,
        DOCUMENTS_OPERATIONS["upload"]: captures.upload,
    })
