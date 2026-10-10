import json
import os

import PyInstaller
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
    (PRODUCT_ROOT / "viva/ledger/networth.py", "viva/ledger"),
    (PRODUCT_ROOT / "viva/ledger/accounting.py", "viva/ledger"),
    (PRODUCT_ROOT / "viva/read_store/overview.py", "viva/read_store"),
    (PRODUCT_ROOT / "viva/surface/overview.py", "viva/surface"),
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


RUNTIME_HOOK = Path(SPECPATH) / "pyi_rth_admission_sources.py"
INSPECT_HOOK = Path(PyInstaller.__file__).parent / "hooks/rthooks/pyi_rth_inspect.py"
SOURCE_MANIFEST = Path(workpath) / "admission-source-map.json"
SOURCE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
source_map = {}
for source, destination in ADMISSION_SOURCES:
    relative = f"{destination}/{source.name}"
    name = relative[:-3].replace("/", ".")
    if name.endswith(".__init__"):
        name = name[:-9]
    if name in source_map:
        raise SystemExit("sidecar build: duplicate admission module")
    source_map[name] = relative
SOURCE_MANIFEST.write_text(json.dumps(source_map, sort_keys=True), encoding="utf-8")


def _order_inspection_hooks(scripts, custom_path, builtin_path, program_path):
    """Keep every script's order except the bounded inspection wrapper."""
    original = list(scripts)

    def entry_for(name, path):
        matches = [entry for entry in original if
                   entry[0] == name or Path(entry[1]).resolve() == path.resolve()]
        if (len(matches) != 1 or matches[0][0] != name or
                Path(matches[0][1]).resolve() != path.resolve() or
                matches[0][2] != "PYSOURCE"):
            raise SystemExit("sidecar build: inconsistent inspection hook table")
        return matches[0]

    custom = entry_for("pyi_rth_admission_sources", custom_path)
    builtin = entry_for("pyi_rth_inspect", builtin_path)
    program = entry_for("__main__", program_path)
    others = [entry for entry in original if entry is not custom]
    ordered = list(others)
    ordered.insert(ordered.index(builtin) + 1, custom)
    if (ordered.index(custom) != ordered.index(builtin) + 1 or
            ordered.index(program) <= ordered.index(custom) or
            len(ordered) != len(original) or
            [entry for entry in ordered if entry is not custom] != others or
            ordered.count(custom) != 1 or ordered.count(builtin) != 1):
        raise SystemExit("sidecar build: invalid inspection hook order")
    return ordered


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
        + [(str(SOURCE_MANIFEST), ".")]
    ),
    hiddenimports=["sqlcipher3", "sqlcipher3.dbapi2"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(RUNTIME_HOOK)],
    excludes=[],
    noarchive=False,
)


analysis.scripts = _order_inspection_hooks(
    analysis.scripts, RUNTIME_HOOK, INSPECT_HOOK,
    PRODUCT_ROOT / "viva/desktop_bridge/__main__.py",
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
