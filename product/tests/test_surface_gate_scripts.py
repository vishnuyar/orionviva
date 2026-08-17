"""Executable contract tests for the Slice 0 surface gates."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
GATES = ("check_surface_contract.py", "check_surface_impact.py")


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("script", GATES)
def test_surface_gate_script_exists(script: str):
    path = ROOT / "scripts" / script
    assert path.is_file(), f"missing Slice 0 gate: {path}"


@pytest.mark.parametrize("script", GATES)
def test_surface_gate_exposes_help(script: str):
    result = _run(script, "--help")

    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()


@pytest.mark.parametrize("script", GATES)
def test_surface_gate_check_mode_passes_current_tree(script: str):
    result = _run(script, "--check")

    assert result.returncode == 0, result.stderr or result.stdout

