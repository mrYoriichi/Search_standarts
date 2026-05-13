"""
Разбор PDF в структурированный JSON через Docling.

Главная функция: parse_pdf(pdf_path) — принимает путь к PDF,
возвращает Python-словарь по нашей схеме (document_id, document_name, pages).

Этот модуль НЕ знает, куда сохранять результат.
Сохранение — забота того, кто вызывает (main.py, веб-сервер и т.д.).
"""
import re
import unicodedata
from pathlib import Path

from docling.document_converter import DocumentConverter


# Таблица перевода: метка Docling -> наш внутренний тип блока.
# Если завтра захотим добавить новый тип — меняем только эту таблицу.
LABEL_MAP = {
    "text": "text",
    "paragraph": "text",
    "section_header": "heading",
    "title": "heading",
    "page_header": "header",
    "page_footer": "footer",
    "caption": "caption",
    "list_item": "list_item",
    "table": "table",
    "picture": "figure",
    "formula": "formula",
    "code": "code",
    "footnote": "footnote",
}


def make_document_id(filename: str) -> str:
    """
    Превращает имя файла в безопасный id для использования в путях и БД.
    'ČSN EN 1991-2.pdf' -> 'csn_en_1991_2'
    """
    stem = Path(filename).stem
    # Раскладываем буквы с диакритикой: Č -> C + ̌
    normalized = unicodedata.normalize("NFD", stem)
    # Выкидываем все «крышки» и «хвостики», остаётся чистая латиница
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    # Всё в нижний регистр, не-буквы/не-цифры заменяем на подчёркивание
    return re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")


def map_label(docling_label) -> str:
    """
    Переводит метку Docling в наш тип.
    Незнакомые метки возвращаем как есть, чтобы не терять информацию.
    """
    label_str = getattr(docling_label, "value", str(docling_label)).lower()
    return LABEL_MAP.get(label_str, label_str)


def extract_bbox(item) -> list | None:
    """Возвращает рамку блока [x1, y1, x2, y2] в виде целых чисел или None."""
    if not item.prov:
        return None
    bbox = item.prov[0].bbox
    return [round(bbox.l), round(bbox.t), round(bbox.r), round(bbox.b)]


def make_block(item, block_idx_on_page: int, page_num: int) -> dict:
    """
    Превращает один элемент Docling в наш словарь-блок.
    Для картинок возвращает расширенную структуру с полями
    под будущие шаги (caption, image_path, description).
    """
    block_type = map_label(item.label)
    block_id = f"p{page_num}_b{block_idx_on_page:02d}"
    bbox = extract_bbox(item)

    if block_type == "figure":
        return {
            "block_id": block_id,
            "type": "figure",
            "caption": None,        # позже свяжем с соседней подписью
            "image_path": None,     # позже впишем путь к картинке
            "description": None,    # позже впишет vision LLM
            "bbox": bbox,
        }

    return {
        "block_id": block_id,
        "type": block_type,
        "text": getattr(item, "text", None),
        "bbox": bbox,
    }


def build_document_dict(doc, pdf_filename: str) -> dict:
    """
    Собирает итоговый словарь документа по нашей JSON-схеме.
    """
    # Шаг 1: группируем блоки по страницам
    pages_dict: dict[int, list] = {}
    for item, _level in doc.iterate_items():
        if not item.prov:
            continue
        page_num = item.prov[0].page_no
        if page_num not in pages_dict:
            pages_dict[page_num] = []
        block_idx = len(pages_dict[page_num]) + 1
        pages_dict[page_num].append(make_block(item, block_idx, page_num))

    # Шаг 2: превращаем словарь в отсортированный список страниц
    pages_list = [
        {"page_number": page_num, "blocks": blocks}
        for page_num, blocks in sorted(pages_dict.items())
    ]

    return {
        "document_id": make_document_id(pdf_filename),
        "document_name": pdf_filename,
        "pages": pages_list,
    }


def parse_pdf(pdf_path: str) -> dict:
    """
    Главная функция модуля.
    Принимает путь к PDF, возвращает структурированный словарь документа.
    Не сохраняет ничего на диск.
    """
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    doc = result.document

    pdf_filename = Path(pdf_path).name
    return build_document_dict(doc, pdf_filename)