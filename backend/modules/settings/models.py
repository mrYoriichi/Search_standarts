"""Модель Setting — простое key-value хранилище для настроек приложения.

Сейчас хранит только library_path. В будущем сюда же положим OpenAI-ключ,
выбранные модели и т.п.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
