import os
from pathlib import Path

from PyInstaller.building.build_main import Analysis, EXE, PYZ
from PyInstaller.utils.hooks import collect_data_files


PRODUCT_ROOT = Path(SPECPATH).parents[1]
REPOSITORY_ROOT = PRODUCT_ROOT.parent
REVISION_SOURCE = os.environ.get("VIVA_BUILD_REVISION_FILE", "")
if not REVISION_SOURCE or not Path(REVISION_SOURCE).is_file():
    raise SystemExit("sidecar build: VIVA_BUILD_REVISION_FILE does not name a revision file")

ADMISSION_SOURCES = [
    (PRODUCT_ROOT / "viva/ledger/scenarios.py", "viva/ledger"),
    (PRODUCT_ROOT / "viva/tools/scenarios.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/answer_program/capability_fixture.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/admission_fixture.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/admission.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/eval.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/ledger/movement_identity.py", "viva/ledger"),
    (PRODUCT_ROOT / "viva/ledger/events.py", "viva/ledger"),
    (PRODUCT_ROOT / "viva/ledger/postings.py", "viva/ledger"),
    (PRODUCT_ROOT / "viva/answer_program/intents.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/compiler.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/runtime.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/replay.py", "viva/answer_program"),
    (REPOSITORY_ROOT / "core/vivacore/models/openai_compat.py", "vivacore/models"),
    (PRODUCT_ROOT / "viva/answer_program/capabilities.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/tools/ledger_aggregates.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/ledger_common.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/ledger_movements.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/ledger_vocabulary.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/ledger/projection/movements.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/projection/categories.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/projection/merchants.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/statements.py", "viva/ledger"),
    (PRODUCT_ROOT / "viva/tools/__init__.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/registry.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/ledger_tools.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/ledger/projection/core.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/projection/accounts.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/projection/balances.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/projection/rhythm.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/streams.py", "viva/ledger"),
    (PRODUCT_ROOT / "viva/tools/measurements.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/projections.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/ledger/projection/measurements.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/projection/positions.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/projection/current_period.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/projection/obligations.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ledger/projection/goals.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/ingest/brokerage.py", "viva/ingest"),
    (REPOSITORY_ROOT / "core/vivacore/verify/arithmetic.py", "vivacore/verify"),
    (REPOSITORY_ROOT / "core/vivacore/verify/normalize.py", "vivacore/verify"),
    (PRODUCT_ROOT / "viva/ledger/projection/__init__.py", "viva/ledger/projection"),
    (PRODUCT_ROOT / "viva/answer_program/bind.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/execute.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/evidence.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/validate.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/answer_program/schema.py", "viva/answer_program"),
    (PRODUCT_ROOT / "viva/tools/envelope.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/boundary.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/shape.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/runner_binding.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/runner_delivery.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/runner.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/tools/compute.py", "viva/tools"),
    (PRODUCT_ROOT / "viva/quantity.py", "viva"),
    (PRODUCT_ROOT / "viva/render.py", "viva"),
]
for source, destination in ADMISSION_SOURCES:
    if not source.is_file():
        raise SystemExit(f"sidecar build: missing admission source {source.name}")


analysis = Analysis(
    [str(PRODUCT_ROOT / "viva" / "desktop_bridge" / "__main__.py")],
    pathex=[
        str(PRODUCT_ROOT),
        str(REPOSITORY_ROOT / "core"),
        str(REPOSITORY_ROOT / "merchant"),
    ],
    binaries=[],
    datas=(
        collect_data_files("viva", include_py_files=False)
        + collect_data_files("vivacore", include_py_files=False)
        + collect_data_files("merchantcore", include_py_files=False)
        + [(str(source), destination) for source, destination in ADMISSION_SOURCES]
        + [(REVISION_SOURCE, "viva")]
    ),
    hiddenimports=["sqlcipher3", "sqlcipher3.dbapi2"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)


pyz = PYZ(analysis.pure)


EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="viva-desktop-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
