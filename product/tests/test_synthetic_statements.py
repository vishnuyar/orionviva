import json
import subprocess
import sys
from pathlib import Path

def test_synthetic_statement_generator_creates_manifest_and_pdfs(tmp_path):
    out_dir = tmp_path / "synthetic"
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, "scripts/generate_synthetic_statements.py",
         "--output", str(out_dir)],
        cwd=root,
        check=True,
    )
    generated = out_dir

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
