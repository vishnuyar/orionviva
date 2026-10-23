"""Affected selection includes dependents and falls back on unknown inputs."""
import subprocess

import pytest

from scripts import test as runner
from scripts.test import changed_files, commands, full_plan, make_plan


def _write(root, name, content=""):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_python_closure_includes_relative_imports_helpers_and_dynamic_targets(tmp_path):
    for name, content in {
        "core/vivacore/__init__.py": "",
        "core/vivacore/amount.py": "",
        "product/viva/service.py": "from vivacore.amount import value",
        "product/viva/feature.py": "from .service import value",
        "product/tests/_helper.py": "from viva.feature import value",
        "product/tests/test_feature.py": "from _helper import value",
        "product/tests/test_dynamic.py": "import_module('vivacore.amount')",
        "product/tests/test_unrelated.py": "assert True",
    }.items():
        _write(tmp_path, name, content)
    plan = make_plan(tmp_path, ["core/vivacore/amount.py"])
    assert plan.python == ["product/tests/test_dynamic.py", "product/tests/test_feature.py"]
    assert plan.desktop == []


@pytest.mark.parametrize("name", [
    "product/viva/prompts/new.txt", "desktop/src/styles/picture.css",
    "product/tests/conftest.py", "product/viva/__init__.py",
    "product/viva/deleted.py", "desktop/src/test/setup.ts",
    "desktop/package.json", ".github/workflows/quality.yml", "scripts/test.py",
    "product/unknown/script.py",
])
def test_uncertain_changes_require_complete_suites(tmp_path, name):
    if "deleted" not in name:
        _write(tmp_path, name)
    assert make_plan(tmp_path, [name]) == full_plan(
        make_plan(tmp_path, [name]).reason)


def test_test_only_changes_select_the_test_and_its_importers(tmp_path):
    _write(tmp_path, "product/tests/test_owner.py")
    _write(tmp_path, "product/tests/test_user.py", "from test_owner import fixture")
    _write(tmp_path, "product/tests/test_other.py")
    plan = make_plan(tmp_path, ["product/tests/test_owner.py"])
    assert plan.python == ["product/tests/test_owner.py", "product/tests/test_user.py"]
    assert plan.desktop is None
    _write(tmp_path, "desktop/src/app/selection.ts")
    mixed = make_plan(tmp_path, ["product/tests/test_owner.py", "desktop/src/app/selection.ts"])
    assert mixed.python == plan.python
    assert mixed.desktop == ["src/app/selection.ts"]


def test_uncovered_python_module_runs_its_whole_package(tmp_path):
    _write(tmp_path, "merchant/merchantcore/new.py")
    assert make_plan(tmp_path, ["merchant/merchantcore/new.py"]).python == ["merchant"]
    _write(tmp_path, "core/vivacore/amount.py")
    _write(tmp_path, "core/tests/test_amount.py", "from vivacore.amount import value")
    plan = make_plan(tmp_path, ["merchant/merchantcore/new.py", "core/vivacore/amount.py"])
    assert plan.python == ["core/tests/test_amount.py", "merchant"]


def test_frontend_changes_use_vitest_related_and_no_changes_run_nothing(tmp_path):
    _write(tmp_path, "desktop/src/app/selection.ts")
    plan = make_plan(tmp_path, ["desktop/src/app/selection.ts"])
    assert plan.python == []
    assert commands(plan)[0][1][-4:] == ["vitest", "related", "src/app/selection.ts", "--run"]
    assert not commands(make_plan(tmp_path, []))


def test_git_selection_includes_staged_unstaged_untracked_and_deleted_paths(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    git("init")
    for name in ["staged.py", "working.py", "deleted.py"]:
        _write(tmp_path, name)
    git("add", ".")
    git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
        "-c", "core.hooksPath=/dev/null", "commit", "-m", "fixture")
    _write(tmp_path, "staged.py", "changed")
    git("add", "staged.py")
    _write(tmp_path, "working.py", "changed")
    _write(tmp_path, "untracked.py")
    (tmp_path / "deleted.py").unlink()
    assert changed_files(tmp_path, None) == ["deleted.py", "staged.py", "untracked.py", "working.py"]
    assert changed_files(tmp_path, "HEAD") == changed_files(tmp_path, None)


def test_failed_python_run_returns_failure_before_starting_desktop(monkeypatch):
    monkeypatch.setattr(runner.sys, "argv", ["test.py", "--all"])
    called = []
    def fail(command, **_kwargs):
        called.append(command)
        return subprocess.CompletedProcess(command, 7)
    monkeypatch.setattr(runner.subprocess, "run", fail)
    assert runner.main() == 7
    assert len(called) == 1
    assert "pytest" in called[0]
