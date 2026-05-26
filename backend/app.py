"""
Точка входа web-приложения Search_standarts.

Создаёт FastAPI-приложение и подключает роутеры из всех модулей.
Структура кода — по модулям (см. VISION.md, принцип «Модульная структура»).

Запуск (из корня проекта):
    uvicorn backend.app:app --reload

После запуска:
  - http://localhost:8000/api/health  — проверка живости
  - http://localhost:8000/docs        — авто-документация (Swagger UI)
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from pathlib import Path

from backend.core.database import Base, SessionLocal, engine
from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline
from backend.modules.documents.router import router as documents_router
from backend.modules.health.router import router as health_router
from backend.modules.library.router import router as library_router
from backend.modules.queries.router import router as queries_router
from backend.modules.settings import service as settings_service
from backend.modules.settings.models import Setting  # noqa: F401 — для create_all
from backend.modules.settings.router import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Старт/остановка приложения: БД, пул потоков, возобновление задач."""
    # Страховка для чистой машины: создаст таблицы, если их ещё нет.
    Base.metadata.create_all(engine)

    # Бассейн из 3 потоков — параллельно обрабатываем максимум 3 PDF.
    # Остальные ждут в очереди executor'а.
    executor = ThreadPoolExecutor(max_workers=3)
    app.state.executor = executor

    # Возобновляем документы, которые остались processing после прошлого падения.
    # Если у документа есть relative_path — он добавлен через scan, PDF лежит
    # в папке библиотеки юзера. Иначе старый upload-flow, путь по умолчанию.
    db = SessionLocal()
    try:
        library_path = settings_service.get_library_path(db)
        stuck = db.scalars(
            select(Document).where(Document.status == "processing")
        ).all()
        for doc in stuck:
            pdf_path: str | None = None
            if doc.relative_path and library_path:
                pdf_path = str(Path(library_path) / doc.relative_path)
            executor.submit(run_pipeline, doc.slug, pdf_path)
            print(f"[startup] Возобновлён pipeline для {doc.slug}")
    finally:
        db.close()

    yield

    # Не ждём текущих обработок (они могут идти минуты), отменяем очередь.
    # Прерванные подхватятся при следующем старте.
    executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Search_standarts API", lifespan=lifespan)

# Префикс /api отделяет API от будущей статики/SPA, чтобы Nginx
# или сам FastAPI могли отдавать React-приложение на /
app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(queries_router, prefix="/api", tags=["queries"])
app.include_router(documents_router, prefix="/api", tags=["documents"])
app.include_router(settings_router, prefix="/api", tags=["settings"])
app.include_router(library_router, prefix="/api", tags=["library"])
