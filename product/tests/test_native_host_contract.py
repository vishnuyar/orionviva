"""Acceptance checks for the native Tauri-to-sidecar boundary."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
TAURI_DIR = ROOT / "desktop" / "src-tauri"
TAURI_CONFIG = TAURI_DIR / "tauri.conf.json"
SIDECAR_NAME = "viva-desktop-bridge"


def test_native_host_declares_tauri_configuration_and_named_sidecar():
    assert TAURI_CONFIG.is_file(), (
        "native host is missing desktop/src-tauri/tauri.conf.json"
    )
    config = json.loads(TAURI_CONFIG.read_text())

    external_bins = config.get("bundle", {}).get("externalBin", [])
    assert f"binaries/{SIDECAR_NAME}" in external_bins


def test_named_sidecar_maps_to_the_python_module_entrypoint():
    entrypoint = ROOT / "product" / "viva" / "desktop_bridge" / "__main__.py"
    assert entrypoint.is_file()
    source = entrypoint.read_text()
    assert 'if __name__ == "__main__":' in source
    assert "sys.stdin" in source
    assert "sys.stdout" in source


def test_native_host_boundary_names_match_frontend_operations():
    bridge_client = ROOT / "desktop" / "src" / "app" / "bridge-client.ts"
    source = bridge_client.read_text()

    assert 'request("bridge.open_vault"' in source
    assert 'request<SurfaceReadResult>("viva.surface.read"' in source
    assert 'vault_directory: vaultDirectory' in source
    assert 'passphrase' in source
    assert 'surface,' in source
    assert 'job_id:' in source
