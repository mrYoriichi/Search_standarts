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

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from pathlib import Path

# Загружаем .env как можно раньше — до импорта сервисов, читающих env-vars.
load_dotenv()

from backend.core import index_lock, index_store
from backend.core.database import Base, SessionLocal, engine, ensure_columns
from backend.core.paths import FRONTEND_DIST
from backend.modules.auth import service as auth_service
from backend.modules.auth.deps import require_auth
from backend.modules.auth.models import AuthSession  # noqa: F401 — для create_all
from backend.modules.auth.router import router as auth_router
from backend.modules.telemetry import service as telemetry_service
from backend.modules.telemetry.models import (  # noqa: F401 — для create_all
    PendingEvent,
    PendingReport,
)
from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline, run_pipeline_locked
from backend.modules.documents.router import router as documents_router
from backend.modules.health.router import router as health_router
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.pipeline import run_project_pipeline
from backend.modules.projects.router import router as projects_router
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
    # Дозаливаем недостающие колонки в таблицы, созданные прошлой версией.
    ensure_columns()

    # Бассейн из 3 потоков — параллельно обрабатываем максимум 3 PDF.
    # Остальные ждут в очереди executor'а.
    executor = ThreadPoolExecutor(max_workers=3)
    app.state.executor = executor

    # Возобновляем документы, которые остались processing после прошлого падения.
    # Если у документа есть relative_path — он добавлен через scan, PDF лежит
    # в папке библиотеки юзера. Иначе старый upload-flow, путь по умолчанию.
    db = SessionLocal()
    try:
        # Ключ OpenAI из БД (если задан) кладём в окружение до первых LLM-вызовов.
        settings_service.apply_openai_key_to_env(db)

        library_paths = [Path(p) for p in settings_service.get_library_paths(db)]
        stuck = db.scalars(
            select(Document).where(Document.status == "processing")
        ).all()
        for doc in stuck:
            if not doc.relative_path:
                # Легаси upload-flow: PDF в data/pdfs, артефакты в data/raw_data.
                executor.submit(run_pipeline, doc.slug, None, None)
                print(f"[startup] Возобновлён pipeline для {doc.slug}")
                continue
            folder = index_store.resolve_folder(library_paths, doc.slug)
            if folder is None:
                # Папка отключена или сетевой диск ещё не смонтирован — раньше
                # пайплайн уходил в легаси-путь и честный документ помечался
                # failed. Возвращаем в pending: доиндексируется кнопкой
                # «Indexovat», когда папка появится.
                doc.status = "pending"
                print(f"[startup] Папка {doc.slug} недоступна — вернул в pending")
                continue
            busy = index_lock.acquire(folder)
            if busy is not None:
                # Папку уже индексирует другая машина — параллельно не лезем.
                doc.status = "pending"
                print(f"[startup] {doc.slug}: папку индексирует {busy} — pending")
                continue
            index_lock.register(folder, 1)
            executor.submit(
                run_pipeline_locked,
                folder,
                doc.slug,
                str(folder / doc.relative_path),
                index_store.doc_dir(folder, doc.slug),
            )
            print(f"[startup] Возобновлён pipeline для {doc.slug}")
        db.commit()

        # То же для архива проектов: застрявшие в processing после падения.
        projects_paths = [Path(p) for p in settings_service.get_projects_paths(db)]
        if projects_paths:
            from backend.modules.projects import service as projects_service

            stuck_projects = db.scalars(
                select(ProjectDocument).where(ProjectDocument.status == "processing")
            ).all()
            for pdoc in stuck_projects:
                root = projects_service.resolve_project_root(
                    projects_paths, pdoc.relative_path
                )
                if root is None:
                    continue
                executor.submit(
                    run_project_pipeline,
                    pdoc.slug,
                    str(root / pdoc.relative_path),
                )
                print(f"[startup] Возобновлён pipeline архива для {pdoc.slug}")
    finally:
        db.close()

    # Фоновый verify лицензии раз в час (см. backend/modules/auth/service.py).
    # Отдельной задачей, чтобы не блокировать старт сервера.
    verify_task = asyncio.create_task(auth_service.run_verify_loop())

    # Фоновый отправщик телеметрии (см. backend/modules/telemetry/service.py).
    telemetry_task = asyncio.create_task(telemetry_service.run_telemetry_sender())

    # Событие старта приложения — складываем в локальную очередь, sender отправит
    # при первой возможности.
    telemetry_service.track_event("app_started")

    yield

    # Не ждём текущих обработок (они могут идти минуты), отменяем очередь.
    # Прерванные подхватятся при следующем старте.
    executor.shutdown(wait=False, cancel_futures=True)
    verify_task.cancel()
    telemetry_task.cancel()


app = FastAPI(title="Search_standarts API", lifespan=lifespan)

# /api/health и /api/auth/* — без require_auth (нужно где-то логиниться и пинговать).
# Остальные роутеры защищены: 401, если нет сессии или сессия в 'blocked'.
app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(auth_router, prefix="/api", tags=["auth"])

protected = [Depends(require_auth)]
app.include_router(
    queries_router, prefix="/api", tags=["queries"], dependencies=protected
)
app.include_router(
    documents_router, prefix="/api", tags=["documents"], dependencies=protected
)
app.include_router(
    settings_router, prefix="/api", tags=["settings"], dependencies=protected
)
app.include_router(
    library_router, prefix="/api", tags=["library"], dependencies=protected
)
app.include_router(
    projects_router, prefix="/api", tags=["projects"], dependencies=protected
)

# Собранный фронтенд отдаём с корня — ПОСЛЕ всех /api-роутеров (mount на "/" ловит
# всё остальное). html=True → index.html на "/". В dev без сборки папки нет —
# фронт берётся из Vite (dev-прокси на /api), поэтому монтируем только если есть.
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
