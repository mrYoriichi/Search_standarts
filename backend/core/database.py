"""БД-инфраструктура: engine, базовый класс моделей, доступ к сессии."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# Адрес БД. sqlite:/// — относительный путь от текущей рабочей директории.
# Файл app.db появится в корне проекта при первом подключении.
DATABASE_URL = "sqlite:///./app.db"


# Engine — связь с конкретной БД. Один на всё приложение.
# check_same_thread=False нужно только для SQLite: разрешаем использовать
# соединение из разных потоков FastAPI.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


# Фабрика сессий. Каждый вызов SessionLocal() создаёт новую сессию.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей. От него наследуются User, Company и т.д."""


def get_session() -> Generator[Session, None, None]:
    """Зависимость FastAPI: открыть сессию на запрос, закрыть после ответа."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
