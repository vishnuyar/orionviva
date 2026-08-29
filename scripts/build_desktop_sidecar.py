#!/usr/bin/env python3
"""Build and stage the PyInstaller executable consumed by Tauri."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn


ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT / "product"
SPEC = PRODUCT / "viva" / "desktop_bridge" / "viva-desktop-bridge.spec"
SIDECAR_NAME = "viva-desktop-bridge"


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"sidecar build: {message}")


def build_revision() -> str:
    """Name the exact source state embedded in this packaged executable."""
    found = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD"],
        capture_output=True, text=True, check=False)
    revision = found.stdout.strip()
    if found.returncode or not revision.isalnum() or len(revision) < 7:
        fail("git could not establish the source revision for this build")
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        capture_output=True, text=True, check=False)
    if dirty.returncode:
        fail("git could not establish whether the source tree has changes")
    return f"{revision}+changes" if dirty.stdout.strip() else revision


def main() -> int:
    # Validate the interpreter that is running this build.
    if sys.version_info < (3, 11):
        fail("Python 3.11 or newer is required by the product runtime; "
             f"found {sys.version.split()[0]} ({sys.executable})")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", help="Rust target triple used by Tauri")
    args = parser.parse_args()

    if not SPEC.is_file():
        fail(f"missing PyInstaller spec: {SPEC}")

    target = args.target or os.environ.get("TAURI_ENV_TARGET_TRIPLE")
    if not target:
        rustc = shutil.which("rustc")
        if not rustc:
            fail("a target triple is required via --target or TAURI_ENV_TARGET_TRIPLE; rustc is unavailable")
        result = subprocess.run([rustc, "-vV"], capture_output=True, text=True, check=False)
        if result.returncode:
            fail("rustc could not report its host target triple")
        target = next((line.split(":", 1)[1].strip() for line in result.stdout.splitlines() if line.startswith("host:")), None)
        if not target:
            fail("rustc did not report a host target triple")

    pyinstaller = [sys.executable, "-m", "PyInstaller"]
    check = subprocess.run(
        [*pyinstaller, "--version"], cwd=PRODUCT, capture_output=True, text=True, check=False
    )
    if check.returncode:
        fail(
            f"PyInstaller is unavailable for {sys.executable}; "
            "install product/requirements-sidecar-build.txt"
        )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.glob(f"{SIDECAR_NAME}-*"):
        if existing.is_file():
            existing.unlink()

    with tempfile.TemporaryDirectory(prefix="orionviva-sidecar-") as temporary:
        temporary_root = Path(temporary)
        revision_file = temporary_root / "REVISION"
        revision_file.write_text(build_revision() + "\n", encoding="utf-8")
        build_environment = dict(os.environ)
        build_environment["VIVA_BUILD_REVISION_FILE"] = str(revision_file)
        subprocess.run(
            [
                *pyinstaller,
                "--noconfirm",
                "--clean",
                "--distpath",
                str(temporary_root / "dist"),
                "--workpath",
                str(temporary_root / "work"),
                str(SPEC),
            ],
            cwd=PRODUCT,
            env=build_environment,
            check=True,
        )
        suffix = ".exe" if "windows" in target else ""
        built = temporary_root / "dist" / f"{SIDECAR_NAME}{suffix}"
        if not built.is_file():
            fail(f"PyInstaller did not produce {built}")
        staged = output_dir / f"{SIDECAR_NAME}-{target}{suffix}"
        shutil.copy2(built, staged)

    print(f"sidecar build: staged {staged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
