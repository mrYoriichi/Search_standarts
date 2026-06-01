"""Предзагрузка моделей docling в папку проекта (для упаковки в дистрибутив).

Запускается ОДИН РАЗ при сборке (см. BUILD.md). Качает модели разбора PDF
в docling_models/, чтобы PyInstaller положил их внутрь .exe и у юзера ничего
не докачивалось из интернета (вариант 2 блока E).

    python download_models.py
"""
from pathlib import Path

from docling.utils.model_downloader import download_models

OUTPUT_DIR = Path("docling_models")


def main() -> None:
    print(f"Скачиваю модели docling в {OUTPUT_DIR.resolve()} ...")
    # Дефолтные флаги (layout + tableformer + rapidocr + code/picture) —
    # ровно то, что использует наш PDF-пайплайн.
    download_models(output_dir=OUTPUT_DIR, progress=True)
    print("Готово. Модели лежат в docling_models/")


if __name__ == "__main__":
    main()
