"""Run affected tests locally, or complete package suites at verification gates.

Python selection follows a conservative static import closure. Resources,
configuration and unrecognized paths fall back to complete suites; this is a
feedback command, not a replacement for the complete CI and release gates.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {"core": "vivacore", "merchant": "merchantcore",
            "product": "viva", "bench": "vivabench"}


@dataclass
class Plan:
    python: list[str]
    desktop: list[str] | None
    reason: str


def full_plan(reason: str) -> Plan:
    return Plan(list(PACKAGES), [], reason)


def changed_files(root: Path, base: str | None) -> list[str]:
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root).decode().split("\0")
    # Diff against HEAD includes staged and unstaged edits. An explicit base
    # includes committed branch work as well. Untracked tests matter too.
    return sorted(set(filter(None, git("diff", "--name-only", "-z", base or "HEAD")
                             + git("ls-files", "--others", "--exclude-standard", "-z"))))


def python_selection(root: Path, changes: set[str]) -> list[str]:
    modules: dict[str, str] = {}
    sources: dict[str, Path] = {}
    for package, namespace in PACKAGES.items():
        for path in (root / package).rglob("*.py"):
            relative = path.relative_to(root).as_posix()
            parts = path.relative_to(root / package).with_suffix("").parts
            module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            # Test helpers are imported by their short names by pytest.
            if parts[0] == "tests":
                module = parts[-1]
            elif parts[0] != namespace:
                continue
            modules[relative] = module
            sources[relative] = path

    dependencies: dict[str, set[str]] = {}
    all_modules = set(modules.values())
    paths_by_module: dict[str, set[str]] = defaultdict(set)
    initializers = set()
    for path, module in modules.items():
        paths_by_module[module].add(path)
        if sources[path].name == "__init__.py":
            initializers.add(module)
    for relative, path in sources.items():
        module = modules[relative]
        parent = module if path.name == "__init__.py" else module.rpartition(".")[0]
        imports = set()
        dynamic = False
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=relative)):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                prefix = node.module or ""
                if node.level:
                    parts = parent.split(".")
                    prefix = ".".join(parts[:len(parts) - node.level + 1]
                                      + ([prefix] if prefix else []))
                imports.add(prefix)
                imports.update(f"{prefix}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Include literal dynamic imports and monkeypatch targets.
                parts = node.value.split(".")
                for end in range(1, len(parts) + 1):
                    candidate = ".".join(parts[:end])
                    if candidate in all_modules:
                        imports.add(candidate)
            elif isinstance(node, ast.Call):
                name = (node.func.id if isinstance(node.func, ast.Name) else
                        node.func.attr if isinstance(node.func, ast.Attribute) else "")
                if name in {"import_module", "__import__"} and (
                        not node.args or not isinstance(node.args[0], ast.Constant)):
                    dynamic = True
        # Re-exports are followed through the package's own imports. Parents
        # also execute their __init__ when a child is imported.
        targets = set(sources) if dynamic else set()
        for item in imports:
            targets.update(paths_by_module.get(item, ()))
            parts = item.split(".")
            for end in range(1, len(parts)):
                parent_module = ".".join(parts[:end])
                if parent_module in initializers:
                    targets.update(paths_by_module[parent_module])
        dependencies[relative] = targets - {relative}

    importers: dict[str, set[str]] = defaultdict(set)
    for path, targets in dependencies.items():
        for target in targets:
            importers[target].add(path)
    selected = set()
    for changed in changes:
        affected, pending = set(), [changed]
        while pending:
            path = pending.pop()
            if path not in affected:
                affected.add(path)
                pending.extend(importers[path] - affected)
        tests = {path for path in affected
                 if path in sources and Path(path).name.startswith("test_")}
        # Apply this fallback to each changed source. A covered source must
        # never hide another changed module with no discovered dependents.
        selected.update(tests or {changed.split("/")[0]})
    packages = selected & PACKAGES.keys()
    return sorted(path for path in selected
                  if path in packages or path.split("/")[0] not in packages)


def make_plan(root: Path, files: list[str]) -> Plan:
    changes = set(files)
    if not changes:
        return Plan([], None, "No changed files.")
    python = set()
    desktop = []
    for name in changes:
        path = Path(name)
        if path.parts[0] in PACKAGES and path.suffix == ".py":
            if len(path.parts) < 3 or path.parts[1] not in {PACKAGES[path.parts[0]], "tests"}:
                return full_plan("Unmapped Python paths: complete suites.")
            if not (root / name).is_file() or path.name in {"conftest.py", "__init__.py"}:
                return full_plan("Deleted files or Python collection/package changes: complete suites.")
            python.add(name)
        elif name.startswith("desktop/src/") and path.suffix in {".ts", ".tsx"}:
            if not (root / name).is_file() or name.startswith("desktop/src/test/"):
                return full_plan("Deleted files or shared test setup: complete suites.")
            desktop.append(name.removeprefix("desktop/"))
        else:
            return full_plan("Resources, configuration, tooling or unmapped changes: complete suites.")
    # Backend source can alter any serialized UI contract. Use related UI
    # selection only when no backend source changes.
    backend_source = any(Path(name).parts[1] != "tests" for name in python)
    return Plan(python_selection(root, python) if python else [],
                [] if backend_source else sorted(desktop) or None,
                "Affected Python import closure; complete UI for backend source edits."
                if backend_source else "Tests related to the changed Python tests and UI source files.")


def commands(plan: Plan) -> list[tuple[Path, list[str]]]:
    result = []
    if plan.python:
        result.append((ROOT, [sys.executable, "-m", "pytest", *plan.python, "-q", "--durations=10"]))
    if plan.desktop is not None:
        result.append((ROOT / "desktop", ["npm.cmd" if os.name == "nt" else "npm",
            "exec", "--", "vitest", *(["related", *plan.desktop, "--run"]
                                        if plan.desktop else ["run"])]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="complete Python and UI suites")
    group.add_argument("--package", choices=[*PACKAGES, "desktop"])
    group.add_argument("--files", nargs="+", help="repository-relative changed paths")
    parser.add_argument("--base", help="compare working tree with this Git ref (default HEAD)")
    parser.add_argument("--dry-run", action="store_true", help="show the selection without running it")
    args = parser.parse_args()
    if args.all:
        plan = full_plan("Explicit complete-suite run.")
    elif args.package:
        plan = Plan([] if args.package == "desktop" else [args.package],
                    [] if args.package == "desktop" else None, "Explicit complete package run.")
    else:
        files = args.files if args.files is not None else changed_files(ROOT, args.base)
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in files):
            parser.error("--files requires paths relative to the repository root")
        plan = make_plan(ROOT, files)
    print(plan.reason, flush=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / part) for part in [".", *PACKAGES])
    for directory, command in commands(plan):
        print(f"[{directory.relative_to(ROOT) or '.'}] {' '.join(command)}", flush=True)
        if not args.dry_run:
            completed = subprocess.run(command, cwd=directory, env=env)
            if completed.returncode:
                return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
