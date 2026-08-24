"""Slice 0 coverage gates for the user-facing capability registry.

These tests deliberately exercise the registry as a public contract.  A new
backend action must either name its UI destination or explain why it remains
developer-only, internal, or deferred.
"""

import json
from dataclasses import fields
from importlib import import_module

import pytest

from viva.surface.operations import (
    BRIDGE_OPERATIONS,
    DECLARED_OPERATIONS,
    BridgeOperation,
    action_operation_name,
    action_operations,
    declared_contracts,
    operation_names,
    served_contracts,
    validate_operations,
)
from viva.surface.capabilities import (
    CapabilitySpec,
    Destination,
    Disposition,
    Maturity,
    TrustEffect,
    capabilities,
    capability_for,
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
        for effect in entry.trust_effect:
            assert isinstance(effect, TrustEffect), f"{entry.id} declares {effect!r}"


def test_overview_contract_advances_with_the_proof_presentation_shape():
    assert capability_for("overview.accounts").contract == "AccountOverview.v2"
    assert "AccountOverview.v2" in declared_contracts()
    assert "AccountOverview.v2" in served_contracts()
    assert "AccountOverview.v1" not in declared_contracts()


def test_maturity_is_read_from_the_operation_table_and_never_typed(monkeypatch):
    """Maturity is neither a field a person fills in nor a constant.

    Restating the derivation here would only compare the formula with itself.
    Instead the table is answered twice, and the reviewed contract artifact —
    regenerated and compared byte for byte — is what holds the values.
    """
    typed = [field.name for field in fields(CapabilitySpec) if field.name == "maturity"]

    assert not typed, (
        "maturity is derived from the operation table; a constructor field "
        "would let someone type one again"
    )
    assert BRIDGE_OPERATIONS, "the operation table must not be empty"

    served = served_contracts()
    entry = next(item for item in capabilities() if item.contract not in served)
    assert entry.maturity is Maturity.PREVIEW, (
        "no operation serves this contract, so it is not reachable"
    )
    monkeypatch.setattr(
        import_module("viva.surface.operations"),
        "served_contracts",
        lambda: frozenset({entry.contract}),
    )
    assert entry.maturity is Maturity.STABLE, (
        "maturity does not answer the operation table"
    )


def test_the_operation_table_is_the_actions_the_registry_declares():
    """The sidecar's operation table is meant to be read on its own as the
    complete list of what can touch a vault, so it is compared against the
    registry rather than trusted.

    Both sides are built. The table's action half is whatever it holds beyond
    the operations that answer with a read model; the registry's is one name
    per action any capability declares. An operation added by hand, or an
    action declared and never reachable, moves one side and not the other.
    """
    reads = {operation.name for operation in DECLARED_OPERATIONS}
    tabled = operation_names() - reads
    declared = {action_operation_name(entry.id, action)
                for entry in capabilities() for action in entry.actions}

    assert tabled == declared, (
        f"the table serves {sorted(tabled - declared)} that no capability "
        f"declares, and the registry declares {sorted(declared - tabled)} "
        f"that the table does not serve")


def test_an_action_operation_is_named_for_the_family_that_declares_it():
    """Two capabilities in one family reach their actions under one prefix, and
    an action of another family never lands there. The rule is checked on
    synthetic ids so that it holds for whatever the registry declares next."""
    same_family = {action_operation_name("family.first", "act"),
                   action_operation_name("family.second", "other")}
    prefixes = {name.rsplit(".", 1)[0] for name in same_family}

    assert len(prefixes) == 1, "one family reaches its actions under one prefix"
    assert action_operation_name("family.first", "act").endswith(".act")
    assert prefixes.isdisjoint(
        {action_operation_name("elsewhere.first", "act").rsplit(".", 1)[0]})
    with pytest.raises(ValueError):
        action_operation_name("family.first", "  ")


def test_two_actions_deriving_one_operation_name_fail_where_they_are_derived(monkeypatch):
    """Two capabilities of one family declaring the same action derive one
    operation name, which would leave one of them unreachable with the drift
    gate still green. The derivation refuses rather than overwriting, and the
    refusal names both capabilities."""
    def _capability(id: str) -> CapabilitySpec:
        return CapabilitySpec(
            id=id, owner="tests", disposition=Disposition.INTERNAL,
            destination=Destination.NONE, availability="in this test",
            contract="Synthetic.v1", actions=("act",), reason="a test fixture")

    monkeypatch.setattr(
        import_module("viva.surface.operations"), "capability_registry",
        lambda: (_capability("family.first"), _capability("family.second")))

    with pytest.raises(ValueError) as refused:
        action_operations()

    assert "family.first" in str(refused.value)
    assert "family.second" in str(refused.value)


def test_an_operation_may_only_serve_a_contract_some_capability_declares(monkeypatch):
    """Maturity is derived from what the table serves, so a served contract
    name matching no capability is refused rather than reporting that contract
    reachable under a name nothing answers to."""
    validate_operations((BridgeOperation(
        "viva.test.read", serves=(next(iter(declared_contracts())),)),))

    with pytest.raises(ValueError) as refused:
        validate_operations((BridgeOperation(
            "viva.test.read", serves=("NoCapabilityDeclares.v1",)),))

    assert "NoCapabilityDeclares.v1" in str(refused.value)


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
        {"trust_effect": ("invented effect",)},
        {"trust_effect": "reads data"},
        {"trust_effect": ("reads_data",)},
    ],
)
def test_malformed_capability_contracts_fail(changes):
    values = dict(
        id="overview.read",
        owner="overview",
        disposition="surface",
        destination="overview",
        availability="synthetic vault is open",
        contract="OverviewReadV1",
        actions=(),
        trust_effect=(TrustEffect.READS_DATA,),
        reason=None,
        fixture_ids=("overview-ready",),
    )
    values.update(changes)

    with pytest.raises((TypeError, ValueError)):
        CapabilitySpec(**values)
