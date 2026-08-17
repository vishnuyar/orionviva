"""Factory for the concrete opened-vault surface provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .vault_surface import OpenedVaultSurfaceProvider

if TYPE_CHECKING:
    from ..vault import Vault


def create_vault_surface_provider(vault: "Vault") -> OpenedVaultSurfaceProvider:
    """Create a read-only surface provider for an already-open vault."""

    return OpenedVaultSurfaceProvider(vault)
