"""Acceptance checks for repeatable native sidecar packaging."""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


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


def _sidecar_analysis_data(monkeypatch, tmp_path, spec_path=SIDECAR_SPEC):
    captured = {}

    def analyze(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=kwargs["datas"])

    build_main = ModuleType("PyInstaller.building.build_main")
    build_main.Analysis = analyze
    build_main.PYZ = lambda *args, **kwargs: None
    build_main.EXE = lambda *args, **kwargs: None
    hooks = ModuleType("PyInstaller.utils.hooks")

    def collect(package, *, include_py_files):
        assert include_py_files is False
        return [(str(tmp_path / f"{package}.asset"), package)]

    hooks.collect_data_files = collect
    monkeypatch.setitem(sys.modules, build_main.__name__, build_main)
    monkeypatch.setitem(sys.modules, hooks.__name__, hooks)
    revision = tmp_path / "revision.txt"
    revision.write_text("synthetic-build")
    monkeypatch.setenv("VIVA_BUILD_REVISION_FILE", str(revision))
    runpy.run_path(str(spec_path), init_globals={"SPECPATH": str(spec_path.parent)})
    return captured["datas"], revision


def test_sidecar_delivers_exact_sources_authenticated_by_runtime_admission(monkeypatch, tmp_path):
    data, revision = _sidecar_analysis_data(monkeypatch, tmp_path)
    bundled = {
        f"{destination}/{Path(source).name}": Path(source).read_bytes()
        for source, destination in data if Path(source).suffix == ".py"
    }
    expected = {
        **{f"viva/{name}.py": ROOT / f"product/viva/{name}.py"
           for name in ("ledger/scenarios", "tools/scenarios", "answer_program/capability_fixture",
                        "answer_program/admission_fixture", "answer_program/admission", "answer_program/eval",
                        "ledger/movement_identity", "ledger/events", "ledger/postings")},
        "viva/answer_program/intents.py": ROOT / "product/viva/answer_program/intents.py",
        "viva/answer_program/compiler.py": ROOT / "product/viva/answer_program/compiler.py",
        "viva/answer_program/runtime.py": ROOT / "product/viva/answer_program/runtime.py",
        "viva/answer_program/replay.py": ROOT / "product/viva/answer_program/replay.py",
        "vivacore/models/openai_compat.py": ROOT / "core/vivacore/models/openai_compat.py",
        "viva/answer_program/capabilities.py": ROOT / "product/viva/answer_program/capabilities.py",
        **{f"viva/tools/{name}.py": ROOT / f"product/viva/tools/{name}.py"
           for name in ("ledger_aggregates", "ledger_common", "ledger_movements", "ledger_vocabulary")},
        **{f"viva/ledger/projection/{name}.py": ROOT / f"product/viva/ledger/projection/{name}.py"
           for name in ("movements", "categories", "merchants")},
        "viva/ledger/statements.py": ROOT / "product/viva/ledger/statements.py",
        **{f"viva/tools/{name}.py": ROOT / f"product/viva/tools/{name}.py"
           for name in ("__init__", "registry", "ledger_tools")},
        **{f"viva/ledger/projection/{name}.py": ROOT / f"product/viva/ledger/projection/{name}.py"
           for name in ("core", "accounts", "balances", "rhythm")},
        "viva/ledger/streams.py": ROOT / "product/viva/ledger/streams.py",
        "viva/answer_program/bind.py": ROOT / "product/viva/answer_program/bind.py",
        "viva/answer_program/execute.py": ROOT / "product/viva/answer_program/execute.py",
        "viva/answer_program/evidence.py": ROOT / "product/viva/answer_program/evidence.py",
        "viva/answer_program/validate.py": ROOT / "product/viva/answer_program/validate.py",
        "viva/answer_program/schema.py": ROOT / "product/viva/answer_program/schema.py",
        "viva/tools/envelope.py": ROOT / "product/viva/tools/envelope.py",
        "viva/tools/boundary.py": ROOT / "product/viva/tools/boundary.py",
        "viva/tools/shape.py": ROOT / "product/viva/tools/shape.py",
        "viva/tools/runner_binding.py": ROOT / "product/viva/tools/runner_binding.py",
        "viva/tools/runner_delivery.py": ROOT / "product/viva/tools/runner_delivery.py",
        "viva/tools/runner.py": ROOT / "product/viva/tools/runner.py",
        "viva/tools/compute.py": ROOT / "product/viva/tools/compute.py",
        "viva/quantity.py": ROOT / "product/viva/quantity.py",
        "viva/render.py": ROOT / "product/viva/render.py",
        "viva/ledger/projection/__init__.py": ROOT / "product/viva/ledger/projection/__init__.py",
        "viva/tools/measurements.py": ROOT / "product/viva/tools/measurements.py",
        "viva/tools/projections.py": ROOT / "product/viva/tools/projections.py",
        "viva/ledger/projection/measurements.py": ROOT / "product/viva/ledger/projection/measurements.py",
        "viva/ledger/projection/positions.py": ROOT / "product/viva/ledger/projection/positions.py",
        "viva/ledger/projection/current_period.py": ROOT / "product/viva/ledger/projection/current_period.py",
        "viva/ledger/projection/obligations.py": ROOT / "product/viva/ledger/projection/obligations.py",
        "viva/ledger/projection/goals.py": ROOT / "product/viva/ledger/projection/goals.py",
        "viva/ingest/brokerage.py": ROOT / "product/viva/ingest/brokerage.py",
        "vivacore/verify/arithmetic.py": ROOT / "core/vivacore/verify/arithmetic.py",
        "vivacore/verify/normalize.py": ROOT / "core/vivacore/verify/normalize.py",
    }
    assert bundled.keys() == expected.keys()
    for name, path in expected.items():
        assert bundled[name] == path.read_bytes(), name
    assert (str(revision), "viva") in data
    for package in ("viva", "vivacore", "merchantcore"):
        assert (str(tmp_path / f"{package}.asset"), package) in data


def test_sidecar_build_refuses_a_missing_admission_source(monkeypatch, tmp_path):
    clone = tmp_path / "clone/product/viva/desktop_bridge"
    clone.mkdir(parents=True)
    spec = clone / SIDECAR_SPEC.name
    shutil.copyfile(SIDECAR_SPEC, spec)
    with pytest.raises(SystemExit, match="missing admission source scenarios.py"):
        _sidecar_analysis_data(monkeypatch, tmp_path, spec)


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


def test_sidecar_build_refuses_a_missing_replay_source(monkeypatch, tmp_path):
    clone = tmp_path / 'clone'
    destination = clone / 'product/viva/desktop_bridge'
    destination.mkdir(parents=True)
    spec = destination / SIDECAR_SPEC.name
    shutil.copyfile(SIDECAR_SPEC, spec)
    # Supply every other declared byte; the missing replay authority must be
    # identified regardless of its position in the exact declaration list.
    data,_=_sidecar_analysis_data(monkeypatch,tmp_path)
    for source,_destination in data:
        source=Path(source)
        if source.suffix!='.py' or source.name=='replay.py': continue
        relative=source.relative_to(ROOT)
        target=clone/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    with pytest.raises(SystemExit, match='missing admission source replay.py'):
        _sidecar_analysis_data(monkeypatch, tmp_path, spec)


@pytest.mark.parametrize('relative',[
    'product/viva/ledger/scenarios.py','product/viva/tools/scenarios.py',
    'product/viva/answer_program/capability_fixture.py','product/viva/answer_program/admission_fixture.py',
    'product/viva/answer_program/admission.py','product/viva/answer_program/eval.py',
    'product/viva/ledger/movement_identity.py','product/viva/ledger/events.py','product/viva/ledger/postings.py',
    'product/viva/answer_program/execute.py','product/viva/tools/registry.py',
])
def test_each_added_or_changed_authority_is_mandatory_in_native_source_bundle(monkeypatch,tmp_path,relative):
    data,_=_sidecar_analysis_data(monkeypatch,tmp_path)
    clone=tmp_path/'candidate'
    for source,_destination in data:
        source=Path(source)
        if source.suffix!='.py':continue
        path=source.relative_to(ROOT)
        if str(path)==relative:continue
        target=clone/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    target=clone/'product/viva/desktop_bridge'/SIDECAR_SPEC.name
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SIDECAR_SPEC,target)
    with pytest.raises(SystemExit,match=f'missing admission source {Path(relative).name}'):
        _sidecar_analysis_data(monkeypatch,tmp_path,target)
