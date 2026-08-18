import json
import subprocess
from pathlib import Path


PYTHON = "/Users/vishnu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"


def test_synthetic_statement_generator_creates_manifest_and_pdfs(tmp_path):
    out_dir = tmp_path / "synthetic"
    subprocess.run([PYTHON, "scripts/generate_synthetic_statements.py"], cwd=Path(__file__).resolve().parents[2], check=True)
    generated = Path("/Users/vishnu/orionviva-surface/output/pdf/synthetic_statements")

    pdfs = sorted(p.name for p in generated.glob("*.pdf"))
    assert len(pdfs) == 28
    assert "north-river-checking-june-2023.pdf" in pdfs
    assert "chase-card-june-2026.pdf" in pdfs
    assert "fidelity-brokerage-june-2025.pdf" in pdfs

    manifest = json.loads((generated / "manifest.json").read_text())
    assert manifest["purpose"].startswith("synthetic statement set")
    assert len(manifest["documents"]) == 28
    files = {doc["file"] for doc in manifest["documents"]}
    assert "fidelity-brokerage-june-2024.pdf" in files
    assert any("Amazon Marketplace" in doc["merchants"] for doc in manifest["documents"])
    assert any("Newrez" in doc["merchants"] for doc in manifest["documents"])
