"""Защита от второго экземпляра приложения.

С треем приложение живёт после закрытия окна; повторный клик по ярлыку
не должен запускать второй сервер (гонки за БД, двойная память,
«порт занят»). Если порт уже слушается — только открыть окно и выйти.
"""

import socket

import run_app


def test_detects_running_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert run_app.server_already_running(port) is True


def test_free_port_means_not_running():
    # Порт берём и сразу освобождаем — на нём никто не слушает.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
    assert run_app.server_already_running(port) is False


def test_main_opens_window_and_exits_when_running(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(run_app, "server_already_running", lambda port=None: True)
    monkeypatch.setattr(run_app, "_open_app_window", lambda url: opened.append(url))
    monkeypatch.setattr(
        run_app.uvicorn,
        "Server",
        lambda config: (_ for _ in ()).throw(AssertionError("server must not start")),
    )

    run_app.main()

    assert opened == [f"http://{run_app.HOST}:{run_app.PORT}/"]


def test_parse_worker_flag_runs_worker_not_app(monkeypatch):
    # exe, запущенный спавнером с --parse-worker, — это воркер parse:
    # ни проверки порта, ни сервера, ни окна.
    import pipeline.parse_worker

    called: list[str] = []
    monkeypatch.setattr(run_app.sys, "argv", ["run_app.py", "--parse-worker"])
    monkeypatch.setattr(pipeline.parse_worker, "main", lambda: called.append("worker"))
    monkeypatch.setattr(
        run_app,
        "server_already_running",
        lambda port=None: (_ for _ in ()).throw(AssertionError("must not check port")),
    )

    run_app.main()

    assert called == ["worker"]
