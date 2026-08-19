import pytest

from viva.surface import (
    CAPABILITIES,
    CapabilityDestination,
    CapabilityDisposition,
    CapabilitySpec,
    capability_for,
    validate_registry,
)


def test_registry_classifies_every_registered_capability():
    validate_registry()
    assert {capability.id for capability in CAPABILITIES}
    assert all(capability.availability for capability in CAPABILITIES)
    assert all(
        capability.destination is not CapabilityDestination.NONE
        or capability.disposition is not CapabilityDisposition.SURFACE
        for capability in CAPABILITIES
    )


def test_surface_capabilities_have_rendering_contracts():
    surfaced = [
        capability
        for capability in CAPABILITIES
        if capability.disposition is CapabilityDisposition.SURFACE
    ]
    assert surfaced
    assert all(capability.contract for capability in surfaced)
    assert all(capability.destination is not CapabilityDestination.NONE for capability in surfaced)


def test_developer_only_capability_has_a_reason():
    diagnostic = capability_for("diagnostic.read")
    assert diagnostic.disposition is CapabilityDisposition.DEVELOPER_ONLY
    assert diagnostic.reason
    assert diagnostic.destination is CapabilityDestination.NONE


def test_capability_spec_rejects_unreviewed_dispositions():
    with pytest.raises(ValueError):
        CapabilitySpec(
            id="unreviewed",
            owner="test",
            disposition=CapabilityDisposition.DEVELOPER_ONLY,
            destination=CapabilityDestination.NONE,
            availability="available",
        )

