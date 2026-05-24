"""Сидер: создаёт записи Document в БД по содержимому data/raw_data/.

Временное решение до C1 (загрузка PDF через UI). Сейчас документы уже лежат
на диске, обработаны пайплайном — но в БД о них ничего нет. Этот скрипт
сканирует data/raw_data/, для каждой готовой папки создаёт запись Document
с title из descriptions.json и status='ready'.

Идемпотентный: повторный запуск ничего не дублирует, просто пропускает
уже существующие slug'и.

Запуск (из корня проекта):
    python -m backend.scripts.seed_from_disk
"""

import json
from pathlib import Path

from sqlalchemy import select

from backend.core.database import Base, SessionLocal, engine
from backend.modules.documents.models import Document


DATA_ROOT = Path("data/raw_data")


def seed() -> None:
    """Создаёт записи Document для каждой готовой папки в data/raw_data/."""
    # На случай первого запуска до того, как FastAPI поднимался —
    # убедимся, что таблицы созданы.
    Base.metadata.create_all(engine)

    db = SessionLocal()
    try:
        added = 0
        skipped = 0
        for doc_dir in sorted(DATA_ROOT.iterdir()):
            if not doc_dir.is_dir():
                continue

            slug = doc_dir.name
            descriptions_path = doc_dir / "descriptions.json"
            if not descriptions_path.exists():
                print(f"  [skip] {slug} — нет descriptions.json")
                continue

            # Уже есть в БД?
            existing = db.scalar(select(Document).where(Document.slug == slug))
            if existing is not None:
                print(f"  [exists] {slug}")
                skipped += 1
                continue

            with open(descriptions_path, encoding="utf-8") as f:
                desc = json.load(f)
            title = desc.get("document_title") or slug

            doc = Document(slug=slug, title=title, status="ready")
            db.add(doc)
            print(f"  [add]  {slug} — {title}")
            added += 1

        db.commit()
        print(f"\nГотово. Добавлено: {added}, уже было: {skipped}.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
