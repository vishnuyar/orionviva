"""AST checks for the dependency direction of the surface architecture."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _python_files(directory: Path):
    return sorted(path for path in directory.rglob("*.py") if "__pycache__" not in path.parts)


def _python_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _typescript_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("export ") and " from " in stripped:
            marker = " from "
            if marker in stripped:
                imports.add(stripped.split(marker, 1)[1].strip().rstrip(";\"").strip('"'))
    return imports


def test_core_does_not_depend_on_product_surface_or_desktop():
    forbidden = ("viva", "viva.surface", "desktop", "react", "tauri")
    violations = []
    for path in _python_files(ROOT / "core"):
        for imported in _python_imports(path):
            if imported == "viva" or imported.startswith(("viva.", "desktop", "product")):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert not violations, "\n".join(violations)


def test_product_engine_does_not_depend_on_surface_or_desktop():
    violations = []
    for path in _python_files(ROOT / "product" / "viva"):
        if path.parts[-2:] == ("surface", path.name):
            continue
        for imported in _python_imports(path):
            if imported == "viva.surface" or imported.startswith(("viva.surface.", "desktop")):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert not violations, "\n".join(violations)


def test_surface_contract_does_not_depend_on_react_or_tauri():
    violations = []
    for path in _python_files(ROOT / "product" / "viva" / "surface"):
        for imported in _python_imports(path):
            if imported == "react" or imported.startswith(("react.", "tauri", "desktop")):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert not violations, "\n".join(violations)


def test_desktop_consumes_local_surface_boundary_without_python_imports():
    violations = []
    for path in sorted((ROOT / "desktop" / "src").rglob("*.ts*")):
        for imported in _typescript_imports(path):
            if imported == "viva" or imported.startswith(("viva/", "viva.", "vivacore", "@tauri-apps")):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("directory", [ROOT / "core", ROOT / "product" / "viva" / "surface"])
def test_python_surface_layers_are_syntax_valid(directory: Path):
    for path in _python_files(directory):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

