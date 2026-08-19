"""Every workflow file loads as a document that declares jobs with steps.

A workflow that cannot be parsed is rejected whole rather than failing, so every
gate named inside it stops running and reports nothing. The subject here is the
structure of the file, never the text of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow_files() -> list[Path]:
    assert WORKFLOWS.is_dir(), f"the workflow directory is missing: {WORKFLOWS}"
    files = sorted(WORKFLOWS.glob("*.y*ml"))
    assert files, f"no workflow files under {WORKFLOWS}; this test's grip is gone"
    return files


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda path: path.name)
def test_every_workflow_file_parses(workflow: Path):
    """A workflow GitHub cannot parse is rejected whole and runs nothing."""
    try:
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise AssertionError(
            f"{workflow.relative_to(ROOT)} is not loadable, so every job in it "
            f"is absent from the build rather than failing in it:\n{error}"
        ) from None

    assert isinstance(document, dict), (
        f"{workflow.relative_to(ROOT)} does not describe a workflow"
    )
    assert document.get("jobs"), (
        f"{workflow.relative_to(ROOT)} declares no jobs, so it runs nothing"
    )


def test_every_declared_job_has_steps_to_run():
    for workflow in _workflow_files():
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for name, job in document["jobs"].items():
            assert job.get("steps") or job.get("uses"), (
                f"{workflow.relative_to(ROOT)}: job {name!r} runs nothing"
            )
