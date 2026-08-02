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

import socket
import threading
import time
import webbrowser

import uvicorn

from backend.app import app

HOST = "127.0.0.1"
PORT = 8000


def _wait_and_open_browser() -> None:
    """Poll the port until the server accepts connections, then open the browser.

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
                webbrowser.open(url)
                return
        time.sleep(0.5)


def main() -> None:
    threading.Thread(target=_wait_and_open_browser, daemon=True).start()
    # Pass the app object, not the "backend.app:app" string: the .exe has no
    # source tree to re-import the module by name.
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
