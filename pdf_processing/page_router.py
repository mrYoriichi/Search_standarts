"""По-страничный роутер: чертёж или текстовая страница.

Признак чертежа — доминирование векторной геометрии (число PATH-объектов)
ЛИБО отсутствие извлекаемого текстового слоя. Опубликованные чертежи идут
либо тысячами векторных путей (текст сплющён в кривые), либо сканом без
текста — и то, и другое надо OCR-ить, а не резать по заголовкам.

Порог подобран на реальных страницах (замер 2026-07-18): проза даже со
встроенной схемой ≤ 575 путей, чертёж 3200–116000. Держим тестом.
"""

import pypdfium2 as pdfium

from pdf_processing.pdfium_lock import PDFIUM_LOCK

# Выше этого числа векторных путей страница считается чертёжной.
PATH_DOMINANT_THRESHOLD = 1000
# Меньше этого текста в слое — считаем, что извлекаемого текста нет (скан/кривые).
MIN_TEXT_LAYER_CHARS = 50

# Тип объекта Docling/pdfium: 2 = векторный путь (FPDF_PAGEOBJ_PATH).
_PATH_OBJ_TYPE = 2


def count_paths(page: "pdfium.PdfPage") -> int:
    """Число векторных путей на странице — мера «чертёжности» геометрии."""
    return sum(1 for obj in page.get_objects() if obj.type == _PATH_OBJ_TYPE)


def classify_page(path_count: int, text_len: int) -> str:
    """Тип страницы: 'drawing' (OCR) или 'text' (нарезка по заголовкам).

    Чертёж — если доминируют векторы ИЛИ нет извлекаемого текстового слоя.
    """
    if path_count > PATH_DOMINANT_THRESHOLD or text_len < MIN_TEXT_LAYER_CHARS:
        return "drawing"
    return "text"


def classify_pages(pdf_path: str) -> list[str]:
    """Тип каждой страницы PDF по порядку: список из 'drawing' | 'text'.

    Мост для пайплайна: считает пути и длину текстового слоя каждой
    страницы и прогоняет через classify_page.
    """
    with PDFIUM_LOCK:
        doc = pdfium.PdfDocument(pdf_path)
        try:
            result: list[str] = []
            for i in range(len(doc)):
                page = doc[i]
                text_len = len(page.get_textpage().get_text_range().strip())
                result.append(classify_page(count_paths(page), text_len))
            return result
        finally:
            doc.close()
