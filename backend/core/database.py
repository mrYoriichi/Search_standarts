"""DB infrastructure: engine, model base class, session access."""

from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.core.paths import DB_PATH


def naive_utcnow() -> datetime:
    """Current UTC time without tzinfo — how SQLite DateTime columns store it.

    Replacement for the deprecated `datetime.utcnow()`: comparisons with
    naive dates from the DB keep working.
    """
    return datetime.now(UTC).replace(tzinfo=None)


# DB address. app.db location comes from core/paths (project root in dev,
# the OS user-data directory in the .exe so it survives updates).
DATABASE_URL = f"sqlite:///{DB_PATH}"


# One engine per app. check_same_thread=False is SQLite-specific: allow
# using the connection from different FastAPI threads.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Configure every new SQLite connection.

    WAL — readers do not block the writer (fewer "database is locked"
    errors with parallel document processing + telemetry).
    busy_timeout — wait up to 5 s for the DB instead of failing instantly.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


# Session factory; each SessionLocal() call creates a new session.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base class for all models."""


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: open a session per request, close after."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def ensure_columns() -> None:
    """Add missing columns to existing tables (idempotent).

    `Base.metadata.create_all` creates new tables but never alters
    existing ones. When a field is added to a table that already exists
    in a user's DB, it must arrive via ALTER TABLE. SQLite only supports
    ADD COLUMN — enough, since new fields are nullable. Runs at startup
    after create_all.
    """
    # {table: {column: type}} — the target shape; whatever is missing gets added.
    wanted: dict[str, dict[str, str]] = {
        "pending_reports": {
            "chunks": "JSON",  # F7: text of the used fragments
            "username": "VARCHAR",  # author of the report (NULL on old rows)
        },
        "documents": {
            # public-build page limit (NULL on old rows)
            "page_count": "INTEGER",
        },
        "project_documents": {
            "pinned": "BOOLEAN DEFAULT 0",  # archive pinning
            # PDF stat for replaced-file detection (NULL on old rows)
            "file_size": "INTEGER",
            "file_mtime": "FLOAT",
        },
    }
    with engine.begin() as conn:
        for table, columns in wanted.items():
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            existing = {row[1] for row in rows}  # row[1] is the column name
            if not existing:
                continue  # table absent — create_all builds it complete
            for name, col_type in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"
                    )
