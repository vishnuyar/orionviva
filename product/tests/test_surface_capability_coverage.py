"""Slice 0 coverage gates for the user-facing capability registry.

These tests deliberately exercise the registry as a public contract.  A new
backend action must either name its UI destination or explain why it remains
developer-only, internal, or deferred.
"""

import json

import pytest

from viva.surface.capabilities import (
    CapabilitySpec,
    Destination,
    Disposition,
    Maturity,
    TRUST_EFFECTS,
    capabilities,
    command_classifications,
    serialize_registry,
)


def test_registered_capabilities_have_unique_ids_and_complete_contracts():
    entries = tuple(capabilities())
    ids = [entry.id for entry in entries]

    assert entries, "the registry must not silently report an empty product"
    assert len(ids) == len(set(ids))
    for entry in entries:
        assert entry.owner
        assert entry.maturity in Maturity
        assert entry.disposition in Disposition
        assert entry.destination in Destination
        assert entry.availability
        assert entry.contract
        assert entry.trust_effect in TRUST_EFFECTS


def test_surface_capabilities_have_destinations():
    surfaced = [entry for entry in capabilities() if entry.disposition is Disposition.SURFACE]

    assert surfaced
    assert all(entry.destination is not Destination.NONE for entry in surfaced)
    assert all(entry.reason is None for entry in surfaced)


def test_non_surface_capabilities_have_explicit_disposition_and_reason():
    non_surface = [entry for entry in capabilities() if entry.disposition is not Disposition.SURFACE]

    assert non_surface
    assert all(entry.destination is Destination.NONE for entry in non_surface)
    assert all(entry.reason and entry.reason.strip() for entry in non_surface)


def test_surface_capabilities_have_allowlisted_actions_and_fixtures():
    for entry in capabilities():
        if entry.disposition is Disposition.SURFACE:
            assert entry.fixture_ids, entry.id
            assert all(action and action.strip() for action in entry.actions)


def test_command_entry_points_are_classified():
    classifications = command_classifications()

    assert classifications
    allowed = {Disposition.DEVELOPER_ONLY, Disposition.INTERNAL, Disposition.DEFERRED}
    for command, disposition in classifications.items():
        assert command
        assert disposition in allowed or disposition is Disposition.SURFACE


def test_registry_serialization_is_json_safe_and_deterministic():
    first = serialize_registry()
    second = serialize_registry()

    assert first == second
    assert json.loads(first) == json.loads(second)
    assert [entry["id"] for entry in json.loads(first)] == sorted(
        entry["id"] for entry in json.loads(first)
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"id": ""},
        {"owner": ""},
        {"availability": ""},
        {"contract": ""},
        {"disposition": "surface", "destination": "none"},
        {"disposition": "deferred", "destination": "overview", "reason": ""},
        {"disposition": "surface", "destination": "overview", "reason": "not needed"},
        {"trust_effect": "invented effect"},
    ],
)
def test_malformed_capability_contracts_fail(changes):
    values = dict(
        id="overview.read",
        owner="overview",
        maturity="stable",
        disposition="surface",
        destination="overview",
        availability="synthetic vault is open",
        contract="OverviewReadV1",
        actions=(),
        trust_effect="reads data",
        reason=None,
        fixture_ids=("overview-ready",),
    )
    values.update(changes)

    with pytest.raises((TypeError, ValueError)):
        CapabilitySpec(**values)
