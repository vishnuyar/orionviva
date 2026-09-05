"""Static inventory of capabilities that may cross the product boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapabilityMaturity(StrEnum):
    PREVIEW = "preview"
    STABLE = "stable"


class CapabilityDisposition(StrEnum):
    SURFACE = "surface"
    DEVELOPER_ONLY = "developer_only"
    INTERNAL = "internal"
    DEFERRED = "deferred"


class CapabilityDestination(StrEnum):
    """Where in the interface a capability is reached, in interface spelling."""

    OVERVIEW = "overview"
    ACCOUNTS = "accounts"
    REVIEW = "review"
    ACTIVITY = "activity"
    DOCUMENTS = "documents"
    VIVA = "viva"
    TRUST = "trust"
    SETTINGS = "settings"
    PLANS = "plans"
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

        Reachability is the only input; nothing else moves this value. The
        operation table is imported where the question is put rather than at
        module level, because the table is derived from this registry.
        """
        from .operations import served_contracts

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
    fixture_states: tuple[str, ...] = ("ready",),
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
        fixture_ids=tuple(f"{id}.{state}" for state in fixture_states),
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
        "AccountOverview.v2",
        (),
        # This read writes no event, calls no model and sends nothing outward.
        (TrustEffect.READS_DATA,),
    ),
    _surface(
        "overview.spending",
        "viva.surface.spending",
        CapabilityDestination.OVERVIEW,
        "when a vault is open",
        "SpendingBreakdown.v1",
        (),
        (TrustEffect.READS_DATA,),
        fixture_states=("ready", "empty"),
    ),
    _surface(
        "accounts.ledger",
        "viva.surface.account_ledger",
        CapabilityDestination.ACCOUNTS,
        "when a vault is open and one exact account is requested",
        "AccountLedger.v1",
        (),
        # Pagination and evidence reads remain deterministic and local.
        (TrustEffect.READS_DATA,),
    ),
    _surface(
        "overview.obligations",
        "viva.surface.obligations",
        CapabilityDestination.OVERVIEW,
        "when a vault is open and its records support an obligation or finding",
        "ObligationsAndFindings.v1",
        ("set_aside_finding",),
        # The read is deterministic and local. Setting one finding aside writes
        # only its identity and evidence stake; it changes no financial row.
        (TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT),
    ),
    _surface(
        "overview.current_period",
        "viva.surface.current_period",
        CapabilityDestination.OVERVIEW,
        "when a vault holds an issuer-backed depository balance",
        "CurrentPeriodControl.v1",
        (),
        (TrustEffect.READS_DATA,),
        fixture_states=("ready", "limited", "refused"),
    ),
    _surface(
        "plans.goals",
        "viva.surface.plans",
        CapabilityDestination.PLANS,
        "when a vault is open; shown after a goal exists or a draft is requested",
        "GoalsAndPlans.v1",
        ("draft", "propose", "confirm", "decline"),
        (TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT),
        fixture_states=("absent", "ready", "needs_input", "partial",
                        "refused", "open", "completed", "stale"),
    ),
    _surface(
        "review.attention",
        "viva.surface.review",
        CapabilityDestination.REVIEW,
        "when a vault is open",
        "ReviewSummary.v1",
        (),
        (TrustEffect.READS_DATA,),
        fixture_states=("ready", "empty"),
    ),
    _surface(
        "conversation.viva",
        "viva.conversation",
        CapabilityDestination.VIVA,
        "when a vault is open",
        "ConversationTimeline.v1",
        # The deterministic queue and question verbs share this conversation.
        ("ask", "answer", "confirm", "decline"),
        (TrustEffect.READS_DATA, TrustEffect.MAY_CALL_MODEL,
         TrustEffect.MAY_EGRESS, TrustEffect.WRITES_EVENT),
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
        "activity.movements",
        "viva.surface.activity",
        CapabilityDestination.ACTIVITY,
        "when a vault is open",
        "ActivityMovements.v3",
        ("assign_category", "assign_classification", "assign_meaning",
         "replace_tags", "add_tags", "remove_tags", "confirm_transfer",
         "reject_transfer", "unlink_transfer"),
        # The local read and movement actions use no model or egress.
        (TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT),
    ),
    _surface(
        "documents.jobs",
        "viva.desktop_bridge.jobs",
        CapabilityDestination.DOCUMENTS,
        "while the sidecar holds an open vault",
        "JobRegistry.v1",
        (),
        # The registry is a list of what this process is doing. It opens no
        # projection, writes no event and reaches no model: the work it
        # describes does all of that, and the description of work is not the
        # work.
        (TrustEffect.READS_DATA,),
    ),
    _surface(
        "documents.rescan",
        "viva.rescan",
        CapabilityDestination.DOCUMENTS,
        "after a document has been ingested",
        "RescanResult.v1",
        # The action is named for what it does rather than for pressing it: the
        # operation is derived from the capability's family and this word, and
        # `viva.documents.run` would name a thing nobody could identify.
        ("rescan",),
        # It writes: links, heals and corroborations are events. It reaches no
        # model and sends nothing — going back over what is already held reads
        # nothing new, which is what keeps this action free and repeatable.
        (TrustEffect.READS_DATA, TrustEffect.WRITES_EVENT),
        entrypoint="viva.rescan",
    ),
    _surface(
        "settings.configuration",
        "viva.configuration",
        CapabilityDestination.SETTINGS,
        "always, with or without a vault open",
        "Configuration.v1",
        ("propose", "confirm"),
        # Proposing sends nothing and reaches nothing: it describes what would
        # change. Confirming a model is the moment bytes become able to leave,
        # which is why the pair is declared as one capability with `may_egress`
        # on it — a person is agreeing to the permission, not to a call.
        (TrustEffect.READS_DATA, TrustEffect.MAY_EGRESS),
        entrypoint="viva.configuration",
    ),
    _surface(
        "trust.lifecycle",
        "viva.surface.lifecycle",
        CapabilityDestination.TRUST,
        "always, with or without a vault open",
        "UpdateLifecycle.v1",
        (),
        # It folds what this process can establish about itself. It opens no
        # vault, reaches no network to ask whether a newer version exists, and
        # installs nothing: there is no update channel, and this read is where
        # that is said rather than implied by a screen having a section.
        (TrustEffect.READS_DATA,),
    ),
    _surface(
        "trust.outbound",
        "viva.surface.outbound",
        CapabilityDestination.TRUST,
        "when a vault is open",
        "OutboundRecord.v1",
        (),
        # It reads the log and nothing else. The record describes calls that
        # were made; describing them makes none, and this read reaches no model
        # and sends nothing.
        (TrustEffect.READS_DATA,),
    ),
    _surface(
        "vault.transfer",
        "viva.vault_transfer",
        CapabilityDestination.TRUST,
        "when a vault is open",
        "VaultTransfer.v1",
        ("export", "restore"),
        # Neither action decrypts anything to travel and neither touches the
        # open vault in place: the export reads the files this vault is made of
        # and writes them elsewhere, and the restore writes into a directory
        # that holds nothing. Nothing here writes an event into this vault and
        # nothing reaches the network — a copy on this machine is not egress,
        # and what a person then does with that file is theirs.
        (TrustEffect.READS_DATA,),
        entrypoint="viva.vault_transfer",
    ),
    _surface(
        "maintenance.agent",
        "viva.agent",
        CapabilityDestination.TRUST,
        "when unattended maintenance is explicitly enabled",
        "MaintenanceRun.v1",
        # Running is one action; writing a file somebody can send is the other.
        # They are one capability because they are the same destination and the
        # same question — what has this product been doing, and can I show
        # somebody — and splitting them would put half the answer under a
        # capability nobody would look for.
        ("run", "diagnose"),
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
        "tier diagnostics explain engine question states and are not the conversation contract",
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


def served_destinations() -> dict[str, bool]:
    """Every destination the registry declares, and whether a read reaches it.

    A destination is served when some surfaced capability aimed at it has a
    contract an operation actually delivers — which is the same question
    maturity asks, asked one level up. It is derived here rather than on the
    far side of a bridge because two derivations of one rule are two rules, and
    the one a person would meet is the one nobody reviewed.

    `none` is in the answer and is never served: it is how the registry says a
    capability has no destination at all, and leaving it out would make its
    absence look like an oversight rather than a statement.
    """
    served = {destination.value: False for destination in CapabilityDestination}
    for capability in CAPABILITIES:
        if capability.disposition is not CapabilityDisposition.SURFACE:
            continue
        if capability.destination is CapabilityDestination.NONE:
            continue
        if capability.maturity is CapabilityMaturity.STABLE:
            served[capability.destination.value] = True
    served[CapabilityDestination.NONE.value] = False
    return served


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
