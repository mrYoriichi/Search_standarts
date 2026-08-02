"""Where the app stores user data: the DB, indexes, settings.

Why: in the .exe the binary sits in Program Files (overwritten wholesale
on update), while user data must survive updates → it belongs in the
OS user-data directory. In dev (running from source) data stays in the
project root.

Single source of truth for paths. Every consumer (database, pipeline,
library) builds paths from DATA_DIR, never from the working directory.
"""

import os
import sys
from pathlib import Path

APP_NAME = "Search_standarts"


def _project_root() -> Path:
    """Repository root: backend/core/paths.py → ../../.."""
    return Path(__file__).resolve().parents[2]


def _system_user_data_dir() -> Path:
    """OS-specific application data directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    # Linux/other: XDG_DATA_HOME or ~/.local/share
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def _bundle_root() -> Path:
    """Root of the bundled resources (code, built frontend).

    In the .exe PyInstaller unpacks into the temp folder sys._MEIPASS.
    In dev it is the project root. Distinct from DATA_DIR: this side is
    read-only code/static, that side is writable user data.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _project_root()


def _resolve_data_dir() -> Path:
    """Data directory.

    Priority: explicit env var (set by the .exe launcher) → the system
    directory when frozen (PyInstaller sets sys.frozen) → the project
    root (dev).
    """
    env = os.environ.get("SEARCH_STANDARTS_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return _system_user_data_dir()
    return _project_root()


# Data directory and derived paths, computed once at import.
DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "app.db"
# CLI pipeline scripts (parse → describe → chunk → embed → ask): input and
# output. Source-run only — the app never looks here; its documents live
# in `<user folder>/.search_index/` and the archive pool.
CLI_PDF_DIR = DATA_DIR / "data" / "pdfs"
CLI_OUTPUT_DIR = DATA_DIR / "data" / "cli_output"
# Project-archive pool: per-slug indexes.
PROJECTS_DATA_DIR = DATA_DIR / "data" / "projects_data"

# Built frontend (Vite output; a bundled resource in the .exe).
FRONTEND_DIST = _bundle_root() / "frontend" / "dist"

# Pre-downloaded docling models (download_models.py → docling_models/).
# When present, the parser uses them and downloads nothing.
DOCLING_MODELS = _bundle_root() / "docling_models"

# Make sure the data directory exists (subfolders are created on demand).
DATA_DIR.mkdir(parents=True, exist_ok=True)
