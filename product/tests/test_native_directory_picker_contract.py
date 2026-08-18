"""Acceptance contracts for selecting a local vault directory in Tauri."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]
HOST = ROOT / "desktop" / "src-tauri" / "src" / "main.rs"
CARGO_MANIFEST = ROOT / "desktop" / "src-tauri" / "Cargo.toml"
CAPABILITY = ROOT / "desktop" / "src-tauri" / "capabilities" / "default.json"
TAURI_HOST = ROOT / "desktop" / "src" / "tauri-host.ts"


def _source(path: Path) -> str:
    assert path.is_file(), f"missing native picker contract file: {path}"
    return path.read_text()


def test_native_host_declares_a_supported_dialog_implementation():
    manifest = _source(CARGO_MANIFEST)
    source = _source(HOST)
    capability = _source(CAPABILITY)

    assert "tauri-plugin-dialog" in manifest
    assert "tauri_plugin_dialog::init()" in source
    assert "dialog:allow-open" in capability


def test_frontend_host_adapter_uses_a_folder_only_picker_outside_the_sidecar_protocol():
    source = _source(TAURI_HOST)

    assert 'from "@tauri-apps/plugin-dialog"' in source
    assert "pickVaultDirectory" in source
    assert "await open({" in source
    assert "directory: true" in source
    assert "multiple: false" in source
    # The plugin returns null on cancellation, which must stay distinct from
    # a rejected host call so the UI can retain manual input.
    assert 'typeof selected === "string" ? selected : null' in source
    assert '"bridge_request"' in source
