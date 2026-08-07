"""Desktop launcher.

Entry point for the PyInstaller .exe build: starts the local FastAPI
server and opens the browser once the server actually accepts
connections. Unlike dev (`uvicorn --reload`) there is no code reload.
"""

import os
import sys

# In a console-less build (.exe, console=False) sys.stdout/stderr are None.
# uvicorn calls sys.stdout.isatty() on startup and the pipeline prints —
# both crash on None. Redirect output to a log file in the data directory
# (%APPDATA%\Search_standarts\app.log): no crash, logs stay available.
if sys.stdout is None or sys.stderr is None:
    from backend.core.paths import DATA_DIR

    _log_file = open(DATA_DIR / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file

import shutil
import socket
import subprocess
import threading
import time
import webbrowser

import uvicorn

from backend.app import app

HOST = "127.0.0.1"
PORT = 8000


def _find_edge() -> str | None:
    """Locate msedge.exe on Windows; None means "use the default browser"."""
    if sys.platform != "win32":
        return None
    for env_var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env_var)
        if base:
            path = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.isfile(path):
                return path
    return shutil.which("msedge")


def _open_app_window(url: str) -> None:
    """Open the UI in an Edge app window (no address bar/tabs) when available.

    Falls back to the default browser tab if Edge is missing or fails to
    start — the app must open no matter what.
    """
    edge = _find_edge()
    if edge:
        try:
            subprocess.Popen([edge, f"--app={url}"])
            return
        except OSError:
            pass
    webbrowser.open(url)


def _wait_and_open_browser() -> None:
    """Poll the port until the server accepts connections, then open the UI.

    Polling instead of a fixed sleep: startup time (docling/torch imports)
    varies. SS_NO_BROWSER=1 disables the browser (tests/headless).
    """
    if os.environ.get("SS_NO_BROWSER") == "1":
        return
    url = f"http://{HOST}:{PORT}/"
    for _ in range(120):  # up to ~60 seconds
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((HOST, PORT)) == 0:
                _open_app_window(url)
                return
        time.sleep(0.5)


def main() -> None:
    threading.Thread(target=_wait_and_open_browser, daemon=True).start()
    # Pass the app object, not the "backend.app:app" string: the .exe has no
    # source tree to re-import the module by name.
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
