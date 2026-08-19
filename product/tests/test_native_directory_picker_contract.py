"""Acceptance contracts for the native dialog plugin behind vault selection.

The subject is what the Rust host declares and permits, plus the presence of
the frontend shim. What the shim does is the Node checker's.
"""

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


def test_the_frontend_host_shim_is_present():
    """Assert the shim exists at the path the frontend boundary map names.

    What the shim does is not checked here. Whether the picker is folder-only,
    and whether a cancellation stays distinct from a failed host call, are
    claims about TypeScript behaviour and belong to the Node checker.
    """
    assert TAURI_HOST.is_file(), f"missing native picker contract file: {TAURI_HOST}"
