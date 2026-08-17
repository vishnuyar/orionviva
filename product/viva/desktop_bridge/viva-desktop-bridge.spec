from pathlib import Path

from PyInstaller.building.build_main import Analysis, EXE, PYZ
from PyInstaller.utils.hooks import collect_data_files


PRODUCT_ROOT = Path(SPECPATH).parents[1]
REPOSITORY_ROOT = PRODUCT_ROOT.parent


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
    ),
    hiddenimports=[],
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
