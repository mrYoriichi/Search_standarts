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


def route_and_ocr(document: dict, pdf_path: str) -> None:
    """Проставляет тип каждой странице document и OCR-текст чертёжным (на месте).

    Идём по РЕАЛЬНЫМ страницам PDF (pypdfium — источник истины: Docling может
    пропустить чисто-векторную страницу-чертёж). Прозаической ставим
    page_type='text' и оставляем разбор Docling; чертёжной — page_type='drawing'
    + drawing_text (OCR + текстовый слой), блоки пустые (чанк соберём отдельно).
    Прозаические страницы, которых Docling не нашёл, пропускаем (пустые).
    """
    import pypdfium2 as pdfium

    from pdf_processing.page_router import classify_page, count_paths

    docling_pages = {p["page_number"]: p for p in document["pages"]}
    doc = pdfium.PdfDocument(pdf_path)
    try:
        routed: list[dict] = []
        for i in range(len(doc)):
            page_number = i + 1
            page = doc[i]
            text_len = len(page.get_textpage().get_text_range().strip())
            page_type = classify_page(count_paths(page), text_len)

            if page_type == "drawing":
                drawing_text = read_drawing_page(page)
                routed.append(
                    {
                        "page_number": page_number,
                        "page_text": drawing_text,
                        "page_type": "drawing",
                        "drawing_text": drawing_text,
                        "blocks": [],
                    }
                )
            else:
                docling_page = docling_pages.get(page_number)
                if docling_page is None:
                    continue  # Docling ничего не нашёл — пустая страница, пропуск
                docling_page["page_type"] = "text"
                routed.append(docling_page)
        document["pages"] = routed
    finally:
        doc.close()
