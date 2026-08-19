#!/usr/bin/env python3
"""Check that backend-sensitive changes declare their surface impact."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# These paths can change the meaning, shape, or availability of a surface read.
SENSITIVE_PREFIXES = (
    "product/viva/engine.py",
    "product/viva/questions.py",
    "product/viva/render.py",
    "product/viva/quantity.py",
    "product/viva/persona/",
    "product/viva/ingest/",
    "product/viva/ledger/",
    "product/viva/agent/",
    "product/viva/reply.py",
    "product/viva/speak.py",
    "product/viva/ask.py",
)
SURFACE_PREFIXES = (
    "product/viva/surface/",
    "desktop/",
    "scripts/check_surface_contract.py",
    "scripts/check_surface_impact.py",
)
# A declaration may be written in the commit message under either key.
DECLARATION_KEYS = ("interface impact:", "surface impact:")


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=check, text=True, capture_output=True
    )


def default_base(root: Path) -> str:
    """Return the commit before the tip, or the tip when there is no parent.

    A tree compared against itself reports no change, so the base is a revision
    that can differ from the working tree. `HEAD` is the fallback when no
    parent commit is reachable, and in that case the diff half of the changed
    set reports nothing; only untracked paths are seen. A checkout fetched to a
    depth of one reaches this fallback, so a build that wants this gate to see
    committed changes fetches at least two.
    """
    parent = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^", check=False)
    return parent.stdout.strip() if parent.returncode == 0 else "HEAD"


def commit_declaration(root: Path) -> str | None:
    """Return the impact declaration written in the tip commit's message."""
    message = _git(root, "log", "-1", "--format=%B", check=False)
    if message.returncode != 0:
        return None
    for line in message.stdout.splitlines():
        normalized = line.strip().lower()
        for key in DECLARATION_KEYS:
            if normalized.startswith(key):
                return normalized[len(key) :].strip()
    return None


def changed_paths(root: Path, base: str) -> list[str]:
    """Return every path this change adds or edits, tracked or not.

    `git diff` reports nothing about a file git has never seen, so untracked
    paths are collected separately and merged into the same set.
    """
    tracked = _git(root, "diff", "--name-only", "--diff-filter=ACMR", base, "--")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    paths = {
        line.strip()
        for line in (*tracked.stdout.splitlines(), *untracked.stdout.splitlines())
        if line.strip()
    }
    return sorted(paths)


def is_sensitive(path: str) -> bool:
    return path.startswith(SENSITIVE_PREFIXES)


def has_surface_change(paths: list[str]) -> bool:
    return any(path.startswith(SURFACE_PREFIXES) for path in paths)


def declaration_value(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"none", "changed", "unchanged"}:
        return normalized
    raise ValueError("impact declaration must be one of: none, changed, unchanged")


def check_impact(
    root: Path = ROOT,
    *,
    base: str | None = None,
    declaration: str | None = None,
    unchanged_proof: bool = False,
) -> None:
    paths = changed_paths(root, base or default_base(root))
    sensitive = [path for path in paths if is_sensitive(path)]
    if not sensitive:
        print("surface impact: no backend-sensitive changes")
        return

    declared = declaration_value(
        declaration
        or os.environ.get("ORIONVIVA_INTERFACE_IMPACT")
        or commit_declaration(root)
    )
    if declared == "none":
        if not unchanged_proof:
            raise SystemExit(
                "interface impact is declared none, but --unchanged-proof is required "
                "for backend-sensitive changes"
            )
        print("surface impact: none (explicit unchanged-contract proof)")
        return
    if declared in {"changed", "unchanged"} or has_surface_change(paths):
        print("surface impact: declared and covered")
        return
    changed = ", ".join(sensitive)
    keys = " or ".join(f"`{key} changed`" for key in DECLARATION_KEYS)
    raise SystemExit(
        "backend-sensitive changes require an interface-impact declaration or "
        f"surface contract coverage: {changed}\n"
        f"declare it in the commit message ({keys}), with --declaration, or in "
        "ORIONVIVA_INTERFACE_IMPACT"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check the current diff (the default)")
    parser.add_argument(
        "--base",
        help="git revision to compare against (default: the commit before the tip)",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--declaration", choices=("none", "changed", "unchanged"))
    parser.add_argument(
        "--unchanged-proof",
        action="store_true",
        help="confirm tests or an adapter prove the existing surface is unchanged",
    )
    args = parser.parse_args(argv)
    try:
        check_impact(
            args.root.resolve(),
            base=args.base,
            declaration=args.declaration,
            unchanged_proof=args.unchanged_proof,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
