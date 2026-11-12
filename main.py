"""Application entry point for CHENNAI FLOODGUARD (Phases 1–7)."""

from __future__ import annotations

import logging
import shutil
import sys
import traceback
from pathlib import Path

from config import APP_NAME, BUNDLE_DIR, DATA_DIR, DB_PATH, LOG_PATH


def configure_logging() -> None:
    """Configure console and file logging safely inside writable data directory."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def ensure_writable_initial_database() -> None:
    """When packaged with a seed DB and no local DB exists yet, copy it to writable app-data."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bundled_db = BUNDLE_DIR / "data" / "floodguard.db"
    if getattr(sys, "frozen", False) and not DB_PATH.exists() and bundled_db.exists():
        shutil.copy2(bundled_db, DB_PATH)


def _show_startup_error(title: str, message: str) -> None:
    """Display a clean Tkinter startup error dialog without leaking stack internals unnecessarily."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)


def main() -> int:
    try:
        configure_logging()
        ensure_writable_initial_database()
        from gui.app import FloodGuardApp

        app = FloodGuardApp()
        app.mainloop()
        return 0
    except Exception as exc:
        logging.getLogger(__name__).exception("Fatal application startup error")
        err_note = (
            f"{APP_NAME} encountered a startup error:\n\n{exc}\n\n"
            f"Technical details have been saved to:\n{Path(LOG_PATH)}"
        )
        if getattr(sys, "frozen", False) or "--debug" not in sys.argv:
            _show_startup_error(f"{APP_NAME} — Startup Error", err_note)
        else:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
