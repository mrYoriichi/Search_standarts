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
from fastapi import FastAPI

from backend.modules.documents.router import router as documents_router
from backend.modules.health.router import router as health_router
from backend.modules.queries.router import router as queries_router


app = FastAPI(title="Search_standarts API")

# Префикс /api отделяет API от будущей статики/SPA, чтобы Nginx
# или сам FastAPI могли отдавать React-приложение на /
app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(queries_router, prefix="/api", tags=["queries"])
app.include_router(documents_router, prefix="/api", tags=["documents"])
