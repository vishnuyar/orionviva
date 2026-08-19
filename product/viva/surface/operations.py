"""The declared table of bridge operations and the contracts they serve.

Two consumers read this table. The bridge builds its handler map from it, so an
operation the sidecar serves is an operation named here. The registry reads it
to derive each capability's maturity.

An operation serves a contract when a caller of that operation receives that
contract's response. The table describes what the sidecar serves and never what
a client calls, so nothing here depends on reading frontend source.
"""

from __future__ import annotations

from dataclasses import dataclass


BRIDGE_HANDSHAKE = "bridge.handshake"
BRIDGE_OPEN_VAULT = "bridge.open_vault"
SURFACE_CAPABILITIES = "viva.surface.capabilities"
SURFACE_READ = "viva.surface.read"


@dataclass(frozen=True)
class BridgeOperation:
    """One operation the sidecar serves, and the contracts it delivers."""

    name: str
    serves: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a bridge operation requires a name")
        if any(not contract.strip() for contract in self.serves):
            raise ValueError("a served contract name must be non-empty")


BRIDGE_OPERATIONS: tuple[BridgeOperation, ...] = (
    BridgeOperation(BRIDGE_HANDSHAKE),
    BridgeOperation(BRIDGE_OPEN_VAULT),
    BridgeOperation(SURFACE_CAPABILITIES),
    BridgeOperation(SURFACE_READ),
)


def operation_names() -> frozenset[str]:
    """Return every operation name the sidecar is allowed to serve."""
    return frozenset(operation.name for operation in BRIDGE_OPERATIONS)


def served_contracts() -> frozenset[str]:
    """Return every capability contract some operation delivers."""
    return frozenset(
        contract for operation in BRIDGE_OPERATIONS for contract in operation.serves
    )


def validate_operations(
    operations: tuple[BridgeOperation, ...] = BRIDGE_OPERATIONS,
) -> None:
    """Reject a table that names one operation twice."""
    names = [operation.name for operation in operations]
    if len(names) != len(set(names)):
        raise ValueError("bridge operation names must be unique")


validate_operations()
