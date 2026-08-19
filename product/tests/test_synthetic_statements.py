import json
import subprocess
from pathlib import Path

import pytest


PYTHON = "/Users/vishnu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"


@pytest.mark.xfail(
    reason=(
        "Brief B — The Gates That Cannot Fail — owns this classification: "
        "the test invokes the generator through an absolute interpreter "
        "path and the generator reads its catalog from an absolute "
        "home-directory path, so this has never been able to pass outside "
        "one machine. The repair is fenced out of B and is owned by no "
        "brief."
    ),
    strict=True,
)
def test_synthetic_statement_generator_creates_manifest_and_pdfs(tmp_path):
    out_dir = tmp_path / "synthetic"
    subprocess.run([PYTHON, "scripts/generate_synthetic_statements.py"], cwd=Path(__file__).resolve().parents[2], check=True)
    generated = Path("/Users/vishnu/orionviva-surface/output/pdf/synthetic_statements")

    pdfs = sorted(p.name for p in generated.glob("*.pdf"))
    assert len(pdfs) == 28
    assert "north-river-checking-june-2023.pdf" in pdfs
    assert "harborline-card-june-2026.pdf" in pdfs
    assert "northgate-brokerage-june-2025.pdf" in pdfs

    manifest = json.loads((generated / "manifest.json").read_text())
    assert manifest["purpose"].startswith("synthetic statement set")
    assert len(manifest["documents"]) == 28
    files = {doc["file"] for doc in manifest["documents"]}
    assert "northgate-brokerage-june-2024.pdf" in files
    assert any("Riverbend Market" in doc["merchants"] for doc in manifest["documents"])
    assert any("Ridgeline Servicing" in doc["merchants"] for doc in manifest["documents"])
