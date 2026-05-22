"""
Health-check эндпоинт.

Возвращает {"status": "ok"} — простая проверка живости сервера.
Используется чтобы убедиться, что FastAPI и роутинг работают,
до подключения реальных модулей.
"""
from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Простая проверка живости backend."""
    return {"status": "ok"}
