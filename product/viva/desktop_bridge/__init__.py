"""Transport boundary between the desktop shell and the Viva sidecar."""

from .handlers import (
    BridgeDispatcher,
    BridgeRequestError,
    default_handlers,
    handlers_for_opened_vault,
    handlers_with_surface_provider,
)
from .rpc import BridgeProtocolError, decode_frame, dispatch_frame, encode_frame
from .surface_read import JobProgressEvent, VaultSurfaceProvider, VaultSurfaceReader
from .vault_surface import OpenedVaultSurfaceProvider
from .vault_provider import create_vault_surface_provider

__all__ = [
    "BridgeDispatcher",
    "BridgeProtocolError",
    "BridgeRequestError",
    "decode_frame",
    "default_handlers",
    "dispatch_frame",
    "encode_frame",
    "handlers_with_surface_provider",
    "handlers_for_opened_vault",
    "JobProgressEvent",
    "VaultSurfaceProvider",
    "VaultSurfaceReader",
    "OpenedVaultSurfaceProvider",
    "create_vault_surface_provider",
]
