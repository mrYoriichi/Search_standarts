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
from sqlalchemy import select

from pathlib import Path

# Загружаем .env как можно раньше — до импорта сервисов, читающих env-vars.
load_dotenv()

from backend.core.database import Base, SessionLocal, engine
from backend.modules.auth import service as auth_service
from backend.modules.auth.deps import require_auth
from backend.modules.auth.models import AuthSession  # noqa: F401 — для create_all
from backend.modules.auth.router import router as auth_router
from backend.modules.telemetry import service as telemetry_service
from backend.modules.telemetry.models import PendingEvent  # noqa: F401 — для create_all
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
        # Ключ OpenAI из БД (если задан) кладём в окружение до первых LLM-вызовов.
        settings_service.apply_openai_key_to_env(db)

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
app.include_router(queries_router, prefix="/api", tags=["queries"], dependencies=protected)
app.include_router(documents_router, prefix="/api", tags=["documents"], dependencies=protected)
app.include_router(settings_router, prefix="/api", tags=["settings"], dependencies=protected)
app.include_router(library_router, prefix="/api", tags=["library"], dependencies=protected)
