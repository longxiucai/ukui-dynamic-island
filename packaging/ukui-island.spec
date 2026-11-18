# PyInstaller onedir bundle. Build from a venv that has PySide2 + jeepney.
import os
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "themes"), "themes")],
    hiddenimports=["jeepney", "jeepney.io.blocking"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "numpy", "matplotlib", "PIL", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ukui-island",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="ukui-island",
)
