"""Сервис телеметрии: складываем события в очередь, фоновая корутина их отправляет.

Главный публичный API:
- `track_event(name, **props)` — кладёт событие в pending_events. Дёшево, безопасно.
- `run_telemetry_sender()` — фоновый цикл, запускается в lifespan.

Принципы:
- Если юзер не залогинен — не отправляем. События копятся.
- Если сервер недоступен — не удаляем из очереди. Попробуем в следующий раз.
- Если сервер вернул 200 — удаляем отправленные ровно по id.
- Поломка отправки не должна ронять основной процесс (вокруг tracker и sender — try/except).
"""

import asyncio
from typing import Any

import httpx
from sqlalchemy import select

from backend.core.database import SessionLocal
from backend.modules.auth.models import AuthSession
from backend.modules.auth.service import (
    HTTP_TIMEOUT,
    LICENSE_SERVER_URL,
    VERSION_HEADERS,
)
from backend.modules.telemetry.models import PendingEvent, PendingReport


# Шлём раз в минуту. Чаще — лишний трафик, реже — отчёты «слепые» дольше.
SEND_INTERVAL_SECONDS = 60

# Максимум в одном батче. Берём с запасом — обычно событий не накапливается много.
BATCH_LIMIT = 100


def track_event(name: str, **props: Any) -> None:
    """Кладёт событие в локальную очередь.

    Любые проблемы (БД, диск) глотаются: телеметрия НЕ должна ронять приложение.
    """
    try:
        db = SessionLocal()
        try:
            db.add(PendingEvent(name=name, props=props or None))
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[telemetry] track_event({name}) failed: {exc}")


def track_report(
    question: str,
    answer: str,
    answer_model: str | None = None,
    note: str | None = None,
    chunks: list[dict] | None = None,
) -> None:
    """Кладёт помеченный ответ («Nahlásit») в очередь отчётов (F7).

    Вызывается по явному действию юзера (кнопка под ответом), поэтому согласие
    не проверяем — сам клик и есть согласие. chunks — использованные фрагменты с
    текстом. Ошибки глотаем, как в track_event.
    """
    try:
        db = SessionLocal()
        try:
            db.add(
                PendingReport(
                    question=question,
                    answer=answer,
                    answer_model=answer_model,
                    note=note,
                    chunks=chunks or None,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[telemetry] track_report failed: {exc}")


def _post_batch(endpoint: str, body: dict, token: str) -> bool:
    """POST батча на сервер лицензий. True — сервер принял (200), очередь чистим.

    На не-200 / сетевую ошибку возвращаем False: батч остаётся в очереди до
    следующего тика. 401 (токен), 426 (устарел), 5xx — стратегия одна.
    """
    headers = {"Authorization": f"Bearer {token}", **VERSION_HEADERS}
    try:
        response = httpx.post(
            f"{LICENSE_SERVER_URL}{endpoint}",
            json=body,
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        print(f"[telemetry] network error on {endpoint}: {exc}")
        return False
    if response.status_code != 200:
        print(f"[telemetry] {endpoint} returned {response.status_code}, keeping batch")
        return False
    return True


def send_pending_batch() -> int:
    """Шлёт один батч анонимных событий (Уровень 1). Возвращает число отправленных.

    Если юзер не залогинен — возвращает 0. Если сервер ответил не-200 —
    оставляет события в очереди.
    """
    db = SessionLocal()
    try:
        session = db.get(AuthSession, 1)
        if session is None:
            return 0  # некому слать — пользователь не залогинен

        rows = db.scalars(
            select(PendingEvent).order_by(PendingEvent.id).limit(BATCH_LIMIT)
        ).all()
        if not rows:
            return 0

        body = {
            "events": [
                {
                    "name": row.name,
                    "props": row.props or {},
                    "client_timestamp": row.client_timestamp.isoformat(),
                }
                for row in rows
            ]
        }
        if not _post_batch("/telemetry/events", body, session.token):
            return 0

        ids = [row.id for row in rows]
        db.query(PendingEvent).filter(PendingEvent.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.commit()
        return len(ids)
    finally:
        db.close()


def send_pending_report_batch() -> int:
    """Шлёт один батч помеченных ответов (F7). Возвращает число отправленных.

    Поведение как у send_pending_batch, но эндпоинт /telemetry/flagged и текст q/a.
    """
    db = SessionLocal()
    try:
        session = db.get(AuthSession, 1)
        if session is None:
            return 0

        rows = db.scalars(
            select(PendingReport).order_by(PendingReport.id).limit(BATCH_LIMIT)
        ).all()
        if not rows:
            return 0

        body = {
            "events": [
                {
                    "question": row.question,
                    "answer": row.answer,
                    "answer_model": row.answer_model,
                    "note": row.note,
                    "chunks": row.chunks or [],
                    "client_timestamp": row.client_timestamp.isoformat(),
                }
                for row in rows
            ]
        }
        if not _post_batch("/telemetry/flagged", body, session.token):
            return 0

        ids = [row.id for row in rows]
        db.query(PendingReport).filter(PendingReport.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.commit()
        return len(ids)
    finally:
        db.close()


async def run_telemetry_sender() -> None:
    """Фоновая корутина: раз в минуту шлёт события и помеченные ответы."""
    while True:
        try:
            await asyncio.to_thread(send_pending_batch)
            await asyncio.to_thread(send_pending_report_batch)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[telemetry] sender error: {exc}")
        await asyncio.sleep(SEND_INTERVAL_SECONDS)
