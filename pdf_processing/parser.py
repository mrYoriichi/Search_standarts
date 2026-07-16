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

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from backend.core.paths import DOCLING_MODELS


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

# Типы блоков, текст которых используется для построения page_text.
TEXT_BLOCK_TYPES = {
    "text",
    "heading",
    "header",
    "footer",
    "caption",
    "list_item",
    "footnote",
}


# Типы блоков, для которых нужны скриншоты страниц (для будущей vision LLM).
VISUAL_BLOCK_TYPES = {"figure", "table"}


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


# Шаблон для номера раздела в начале заголовка: "7", "7.12", "7.12.5"
SECTION_NUMBER_PATTERN = re.compile(r"^(\d+(?:\.\d+)*)")


def parse_heading_number(text: str) -> tuple[str | None, int | None]:
    """
    Извлекает номер раздела и его уровень из текста заголовка.

    Примеры:
      "7  Konstrukční zásady"  -> ("7", 1)
      "7.12  Zábradlí"         -> ("7.12", 2)
      "7.12.5  Vzdálenost..."  -> ("7.12.5", 3)
      "Seznam zkratek"         -> (None, None)   # без номера

    Возвращает кортеж (номер_раздела, уровень).
    Если номер не найден — (None, None).
    """
    if not text:
        return None, None

    # Ищем номер в самом начале строки
    match = SECTION_NUMBER_PATTERN.match(text.strip())
    if not match:
        return None, None

    section_number = match.group(1)
    # Уровень = количество точек + 1. "7" -> 0 точек -> уровень 1.
    level = section_number.count(".") + 1
    return section_number, level


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

    if block_type in VISUAL_BLOCK_TYPES:
        return {
            "block_id": block_id,
            "type": block_type,
            "bbox": bbox,
            "page_image_path": None,
            "prev_page": None,
            "next_page": None,
            "description": None,
        }

    # Обычный текстовый блок
    block = {
        "block_id": block_id,
        "type": block_type,
        "text": getattr(item, "text", None),
        "bbox": bbox,
    }

    # Для заголовков дополнительно определяем номер раздела и уровень
    if block_type == "heading":
        section_number, level = parse_heading_number(block["text"] or "")
        block["section_number"] = section_number
        block["level"] = level

    return block


def build_page_text(blocks: list[dict]) -> str:
    """
    Склеивает текст всех текстовых блоков страницы в одну строку.
    Используется как контекст для vision LLM при описании соседних страниц.
    Пустые блоки и блоки без поля text пропускаем.
    """
    pieces = []
    for block in blocks:
        if block["type"] not in TEXT_BLOCK_TYPES:
            continue
        text = block.get("text")
        if text:
            pieces.append(text.strip())
    # Сцепляем через двойной перевод строки — чтобы границы блоков были видны
    return "\n\n".join(pieces)


def enrich_visual_blocks(document: dict, pages_to_save: set[int]) -> None:
    """
    Дозаполняет поля у блоков figure/table:
      - page_image_path — путь к скриншоту страницы (если её сохраняем);
      - prev_page, next_page — номера соседних страниц (или None на границах).

    Меняет document на месте (in-place). Ничего не возвращает.
    """
    # Все существующие номера страниц — чтобы понять, есть ли сосед
    all_page_numbers = {p["page_number"] for p in document["pages"]}

    for page in document["pages"]:
        page_num = page["page_number"]
        for block in page["blocks"]:
            if block["type"] not in VISUAL_BLOCK_TYPES:
                continue

            # Путь к скриншоту — относительный, от папки документа
            if page_num in pages_to_save:
                block["page_image_path"] = f"pages/p{page_num:03d}.png"

            # Номера соседних страниц, если они есть в документе
            prev_num = page_num - 1
            next_num = page_num + 1
            if prev_num in all_page_numbers:
                block["prev_page"] = prev_num
            if next_num in all_page_numbers:
                block["next_page"] = next_num


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

    # Шаг 2: превращаем словарь в отсортированный список страниц.
    # Для каждой страницы заодно строим page_text — сцепленный текст.
    pages_list = [
        {
            "page_number": page_num,
            "page_text": build_page_text(blocks),
            "blocks": blocks,
        }
        for page_num, blocks in sorted(pages_dict.items())
    ]

    return {
        "document_id": make_document_id(pdf_filename),
        "document_name": pdf_filename,
        "pages": pages_list,
    }


def collect_pages_to_save(document: dict) -> set[int]:
    """
    Возвращает множество номеров страниц, которые нужно сохранить как PNG.

    Сохраняем только страницы, содержащие figure или table.
    Текстовый контекст соседних страниц берётся отдельно
    (из поля page_text в JSON) при отправке в vision LLM.
    """
    pages = document["pages"]
    # Множество всех существующих номеров страниц — чтобы не добавлять
    # «соседей», которых на самом деле нет (за пределами документа).

    pages_to_save: set[int] = set()

    for page in pages:
        # Есть ли на странице блок типа figure или table?
        has_visual = any(
            block["type"] in VISUAL_BLOCK_TYPES for block in page["blocks"]
        )
        if not has_visual:
            continue

        # Сохраняем только саму страницу с figure/table.
        # Текстовый контекст соседей будет вытаскиваться из JSON-поля page_text
        # при отправке в vision LLM.
        pages_to_save.add(page["page_number"])

    return pages_to_save


def parse_pdf(pdf_path: str) -> tuple[dict, dict]:
    """
    Главная функция модуля.
    Принимает путь к PDF.
    Возвращает кортеж из двух элементов:
      1. document — структурированный словарь документа.
      2. page_images — словарь {номер_страницы: PIL.Image} с картинками всех страниц.

    Сохранением на диск занимается тот, кто вызывает (main.py).
    """
    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_page_images = True
    pipeline_options.images_scale = 2.0
    # Если модели предзагружены в docling_models/ (сборка .exe) — берём их оттуда,
    # docling ничего не качает. Иначе путь не задан → старое поведение (докачка).
    if DOCLING_MODELS.exists():
        pipeline_options.artifacts_path = str(DOCLING_MODELS)
    # MPS (Apple Silicon GPU) не поддерживает float64, на котором работают
    # модели Docling (RT-DETR). Принудительно используем CPU.
    pipeline_options.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CPU
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    result = converter.convert(pdf_path)
    doc = result.document

    # Собираем картинки всех страниц в обычный словарь {page_no: PIL.Image}.
    # Так удобнее работать дальше: парсер не «утечёт» в чужой код объектами Docling.
    page_images = {}
    for page_num, page in doc.pages.items():
        if page.image and page.image.pil_image:
            page_images[page_num] = page.image.pil_image

    pdf_filename = Path(pdf_path).name
    document = build_document_dict(doc, pdf_filename)

    return document, page_images
