"""Acceptance checks for repeatable native sidecar packaging."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]
DESKTOP = ROOT / "desktop"
TAURI_CONFIG = DESKTOP / "src-tauri" / "tauri.conf.json"
PACKAGE_JSON = DESKTOP / "package.json"
QUALITY_WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"
SIDECAR_SCRIPT = ROOT / "scripts" / "build_desktop_sidecar.py"
SIDECAR_SPEC = ROOT / "product" / "viva" / "desktop_bridge" / "viva-desktop-bridge.spec"
SIDECAR_MAIN = ROOT / "product" / "viva" / "desktop_bridge" / "__main__.py"
SIDECAR_REQUIREMENTS = ROOT / "product" / "requirements-sidecar-build.txt"
SQLCIPHER_WHEEL_LOCK = ROOT / "product" / "requirements-sqlcipher-wheels.txt"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-desktop.yml"
SIDECAR_NAME = "viva-desktop-bridge"
SIDECAR_LAUNCHER = DESKTOP / "scripts" / "build-sidecar.mjs"


def test_sidecar_build_script_has_reproducible_target_and_output_contract():
    assert SIDECAR_SCRIPT.is_file(), (
        "native packaging is missing scripts/build_desktop_sidecar.py"
    )
    source = SIDECAR_SCRIPT.read_text()

    for argument in ("--output-dir", "--target"):
        assert argument in source
    assert SIDECAR_NAME in source
    assert "sys.executable" in source or "python -m build" in source
    assert "VIVA_BUILD_REVISION_FILE" in source
    assert "build_revision()" in source


def test_sidecar_launcher_uses_configured_external_python_without_a_target_venv(tmp_path):
    """A clean evaluator/release clone may borrow its prepared interpreter."""
    target = tmp_path / "clean-target"
    launcher = target / "desktop" / "scripts" / SIDECAR_LAUNCHER.name
    builder = target / "scripts" / SIDECAR_SCRIPT.name
    launcher.parent.mkdir(parents=True)
    builder.parent.mkdir(parents=True)
    shutil.copy2(SIDECAR_LAUNCHER, launcher)
    shutil.copy2(SIDECAR_SCRIPT, builder)
    assert not (target / ".venv").exists()

    environment = dict(os.environ)
    environment["ORIONVIVA_PYTHON"] = sys.executable
    result = subprocess.run(
        ["node", str(launcher)], cwd=target / "desktop", env=environment,
        capture_output=True, text=True, check=False)

    # The external interpreter reached the copied builder. It then refused the
    # intentionally incomplete target at its first product-file boundary.
    assert result.returncode != 0
    assert "missing PyInstaller spec" in result.stderr


def test_sidecar_launcher_uses_path_python_when_clean_target_has_no_venv(tmp_path):
    target = tmp_path / "clean-target"
    launcher = target / "desktop" / "scripts" / SIDECAR_LAUNCHER.name
    builder = target / "scripts" / SIDECAR_SCRIPT.name
    launcher.parent.mkdir(parents=True)
    builder.parent.mkdir(parents=True)
    shutil.copy2(SIDECAR_LAUNCHER, launcher)
    shutil.copy2(SIDECAR_SCRIPT, builder)

    environment = dict(os.environ)
    environment.pop("ORIONVIVA_PYTHON", None)
    environment["PATH"] = os.pathsep.join(
        [str(Path(sys.executable).parent), environment.get("PATH", "")])
    result = subprocess.run(
        ["node", str(launcher)], cwd=target / "desktop", env=environment,
        capture_output=True, text=True, check=False)

    assert result.returncode != 0
    assert "missing PyInstaller spec" in result.stderr


def test_sidecar_build_uses_a_run_owned_pyinstaller_cache():
    source = SIDECAR_SCRIPT.read_text()

    assert 'if not build_environment.get("PYINSTALLER_CONFIG_DIR", "").strip()' in source
    assert '"PYINSTALLER_CONFIG_DIR"' in source
    assert 'temporary_root / "pyinstaller-config"' in source


def test_sidecar_build_script_emits_tauri_external_bin_name():
    assert SIDECAR_SCRIPT.is_file()
    source = SIDECAR_SCRIPT.read_text()

    # Tauri appends the target triple to this base name when resolving
    # externalBin resources; the build script must not invent another name.
    assert f'"{SIDECAR_NAME}"' in source or f"'{SIDECAR_NAME}'" in source
    assert "output_dir" in source


def test_packaged_sidecar_requires_the_sqlcipher_runtime_at_startup():
    spec = SIDECAR_SPEC.read_text()
    entrypoint = SIDECAR_MAIN.read_text()

    assert '"sqlcipher3"' in spec
    assert '"sqlcipher3.dbapi2"' in spec
    assertion = "assert_sqlcipher_runtime()"
    assert assertion in entrypoint
    assert entrypoint.index(assertion) < entrypoint.index(
        "sidecar = Sidecar(sys.stdout, sys.stdin)"
    )


def test_release_sqlcipher_wheels_are_version_and_hash_pinned():
    requirements = SQLCIPHER_WHEEL_LOCK.read_text()

    assert "sqlcipher3==0.6.2" in requirements
    assert requirements.count("--hash=sha256:") == 4
    expected = {
        "sqlcipher3-0.6.2-cp312-cp312-macosx_10_13_universal2.whl":
            "a51b18bd782652a2282f9cb1b03b840ba5a6c0c675de6cefb76262c9789c8f06",
        "sqlcipher3-0.6.2-cp312-cp312-macosx_10_13_x86_64.whl":
            "fea0f1264f09d219dd6ce699ffca8cc9022a914661c6efa4390e85a2bf78acf9",
        "sqlcipher3-0.6.2-cp312-cp312-win_amd64.whl":
            "8bd60ffb7bfa65bd0e51da3d5c308553d7149f0091d4ea9f754c33d5ebbf0a66",
        "sqlcipher3-0.6.2-cp312-cp312-manylinux_2_28_x86_64.whl":
            "6b26d28ca844dc2a69b8f74b390e940db47760f0be4c96d93337c57ae8250a48",
    }
    for filename, digest in expected.items():
        assert filename in requirements
        assert f"--hash=sha256:{digest}" in requirements


def test_desktop_workflows_install_sqlcipher_through_the_lock_only():
    required = (
        "python -m pip install --only-binary=:all: --require-hashes --no-deps "
    )
    for workflow in (RELEASE_WORKFLOW, QUALITY_WORKFLOW):
        source = workflow.read_text()
        assert required in source
        assert "requirements-sqlcipher-wheels.txt" in source
        assert "pip install --no-deps -e product" in source.replace("../product", "product")
        assert "-e product[dev]" not in source
        assert "-e ../product[dev]" not in source

    # Every quality job that installs the product first executes the locked
    # wheel step; there is no job-local unhashed resolution route.
    quality = QUALITY_WORKFLOW.read_text()
    assert quality.count("requirements-sqlcipher-wheels.txt") == quality.count(
        "pip install --no-deps -e product"
    ) + quality.count("pip install --no-deps -e ../product")

    # The ordinary build-tool file must not offer an unhashed second route.
    assert "sqlcipher3" not in SIDECAR_REQUIREMENTS.read_text()


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
    """The release metadata and packaged updater capability remain consistent."""
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import prepare_native_release as release

    readable, published = release._updater_declarations()

    assert readable == [], (
        "an updater plugin is compiled in but nothing publishes a channel: "
        f"{readable}")
    assert published == [], (
        "an update channel would be published that no installed copy can read: "
        f"{published}")
    # And the step itself agrees, so a build that acquired half a channel fails
    # the release rather than only failing here.
    release.validate_update_channel()
