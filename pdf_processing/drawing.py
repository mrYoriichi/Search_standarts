"""Обработка чертёжной страницы без vision: текст = текстовый слой + OCR.

У опубликованных чертежей текстовый слой часто пуст (текст сплющён в кривые)
или частично битый (формуляр рамки) — OCR добирает то, чего в слое нет.
Оба источника склеиваем; чистку от дублей/шума пока не делаем (YAGNI,
померим на eval).
"""

import pypdfium2 as pdfium

# Длинная сторона рендера для OCR. 2200 px хватило на большом листе gama
# (проверено живьём); тот же размер, что в sheet-пайплайне архива.
RENDER_MAX_SIDE_PX = 2200


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

    layer = page.get_textpage().get_text_range().strip()
    width, height = page.get_size()
    scale = RENDER_MAX_SIDE_PX / max(width, height)
    image = page.render(scale=scale).to_pil()
    return build_drawing_text(layer, ocr_image(image))
