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
from backend.modules.telemetry.models import PendingEvent


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


def send_pending_batch() -> int:
    """Шлёт один батч событий. Возвращает число отправленных.

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
        headers = {
            "Authorization": f"Bearer {session.token}",
            **VERSION_HEADERS,
        }
        try:
            response = httpx.post(
                f"{LICENSE_SERVER_URL}/telemetry/events",
                json=body,
                headers=headers,
                timeout=HTTP_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            print(f"[telemetry] network error: {exc}")
            return 0

        if response.status_code != 200:
            # 401 — токен битый (юзер перелогинится → новый токен → отправим).
            # 426 — клиент устарел (verify_loop переведёт в blocked).
            # 5xx — сервер. Везде стратегия одна: оставляем в очереди.
            print(
                f"[telemetry] server returned {response.status_code}, keeping batch"
            )
            return 0

        ids = [row.id for row in rows]
        db.query(PendingEvent).filter(PendingEvent.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.commit()
        return len(ids)
    finally:
        db.close()


async def run_telemetry_sender() -> None:
    """Фоновая корутина: раз в минуту шлёт накопившиеся события."""
    while True:
        try:
            await asyncio.to_thread(send_pending_batch)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[telemetry] sender error: {exc}")
        await asyncio.sleep(SEND_INTERVAL_SECONDS)
