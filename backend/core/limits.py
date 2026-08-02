"""Лимит объёма публичной сборки: 3000 страниц (решение 2026-08-02).

Причина — оперативная память: кеш поиска грузит ВСЕ готовые индексы целиком
(замер 2026-08-02: пик ~140 КБ RAM на чанк при загрузке; 3000 страниц ≈ пик
~630 МБ — безопасно даже на ноутбуке с 8 ГБ). Заодно защищает кошелёк юзера
от случайной индексации сотен страниц (vision платный).

Считаются страницы обеих таблиц (библиотека + архив) в статусах ready и
processing, ВКЛЮЧАЯ усыновлённые индексы: памяти всё равно, кто платил.
В пилотной сборке (PUBLIC_BUILD=False) лимита нет.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.modules.documents.models import Document
from backend.modules.projects.models import ProjectDocument
from backend.version import PUBLIC_BUILD

PAGE_LIMIT = 3000


def pages_in_use(db: Session) -> int:
    """Сколько страниц уже занято готовыми и обрабатываемыми документами.

    processing считаем тоже: документ уже отправлен в пайплайн и станет
    ready — иначе два клика «Indexovat» подряд обходили бы лимит.
    NULL page_count (легаси-строки до появления счётчика) считается за 0.
    """
    statuses = ("ready", "processing")
    library = db.scalar(
        select(func.coalesce(func.sum(Document.page_count), 0)).where(
            Document.status.in_(statuses)
        )
    )
    archive = db.scalar(
        select(func.coalesce(func.sum(ProjectDocument.page_count), 0)).where(
            ProjectDocument.status.in_(statuses)
        )
    )
    return int(library) + int(archive)


def pages_remaining(db: Session) -> int | None:
    """Остаток лимита в страницах; None — лимита нет (пилотная сборка)."""
    if not PUBLIC_BUILD:
        return None
    return max(0, PAGE_LIMIT - pages_in_use(db))
