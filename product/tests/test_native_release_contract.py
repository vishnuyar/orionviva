"""Acceptance checks for signed, target-aware native delivery.

The Rust bundle is exercised in CI, but its release metadata and credential
boundaries are configuration contracts.  These checks keep those contracts
reviewable without requiring a local Apple, Windows, or signing toolchain.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.prepare_native_release import release_override


ROOT = Path(__file__).parents[2]
DESKTOP = ROOT / "desktop"
TAURI_CONFIG = DESKTOP / "src-tauri" / "tauri.conf.json"
RELEASE_TARGETS = DESKTOP / "src-tauri" / "release-targets.json"
WORKFLOWS = ROOT / ".github" / "workflows"

REQUIRED_TARGETS = {
    "aarch64-apple-darwin",
    "x86_64-apple-darwin",
    "x86_64-pc-windows-msvc",
}
RELEASE_TRIGGERS = ("workflow_dispatch:", "refs/tags/", "tags:")


def _release_workflows() -> list[Path]:
    """Return workflows that opt in to creating a native release."""
    return [
        workflow
        for workflow in WORKFLOWS.glob("*.y*ml")
        if "tauri build" in workflow.read_text().lower()
        and any(trigger in workflow.read_text() for trigger in RELEASE_TRIGGERS)
    ]


def _declared_release_targets() -> set[str]:
    """Return the target triples the release matrix is actually built from."""
    assert RELEASE_TARGETS.is_file(), (
        f"the release matrix manifest is missing: {RELEASE_TARGETS}"
    )
    manifest = json.loads(RELEASE_TARGETS.read_text())
    assert isinstance(manifest, dict), (
        "the release matrix manifest must be an object with an include list, "
        f"not {type(manifest).__name__}"
    )
    entries = manifest.get("include", [])
    assert entries, (
        "the release matrix manifest declares no entries, so a release would "
        "build nothing at all"
    )
    return {entry["target"] for entry in entries if entry.get("target")}


def _release_workflow_source() -> str:
    workflows = _release_workflows()
    assert workflows, (
        "native delivery needs a release-triggered GitHub workflow that runs "
        "`tauri build`; do not reuse pull-request quality checks for signing"
    )
    return "\n".join(workflow.read_text() for workflow in workflows)


def test_the_release_override_declares_no_update_channel():
    """The sidecar is still bundled; the updater is not.

    This test previously asserted the opposite — that the release generates a
    signed `latest.json` and an updater public key. It was asserting a channel
    no installed copy could read: nothing compiles an updater plugin into this
    application, so the manifest and its signatures described a capability the
    binary did not have. The contract now is that the release ships installers
    and says so."""
    config = json.loads(TAURI_CONFIG.read_text())
    bundle = config.get("bundle", {})
    assert f"binaries/{'viva-desktop-bridge'}" in bundle.get("externalBin", [])

    override = release_override(
        "linux",
        {"ORIONVIVA_WINDOWS_CERTIFICATE_THUMBPRINT": "unused-on-linux"},
    )
    assert "plugins" not in override, (
        "the release override declares a plugin configuration; an updater "
        "plugin is not compiled into the application"
    )
    assert not override["bundle"].get("createUpdaterArtifacts"), (
        "the release would publish updater artifacts for an application with "
        "no updater"
    )


def test_release_workflow_builds_every_supported_target_after_its_sidecar():
    source = _release_workflow_source()

    missing = REQUIRED_TARGETS - _declared_release_targets()
    assert not missing, (
        "the release matrix manifest must include Apple Silicon, Intel macOS "
        f"and Windows x64 targets; missing: {', '.join(sorted(missing))}"
    )
    assert "matrix.target" in source, (
        "sidecar and Tauri build commands must share the release matrix target"
    )
    assert "build_desktop_sidecar.py" in source
    assert "tauri build" in source.lower()
    assert source.index("build_desktop_sidecar.py") < source.lower().index("tauri build"), (
        "each target must stage the sidecar before Tauri bundles it"
    )


def test_release_workflow_signs_bundles_without_exposing_private_material():
    source = _release_workflow_source()

    assert "TAURI_SIGNING_PRIVATE_KEY" in source
    assert "secrets.TAURI_SIGNING_PRIVATE_KEY" in source, (
        "the updater private key must be sourced from GitHub Actions secrets"
    )
    assert "TAURI_SIGNING_PRIVATE_KEY_PASSWORD" in source
    assert "secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD" in source, (
        "the updater key password must be sourced from GitHub Actions secrets"
    )
    assert "--private-key" not in source
    assert "printenv" not in source.lower()
    assert "set -x" not in source.lower()
    assert "-----BEGIN" not in source


def test_release_workflow_keeps_signing_secrets_out_of_pull_request_jobs():
    source = _release_workflow_source()

    # Signing must be confined to a tag/manual release workflow. A pull request
    # from an untrusted fork must never receive the updater private key.
    assert "pull_request:" not in source
    assert not re.search(r"TAURI_SIGNING_PRIVATE_KEY\s*:\s*['\"](?!\$\{\{)", source)
