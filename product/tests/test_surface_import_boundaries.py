"""AST checks for the dependency direction of the surface architecture."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PRODUCT_PACKAGE = ROOT / "product" / "viva"

ENGINE = "engine"
SURFACE = "surface"
BRIDGE = "bridge"
FRONTEND = "frontend"

# Every module inside the product package belongs to exactly one tier. A
# directory named here claims its whole subtree; anything else is the engine.
TIER_DIRECTORIES: dict[str, str] = {
    "surface": SURFACE,
    "desktop_bridge": BRIDGE,
}
DEFAULT_TIER = ENGINE

# The tier an imported module name belongs to. The longest matching prefix
# wins; a name matching no prefix is a third-party dependency and has no tier.
TIER_MODULES: dict[str, str] = {
    "viva": ENGINE,
    "viva.surface": SURFACE,
    "viva.desktop_bridge": BRIDGE,
    # The repository root is on the import path, so every module above is also
    # reachable under a second name. Both spellings map to the same tier.
    "product.viva": ENGINE,
    "product.viva.surface": SURFACE,
    "product.viva.desktop_bridge": BRIDGE,
    "react": FRONTEND,
    "tauri": FRONTEND,
}

# The frontend tier is a directory in this repository, not a spelling. A module
# belongs to it when its top-level name resolves to a path inside that
# directory, so the edge holds for whatever the tree is called and does not
# depend on matching a name prefix.
FRONTEND_ROOT = ROOT / "desktop"

# The dependency direction, declared as the edges that are allowed to exist.
# An edge absent from this set is a violation, so the frontend tier is
# unreachable from Python by construction rather than by a list of exclusions.
PERMITTED_EDGES: frozenset[tuple[str, str]] = frozenset({
    (ENGINE, ENGINE),
    (SURFACE, SURFACE),
    (SURFACE, ENGINE),
    (BRIDGE, BRIDGE),
    (BRIDGE, SURFACE),
    (BRIDGE, ENGINE),
})


def _python_files(directory: Path):
    return sorted(path for path in directory.rglob("*.py") if "__pycache__" not in path.parts)


def _package_of(path: Path) -> list[str]:
    """Return the dotted package parts of the module at this path."""
    return list(path.relative_to(PRODUCT_PACKAGE.parent).parts[:-1])


def _python_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _package_of(path) if path.is_relative_to(PRODUCT_PACKAGE) else []
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                if node.module:
                    imports.add(node.module)
                continue
            # A relative import names the same module a dotted path would, so
            # it is resolved rather than skipped; otherwise a tier could be
            # crossed by writing a leading dot.
            base = package[: len(package) - node.level + 1]
            imports.add(".".join([*base, node.module] if node.module else base))
    return imports


def _tier_of_file(path: Path) -> str:
    relative = path.relative_to(PRODUCT_PACKAGE)
    for part in relative.parts[:-1]:
        tier = TIER_DIRECTORIES.get(part)
        if tier is not None:
            return tier
    return DEFAULT_TIER


def _resolves_into_frontend(module: str) -> bool:
    """True when a module name resolves to a path inside the frontend tree."""
    candidate = ROOT / module.split(".")[0]
    return candidate == FRONTEND_ROOT or FRONTEND_ROOT in candidate.parents


def _tier_of_module(module: str) -> str | None:
    matched: str | None = None
    for prefix, tier in TIER_MODULES.items():
        if module == prefix or module.startswith(f"{prefix}."):
            if matched is None or len(prefix) > len(matched):
                matched = prefix
    if matched is not None:
        return TIER_MODULES[matched]
    return FRONTEND if _resolves_into_frontend(module) else None


def test_core_does_not_depend_on_product_surface_or_desktop():
    files = _python_files(ROOT / "core")

    assert files, f"no modules found under {ROOT / 'core'}; this test's grip is gone"
    violations = []
    for path in files:
        for imported in _python_imports(path):
            if imported == "viva" or imported.startswith(("viva.", "desktop", "product")):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert not violations, "\n".join(violations)


def test_every_declared_tier_has_modules_in_it():
    populated = {_tier_of_file(path) for path in _python_files(PRODUCT_PACKAGE)}

    declared = set(TIER_DIRECTORIES.values()) | {DEFAULT_TIER}
    missing = sorted(declared - populated)
    assert not missing, f"declared tiers with no modules: {', '.join(missing)}"


def test_product_tiers_import_only_along_permitted_edges():
    assert FRONTEND_ROOT.is_dir(), (
        f"the frontend tree is missing: {FRONTEND_ROOT}; the edge forbidding "
        "the engine to reach into it resolves against nothing"
    )
    violations = []
    for path in _python_files(PRODUCT_PACKAGE):
        importer = _tier_of_file(path)
        for imported in _python_imports(path):
            tier = _tier_of_module(imported)
            if tier is None or (importer, tier) in PERMITTED_EDGES:
                continue
            violations.append(
                f"{path.relative_to(ROOT)} ({importer}) imports {imported} ({tier})"
            )
    assert not violations, "\n".join(violations)


def test_surface_contract_does_not_depend_on_react_or_tauri():
    violations = []
    for path in _python_files(PRODUCT_PACKAGE / "surface"):
        for imported in _python_imports(path):
            if imported == "react" or imported.startswith(("react.", "tauri", "desktop")):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("directory", [ROOT / "core", PRODUCT_PACKAGE / "surface"])
def test_python_surface_layers_are_syntax_valid(directory: Path):
    files = _python_files(directory)

    assert files, f"no modules found under {directory}; this test's grip is gone"
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
