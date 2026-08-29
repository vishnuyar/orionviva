"""The declared table of bridge operations and the contracts they serve.

Two consumers read this table. The bridge builds its handler map from it, so an
operation the sidecar serves is an operation named here. The registry reads it
to derive each capability's maturity.

An operation serves a contract when a caller of that operation receives that
contract's response. The table describes what the sidecar serves and never what
a client calls, so nothing here depends on reading frontend source.

Reads are declared here. Actions are derived: one operation per action the
capability registry declares, so the table holds every operation that can touch
a vault and adding an action is a change to the registry rather than to this
file.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import capability_for, capability_registry


BRIDGE_HANDSHAKE = "bridge.handshake"
BRIDGE_OPEN_VAULT = "bridge.open_vault"
# The sample vault, opened from one affordance. It is its own operation rather
# than a flag on the one above, because the demo names neither a directory nor
# a passphrase: both are the engine's, so a caller has nowhere to point it at a
# directory of their own and nowhere to learn what opens it.
BRIDGE_OPEN_DEMO_VAULT = "bridge.open_demo_vault"
SURFACE_CAPABILITIES = "viva.surface.capabilities"
SURFACE_READ = "viva.surface.read"
# What is in force, asked without a vault. It is not a surface read: a surface
# read opens a vault, and this question has an answer before one exists.
SETTINGS_READ = "viva.settings.read"
# What happens to this application when a new version exists. Asked without a
# vault for the same reason settings are: a person meets this question before
# they have opened anything, and the answer does not depend on what they open.
LIFECYCLE_READ = "viva.lifecycle.read"


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


# The operations that answer with a read model. Each names the contracts a
# caller of it receives, which is what the registry's maturity is derived from.
DECLARED_OPERATIONS: tuple[BridgeOperation, ...] = (
    BridgeOperation(BRIDGE_HANDSHAKE),
    BridgeOperation(BRIDGE_OPEN_VAULT),
    BridgeOperation(BRIDGE_OPEN_DEMO_VAULT),
    BridgeOperation(SURFACE_CAPABILITIES),
    BridgeOperation(SURFACE_READ, serves=("AccountOverview.v2", "ObligationsAndFindings.v1",
                                         "CurrentPeriodControl.v1",
                                         "QuestionQueue.v1",
                                         "JobRegistry.v1", "OutboundRecord.v1",
                                         "ActivityMovements.v3")),
    BridgeOperation(SETTINGS_READ, serves=("Configuration.v1",)),
    BridgeOperation(LIFECYCLE_READ, serves=("UpdateLifecycle.v1",)),
)


def action_operation_name(capability_id: str, action: str) -> str:
    """The operation one declared action is reached by.

    An action is reached under the family its capability belongs to — the first
    segment of the capability id — so every action of one family shares a
    prefix and no operation has to be written down twice.
    """
    family = capability_id.split(".", 1)[0].strip()
    verb = action.strip()
    if not family or not verb:
        raise ValueError("an action operation needs a capability family and an action")
    return f"viva.{family}.{verb}"


def action_operations() -> tuple[BridgeOperation, ...]:
    """One operation per action the capability registry declares.

    None of them serves a capability contract: an action answers with what
    happened, which is not a read model any capability names.

    Raises ValueError when two capabilities of one family declare the same
    action, which would derive one operation name for both and leave one of
    them unreachable.
    """
    claimed: dict[str, str] = {}
    for capability in capability_registry():
        for action in capability.actions:
            name = action_operation_name(capability.id, action)
            if name in claimed:
                raise ValueError(
                    f"{name} would be the operation for an action of both "
                    f"{claimed[name]} and {capability.id}; one of them would "
                    "never be reached")
            claimed[name] = capability.id
    return tuple(BridgeOperation(name) for name in claimed)


def action_operations_for(capability_id: str) -> dict[str, str]:
    """Each action one capability declares, mapped to the operation it is
    reached by. A caller that names an action the capability dropped fails
    where it asks rather than at the far end of a bridge."""
    capability = capability_for(capability_id)
    return {action: action_operation_name(capability.id, action)
            for action in capability.actions}


BRIDGE_OPERATIONS: tuple[BridgeOperation, ...] = DECLARED_OPERATIONS + action_operations()


def operation_names() -> frozenset[str]:
    """Return every operation name the sidecar is allowed to serve."""
    return frozenset(operation.name for operation in BRIDGE_OPERATIONS)


def served_contracts() -> frozenset[str]:
    """Return every capability contract some operation delivers."""
    return frozenset(
        contract for operation in BRIDGE_OPERATIONS for contract in operation.serves
    )


def declared_contracts() -> frozenset[str]:
    """Return every response contract the capability registry declares."""
    return frozenset(
        capability.contract
        for capability in capability_registry()
        if capability.contract
    )


def validate_operations(
    operations: tuple[BridgeOperation, ...] = BRIDGE_OPERATIONS,
) -> None:
    """Reject a table that names one operation twice, or that claims to serve
    a contract no capability declares. Raises ValueError.

    Maturity is derived from what this table serves, so a served name matching
    no capability would report that capability reachable under a name nothing
    answers to."""
    names = [operation.name for operation in operations]
    if len(names) != len(set(names)):
        raise ValueError("bridge operation names must be unique")
    declared = declared_contracts()
    unknown = sorted({contract for operation in operations
                      for contract in operation.serves} - declared)
    if unknown:
        raise ValueError(
            "operations may only serve contracts the registry declares; "
            + ", ".join(unknown) + " is served by no capability")


validate_operations()
