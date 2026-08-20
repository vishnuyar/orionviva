"""Acceptance checks for repeatable native sidecar packaging."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
DESKTOP = ROOT / "desktop"
TAURI_CONFIG = DESKTOP / "src-tauri" / "tauri.conf.json"
PACKAGE_JSON = DESKTOP / "package.json"
QUALITY_WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"
SIDECAR_SCRIPT = ROOT / "scripts" / "build_desktop_sidecar.py"
SIDECAR_NAME = "viva-desktop-bridge"


def test_sidecar_build_script_has_reproducible_target_and_output_contract():
    assert SIDECAR_SCRIPT.is_file(), (
        "native packaging is missing scripts/build_desktop_sidecar.py"
    )
    source = SIDECAR_SCRIPT.read_text()

    for argument in ("--output-dir", "--target"):
        assert argument in source
    assert SIDECAR_NAME in source
    assert "sys.executable" in source or "python -m build" in source


def test_sidecar_build_script_emits_tauri_external_bin_name():
    assert SIDECAR_SCRIPT.is_file()
    source = SIDECAR_SCRIPT.read_text()

    # Tauri appends the target triple to this base name when resolving
    # externalBin resources; the build script must not invent another name.
    assert f'"{SIDECAR_NAME}"' in source or f"'{SIDECAR_NAME}'" in source
    assert "output_dir" in source


def test_tauri_bundle_declares_product_identity_and_sidecar_resource():
    config = json.loads(TAURI_CONFIG.read_text())

    assert config["productName"] == "OrionViva"
    assert config["version"]
    assert config["identifier"] == "com.orionviva.desktop"
    assert config["bundle"]["active"] is True
    assert f"binaries/{SIDECAR_NAME}" in config["bundle"]["externalBin"]
    assert config["bundle"].get("targets")


def test_desktop_package_exposes_a_native_build_command():
    package = json.loads(PACKAGE_JSON.read_text())
    scripts = package.get("scripts", {})

    assert "tauri" in package.get("devDependencies", {}) or "@tauri-apps/cli" in package.get(
        "devDependencies", {}
    )
    assert any(
        command in scripts.get("desktop:build", "")
        or command in scripts.get("tauri:build", "")
        for command in ("tauri build", "tauri-cli build")
    ), "desktop package is missing a Tauri production build command"


def test_ci_wires_sidecar_build_before_tauri_bundle():
    source = QUALITY_WORKFLOW.read_text()

    assert "build_desktop_sidecar.py" in source
    assert "tauri build" in source
    assert source.index("build_desktop_sidecar.py") < source.index("tauri build")


def test_the_bundle_names_icons_that_exist():
    """An empty `bundle.icon` does not fail the build — Tauri accepts it and
    ships an application with no icon, so CI stays green over a defect a person
    sees the moment they open the folder. The macOS and Windows bundlers need
    the `.icns` and `.ico` specifically; a directory of PNGs is not enough."""
    bundle = json.loads(TAURI_CONFIG.read_text())["bundle"]
    icons = bundle.get("icon", [])
    assert icons, (
        "bundle.icon is empty, so the bundlers ship an iconless application "
        "and nothing reports it"
    )

    missing = [name for name in icons
               if not (TAURI_CONFIG.parent / name).is_file()]
    assert not missing, f"bundle.icon names files that do not exist: {missing}"

    suffixes = {Path(name).suffix for name in icons}
    for required in (".icns", ".ico"):
        assert required in suffixes, (
            f"bundle.icon names no {required}; the "
            f"{'macOS' if required == '.icns' else 'Windows'} bundler needs one"
        )


def test_the_release_ships_no_updater_it_cannot_honour():
    """A signed `latest.json` beside the installers advertises an update channel.
    Nothing compiles an updater plugin into this application, so no installed
    copy can read that channel — the manifest would be a promise the binary
    cannot keep. The two halves ship together or not at all."""
    cargo = (DESKTOP / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    package = PACKAGE_JSON.read_text(encoding="utf-8")
    has_plugin = "tauri-plugin-updater" in cargo or "plugin-updater" in package

    release_script = (ROOT / "scripts" / "prepare_native_release.py").read_text()
    release_workflow = (ROOT / ".github" / "workflows"
                        / "release-desktop.yml").read_text()
    publishes = ("createUpdaterArtifacts" in release_script
                 or "uploadUpdaterJson" in release_workflow
                 or "uploadUpdaterSignatures" in release_workflow)

    assert has_plugin == publishes, (
        "the release publishes updater artifacts but the application has no "
        "updater plugin" if publishes else
        "the application has an updater plugin but the release publishes no "
        "updater artifacts"
    )
