"""Reproducible Windows packaging helper for CHENNAI FLOODGUARD using PyInstaller."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    spec_path = root / "floodguard.spec"
    if not spec_path.exists():
        print(f"Missing spec file: {spec_path}", file=sys.stderr)
        return 1

    if importlib.util.find_spec("PyInstaller") is None:
        print(
            "PyInstaller is not installed in this Python environment.\n"
            "Install it with:\n"
            "    pip install pyinstaller>=6.0\n"
            "Then re-run:\n"
            "    python build_windows.py\n"
            "Or directly:\n"
            "    pyinstaller --clean floodguard.spec",
            file=sys.stderr,
        )
        return 2

    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(spec_path)]
    print("Running:", " ".join(cmd))
    res = subprocess.run(cmd, cwd=root)
    if res.returncode == 0:
        dist_dir = root / "dist" / "ChennaiFloodGuard"
        print(f"\nBuild complete: {dist_dir / 'ChennaiFloodGuard.exe'}")
        print(
            "User data (SQLite DB, backups, exports, logs) will be stored in "
            "%LOCALAPPDATA%\\ChennaiFloodGuard when running the packaged executable."
        )
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
