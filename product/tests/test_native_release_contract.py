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


def _required_gate_step(workflow, job, command):
    """Require one unsuppressed, standalone command using a standard CI shell."""
    assert not job.get("if") and not job.get("continue-on-error")
    steps = [step for step in job["steps"] if step.get("run", "").strip() == command]
    assert len(steps) == 1, f"missing standalone gate command: {command}"
    step = steps[0]
    assert not step.get("if") and not step.get("continue-on-error")
    shell = step.get("shell", job.get("defaults", {}).get("run", {}).get(
        "shell", workflow.get("defaults", {}).get("run", {}).get("shell")))
    assert shell in (None, "bash", "pwsh"), "gate shell must propagate command failure"
    return step


def _assert_native_test_gates(workflows):
    import yaml

    quality = yaml.safe_load((workflows / "quality.yml").read_text())
    desktop = quality["jobs"]["desktop"]
    assert set(desktop["strategy"]["matrix"]["runner"]) >= {
        "macos-latest", "windows-latest", "ubuntu-22.04"}
    assert desktop["runs-on"] == "${{ matrix.runner }}"
    _required_gate_step(
        quality, desktop, "cargo test --locked --manifest-path src-tauri/Cargo.toml")
    _required_gate_step(
        quality, desktop,
        "python -m pytest product/tests/test_store.py product/tests/test_ledger_platform_io.py "
        "product/tests/test_native_release_contract.py -q")

    release = yaml.safe_load((workflows / "release-desktop.yml").read_text())
    package = release["jobs"]["package"]
    native = _required_gate_step(
        release, package,
        'cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml --target "${{ matrix.target }}"')
    steps = package["steps"]
    publish = next(index for index, step in enumerate(steps)
                   if step.get("uses", "").startswith("tauri-apps/tauri-action@"))
    assert steps.index(native) < publish


def test_native_host_and_storage_tests_gate_supported_platforms():
    _assert_native_test_gates(WORKFLOWS)


def test_native_gate_rejects_removed_tests_and_non_executable_mentions(tmp_path):
    import pytest
    import yaml

    for filename in ("quality.yml", "release-desktop.yml"):
        (tmp_path / filename).write_text((WORKFLOWS / filename).read_text())
    original = (tmp_path / "quality.yml").read_text()
    for replacement in ("echo cargo test --locked --manifest-path src-tauri/Cargo.toml",
                        "# cargo test --locked --manifest-path src-tauri/Cargo.toml"):
        quality = yaml.safe_load(original)
        step = next(step for step in quality["jobs"]["desktop"]["steps"]
                    if step.get("run", "").startswith("cargo test"))
        step["run"] = replacement
        (tmp_path / "quality.yml").write_text(yaml.safe_dump(quality))
        with pytest.raises(AssertionError):
            _assert_native_test_gates(tmp_path)
    (tmp_path / "quality.yml").write_text(original)
    release = yaml.safe_load((tmp_path / "release-desktop.yml").read_text())
    release["jobs"]["package"]["steps"] = [
        step for step in release["jobs"]["package"]["steps"]
        if not step.get("run", "").startswith("cargo test")]
    (tmp_path / "release-desktop.yml").write_text(yaml.safe_dump(release))
    with pytest.raises(AssertionError):
        _assert_native_test_gates(tmp_path)


def test_native_gate_rejects_failure_suppression(tmp_path):
    import pytest
    import yaml

    originals = {name: (WORKFLOWS / name).read_text()
                 for name in ("quality.yml", "release-desktop.yml")}
    mutations = (
        "or_true", "semicolon_true", "pipeline", "background", "next_line",
        "set_plus_e", "subshell", "step_continue", "job_continue",
        "step_shell", "job_shell", "workflow_shell",
    )
    for filename, job_name, prefix in (
            ("quality.yml", "desktop", "cargo test"),
            ("quality.yml", "desktop", "python -m pytest"),
            ("release-desktop.yml", "package", "cargo test")):
        for mutation in mutations:
            for name, original in originals.items():
                (tmp_path / name).write_text(original)
            workflow = yaml.safe_load(originals[filename])
            job = workflow["jobs"][job_name]
            step = next(step for step in job["steps"]
                        if step.get("run", "").startswith(prefix))
            command = step["run"].strip()
            replacements = {
                "or_true": command + " || true",
                "semicolon_true": command + "; true",
                "pipeline": command + " | cat",
                "background": command + " &",
                "next_line": command + "\ntrue",
                "set_plus_e": "set +e\n" + command + "\ntrue",
                "subshell": "(" + command + ") || true",
            }
            if mutation in replacements:
                step["run"] = replacements[mutation]
            elif mutation == "step_continue":
                step["continue-on-error"] = True
            elif mutation == "job_continue":
                job["continue-on-error"] = True
            elif mutation == "step_shell":
                step["shell"] = "bash -c '{0}; true'"
            else:
                step.pop("shell", None)
                if mutation == "job_shell":
                    job.setdefault("defaults", {}).setdefault("run", {})["shell"] = "bash -c '{0}; true'"
                else:
                    job.get("defaults", {}).get("run", {}).pop("shell", None)
                    workflow.setdefault("defaults", {}).setdefault("run", {})["shell"] = "bash -c '{0}; true'"
            (tmp_path / filename).write_text(yaml.safe_dump(workflow))
            with pytest.raises(AssertionError):
                _assert_native_test_gates(tmp_path)
