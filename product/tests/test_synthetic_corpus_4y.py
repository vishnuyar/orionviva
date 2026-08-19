import json
import subprocess
from pathlib import Path

import pytest


PYTHON = "/Users/vishnu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
ROOT = Path(__file__).resolve().parents[2]


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
def test_four_year_corpus_generator_smoke(tmp_path):
    out_dir = tmp_path / "corpus4y"
    subprocess.run(
        [
            PYTHON,
            "scripts/generate_synthetic_corpus_4y.py",
            "--output",
            str(out_dir),
            "--years",
            "1",
            "--start-year",
            "2025",
            "--start-month",
            "1",
        ],
        cwd=ROOT,
        check=True,
    )

    pdfs = sorted(p.name for p in out_dir.glob("*.pdf"))
    assert len(pdfs) == 44
    assert "silverline-checking-2025-01.pdf" in pdfs
    assert "northgate-brokerage-2025-01-to-2025-03.pdf" in pdfs

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["range"] == {"from": "2025-01-01", "to": "2025-12-31"}
    assert len(manifest["documents"]) == 44
    assert manifest["documents"][0]["page_count"] in {1, 2}

