"""БД-инфраструктура: engine, базовый класс моделей, доступ к сессии."""

from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.core.paths import DB_PATH


def naive_utcnow() -> datetime:
    """Текущее время UTC без tzinfo — как хранят колонки DateTime в SQLite.

    Замена deprecated `datetime.utcnow()`: сравнения с наивными датами из БД
    продолжают работать.
    """
    return datetime.now(UTC).replace(tzinfo=None)


# Адрес БД. Путь к файлу app.db даёт core/paths (в dev — корень проекта,
# в .exe — системный user-data каталог, чтобы пережить обновление).
DATABASE_URL = f"sqlite:///{DB_PATH}"


# Engine — связь с конкретной БД. Один на всё приложение.
# check_same_thread=False нужно только для SQLite: разрешаем использовать
# соединение из разных потоков FastAPI.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Настраивает каждое новое соединение с SQLite.

    WAL — читатели не блокируют писателя (меньше ошибок «database is locked»
    при параллельной обработке документов + телеметрии).
    busy_timeout — ждать до 5 сек, пока база освободится, вместо мгновенного падения.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


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


def ensure_columns() -> None:
    """Дозаливает недостающие колонки в существующие таблицы (idempotent).

    `Base.metadata.create_all` создаёт новые таблицы, но НЕ меняет существующие.
    Когда добавляем поле в уже созданную таблицу (у юзера БД с прошлой версии),
    его нужно долить через ALTER TABLE. SQLite поддерживает только ADD COLUMN —
    хватает (новые поля nullable). Запускается на старте после create_all.
    """
    # {таблица: {колонка: тип}} — что должно быть. Чего нет — добавим.
    wanted: dict[str, dict[str, str]] = {
        "pending_reports": {"chunks": "JSON"},  # F7: текст использованных фрагментов
        "project_documents": {
            "pinned": "BOOLEAN DEFAULT 0",  # закрепление в архиве
            # stat PDF для детекта замены файла (NULL у старых строк)
            "file_size": "INTEGER",
            "file_mtime": "FLOAT",
        },
    }
    with engine.begin() as conn:
        for table, columns in wanted.items():
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            existing = {row[1] for row in rows}  # row[1] — имя колонки
            if not existing:
                continue  # таблицы ещё нет — create_all создаст её сразу с полями
            for name, col_type in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"
                    )
