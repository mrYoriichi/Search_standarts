"""Обработка чертёжной страницы без vision: текст = текстовый слой + OCR.

У опубликованных чертежей текстовый слой часто пуст (текст сплющён в кривые)
или частично битый (формуляр рамки) — OCR добирает то, чего в слое нет.
Оба источника склеиваем; чистку от дублей/шума пока не делаем (YAGNI,
померим на eval).
"""

import re

import pypdfium2 as pdfium

from pdf_processing.pdfium_lock import PDFIUM_LOCK

# Длинная сторона рендера для OCR. 2200 px хватило на большом листе gama
# (проверено живьём); тот же размер, что в sheet-пайплайне архива.
RENDER_MAX_SIDE_PX = 2200

# Известные ступени проектной документации (чешские). Длинные коды впереди,
# чтобы «DSPS» не срабатывал как «DSP». Штамп чертежа пишет ступень дословно,
# поэтому ищем готовое слово в тексте листа, а не гадаем по картинке (vision
# путает ступень с соседними кодами вроде D.2.1.4).
_STUPEN_CODES = (
    "DSPS",
    "PDPS",
    "DÚR",
    "DUR",
    "DSP",
    "DPS",
    "RDS",
    "DVZ",
    "ZDS",
    "DZS",
    "DOS",
)
_STUPEN_RE = re.compile(r"\b(" + "|".join(_STUPEN_CODES) + r")\b")


def extract_stupen(text: str) -> str:
    """Ступень проектной документации из текста листа (текстовый слой + OCR).

    Возвращает первый найденный код (DSP, DÚR, PDPS…) как целое слово или "".
    Штамп пишет ступень буквами — берём готовое слово, не угадываем по картинке.
    """
    match = _STUPEN_RE.search(text)
    return match.group(1) if match else ""


def build_drawing_text(layer_text: str, ocr_text: str) -> str:
    """Текст чанка чертёжной страницы из текстового слоя PDF и OCR.

    Непустые источники склеиваем через пустую строку; оба пустые → "".
    """
    parts = [p.strip() for p in (layer_text, ocr_text) if p and p.strip()]
    return "\n\n".join(parts)


def read_drawing_page(page: "pdfium.PdfPage") -> str:
    """Полный текст чертёжной страницы: текстовый слой + OCR рендера."""
    # Импорт здесь — OCR-движок тяжёлый, не грузим при импорте модуля.
    from pdf_processing.ocr import ocr_image

    with PDFIUM_LOCK:
        layer = page.get_textpage().get_text_range().strip()
        width, height = page.get_size()
        scale = RENDER_MAX_SIDE_PX / max(width, height)
        image = page.render(scale=scale).to_pil()
    # OCR — вне замка: он медленный и pdfium не трогает.
    return build_drawing_text(layer, ocr_image(image))


def insert_drawing_pages(document: dict, pdf_path: str, page_types: list[str]) -> None:
    """Вставляет чертёжные страницы (OCR) в document на их места по номеру.

    Прозаические страницы уже разобраны Docling и лежат в document. Чертёжные
    Docling не видел — читаем их OCR'ом здесь и собираем итоговый список страниц
    в правильном порядке (проза + чертежи). Прозаические страницы, которых
    Docling не нашёл (пустые), пропускаем.
    """
    import pypdfium2 as pdfium

    prose_pages = {p["page_number"]: p for p in document["pages"]}
    for page in document["pages"]:
        page["page_type"] = "text"

    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_path)
    try:
        pages: list[dict] = []
        for i, page_type in enumerate(page_types):
            page_number = i + 1
            if page_type == "drawing":
                with PDFIUM_LOCK:
                    pdf_page = doc[i]
                drawing_text = read_drawing_page(pdf_page)
                pages.append(
                    {
                        "page_number": page_number,
                        "page_text": drawing_text,
                        "page_type": "drawing",
                        "drawing_text": drawing_text,
                        "blocks": [],
                    }
                )
            elif page_number in prose_pages:
                pages.append(prose_pages[page_number])
        document["pages"] = pages
    finally:
        with PDFIUM_LOCK:
            doc.close()
