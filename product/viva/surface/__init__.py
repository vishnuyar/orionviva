"""Transport-independent contracts for user-facing product surfaces."""

from .capabilities import (
    CAPABILITIES,
    Destination,
    Disposition,
    Maturity,
    CapabilityDestination,
    CapabilityDisposition,
    CapabilityMaturity,
    CapabilitySpec,
    TrustEffect,
    TRUST_EFFECTS,
    capabilities,
    capability_for,
    capability_registry,
    command_classifications,
    serialize_registry,
    validate_registry,
)
from .models import ActionOutcome, FigureView, PanelState
from .protocol import CURRENT_PROTOCOL, ProtocolVersion, ProtocolVersionError

__all__ = [
    "ActionOutcome",
    "CAPABILITIES",
    "Destination",
    "Disposition",
    "Maturity",
    "CapabilityDestination",
    "CapabilityDisposition",
    "CapabilityMaturity",
    "CapabilitySpec",
    "CURRENT_PROTOCOL",
    "FigureView",
    "PanelState",
    "ProtocolVersion",
    "ProtocolVersionError",
    "TrustEffect",
    "TRUST_EFFECTS",
    "capabilities",
    "capability_for",
    "capability_registry",
    "command_classifications",
    "serialize_registry",
    "validate_registry",
]
