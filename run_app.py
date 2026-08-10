"""Desktop launcher.

Entry point for the PyInstaller .exe build: starts the local FastAPI
server and opens the browser once the server actually accepts
connections. Unlike dev (`uvicorn --reload`) there is no code reload.
"""

import os
import sys

from backend.core.log_time import TimestampWriter

# In a console-less build (.exe, console=False) sys.stdout/stderr are None.
# uvicorn calls sys.stdout.isatty() on startup and the pipeline prints —
# both crash on None. Redirect output to a log file in the data directory
# (%APPDATA%\Search_standarts\app.log): no crash, logs stay available.
if sys.stdout is None or sys.stderr is None:
    from backend.core.paths import DATA_DIR

    _log_file = TimestampWriter(
        open(DATA_DIR / "app.log", "a", encoding="utf-8", buffering=1)
    )
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


def server_already_running(port: int = PORT) -> bool:
    """True, если на порту уже слушает другой экземпляр приложения.

    С треем приложение живёт после закрытия окна; повторный клик по
    ярлыку не должен поднимать второй сервер (двойная память, гонки за
    БД, «порт занят») — вместо этого просто открываем окно к первому.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, port)) == 0


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


def _run_tray() -> None:
    """Иконка в трее (только Windows): «Otevřít» и «Ukončit».

    Блокируется до выбора «Ukončit» — pystray хочет главный поток.
    Импорты ленивые: на macOS/Linux пакета нет (маркер win32 в
    requirements.txt).
    """
    import pystray
    from PIL import Image, ImageDraw

    from backend.version import APP_VERSION

    # Иконку рисуем кодом — отдельного .ico файла в проекте нет.
    image = Image.new("RGB", (64, 64), (37, 99, 235))
    ImageDraw.Draw(image).text((32, 32), "M", fill="white", anchor="mm", font_size=40)

    def open_ui(icon: object, item: object) -> None:
        _open_app_window(f"http://{HOST}:{PORT}/")

    def quit_app(icon: "pystray.Icon", item: object) -> None:
        icon.stop()

    pystray.Icon(
        "asistent_mai",
        image,
        f"Asistent MAI {APP_VERSION}",
        menu=pystray.Menu(
            pystray.MenuItem("Otevřít", open_ui, default=True),
            pystray.MenuItem("Ukončit", quit_app),
        ),
    ).run()


def main() -> None:
    if server_already_running():
        # Приложение уже работает (в трее) — не запускаем второй
        # экземпляр, только показываем его окно.
        _open_app_window(f"http://{HOST}:{PORT}/")
        return

    threading.Thread(target=_wait_and_open_browser, daemon=True).start()
    # Server-объект вместо uvicorn.run(): нужен should_exit для выхода из трея.
    # Pass the app object, not the "backend.app:app" string: the .exe has no
    # source tree to re-import the module by name.
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="info"))
    if sys.platform == "win32":
        # Сервер — в фоновом потоке, трей — в главном. После «Ukončit» выход
        # жёсткий: потоки индексации не daemon и могут крутиться часами, а
        # недоделанный документ докрутит crash-resume при следующем запуске.
        threading.Thread(target=server.run, daemon=True).start()
        _run_tray()
        server.should_exit = True
        time.sleep(1)
        os._exit(0)
    else:
        server.run()


if __name__ == "__main__":
    main()
