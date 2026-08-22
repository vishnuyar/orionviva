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
    SETTINGS_READ,
    SURFACE_READ,
    action_operations_for,
    operation_names,
    serialize_registry,
    served_destinations,
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
TRANSFER_CAPABILITY = "vault.transfer"
TRANSFER_OPERATIONS = action_operations_for(TRANSFER_CAPABILITY)
MAINTENANCE_CAPABILITY = "maintenance.agent"
MAINTENANCE_OPERATIONS = action_operations_for(MAINTENANCE_CAPABILITY)
CONVERSATION_CAPABILITY = "conversation.viva"
CONVERSATION_OPERATIONS = action_operations_for(CONVERSATION_CAPABILITY)
RESCAN_CAPABILITY = "documents.rescan"
RESCAN_OPERATIONS = action_operations_for(RESCAN_CAPABILITY)
SETTINGS_CAPABILITY = "settings.configuration"
SETTINGS_OPERATIONS = action_operations_for(SETTINGS_CAPABILITY)


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
    """Who answered, and which build of it.

    The revision belongs here rather than on a trust read because the handshake
    is the one exchange that happens before anything else and without a vault:
    a build that cannot open a vault, or that opens one and answers wrongly, is
    exactly the build whose identity somebody needs. It is read, never guessed,
    and a build that cannot establish its own says the word for that."""
    from viva.revision import source_revision

    if payload:
        raise BridgeRequestError(f"{BRIDGE_HANDSHAKE} does not accept payload fields")
    return {"protocol": CURRENT_PROTOCOL.wire(), "transport": "json-lines",
            "revision": source_revision()}


def _surface_capabilities(payload: dict[str, Any]) -> dict[str, Any]:
    """Read the reviewed surface registry without crossing into vault code."""

    if payload:
        raise BridgeRequestError(
            f"{SURFACE_CAPABILITIES} does not accept payload fields"
        )
    return {
        "protocol": CURRENT_PROTOCOL.wire(),
        "capabilities": json.loads(serialize_registry()),
        # Which destinations a read actually reaches, derived from the registry
        # by the registry. The interface used to carry a hand-written
        # vocabulary in place of this, which is a second answer to a question
        # only one side can answer.
        "destinations": served_destinations(),
    }


def default_handlers() -> BridgeDispatcher:
    """Return the safe baseline allowlist for a newly started sidecar."""

    from .settings_actions import SettingsActions

    # Settings are in the baseline allowlist rather than the opened-vault one.
    # A person with no vault yet has to be able to say how figures are written
    # and whether a model may be reached at all, and a build that made them
    # open a vault first would have made configuration a thing you need a vault
    # to reach and a vault a thing you need configuration to use.
    settings = SettingsActions()
    return BridgeDispatcher({
        BRIDGE_HANDSHAKE: _handshake,
        SURFACE_CAPABILITIES: _surface_capabilities,
        SETTINGS_READ: settings.read,
        SETTINGS_OPERATIONS["propose"]: settings.propose,
        SETTINGS_OPERATIONS["confirm"]: settings.confirm,
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
    pump: Callable[[], None] | None = None,
) -> BridgeDispatcher:
    """Build the allowlist for one concrete, already-open product vault.

    One job registry is built here and handed to everything that needs it, so
    the handler that starts a job, the handler that stops one and the read that
    lists them are looking at the same jobs. Two registries would be two
    answers to the same question, and the one a person could see would not be
    the one their cancel reached.

    ``pump`` is what a running job calls between its steps to let a frame that
    arrived mid-job be read. The registry does not know what it does — the
    sidecar owns the transport — and a registry with none still records what
    happened, which is what makes this testable without a bridge.
    """

    from .conversation_actions import ConversationActions
    from .document_actions import DocumentActions
    from .jobs import JobRegistry
    from .review_actions import ReviewActions
    from .rescan_actions import RescanActions
    from .trust_actions import TrustActions
    from .vault_actions import VaultTransferActions
    from .vault_surface import OpenedVaultSurfaceProvider

    jobs = JobRegistry(progress_sink, pump)
    reads = handlers_with_surface_provider(
        OpenedVaultSurfaceProvider(vault, jobs), progress_sink
    )
    actions = ReviewActions(vault)
    captures = DocumentActions(vault, jobs)
    transfers = VaultTransferActions(vault, jobs)
    sweeps = RescanActions(vault, jobs)
    talking = ConversationActions(vault, jobs)
    trust = TrustActions(vault, jobs)
    return BridgeDispatcher({
        **reads.handlers,
        REVIEW_OPERATIONS["answer"]: actions.answer,
        REVIEW_OPERATIONS["decline"]: actions.decline,
        DOCUMENTS_OPERATIONS["upload"]: captures.upload,
        DOCUMENTS_OPERATIONS["cancel"]: captures.cancel,
        TRANSFER_OPERATIONS["export"]: transfers.export,
        TRANSFER_OPERATIONS["restore"]: transfers.restore,
        RESCAN_OPERATIONS["rescan"]: sweeps.run,
        CONVERSATION_OPERATIONS["ask"]: talking.ask,
        MAINTENANCE_OPERATIONS["run"]: trust.run,
        MAINTENANCE_OPERATIONS["diagnose"]: trust.diagnose,
    })
