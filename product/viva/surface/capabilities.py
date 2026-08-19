"""Static inventory of capabilities that may cross the product boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .operations import served_contracts


class CapabilityMaturity(StrEnum):
    PREVIEW = "preview"
    STABLE = "stable"


class CapabilityDisposition(StrEnum):
    SURFACE = "surface"
    DEVELOPER_ONLY = "developer_only"
    INTERNAL = "internal"
    DEFERRED = "deferred"


class CapabilityDestination(StrEnum):
    OVERVIEW = "overview"
    ACCOUNT = "account"
    ACTIVITY = "activity"
    DOCUMENTS = "documents"
    REVIEW = "review"
    VIVA = "viva"
    TRUST = "trust"
    SETTINGS = "settings"
    NONE = "none"


class TrustEffect(StrEnum):
    READS_DATA = "reads_data"
    WRITES_EVENT = "writes_event"
    MAY_CALL_MODEL = "may_call_model"
    MAY_EGRESS = "may_egress"


# Short names keep the registry readable for contract and coverage consumers.
Maturity = CapabilityMaturity
Disposition = CapabilityDisposition
Destination = CapabilityDestination


@dataclass(frozen=True)
class CapabilitySpec:
    """The reviewed disposition and contract for one product capability."""

    id: str
    owner: str
    disposition: CapabilityDisposition
    destination: CapabilityDestination
    availability: str
    contract: str | None = None
    actions: tuple[str, ...] = ()
    trust_effect: tuple[TrustEffect, ...] = ()
    reason: str | None = None
    entrypoint: str | None = None
    fixture_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = (self.id, self.owner, self.availability)
        if any(not value.strip() for value in required):
            raise ValueError("capabilities require id, owner, and availability")
        if self.disposition == CapabilityDisposition.SURFACE:
            if self.destination == CapabilityDestination.NONE:
                raise ValueError("surfaced capabilities require a destination")
            if not self.contract:
                raise ValueError("surfaced capabilities require a contract")
            if self.reason:
                raise ValueError("surfaced capabilities do not require a reason")
        elif not self.reason or not self.reason.strip():
            raise ValueError("non-surfaced capabilities require a reason")

        if self.contract is None:
            raise ValueError("capabilities require a response contract")
        if self.disposition == CapabilityDisposition.SURFACE and not self.fixture_ids:
            raise ValueError("surfaced capabilities require fixture ids")

        if any(not action.strip() for action in self.actions):
            raise ValueError("capability actions must be non-empty")
        if not isinstance(self.trust_effect, tuple) or not all(
            isinstance(effect, TrustEffect) for effect in self.trust_effect
        ):
            raise TypeError("trust_effect must be a tuple of TrustEffect values")

    @property
    def maturity(self) -> CapabilityMaturity:
        """Return `stable` when an operation serves this contract, else `preview`.

        Reachability is the only input; nothing else moves this value.
        """
        if self.contract and self.contract in served_contracts():
            return CapabilityMaturity.STABLE
        return CapabilityMaturity.PREVIEW


def _surface(
    id: str,
    owner: str,
    destination: CapabilityDestination,
    availability: str,
    contract: str,
    actions: tuple[str, ...],
    trust_effect: tuple[TrustEffect, ...],
    *,
    entrypoint: str | None = None,
) -> CapabilitySpec:
    return CapabilitySpec(
        id=id,
        owner=owner,
        disposition=CapabilityDisposition.SURFACE,
        destination=destination,
        availability=availability,
        contract=contract,
        actions=actions,
        trust_effect=trust_effect,
        fixture_ids=(f"{id}.ready",),
        entrypoint=entrypoint,
    )


def _classified(
    id: str,
    owner: str,
    disposition: CapabilityDisposition,
    reason: str,
    *,
    entrypoint: str | None = None,
    trust_effect: tuple[TrustEffect, ...] = (),
) -> CapabilitySpec:
    return CapabilitySpec(
        id=id,
        owner=owner,
        disposition=disposition,
        destination=CapabilityDestination.NONE,
        availability="available to the local engine",
        contract="DeveloperDiagnostic.v1",
        trust_effect=trust_effect,
        reason=reason,
        entrypoint=entrypoint,
    )


CAPABILITIES: tuple[CapabilitySpec, ...] = (
    _surface(
        "overview.accounts",
        "viva.surface.overview",
        CapabilityDestination.OVERVIEW,
        "when a vault is open",
        "AccountOverview.v1",
        (),
        # This read writes no event, calls no model and sends nothing outward.
        (TrustEffect.READS_DATA,),
    ),
    _surface(
        "review.questions",
        "viva.ask",
        CapabilityDestination.REVIEW,
        "when the vault has open questions",
        "QuestionQueue.v1",
        ("answer", "decline"),
        (TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT),
        entrypoint="viva.ask",
    ),
    _surface(
        "conversation.viva",
        "viva.speak",
        CapabilityDestination.VIVA,
        "when the vault is open and the conversation engine is configured",
        "ConversationTurn.v1",
        (),
        (TrustEffect.READS_DATA, TrustEffect.MAY_CALL_MODEL, TrustEffect.WRITES_EVENT),
        entrypoint="viva.speak",
    ),
    _surface(
        "documents.ingest",
        "viva.ingest",
        CapabilityDestination.DOCUMENTS,
        "when a local document is selected or dropped",
        "DocumentIngestResult.v1",
        ("upload", "cancel"),
        (
            TrustEffect.READS_DATA,
            TrustEffect.WRITES_EVENT,
            TrustEffect.MAY_CALL_MODEL,
            TrustEffect.MAY_EGRESS,
        ),
    ),
    _surface(
        "documents.rescan",
        "viva.rescan",
        CapabilityDestination.DOCUMENTS,
        "after a document has been ingested",
        "RescanResult.v1",
        (),
        (TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT),
        entrypoint="viva.rescan",
    ),
    _surface(
        "maintenance.agent",
        "viva.agent",
        CapabilityDestination.TRUST,
        "when unattended maintenance is explicitly enabled",
        "MaintenanceRun.v1",
        ("run",),
        (TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT, TrustEffect.MAY_CALL_MODEL),
        entrypoint="viva.agent",
    ),
    _classified(
        "maintenance.merchant_enrichment",
        "viva.enrich",
        CapabilityDisposition.DEFERRED,
        "model-bound merchant enrichment needs a reviewed privacy boundary before it is surfaced",
        entrypoint="viva.enrich",
        trust_effect=(TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT, TrustEffect.MAY_CALL_MODEL, TrustEffect.MAY_EGRESS),
    ),
    _classified(
        "maintenance.grammar_induction",
        "viva.induce_profile",
        CapabilityDisposition.INTERNAL,
        "private maintenance is audited by the engine and is not an ordinary product destination",
        entrypoint="viva.induce_profile",
        trust_effect=(TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT, TrustEffect.MAY_CALL_MODEL),
    ),
    _classified(
        "diagnostic.stream_report",
        "viva.streams_report",
        CapabilityDisposition.DEVELOPER_ONLY,
        "diagnostic report for engine development; selected findings may later feed Activity",
        entrypoint="viva.streams_report",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "diagnostic.transfer_report",
        "viva.transfer_report",
        CapabilityDisposition.DEVELOPER_ONLY,
        "diagnostic report for transfer matching and repair review",
        entrypoint="viva.transfer_report",
        trust_effect=(TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT),
    ),
    _classified(
        "diagnostic.pattern_report",
        "viva.pattern_report",
        CapabilityDisposition.DEVELOPER_ONLY,
        "diagnostic report; it describes recurrence but does not decide a user-facing finding",
        entrypoint="viva.pattern_report",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "diagnostic.gaps",
        "viva.debug.gaps",
        CapabilityDisposition.DEVELOPER_ONLY,
        "debug diagnostic output is not a product read model",
        entrypoint="viva.debug.gaps",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "diagnostic.categories",
        "viva.debug.categories",
        CapabilityDisposition.DEVELOPER_ONLY,
        "category diagnostics inspect engine projections and are not a product read model",
        entrypoint="viva.debug.categories",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "diagnostic.claim",
        "viva.debug.claim",
        CapabilityDisposition.DEVELOPER_ONLY,
        "claim inspection exposes internal evidence and is reserved for development",
        entrypoint="viva.debug.claim",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "diagnostic.descriptors",
        "viva.debug.descriptors",
        CapabilityDisposition.DEVELOPER_ONLY,
        "descriptor diagnostics expose raw recognition details outside the product surface",
        entrypoint="viva.debug.descriptors",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "diagnostic.networth",
        "viva.debug.networth",
        CapabilityDisposition.DEVELOPER_ONLY,
        "debug diagnostic output is not the canonical financial picture",
        entrypoint="viva.debug.networth",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "diagnostic.read",
        "viva.debug.read",
        CapabilityDisposition.DEVELOPER_ONLY,
        "document reader trace is a development diagnostic, not a rendered journey",
        entrypoint="viva.debug.read",
        trust_effect=(TrustEffect.READS_DATA, TrustEffect.MAY_CALL_MODEL),
    ),
    _classified(
        "diagnostic.speak",
        "viva.debug.speak",
        CapabilityDisposition.DEVELOPER_ONLY,
        "conversation trace is a development diagnostic, not a second conversation surface",
        entrypoint="viva.debug.speak",
        trust_effect=(TrustEffect.READS_DATA, TrustEffect.MAY_CALL_MODEL),
    ),
    _classified(
        "diagnostic.tiers",
        "viva.debug.tiers",
        CapabilityDisposition.DEVELOPER_ONLY,
        "tier diagnostics explain engine question states and are not the Review contract",
        entrypoint="viva.debug.tiers",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "diagnostic.vault",
        "viva.debug.vault",
        CapabilityDisposition.DEVELOPER_ONLY,
        "vault inspection exposes internal storage details unsuitable for the ordinary UI",
        entrypoint="viva.debug.vault",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "advanced.rebuild",
        "viva.rebuild",
        CapabilityDisposition.DEVELOPER_ONLY,
        "rebuild creates a new vault and belongs to the advanced vault laboratory",
        entrypoint="viva.rebuild",
        trust_effect=(TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT),
    ),
    _classified(
        "advanced.reingest",
        "viva.reingest",
        CapabilityDisposition.DEVELOPER_ONLY,
        "reingest is an advanced migration operation requiring a fresh vault",
        entrypoint="viva.reingest",
        trust_effect=(TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT, TrustEffect.MAY_CALL_MODEL),
    ),
    _classified(
        "advanced.reset_categorization",
        "viva.reset_categorization",
        CapabilityDisposition.DEVELOPER_ONLY,
        "categorization reset rewrites a derived vault and is not ordinary settings",
        entrypoint="viva.reset_categorization",
        trust_effect=(TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT),
    ),
    _classified(
        "advanced.export_rulings",
        "viva.export_rulings",
        CapabilityDisposition.DEVELOPER_ONLY,
        "ruling export contains personal data and requires an explicit advanced privacy warning",
        entrypoint="viva.export_rulings",
        trust_effect=(TrustEffect.READS_DATA, TrustEffect.MAY_EGRESS),
    ),
    _classified(
        "advanced.diff_rulings",
        "viva.diff_rulings",
        CapabilityDisposition.DEVELOPER_ONLY,
        "ruling comparison is rebuild evaluation tooling, not a user-facing action",
        entrypoint="viva.diff_rulings",
        trust_effect=(TrustEffect.READS_DATA,),
    ),
    _classified(
        "evaluation.listen",
        "viva.eval_listen",
        CapabilityDisposition.DEVELOPER_ONLY,
        "model evaluation is CI and developer tooling only",
        entrypoint="viva.eval_listen",
        trust_effect=(TrustEffect.MAY_CALL_MODEL,),
    ),
)


def capability_registry() -> tuple[CapabilitySpec, ...]:
    """Return the immutable, reviewed capability inventory."""
    return CAPABILITIES


def capabilities() -> tuple[CapabilitySpec, ...]:
    """Compatibility name for coverage tools consuming the public registry."""
    return capability_registry()


def command_classifications() -> dict[str, CapabilityDisposition]:
    """Map every registered command entry point to its reviewed disposition."""
    return {
        capability.entrypoint: capability.disposition
        for capability in CAPABILITIES
        if capability.entrypoint is not None
    }


def serialize_registry() -> str:
    """Return a stable JSON representation suitable for drift checks."""
    import json

    entries = []
    for capability in sorted(CAPABILITIES, key=lambda item: item.id):
        entries.append({
            "id": capability.id,
            "owner": capability.owner,
            "maturity": capability.maturity.value,
            "disposition": capability.disposition.value,
            "destination": capability.destination.value,
            "availability": capability.availability,
            "contract": capability.contract,
            "actions": list(capability.actions),
            "trust_effect": [effect.value for effect in capability.trust_effect],
            "reason": capability.reason,
            "entrypoint": capability.entrypoint,
            "fixture_ids": list(capability.fixture_ids),
        })
    return json.dumps(entries, indent=2, sort_keys=True)


def capability_for(capability_id: str) -> CapabilitySpec:
    for capability in CAPABILITIES:
        if capability.id == capability_id:
            return capability
    raise KeyError(capability_id)


def validate_registry(capabilities: tuple[CapabilitySpec, ...] = CAPABILITIES) -> None:
    """Reject duplicate ids or entry points before a registry is consumed."""
    ids = [capability.id for capability in capabilities]
    if len(ids) != len(set(ids)):
        raise ValueError("capability ids must be unique")
    entrypoints = [capability.entrypoint for capability in capabilities if capability.entrypoint]
    if len(entrypoints) != len(set(entrypoints)):
        raise ValueError("capability entrypoints must be unique")


validate_registry()
