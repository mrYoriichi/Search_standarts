"""Лаунчер десктоп-приложения Search_standarts.

Точка входа для сборки в .exe (PyInstaller). Поднимает локальный FastAPI-сервер
и, когда он реально готов принимать соединения, открывает браузер на localhost.
В отличие от dev-запуска (`uvicorn --reload`) — без перезагрузки кода.
"""
import os
import socket
import threading
import time
import webbrowser

import uvicorn

from backend.app import app

HOST = "127.0.0.1"
PORT = 8000


def _wait_and_open_browser() -> None:
    """Ждёт, пока сервер начнёт принимать соединения, и открывает браузер.

    Опрашиваем порт, а не спим фиксированно: время старта (импорт docling/torch)
    плавает. SS_NO_BROWSER=1 — не открывать (для тестов/headless).
    """
    if os.environ.get("SS_NO_BROWSER") == "1":
        return
    url = f"http://{HOST}:{PORT}/"
    for _ in range(120):  # до ~60 секунд
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((HOST, PORT)) == 0:
                webbrowser.open(url)
                return
        time.sleep(0.5)


def main() -> None:
    threading.Thread(target=_wait_and_open_browser, daemon=True).start()
    # Передаём объект app (а не строку "backend.app:app") — в .exe нет исходников
    # для повторного импорта по имени модуля.
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
