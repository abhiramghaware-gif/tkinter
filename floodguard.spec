# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for CHENNAI FLOODGUARD Windows desktop packaging."""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project_root = Path.cwd()

datas = [
    (str(project_root / "database" / "schema.sql"), "database"),
    (str(project_root / "assets"), "assets"),
]
seed_db = project_root / "data" / "floodguard.db"
if seed_db.exists():
    datas.append((str(seed_db), "data"))

hiddenimports = [
    "tkinter",
    "tkinter.ttk",
    "matplotlib.backends.backend_tkagg",
    "matplotlib.backends.backend_pdf",
    "PIL._tkinter_finder",
]
for pkg in ("core", "database", "emergency", "gui", "routing", "services", "visualization"):
    hiddenimports.extend(collect_submodules(pkg))

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "_pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChennaiFloodGuard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ChennaiFloodGuard",
)
