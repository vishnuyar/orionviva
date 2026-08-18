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
DECLARATION_KEYS = ("interface impact:", "surface impact:")


def changed_paths(root: Path, base: str = "HEAD") -> list[str]:
    command = ["git", "diff", "--name-only", "--diff-filter=ACMR", base, "--"]
    result = subprocess.run(command, cwd=root, check=True, text=True, capture_output=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


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
    base: str = "HEAD",
    declaration: str | None = None,
    unchanged_proof: bool = False,
) -> None:
    paths = changed_paths(root, base)
    sensitive = [path for path in paths if is_sensitive(path)]
    if not sensitive:
        print("surface impact: no backend-sensitive changes")
        return

    declared = declaration_value(declaration or os.environ.get("ORIONVIVA_INTERFACE_IMPACT"))
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
    raise SystemExit(
        "backend-sensitive changes require an interface-impact declaration or "
        f"surface contract coverage: {changed}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check the current diff (the default)")
    parser.add_argument("--base", default="HEAD", help="git revision to compare against")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--declaration", choices=("none", "changed", "unchanged"))
    parser.add_argument(
        "--unchanged-proof",
        action="store_true",
        help="confirm tests or an adapter prove the existing surface is unchanged",
    )
    args = parser.parse_args(argv)
    check_impact(
        args.root.resolve(),
        base=args.base,
        declaration=args.declaration,
        unchanged_proof=args.unchanged_proof,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
